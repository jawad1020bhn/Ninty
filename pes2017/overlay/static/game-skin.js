/* =====================================================================
   THE GAFFER - MATCHDAY IDENTITY  (pc414 / PES 2017)  -  r10
   ---------------------------------------------------------------------
   * One coherent, hand-drawn SVG library.  Every pictograph that appears
     in the shipped UI has a purpose-specific symbol; an unknown glyph is
     hidden (its text stays in the DOM) instead of being faked as a badge.
   * Stadium Dark palette with a club colour as the only accent.
   * Console top navigation + subsection bar + quick switcher hook.
   * Loaded after the app's own scripts; everything is opt-out via the
     CLASSIC UI toggle and scoped under body.game-skin.
   ===================================================================== */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var XLINK = 'http://www.w3.org/1999/xlink';
  var SKIN_KEY = 'gaffer_game_skin';
  var INTRO_KEY = 'gaffer_game_skin_intro';
  var THEME_KEY = 'gaffer_game_theme';   /* r5 key kept: saved accent survives the r10 refresh */
  var SOUND_KEY = 'gaffer_game_sound';
  var THEMES = ['club', 'gold', 'pitch'];

  /* ------------------------------------------------------------- icon map
     Key = exact glyph (including variation selectors), value = symbol id.
     FE0F variants are intentional duplicates: Unicode emoji presentation. */
var BASE = {
    '⚽': 'ball',
    '🏆': 'trophy',
    '🥇': 'medal',
    '🥈': 'medal',
    '👑': 'crown',
    '🏟': 'stadium',
    '🏗': 'stadium',
    '🏁': 'flag',
    '⚑': 'flag',
    '🎯': 'target',
    '⚔': 'duel',
    '🎮': 'gamepad',
    '🎟': 'match',
    '🎓': 'training',
    '🏅': 'medal',
    '🟨': 'card',
    '⬡': 'formation',
    '⭐': 'star',
    '🌟': 'star',
    '★': 'star',
    '☆': 'star',
    '✦': 'star',
    '🔥': 'fire',
    '⚡': 'bolt',
    '🔋': 'fitness',
    '⚠': 'warning',
    '✅': 'check',
    '✔': 'check',
    '✓': 'check',
    '❌': 'cross',
    '😠': 'angry',
    '😡': 'angry',
    '😌': 'calm',
    '☺': 'happy',
    '☹': 'sad',
    '🥶': 'calm',
    '🤫': 'calm',
    '🙅': 'no',
    '💶': 'finance',
    '💰': 'coin',
    '💼': 'briefcase',
    '📁': 'briefcase',
    '📈': 'stats',
    '📊': 'stats',
    '📉': 'chart-down',
    '🛒': 'cart',
    '🏷': 'cart',
    '💔': 'heart',
    '👥': 'squad',
    '👤': 'player',
    '🧓': 'staff',
    '🕴': 'manager',
    '🧤': 'glove',
    '👕': 'shirt',
    '👔': 'manager',
    '🎩': 'manager',
    '👟': 'boot',
    '🛡': 'shield',
    '🩹': 'injury',
    '🩺': 'injury',
    '💪': 'fitness',
    '🏋': 'fitness',
    '🌱': 'youth',
    '🔭': 'scout',
    '🏃': 'pace',
    '👋': 'wave',
    '✋': 'wave',
    '🪑': 'bench',
    '🧱': 'defence',
    '🤝': 'contract',
    '🔁': 'substitute',
    '🔄': 'refresh',
    '⇄': 'swap',
    '📋': 'clipboard',
    '📄': 'contract',
    '📰': 'news',
    '📖': 'book',
    '📕': 'book',
    '📅': 'calendar',
    '🗓': 'calendar',
    '💬': 'chat',
    '🎤': 'press',
    '🎙': 'press',
    '📣': 'news',
    '📢': 'news',
    '✍': 'pen',
    '✒': 'pen',
    '✎': 'pen',
    '✉': 'mail',
    '✂': 'scissors',
    '⚙': 'gear',
    '🔒': 'lock',
    '🔓': 'lock',
    '👀': 'scout',
    '💾': 'save',
    '📥': 'download',
    '🔊': 'volume',
    '🖥': 'gear',
    '🚪': 'door',
    '🎉': 'party',
    '🧩': 'tactics',
    '🧭': 'compass',
    '🌍': 'globe',
    '✚': 'plus',
    '↗': 'arrow-ur',
    '↘': 'arrow-dr',
    '⬆': 'arrow-up',
    '⬇': 'download',
    '⬅': 'arrow-left',
    '↩': 'undo',
    '↻': 'refresh',
    '↺': 'refresh',
    '🥉': 'medal',
    '➜': 'arrow-ur',
    '🧪': 'training',
    '🏛': 'stadium',
    '🏹': 'target',
    '🗡': 'duel',
    '🐢': 'fitness',
    '🪂': 'table',
    '♟': 'tactics',
    '🎛': 'gear',
    '✈': 'match',
    '🔎': 'search',
    '🧳': 'transfer',
    '😄': 'happy',
    '🙂': 'happy',
    '😐': 'calm',
    '🙁': 'sad',
    '🧮': 'finance',
    '💡': 'tactics',
    '❤': 'heart',
    '🧬': 'youth',
    '😮': 'calm',
    '💨': 'pace',
    '⚖': 'contract',
    '🟢': 'status',
    '🔴': 'status',
    '💸': 'finance',
    '🌧': 'weather',
    '🚀': 'pace',
    '☰': 'menu',
    '🔔': 'bell',
    '❗': 'warning',
    '🧠': 'tactics',
    '🧾': 'contract',
    '🧑': 'player',
    '✨': 'form',
    '😞': 'sad',
    '🤯': 'angry',
    '🛟': 'shield',
    '♪': 'volume',
    '👨': 'player',
    '👩': 'player',
    '👧': 'player',
    '📨': 'mail',
    '🦈': 'transfer',
    '🏠': 'home',
    '📚': 'book',
    '✕': 'close',
    '✗': 'close',
    '✖': 'close',
    '→': 'arrow-right',
    '←': 'arrow-left',
    '↑': 'arrow-up',
    '↓': 'arrow-down',
    '↔': 'arrow-lr',
    '⇢': 'arrow-right',
    '↪': 'arrow-hook',
    '⬑': 'arrow-ur',
    '⬒': 'arrow-up',
    '🅰': 'rating',
    '🃏': 'card',
    '🆕': 'news',
    '😮\u200d💨': 'mood',
    '🧑\u200d💼': 'briefcase',
    '👨\u200d👩\u200d👧': 'squad'
  };

  var MAP = {};
  Object.keys(BASE).forEach(function (k) { MAP[k] = BASE[k]; });

  var keys = Object.keys(MAP).sort(function (a, b) { return b.length - a.length; });
  var ESC = keys.map(function (s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }).join('|');
  var VS16 = '\\u{FE0F}?';
  var ZWJ = '(?:\\u{200D}' + '(?:' + ESC + ')' + VS16 + ')*';

  var PICTO = '[\\u{1F000}-\\u{1FAFF}\\u{2600}-\\u{27BF}\\u{2B00}-\\u{2BFF}\\u{2190}-\\u{21FF}\\u{2300}-\\u{23FF}\\u{25A0}-\\u{25FF}\\u{FE0F}\\u{20E3}]';
  var CATCH = '(?:' + PICTO + VS16 + ZWJ + ')+';
  var exact = '(?:' + ESC + ')' + VS16 + ZWJ;
  var pattern = exact + '|' + CATCH;
  var TEST = new RegExp(pattern, 'u');
  var RE = new RegExp(pattern, 'gu');

  /* r10: no more "unknown symbol -> generic badge".  An unmapped glyph is
     kept as text in an accessible hidden span, never drawn as a fake icon. */
  function iconId(s) {
    if (MAP[s]) return MAP[s];
    var cp = s.codePointAt(0);
    if (cp >= 0x2190 && cp <= 0x21FF) return 'arrow-right';
    if (cp === 0x2715 || cp === 0x2716 || cp === 0x2717) return 'close';
    return null;
  }

  /* ------------------------------------------------------------- sprite */
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
    '<symbol id="gi-arrow-right" viewBox="0 0 24 24"><path d="M4 12h16M14 6l6 6-6 6"/></symbol>',
    '<symbol id="gi-arrow-down" viewBox="0 0 24 24"><path d="M12 4v16M6.5 14.5L12 20l5.5-5.5"/></symbol>',
    '<symbol id="gi-arrow-lr" viewBox="0 0 24 24"><path d="M3 12h18M7 8l-4 4 4 4M17 8l4 4-4 4"/></symbol>',
    '<symbol id="gi-arrow-hook" viewBox="0 0 24 24"><path d="M8 6l4 4-4 4M12 10h4a4 4 0 0 1 0 8h-3"/></symbol>',
    '<symbol id="gi-close" viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M8.5 8.5l7 7M15.5 8.5l-7 7"/></symbol>',
    '<symbol id="gi-pitch" viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="1"/><path d="M12 4v16M2 12h20"/><circle cx="12" cy="12" r="3"/><circle cx="12" cy="7" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="17" r="1" fill="currentColor" stroke="none"/></symbol>',
    '<symbol id="gi-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6h.01"/></symbol>',
    '<symbol id="gi-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 6.8V12l3.4 2.2"/></symbol>',
    '<symbol id="gi-home" viewBox="0 0 24 24"><path d="M3 11L12 3l9 8M5.5 9.5V21h13V9.5M10 21v-6h4v6"/></symbol>',
    '<symbol id="gi-search" viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/></symbol>',
    '<symbol id="gi-formation" viewBox="0 0 24 24"><path d="M3 4h18v16H3z"/><path d="M12 4v16M3 12h18"/><circle cx="7" cy="8" r="1"/><circle cx="17" cy="8" r="1"/><circle cx="7" cy="16" r="1"/><circle cx="17" cy="16" r="1"/></symbol>',
    '<symbol id="gi-tactics" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M6 16l4-4 3 2 5-6"/><path d="M15 8h3v3"/></symbol>',
    '<symbol id="gi-training" viewBox="0 0 24 24"><circle cx="12" cy="7" r="3"/><path d="M4 20l3-6h10l3 6M8 14l-2 6M16 14l2 6"/><path d="M12 10v4"/></symbol>',
    '<symbol id="gi-contract" viewBox="0 0 24 24"><path d="M5 3h10l4 4v14H5z"/><path d="M15 3v4h4M8 12h8M8 15h5"/><path d="M8 18c2-1 3 1 5 0s2-1 3 0"/></symbol>',
    '<symbol id="gi-transfer" viewBox="0 0 24 24"><circle cx="5" cy="8" r="2.2"/><path d="M2 18v-3a4 4 0 0 1 4-4h3"/><circle cx="19" cy="16" r="2.2"/><path d="M22 6v3a4 4 0 0 1-4 4h-3"/><path d="M9 11h6M13 9l2 2-2 2M15 15H9M11 13l-2 2 2 2"/></symbol>',
    '<symbol id="gi-injury" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M7 12h10"/></symbol>',
    '<symbol id="gi-finance" viewBox="0 0 24 24"><rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/><path d="M6 9.5h.01M18 14.5h.01M2.5 9h19"/></symbol>',
    '<symbol id="gi-competition" viewBox="0 0 24 24"><path d="M7 4h10v5.5a5 5 0 0 1-10 0z"/><path d="M7 5H4v2a3 3 0 0 0 3 3M17 5h3v2a3 3 0 0 1-3 3M12 14.5V18M8.5 21h7"/><path d="M3 4l2 2M21 4l-2 2"/></symbol>',
    '<symbol id="gi-news" viewBox="0 0 24 24"><path d="M3 5h15v14H5a2 2 0 0 1-2-2z"/><path d="M18 9h3v8a2 2 0 0 1-2 2M6 8h9M6 11h9M6 14h6"/></symbol>',
    '<symbol id="gi-book" viewBox="0 0 24 24"><path d="M12 6c-2.5-2-5-2-8-1v13c3-1 5.5-1 8 1 2.5-2 5-2 8-1V5c-3-1-5.5-1-8 1z"/><path d="M12 6v13"/></symbol>',
    '<symbol id="gi-scout" viewBox="0 0 24 24"><circle cx="10.5" cy="9" r="5.5"/><path d="M15 13.5L21 20"/><circle cx="10.5" cy="7.5" r="1.8"/><path d="M7 14a4 4 0 0 1 7 2"/></symbol>',
    '<symbol id="gi-youth" viewBox="0 0 24 24"><circle cx="12" cy="6" r="2.4"/><path d="M8 20v-5a4 4 0 0 1 8 0v5"/><path d="M12 20v-6M12 14c-3 0-4-2-4-4 3 0 4 2 4 4zM12 14c3 0 4-2 4-4-3 0-4 2-4 4z"/></symbol>',
    '<symbol id="gi-player" viewBox="0 0 24 24"><circle cx="12" cy="7" r="3.4"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/></symbol>',
    '<symbol id="gi-staff" viewBox="0 0 24 24"><circle cx="10" cy="7" r="3"/><path d="M3.5 20v-1.5A5.5 5.5 0 0 1 9 13h1"/><rect x="14" y="12" width="7" height="9" rx="1"/><path d="M16 15h3M16 17.5h3"/></symbol>',
    '<symbol id="gi-manager" viewBox="0 0 24 24"><circle cx="12" cy="6.5" r="3.2"/><path d="M5 21v-2a7 7 0 0 1 14 0v2"/><path d="M12 10l-1.6 2.5 1.6 5 1.6-5z"/></symbol>',
    '<symbol id="gi-substitute" viewBox="0 0 24 24"><path d="M4 7h11M12 4l3 3-3 3M20 17H9M12 14l-3 3 3 3"/><rect x="2.5" y="3" width="4" height="18" rx="1"/></symbol>',
    '<symbol id="gi-bench" viewBox="0 0 24 24"><path d="M3 11h18v3H3zM5 14v6M19 14v6M3 8h18M7 8V5h10v3"/></symbol>',
    '<symbol id="gi-medal" viewBox="0 0 24 24"><circle cx="12" cy="15" r="5"/><path d="M8 3l2.5 7M16 3l-2.5 7M12 12.5l.9 1.9 2 .3-1.5 1.4.4 2-1.8-1-1.8 1 .4-2-1.5-1.4 2-.3z"/></symbol>',
    '<symbol id="gi-crown" viewBox="0 0 24 24"><path d="M3 7l4 4 5-7 5 7 4-4-2 12H5z"/><path d="M5 19h14"/></symbol>',
    '<symbol id="gi-pace" viewBox="0 0 24 24"><path d="M2 8h9M2 12h6M2 16h8"/><path d="M13 4c4 0 7 3 7 7s-3 7-7 7"/><path d="M16 8l4 3-4 3"/></symbol>',
    '<symbol id="gi-status" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></symbol>',
    '<symbol id="gi-rating" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 17l4-10 4 10M9.5 13.5h5"/></symbol>',
    '<symbol id="gi-menu" viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></symbol>',
    '<symbol id="gi-bell" viewBox="0 0 24 24"><path d="M6 16h12l-1.5-3V9a4.5 4.5 0 0 0-9 0v4z"/><path d="M10 19a2 2 0 0 0 4 0M12 3v1.5"/></symbol>',
    '<symbol id="gi-undo" viewBox="0 0 24 24"><path d="M4 9h9a5 5 0 0 1 0 10H8"/><path d="M8 5L4 9l4 4"/></symbol>',
    '<symbol id="gi-refresh" viewBox="0 0 24 24"><path d="M20 7a8 8 0 0 0-14-2L3 8M3 4v4h4M4 17a8 8 0 0 0 14 2l3-3M21 20v-4h-4"/></symbol>',
    '<symbol id="gi-weather" viewBox="0 0 24 24"><path d="M6 13a4 4 0 0 1 1-7.9A5.5 5.5 0 0 1 18 8a3.5 3.5 0 0 1 .5 7z"/><path d="M8 17l-1 3M12 17l-1 3M16 17l-1 3"/></symbol>',
    '<symbol id="gi-defence" viewBox="0 0 24 24"><path d="M3 9l3-2v-2h3l3-2 3 2h3v2l3 2v10H3z"/><path d="M9 12v4M15 12v4"/></symbol>',
    '<symbol id="gi-press" viewBox="0 0 24 24"><rect x="9" y="2.5" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8 21h8"/></symbol>',
    '<symbol id="gi-happy" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 14c1 1.5 2.4 2.2 4 2.2s3-.7 4-2.2M9 9.3h.01M15 9.3h.01"/></symbol>',
    '<symbol id="gi-sad" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 16c1-1.5 2.4-2.2 4-2.2s3 .7 4 2.2M9 9.3h.01M15 9.3h.01"/></symbol>',
    '<symbol id="gi-angry" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 16c1-1.2 2.4-1.8 4-1.8s3 .6 4 1.8M7.5 8.5l2.5 1.5M16.5 8.5L14 10"/></symbol>',
    '<symbol id="gi-calm" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8.5 14.5h7M9 9.3h.01M15 9.3h.01"/></symbol>',
    '<symbol id="gi-match" viewBox="0 0 24 24"><circle cx="7" cy="8" r="3"/><path d="M10 8h4M17 8l2-1v8l-2-1a3 3 0 0 0 0-6z"/><path d="M4 18h16"/></symbol>',
    '<symbol id="gi-table" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 4v16"/></symbol>',
    '<symbol id="gi-form" viewBox="0 0 24 24"><path d="M3 18l5-5 4 3 6-8"/><path d="M15 8h3v3"/><path d="M19 3l.7 1.8L21.5 5.5l-1.8.7L19 8l-.7-1.8-1.8-.7 1.8-.7z"/></symbol>',
    '<symbol id="gi-quick" viewBox="0 0 24 24"><path d="M4 5h16v14H4z"/><path d="M8 10l2 2-2 2M13 14h4"/></symbol>',
    '<symbol id="gi-stats" viewBox="0 0 24 24"><path d="M3 20.5h18"/><rect x="5" y="12" width="3" height="7"/><rect x="10.5" y="8" width="3" height="11"/><rect x="16" y="4" width="3" height="15"/></symbol>',
    '<symbol id="gi-whistle" viewBox="0 0 24 24"><path d="M3 9h9a4 4 0 1 0-4-4"/><circle cx="17" cy="14" r="5"/><path d="M12 14h.01"/></symbol>'
  ];

  var sprite = null;
  function ensureSprite() {
    if (sprite && sprite.isConnected) return sprite;
    sprite = document.createElementNS(NS, 'svg');
    sprite.setAttribute('aria-hidden', 'true');
    sprite.setAttribute('focusable', 'false');
    sprite.setAttribute('width', '0');
    sprite.setAttribute('height', '0');
    sprite.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
    S.forEach(function (raw) {
      var t = document.createElementNS(NS, 'g');
      t.innerHTML = raw;
      var node = t.firstChild;
      if (node) sprite.appendChild(node);
    });
    (document.body || document.documentElement).appendChild(sprite);
    return sprite;
  }

  function makeIcon(id, emoji) {
    var wrap = document.createElement('span');
    wrap.className = 'gi-wrap' + (id ? ' gi-' + id : ' gi-unknown');
    wrap.setAttribute('data-gi-emoji', emoji);
    if (id) {
      var svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('class', 'gi');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('aria-hidden', 'true');
      svg.setAttribute('focusable', 'false');
      var use = document.createElementNS(NS, 'use');
      use.setAttribute('href', '#gi-' + id);
      use.setAttributeNS(XLINK, 'xlink:href', '#gi-' + id);
      svg.appendChild(use);
      wrap.appendChild(svg);
    }
    /* text label is always preserved for the app, screen readers, search
       and the CLASSIC UI toggle; it is visually hidden, never deleted. */
    var sr = document.createElement('span');
    sr.className = 'gi-sr';
    sr.textContent = emoji;
    wrap.appendChild(sr);
    return wrap;
  }

  var SKIP = 'SCRIPT,STYLE,NOSCRIPT,TEXTAREA,SVG,CANVAS,OPTION,CODE,PRE';
  function convertText(node) {
    var text = node.nodeValue;
    if (!text || !TEST.test(text)) return 0;
    ensureSprite();
    var frag = document.createDocumentFragment();
    var last = 0, count = 0, m;
    RE.lastIndex = 0;
    while ((m = RE.exec(text)) !== null) {
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      frag.appendChild(makeIcon(iconId(m[0]), m[0]));
      count++;
      last = m.index + m[0].length;
      if (m[0].length === 0) RE.lastIndex++;
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    node.nodeValue = '';
    if (!count) return 0;
    var parent = node.parentNode;
    if (parent) parent.replaceChild(frag, node);
    return count;
  }

  function walk(root) {
    if (!root) return 0;
    var n = 0;
    var skip = root.nodeType === 1 && root.matches && root.matches(SKIP);
    if (skip) return 0;
    if (root.getAttribute && root.getAttribute('data-gi-keep')) return 0;
    var it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (t) {
        if (!t.nodeValue || !t.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        var p = t.parentNode;
        if (!p || (p.matches && p.matches(SKIP))) return NodeFilter.FILTER_REJECT;
        if (p.classList && p.classList.contains('gi-sr')) return NodeFilter.FILTER_REJECT;
        return TEST.test(t.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    var todo = [], t;
    while ((t = it.nextNode())) todo.push(t);
    for (var i = 0; i < todo.length; i++) n += convertText(todo[i]);
    return n;
  }

  function convertAll() {
    if (!document.body) return 0;
    return walk(document.body) + convertTitles();
  }
  function convertTitles() {
    var n = 0;
    ['title', 'aria-label', 'placeholder', 'alt'].forEach(function (a) {
      var list;
      try { list = document.querySelectorAll('[' + a + ']'); } catch (e) { return; }
      Array.prototype.forEach.call(list, function (el) {
        var v = el.getAttribute(a);
        if (!v || !TEST.test(v)) return;
        RE.lastIndex = 0;
        var out = v.replace(RE, function (g) { return iconId(g) ? '' : g; });
        if (out !== v) { el.setAttribute(a, out.replace(/\s{2,}/g, ' ').trim()); n++; }
      });
    });
    return n;
  }
  function restore() {
    var list = document.querySelectorAll('.gi-wrap[data-gi-emoji]');
    Array.prototype.forEach.call(list, function (w) {
      var t = document.createTextNode(w.getAttribute('data-gi-emoji') || '');
      if (w.parentNode) w.parentNode.replaceChild(t, w);
    });
    if (sprite) { sprite.remove(); sprite = null; }
  }

  /* -------------------------------------------------- localStorage safe */
  function lsGet(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
  function lsDel(k) { try { window.localStorage.removeItem(k); } catch (e) {} }

  /* ------------------------------------------------------ club identity */
  var clubTint = null, tintLoaded = false;
  function applyClubColor() {
    var b = document.body;
    if (!b) return;
    if (clubTint && b.dataset.giTheme === 'club') b.style.setProperty('--club', clubTint);
    else b.style.removeProperty('--club');
    if (tintLoaded) return;
    tintLoaded = true;
    if (!window.fetch) return;
    fetch('/api/clubcolors').then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
      if (!d || typeof d !== 'object') return;
      var nameEl = document.getElementById('clubName') || document.getElementById('giClubName');
      var name = nameEl ? (nameEl.textContent || '').trim() : '';
      var hit = null;
      Object.keys(d).some(function (k) {
        if (name && k.toLowerCase() === name.toLowerCase()) { hit = d[k]; return true; }
        return false;
      });
      if (!hit && name) {
        Object.keys(d).some(function (k) {
          if (k.toLowerCase().indexOf(name.toLowerCase()) === 0) { hit = d[k]; return true; }
          return false;
        });
      }
      var hex = Array.isArray(hit) ? hit[0] : (typeof hit === 'string' ? hit : null);
      if (hex && /^#[0-9a-f]{6}$/i.test(hex)) {
        clubTint = hex;
        if (document.body && document.body.dataset.giTheme === 'club') document.body.style.setProperty('--club', hex);
      }
    }).catch(function () { /* offline / endpoint absent: keep gold */ });
  }

  function applyTheme(name, save) {
    var b = document.body;
    if (!b) return;
    if (THEMES.indexOf(name) < 0) name = THEMES[0];
    b.dataset.giTheme = name;
    if (save) lsSet(THEME_KEY, name);
    applyClubColor();
    var btn = document.getElementById('giThemeBtn');
    if (btn) btn.textContent = name.toUpperCase();
  }
  function cycleTheme() {
    var cur = document.body.dataset.giTheme || THEMES[0];
    var next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length];
    applyTheme(next, true);
    toast('CLUB COLOUR / ' + next.toUpperCase());
  }

  /* --------------------------------------------------------- game feel */
  var toastEl = null, toastTimer = null;
  function toast(msg) {
    if (!document.body) return;
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'gi-toast';
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    toastEl.classList.add('on');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('on'); }, 2200);
  }
  window.gafferToast = toast;

  var audio = null;
  function beep(kind) {
    if (lsGet(SOUND_KEY) !== '1') return;
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      if (!audio) audio = new AC();
      if (audio.state === 'suspended') audio.resume();
      var o = audio.createOscillator(), g = audio.createGain();
      o.type = 'sine';
      o.frequency.setValueAtTime(kind === 'confirm' ? 660 : 420, audio.currentTime);
      o.frequency.exponentialRampToValueAtTime(kind === 'confirm' ? 880 : 320, audio.currentTime + .08);
      g.gain.setValueAtTime(.0001, audio.currentTime);
      g.gain.exponentialRampToValueAtTime(.045, audio.currentTime + .012);
      g.gain.exponentialRampToValueAtTime(.0001, audio.currentTime + .12);
      o.connect(g); g.connect(audio.destination);
      o.start(); o.stop(audio.currentTime + .13);
    } catch (e) { /* audio unavailable: silent */ }
  }
  function toggleSound() {
    var on = lsGet(SOUND_KEY) === '1';
    if (on) lsDel(SOUND_KEY); else lsSet(SOUND_KEY, '1');
    var b = document.getElementById('giSoundBtn');
    if (b) { b.textContent = on ? 'SOUND OFF' : 'SOUND ON'; b.setAttribute('aria-pressed', on ? 'false' : 'true'); }
    if (!on) beep('confirm');
    toast(on ? 'MENU SOUND: OFF' : 'MENU SOUND: ON');
  }

  /* ------------------------------------------------- console navigation */
  var SECTIONS = [
    { id: 'home',   label: 'HOME',         icon: 'home',        pages: [['home', 'Home']] },
    { id: 'squad',  label: 'SQUAD',        icon: 'formation',   pages: [['squad', 'Squad & tactics'], ['kit', 'Kit / numbers'], ['growth', 'Training'], ['youth', 'Youth academy']] },
    { id: 'market', label: 'TRANSFERS',    icon: 'transfer',    pages: [['signings', 'Signings'], ['shortlist', 'Shortlist'], ['sales', 'Sales'], ['loans', 'Loans'], ['aimoves', 'AI transfers'], ['deadline', 'Deadline day']] },
    { id: 'comp',   label: 'COMPETITIONS', icon: 'competition', pages: [['league', 'League table'], ['clubs', 'Clubs'], ['honours', 'Trophy room'], ['records', 'Records'], ['history', 'History']] },
    { id: 'media',  label: 'MEDIA',        icon: 'press',       pages: [['press', 'Press'], ['news', 'News'], ['rumours', 'Rumours'], ['journal', 'Journal']] },
    { id: 'office', label: 'OFFICE',       icon: 'briefcase',   pages: [['inbox', 'Inbox'], ['assistant', 'Assistant'], ['board', 'Board'], ['talks', 'Dressing room'], ['calendar', 'Calendar']] }
  ];
  var navEl = null, subEl = null, mobileEl = null;

  function currentPage() {
    var p = (location.hash || '#home').slice(1);
    if (!document.getElementById('p-' + p)) p = 'home';
    return p;
  }
  function sectionOf(page) {
    for (var i = 0; i < SECTIONS.length; i++) {
      for (var j = 0; j < SECTIONS[i].pages.length; j++) {
        if (SECTIONS[i].pages[j][0] === page) return SECTIONS[i];
      }
    }
    return SECTIONS[0];
  }
  function goPage(p, label) {
    try {
      /* Prefer the app's own nav button: its handler calls the real show()
         and runs every per-page loader, even if show() is not global. */
      var nb = document.querySelector('#nav button[data-p="' + p + '"]');
      if (nb) nb.click();
      else if (typeof window.show === 'function') window.show(p);
      else {
        Array.prototype.forEach.call(document.querySelectorAll('.panel'), function (x) {
          x.classList.toggle('on', x.id === 'p-' + p);
        });
        location.hash = p;
      }
    } catch (e) { location.hash = p; }
    beep('confirm');
    syncNav();
    if (label) toast(label.toUpperCase());
    var main = document.querySelector('main');
    if (main && window.scrollTo) window.scrollTo({ top: 0, behavior: 'smooth' });
    document.body.classList.remove('gi-side-open');
  }
  function iconSvg(id, cls) {
    ensureSprite();
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'gi ' + (cls || ''));
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    var use = document.createElementNS(NS, 'use');
    use.setAttribute('href', '#gi-' + id);
    use.setAttributeNS(XLINK, 'xlink:href', '#gi-' + id);
    svg.appendChild(use);
    return svg;
  }
  function syncNav() {
    if (!navEl) return;
    var p = currentPage(), s = sectionOf(p);
    Array.prototype.forEach.call(navEl.querySelectorAll('[data-gi-sec]'), function (b) {
      var on = b.getAttribute('data-gi-sec') === s.id;
      b.classList.toggle('on', on);
      if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    });
    if (subEl) {
      subEl.innerHTML = '';
      s.pages.forEach(function (pair) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'gi-sub' + (pair[0] === p ? ' on' : '');
        b.setAttribute('data-gi-go', pair[0]);
        b.appendChild(iconSvg(s.icon));
        var t = document.createElement('span'); t.textContent = pair[1];
        b.appendChild(t);
        if (pair[0] === p) b.setAttribute('aria-current', 'page');
        subEl.appendChild(b);
      });
      /* r10: keep the app's own Scouting action reachable from the console */
      if (s.id === 'market') {
        var sc = document.createElement('button');
        sc.type = 'button';
        sc.className = 'gi-sub gi-scout';
        sc.setAttribute('data-gi-scout', '1');
        sc.appendChild(iconSvg('scout'));
        var st = document.createElement('span'); st.textContent = 'Scouting';
        sc.appendChild(st);
        subEl.appendChild(sc);
      }
    }
    if (mobileEl) {
      Array.prototype.forEach.call(mobileEl.querySelectorAll('[data-gi-sec]'), function (b) {
        var on = b.getAttribute('data-gi-sec') === s.id;
        b.classList.toggle('on', on);
        if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
      });
    }
  }
  function openSwitcher() {
    beep('move');
    var f = document.getElementById('tbFind');
    if (f) { f.click(); return; }
    try {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', code: 'KeyK', ctrlKey: true, bubbles: true }));
    } catch (e) { /* older engines */ }
    var q = document.getElementById('kpQ');
    if (q) q.focus();
  }
  function buildNav() {
    if (navEl || !document.querySelector('.app') || !document.getElementById('nav')) return;
    ensureSprite();
    var bar = document.createElement('div');
    bar.className = 'gi-console';
    bar.setAttribute('data-gi-keep', '1');
    bar.innerHTML =
      '<div class="gi-console-row">' +
        '<div class="gi-brand"><span class="gi-brand-mark">TG</span>' +
          '<span class="gi-brand-txt"><b>THE GAFFER</b><i>PES 2017 · MASTER LEAGUE</i></span></div>' +
        '<div class="gi-tabs" id="giTabs" role="tablist" aria-label="Main sections"></div>' +
        '<div class="gi-console-tools">' +
          '<button type="button" class="gi-quick" id="giQuick" aria-label="Quick switcher (Ctrl+K)"><kbd>CTRL K</kbd><span>QUICK SWITCH</span></button>' +
          '<button type="button" class="gi-icon-btn" id="giDrawer" aria-label="Open menu">☰</button>' +
        '</div>' +
      '</div>' +
      '<div class="gi-subbar" id="giSubbar" aria-label="Section pages"></div>';
    document.body.insertBefore(bar, document.body.firstChild);
    navEl = bar.querySelector('#giTabs');
    subEl = bar.querySelector('#giSubbar');

    SECTIONS.forEach(function (s, i) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'gi-tab';
      b.setAttribute('data-gi-sec', s.id);
      b.setAttribute('role', 'tab');
      b.setAttribute('data-gi-keep', '1');
      b.title = s.label + '  (Alt+' + (i + 1) + ')';
      b.appendChild(iconSvg(s.icon));
      var t = document.createElement('span'); t.textContent = s.label; b.appendChild(t);
      navEl.appendChild(b);
    });

    var extra = document.createElement('div');
    extra.className = 'gi-status';
    extra.setAttribute('data-gi-keep', '1');
    extra.id = 'giStatus';
    document.body.insertBefore(extra, bar.nextSibling);

    /* slim utility strip: theme / sound / classic UI / intro */
    var hud = document.createElement('div');
    hud.className = 'gi-hud';
    hud.setAttribute('data-gi-keep', '1');
    hud.innerHTML =
      '<span class="gi-hud-title">MATCHDAY · R10</span><span class="gi-hud-slash">/</span>' +
      '<span class="gi-hud-mode" id="giHudPage">HOME</span><span class="gi-hud-right">' +
      '<button type="button" class="gi-hud-btn" id="giThemeBtn">CLUB</button>' +
      '<button type="button" class="gi-hud-btn" id="giSoundBtn" aria-pressed="false">SOUND OFF</button>' +
      '<button type="button" class="gi-hud-btn" id="giIntroBtn">INTRO</button>' +
      '</span>';
    document.body.appendChild(hud);
    document.body.classList.add('gi-console-on');

    /* mobile bottom navigation */
    mobileEl = document.createElement('nav');
    mobileEl.className = 'gi-mobilenav';
    mobileEl.setAttribute('aria-label', 'Quick navigation');
    mobileEl.setAttribute('data-gi-keep', '1');
    SECTIONS.slice(0, 5).forEach(function (s) {
      var b = document.createElement('button');
      b.type = 'button'; b.setAttribute('data-gi-sec', s.id);
      b.appendChild(iconSvg(s.icon));
      var t = document.createElement('span'); t.textContent = s.label; b.appendChild(t);
      mobileEl.appendChild(b);
    });
    document.body.appendChild(mobileEl);

    document.addEventListener('click', function (e) {
      var tab = e.target.closest ? e.target.closest('[data-gi-sec]') : null;
      if (tab) {
        var s = SECTIONS.filter(function (x) { return x.id === tab.getAttribute('data-gi-sec'); })[0];
        if (s) goPage(s.pages[0][0], s.label);
        return;
      }
      var sub = e.target.closest ? e.target.closest('[data-gi-go]') : null;
      if (sub) {
        var p = sub.getAttribute('data-gi-go');
        var lbl = p.replace(/-/g, ' ');
        goPage(p, lbl);
        return;
      }
      if (e.target.closest && e.target.closest('#giQuick')) { openSwitcher(); return; }
      if (e.target.closest && e.target.closest('#giDrawer')) {
        document.body.classList.toggle('gi-side-open'); beep('move'); return;
      }
      if (e.target.closest && e.target.closest('#giThemeBtn')) { cycleTheme(); return; }
      if (e.target.closest && e.target.closest('#giSoundBtn')) { toggleSound(); return; }
      if (e.target.closest && e.target.closest('#giIntroBtn')) { boot(true); return; }
      if (e.target.closest && e.target.closest('[data-gi-scout]')) {
        var scb = document.querySelector('[data-sc-go]');
        if (scb) scb.click();
        beep('confirm'); toast('SCOUTING');
        return;
      }
      /* r10: explicit Selected state for roster / bench rows */
      var row = e.target.closest ? e.target.closest('#squadList > button, #bench > button, #benchHost > button, #pitch > g') : null;
      if (row) {
        var box = row.parentNode;
        if (box) Array.prototype.forEach.call(box.querySelectorAll('[data-gi-selected]'), function (x) {
          x.removeAttribute('data-gi-selected');
        });
        row.setAttribute('data-gi-selected', '1');
        beep('move');
      }
      /* focus feedback on any real UI control */
      var ctl = e.target.closest ? e.target.closest('button, [role="button"], tr.clk') : null;
      if (ctl) { ctl.classList.add('gi-press'); setTimeout(function () { ctl.classList.remove('gi-press'); }, 220); }
    });

    document.addEventListener('keydown', function (e) {
      if (e.altKey && /^[1-6]$/.test(e.key)) {
        e.preventDefault();
        var s = SECTIONS[+e.key - 1];
        if (s) goPage(s.pages[0][0], s.label);
        return;
      }
      var tag = (e.target && e.target.tagName || '').toLowerCase();
      var typing = tag === 'input' || tag === 'textarea' || tag === 'select' || (e.target && e.target.isContentEditable);
      if (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey) { e.preventDefault(); openSwitcher(); return; }
      if (e.key === 'Escape') document.body.classList.remove('gi-side-open');
      /* r10: arrow-key roving focus through the squad list (gamepad-like) */
      if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && e.target && e.target.closest) {
        var r = e.target.closest('#squadList > button');
        if (r) {
          var rows = Array.prototype.filter.call(r.parentNode.children, function (n) {
            return n.tagName === 'BUTTON';
          });
          var ix = rows.indexOf(r);
          if (ix >= 0) {
            e.preventDefault();
            var nxt = rows[(ix + (e.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length];
            if (nxt) {
              Array.prototype.forEach.call(rows, function (n) { n.removeAttribute('data-gi-selected'); });
              nxt.setAttribute('data-gi-selected', '1');
              nxt.focus();
              beep('move');
            }
            return;
          }
        }
      }
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        if (typing || !navEl) return;
        var tabs = Array.prototype.slice.call(navEl.querySelectorAll('.gi-tab'));
        var at = tabs.indexOf(document.activeElement);
        if (at < 0) return;
        e.preventDefault();
        var nx = tabs[(at + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        nx.focus(); beep('move');
      }
    });

    window.addEventListener('hashchange', function () {
      syncNav();
      var hp = document.getElementById('giHudPage');
      if (hp) hp.textContent = sectionOf(currentPage()).label;
      var main = document.querySelector('main');
      if (main) { main.classList.remove('gi-enter'); void main.offsetWidth; main.classList.add('gi-enter'); }
    });

    var sb = document.getElementById('giSoundBtn');
    if (sb) { sb.textContent = lsGet(SOUND_KEY) === '1' ? 'SOUND ON' : 'SOUND OFF'; sb.setAttribute('aria-pressed', lsGet(SOUND_KEY) === '1' ? 'true' : 'false'); }
    syncNav();
    var hp = document.getElementById('giHudPage');
    if (hp) hp.textContent = sectionOf(currentPage()).label;
  }

  /* ---------------------------------------------------------- boot intro */
  function boot(force) {
    if (!force && lsGet(INTRO_KEY)) return;
    if (!document.body || document.getElementById('giBoot')) return;
    var d = document.createElement('div');
    d.className = 'gi-boot';
    d.id = 'giBoot';
    d.setAttribute('data-gi-keep', '1');
    d.innerHTML =
      '<div class="gi-boot-inner">' +
        '<div class="gi-boot-badge">' + iconSvg('ball').outerHTML + '</div>' +
        '<div class="gi-boot-kicker">PES 2017 · MASTER LEAGUE</div>' +
        '<div class="gi-boot-title">THE GAFFER<span>MATCHDAY</span></div>' +
        '<div class="gi-boot-bar"><i></i></div>' +
        '<div class="gi-boot-sub">PREPARING YOUR CLUB</div>' +
      '</div>' +
      '<button type="button" class="gi-boot-skip" id="giBootSkip">PRESS ANY KEY TO CONTINUE</button>';
    document.body.appendChild(d);
    function close() {
      d.classList.add('gi-boot-out');
      setTimeout(function () { d.remove(); }, 500);
      lsSet(INTRO_KEY, '1');
      document.removeEventListener('keydown', onKey);
    }
    function onKey(e) { if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); close(); } }
    document.addEventListener('keydown', onKey);
    d.addEventListener('click', close);
    setTimeout(close, 2600);
    beep('confirm');
  }

  /* ------------------------------------------------------------- toggle */
  function buildToggle() {
    if (!document.body || document.getElementById('gi-toggle')) return;
    var b = document.createElement('button');
    b.type = 'button';
    b.id = 'gi-toggle';
    b.className = 'gi-toggle';
    b.setAttribute('data-gi-keep', '1');
    b.setAttribute('aria-pressed', 'true');
    b.textContent = 'CLASSIC UI';
    b.addEventListener('click', function () {
      var on = !document.body.classList.contains('game-skin');
      document.body.classList.toggle('game-skin', on);
      if (on) lsSet(SKIN_KEY, '1'); else lsDel(SKIN_KEY);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      document.body.classList.remove('gi-console-on');
      if (on) { document.body.classList.add('gi-console-on'); convertAll(); applyTheme(lsGet(THEME_KEY) || THEMES[0], false); }
      else { restore(); document.body.removeAttribute('data-gi-theme'); }
      toast(on ? 'MATCHDAY UI' : 'CLASSIC UI');
      beep('confirm');
    });
    document.body.appendChild(b);
  }

  /* --------------------------------------------------------------- init */
  function init() {
    if (!document.body) return;
    var want = lsGet(SKIN_KEY) !== '0';
    document.body.classList.toggle('game-skin', want);
    if (!want) return;
    applyTheme(lsGet(THEME_KEY) || THEMES[0], false);
    convertAll();
    buildNav();
    buildToggle();
    boot(false);

    var queued = false;
    var mo = new MutationObserver(function (muts) {
      if (queued) return;
      queued = true;
      setTimeout(function () {
        queued = false;
        if (!document.body.classList.contains('game-skin')) return;
        var dirty = false;
        for (var i = 0; i < muts.length; i++) {
          var m = muts[i];
          if (m.type === 'childList') {
            for (var j = 0; j < m.addedNodes.length; j++) {
              var n = m.addedNodes[j];
              if (n.nodeType === 1 && n.getAttribute && n.getAttribute('data-gi-keep')) continue;
              dirty = true;
            }
          } else if (m.type === 'characterData') dirty = true;
        }
        if (dirty) { convertAll(); applyClubColor(); }
      }, 24);
    });
    mo.observe(document.body, { childList: true, subtree: true, characterData: true });

    /* club name can arrive after the first paint */
    [0, 900, 2600].forEach(function (ms) { setTimeout(applyClubColor, ms); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
