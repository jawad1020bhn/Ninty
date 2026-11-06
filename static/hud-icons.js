/* The Gaffer matchday HUD. All artwork is local; no icon font or network. */
(() => {
  'use strict';
  // Filled by pro_ui.py with reversible codepoint -> sprite mappings.
  const ICONS = {"26bd":"ball","1f3c6":"trophy","1f389":"trophy","1f3af":"target","1f3f9":"target","1f4c8":"trend-up","1f4c9":"trend-down","23f3":"hourglass","270d":"contract","2712":"contract","270e":"contract","2605":"star","2b50":"star","1f31f":"star","2728":"star","2726":"star","2606":"star-empty","1f525":"flame","1f4f0":"news","1f4cb":"clipboard","1f9fe":"clipboard","1f9e4":"glove","25b6":"play","26a0":"warning","2757":"warning","1f92f":"warning","1f4c4":"document","1f92b":"waiting","2615":"waiting","1f91d":"handshake","1f4b6":"money","1f4b0":"money","1f4b8":"money","1f9ee":"money","271a":"medical","1fa7a":"medical","26a1":"bolt","1f501":"transfer","1f504":"transfer","1f455":"shirt","1f5a5":"screen","1f4fa":"screen","1f4ac":"chat","23f0":"clock","23f1":"clock","1f512":"lock","1f3a4":"microphone","1f399":"microphone","2705":"check","2714":"check","1f4bc":"briefcase","1f9f3":"briefcase","1fa79":"injury","1f465":"squad","1f331":"youth","1f9ec":"youth","1f4c5":"calendar","1f5d3":"calendar","1f52d":"scout","1f9ed":"scout","1f6aa":"door","1f44b":"door","1f3cb":"workout","1f393":"academy","1f50a":"sound","1f4e2":"sound","1f4e3":"sound","1f4de":"sound","266a":"sound","2b07":"arrow-down","1f422":"arrow-down","2b06":"arrow-up","1f45f":"boot","1f3a9":"manager","1f454":"manager","1f9d3":"manager","1f574":"manager","1f6e1":"shield","1f6df":"shield","1f494":"heart","2764":"heart","1f4ca":"chart","1f3db":"board","1f3d7":"board","2696":"board","1f50b":"battery","1f4aa":"strength","2694":"strength","1f5e1":"strength","1f988":"strength","1f3df":"stadium","1f440":"eye","1f3ae":"gamepad","2691":"flag","1f3c1":"flag","1f9e3":"flag","1f3c3":"run","1f4d6":"book","1f4d5":"book","1f4da":"book","1f9f1":"brick","1f947":"medal","1f948":"medal","1f949":"medal","1f464":"player","1f4c1":"folder","1f5c2":"folder","1fa91":"seat","1f4be":"save","1f513":"unlock","2699":"settings","2315":"search","1f50e":"search","1f604":"form-up","1f642":"form-good","263a":"form-good","1f60c":"form-good","1f610":"form-neutral","2639":"form-low","1f641":"form-low","1f620":"form-low","1f61e":"form-low","1f621":"form-down","1f976":"form-down","1f451":"crown","1f30d":"globe","1f3f7":"tag","1f195":"tag","23f8":"pause","1f6e0":"tools","2702":"tools","23fb":"power","274c":"close","1f645":"close","270b":"close","1f9ea":"science","1f39b":"sliders","265f":"sliders","1f9e9":"sliders","1f0cf":"sliders","1f9e0":"sliders","2708":"flight","1f6eb":"flight","1fa82":"flight","2139":"info","1f4a1":"idea","1f327":"weather","1f680":"rocket","1f514":"bell","1f3e0":"home","2709":"mail","1f4e8":"mail","1f4e5":"mail","1f6d2":"store","1f170":"assist","1f39f":"ticket","1f7e8":"card","1f7e2":"signal","1f534":"signal","26bd_fe0f":"ball","1f3c6_fe0f":"trophy","1f389_fe0f":"trophy","1f3af_fe0f":"target","1f3f9_fe0f":"target","1f4c8_fe0f":"trend-up","1f4c9_fe0f":"trend-down","23f3_fe0f":"hourglass","270d_fe0f":"contract","2712_fe0f":"contract","270e_fe0f":"contract","2605_fe0f":"star","2b50_fe0f":"star","1f31f_fe0f":"star","2728_fe0f":"star","2726_fe0f":"star","2606_fe0f":"star-empty","1f525_fe0f":"flame","1f4f0_fe0f":"news","1f4cb_fe0f":"clipboard","1f9fe_fe0f":"clipboard","1f9e4_fe0f":"glove","25b6_fe0f":"play","26a0_fe0f":"warning","2757_fe0f":"warning","1f92f_fe0f":"warning","1f4c4_fe0f":"document","1f92b_fe0f":"waiting","2615_fe0f":"waiting","1f91d_fe0f":"handshake","1f4b6_fe0f":"money","1f4b0_fe0f":"money","1f4b8_fe0f":"money","1f9ee_fe0f":"money","271a_fe0f":"medical","1fa7a_fe0f":"medical","26a1_fe0f":"bolt","1f501_fe0f":"transfer","1f504_fe0f":"transfer","1f455_fe0f":"shirt","1f5a5_fe0f":"screen","1f4fa_fe0f":"screen","1f4ac_fe0f":"chat","23f0_fe0f":"clock","23f1_fe0f":"clock","1f512_fe0f":"lock","1f3a4_fe0f":"microphone","1f399_fe0f":"microphone","2705_fe0f":"check","2714_fe0f":"check","1f4bc_fe0f":"briefcase","1f9f3_fe0f":"briefcase","1fa79_fe0f":"injury","1f465_fe0f":"squad","1f331_fe0f":"youth","1f9ec_fe0f":"youth","1f4c5_fe0f":"calendar","1f5d3_fe0f":"calendar","1f52d_fe0f":"scout","1f9ed_fe0f":"scout","1f6aa_fe0f":"door","1f44b_fe0f":"door","1f3cb_fe0f":"workout","1f393_fe0f":"academy","1f50a_fe0f":"sound","1f4e2_fe0f":"sound","1f4e3_fe0f":"sound","1f4de_fe0f":"sound","266a_fe0f":"sound","2b07_fe0f":"arrow-down","1f422_fe0f":"arrow-down","2b06_fe0f":"arrow-up","1f45f_fe0f":"boot","1f3a9_fe0f":"manager","1f454_fe0f":"manager","1f9d3_fe0f":"manager","1f574_fe0f":"manager","1f6e1_fe0f":"shield","1f6df_fe0f":"shield","1f494_fe0f":"heart","2764_fe0f":"heart","1f4ca_fe0f":"chart","1f3db_fe0f":"board","1f3d7_fe0f":"board","2696_fe0f":"board","1f50b_fe0f":"battery","1f4aa_fe0f":"strength","2694_fe0f":"strength","1f5e1_fe0f":"strength","1f988_fe0f":"strength","1f3df_fe0f":"stadium","1f440_fe0f":"eye","1f3ae_fe0f":"gamepad","2691_fe0f":"flag","1f3c1_fe0f":"flag","1f9e3_fe0f":"flag","1f3c3_fe0f":"run","1f4d6_fe0f":"book","1f4d5_fe0f":"book","1f4da_fe0f":"book","1f9f1_fe0f":"brick","1f947_fe0f":"medal","1f948_fe0f":"medal","1f949_fe0f":"medal","1f464_fe0f":"player","1f4c1_fe0f":"folder","1f5c2_fe0f":"folder","1fa91_fe0f":"seat","1f4be_fe0f":"save","1f513_fe0f":"unlock","2699_fe0f":"settings","2315_fe0f":"search","1f50e_fe0f":"search","1f604_fe0f":"form-up","1f642_fe0f":"form-good","263a_fe0f":"form-good","1f60c_fe0f":"form-good","1f610_fe0f":"form-neutral","2639_fe0f":"form-low","1f641_fe0f":"form-low","1f620_fe0f":"form-low","1f61e_fe0f":"form-low","1f621_fe0f":"form-down","1f976_fe0f":"form-down","1f451_fe0f":"crown","1f30d_fe0f":"globe","1f3f7_fe0f":"tag","1f195_fe0f":"tag","23f8_fe0f":"pause","1f6e0_fe0f":"tools","2702_fe0f":"tools","23fb_fe0f":"power","274c_fe0f":"close","1f645_fe0f":"close","270b_fe0f":"close","1f9ea_fe0f":"science","1f39b_fe0f":"sliders","265f_fe0f":"sliders","1f9e9_fe0f":"sliders","1f0cf_fe0f":"sliders","1f9e0_fe0f":"sliders","2708_fe0f":"flight","1f6eb_fe0f":"flight","1fa82_fe0f":"flight","2139_fe0f":"info","1f4a1_fe0f":"idea","1f327_fe0f":"weather","1f680_fe0f":"rocket","1f514_fe0f":"bell","1f3e0_fe0f":"home","2709_fe0f":"mail","1f4e8_fe0f":"mail","1f4e5_fe0f":"mail","1f6d2_fe0f":"store","1f170_fe0f":"assist","1f39f_fe0f":"ticket","1f7e8_fe0f":"card","1f7e2_fe0f":"signal","1f534_fe0f":"signal","21a9_fe0f":"transfer","2194_fe0f":"transfer","2197_fe0f":"arrow-up","1f9d1_200d_1f4bc":"manager","1f9d1_200d_1f91d_200d_1f9d1":"squad","1f468_200d_1f469_200d_1f467":"squad","1f62e_200d_1f4a8":"form-neutral"};
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
