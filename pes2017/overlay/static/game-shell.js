/* Game Shell V2: a bounded, additive navigation layer for the Classic app. */
(() => {
  'use strict';
  const KEY = 'gaffer_shell';
  const MQ = '(min-width: 1025px) and (min-height: 560px)';
  const NS = 'http://www.w3.org/2000/svg';
  const DEFINITIONS = [
    {id:'home', icon:'home', label:'[data-p="home"]', pages:['home']},
    {id:'squad', icon:'squad', label:'[data-ng="squad"]', pages:['squad','kit','growth','youth','players']},
    {id:'transfers', icon:'transfer', label:'[data-ng="transfers"]', pages:['signings','transfers','shortlist','sales','loans','aimoves','deadline']},
    {id:'competitions', icon:'trophy', label:'[data-ng="comp"]', pages:['league','clubs','honours','records','history','stats','awards']},
    {id:'media', icon:'news', label:'[data-ng="media"]', pages:['news','press','rumours','journal','story','fans','stories']},
    {id:'office', icon:'board', label:'[data-p="board"]', pages:['board','inbox','assistant','talks','calendar','review']}
  ];

  function start() {
    const body = document.body;
    // Tools are wired to the assets now, but keep their current behavior until
    // the separate tools-board phase. Mobile keeps the existing phone layout.
    if (!body || body.dataset.hud !== 'classic') return;
    const main = document.querySelector('.app > main');
    const originalNav = document.getElementById('nav');
    const look = document.querySelector('#sfLook .sf-lk');
    if (!main || !originalNav || !look) return;

    const media = window.matchMedia(MQ);
    let preferred = true;
    try { preferred = localStorage.getItem(KEY) !== '0'; } catch (_) {}
    let previousWindowScroll = 0;
    let activeSection = '';
    let groupSignature = '';
    let pageSignature = '';
    let pending = false;
    let tourWaitExpired = false;
    let requestedAlias = null;
    let dispatchingRoute = false;
    const aliases = {transfers:'signings', story:'news'};
    const lastPage = Object.create(null);
    const addedTabStops = new Set();

    function navButton(id) {
      return originalNav.querySelector('button[data-p="' + id + '"]');
    }
    function labelOf(el) {
      if (!el) return '';
      const copy = el.cloneNode(true);
      copy.querySelectorAll('.hud-icon,.nbadge,.n-badge,.ibn,svg,[aria-hidden="true"]').forEach(n => n.remove());
      return copy.textContent.replace(/\s+/g, ' ').trim();
    }
    function sections() {
      return DEFINITIONS.map(def => {
        const pages = def.pages.filter(id => navButton(id) && document.getElementById('p-' + id))
          .map(id => ({id, label:labelOf(navButton(id))}));
        const source = originalNav.querySelector(def.label) || navButton(pages[0] && pages[0].id);
        return {id:def.id, label:labelOf(source), icon:def.icon, pages};
      }).filter(group => group.pages.length);
    }
    function pageNow() {
      const panel = main.querySelector('section.panel.on[id^="p-"]');
      return panel ? panel.id.slice(2) : (location.hash.slice(1) || 'home');
    }
    function openPage(id) {
      const source = navButton(id);
      if (!source) return false;
      // Even a hidden original button participates in the existing delegated
      // handler. This keeps all loaders, redirects and app-side state intact.
      requestedAlias = aliases[id] ? id : null;
      dispatchingRoute = true;
      try { source.click(); } finally { dispatchingRoute = false; }
      // Native show() selects its panel synchronously; reflect it right away
      // rather than waiting for a later paint during a heavy page load.
      sync();
      schedule();
      return true;
    }
    function icon(name) {
      const span = document.createElement('span');
      span.className = 'gs-section-icon';
      span.setAttribute('aria-hidden', 'true');
      const svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('focusable', 'false');
      const use = document.createElementNS(NS, 'use');
      use.setAttribute('href', '/hud-icons.svg#hud-' + name);
      svg.appendChild(use); span.appendChild(svg);
      return span;
    }
    function button(text, dataset, iconName) {
      const el = document.createElement('button');
      el.type = 'button';
      Object.keys(dataset).forEach(key => { el.dataset[key] = dataset[key]; });
      if (iconName) el.appendChild(icon(iconName));
      const label = document.createElement('span');
      label.className = 'gs-label'; label.textContent = text;
      el.appendChild(label);
      return el;
    }

    const hud = document.createElement('div');
    hud.id = 'gsHud'; hud.hidden = true;
    const primary = document.createElement('div'); primary.className = 'gs-primary';
    const tabs = document.createElement('nav'); tabs.className = 'gs-tabs';
    tabs.setAttribute('aria-label', 'Main sections');
    primary.appendChild(tabs);
    const subrow = document.createElement('div'); subrow.className = 'gs-subrow';
    const context = document.createElement('span'); context.className = 'gs-context';
    const pages = document.createElement('nav'); pages.className = 'gs-pages';
    pages.setAttribute('aria-label', 'Section pages');
    subrow.append(context, pages); hud.append(primary, subrow);
    const bar = document.getElementById('tbar');
    if (bar && bar.parentElement === main) bar.after(hud); else main.prepend(hud);

    const toggle = document.createElement('button');
    toggle.type = 'button'; toggle.id = 'gameShellBtn';
    toggle.className = 'btn ghost sm';
    toggle.setAttribute('aria-controls', 'gsHud');
    const retro = document.getElementById('retroBtn');
    if (retro && retro.parentElement === look) retro.after(toggle); else look.appendChild(toggle);

    function addPanelTabStops() {
      main.querySelectorAll('section.panel').forEach(panel => {
        if (!panel.hasAttribute('tabindex')) {
          panel.setAttribute('tabindex', '0');
          addedTabStops.add(panel);
        }
      });
    }
    function removePanelTabStops() {
      addedTabStops.forEach(panel => {
        if (panel.getAttribute('tabindex') === '0') panel.removeAttribute('tabindex');
      });
      addedTabStops.clear();
    }
    function waitingForTour() {
      try {
        if (localStorage.getItem('tourDone')) return false;
        // The native tour stops checking after 40 attempts (about 123s). If no
        // tour ever appeared, do not strand a first-time user in Classic forever.
        return !tourWaitExpired || !!document.getElementById('tourO');
      } catch (_) { return false; }
    }
    function toggleLabel() {
      const hr = document.documentElement.lang === 'hr';
      let value = preferred ? (hr ? 'uključen' : 'on') : (hr ? 'isključen' : 'off');
      // The app's optional UI-language dictionary already translates Enabled /
      // Disabled. Reuse those entries rather than maintaining another dictionary.
      try {
        if (!hr && typeof UIT !== 'undefined' && UIT) value = UIT[preferred ? 'Enabled' : 'Disabled'] || value;
      } catch (_) {}
      toggle.textContent = (hr ? 'Izbornik igre: ' : 'Game shell: ') + value;
      toggle.setAttribute('aria-pressed', String(preferred));
      toggle.title = preferred && waitingForTour()
        ? (hr ? 'Aktivira se nakon obilaska' : 'Starts after the first-run tour')
        : (hr ? 'Fiksni izbornik na većim zaslonima' : 'Fixed-screen menus on larger displays');
    }
    function applyMode() {
      const was = body.classList.contains('game-shell');
      // The native first-run tour locates its steps in #nav. Leave the Classic
      // interface in place until the user has completed or skipped that tour.
      const enabled = preferred && media.matches && !waitingForTour();
      if (enabled && !was) {
        previousWindowScroll = window.scrollY;
        window.scrollTo(0, 0);
        addPanelTabStops();
      }
      body.classList.toggle('game-shell', enabled);
      hud.hidden = !enabled;
      if (!enabled && was) {
        removePanelTabStops();
        requestAnimationFrame(() => window.scrollTo(0, previousWindowScroll));
      }
      toggleLabel();
      schedule();
    }
    toggle.addEventListener('click', () => {
      preferred = !preferred;
      try { localStorage.setItem(KEY, preferred ? '1' : '0'); } catch (_) {}
      applyMode();
    });
    if (media.addEventListener) media.addEventListener('change', applyMode);
    else if (media.addListener) media.addListener(applyMode);
    window.setTimeout(() => { tourWaitExpired = true; applyMode(); }, 125000);
    document.addEventListener('click', event => {
      if (event.target.closest && event.target.closest('[data-tour]')) requestAnimationFrame(applyMode);
    });

    function markCurrent(container, key, value) {
      container.querySelectorAll('button').forEach(el => {
        if (el.dataset[key] === value) el.setAttribute('aria-current', 'page');
        else el.removeAttribute('aria-current');
      });
    }
    function sync() {
      pending = false;
      const groups = sections();
      const current = pageNow();
      const group = groups.find(g => g.pages.some(p => p.id === current)) || groups[0];
      if (!group) return;
      if (requestedAlias && aliases[requestedAlias] !== current) requestedAlias = null;
      const locationPage = requestedAlias || current;
      lastPage[group.id] = locationPage;
      const nextGroups = groups.map(g => g.id).join('|');
      if (nextGroups !== groupSignature) {
        groupSignature = nextGroups;
        const frag = document.createDocumentFragment();
        groups.forEach(g => frag.appendChild(button(g.label, {gsSection:g.id}, g.icon)));
        tabs.replaceChildren(frag);
      }
      // A language or unread-count update must not replace a focused tab.
      groups.forEach(g => {
        const label = tabs.querySelector('[data-gs-section="' + g.id + '"] .gs-label');
        if (label && label.textContent !== g.label) label.textContent = g.label;
      });
      const nextPages = group.pages.map(p => p.id).join('|');
      if (activeSection !== group.id || pageSignature !== nextPages) {
        activeSection = group.id;
        pageSignature = nextPages;
        const frag = document.createDocumentFragment();
        group.pages.forEach(p => frag.appendChild(button(p.label, {gsPage:p.id})));
        pages.replaceChildren(frag);
      }
      if (context.textContent !== group.label) context.textContent = group.label;
      group.pages.forEach(p => {
        const label = pages.querySelector('[data-gs-page="' + p.id + '"] .gs-label');
        if (label && label.textContent !== p.label) label.textContent = p.label;
      });
      markCurrent(tabs, 'gsSection', group.id);
      markCurrent(pages, 'gsPage', locationPage);
    }
    function schedule() {
      if (pending) return;
      pending = true;
      requestAnimationFrame(sync);
    }
    function openSection(id) {
      const group = sections().find(g => g.id === id);
      if (!group) return;
      const target = group.pages.find(p => p.id === lastPage[id]) || group.pages[0];
      if (target) openPage(target.id);
    }
    hud.addEventListener('click', event => {
      const section = event.target.closest('[data-gs-section]');
      if (section && hud.contains(section)) { openSection(section.dataset.gsSection); return; }
      const page = event.target.closest('[data-gs-page]');
      if (page && hud.contains(page)) openPage(page.dataset.gsPage);
    });
    hud.addEventListener('keydown', event => {
      const target = event.target.closest('button');
      if (!target || !body.classList.contains('game-shell') || document.querySelector('dialog[open]')) return;
      const container = target.closest('.gs-tabs,.gs-pages');
      if (!container) return;
      const items = Array.from(container.querySelectorAll('button'));
      let index = items.indexOf(target), next = -1;
      const step = getComputedStyle(container).direction === 'rtl' ? -1 : 1;
      if (event.key === 'ArrowRight') next = (index + step + items.length) % items.length;
      else if (event.key === 'ArrowLeft') next = (index - step + items.length) % items.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = items.length - 1;
      else if (event.key === 'ArrowDown' && container === tabs) {
        const to = pages.querySelector('[aria-current="page"]') || pages.querySelector('button');
        if (to) { event.preventDefault(); to.focus(); }
        return;
      } else if (event.key === 'ArrowUp' && container === pages) {
        const to = tabs.querySelector('[aria-current="page"]');
        if (to) { event.preventDefault(); to.focus(); }
        return;
      }
      if (next >= 0 && items[next]) { event.preventDefault(); items[next].focus(); }
    });
    document.addEventListener('keydown', event => {
      const target = event.target instanceof Element ? event.target : null;
      if (!body.classList.contains('game-shell') || !event.altKey || event.ctrlKey || event.metaKey ||
          !/^[1-6]$/.test(event.key) || (target && target.closest('input,textarea,select,[contenteditable="true"]')) ||
          document.querySelector('dialog[open]')) return;
      const group = sections()[Number(event.key) - 1];
      if (group) { event.preventDefault(); openSection(group.id); }
    });
    // The native league picker calculates its absolute position for a document
    // scroller. Add the panel's internal scroll offsets after its own handler
    // runs so it remains anchored in the fixed-screen layout.
    document.addEventListener('click', event => {
      if (!body.classList.contains('game-shell') || !(event.target instanceof Element)) return;
      const clicked = event.target.closest('[data-p-go="league"]');
      const panel = document.getElementById('p-league');
      const menu = document.getElementById('lgPills');
      // Another native capture handler can recreate the subnav before this
      // listener runs. The original event path still identifies its panel;
      // use the newly rendered button for the current screen coordinates.
      if (!clicked || !panel || !event.composedPath().includes(panel) ||
          !menu || !menu.classList.contains('open')) return;
      const trigger = panel.querySelector('.subtabs [data-p-go="league"]');
      if (!trigger) return;
      const r = trigger.getBoundingClientRect(), pr = panel.getBoundingClientRect();
      menu.style.top = (r.bottom - pr.top + panel.scrollTop + 8) + 'px';
      menu.style.left = Math.max(0, r.left - pr.left + panel.scrollLeft) + 'px';
    }, true);
    document.addEventListener('click', event => {
      if (dispatchingRoute || !(event.target instanceof Element)) return;
      // The app may re-render #sgTabs before this bubbling listener runs, so
      // match the detached tab itself rather than relying on its old parent.
      if (event.target.closest('#nav [data-p], [data-p-go], [data-sc-go], [data-sgt]')) {
        requestedAlias = null;
        schedule();
      }
    });
    window.addEventListener('hashchange', schedule);
    window.addEventListener('popstate', schedule);
    new MutationObserver(schedule).observe(originalNav, {
      childList:true, subtree:true, characterData:true, attributes:true,
      attributeFilter:['aria-current','hidden']
    });
    new MutationObserver(() => { toggleLabel(); schedule(); }).observe(document.documentElement, {
      attributes:true, attributeFilter:['lang']
    });

    // Public navigation interface for the following interaction milestone.
    window.GS = {sections, get mode() { return body.classList.contains('game-shell') ? 'game' : null; }};
    applyMode();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
