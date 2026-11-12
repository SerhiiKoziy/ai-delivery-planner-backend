"""Build the AI mock-interview page from the question bank.

    python3 docs/interview-ai/_src/build.py

Outputs (next to _src/):
  01-python-databases.html — the tutorial page (human view + context builder)
  01-python-databases.md   — the full AI context: prompt + whole bank
The bank lives in bank_python_db.py + bank_system_design.py, the interviewer prompt in prompt.md.
"""
import html
import json
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
OUT = SRC.parent
DOCS = OUT.parent
sys.path.insert(0, str(SRC))
import bank_python_db as _py  # noqa: E402
import bank_system_design as _sd  # noqa: E402

# Python + DB topics, Redis joins the DB topic, System Design is its own topic.
TOPICS = [dict(t, groups=list(t["groups"])) for t in _py.TOPICS]
next(t for t in TOPICS if t["id"] == "db")["groups"].append(_sd.REDIS_GROUP)
TOPICS.append(_sd.SD_TOPIC)
DRILLS = _py.DRILLS + _sd.DRILLS

SLUG = "01-python-databases"
LVL_NAME = {"J": "Junior", "M": "Middle", "S": "Senior"}
LVL_CLS = {"J": "l1", "M": "l2", "S": "l3"}
esc = html.escape

# ---------- tutorial links: "06#s1" -> file, page title, section title ----------
TUT = {}
TUT_DIRS = {"": "python-tutorials", "sd": "system-design"}
for prefix, folder in TUT_DIRS.items():
    for f in sorted((DOCS / folder).glob("[0-9]*.html")):
        num = prefix + f.name.split("-")[0]
        s = f.read_text()
        title = re.search(r"<title>(.*?)</title>", s).group(1).split(" — ")[0]
        title = re.sub(r"^\d+\.\s*", "", html.unescape(title))
        secs = {}
        for m in re.finditer(r'<section[^>]*id="([^"]+)"[^>]*>(?:(?!<section).)*?<h2[^>]*>(.*?)</h2>', s, re.S):
            t = re.sub(r'<span class="(?:num|lvlbadge)[^"]*">.*?</span>', "", m.group(2))
            t = html.unescape(t)
            t = re.sub(r"<[^>]+>", " ", t)
            secs[m.group(1)] = re.sub(r"\s+", " ", t).strip()
        TUT[num] = dict(folder=folder, file=f.name, title=title, secs=secs)


def link(ref):
    num, anchor = ref.split("#")
    t = TUT[num]
    if anchor not in t["secs"]:
        raise SystemExit(f"anchor {ref} not found in {t['file']}")
    short = ("SD " if num.startswith("sd") else "") + str(int(num.lstrip("sd")))
    return dict(
        path=f"{t['folder']}/{t['file']}#{anchor}",
        label=f"{short}. {t['title']} → {t['secs'][anchor]}",
    )


# ---------- validation ----------
DRILL = {d["id"]: d for d in DRILLS}
PARENTS = [q for t in TOPICS for g in t["groups"] for q in g["qs"]]
USED_BY = {d["id"]: [] for d in DRILLS}
ids = set()
for n in PARENTS + DRILLS:
    assert n["id"] not in ids, f"duplicate id {n['id']}"
    ids.add(n["id"])
    total = sum(k[0] for k in n["keys"])
    assert total == 100, f"{n['id']}: weights sum to {total}"
    assert n["lvl"] in LVL_NAME, n["id"]
    for r in n["deep"]:
        link(r)
for q in PARENTS:
    for did, _ in q["sub"]:
        assert did in DRILL, f"{q['id']} -> unknown drill {did}"
        USED_BY[did].append(q["id"])
unused = [d for d, u in USED_BY.items() if not u]
assert not unused, f"unused drills: {unused}"


# ---------- markdown (AI context) ----------
def md_node(n, drill=False):
    case = n.get("kind") == "case"
    out = [f"### {n['id']} [{n['lvl']}]{' [кейс]' if case else ''} {n['title']}"]
    if drill:
        out.append("Використовується в: " + ", ".join(USED_BY[n["id"]]))
    out.append(f"Питання: {n['q']}")
    if case:
        out.append(f"Вхідні дані (називай, коли кандидат питає про масштаб чи обмеження): {n['given']}")
    out.append(f"Еталон: {n['a']}")
    out.append("Ключові пункти (вага → уточнення, якщо пункт не прозвучав):")
    for w, text, probe in n["keys"]:
        out.append(f"- ({w}%) {text} → уточнення: «{probe}»")
    if not drill and n["sub"]:
        out.append("Підтеми для заглиблення (постав у цьому формулюванні):")
        for did, framing in n["sub"]:
            out.append(f"- {did} [{DRILL[did]['lvl']}] → «{framing}»")
    if n["red"]:
        out.append("Червоні прапорці: " + "; ".join(f"«{r}»" for r in n["red"]))
    out.append("Глибше: " + "; ".join(f"{{{{DOCS}}}}{link(r)['path']}" for r in n["deep"]))
    return "\n".join(out)


PROMPT = (SRC / "prompt.md").read_text().strip()
DOC_TITLE = "Контекст для AI-інтерв'юера: Python, бази даних, системний дизайн"
LEGEND = (
    "Рівні: [J] Junior, [M] Middle, [S] Senior; [кейс] — відкрита задача на проєктування. Ваги ключових пунктів у питанні дають 100%. "
    "Посилання «Глибше» ведуть на туторіали, з яких складено банк."
)

groups_json = []
for t in TOPICS:
    for g in t["groups"]:
        groups_json.append(dict(
            id=g["id"], topic=t["title"], icon=t["icon"], title=g["title"],
            nodes=[dict(id=q["id"], lvl=q["lvl"], subs=[s[0] for s in q["sub"]], md=md_node(q)) for q in g["qs"]],
        ))
drills_json = [dict(id=d["id"], lvl=d["lvl"], md=md_node(d, drill=True)) for d in DRILLS]


def assemble(groups, drills, docs_prefix=""):
    """Same algorithm as the JS builder on the page (keep them in sync)."""
    parents = [n for g in groups for n in g["nodes"]]
    used = {s for n in parents for s in n["subs"]}
    drills = [d for d in drills if d["id"] in used]
    parts = [
        f"# {DOC_TITLE}",
        f"Обсяг: {len(parents)} основних питань, {len(drills)} підтем. {LEGEND}",
        "---",
        PROMPT,
        "---",
        "# БАНК ПИТАНЬ",
    ]
    for g in groups:
        parts.append(f"## {g['topic']} › {g['title']}")
        parts += [n["md"] for n in g["nodes"]]
    parts.append("# БІБЛІОТЕКА ПІДТЕМ")
    parts += [d["md"] for d in drills]
    parts.append("---\nКінець документа. Чекай першого повідомлення кандидата і почни з кроку «Старт сесії».")
    return "\n\n".join(parts).replace("{{DOCS}}", docs_prefix)


FULL_MD = assemble(groups_json, drills_json)
(OUT / f"{SLUG}.md").write_text(FULL_MD + "\n")


# ---------- HTML ----------
def lvl_badge(lv, short=False):
    return f'<span class="lvl {LVL_CLS[lv]}">{lv if short else LVL_NAME[lv]}</span>'


def deep_html(refs):
    items = []
    for r in refs:
        l = link(r)
        items.append(f'<a href="../{l["path"]}">{esc(l["label"])}</a>')
    return '<div class="iq-deep"><span class="iq-label">Глибше</span>' + "".join(items) + "</div>"


def node_html(n, drill=False):
    kps = "".join(
        f'<li><span class="kp-w"><span class="kp-bar" style="width:{w}%"></span><b>{w}%</b></span>'
        f'<span class="kp-t">{esc(t)}<span class="kp-probe">↳ уточнення: «{esc(p)}»</span></span></li>'
        for w, t, p in n["keys"]
    )
    parts = [
        f'<details class="iq{" iq-drill" if drill else ""}" id="{n["id"]}">',
        f'<summary><span class="iq-id">{n["id"]}</span>{lvl_badge(n["lvl"])}'
        + ('<span class="lvl type">кейс</span>' if n.get("kind") == "case" else "")
        + f'<span class="iq-title">{esc(n["title"])}</span></summary>',
        '<div class="iq-body">',
    ]
    if drill:
        parts.append('<div class="iq-used">Використовується в: ' + ", ".join(
            f'<a href="#{p}">{p}</a>' for p in USED_BY[n["id"]]) + "</div>")
    parts += [
        f'<p class="iq-q">{esc(n["q"])}</p>',
    ]
    if n.get("kind") == "case":
        parts.append(f'<div class="iq-given"><span class="iq-label">Вхідні дані — агент називає, коли ви питаєте про масштаб</span>{esc(n["given"])}</div>')
    parts += [
        '<div class="iq-label">Еталон</div>',
        f'<p class="iq-a">{esc(n["a"])}</p>',
        '<div class="iq-label">Ключові пункти · вага · уточнення</div>',
        f'<ul class="kps">{kps}</ul>',
    ]
    if not drill and n["sub"]:
        subs = "".join(
            f'<li><a href="#{d}" class="sub-chip">{d}</a>{lvl_badge(DRILL[d]["lvl"], True)}'
            f'<span class="sub-f">«{esc(f)}»</span></li>'
            for d, f in n["sub"]
        )
        parts += ['<div class="iq-label">Підтеми для заглиблення</div>', f'<ul class="subs">{subs}</ul>']
    if n["red"]:
        parts.append('<div class="iq-red"><span class="iq-label">🚩 Червоні прапорці</span>'
                     + "".join(f"<span>«{esc(r)}»</span>" for r in n["red"]) + "</div>")
    parts.append(deep_html(n["deep"]))
    parts.append("</div></details>")
    return "\n".join(parts)


def count_lvls(nodes):
    c = {"J": 0, "M": 0, "S": 0}
    for n in nodes:
        c[n["lvl"]] += 1
    return " · ".join(f"{LVL_NAME[k][0]} {v}" for k, v in c.items() if v)


DIAGRAM = '''<figure class="diagram">
<svg viewBox="0 0 720 330" role="img" aria-label="Дерево: тема, група, основні питання з ключовими пунктами і спільні підтеми">
  <defs>
    <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="sv-arrow"/></marker>
  </defs>
  <rect x="8" y="132" width="104" height="54" rx="10" class="sv-box sv-accent"/>
  <text x="60" y="152" class="sv-s" text-anchor="middle">тема</text>
  <text x="60" y="172" class="sv-b" text-anchor="middle">🐍 Python</text>
  <rect x="140" y="132" width="128" height="54" rx="10" class="sv-box"/>
  <text x="204" y="152" class="sv-s" text-anchor="middle">група</text>
  <text x="204" y="172" class="sv-b" text-anchor="middle">Конкурентність</text>
  <line x1="112" y1="159" x2="138" y2="159" class="sv-line" marker-end="url(#ar)"/>
  <path d="M268,159 C285,159 282,80 298,80" class="sv-line" fill="none" marker-end="url(#ar)"/>
  <path d="M268,159 C285,159 282,240 298,240" class="sv-line" fill="none" marker-end="url(#ar)"/>

  <rect x="300" y="38" width="190" height="86" rx="10" class="sv-box"/>
  <text x="314" y="58" class="sv-s">PY-CONC-01 · Middle</text>
  <text x="314" y="78" class="sv-b">GIL</text>
  <rect x="314" y="92" width="40" height="12" class="sv-good"/><rect x="355" y="92" width="40" height="12" class="sv-warn"/><rect x="396" y="92" width="40" height="12" class="sv-warn"/><rect x="437" y="92" width="23" height="12" class="sv-good"/><rect x="461" y="92" width="15" height="12" class="sv-bad"/>
  <text x="314" y="118" class="sv-s">5 пунктів · 25/25/25/15/10</text>

  <rect x="300" y="198" width="190" height="86" rx="10" class="sv-box"/>
  <text x="314" y="218" class="sv-s">PY-CONC-02 · Middle</text>
  <text x="314" y="238" class="sv-b">threading / asyncio</text>
  <rect x="314" y="252" width="48" height="12" class="sv-good"/><rect x="363" y="252" width="40" height="12" class="sv-good"/><rect x="404" y="252" width="48" height="12" class="sv-bad"/><rect x="453" y="252" width="23" height="12" class="sv-warn"/>
  <text x="314" y="278" class="sv-s">4 пункти · 30/25/30/15</text>

  <rect x="560" y="44" width="152" height="62" rx="10" class="sv-box sv-drill"/>
  <text x="574" y="66" class="sv-s">D-RACE-GIL · M</text>
  <text x="574" y="88" class="sv-b">Гонки попри GIL</text>
  <rect x="560" y="206" width="152" height="62" rx="10" class="sv-box sv-drill"/>
  <text x="574" y="228" class="sv-s">D-CPU-IN-ASYNC · M</text>
  <text x="574" y="250" class="sv-b">CPU в async</text>

  <line x1="490" y1="66" x2="557" y2="66" class="sv-dash" marker-end="url(#ar)"/>
  <line x1="490" y1="108" x2="557" y2="222" class="sv-dash" marker-end="url(#ar)"/>
  <line x1="490" y1="214" x2="557" y2="96" class="sv-dash" marker-end="url(#ar)"/>
  <line x1="490" y1="262" x2="557" y2="252" class="sv-dash" marker-end="url(#ar)"/>

  <rect x="8" y="306" width="12" height="12" class="sv-good"/><text x="26" y="317" class="sv-s">покрито сам</text>
  <rect x="120" y="306" width="12" height="12" class="sv-warn"/><text x="138" y="317" class="sv-s">після уточнення (60%)</text>
  <rect x="290" y="306" width="12" height="12" class="sv-bad"/><text x="308" y="317" class="sv-s">не покрито</text>
  <line x1="410" y1="312" x2="440" y2="312" class="sv-dash"/><text x="448" y="317" class="sv-s">заглиблення в спільну підтему</text>
</svg>
<figcaption>Ширина сегмента дорівнює вазі ключового пункту. Обидва основні питання ведуть в обидві підтеми, але кожне ставить її <b>своїм формулюванням</b>: агент заходить у підтему з контексту батька.</figcaption>
</figure>'''

EXAMPLE = '''<div class="dialog">
  <div class="dl ai"><span class="who">AI</span><p>Розкажіть, що таке GIL і на що він впливає?</p></div>
  <div class="dl me"><span class="who">Ви</span><p>Це глобальний лок у CPython: одночасно виконується тільки один потік, тому потоки не дають паралелізму для обчислень, для цього беруть multiprocessing.</p></div>
  <div class="dl note"><b>Внутрішня оцінка:</b> K1 «один потік» ✓ 25 · K4 «CPU → процеси» ✓ 15 · K2, K3, K5 ✗ → <b>40%</b>. Нижче 80%, тож уточнення до найважчого непокритого пункту (K2 і K3 по 25, береться перший — K2).</div>
  <div class="dl ai"><span class="who">AI</span><p>А чому CPython просто не прибрав GIL ще двадцять років тому?</p></div>
  <div class="dl me"><span class="who">Ви</span><p>Через підрахунок посилань: без GIL кожен інкремент refcount мав би бути атомарним, і однопотоковий код став би повільнішим.</p></div>
  <div class="dl note">K2 розкрито після уточнення: 25 × 0.6 = 15 → <b>55%</b>. Друге (останнє) уточнення — до K3.</div>
  <div class="dl ai"><span class="who">AI</span><p>Тоді чому threading нормально прискорює сто HTTP-запитів?</p></div>
  <div class="dl me"><span class="who">Ви</span><p>Бо поки потік чекає на мережу, GIL відпускається й інші потоки працюють.</p></div>
  <div class="dl note">K3 після уточнення +15 → <b>70%</b>. Уточнення вичерпано. 70% ≥ 70 і підтема D-RACE-GIL має рівень Middle ≤ цільового → <b>заглиблення</b> з формулюванням батька.</div>
  <div class="dl ai"><span class="who">AI</span><p>Якщо є GIL і одночасно виконується один потік — навіщо тоді threading.Lock?</p></div>
  <div class="dl me"><span class="who">Ви</span><p>…</p></div>
  <div class="dl ai fb"><span class="who">AI · фідбек</span><p>Покриття близько 70%. Сильно — суть GIL і поділ CPU/I-O. Самі ви не пояснили, навіщо GIL існує і що він звільняється на I/O, і не згадали free-threaded збірку з Python 3.13 (PEP 703). Наступне питання…</p></div>
</div>'''

EXTRA_CSS = '''
  /* --- interview-ai extras --- */
  .iq{border:1px solid var(--border); border-radius:12px; margin:10px 0; background:var(--card); overflow:hidden; scroll-margin-top:80px;}
  .iq summary{cursor:pointer; list-style:none; padding:12px 44px 12px 14px; position:relative; display:flex; align-items:center; gap:8px; flex-wrap:wrap;}
  .iq summary::-webkit-details-marker{display:none;}
  .iq summary::after{content:"+"; position:absolute; right:16px; top:50%; transform:translateY(-56%); color:var(--fg-muted); font-size:19px;}
  .iq[open] summary::after{content:"–";}
  .iq summary:hover{background:var(--bg-soft);}
  .iq:target{border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft);}
  .iq-id{font-family:"SF Mono",ui-monospace,Consolas,monospace; font-size:12px; font-weight:700; color:var(--accent);}
  .iq-drill .iq-id{color:var(--interview);}
  .iq-title{font-weight:600; font-size:14.8px;}
  .iq-body{border-top:1px solid var(--border); padding:12px 16px 16px; font-size:14.3px;}
  .iq-q{font-weight:600; font-size:15px; margin:4px 0 12px; padding:10px 12px; border-left:3px solid var(--accent); background:var(--accent-soft); border-radius:0 8px 8px 0;}
  .iq-drill .iq-q{border-left-color:var(--interview); background:var(--interview-bg);}
  .iq-label{display:block; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; color:var(--fg-muted); margin:14px 0 6px;}
  .iq-a{margin:0; color:var(--fg);}
  .iq-given{margin:4px 0 0; padding:8px 12px; border-radius:8px; background:var(--warn-bg); border:1px solid var(--warn-border); font-size:13.8px;}
  .iq-given .iq-label{margin:0 0 2px; color:var(--warn);}
  .iq-used{font-size:13px; color:var(--fg-muted); margin-bottom:6px;}
  .iq-used a{font-family:"SF Mono",ui-monospace,Consolas,monospace; font-size:12px;}
  ul.kps{list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:8px;}
  ul.kps li{display:grid; grid-template-columns:64px 1fr; gap:10px; align-items:start; margin:0;}
  .kp-w{position:relative; display:block; height:22px; border-radius:6px; background:var(--bg-soft); border:1px solid var(--border); overflow:hidden;}
  .kp-bar{position:absolute; left:0; top:0; bottom:0; background:var(--good-bg); border-right:2px solid var(--good);}
  .kp-w b{position:relative; display:block; text-align:center; font-size:12px; line-height:20px; color:var(--fg);}
  .kp-t{display:flex; flex-direction:column; gap:2px;}
  .kp-probe{color:var(--fg-muted); font-size:13.2px; font-style:italic;}
  ul.subs{list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:6px;}
  ul.subs li{margin:0; display:flex; gap:8px; align-items:baseline; flex-wrap:wrap;}
  .sub-chip{font-family:"SF Mono",ui-monospace,Consolas,monospace; font-size:12px; font-weight:700; color:var(--interview); background:var(--interview-bg); border:1px solid var(--interview-border); padding:1px 8px; border-radius:999px; text-decoration:none;}
  .sub-f{color:var(--fg-muted); font-size:13.5px;}
  .iq-red{margin-top:12px; padding:8px 12px; border-radius:8px; background:var(--bad-bg); border:1px solid var(--bad-border); display:flex; flex-direction:column; gap:2px; font-size:13.5px;}
  .iq-red .iq-label{margin:0 0 2px; color:var(--bad);}
  .iq-deep{margin-top:12px; display:flex; flex-direction:column; gap:3px; font-size:13px;}
  .iq-deep .iq-label{margin:0 0 2px;}
  .group-head{display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin:30px 0 6px; scroll-margin-top:80px;}
  .group-head h3{margin:0;}
  .group-head .cnt{font-size:12px; color:var(--fg-muted);}
  /* svg */
  .sv-box{fill:var(--card); stroke:var(--border); stroke-width:1.5;}
  .sv-accent{stroke:var(--accent);}
  .sv-drill{stroke:var(--interview); fill:var(--interview-bg);}
  .sv-b{fill:var(--fg); font-size:14px; font-weight:700;}
  .sv-s{fill:var(--fg-muted); font-size:11.5px;}
  .sv-line{stroke:var(--fg-muted); stroke-width:1.5;}
  .sv-dash{stroke:var(--interview); stroke-width:1.5; stroke-dasharray:5 4;}
  .sv-arrow{fill:var(--fg-muted);}
  .sv-good{fill:var(--good);} .sv-warn{fill:var(--warn);} .sv-bad{fill:var(--bad); opacity:.75;}
  /* dialog example */
  .dialog{display:flex; flex-direction:column; gap:8px; margin:16px 0;}
  .dl{border-radius:12px; padding:10px 14px; font-size:14.3px; max-width:88%;}
  .dl p{margin:2px 0 0;}
  .dl .who{font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; color:var(--fg-muted);}
  .dl.ai{background:var(--bg-soft); border:1px solid var(--border); align-self:flex-start;}
  .dl.me{background:var(--accent-soft); border:1px solid var(--info-border); align-self:flex-end;}
  .dl.note{align-self:center; max-width:100%; background:transparent; border:1px dashed var(--interview-border); color:var(--fg-muted); font-size:13.2px;}
  .dl.note b{color:var(--interview);}
  .dl.fb{border-color:var(--good-border); background:var(--good-bg);}
  @media (max-width:600px){ .dl{max-width:100%;} }
  /* context builder */
  .builder{border:1px solid var(--accent); border-radius:var(--radius); background:var(--bg-soft); padding:18px; margin:18px 0;}
  .builder h4{margin:0 0 10px; font-size:15px;}
  .b-grid{display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:6px 14px; margin:6px 0 14px;}
  .b-grid label, .b-lv label{display:flex; gap:8px; align-items:flex-start; font-size:14px; cursor:pointer;}
  .b-grid label .c{color:var(--fg-muted); font-size:12px;}
  .b-topic{grid-column:1/-1; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; color:var(--accent); margin-top:6px;}
  .b-lv{display:flex; gap:16px; flex-wrap:wrap; margin:6px 0 16px;}
  .b-actions{display:flex; gap:10px; flex-wrap:wrap; align-items:center;}
  .b-btn{cursor:pointer; font:inherit; font-size:14px; font-weight:600; padding:9px 16px; border-radius:10px; border:1px solid var(--accent); background:var(--accent); color:#fff;}
  .b-btn.sec{background:var(--card); color:var(--accent);}
  .b-btn:hover{filter:brightness(1.07);}
  .b-btn:focus-visible{outline:2px solid var(--accent); outline-offset:2px;}
  .b-stat{font-size:13px; color:var(--fg-muted);}
  .b-preview{margin-top:14px;}
  .b-preview summary{cursor:pointer; font-size:13.5px; color:var(--accent); font-weight:600;}
  .b-preview textarea{width:100%; height:320px; margin-top:8px; font-family:"SF Mono",ui-monospace,Consolas,monospace; font-size:12px; background:var(--code-bg); color:var(--code-fg); border:1px solid var(--border); border-radius:10px; padding:12px; resize:vertical;}
  .prompt-box{white-space:pre-wrap; word-break:break-word; font-size:13px; line-height:1.55;}
'''

BUILDER_JS = r'''<script>
(function(){
  var DATA = JSON.parse(document.getElementById('bank-data').textContent);
  var root = document.getElementById('builder');
  if(!root) return;
  var DOCS_BASE = new URL('../', location.href).href;
  var LV = {J:['J'], M:['J','M'], S:['J','M','S']};
  function selected(){
    var on = {};
    root.querySelectorAll('input[data-group]').forEach(function(c){ if(c.checked) on[c.dataset.group] = 1; });
    var lv = (root.querySelector('input[name="b-lvl"]:checked') || {}).value || 'S';
    return DATA.groups.filter(function(g){ return on[g.id]; }).map(function(g){
      return {topic:g.topic, title:g.title, nodes:g.nodes.filter(function(n){ return LV[lv].indexOf(n.lvl) >= 0; })};
    }).filter(function(g){ return g.nodes.length; });
  }
  // Same algorithm as assemble() in _src/build.py (keep in sync).
  function assemble(groups){
    var parents = [], used = {};
    groups.forEach(function(g){ g.nodes.forEach(function(n){ parents.push(n); n.subs.forEach(function(s){ used[s] = 1; }); }); });
    var drills = DATA.drills.filter(function(d){ return used[d.id]; });
    var parts = ['# ' + DATA.title,
      'Обсяг: ' + parents.length + ' основних питань, ' + drills.length + ' підтем. ' + DATA.legend,
      '---', DATA.prompt, '---', '# БАНК ПИТАНЬ'];
    groups.forEach(function(g){
      parts.push('## ' + g.topic + ' › ' + g.title);
      g.nodes.forEach(function(n){ parts.push(n.md); });
    });
    parts.push('# БІБЛІОТЕКА ПІДТЕМ');
    drills.forEach(function(d){ parts.push(d.md); });
    parts.push('---\nКінець документа. Чекай першого повідомлення кандидата і почни з кроку «Старт сесії».');
    return {text: parts.join('\n\n').split('{{DOCS}}').join(DOCS_BASE), parents: parents.length, drills: drills.length};
  }
  var stat = document.getElementById('b-stat'), ta = document.getElementById('b-text');
  function refresh(){
    var r = assemble(selected());
    ta.value = r.text;
    stat.textContent = r.parents + ' питань · ' + r.drills + ' підтем · ' +
      Math.round(r.text.length / 1000) + ' тис. символів (≈' + Math.round(r.text.length / 2600) + ' тис. токенів)';
    return r;
  }
  root.addEventListener('change', refresh);
  function flash(btn, text){
    var old = btn.textContent; btn.textContent = text;
    setTimeout(function(){ btn.textContent = old; }, 1600);
  }
  document.getElementById('b-copy').addEventListener('click', function(){
    var btn = this, text = refresh().text;
    function fallback(){
      ta.closest('details').open = true; ta.focus(); ta.select();
      try{ document.execCommand('copy'); flash(btn, '✓ Скопійовано'); }catch(e){ flash(btn, 'Виділено — натисніть Ctrl/⌘+C'); }
    }
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(function(){ flash(btn, '✓ Скопійовано'); }, fallback);
    } else fallback();
  });
  document.getElementById('b-dl').addEventListener('click', function(){
    var blob = new Blob([refresh().text], {type:'text/markdown;charset=utf-8'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'ai-interviewer-backend.md';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function(){ URL.revokeObjectURL(a.href); }, 1000);
  });
  refresh();
})();
</script>'''


def build_page():
    tpl = (OUT / "_template.html").read_text()
    n_par, n_drill = len(PARENTS), len(DRILLS)

    # builder checkboxes
    rows = []
    for t in TOPICS:
        rows.append(f'<div class="b-topic">{t["icon"]} {esc(t["title"])}</div>')
        for g in t["groups"]:
            rows.append(f'<label><input type="checkbox" data-group="{g["id"]}" checked> '
                        f'<span>{esc(g["title"])} <span class="c">({count_lvls(g["qs"])})</span></span></label>')
    builder = f'''<div class="builder" id="builder">
  <h4>Конструктор контексту</h4>
  <div class="b-grid">{"".join(rows)}</div>
  <div class="iq-label">Які рівні включити</div>
  <div class="b-lv">
    <label><input type="radio" name="b-lvl" value="J"> лише Junior</label>
    <label><input type="radio" name="b-lvl" value="M"> Junior + Middle</label>
    <label><input type="radio" name="b-lvl" value="S" checked> усі (+ Senior)</label>
  </div>
  <div class="b-actions">
    <button type="button" class="b-btn" id="b-copy">📋 Скопіювати контекст</button>
    <button type="button" class="b-btn sec" id="b-dl">⬇️ Завантажити .md</button>
    <span class="b-stat" id="b-stat"></span>
  </div>
  <details class="b-preview"><summary>Попередній перегляд того, що піде в AI</summary><textarea id="b-text" readonly spellcheck="false"></textarea></details>
</div>'''

    # bank sections
    def group_block(g):
        head = (f'<div class="group-head" id="g-{g["id"]}"><h3>{esc(g["title"])}</h3>'
                f'<span class="cnt">{len(g["qs"])} питань · {count_lvls(g["qs"])}</span></div>')
        return head + "\n" + "\n".join(node_html(q) for q in g["qs"])

    topic_desc = {
        "py": "Мова, ООП, генератори, конкурентність, пам'ять, FastAPI/Pydantic, екосистема. Джерела — туторіали 4–16, 21–31.",
        "db": "PostgreSQL (транзакції, MVCC, блокування, міграції, реплікація), продуктивність запитів і Redis. Джерела — туторіали 17–20, 22, 26, 28, 29, 32.",
        "sd": "Концептуальні питання (масштабування, кеш, шардинг, черги, надійність) і кейси «спроєктуй систему». Джерела — вкладка System Design і туторіал 25.",
    }
    case_note = (
        '<div class="callout info"><span class="ic">🧩</span><div class="body"><span class="tag">Як агент веде кейс</span><br>'
        "Кейс — відкрита задача на 15–25 хвилин. Структуру ведете ви: вимоги → оцінки → API і дані → схема → вузькі місця. "
        "Агент не підказує етапи, на питання про масштаб називає «вхідні дані», а уточнення ставить у порядку етапів (до трьох). "
        "Ключові пункти тут — етапи і рішення, які очікують на співбесіді.</div></div>"
    )
    sec_html = []
    for i, t in enumerate(TOPICS):
        qs = [q for g in t["groups"] for q in g["qs"]]
        body = "".join(group_block(g) for g in t["groups"])
        if t["id"] == "sd":
            body = case_note + body
        sec_html.append(
            f'<section id="t-{t["id"]}">\n  <h2><span class="num">{4 + i}</span> {t["icon"]} {esc(t["title"])}</h2>\n'
            f'  <p class="section-desc">{len(qs)} основних питань у {len(t["groups"])} групах. {topic_desc[t["id"]]} Розгорніть питання, щоб побачити, що саме агент очікує почути.</p>\n'
            f"  {body}\n</section>"
        )
    topic_sections = "\n\n".join(sec_html)
    n_drill_sec, n_ext_sec = 4 + len(TOPICS), 5 + len(TOPICS)

    content = f'''
<section id="s0">
  <h2><span class="num">0</span> Ідея: дерево питань замість списку</h2>
  <p class="section-desc">Ця сторінка — одночасно туторіал і готовий контекст для AI-агента. Скопіюйте її в чат, увімкніть голосовий режим, і агент проведе з вами співбесіду: поставить питання, оцінить, яку частину відповіді ви покрили, і піде вглиб саме там, де ви «поплили».</p>
  <p>Звичайний список «74 питання» перевіряє, чи ви чули про тему. На справжній співбесіді важливіше, <b>як глибоко</b> ви її знаєте: інтерв'юер чує неповну відповідь, ставить уточнення, і якщо ви тримаєтесь, копає в підтему. Щоб AI міг робити так само, кожне питання тут — це вузол дерева з такою структурою:</p>
  <ul>
    <li><b>Рівень</b> — Junior, Middle або Senior; від нього залежить, які питання агент вибирає і наскільки глибоко копає.</li>
    <li><b>Еталон</b> — суть правильної відповіді (агент її не зачитує).</li>
    <li><b>Ключові пункти з вагами</b> (сума 100%) — за ними агент рахує <b>покриття</b> вашої відповіді.</li>
    <li><b>Уточнення</b> до кожного пункту — навідне питання, яке агент поставить, якщо пункт не прозвучав. Відповідь у ньому не підказується.</li>
    <li><b>Підтеми</b> D-… — спільні вузли для заглиблення. Одна підтема (наприклад, MVCC) живе в кількох батьківських питаннях, але кожен батько ставить її <b>своїм формулюванням</b>.</li>
    <li><b>Червоні прапорці</b> — типові хибні твердження, на які агент реагує зустрічним питанням.</li>
    <li><b>Глибше</b> — розділи туторіалів, що потрапляють у фінальний звіт як «що перечитати».</li>
  </ul>
  {DIAGRAM}
  <div class="fe-analogy"><div class="tag">Аналогія для фронтендера</div>
  Банк — це дерево компонентів. Основне питання — сторінка, ключові пункти — її обов'язкові пропси, а підтема D-… — перевикористовуваний компонент на кшталт <code>&lt;MvccExplainer /&gt;</code>. Він рендериться в кількох батьках, і кожен батько передає свої props, тобто формулювання питання. Сам компонент (ключові пункти підтеми) один, тож оцінка консистентна, а контекст щоразу свій.</div>
</section>

<section id="s1">
  <h2><span class="num">1</span> Як агент оцінює відповідь</h2>
  <p class="section-desc">Вся «механіка» живе в промпті (розділ 3), але її корисно знати: тоді зрозуміло, чому агент ставить саме таке уточнення.</p>
  <div class="flow">
    <span class="step">Питання</span><span class="arrow">→</span>
    <span class="step">Ваша відповідь</span><span class="arrow">→</span>
    <span class="step">Покриття = Σ ваг</span><span class="arrow">→</span>
    <span class="step">&lt; 80%: уточнення (≤ 2)</span><span class="arrow">→</span>
    <span class="step">≥ 70%: підтема</span><span class="arrow">→</span>
    <span class="step">Фідбек · наступне</span>
  </div>
  <table>
    <tr><th>Правило</th><th>Значення</th></tr>
    <tr><td>Пункт покрито самостійно</td><td>100% ваги</td></tr>
    <tr><td>Пункт покрито частково</td><td>50% ваги</td></tr>
    <tr><td>Пункт розкрито після уточнення</td><td>60% ваги</td></tr>
    <tr><td>Уточнень на основне питання / підтему</td><td>до 2 / до 1</td></tr>
    <tr><td>Заглиблення в підтему</td><td>покриття ≥ 70% і рівень підтеми ≤ цільового</td></tr>
    <tr><td>Адаптація рівня</td><td>2 поспіль ≥ 80% → вище; 2 поспіль &lt; 50% → нижче</td></tr>
    <tr><td>Рівень підтверджено</td><td>середнє покриття питань цього рівня ≥ 70%</td></tr>
  </table>
  <h3>Приклад: як це звучить</h3>
  <p>Цільовий рівень — Middle, режим тренування. Сірі пунктирні блоки показують «думки» агента; вголос він їх не промовляє.</p>
  {EXAMPLE}
</section>

<section id="s2">
  <h2><span class="num">2</span> Запуск за 3 кроки</h2>
  <p class="section-desc">Оберіть, що тренуєте, скопіюйте контекст і почніть розмову голосом.</p>
  <ol class="steps">
    <li><b>Зберіть контекст</b> у конструкторі нижче: відмітьте групи й рівні. Що менше контекст, то краще його «тримає» голосовий режим.</li>
    <li><b>Вставте його в новий текстовий чат</b> з асистентом (ChatGPT, Claude, Gemini тощо) і надішліть одним повідомленням. Інший варіант — завантажити <code>.md</code> як файл у проєкт або custom-асистента, щоб не вставляти щоразу.</li>
    <li><b>Увімкніть голосовий режим у тому ж чаті</b> і скажіть «Почни». Агент запитає рівень, теми, режим і кількість питань.</li>
  </ol>
  {builder}
  <div class="callout warn"><span class="ic">⚠️</span><div class="body"><span class="tag">Обмеження голосових режимів</span><br>Голосові режими деяких застосунків працюють з меншою моделлю або коротшим контекстом, ніж текстовий чат. Якщо агент починає вигадувати питання поза банком або забуває правила, звузьте контекст до 2–3 груп або проходьте співбесіду в текстовому чаті з диктуванням. Повний файл без фільтрів: <a href="{SLUG}.md">{SLUG}.md</a>.</div></div>
  <div class="callout info"><span class="ic">💡</span><div class="body"><span class="tag">Як тренуватись</span><br>Спершу 2–3 сесії в режимі «тренування» по одній темі, потім «співбесіда» на всі теми. Збережіть фінальні звіти: три питання «для наступної сесії» з кожного звіту — найкращий план повторення.</div></div>
</section>

<section id="s3">
  <h2><span class="num">3</span> Головний промпт</h2>
  <p class="section-desc">Він іде на початку контексту. Кожен розділ закриває конкретну проблему, через яку AI-інтерв'юери зазвичай розчаровують.</p>
  <table>
    <tr><th>Розділ промпту</th><th>Яку проблему закриває</th></tr>
    <tr><td>Роль, «єдине джерело — банк»</td><td>Агент вигадує випадкові питання і сам на них відповідає</td></tr>
    <tr><td>Цикл питання, бали, 60% після уточнення</td><td>Оцінка «на око»; агент приймає будь-яку відповідь</td></tr>
    <tr><td>Уточнення без підказок, максимум 2</td><td>Агент сам договорює відповідь або нескінченно «допитує»</td></tr>
    <tr><td>Підтеми з формулюванням батька, глибина ≤ 2</td><td>Заглиблення без зв'язку з контекстом або занадто глибоко</td></tr>
    <tr><td>Голосовий формат, толерантність до розпізнавання</td><td>Довгі монологи зі списками; штраф за «гіл» замість GIL</td></tr>
    <tr><td>Кейси: кандидат веде, вхідні дані — на запит</td><td>Агент сам розписує дизайн або одразу вивалює всі цифри</td></tr>
    <tr><td>Команди кандидата</td><td>Немає способу керувати сесією голосом</td></tr>
    <tr><td>Підсумок зі звітом і посиланнями</td><td>Співбесіда закінчилась, а що робити далі — незрозуміло</td></tr>
  </table>
  <div class="codecard plain"><div class="bar"><span class="path">prompt.md · іде першим у контексті</span></div><pre><code class="prompt-box">{esc(PROMPT)}</code></pre></div>
</section>

{topic_sections}

<section id="s7">
  <h2><span class="num">{n_drill_sec}</span> Бібліотека підтем</h2>
  <p class="section-desc">{n_drill} спільних вузлів для заглиблення. У кожного вказано, з яких основних питань агент може в нього зайти.</p>
  {"".join(node_html(d, drill=True) for d in DRILLS)}
</section>

<section id="s8">
  <h2><span class="num">{n_ext_sec}</span> Як розширювати банк</h2>
  <p class="section-desc">Наступні теми (Kubernetes, JS, Node.js) додаються так само: дані окремо, сторінка генерується.</p>
  <div class="codecard"><div class="bar"><span class="path">docs/interview-ai/_src/</span></div><pre><code>prompt.md            <span class="cmt"># головний промпт інтерв'юера</span>
bank_python_db.py    <span class="cmt"># Python і PostgreSQL: TOPICS → groups → питання, DRILLS → підтеми</span>
bank_system_design.py <span class="cmt"># Redis (група в «Бази даних») і тема «Системний дизайн»</span>
build.py             <span class="cmt"># валідація + HTML-сторінка + .md-контекст</span>

python3 docs/interview-ai/_src/build.py</code></pre></div>
  <p>Скрипт перевіряє, що ваги кожного вузла дають рівно 100, що всі підтеми існують і використовуються, а кожне посилання «Глибше» веде на наявний розділ туторіалу.</p>
  <h3>Як писати добрі ключові пункти</h3>
  <ul class="checklist">
    <li><b>Перевірюваний факт, а не тема.</b> «Звільняється на I/O → потоки корисні для I/O-bound» замість «знає про I/O».</li>
    <li><b>3–5 пунктів, вага за важливістю.</b> Пункт, без якого відповідь хибна, важить 30–40; деталь для Senior — 10–15.</li>
    <li><b>Уточнення не містить відповіді.</b> «Тоді чому threading прискорює HTTP-запити?», а не «GIL відпускається на I/O, так?».</li>
    <li><b>Формулювання підтеми спирається на батька</b>: «Ви сказали X. А як тоді Y?».</li>
    <li><b>Червоний прапорець — реальна поширена помилка</b>, а не вигадана пастка.</li>
  </ul>
</section>
'''

    topic_toc = "".join(
        f'<li><a href="#t-{t["id"]}">{4 + i}. {esc(t["title"])}</a><ol>'
        + "".join(f'<li><a href="#g-{g["id"]}">{esc(g["title"])}</a></li>' for g in t["groups"])
        + "</ol></li>"
        for i, t in enumerate(TOPICS)
    )
    toc = f'''    <div class="toc-group">Як це працює</div>
    <ol>
      <li><a href="#s0">0. Дерево питань</a></li>
      <li><a href="#s1">1. Оцінка покриття</a></li>
      <li><a href="#s2">2. Запуск і конструктор</a></li>
      <li><a href="#s3">3. Головний промпт</a></li>
    </ol>
    <div class="toc-group">Банк питань</div>
    <ol>
      {topic_toc}
      <li><a href="#s7">{n_drill_sec}. Бібліотека підтем</a></li>
    </ol>
    <div class="toc-group">Далі</div>
    <ol>
      <li><a href="#s8">{n_ext_sec}. Як розширювати банк</a></li>
    </ol>'''

    data = dict(title=DOC_TITLE, legend=LEGEND, prompt=PROMPT, groups=groups_json, drills=drills_json)
    data_js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    pills = "\n".join(f'    <span class="pill">{p}</span>' for p in [
        f"{n_par} основних питань", f"{n_drill} підтем", f"{sum(1 for q in PARENTS if q.get('kind') == 'case')} кейсів на дизайн", "Junior · Middle · Senior", "🎙️ голосовий режим", "📋 копіюється в будь-який AI"])
    page = (tpl
            .replace("{{TITLE}}", "Python, БД, System Design")
            .replace("{{KICKER}}", "🎙️ Підготовка до співбесіди з AI")
            .replace("{{H1}}", "Тренажер співбесіди: Python, бази даних, системний дизайн")
            .replace("{{LEAD}}", "Промпт плюс розгалужений банк питань: з ним AI-асистент у голосовому режимі стає інтерв'юером. Він оцінює, на скільки відсотків ви покрили питання, ставить уточнення і йде вглиб у підтеми.")
            .replace("{{PILLS}}", pills)
            .replace("{{TOC}}", toc)
            .replace("{{CONTENT}}", content)
            .replace("{{FOOTER}}", 'Банк зібрано з <a href="../python-tutorials/04-python-types.html">Python Doc</a> і <a href="../system-design/01-interview-framework.html">System Design</a>.')
            .replace("</style>", EXTRA_CSS + "</style>", 1)
            .replace('<script src="../assets/mobile-nav.js"></script>',
                     f'<script type="application/json" id="bank-data">{data_js}</script>\n{BUILDER_JS}\n<script src="../assets/mobile-nav.js"></script>'))
    # mark this page active in the sidebar
    page = page.replace('id="tab-mock" class="tab-radio">', 'id="tab-mock" class="tab-radio" checked>', 1)
    page = page.replace(f'<a href="../interview-ai/{SLUG}.html">', f'<a href="../interview-ai/{SLUG}.html" class="active">', 1)
    assert "{{" not in page.replace("{{DOCS}}", ""), "unfilled placeholder"
    (OUT / f"{SLUG}.html").write_text(page)
    print(f"OK: {n_par} parents, {n_drill} drills; html {len(page)//1024} KB, md {len(FULL_MD)//1024} KB")


build_page()
