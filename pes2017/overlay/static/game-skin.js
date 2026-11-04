/* The Gaffer - GAME HUD skin + vector icon pack (pc414 / PES 2017 build)
 *
 * What this does, without touching the 2.8 MB index.html:
 *   1. adds a "game-skin" class to <body> (persisted, toggleable),
 *   2. injects a same-document SVG sprite of hand-drawn 24px vector icons,
 *   3. walks text nodes and swaps colorful emoji for those SVG icons,
 *      including content the app renders later (MutationObserver),
 *   4. adds a HUD strip, a skin toggle and a short boot intro.
 *
 * The original emoji character is kept in a visually hidden span inside each
 * icon wrapper, so textContent/innerText based logic in the original app keeps
 * seeing the same text.  Turning the skin off restores the plain emoji.
 *
 * No network requests, no external fonts, no dependencies.  Pure DOM + SVG.
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var XLINK = 'http://www.w3.org/1999/xlink';
  var SKIN_KEY = 'gaffer_game_skin';
  var INTRO_KEY = 'gaffer_game_intro';

  /* ------------------------------------------------------------------ *
   * 1. emoji -> icon id.  Single-codepoint keys only; the FE0F
   *    "emoji presentation" variant is added automatically below.
   * ------------------------------------------------------------------ */
  var BASE = {
    /* pitch & competition */
    '⚽': 'ball', '🏆': 'trophy', '🥇': 'trophy', '🥈': 'trophy', '👑': 'trophy',
    '🏟': 'stadium', '🏗': 'stadium', '🏁': 'flag', '⚑': 'flag',
    '🎯': 'target', '⚔': 'duel', '🎮': 'gamepad', '🎟': 'gamepad',
    '🎓': 'star', '🏅': 'trophy', '🟨': 'card', '⬡': 'badge',
    /* ratings, form, mood */
    '⭐': 'star', '🌟': 'star', '★': 'star', '☆': 'star', '✦': 'star',
    '🔥': 'fire', '⚡': 'bolt', '🔋': 'bolt', '⚠': 'warning',
    '✅': 'check', '✔': 'check', '✓': 'check', '❌': 'cross',
    '😠': 'mood', '😡': 'mood', '😌': 'mood', '☺': 'mood', '☹': 'mood',
    '🥶': 'mood', '🤫': 'mood', '🙅': 'no',
    /* money & market */
    '💶': 'money', '💰': 'coin', '💼': 'briefcase', '📁': 'briefcase',
    '📈': 'chart-up', '📊': 'chart-up', '📉': 'chart-down',
    '🛒': 'cart', '🏷': 'cart', '💔': 'heart',
    /* club / squad / staff */
    '👥': 'squad', '👤': 'squad', '🧓': 'squad', '🕴': 'squad',
    '🧤': 'glove', '👕': 'shirt', '👔': 'tie', '🎩': 'tie', '👟': 'boot',
    '🛡': 'shield', '🩹': 'bandage', '🩺': 'bandage', '💪': 'fitness',
    '🏋': 'fitness', '🌱': 'sprout', '🔭': 'telescope', '🏃': 'run',
    '👋': 'wave', '✋': 'wave', '🪑': 'badge', '🧱': 'badge',
    '🤝': 'deal', '🔁': 'swap', '🔄': 'swap', '⇄': 'swap',
    /* documents, comms, time, system */
    '📋': 'clipboard', '📄': 'clipboard', '📰': 'clipboard', '📖': 'clipboard',
    '📕': 'clipboard', '📅': 'calendar', '🗓': 'calendar',
    '💬': 'chat', '🎤': 'chat', '🎙': 'chat', '📣': 'chat', '📢': 'chat',
    '✍': 'pen', '✒': 'pen', '✎': 'pen', '✉': 'mail', '✂': 'scissors',
    '⚙': 'gear', '🔒': 'lock', '🔓': 'lock', '👀': 'eye',
    '💾': 'save', '📥': 'download', '🔊': 'volume', '🖥': 'gear',
    '🚪': 'door', '🎉': 'party', '🧩': 'badge', '🧭': 'compass',
    '🌍': 'globe', '🔭': 'telescope', '✚': 'plus',
    '↗': 'arrow-ur', '↘': 'arrow-dr', '⬆': 'arrow-up', '⬇': 'download',
    '⬅': 'arrow-left', '↩': 'swap', '↻': 'swap', '↺': 'swap',
    /* the long tail of single-use emoji (still vector, still consistent) */
    '🥉': 'trophy', '➜': 'arrow-ur', '🧪': 'badge', '🏛': 'stadium',
    '🏹': 'target', '🗡': 'duel', '🐢': 'badge', '🪂': 'badge',
    '♟': 'badge', '🎛': 'gear', '✈': 'arrow-ur', '🔎': 'search',
    '🧳': 'briefcase', '😄': 'mood', '🙂': 'mood', '😐': 'mood',
    '🙁': 'mood', '🧮': 'chart-up', '💡': 'star', '❤': 'heart',
    '🧬': 'badge', '😮': 'mood', '💨': 'bolt', '⚖': 'badge',
    '🟢': 'card', '🔴': 'card', '💸': 'money', '🌧': 'badge',
    '🚀': 'arrow-ur', '☰': 'gear', '🔔': 'volume', '❗': 'warning',
    '🧠': 'badge', '🧾': 'clipboard', '🧑': 'squad', '✨': 'star',
    '😞': 'mood', '🤯': 'mood', '🛟': 'shield', '♪': 'volume',
    '👨': 'squad', '👩': 'squad', '👧': 'squad', '📨': 'mail',
    '🦈': 'badge', '🏠': 'home', '📚': 'clipboard'
  };

  var MAP = {};
  Object.keys(BASE).forEach(function (k) {
    MAP[k] = BASE[k];
    MAP[k + '\uFE0F'] = BASE[k];
  });

  var keys = Object.keys(MAP).sort(function (a, b) { return b.length - a.length; });
  var escapeRe = function (s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); };
  var pattern = keys.map(escapeRe).join('|');
  var TEST = new RegExp(pattern);
  var RE = new RegExp(pattern, 'g');

  /* ------------------------------------------------------------------ *
   * 2. SVG sprite.  One consistent 24x24 stroke grid, currentColor,
   *    no bitmap assets, no emoji fonts.
   * ------------------------------------------------------------------ */
  var S = [
    '<symbol id="gi-ball" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8.5l3.1 2.3-1.2 3.6h-3.8L8.9 10.8z"/><path d="M12 8.5V3M15.1 10.8l4.6-.8M13.9 14.4l2.8 4M10.1 14.4l-2.8 4M8.9 10.8l-4.6-.8"/></symbol>',
    '<symbol id="gi-trophy" viewBox="0 0 24 24"><path d="M7 4h10v5.5a5 5 0 0 1-10 0z"/><path d="M7 5H4v2a3 3 0 0 0 3 3M17 5h3v2a3 3 0 0 1-3 3"/><path d="M12 14.5V18M8.5 21h7M10 18h4"/></symbol>',
    '<symbol id="gi-stadium" viewBox="0 0 24 24"><path d="M3 10c0-4 4-6 9-6s9 2 9 6v3H3z"/><path d="M3 13v7M21 13v7M7 20v-7M17 20v-7M2 20h20"/></symbol>',
    '<symbol id="gi-flag" viewBox="0 0 24 24"><path d="M5 21V3M5 4h13l-2.5 4L18 12H5"/></symbol>',
    '<symbol id="gi-target" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/></symbol>',
    '<symbol id="gi-duel" viewBox="0 0 24 24"><path d="M4 3l4 1-1 4-3-3zM20 3l-4 1 1 4 3-3zM6.5 8L19 20M17.5 8L5 20"/><path d="M3 21l3-3M21 21l-3-3"/></symbol>',
    '<symbol id="gi-gamepad" viewBox="0 0 24 24"><path d="M7.5 8h9a4 4 0 0 1 3.8 4.3l-.5 3.4a2.7 2.7 0 0 1-4.6 1.4L14 15.5h-4l-1.2 1.6a2.7 2.7 0 0 1-4.6-1.4l-.5-3.4A4 4 0 0 1 7.5 8z"/><path d="M7.5 11v3M6 12.5h3M16.5 11.5h.01M18 14h.01"/></symbol>',
    '<symbol id="gi-card" viewBox="0 0 24 24"><rect x="7" y="2.5" width="10" height="19" rx="1.5"/></symbol>',
    '<symbol id="gi-badge" viewBox="0 0 24 24"><path d="M12 2l8.7 5v10L12 22l-8.7-5V7z"/><path d="M12 7.5l1.4 2.9 3.2.5-2.3 2.2.5 3.2-2.8-1.5-2.8 1.5.5-3.2-2.3-2.2 3.2-.5z"/></symbol>',
    '<symbol id="gi-star" viewBox="0 0 24 24"><path d="M12 2.8l2.9 5.9 6.5 1-4.7 4.6 1.1 6.5L12 17.7l-5.8 3.1 1.1-6.5-4.7-4.6 6.5-1z"/></symbol>',
    '<symbol id="gi-fire" viewBox="0 0 24 24"><path d="M12 21a6.5 6.5 0 0 0 6.5-6.5c0-4-3-6.5-4.5-9.5 0 3-2 4-3 5-1-1-1-2-1-3-2.5 2.2-4.5 4.7-4.5 7.5A6.5 6.5 0 0 0 12 21z"/><path d="M12 21a3 3 0 0 0 3-3c0-1.8-1.2-3-2-4-.2 1.5-1 2-2 2.5-.4-1 0-2 0-2.5-1.3 1-2 2.4-2 4a3 3 0 0 0 3 3z"/></symbol>',
    '<symbol id="gi-bolt" viewBox="0 0 24 24"><path d="M13.5 2L5 13.5h6L10 22l9-11.5h-6z"/></symbol>',
    '<symbol id="gi-warning" viewBox="0 0 24 24"><path d="M12 3.2L21.5 20.5h-19z"/><path d="M12 9.5v5M12 17.6h.01"/></symbol>',
    '<symbol id="gi-check" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M7.8 12.3l2.9 2.9 5.5-5.9"/></symbol>',
    '<symbol id="gi-cross" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8.8 8.8l6.4 6.4M15.2 8.8l-6.4 6.4"/></symbol>',
    '<symbol id="gi-mood" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8.5 14.5c.9 1 2.2 1.5 3.5 1.5s2.6-.5 3.5-1.5M9 9.3h.01M15 9.3h.01"/></symbol>',
    '<symbol id="gi-no" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/></symbol>',
    '<symbol id="gi-money" viewBox="0 0 24 24"><rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/><path d="M6 10h.01M18 14h.01"/></symbol>',
    '<symbol id="gi-coin" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 6.5v11M9 9.5h4.5a2 2 0 0 1 0 4H9h5"/></symbol>',
    '<symbol id="gi-briefcase" viewBox="0 0 24 24"><rect x="2.5" y="7" width="19" height="13.5" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M2.5 12.5h19M11 12.5v2h2v-2"/></symbol>',
    '<symbol id="gi-chart-up" viewBox="0 0 24 24"><path d="M3 20.5h18M4 16.5l5-5 4 3 6.5-7.5"/><path d="M16 7h3.5v3.5"/></symbol>',
    '<symbol id="gi-chart-down" viewBox="0 0 24 24"><path d="M3 20.5h18M4 8l5 5 4-3 6.5 7.5"/><path d="M16 17.5h3.5V14"/></symbol>',
    '<symbol id="gi-cart" viewBox="0 0 24 24"><path d="M2.5 4h2.2l2.3 11h10.5l2-7.5H6.2"/><circle cx="9" cy="19" r="1.4"/><circle cx="17" cy="19" r="1.4"/></symbol>',
    '<symbol id="gi-heart" viewBox="0 0 24 24"><path d="M12 20.5C7 16.7 3 13.6 3 9.4A4.6 4.6 0 0 1 12 6.6a4.6 4.6 0 0 1 9 2.8c0 4.2-4 7.3-9 11.1z"/><path d="M12.5 8.5l-2 4h3l-2 4"/></symbol>',
    '<symbol id="gi-squad" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3.2 20v-1.6A5.8 5.8 0 0 1 9 12.6a5.8 5.8 0 0 1 5.8 5.8V20"/><circle cx="17.5" cy="9" r="2.3"/><path d="M16 14.2a4.6 4.6 0 0 1 4.5 4.6V20"/></symbol>',
    '<symbol id="gi-glove" viewBox="0 0 24 24"><path d="M7 12V6.5a1.5 1.5 0 0 1 3 0V10V5.5a1.5 1.5 0 0 1 3 0V10V7a1.5 1.5 0 0 1 3 0v6c0 3.3-2.2 5.7-5.5 5.7h-1A4.5 4.5 0 0 1 5 14.2l-1.2-2.5a1.6 1.6 0 0 1 2.7-1.6z"/></symbol>',
    '<symbol id="gi-shirt" viewBox="0 0 24 24"><path d="M8.5 3L12 5l3.5-2 5 3-2 4-2-1v12h-9V9l-2 1-2-4z"/><path d="M9.5 6.2a2.5 2.5 0 0 0 5 0"/></symbol>',
    '<symbol id="gi-tie" viewBox="0 0 24 24"><path d="M9 3l3 2 3-2 2.5 3-2 3-1.5 11h-4L8.5 9l-2-3z"/><path d="M10.5 5.5h3"/></symbol>',
    '<symbol id="gi-boot" viewBox="0 0 24 24"><path d="M3.5 6.5h5l1 6.5 6 2c2 .7 4 2.2 4 4.3V21h-16z"/><path d="M3.5 18h16M7 10l3 1.5"/></symbol>',
    '<symbol id="gi-shield" viewBox="0 0 24 24"><path d="M12 2l8 3v6c0 5-3.4 8.6-8 11-4.6-2.4-8-6-8-11V5z"/><path d="M8.8 12l2.2 2.2 4.2-4.4"/></symbol>',
    '<symbol id="gi-bandage" viewBox="0 0 24 24"><rect x="2.5" y="8.5" width="19" height="7" rx="3.5" transform="rotate(-32 12 12)"/><path d="M10 10.5h.01M12 12h.01M14 13.5h.01"/></symbol>',
    '<symbol id="gi-fitness" viewBox="0 0 24 24"><path d="M3 9.5h2.5v5H3zM18.5 9.5H21v5h-2.5zM5.5 11h13v2h-13zM8 7.5v9M16 7.5v9"/></symbol>',
    '<symbol id="gi-sprout" viewBox="0 0 24 24"><path d="M12 21v-9"/><path d="M12 14c-4 0-6-3-6-7 4 0 6 3 6 7zM12 14c4 0 6-3 6-7-4 0-6 3-6 7z"/></symbol>',
    '<symbol id="gi-telescope" viewBox="0 0 24 24"><path d="M2.5 13.5l10.5-5 2.2 4.2-10.5 5z"/><path d="M13 8.5l4-2 2.2 4.2-4 2M8.5 18v3M6 21h6"/></symbol>',
    '<symbol id="gi-run" viewBox="0 0 24 24"><circle cx="14.5" cy="4.8" r="2"/><path d="M10 21l2.5-5.5-3-3 1-5 4 2 3 1M8 13l-3.5 3M13 12.5l4 1"/></symbol>',
    '<symbol id="gi-wave" viewBox="0 0 24 24"><path d="M7.5 12V5a1.5 1.5 0 0 1 3 0v6V4a1.5 1.5 0 0 1 3 0v7V6.5a1.5 1.5 0 0 1 3 0v6V9a1.5 1.5 0 0 1 3 0v6c0 4-2.8 6-6.5 6-3 0-5-2-6-4l-1.8-3.5a1.6 1.6 0 0 1 2.7-1.7z"/></symbol>',
    '<symbol id="gi-deal" viewBox="0 0 24 24"><path d="M2.5 9.5l4-4 3.5 2 4-2 4 4 3.5-1-1 6-4 3.5-7-1.5-3-3-4 1z"/><path d="M9 13.5l3 2.5"/></symbol>',
    '<symbol id="gi-swap" viewBox="0 0 24 24"><path d="M3 8.5h14M14 5.5l3 3-3 3M21 15.5H7M10 12.5l-3 3 3 3"/></symbol>',
    '<symbol id="gi-clipboard" viewBox="0 0 24 24"><rect x="4.5" y="4" width="15" height="17" rx="2"/><path d="M9 4V2.8h6V4M8 9h8M8 13h8M8 17h5"/></symbol>',
    '<symbol id="gi-calendar" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4M7 14h2M11 14h2M15 14h2M7 17.5h2"/></symbol>',
    '<symbol id="gi-chat" viewBox="0 0 24 24"><path d="M3.5 4h17v12H9l-5.5 4z"/><path d="M7.5 8.5h9M7.5 12h6"/></symbol>',
    '<symbol id="gi-pen" viewBox="0 0 24 24"><path d="M4 20l4.2-1L19 8.2 15.8 5 5 15.8z"/><path d="M14.2 6.6l3.2 3.2M4 20h4.2"/></symbol>',
    '<symbol id="gi-mail" viewBox="0 0 24 24"><rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M2.5 7l9.5 6 9.5-6"/></symbol>',
    '<symbol id="gi-scissors" viewBox="0 0 24 24"><circle cx="6" cy="6.5" r="2.3"/><circle cx="6" cy="17.5" r="2.3"/><path d="M8 8L20 19M8 16L20 5"/></symbol>',
    '<symbol id="gi-gear" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/><circle cx="12" cy="12" r="8"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M5 5l1.8 1.8M17.2 17.2L19 19M19 5l-1.8 1.8M6.8 17.2L5 19"/></symbol>',
    '<symbol id="gi-lock" viewBox="0 0 24 24"><rect x="4.5" y="10" width="15" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14.5v2.5"/></symbol>',
    '<symbol id="gi-eye" viewBox="0 0 24 24"><path d="M2 12s3.8-6 10-6 10 6 10 6-3.8 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.6"/></symbol>',
    '<symbol id="gi-save" viewBox="0 0 24 24"><path d="M4 3h12.5L20.5 7v14H4z"/><path d="M8 3v6h8V3M8 21v-7h8v7"/></symbol>',
    '<symbol id="gi-download" viewBox="0 0 24 24"><path d="M12 3v12M7.5 10.5l4.5 4.5 4.5-4.5M3.5 20.5h17"/></symbol>',
    '<symbol id="gi-volume" viewBox="0 0 24 24"><path d="M3.5 9h4l5-4v14l-5-4h-4z"/><path d="M16.5 9a4.2 4.2 0 0 1 0 6M19 6.5a7.5 7.5 0 0 1 0 11"/></symbol>',
    '<symbol id="gi-door" viewBox="0 0 24 24"><path d="M4 21V4a1 1 0 0 1 1-1h10v18M4 21h16M15 12h1.2"/></symbol>',
    '<symbol id="gi-party" viewBox="0 0 24 24"><path d="M3.5 20.5L10 6l8 8z"/><path d="M14 3l1 2.2M19 7l2 1M19 3l.6 1.6M7 3l1 2M4 8l2 .8"/></symbol>',
    '<symbol id="gi-compass" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/></symbol>',
    '<symbol id="gi-globe" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3.2 3.2 3.2 14.8 0 18M12 3c-3.2 3.2-3.2 14.8 0 18"/></symbol>',
    '<symbol id="gi-plus" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></symbol>',
    '<symbol id="gi-arrow-ur" viewBox="0 0 24 24"><path d="M6 18L18 6M9 6h9v9"/></symbol>',
    '<symbol id="gi-arrow-dr" viewBox="0 0 24 24"><path d="M6 6l12 12M18 9v9H9"/></symbol>',
    '<symbol id="gi-arrow-up" viewBox="0 0 24 24"><path d="M12 20V4M6.5 9.5L12 4l5.5 5.5"/></symbol>',
    '<symbol id="gi-arrow-left" viewBox="0 0 24 24"><path d="M20 12H4M10 6.5L4 12l6 5.5"/></symbol>',
    '<symbol id="gi-pitch" viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="1"/><path d="M12 4v16M2 12h20"/><circle cx="12" cy="12" r="3"/><circle cx="12" cy="7" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="17" r="1" fill="currentColor" stroke="none"/></symbol>',
    '<symbol id="gi-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6h.01"/></symbol>',
    '<symbol id="gi-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 6.8V12l3.4 2.2"/></symbol>',
    '<symbol id="gi-home" viewBox="0 0 24 24"><path d="M3 11L12 3l9 8M5.5 9.5V21h13V9.5M10 21v-6h4v6"/></symbol>',
    '<symbol id="gi-search" viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/></symbol>'
  ];

  var SPRITE = '<svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" ' +
    'style="position:absolute;width:0;height:0;overflow:hidden">' + S.join('') + '</svg>';

  /* ------------------------------------------------------------------ *
   * 3. DOM helpers
   * ------------------------------------------------------------------ */
  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  function injectSprite() {
    if (document.getElementById('gi-sprite')) return;
    var holder = document.createElement('div');
    holder.id = 'gi-sprite';
    holder.innerHTML = SPRITE;
    document.body.insertBefore(holder, document.body.firstChild);
  }

  function makeIcon(id, emoji) {
    var wrap = document.createElement('span');
    wrap.className = 'gi-wrap';
    wrap.setAttribute('data-gi-emoji', emoji);

    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'gi gi-' + id);
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    var use = document.createElementNS(NS, 'use');
    use.setAttribute('href', '#gi-' + id);
    use.setAttributeNS(XLINK, 'xlink:href', '#gi-' + id);
    svg.appendChild(use);
    wrap.appendChild(svg);

    /* keep the original character in the accessibility/text layer */
    var sr = document.createElement('span');
    sr.className = 'gi-sr';
    sr.setAttribute('data-gi-keep', '1');
    sr.textContent = emoji;
    wrap.appendChild(sr);
    return wrap;
  }

  var SKIP = 'script,style,textarea,input,option,title,[data-gi-keep],svg';

  function skipped(p) {
    return !p || !p.closest || p.closest(SKIP);
  }

  function convertText(n) {
    var text = n.nodeValue;
    if (!text || !TEST.test(text)) return;
    if (skipped(n.parentElement)) return;
    RE.lastIndex = 0;
    var frag = document.createDocumentFragment(), m, last = 0;
    while ((m = RE.exec(text))) {
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      frag.appendChild(makeIcon(MAP[m[0]], m[0]));
      last = m.index + m[0].length;
    }
    if (!last) return;
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    if (n.parentNode) n.parentNode.replaceChild(frag, n);
  }

  function convertTree(root) {
    if (!root) return;
    if (root.nodeType === 3) { convertText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1 && root.matches && root.matches(SKIP)) return;
    var nodes = [], w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!n.nodeValue || !TEST.test(n.nodeValue)) return NodeFilter.FILTER_REJECT;
        if (skipped(n.parentElement)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    while (w.nextNode()) nodes.push(w.currentNode);
    for (var i = 0; i < nodes.length; i++) convertText(nodes[i]);
  }

  function restore() {
    var list = document.querySelectorAll('.gi-wrap');
    for (var i = 0; i < list.length; i++) {
      var w = list[i];
      var e = w.getAttribute('data-gi-emoji') || '';
      if (w.parentNode) w.parentNode.replaceChild(document.createTextNode(e), w);
    }
  }

  /* ------------------------------------------------------------------ *
   * 4. HUD strip + toggle + boot intro
   * ------------------------------------------------------------------ */
  function buildHud() {
    if (document.querySelector('.gi-hud')) return;
    var app = document.querySelector('.app');
    if (!app) return;                              // pes17.html has its own header
    var hud = document.createElement('div');
    hud.className = 'gi-hud';
    hud.innerHTML =
      '<span class="gi-hud-mark">TG</span>' +
      '<span class="gi-hud-title">THE GAFFER</span>' +
      '<span class="gi-hud-slash">//</span>' +
      '<span class="gi-hud-mode">PES 2017 &nbsp;&middot;&nbsp; MASTER LEAGUE</span>' +
      '<span class="gi-hud-right"><i class="gi-led"></i> SAVE LINK LOCAL' +
      '<span class="gi-hud-sep">|</span> PC414</span>';
    document.body.insertBefore(hud, app);
  }

  function buildToggle() {
    if (document.getElementById('gi-toggle')) return;
    var b = document.createElement('button');
    b.id = 'gi-toggle';
    b.type = 'button';
    b.className = 'gi-toggle';
    b.innerHTML = '<svg class="gi" viewBox="0 0 24 24" aria-hidden="true"><use href="#gi-badge"></use></svg>' +
      '<span class="gi-toggle-label">GAME UI</span><i class="gi-led"></i>';
    b.title = 'Switch between the game HUD skin and the original website look';
    document.body.appendChild(b);
    b.addEventListener('click', function () {
      set(!document.body.classList.contains('game-skin'), true);
    });
  }

  function set(on, save) {
    document.body.classList.toggle('game-skin', !!on);
    if (on) convertTree(document.body); else restore();
    var label = document.querySelector('.gi-toggle-label');
    if (label) label.textContent = on ? 'GAME UI' : 'CLASSIC UI';
    if (save) lsSet(SKIN_KEY, on ? '1' : '0');
  }

  function boot() {
    if (!document.body.classList.contains('game-skin')) return;
    if (!document.querySelector('.app')) return;        // tools page: no intro
    try { if (sessionStorage.getItem('gi_boot') === '1') return; } catch (e) {}
    if (lsGet(INTRO_KEY) === '0') return;
    try { sessionStorage.setItem('gi_boot', '1'); } catch (e) {}

    var el = document.createElement('div');
    el.className = 'gi-boot';
    el.innerHTML =
      '<div class="gi-boot-inner">' +
      '<div class="gi-boot-badge"><svg class="gi" viewBox="0 0 24 24" aria-hidden="true"><use href="#gi-pitch"></use></svg></div>' +
      '<div class="gi-boot-kicker">THE GAFFER &nbsp;//&nbsp; PC414</div>' +
      '<div class="gi-boot-title">PES 2017 <span>MASTER LEAGUE</span></div>' +
      '<div class="gi-boot-bar"><i></i></div>' +
      '<div class="gi-boot-sub">LOADING CAREER DATA &nbsp;&middot;&nbsp; LOCAL SAVE LINK</div>' +
      '<button type="button" class="gi-boot-skip" data-gi-nointro>SKIP &amp; DON\'T SHOW AGAIN</button>' +
      '</div>';
    document.body.appendChild(el);

    var done = false;
    function close() {
      if (done) return;
      done = true;
      el.classList.add('gi-boot-out');
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 480);
    }
    setTimeout(close, 1900);
    el.addEventListener('click', function (ev) {
      if (ev.target.closest('[data-gi-nointro]')) lsSet(INTRO_KEY, '0');
      close();
    });
    document.addEventListener('keydown', close, { once: true });
  }

  /* ------------------------------------------------------------------ *
   * 5. boot the skin
   * ------------------------------------------------------------------ */
  function init() {
    injectSprite();
    buildHud();
    buildToggle();

    var on = lsGet(SKIN_KEY) !== '0';    // game skin is the default
    set(on, false);

    /* the app is heavily dynamic: convert newly rendered nodes too */
    var pending = [], scheduled = false;
    function flush() {
      scheduled = false;
      var list = pending.slice();
      pending.length = 0;
      for (var i = 0; i < list.length; i++) convertTree(list[i]);
    }
    var mo = new MutationObserver(function (muts) {
      if (!document.body.classList.contains('game-skin')) return;
      for (var i = 0; i < muts.length; i++) {
        var m = muts[i];
        if (m.type === 'characterData' && m.target.nodeType === 3) pending.push(m.target);
        for (var j = 0; j < m.addedNodes.length; j++) {
          var n = m.addedNodes[j];
          if (n.nodeType === 1 || n.nodeType === 3) pending.push(n);
        }
      }
      if (pending.length && !scheduled) { scheduled = true; requestAnimationFrame(flush); }
    });
    mo.observe(document.documentElement, { childList: true, subtree: true, characterData: true });

    boot();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
