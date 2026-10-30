/* Site navigation helpers for the docs pages (see mobile-nav.css):
   1. Mobile drawer (≤768px): level 1 lists the tutorial sections (the
      sidebar's tab buttons), level 2 the pages of the chosen section. Read
      from the page's own .nav-sidebar, so no link list is duplicated.
   2. Wraps tables that sit directly in the text flow in a horizontal
      scroller, so wide tables scroll instead of widening the page.
   3. "На цій сторінці" scroll-spy: highlights the section being read in
      aside.toc; on mobile, where the TOC is hidden, a small bar under the
      header shows that section's number and title and opens the TOC list. */
(function () {
  var MOBILE = window.matchMedia ? window.matchMedia('(max-width: 768px)') : null;
  var sidebar = document.querySelector('.nav-sidebar');
  var topRow = document.querySelector('header.top .top-row') || document.querySelector('header.top .top-inner');
  if (!sidebar || !topRow) return;

  // Each tab button is <label for="tab-x">; its links live in the .nav-links
  // block that the stylesheet shows for that radio (#tab-x:checked ~ .nav-links.y).
  var NAV_CLASS = {
    'tab-project': 'proj', 'tab-interview': 'interview', 'tab-sysdesign': 'sysdesign',
    'tab-jsdoc': 'jsdoc', 'tab-node': 'node', 'tab-quantum': 'quantum'
  };
  var groups = [];
  Array.prototype.forEach.call(sidebar.querySelectorAll('.nav-tabbtn'), function (label) {
    var id = label.getAttribute('for');
    var nav = sidebar.querySelector('.nav-links.' + (NAV_CLASS[id] || ''));
    if (!nav) return;
    var radio = document.getElementById(id);
    groups.push({
      id: id,
      label: label.textContent.trim(),
      links: Array.prototype.slice.call(nav.querySelectorAll('a')),
      current: !!nav.querySelector('a.active'),
      checked: !!(radio && radio.defaultChecked)
    });
  });
  if (!groups.length) return;
  // The section of the current page: the one holding the active link, else the pre-checked tab.
  var currentIndex = groups.findIndex(function (g) { return g.current; });
  if (currentIndex < 0) currentIndex = groups.findIndex(function (g) { return g.checked; });

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text != null) node.textContent = text;
    return node;
  }

  // ----- toggle button in the header -----
  var toggle = el('button', { type: 'button', 'class': 'mnav-toggle', 'aria-controls': 'mnav', 'aria-expanded': 'false' });
  toggle.appendChild(el('span', { 'class': 'mnav-burger', 'aria-hidden': 'true' }, '☰'));
  toggle.appendChild(el('span', {}, 'Меню'));
  topRow.insertBefore(toggle, topRow.firstChild);

  // ----- drawer -----
  var root = el('div', { id: 'mnav', 'class': 'mnav', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Навігація по туторіалах', hidden: '' });
  var backdrop = el('div', { 'class': 'mnav-backdrop' });
  var sheet = el('div', { 'class': 'mnav-sheet' });
  var head = el('div', { 'class': 'mnav-head' });
  var back = el('button', { type: 'button', 'class': 'mnav-icon-btn mnav-back', 'aria-label': 'Назад до розділів', hidden: '' }, '← Розділи');
  var title = el('div', { 'class': 'mnav-title' }, 'Туторіали');
  var close = el('button', { type: 'button', 'class': 'mnav-icon-btn', 'aria-label': 'Закрити меню' }, '✕');
  head.appendChild(back); head.appendChild(title); head.appendChild(close);

  var views = el('div', { 'class': 'mnav-views' });
  var lvl1 = el('div', { 'class': 'mnav-view lvl1' });
  var lvl2 = el('div', { 'class': 'mnav-view lvl2' });
  lvl1.appendChild(el('div', { 'class': 'mnav-hint' }, 'Оберіть розділ'));
  groups.forEach(function (g, i) {
    var b = el('button', { type: 'button', 'class': 'mnav-group' + (i === currentIndex ? ' is-current' : '') });
    b.appendChild(el('span', { 'class': 'mnav-glabel' }, g.label));
    b.appendChild(el('span', { 'class': 'mnav-count' }, String(g.links.length)));
    b.appendChild(el('span', { 'class': 'mnav-chev', 'aria-hidden': 'true' }, '›'));
    b.addEventListener('click', function () { showGroup(i); });
    lvl1.appendChild(b);
  });
  var lvl2Hint = el('div', { 'class': 'mnav-hint' });
  var lvl2List = el('nav', { 'class': 'mnav-links' });
  lvl2.appendChild(lvl2Hint); lvl2.appendChild(lvl2List);
  views.appendChild(lvl1); views.appendChild(lvl2);
  sheet.appendChild(head); sheet.appendChild(views);
  root.appendChild(backdrop); root.appendChild(sheet);
  document.body.appendChild(root);

  function showGroup(i) {
    var g = groups[i];
    lvl2List.textContent = '';
    g.links.forEach(function (a) {
      var link = el('a', { href: a.getAttribute('href') }, a.textContent.trim());
      if (a.classList.contains('active')) { link.className = 'active'; link.setAttribute('aria-current', 'page'); }
      lvl2List.appendChild(link);
    });
    lvl2Hint.textContent = 'Теми розділу';
    title.textContent = g.label;
    back.hidden = false;
    root.classList.add('show-lvl2');
    lvl2.scrollTop = 0;
    var active = lvl2List.querySelector('a.active');
    if (active) active.scrollIntoView({ block: 'center' });
    (active || lvl2List.querySelector('a') || back).focus({ preventScroll: true });
  }

  function showSections() {
    root.classList.remove('show-lvl2');
    title.textContent = 'Туторіали';
    back.hidden = true;
    var cur = lvl1.querySelector('.mnav-group.is-current') || lvl1.querySelector('.mnav-group');
    if (cur) cur.focus({ preventScroll: true });
  }

  var closeTimer = null;
  function open() {
    clearTimeout(closeTimer);
    root.hidden = false;
    showSections();
    // next frame so the slide-in transition runs from the hidden position
    requestAnimationFrame(function () { root.classList.add('is-open'); });
    document.documentElement.classList.add('mnav-lock');
    toggle.setAttribute('aria-expanded', 'true');
  }
  function shut(returnFocus) {
    if (root.hidden) return;
    root.classList.remove('is-open');
    document.documentElement.classList.remove('mnav-lock');
    toggle.setAttribute('aria-expanded', 'false');
    closeTimer = setTimeout(function () { root.hidden = true; root.classList.remove('show-lvl2'); }, 230);
    if (returnFocus) toggle.focus();
  }

  toggle.addEventListener('click', function () { root.hidden ? open() : shut(true); });
  close.addEventListener('click', function () { shut(true); });
  backdrop.addEventListener('click', function () { shut(true); });
  back.addEventListener('click', showSections);
  lvl2List.addEventListener('click', function (e) { if (e.target.closest('a')) shut(false); });

  document.addEventListener('keydown', function (e) {
    if (root.hidden) return;
    if (e.key === 'Escape') {
      if (root.classList.contains('show-lvl2')) showSections(); else shut(true);
      return;
    }
    if (e.key !== 'Tab') return;
    // keep focus inside the drawer while it's open
    var focusable = Array.prototype.filter.call(
      sheet.querySelectorAll('button, a[href]'),
      function (n) { return !n.hidden && n.offsetParent !== null && getComputedStyle(n).visibility !== 'hidden'; }
    );
    if (!focusable.length) return;
    var first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  // Leaving mobile width (rotation, resize) closes the drawer; the sidebar takes over.
  if (MOBILE) {
    var onChange = function (mq) { if (!mq.matches) shut(false); };
    if (MOBILE.addEventListener) MOBILE.addEventListener('change', onChange);
    else if (MOBILE.addListener) MOBILE.addListener(onChange);
  }
})();

(function () {
  var toc = document.querySelector('aside.toc');
  var header = document.querySelector('header.top');
  if (!toc || !header) return;

  // TOC entries that point at a section on this page, in document order.
  var items = [];
  Array.prototype.forEach.call(toc.querySelectorAll('a[href^="#"]'), function (a) {
    var id = decodeURIComponent(a.getAttribute('href').slice(1));
    var target = id && document.getElementById(id);
    if (!target) return;
    var label = '';
    a.childNodes.forEach(function (n) {   // skip badges such as <span class="toc-count">
      if (n.nodeType === 3 || !(n.classList && n.classList.contains('toc-count'))) label += n.textContent;
    });
    items.push({ link: a, target: target, label: label.replace(/\s+/g, ' ').trim() });
  });
  if (!items.length) return;
  items.sort(function (x, y) {
    return x.target.compareDocumentPosition(y.target) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
  });

  // ----- mobile "you are reading" bar + dropdown with the page TOC -----
  var bar = document.createElement('div');
  bar.className = 'toc-here';
  bar.hidden = true;
  var barBtn = document.createElement('button');
  barBtn.type = 'button';
  barBtn.className = 'toc-here-btn';
  barBtn.setAttribute('aria-expanded', 'false');
  barBtn.setAttribute('aria-controls', 'toc-here-list');
  var barText = document.createElement('span');
  barText.className = 'toc-here-text';
  var barChev = document.createElement('span');
  barChev.className = 'toc-here-chev';
  barChev.setAttribute('aria-hidden', 'true');
  barChev.textContent = '▾';
  barBtn.appendChild(barText); barBtn.appendChild(barChev);
  var list = document.createElement('nav');
  list.id = 'toc-here-list';
  list.className = 'toc-here-list';
  list.setAttribute('aria-label', 'На цій сторінці');
  list.hidden = true;
  items.forEach(function (it, i) {
    var a = document.createElement('a');
    a.href = it.link.getAttribute('href');
    a.textContent = it.label;
    a.dataset.idx = String(i);
    list.appendChild(a);
  });
  bar.appendChild(barBtn); bar.appendChild(list);
  header.appendChild(bar);

  function setListOpen(open) {
    list.hidden = !open;
    barBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    bar.classList.toggle('is-open', open);
    if (open) {
      var cur = list.querySelector('a.is-active');
      if (cur) list.scrollTop = cur.offsetTop - list.clientHeight / 2;
    }
  }
  barBtn.addEventListener('click', function () { setListOpen(list.hidden); });
  list.addEventListener('click', function (e) { if (e.target.closest('a')) setListOpen(false); });
  document.addEventListener('click', function (e) { if (!list.hidden && !bar.contains(e.target)) setListOpen(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !list.hidden) { setListOpen(false); barBtn.focus(); } });

  // ----- scroll-spy -----
  var current = -1;
  function activate(idx) {
    if (idx === current) return;
    if (current >= 0) {
      items[current].link.classList.remove('is-active');
      items[current].link.removeAttribute('aria-current');
      var prev = list.querySelector('a[data-idx="' + current + '"]');
      if (prev) prev.classList.remove('is-active');
    }
    current = idx;
    bar.hidden = idx < 0;
    if (idx < 0) return;
    var it = items[idx];
    it.link.classList.add('is-active');
    it.link.setAttribute('aria-current', 'location');
    var mob = list.querySelector('a[data-idx="' + idx + '"]');
    if (mob) mob.classList.add('is-active');
    barText.textContent = it.label;
    // keep the highlighted entry visible inside the sticky TOC without moving the page
    if (toc.scrollHeight > toc.clientHeight) {
      var top = it.link.offsetTop - toc.offsetTop, h = it.link.offsetHeight;
      if (top < toc.scrollTop + 40 || top + h > toc.scrollTop + toc.clientHeight - 40) {
        toc.scrollTop = Math.max(0, top - toc.clientHeight / 3);
      }
    }
  }

  function compute() {
    var line = header.getBoundingClientRect().bottom + 24;   // "reading line" just below the sticky header
    var idx = -1;
    for (var i = 0; i < items.length; i++) {
      if (items[i].target.getBoundingClientRect().top <= line) idx = i; else break;
    }
    // at the very bottom the last short sections can never reach the line
    var doc = document.documentElement;
    if (window.innerHeight + window.scrollY >= doc.scrollHeight - 4 && items[items.length - 1].target.getBoundingClientRect().top < window.innerHeight) {
      idx = items.length - 1;
    }
    activate(idx);
  }

  var ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () { ticking = false; compute(); });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  window.addEventListener('load', compute);
  compute();
})();

(function () {
  var article = document.querySelector('article');
  if (!article) return;
  Array.prototype.forEach.call(article.querySelectorAll('table'), function (table) {
    for (var p = table.parentElement; p && p !== article; p = p.parentElement) {
      var o = getComputedStyle(p).overflowX;
      if (o === 'auto' || o === 'scroll' || o === 'hidden') return;   // already scrolls
    }
    if (getComputedStyle(table).display === 'block') return;           // page styles it as a scroller
    var wrap = document.createElement('div');
    wrap.className = 'table-scroll';
    table.parentNode.insertBefore(wrap, table);
    wrap.appendChild(table);
  });
})();
