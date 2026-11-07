"""Player and manager portraits, restricted to freely-licensed images.

There is no open dataset of real footballer faces. EA's are proprietary meshes
and textures, and press photos are copyrighted. The only defensible source is
the freely-licensed subset of Wikimedia Commons, so that is all this module will
accept, and every accepted image records its attribution.

Two independent gates, both pure functions so they can be tested without a
network:

  licence_ok()  - reject anything not explicitly free. Fair use / non-free is
                  refused even when the image is otherwise perfect.
  identity_ok() - reject the wrong human. A name collision that ships another
                  person's face is worse than showing no face at all.

    lib.faces.face(pid, 'Mohamed Salah', directory, allow_network=True)
    -> (bytes, mime, 'photo'|'avatar', attribution_or_None)

NETWORK IS OFF BY DEFAULT. With allow_network=False this only reads the local
cache and otherwise returns a generated avatar, so the game never silently
phones out. The server gates it behind config, exactly like wiki_web.

Personality rights are separate from copyright: a CC-licensed photo is free to
reuse as an image but still depicts a real person. This is for an editorial /
fan career-mode display, not merchandising or endorsement.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

# The server puts lib/ on sys.path and imports these flat. Match that so there
# is exactly one graphics module (and one manifest cache) per process; importing
# it as both `graphics` and `lib.graphics` would create two.
try:
    import graphics
except ImportError:  # standalone use with only the repo root on sys.path
    from lib import graphics

UA = 'TheGaffer/1.0 (personal career-mode companion; local install)'
COMMONS = 'https://commons.wikimedia.org/w/api.php'
WIKI = 'https://en.wikipedia.org/w/api.php'

# Only these licence families are accepted. Matching is on the normalised
# licence code AND the human-readable short name, because Commons populates
# them inconsistently across templates.
_FREE_CODES = ('cc0', 'pd', 'public domain', 'pd-old', 'pd-self', 'pd-author',
               'pd-usgov', 'pd-ineligible', 'pd-textlogo', 'gfdl')
_FREE_PREFIX = ('cc-by', 'cc by', 'attribution')
# Any of these anywhere in the licence fields is an outright refusal, even if
# something else in the record looks free.
_NONFREE = ('fair use', 'fairuse', 'non-free', 'nonfree', 'non free',
            'all rights reserved', 'copyrighted free use', 'arr ')

# Files that are not a portrait of the person at all.
_BAD_FILE = re.compile(
    r'flag|logo|crest|badge|icon|signature|autograph|map|kit|shirt|jersey|statue|'
    r'wax|trophy|cartoon|comic|caricature|stadium|shirt|stamp|coin|graffiti| mural',
    re.I)
# The page has to actually be about a footballer.
_FOOTBALL = re.compile(
    r'football|soccer|fussball|f\u00fa tbol|futebol|calcio|voetbal|pi\u0142kar',
    re.I)

_GAP = 0.6
_LAST = [0.0]
NEG_TTL = 14 * 86400      # a "no free photo" answer is retried after a fortnight
POS_TTL = 180 * 86400     # a cached photo is refreshed after ~6 months


def _norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', str(s or '').lower()).strip()


def _meta(ext, key):
    v = (ext or {}).get(key)
    if isinstance(v, dict):
        v = v.get('value')
    return re.sub(r'<[^>]+>', '', str(v or '')).strip()


def licence_ok(extmetadata):
    """(ok, short_name). Refuses anything not explicitly free.

    A missing licence is a refusal, not a pass: Commons files with no licence
    metadata are exactly the ones that turn out to be non-free.
    """
    code = _norm(_meta(extmetadata, 'License'))
    short = _meta(extmetadata, 'LicenseShortName')
    terms = _meta(extmetadata, 'UsageTerms')
    blob = ' %s %s %s ' % (code, _norm(short), _norm(terms))
    if not code and not short and not terms:
        return False, ''
    for bad in _NONFREE:
        if bad in blob:
            return False, short
    if _norm(_meta(extmetadata, 'NonFree')) in ('true', '1', 'yes'):
        return False, short
    if _norm(_meta(extmetadata, 'Copyrighted')) == 'false':
        return True, short or 'Public domain'
    for c in _FREE_CODES:
        if code == c or code.startswith(c + ' ') or (' ' + c + ' ') in blob:
            return True, short or c
    for p in _FREE_PREFIX:
        if code.startswith(p) or _norm(short).startswith(_norm(p)):
            # CC BY-NC and CC BY-ND are not free enough for reuse in a game.
            # Test NORMALISED TOKENS, not substrings like '-nc': _norm() has
            # already turned 'cc-by-nc-4.0' into 'cc by nc 4 0', so a hyphen
            # test silently accepted every NC and ND image.
            toks = set(code.split()) | set(_norm(short).split()) | set(_norm(terms).split())
            if ({'nc', 'nd'} & toks or 'noncommercial' in toks
                    or 'noderivatives' in toks or 'noderivs' in toks
                    or 'non commercial' in blob or 'no derivatives' in blob):
                return False, short
            return True, short or code
    return False, short


def attribution_of(extmetadata, title='', page_url=''):
    """The credit line CC BY / CC BY-SA require us to keep."""
    ok, short = licence_ok(extmetadata)
    return {
        'artist': _meta(extmetadata, 'Artist') or 'unknown',
        'credit': _meta(extmetadata, 'Credit'),
        'licence': short,
        'licence_url': _meta(extmetadata, 'LicenseUrl'),
        'file': str(title or ''),
        'page': str(page_url or ''),
        'free': bool(ok),
    }


def identity_ok(wanted, file_title='', description='', categories=''):
    """Guard against shipping the wrong person.

    Requires the surname to appear in the file title, and requires football
    context somewhere in the description or categories. Both are needed: the
    surname alone matches unrelated people, and football context alone matches
    any player in a team photo.
    """
    w = _norm(wanted)
    if not w:
        return False
    ft = _norm(file_title)
    if not ft or _BAD_FILE.search(str(file_title or '')):
        return False
    parts = [p for p in w.split() if len(p) > 2]
    if not parts:
        parts = w.split()
    if not parts:
        return False
    # The last token is the surname for most, but not all, naming conventions;
    # accept any substantial token so "Son Heung-min" still matches "Son".
    if not any(p in ft.split() for p in parts):
        return False
    ctx = '%s %s' % (description or '', categories or '')
    return bool(_FOOTBALL.search(ctx))


def pick_candidate(pages, wanted, description=''):
    """Choose the best free, correctly-identified portrait from API pages.

    Returns (page, attribution) or (None, None). Prefers a larger image, but
    only among candidates that passed BOTH gates.
    """
    best = None
    for p in pages or []:
        for ii in p.get('imageinfo') or []:
            ext = ii.get('extmetadata') or {}
            ok, _ = licence_ok(ext)
            if not ok:
                continue
            title = p.get('title', '')
            cats = _meta(ext, 'Categories')
            desc = _meta(ext, 'ImageDescription') or description
            if not identity_ok(wanted, title, desc, cats):
                continue
            url = ii.get('thumburl') or ii.get('url')
            if not url:
                continue
            area = int(ii.get('width') or 0) * int(ii.get('height') or 0)
            cand = (area, url, title, ii)
            if best is None or cand[0] > best[0]:
                best = cand
    if best is None:
        return None, None
    _, url, title, ii = best
    page_url = _meta(ii.get('extmetadata') or {}, 'Credit')
    att = attribution_of(ii.get('extmetadata') or {}, title,
                         ii.get('descriptionurl') or page_url)
    att['url'] = url
    return ii, att


def _get(url, timeout=15, binary=False):
    d = _GAP - (time.time() - _LAST[0])
    if d > 0:
        time.sleep(d)
    _LAST[0] = time.time()
    req = urllib.request.Request(
        url, headers={'User-Agent': UA, 'Accept': '*/*' if binary else 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    return b if binary else json.loads(b.decode('utf-8', 'replace'))


def _search(wanted):
    """Ask Commons for candidate files, WITH licence metadata.

    iiprop must include extmetadata; without it there is no licence to check and
    the old code path would have downloaded non-free images blind.
    """
    q = urllib.parse.urlencode({
        'action': 'query', 'generator': 'search',
        'gsrsearch': '%s filetype:bitmap' % wanted, 'gsrnamespace': '6',
        'gsrlimit': '20', 'prop': 'imageinfo',
        'iiprop': 'url|size|mime|extmetadata', 'iiurlwidth': '512',
        'format': 'json',
    })
    r = _get('%s?%s' % (COMMONS, q))
    return list(((r.get('query') or {}).get('pages') or {}).values())


def _cache_paths(directory, key):
    d = os.path.join(directory, 'faces')
    return (d, os.path.join(d, '%s.jpg' % key), os.path.join(d, '%s.json' % key),
            os.path.join(d, '%s.none' % key))


def face(key, name, directory, allow_network=False, description=''):
    """(bytes, mime, source, attribution). Always returns something renderable.

    source is 'photo' for a cached/fetched free image, 'avatar' for the generated
    placeholder. attribution is None for an avatar.
    """
    key = re.sub(r'[^A-Za-z0-9_-]', '', str(key))
    if not key:
        return graphics.avatar_svg(name), 'image/svg+xml', 'avatar', None
    d, img, meta, none = _cache_paths(directory, key)
    if os.path.isfile(img) and os.path.isfile(meta):
        try:
            with open(meta, encoding='utf-8') as f:
                att = json.load(f)
            if att.get('free') and time.time() - os.path.getmtime(img) < POS_TTL:
                with open(img, 'rb') as f:
                    return f.read(), 'image/jpeg', 'photo', att
        except (OSError, ValueError):
            pass
    if os.path.isfile(none) and time.time() - os.path.getmtime(none) < NEG_TTL:
        return graphics.avatar_svg(name, seed=key), 'image/svg+xml', 'avatar', None
    if not allow_network or not str(name or '').strip():
        return graphics.avatar_svg(name, seed=key), 'image/svg+xml', 'avatar', None
    try:
        os.makedirs(d, exist_ok=True)
        ii, att = pick_candidate(_search(name), name, description)
        if ii is None:
            with open(none, 'w', encoding='utf-8') as f:
                f.write(str(int(time.time())))
            return graphics.avatar_svg(name, seed=key), 'image/svg+xml', 'avatar', None
        blob = _get(att['url'], binary=True)
        with open(img, 'wb') as f:
            f.write(blob)
        with open(meta, 'w', encoding='utf-8') as f:
            json.dump(att, f, ensure_ascii=False, sort_keys=True)
        _append_credit(d, key, att)
        return blob, 'image/jpeg', 'photo', att
    except Exception:
        # Network failure is not a "no photo" answer: do not poison the cache.
        return graphics.avatar_svg(name, seed=key), 'image/svg+xml', 'avatar', None


def _append_credit(directory, key, att):
    """One line per accepted image, so attribution ships with the cache."""
    p = os.path.join(directory, 'CREDITS.txt')
    line = '%s\t%s\t%s\t%s\t%s\n' % (key, att.get('artist', ''), att.get('licence', ''),
                                    att.get('file', ''), att.get('page', ''))
    try:
        with open(p, 'a', encoding='utf-8') as f:
            f.write(line)
    except OSError:
        pass


def status(directory):
    d = os.path.join(directory, 'faces')
    try:
        names = os.listdir(d)
    except OSError:
        return {'photos': 0, 'negative': 0}
    return {'photos': sum(1 for n in names if n.endswith('.jpg')),
            'negative': sum(1 for n in names if n.endswith('.none'))}
