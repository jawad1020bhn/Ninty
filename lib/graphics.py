"""Crest and avatar resolution for the FC 27 game.

FC 27's database has no artwork in it, so crests come from a local cache built by
tools/import_graphics.py. That cache is deliberately NOT committed (the marks
belong to the clubs, not to us), which means this module must work when the cache
is missing, partial, or entirely absent. It does: every request resolves either
to a vendored file or to a generated SVG, never to a 404.

    lib.graphics.crest('clubs', '9', 'Liverpool', ['#e31b23','#ffffff','#ffd700'])
    -> (b'<svg .../>', 'image/svg+xml', 'generated')     # before import
    -> (b'<svg .../>', 'image/svg+xml', 'vendored')      # after import

Nothing here reads the FC 27 database or the network. Callers pass the name and
colours they already have, which keeps this module independent of the save
format and trivially testable.

The generated marks are original geometry driven by each club's own colours.
They are not tracings of anyone's crest and carry no third-party rights.
"""
import hashlib
import json
import os
import re
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(ROOT, 'data', 'graphics')

KINDS = ('clubs', 'leagues', 'nations')

# Words that add nothing to a monogram.
_INITIAL_STOP = {
    'fc', 'cf', 'ac', 'as', 'ssc', 'afc', 'sc', 'cd', 'ud', 'rc', 'rcd', 'ca',
    'ec', 'cr', 'se', 'sk', 'fk', 'bk', 'if', 'aif', 'club', 'calcio', 'de',
    'del', 'la', 'el', 'the', 'and', 'football', 'futbol', 'futebol', 'soccer',
}

_HEX = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')
_FALLBACK = ('#2b3a55', '#e8edf5', '#9fb3d1')

_LOCK = threading.Lock()
_CACHE = {}


def _xml(s):
    """Escape text for XML. Names come from the database, but a crest is served
    as image/svg+xml and an unescaped '&' or '<' would produce invalid SVG."""
    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;').replace("'", '&apos;'))


def _hex(c):
    """Accept only a real hex colour; anything else falls back. Prevents a
    database value from injecting markup into a fill attribute."""
    s = str(c or '').strip()
    if not _HEX.match(s):
        return None
    if len(s) == 4:
        s = '#' + ''.join(ch * 2 for ch in s[1:])
    return s.lower()


def colors_of(colors):
    out = [_hex(c) for c in (colors or [])]
    out = [c for c in out if c]
    while len(out) < 3:
        out.append(_FALLBACK[len(out)])
    return out[:3]


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _ink(bg):
    """Black or white, whichever is readable on this background."""
    r, g, b = _rgb(bg)
    return '#101418' if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else '#ffffff'


def _stable(s):
    """Process-stable hash. Python's hash() is salted per run, which would make
    generated art change on every server restart."""
    return int.from_bytes(hashlib.sha256(str(s).encode('utf-8')).digest()[:8], 'big')


def monogram(name, limit=3):
    words = [w for w in re.split(r'[^0-9A-Za-z\u00c0-\u024f]+', str(name or ''))
             if w and w.lower() not in _INITIAL_STOP]
    if not words:
        words = [str(name or '?').strip() or '?']
    if len(words) == 1:
        return words[0][:limit].upper()
    return ''.join(w[0] for w in words[:limit]).upper()


def shield_svg(name, colors, kind='clubs'):
    """An original shield built from the club's own colours."""
    c1, c2, c3 = colors_of(colors)
    mono = _xml(monogram(name))
    ink = _ink(c1)
    path = 'M50 4 L93 18 V60 C93 87 73 102 50 107 C27 102 7 87 7 60 V18 Z'
    if kind == 'nations':
        body = ('<circle cx="50" cy="55" r="46" fill="%s"/>'
                '<path d="M4 55 H96" stroke="%s" stroke-width="14"/>'
                '<circle cx="50" cy="55" r="46" fill="none" stroke="%s" stroke-width="4"/>'
                % (c1, c2, c3))
        ty, fs = 64, 30
    elif kind == 'leagues':
        body = ('<rect x="6" y="10" width="88" height="90" rx="14" fill="%s"/>'
                '<path d="M6 68 H94 V86 A14 14 0 0 1 80 100 H20 A14 14 0 0 1 6 86 Z" fill="%s"/>'
                '<rect x="6" y="10" width="88" height="90" rx="14" fill="none" stroke="%s" stroke-width="4"/>'
                % (c1, c2, c3))
        ty, fs = 62, 28
    else:
        body = ('<path d="%s" fill="%s"/>'
                '<path d="M50 4 L93 18 V60 C93 87 73 102 50 107 Z" fill="%s" opacity="0.9"/>'
                '<path d="%s" fill="none" stroke="%s" stroke-width="4"/>'
                % (path, c1, c2, path, c3))
        ty, fs = 68, 32
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 110" width="100" height="110" '
        'role="img" aria-label="%s">%s'
        '<text x="50" y="%d" text-anchor="middle" font-family="system-ui,Segoe UI,Roboto,sans-serif" '
        'font-size="%d" font-weight="700" fill="%s">%s</text></svg>'
        % (_xml(name), body, ty, fs, ink, mono)
    ).encode('utf-8')


def avatar_svg(name, seed=None):
    """A deterministic placeholder, NOT a likeness of the person.

    Real faces are only ever served by lib/faces.py from a freely-licensed
    photo. This is what renders when there isn't one, which for most of the
    21,623 players is the normal case.
    """
    h = _stable(seed if seed is not None else name)
    hue = h % 360
    # HSL -> RGB, fixed S/L so every avatar is legible with white text.
    c = 0.42
    x = c * (1 - abs(((hue / 60.0) % 2) - 1))
    seg = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][(hue // 60) % 6]
    m = 0.30
    r, g, b = [int(round((v + m) * 255)) for v in seg]
    bg = '#%02x%02x%02x' % (r, g, b)
    mono = _xml(monogram(name, limit=2))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100" '
        'role="img" aria-label="%s">'
        '<circle cx="50" cy="50" r="49" fill="%s"/>'
        '<circle cx="50" cy="39" r="15" fill="#ffffff" opacity="0.30"/>'
        '<path d="M20 88 C20 68 34 60 50 60 C66 60 80 68 80 88 Z" fill="#ffffff" opacity="0.30"/>'
        '<text x="50" y="94" text-anchor="middle" font-family="system-ui,Segoe UI,Roboto,sans-serif" '
        'font-size="20" font-weight="700" fill="#ffffff">%s</text></svg>'
        % (_xml(name), bg, mono)
    ).encode('utf-8')


def manifest(directory=None):
    """Load the importer's manifest, or {} when it hasn't been run.

    Cached on (path, mtime_ns, size). Note this filesystem's mtime granularity is
    coarse, so a same-size rewrite can reuse a stamp; tests that change the
    manifest must use a fresh directory rather than rewriting in place.
    """
    d = directory or DEFAULT_DIR
    p = os.path.join(d, 'manifest.json')
    try:
        st = os.stat(p)
    except OSError:
        return {}
    k = (p, st.st_mtime_ns, st.st_size)
    with _LOCK:
        hit = _CACHE.get('m')
        if hit and hit[0] == k:
            return hit[1]
    try:
        with open(p, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    with _LOCK:
        _CACHE['m'] = (k, data)
    return data


def _safe_rel(rel):
    """Manifest paths are data, not code. Refuse anything that escapes the
    graphics directory, so a hand-edited manifest cannot read arbitrary files."""
    s = str(rel or '').replace('\\', '/')
    if not s or s.startswith('/') or '..' in s.split('/'):
        return None
    if not s.lower().endswith(('.svg', '.png', '.jpg', '.jpeg', '.webp')):
        return None
    return s


def vendored_path(kind, ident, directory=None):
    """Absolute path to a cached crest, or None. Never raises."""
    if kind not in KINDS:
        return None
    d = directory or DEFAULT_DIR
    ent = (manifest(d).get(kind) or {}).get(str(ident))
    if not isinstance(ent, dict):
        return None
    rel = _safe_rel(ent.get('file'))
    if not rel:
        return None
    p = os.path.join(d, rel)
    return p if os.path.isfile(p) else None


def _mime(p):
    e = os.path.splitext(p)[1].lower()
    return {'.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg', '.webp': 'image/webp'}.get(e, 'application/octet-stream')


def crest(kind, ident, name='', colors=None, directory=None):
    """Return (bytes, mime, source). Always succeeds for a known kind.

    source is 'vendored' when a real mark was served and 'generated' when the
    fallback was, so the UI can tell and so tests can assert coverage.
    """
    p = vendored_path(kind, ident, directory)
    if p:
        try:
            with open(p, 'rb') as f:
                return f.read(), _mime(p), 'vendored'
        except OSError:
            pass
    return shield_svg(name or ident, colors, kind), 'image/svg+xml', 'generated'


def status(directory=None):
    d = directory or DEFAULT_DIR
    m = manifest(d)
    cov = m.get('coverage') or {}
    out = {'imported': bool(m), 'source': (m.get('source') or {}).get('repo'),
           'sha': (m.get('source') or {}).get('sha'), 'coverage': cov, 'present': {}}
    for kind in KINDS:
        ents = m.get(kind) or {}
        have = sum(1 for i in ents if vendored_path(kind, i, d))
        out['present'][kind] = {'mapped': len(ents), 'on_disk': have}
    return out
