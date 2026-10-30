/* Mobile navigation drawer for the docs site (see mobile-nav.css).
   Level 1 lists the tutorial sections (the sidebar's tab buttons), level 2
   lists the pages of the chosen section (that tab's .nav-links). Everything
   is read from the page's own .nav-sidebar, so no link list is duplicated. */
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
