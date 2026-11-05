#!/usr/bin/env python3
"""Integrate the offline matchday HUD into the *classic* pc414 UI.

pc414 embeds hundreds of pictographs in JavaScript strings, translation keys,
plain-text setters and Python responses. Replacing those with HTML at build
 time breaks escaping, comparisons, ``.repeat()``, or i18n lookups. Instead,
we give each original grapheme a reversible, ASCII-only token. The small HUD
renderer turns tokens into local SVG emblems at the final DOM text node (and
also understands icons from older saved data). This keeps application logic,
translation keys and text-only controls intact.

The transformation is deliberately asserted: an upstream icon or markup
change makes the build fail instead of shipping an OS-dependent emoji.
"""
import json
import os
import re
import xml.etree.ElementTree as ET

# The values are the local sprite's semantic names, not Unicode font glyphs.
# Keep this table in the build source; the shipped renderer receives only
# ASCII code points and does not depend on an external font, CDN or service.
GROUPS = {
    'ball': '⚽',
    'trophy': '🏆🎉',
    'target': '🎯🏹',
    'trend-up': '📈',
    'trend-down': '📉',
    'hourglass': '⏳',
    'contract': '✍✒✎',
    'star': '★⭐🌟✨✦',
    'star-empty': '☆',
    'flame': '🔥',
    'news': '📰',
    'clipboard': '📋🧾',
    'glove': '🧤',
    'play': '▶',
    'warning': '⚠❗🤯',
    'document': '📄',
    'waiting': '🤫☕',
    'handshake': '🤝',
    'money': '💶💰💸🧮',
    'medical': '✚🩺',
    'bolt': '⚡',
    'transfer': '🔁🔄',
    'shirt': '👕',
    'screen': '🖥📺',
    'chat': '💬',
    'clock': '⏰⏱',
    'lock': '🔒',
    'microphone': '🎤🎙',
    'check': '✅✔',
    'briefcase': '💼🧳',
    'injury': '🩹',
    'squad': '👥',
    'youth': '🌱🧬',
    'calendar': '📅🗓',
    'scout': '🔭🧭',
    'door': '🚪👋',
    'workout': '🏋',
    'academy': '🎓',
    'sound': '🔊📢📣📞♪',
    'arrow-down': '⬇🐢',
    'arrow-up': '⬆',
    'boot': '👟',
    'manager': '🎩👔🧓🕴',
    'shield': '🛡🛟',
    'heart': '💔❤',
    'chart': '📊',
    'board': '🏛🏗⚖',
    'battery': '🔋',
    'strength': '💪⚔🗡🦈',
    'stadium': '🏟',
    'eye': '👀',
    'gamepad': '🎮',
    'flag': '⚑🏁🧣',
    'run': '🏃',
    'book': '📖📕📚',
    'brick': '🧱',
    'medal': '🥇🥈🥉',
    'player': '👤',
    'folder': '📁🗂',
    'seat': '🪑',
    'save': '💾',
    'unlock': '🔓',
    'settings': '⚙',
    'search': '⌕🔎',
    'form-up': '😄',
    'form-good': '🙂☺😌',
    'form-neutral': '😐',
    'form-low': '☹🙁😠😞',
    'form-down': '😡🥶',
    'crown': '👑',
    'globe': '🌍',
    'tag': '🏷🆕',
    'pause': '⏸',
    'tools': '🛠✂',
    'power': '⏻',
    'close': '❌🙅✋',
    'science': '🧪',
    'sliders': '🎛♟🧩🃏🧠',
    'flight': '✈🛫🪂',
    'info': 'ℹ',
    'idea': '💡',
    'weather': '🌧',
    'rocket': '🚀',
    'bell': '🔔',
    'home': '🏠',
    'mail': '✉📨📥',
    'store': '🛒',
    'assist': '🅰',
    'ticket': '🎟',
    'card': '🟨',
    'signal': '🟢🔴',
}

# Arrows without a variation selector are deliberately left as typographic
# arrows: they also occur in prose and data. Their emoji-style versions get
# an emblem, and preserve their original distinct string identity.
EMOJI_VARIANTS = {'↩': 'transfer', '↔': 'transfer', '↗': 'arrow-up'}
COMPOSITES = {
    '🧑\u200d💼': 'manager',
    '🧑\u200d🤝\u200d🧑': 'squad',
    '👨\u200d👩\u200d👧': 'squad',
    '😮\u200d💨': 'form-neutral',
}

BASE = {}
for _name, _chars in GROUPS.items():
    for _char in _chars:
        if _char in BASE:
            raise RuntimeError('duplicate HUD glyph: %r' % _char)
        BASE[_char] = _name
GLYPHS = dict(BASE)
GLYPHS.update({char + '\ufe0f': name for char, name in BASE.items()})
GLYPHS.update({char + '\ufe0f': name for char, name in EMOJI_VARIANTS.items()})
GLYPHS.update(COMPOSITES)
# Longest first is essential: e.g. a family or a variation selector is one
# icon, not several icons plus an invisible joiner.
_GLYPH_RE = re.compile('|'.join(re.escape(s) for s in sorted(GLYPHS, key=len, reverse=True)))
# Unicode Emoji_Presentation characters in the BMP, plus the supplementary
# pictograph block, variation selectors and joiners. Python's standard `re`
# does not expose Unicode binary properties; keep these ranges explicit so a
# new upstream default-colour emoji cannot silently bypass the mapping check.
_STRICT_LEFTOVER = re.compile(
    '[\U0001f000-\U0001faff\ufe0f\u200d'
    '\u231a-\u231b\u23e9-\u23ec\u23f0\u23f3\u25fd-\u25fe'
    '\u2614-\u2615\u2648-\u2653\u267f\u2693\u26a1\u26aa-\u26ab'
    '\u26bd-\u26be\u26c4-\u26c5\u26ce\u26d4\u26ea\u26f2-\u26f3'
    '\u26f5\u26fa\u26fd\u2705\u270a-\u270b\u2728\u274c\u274e'
    '\u2753-\u2755\u2757\u2795-\u2797\u27b0\u27bf\u2b1b-\u2b1c'
    '\u2b50\u2b55]')
_TOKEN_RE = re.compile(r'__gi_[0-9a-f]+(?:_[0-9a-f]+)*__')


def code(glyph):
    return '_'.join('%x' % ord(c) for c in glyph)


def token(glyph):
    return '__gi_%s__' % code(glyph)


def tokenize(text):
    """Preserve each grapheme's identity across JS, Python and i18n keys."""
    return _GLYPH_RE.sub(lambda m: token(m.group(0)), text)


def _read(root, path):
    with open(os.path.join(root, *path.split('/')), encoding='utf-8') as f:
        return f.read()


def _write(root, path, data):
    with open(os.path.join(root, *path.split('/')), 'w', encoding='utf-8', newline='') as f:
        f.write(data)


def _once(data, old, new, what):
    n = data.count(old)
    if n != 1:
        raise RuntimeError('HUD %s: expected one occurrence, found %d' % (what, n))
    return data.replace(old, new, 1)


def _translation_aliases(strings):
    """Keep translations working after a text node is split around an icon.

    pc414's late translation sweep translates individual text nodes. Its
    original keys can start with an emoji, so after rendering the icon the
    remaining text needs a matching icon-free key too. Keep the original key
    for L2()/tr() lookups, prefer an existing translation on collision, and
    account for a few upstream keys whose first character is an HTML '>'.
    """
    result = dict(strings)
    for key, value in strings.items():
        if not _TOKEN_RE.search(key) or not isinstance(value, str):
            continue
        clean_key = _TOKEN_RE.sub('', key).strip()
        clean_val = _TOKEN_RE.sub('', value).strip()
        if clean_key.startswith('>'):
            clean_key = clean_key[1:].lstrip()
        if clean_val.startswith('>'):
            clean_val = clean_val[1:].lstrip()
        if clean_key and clean_key not in result:
            result[clean_key] = clean_val
    return result


def _replace_css_symbols(html):
    # CSS generated content is not a DOM text node; draw these marks directly.
    html = _once(html,
        '.pc-tr .tr-chip.cm::before{content:"⚡";margin-right:7px;font-size:12px;color:var(--g)}',
        '.pc-tr .tr-chip.cm::before{content:"";display:inline-block;width:10px;height:14px;margin-right:7px;background:var(--g);clip-path:polygon(55% 0,5% 57%,40% 57%,34% 100%,95% 35%,59% 35%);vertical-align:-2px}',
        'lightning CSS')
    html = _once(html,
        'html body #p-journal .jn-main h3::before{content:"⚽ ";text-decoration:none;display:inline-block}',
        'html body #p-journal .jn-main h3::before{content:"";display:inline-block;width:13px;height:13px;margin-right:6px;border:2px solid currentColor;border-radius:50%;background:radial-gradient(circle at 50% 50%,currentColor 0 29%,transparent 32%);vertical-align:-1px}',
        'journal ball CSS')
    html = _once(html,
        '.stx-rs li::before{content:"✔";color:#f0575c;margin-right:8px}',
        '.stx-rs li::before{content:"";display:inline-block;width:12px;height:10px;margin-right:8px;background:#f0575c;clip-path:polygon(0 48%,17% 30%,40% 55%,83% 0,100% 15%,40% 100%);vertical-align:0}',
        'check CSS')
    return html


def apply(root):
    """Transform the extracted build, leaving the upstream archive untouched."""
    svg = _read(root, 'static/hud-icons.svg')
    tree = ET.fromstring(svg)
    ids = {e.attrib.get('id') for e in tree if e.tag.endswith('symbol')}
    missing = sorted({'hud-' + v for v in GLYPHS.values()} - ids)
    if missing:
        raise RuntimeError('HUD sprite is missing symbols: %s' % ', '.join(missing))

    index = _read(root, 'static/index.html')
    index = _replace_css_symbols(index)
    # The HUD supplies the shortlist emblem; do not keep a second star inside
    # the generated sub-tab label. Preserve the shortlist count and its text.
    index = _once(index, "t='★ '+t+(n?' · '+n:'')",
                  "t=t+(n?' · '+n:'')", 'shortlist tab label')
    index = _once(index, '<body>', '<body data-hud="classic">', 'classic body')
    # The page sets translate=no on <html> to prevent browser auto-translation.
    # That must not suppress its own Italian sweep on all descendants. Ignore
    # only the root marker, while still honouring explicit no-translate regions.
    index = _once(index,
        "[translate=no]:not(thead):not(.lgt-h):not(.hm2-th)",
        "[translate=no]:not(html):not(thead):not(.lgt-h):not(.hm2-th)",
        'internal translation scope')
    index = _once(index, '</head>',
        '<link rel="stylesheet" href="/hud-ui.css">\n'
        '<link rel="stylesheet" href="/game-shell.css">\n'
        '<script defer src="/hud-icons.js"></script>\n'
        '<script defer src="/game-shell.js"></script>\n'
        '<script defer src="/pes17-face-refresh.js"></script>\n</head>', 'classic assets')

    # After the three CSS cases above, every remaining pictograph must be in
    # page data, never inside a CSS declaration. Avoid silent placeholder leaks.
    styles = ''.join(re.findall(r'<style\b[^>]*>(.*?)</style>', index, re.S | re.I))
    css_glyphs = _GLYPH_RE.findall(styles)
    if css_glyphs:
        raise RuntimeError('HUD has unhandled CSS glyph(s): %s' % repr(css_glyphs[:8]))

    files = {
        'static/index.html': index,
        'lib/jobintro.py': _read(root, 'lib/jobintro.py'),
        'data/i18n/it.json': _read(root, 'data/i18n/it.json'),
        'data/i18n/strings_en.json': _read(root, 'data/i18n/strings_en.json'),
    }
    for path, data in files.items():
        result = tokenize(data)
        if result == data:
            raise RuntimeError('HUD expected pictographs in %s' % path)
        left = _STRICT_LEFTOVER.search(result)
        if left:
            raise RuntimeError('HUD unmapped pictograph in %s: U+%04X at %d' %
                               (path, ord(left.group()), left.start()))
        if path.endswith('.json'):
            before, after = json.loads(data), json.loads(result)
            if len(before) != len(after):
                raise RuntimeError('HUD translation key collision in %s' % path)
            # The UI translator walks text nodes; the icon renderer splits off
            # the leading emblem. Retain both full and icon-free lookup keys.
            result = json.dumps(_translation_aliases(after), ensure_ascii=False,
                                indent=1) + '\n'
        if path.endswith('.py'):
            compile(result, path, 'exec')
        _write(root, path, result)

    # Feed the renderer the *entire* mapping, not just icons seen in this
    # version: saved inbox records from an older build may contain native emoji.
    mapping = {code(glyph): name for glyph, name in GLYPHS.items()}
    js_path = 'static/hud-icons.js'
    js = _read(root, js_path)
    js = _once(js, '/*__HUD_ICON_MAP__*/{}',
               json.dumps(mapping, ensure_ascii=True, separators=(',', ':')),
               'renderer mapping')
    _write(root, js_path, js)

    tools = _read(root, 'static/pes17.html')
    for marker in ('/hud-ui.css', '/hud-icons.js', 'data-hud="tools"'):
        if marker not in tools:
            raise RuntimeError('HUD tools page missing %s' % marker)
    if _STRICT_LEFTOVER.search(tools):
        raise RuntimeError('HUD tools page contains an unmapped pictograph')
    print('Integrated offline HUD: %d semantic emblems, %d reversible icon tokens' %
          (len(set(GLYPHS.values())), len(mapping)))
