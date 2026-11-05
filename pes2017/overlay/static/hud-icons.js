/* The Gaffer matchday HUD. All artwork is local; no icon font or network. */
(() => {
  'use strict';
  // Filled by pro_ui.py with reversible codepoint -> sprite mappings.
  const ICONS = /*__HUD_ICON_MAP__*/{};
  const SPRITE = '/hud-icons.svg#hud-';
  const NS = 'http://www.w3.org/2000/svg';
  const LABEL = {
    ball:'Goal', trophy:'Trophy', target:'Objective', 'trend-up':'Improving',
    'trend-down':'Declining', hourglass:'Waiting', contract:'Contract',
    star:'Star', 'star-empty':'Not shortlisted', flame:'In form', news:'News',
    clipboard:'Report', glove:'Goalkeeper', play:'Play', warning:'Warning',
    document:'Document', waiting:'Waiting', handshake:'Agreement', money:'Finance',
    medical:'Medical', bolt:'Highlight', transfer:'Transfer', shirt:'Kit',
    screen:'Digital', chat:'Conversation', clock:'Time', lock:'Locked',
    microphone:'Press', check:'Complete', briefcase:'Club', injury:'Injury',
    squad:'Squad', youth:'Youth', calendar:'Calendar', scout:'Scouting',
    door:'Departure', workout:'Training', academy:'Academy', sound:'Audio',
    'arrow-down':'Down', 'arrow-up':'Up', boot:'Player', manager:'Manager',
    shield:'Club', heart:'Support', chart:'Statistics', board:'Board',
    battery:'Fitness', strength:'Strength', stadium:'Stadium', eye:'Watch',
    gamepad:'Controls', flag:'Flag', run:'Player', book:'History', brick:'Defence',
    medal:'Medal', player:'Player', folder:'Folder', seat:'Seat', save:'Save',
    unlock:'Unlocked', settings:'Settings', search:'Search', 'form-up':'Very happy',
    'form-good':'Content', 'form-neutral':'Neutral', 'form-low':'Concerned',
    'form-down':'Unhappy', crown:'Champion', globe:'World', tag:'Label',
    pause:'Pause', tools:'Tools', power:'Quit', close:'No', science:'Analysis',
    sliders:'Tactics', flight:'Travel', info:'Information', idea:'Idea',
    weather:'Weather', rocket:'Progress', bell:'Notifications', home:'Home',
    mail:'Inbox', store:'Shop', refresh:'Reload', menu:'Menu', assist:'Assist',
    ticket:'Tickets', card:'Yellow card', signal:'Status'
  };
  const escapeRx = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const nativeToCode = Object.create(null);
  Object.keys(ICONS).forEach(code => {
    try { nativeToCode[String.fromCodePoint(...code.split('_').map(x => parseInt(x, 16)))] = code; }
    catch (_) { /* malformed mapping cannot become markup */ }
  });
  const natives = Object.keys(nativeToCode).sort((a, b) => b.length - a.length);
  // Legacy/user data may contain emoji not present in the shipped sources.
  // Match whole keycaps, flags and ZWJ sequences first, then known text-style
  // pictographs. Plain arrows and ordinary text symbols remain untouched.
  const unit = '(?:\\p{Emoji_Presentation}\\uFE0F?|\\p{Emoji}\\uFE0F)[\\u{1F3FB}-\\u{1F3FF}]?';
  const fallback = '(?:[#*0-9]\\uFE0F?\\u20E3|[\\u{1F1E6}-\\u{1F1FF}]{2}|' +
    unit + '(?:\\u200D' + unit + ')*)';
  const pattern = new RegExp('__gi_([0-9a-f]+(?:_[0-9a-f]+)*)__|(' +
    fallback + (natives.length ? '|' + natives.map(escapeRx).join('|') : '') + ')', 'gu');

  function parts(text) {
    const found = [];
    pattern.lastIndex = 0;
    let m;
    while ((m = pattern.exec(text))) {
      const code = m[1] || nativeToCode[m[2]] || nativeToCode[(m[2] || '').replace(/\uFE0F/g, '')] || '';
      const name = ICONS[code] || 'info';
      found.push({start:m.index, end:pattern.lastIndex, code, name});
    }
    return found;
  }
  function plain(text) {
    const hits = parts(text);
    if (!hits.length) return text;
    let out = '', pos = 0;
    hits.forEach(hit => {
      out += text.slice(pos, hit.start) + (LABEL[hit.name] || 'Status');
      pos = hit.end;
    });
    return out + text.slice(pos);
  }
  function icon(name, code, decorative) {
    const span = document.createElement('span');
    span.className = 'hud-icon hud-icon--' + name;
    if (code) span.dataset.hudCode = code;
    if (decorative) span.setAttribute('aria-hidden', 'true');
    else {
      span.setAttribute('role', 'img');
      span.setAttribute('aria-label', LABEL[name] || 'Status');
    }
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('focusable', 'false');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS(NS, 'use');
    use.setAttribute('href', SPRITE + name);
    svg.appendChild(use);
    span.appendChild(svg);
    return span;
  }
  function excluded(parent) {
    return !parent || !!parent.closest('script,style,textarea,svg,math,noscript,[contenteditable]:not([contenteditable="false"]),.hud-icon');
  }
  function renderText(text) {
    const parent = text.parentElement;
    if (excluded(parent)) return;
    const value = text.nodeValue;
    const hits = parts(value);
    if (!hits.length) return;
    const option = parent.closest('option');
    if (option || parent.closest('pre,code')) {
      // An <option> without an explicit value derives it from textContent.
      // Preserve that value before making the display text human-readable.
      if (option && !option.hasAttribute('value')) option.setAttribute('value', option.value);
      text.nodeValue = plain(value);
      return;
    }
    const fragment = document.createDocumentFragment();
    let pos = 0;
    hits.forEach(hit => {
      if (hit.start > pos) fragment.appendChild(document.createTextNode(value.slice(pos, hit.start)));
      fragment.appendChild(icon(hit.name, hit.code, false));
      pos = hit.end;
    });
    if (pos < value.length) fragment.appendChild(document.createTextNode(value.slice(pos)));
    text.parentNode.replaceChild(fragment, text);
  }
  const ATTRS = ['title', 'aria-label', 'alt', 'placeholder'];
  function cleanAttrs(el) {
    if (!el || el.nodeType !== 1 || el.classList.contains('hud-icon')) return;
    ATTRS.forEach(name => {
      if (!el.hasAttribute(name)) return;
      const old = el.getAttribute(name), next = plain(old);
      if (old !== next) el.setAttribute(name, next);
    });
  }
  function renderTree(root) {
    if (root.nodeType === 3) { renderText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 11) return;
    if (root.nodeType === 1 && excluded(root)) return;
    if (root.nodeType === 1) cleanAttrs(root);
    // Inspect the whole inserted subtree as older saved content may contain
    // native pictographs in tooltips or labels, not just our source tokens.
    // Never rewrite data-* or values: they are application identifiers.
    if (root.querySelectorAll) root.querySelectorAll('[title],[aria-label],[alt],[placeholder]').forEach(cleanAttrs);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(renderText);
  }

  const NAV = {
    home:'home', inbox:'mail', assistant:'scout', squad:'squad', growth:'workout',
    youth:'youth', transfers:'transfer', signings:'transfer', sales:'money',
    shortlist:'star', loans:'transfer', aimoves:'sliders', comp:'trophy',
    league:'trophy', stats:'chart', calendar:'calendar', media:'news',
    news:'news', rumours:'chat', board:'board', talks:'chat', press:'microphone',
    journal:'book', clubs:'shield', honours:'trophy', awards:'medal',
    review:'clipboard', records:'book', history:'book', deadline:'clock',
    fans:'flag', stories:'document', kit:'shirt', players:'player'
  };
  function prependIcon(el, name, kind, replaceSvg) {
    if (!el || !name || el.querySelector(':scope > .hud-' + kind + '-icon')) return;
    if (replaceSvg) {
      const old = el.querySelector(':scope > svg');
      if (old) old.remove();
    }
    const node = icon(name, '', true);
    node.classList.add('hud-' + kind + '-icon');
    el.insertBefore(node, el.firstChild);
    el.classList.add('hud-equipped');
  }
  function decorateChrome() {
    document.querySelectorAll('#nav > button, #nav > [data-ng]').forEach(el => {
      const key = el.dataset.ng || el.dataset.p || '';
      prependIcon(el, NAV[key] || 'shield', 'nav', false);
    });
    document.querySelectorAll('.subtabs button[data-p-go], .subtabs button[data-sc-go]').forEach(el => {
      const key = el.dataset.pGo || (el.hasAttribute('data-sc-go') ? 'assistant' : '');
      prependIcon(el, NAV[key] || 'clipboard', 'tab', false);
    });
    document.querySelectorAll('#mtab button').forEach(el => {
      const key = el.dataset.mt || 'menu';
      prependIcon(el, NAV[key] || 'menu', 'nav', true);
    });
    [['#tbFind','search'], ['#tbar .tb-bell','bell'], ['#reloadBtn','refresh'],
     ['.ibx-head .ibx-ic','mail']].forEach(([selector, name]) => {
      document.querySelectorAll(selector).forEach(el => prependIcon(el, name, 'chrome', true));
    });
    const menu = document.querySelector('#tbar .tb-menu');
    if (menu && !menu.querySelector(':scope > .hud-chrome-icon')) {
      menu.textContent = '';
      prependIcon(menu, 'menu', 'chrome', false);
    }
    document.querySelectorAll('#sgBudget .sgh-g').forEach(group => {
      const names = ['money', 'squad', 'money', 'chart'];
      Array.from(group.children).forEach((el, index) => prependIcon(el, names[index], 'kpi', false));
    });
    document.querySelectorAll('[data-hud-icon]').forEach(el => {
      prependIcon(el, el.dataset.hudIcon, 'heading', false);
    });
  }
  let chromePending = false;
  function queueChrome() {
    if (chromePending) return;
    chromePending = true;
    requestAnimationFrame(() => { chromePending = false; decorateChrome(); });
  }
  function start() {
    if (!document.body) return;
    renderTree(document.body);
    decorateChrome();
    const observer = new MutationObserver(records => {
      let changed = false;
      records.forEach(record => {
        if (record.type === 'characterData') renderText(record.target);
        else if (record.type === 'attributes') cleanAttrs(record.target);
        else {
          record.addedNodes.forEach(renderTree);
          if (record.addedNodes.length || record.removedNodes.length) changed = true;
        }
      });
      if (changed) queueChrome();
    });
    observer.observe(document.body, {
      subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:ATTRS
    });
    document.body.classList.add('hud-ready');
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
