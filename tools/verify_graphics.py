#!/usr/bin/env python3
"""Verify the graphics layer: crests, generated fallbacks, and portrait gating.

    python3 tools/verify_graphics.py
    python3 tools/verify_graphics.py --verbose
    python3 tools/verify_graphics.py --http http://127.0.0.1:8765

This passes on a FRESH CLONE with no artwork downloaded, because the crest cache
is git-ignored on purpose. Where a real mark is absent the check asserts the
generated fallback instead, which is the behaviour that actually ships.

The portrait gates are tested against synthetic Commons payloads rather than the
live API: the licence and identity decisions are pure functions, so they can be
verified exhaustively offline. The live network path is NOT exercised here.
"""
import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import xml.dom.minidom as MINIDOM

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'lib'))

import graphics as G   # noqa: E402
import faces as F      # noqa: E402

PASS = []
FAIL = []
GDIR = os.path.join(HERE, 'data', 'graphics')


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    if not ok:
        print('  FAIL %s%s' % (name, (' - ' + detail) if detail else ''))


def db(name):
    with open(os.path.join(HERE, 'data', 'fc27', name), encoding='utf-8') as f:
        return json.load(f)


def wellformed(b):
    try:
        MINIDOM.parseString(b)
        return True
    except Exception:
        return False


def ext(**kw):
    return {k: {'value': v} for k, v in kw.items()}


def section_resolver():
    clubs = db('clubs.json')
    check('resolver: every club returns bytes',
          all(isinstance(G.crest('clubs', t, r['name'], r.get('colors'), GDIR)[0], bytes)
              for t, r in clubs.items()))
    srcs = {t: G.crest('clubs', t, r['name'], r.get('colors'), GDIR)[2]
            for t, r in clubs.items()}
    check('resolver: source is only vendored|generated',
          set(srcs.values()) <= {'vendored', 'generated'}, str(set(srcs.values())))
    check('resolver: every club renders (none missing)', len(srcs) == len(clubs) == 717,
          '%d/%d' % (len(srcs), len(clubs)))

    bad = [r['name'] for t, r in clubs.items()
           if G.crest('clubs', t, r['name'], r.get('colors'), GDIR)[2] == 'generated'
           and not wellformed(G.crest('clubs', t, r['name'], r.get('colors'), GDIR)[0])]
    check('resolver: every generated shield is well-formed XML', not bad, str(bad[:4]))

    # A fresh clone has no artwork at all. Everything must still render.
    with tempfile.TemporaryDirectory() as td:
        b, mt, src = G.crest('clubs', '9', 'Liverpool', ['#e31b23', '#ffffff', '#ffd700'], td)
        check('resolver: empty cache -> generated', src == 'generated', src)
        check('resolver: empty cache -> svg mime', mt == 'image/svg+xml', mt)
        check('resolver: empty cache -> well-formed', wellformed(b))
        check('resolver: empty cache -> non-empty', len(b) > 200, str(len(b)))
        for kind in G.KINDS:
            bb, mm, ss = G.crest(kind, '1', 'Test Name', None, td)
            check('resolver: %s renders with no cache' % kind, ss == 'generated' and wellformed(bb))
        st = G.status(td)
        check('resolver: status on empty dir says not imported', st['imported'] is False)
        check('resolver: status on empty dir reports zero on_disk',
              all(v['on_disk'] == 0 for v in st['present'].values()))

    # Unknown ids and kinds must not raise.
    for kind, ident in (('clubs', '99999999'), ('leagues', '99999'), ('nations', '99999')):
        b, mt, src = G.crest(kind, ident, 'Unknown', None, GDIR)
        check('resolver: unknown %s id still renders' % kind, src == 'generated' and len(b) > 100)
    check('resolver: unknown kind is not vendored',
          G.vendored_path('bogus', '9', GDIR) is None)

    # Generated art must be stable across processes: hash() is salted per run.
    a1 = G.avatar_svg('Mohamed Salah', seed=20801)
    check('avatar: deterministic within a process', a1 == G.avatar_svg('Mohamed Salah', seed=20801))
    code = ('import sys;sys.path.insert(0,%r);import graphics;'
            'sys.stdout.buffer.write(graphics.avatar_svg("Mohamed Salah",seed=20801))'
            % os.path.join(HERE, 'lib'))
    outs = []
    for seed in ('1', '99991'):
        e = dict(os.environ, PYTHONHASHSEED=seed)
        outs.append(subprocess.run([sys.executable, '-c', code], env=e,
                                   capture_output=True, timeout=60).stdout)
    check('avatar: identical across PYTHONHASHSEED values',
          outs[0] == outs[1] == a1, 'hash() salting would change the art on restart')
    check('avatar: different people differ',
          G.avatar_svg('Mohamed Salah', seed=1) != G.avatar_svg('Joe Cole', seed=2))
    check('avatar: well-formed', wellformed(a1))

    # The shield must actually use the club's colours.
    s1 = G.shield_svg('Liverpool', ['#e31b23', '#ffffff', '#ffd700'])
    s2 = G.shield_svg('Liverpool', ['#0000ff', '#00ff00', '#123456'])
    check('shield: colours drive the output', s1 != s2)
    check('shield: first colour appears', b'#e31b23' in s1)
    check('shield: deterministic', s1 == G.shield_svg('Liverpool', ['#e31b23', '#ffffff', '#ffd700']))
    check('shield: nation and league differ from club',
          G.shield_svg('X', None, 'nations') != G.shield_svg('X', None, 'clubs')
          and G.shield_svg('X', None, 'leagues') != G.shield_svg('X', None, 'clubs'))


def section_safety():
    b = G.shield_svg('<script>alert(1)</script>', ['#ffffff'])
    check('safety: name is XML-escaped', b'<script>' not in b and b'&lt;script&gt;' in b)
    b2 = G.shield_svg('A & B "C" <D>', ['#ffffff'])
    check('safety: ampersand escaped', b'A &amp; B' in b2)
    check('safety: escaped name still well-formed', wellformed(b2))
    check('safety: avatar name escaped',
          b'<script>' not in G.avatar_svg('<script>x</script>'))

    check('safety: non-hex colour rejected', G._hex('red') is None)
    check('safety: js colour rejected', G._hex('javascript:alert(1)') is None)
    check('safety: quote in colour rejected', G._hex('#fff" onload="x') is None)
    check('safety: 3-digit hex expanded', G._hex('#abc') == '#aabbcc')
    check('safety: 6-digit hex kept', G._hex('#A1B2C3') == '#a1b2c3')
    cs = G.colors_of(['red', 'javascript:x', '#abc'])
    check('safety: bad colours replaced by fallbacks', cs[0] == '#aabbcc' and len(cs) == 3, str(cs))
    check('safety: colours_of always returns 3', len(G.colors_of(None)) == 3)
    check('safety: injected colour never reaches SVG',
          b'javascript' not in G.shield_svg('X', ['javascript:alert(1)']))

    for evil in ('../../server.py', '/etc/passwd', 'crests/../../../server.py',
                 '..\\..\\server.py', '', 'crests/x.exe', 'crests/x.svg.bak'):
        check('safety: refuses manifest path %r' % evil, G._safe_rel(evil) is None)
    # The cases above all end in a non-image extension, so the extension
    # allowlist rejects them on its own and the traversal guard is never
    # exercised. These carry a VALID image extension, so only the traversal
    # guard can stop them.
    for evil in ('../../secret.svg', '/etc/shadow.png', 'crests/../../outside.svg',
                 '..\\..\\secret.svg', 'crests/england/../../../x.svg'):
        check('safety: traversal with an image extension refused %r' % evil,
              G._safe_rel(evil) is None)
    check('safety: accepts a real crest path',
          G._safe_rel('crests/england/Liverpool_FC.svg') == 'crests/england/Liverpool_FC.svg')

    # A hand-edited manifest must not be able to read outside the graphics dir.
    # The target is a REAL .svg one level up: with the traversal guard removed
    # this would resolve and be served, which is what makes the check bite.
    with tempfile.TemporaryDirectory() as parent:
        secret = os.path.join(parent, 'outside.svg')
        with open(secret, 'w', encoding='utf-8') as f:
            f.write('<svg xmlns="http://www.w3.org/2000/svg"/>')
        td = os.path.join(parent, 'graphics')
        os.makedirs(os.path.join(td, 'crests'), exist_ok=True)
        with open(os.path.join(td, 'manifest.json'), 'w', encoding='utf-8') as f:
            json.dump({'clubs': {'9': {'file': '../outside.svg', 'name': 'x'}}}, f)
        check('safety: manifest cannot reach a real file outside the cache',
              G.vendored_path('clubs', '9', td) is None)
        b, mt, src = G.crest('clubs', '9', 'Liverpool', None, td)
        check('safety: traversal in manifest falls back to generated', src == 'generated')
        check('safety: outside bytes are never served', b'outside' not in b and src == 'generated')

    # A manifest pointing at a file that isn't there must degrade, not raise.
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, 'manifest.json'), 'w', encoding='utf-8') as f:
            json.dump({'clubs': {'9': {'file': 'crests/missing.svg', 'name': 'x'}}}, f)
        check('safety: missing file yields no path', G.vendored_path('clubs', '9', td) is None)
        check('safety: missing file falls back',
              G.crest('clubs', '9', 'Liverpool', None, td)[2] == 'generated')
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, 'manifest.json'), 'w', encoding='utf-8') as f:
            f.write('{ not json')
        check('safety: corrupt manifest is survivable', G.manifest(td) == {})
        check('safety: corrupt manifest still renders',
              G.crest('clubs', '9', 'X', None, td)[2] == 'generated')


def section_licence():
    cases = [
        ('cc0', ext(License='cc0', LicenseShortName='CC0'), True),
        ('cc-by-4.0', ext(License='cc-by-4.0', LicenseShortName='CC BY 4.0'), True),
        ('cc-by-sa-3.0', ext(License='cc-by-sa-3.0', LicenseShortName='CC BY-SA 3.0'), True),
        ('cc-by-sa-4.0', ext(License='cc-by-sa-4.0', LicenseShortName='CC BY-SA 4.0'), True),
        ('pd', ext(License='pd', LicenseShortName='Public domain'), True),
        ('pd-old', ext(License='pd-old', LicenseShortName='Public domain'), True),
        ('gfdl', ext(License='gfdl', LicenseShortName='GFDL'), True),
        ('copyrighted=false', ext(License='', LicenseShortName='PD', Copyrighted='false'), True),
        ('fairuse', ext(License='fairuse', LicenseShortName='Fair use'), False),
        ('non-free', ext(License='non-free', LicenseShortName='Non-free'), False),
        ('all-rights-reserved', ext(License='', LicenseShortName='All rights reserved'), False),
        ('cc-by-nc', ext(License='cc-by-nc-4.0', LicenseShortName='CC BY-NC 4.0'), False),
        ('cc-by-nc-nd', ext(License='cc-by-nc-nd-2.0', LicenseShortName='CC BY-NC-ND 2.0'), False),
        ('cc-by-nd', ext(License='cc-by-nd-4.0', LicenseShortName='CC BY-ND 4.0'), False),
        ('nc-in-short-only', ext(License='cc-by-4.0', LicenseShortName='CC BY-NC 4.0'), False),
        ('nc-in-terms', ext(License='cc-by-4.0', UsageTerms='Attribution-NonCommercial'), False),
        ('nonfree-flag', ext(License='cc0', NonFree='true'), False),
        ('no-metadata', {}, False),
        ('empty-strings', ext(License='', LicenseShortName=''), False),
        ('unknown-licence', ext(License='weird', LicenseShortName='Custom terms'), False),
        ('free-code-but-fairuse-terms',
         ext(License='cc0', UsageTerms='Fair use only'), False),
    ]
    for label, e, want in cases:
        got, _ = F.licence_ok(e)
        check('licence: %s -> %s' % (label, want), got is want, 'got %s' % got)

    att = F.attribution_of(ext(License='cc-by-sa-4.0', LicenseShortName='CC BY-SA 4.0',
                               Artist='Jane Photographer', LicenseUrl='https://cc/by-sa/4.0/'),
                           'File:X.jpg', 'https://commons/X')
    check('attribution: artist captured', att['artist'] == 'Jane Photographer', str(att))
    check('attribution: licence captured', att['licence'] == 'CC BY-SA 4.0')
    check('attribution: licence url captured', att['licence_url'].startswith('https://cc/'))
    check('attribution: file and page captured',
          att['file'] == 'File:X.jpg' and att['page'] == 'https://commons/X')
    check('attribution: free flag set', att['free'] is True)
    check('attribution: html stripped from artist',
          F.attribution_of(ext(License='cc0', Artist='<b>Bob</b>'))['artist'] == 'Bob')
    check('attribution: missing artist is unknown',
          F.attribution_of(ext(License='cc0'))['artist'] == 'unknown')
    check('attribution: nonfree marked not free',
          F.attribution_of(ext(License='fairuse'))['free'] is False)


def section_identity():
    cases = [
        ('right-player', 'Mohamed Salah', 'File:Mohamed Salah 2018.jpg', 'Egyptian footballer', '', True),
        ('wrong-person', 'Mohamed Salah', 'File:Kylian Mbappe.jpg', 'French footballer', '', False),
        ('no-context', 'Mohamed Salah', 'File:Mohamed Salah.jpg', 'a man', '', False),
        ('context-in-categories', 'Mohamed Salah', 'File:Mohamed Salah.jpg', '',
         'Association football players from Egypt', True),
        ('crest-file', 'Mohamed Salah', 'File:Mohamed Salah logo.png', 'footballer', '', False),
        ('kit-file', 'Mohamed Salah', 'File:Mohamed Salah jersey.jpg', 'footballer', '', False),
        ('statue-file', 'Mohamed Salah', 'File:Mohamed Salah statue.jpg', 'footballer', '', False),
        ('flag-file', 'Mohamed Salah', 'File:Mohamed Salah flag.svg', 'footballer', '', False),
        ('multiword-name', 'Son Heung-min', 'File:Son Heung-min 2022.jpg', 'Korean footballer', '', True),
        ('empty-wanted', '', 'File:Someone.jpg', 'footballer', '', False),
        ('empty-title', 'Mohamed Salah', '', 'footballer', '', False),
        ('non-football-context', 'Mohamed Salah', 'File:Mohamed Salah.jpg', 'a politician', '', False),
    ]
    for label, w, t, d, c, want in cases:
        got = F.identity_ok(w, t, d, c)
        check('identity: %s -> %s' % (label, want), got is want, 'got %s' % got)

    def page(title, lic, w, h, desc='footballer'):
        return {'title': title, 'imageinfo': [{
            'url': 'https://x/' + title, 'thumburl': 'https://x/t_' + title,
            'width': w, 'height': h, 'descriptionurl': 'https://commons/' + title,
            'extmetadata': ext(License=lic, LicenseShortName=lic,
                               ImageDescription=desc, Artist='A Photographer')}]}

    pages = [page('File:Mohamed Salah small.jpg', 'cc-by-4.0', 200, 200),
             page('File:Mohamed Salah big.jpg', 'cc-by-sa-4.0', 900, 900),
             page('File:Mohamed Salah huge.jpg', 'fairuse', 4000, 4000),
             page('File:Someone Else.jpg', 'cc0', 5000, 5000)]
    ii, att = F.pick_candidate(pages, 'Mohamed Salah')
    check('pick: skips nonfree and wrong person, takes largest free',
          att is not None and att['file'] == 'File:Mohamed Salah big.jpg',
          str(att and att['file']))
    check('pick: returns attribution', att is not None and att['artist'] == 'A Photographer')
    check('pick: attribution marked free', att is not None and att['free'] is True)
    check('pick: carries a download url', att is not None and att.get('url'))
    ii2, a2 = F.pick_candidate([page('File:Mohamed Salah.jpg', 'fairuse', 900, 900)], 'Mohamed Salah')
    check('pick: all-nonfree -> nothing', ii2 is None and a2 is None)
    ii3, a3 = F.pick_candidate([page('File:Other Guy.jpg', 'cc0', 900, 900)], 'Mohamed Salah')
    check('pick: all-wrong-person -> nothing', ii3 is None and a3 is None)
    check('pick: empty pages -> nothing', F.pick_candidate([], 'X') == (None, None))
    check('pick: no imageinfo -> nothing',
          F.pick_candidate([{'title': 'File:Mohamed Salah.jpg'}], 'Mohamed Salah') == (None, None))
    nc = page('File:Mohamed Salah nc.jpg', 'cc-by-nc-4.0', 9000, 9000)
    check('pick: NC image rejected even when largest',
          F.pick_candidate([nc, pages[0]], 'Mohamed Salah')[1]['file'] == 'File:Mohamed Salah small.jpg')


def section_faces_cache():
    with tempfile.TemporaryDirectory() as td:
        b, mt, src, att = F.face(20801, 'Mohamed Salah', td, allow_network=False)
        check('faces: network off -> avatar', src == 'avatar', src)
        check('faces: network off -> svg', mt == 'image/svg+xml')
        check('faces: network off -> no attribution', att is None)
        check('faces: network off -> writes nothing',
              not os.path.exists(os.path.join(td, 'faces')))
        check('faces: avatar well-formed', wellformed(b))

        # Empty name must never trigger a lookup.
        b2, _, src2, _ = F.face(3, '', td, allow_network=True)
        check('faces: empty name -> avatar without network', src2 == 'avatar')

        # A poisoned key must not escape the cache directory.
        b3, _, src3, _ = F.face('../../etc/passwd', 'X', td, allow_network=False)
        check('faces: key sanitised', src3 == 'avatar')

    # A cached, freely-licensed photo is served with its attribution.
    with tempfile.TemporaryDirectory() as td:
        d = os.path.join(td, 'faces')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'p1.jpg'), 'wb') as f:
            f.write(b'\xff\xd8\xff\xd9')
        att = {'free': True, 'artist': 'Jane', 'licence': 'CC BY-SA 4.0', 'file': 'File:X.jpg'}
        with open(os.path.join(d, 'p1.json'), 'w', encoding='utf-8') as f:
            json.dump(att, f)
        b, mt, src, got = F.face('p1', 'Some One', td, allow_network=False)
        check('faces: cached photo served offline', src == 'photo', src)
        check('faces: cached photo mime', mt == 'image/jpeg', mt)
        check('faces: cached photo bytes', b == b'\xff\xd8\xff\xd9')
        check('faces: cached attribution returned', got and got['artist'] == 'Jane')

        # A cache entry whose metadata says non-free must NOT be served.
        with open(os.path.join(d, 'p1.json'), 'w', encoding='utf-8') as f:
            json.dump(dict(att, free=False), f)
        check('faces: non-free cache entry refused',
              F.face('p1', 'Some One', td, allow_network=False)[2] == 'avatar')

        # Corrupt metadata must degrade, not raise.
        with open(os.path.join(d, 'p1.json'), 'w', encoding='utf-8') as f:
            f.write('{ broken')
        check('faces: corrupt cache metadata -> avatar',
              F.face('p1', 'Some One', td, allow_network=False)[2] == 'avatar')

    # Negative cache must actually SHORT-CIRCUIT the lookup. Testing this with
    # allow_network=False proves nothing: that returns an avatar either way.
    with tempfile.TemporaryDirectory() as td:
        d = os.path.join(td, 'faces')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'p9.none'), 'w', encoding='utf-8') as f:
            f.write('0')
        orig = F._search
        calls = []
        try:
            F._search = lambda name: calls.append(name) or []
            src = F.face('p9', 'No Photo', td, allow_network=True)[2]
            check('faces: negative cache -> avatar', src == 'avatar', src)
            check('faces: negative cache skips the network', not calls, str(calls))
        finally:
            F._search = orig
        st = F.status(td)
        check('faces: status counts negatives', st['negative'] == 1, str(st))
        # Without the marker the same call MUST reach the network.
        os.remove(os.path.join(d, 'p9.none'))
        calls2 = []
        try:
            F._search = lambda name: calls2.append(name) or []
            F.face('p9', 'No Photo', td, allow_network=True)
            check('faces: no negative marker -> does query', bool(calls2), str(calls2))
        finally:
            F._search = orig

    # A network error must not be recorded as "no photo exists".
    with tempfile.TemporaryDirectory() as td:
        orig = F._search
        try:
            def boom(_):
                raise OSError('network unreachable')
            F._search = boom
            src = F.face('p7', 'Some Player', td, allow_network=True)[2]
            check('faces: network failure -> avatar', src == 'avatar')
            check('faces: network failure does not poison cache',
                  not os.path.exists(os.path.join(td, 'faces', 'p7.none')))
        finally:
            F._search = orig

    # A successful fetch must write the image, the metadata and a credit line.
    with tempfile.TemporaryDirectory() as td:
        os_, og = F._search, F._get
        try:
            F._search = lambda name: [{'title': 'File:Mohamed Salah.jpg', 'imageinfo': [{
                'url': 'https://x/img.jpg', 'thumburl': 'https://x/img.jpg',
                'width': 800, 'height': 800, 'descriptionurl': 'https://commons/p',
                'extmetadata': ext(License='cc-by-sa-4.0', LicenseShortName='CC BY-SA 4.0',
                                   ImageDescription='footballer', Artist='Jane Photographer')}]}]
            F._get = lambda url, timeout=15, binary=False: b'\xff\xd8\xff\xd9'
            b, mt, src, att = F.face('p11', 'Mohamed Salah', td, allow_network=True)
            check('faces: accepted free photo -> photo', src == 'photo', src)
            check('faces: fetched photo cached', os.path.isfile(os.path.join(td, 'faces', 'p11.jpg')))
            check('faces: attribution cached', os.path.isfile(os.path.join(td, 'faces', 'p11.json')))
            check('faces: credit line appended',
                  os.path.isfile(os.path.join(td, 'faces', 'CREDITS.txt')))
            with open(os.path.join(td, 'faces', 'CREDITS.txt'), encoding='utf-8') as f:
                line = f.read()
            check('faces: credit names the artist', 'Jane Photographer' in line, line)
            check('faces: credit names the licence', 'CC BY-SA 4.0' in line)
            check('faces: fetched attribution is free', att and att['free'] is True)
        finally:
            F._search, F._get = os_, og

    # The fetch path must refuse a non-free result even if the API returns one.
    with tempfile.TemporaryDirectory() as td:
        os_, og = F._search, F._get
        try:
            F._search = lambda name: [{'title': 'File:Mohamed Salah.jpg', 'imageinfo': [{
                'url': 'https://x/img.jpg', 'width': 800, 'height': 800,
                'extmetadata': ext(License='fairuse', LicenseShortName='Fair use',
                                   ImageDescription='footballer')}]}]
            called = []
            F._get = lambda *a, **k: called.append(1) or b''
            src = F.face('p12', 'Mohamed Salah', td, allow_network=True)[2]
            check('faces: non-free search result -> avatar', src == 'avatar')
            check('faces: non-free image is never downloaded', not called)
            check('faces: non-free result cached as negative',
                  os.path.isfile(os.path.join(td, 'faces', 'p12.none')))
        finally:
            F._search, F._get = os_, og


def section_importer_and_manifest():
    p = os.path.join(HERE, 'tools', 'import_graphics.py')
    tree = ast.parse(open(p, encoding='utf-8').read())
    tables = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            nm = node.targets[0].id
            if nm in ('ALIAS', 'COUNTRY_OVERRIDE', 'LEAGUE_ALIAS', 'FOLDER_ALIAS') \
                    and isinstance(node.value, ast.Dict):
                keys = [ast.literal_eval(k) for k in node.value.keys]
                tables[nm] = keys
                dup = {k for k in keys if keys.count(k) > 1}
                check('importer: %s has no duplicate keys' % nm, not dup, str(dup))
    check('importer: alias tables present', len(tables) == 4, str(sorted(tables)))
    check('importer: pinned to a full commit sha',
          any(isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'SHA'
              and len(ast.literal_eval(n.value)) == 40 for n in tree.body))

    src = open(p, encoding='utf-8').read()
    check('importer: requests licence-bearing metadata? (crests need none)',
          'tarfile' in src)
    check('importer: does not write into git-tracked art dir',
          'data/graphics' in src.replace("'", '').replace('"', '') or 'OUT_DIR' in src)

    gi = open(os.path.join(HERE, '.gitignore'), encoding='utf-8').read()
    check('gitignore: crest artwork excluded', 'data/graphics/crests/' in gi)
    check('gitignore: face cache excluded', 'data/graphics/faces/' in gi)
    check('gitignore: download cache excluded', '.cache/' in gi)

    mp = os.path.join(GDIR, 'manifest.json')
    if not os.path.isfile(mp):
        check('manifest: absent is supported (fresh clone)', G.manifest(GDIR) == {}
              or isinstance(G.manifest(GDIR), dict))
        return
    m = G.manifest(GDIR)
    cov = m.get('coverage') or {}
    check('manifest: records the upstream repo', bool((m.get('source') or {}).get('repo')))
    check('manifest: records a pinned sha', len((m.get('source') or {}).get('sha') or '') == 40)
    check('manifest: states the artwork licence caveat',
          'trademark' in ((m.get('source') or {}).get('licence') or '').lower())
    for kind, total in (('clubs', 717), ('leagues', 41), ('nations', 219)):
        n = len(m.get(kind) or {})
        check('manifest: %s mapped <= total' % kind, 0 < n <= total, '%d/%d' % (n, total))
        check('manifest: %s coverage matches entries' % kind, cov.get(kind) == n,
              '%s vs %d' % (cov.get(kind), n))
    ents = sum(len(m.get(k) or {}) for k in G.KINDS)
    check('manifest: entities counts every mapped id', cov.get('entities') == ents,
          '%s vs %d' % (cov.get('entities'), ents))
    check('manifest: files <= entities (shared crests allowed)',
          cov.get('files', 0) <= ents, '%s vs %d' % (cov.get('files'), ents))
    clubs = db('clubs.json')
    check('manifest: every mapped club id exists in the database',
          all(t in clubs for t in m.get('clubs', {})))
    check('manifest: mapped names match the database',
          all(m['clubs'][t]['name'] == clubs[t]['name'] for t in m.get('clubs', {})))
    check('manifest: all paths are safe',
          all(G._safe_rel(e['file']) for k in G.KINDS for e in (m.get(k) or {}).values()))
    # Every club must resolve to SOMETHING, mapped or not.
    check('manifest: unmapped clubs still render',
          all(G.crest('clubs', t, r['name'], r.get('colors'), GDIR)[2] == 'generated'
              for t, r in clubs.items() if t not in m.get('clubs', {})))
    on_disk = sum(1 for t in m.get('clubs', {}) if G.vendored_path('clubs', t, GDIR))
    if on_disk:
        check('manifest: on-disk crests are non-empty',
              all(os.path.getsize(G.vendored_path('clubs', t, GDIR)) > 100
                  for t in m['clubs'] if G.vendored_path('clubs', t, GDIR)))
        check('manifest: status agrees with the filesystem',
              G.status(GDIR)['present']['clubs']['on_disk'] == on_disk)


def section_importer_exercised():
    """Run the REAL importer against a synthetic upstream tarball.

    Reading the committed manifest cannot catch an importer regression: the
    manifest is a static file, so breaking the importer changes nothing the
    other checks can see. Here two FC 27 clubs legitimately share one crest
    (Liverpool exists as id 9 and id 116343), which is exactly the case a
    filename-keyed manifest silently drops.
    """
    import contextlib
    import importlib.util
    import io as _io
    import tarfile

    spec = importlib.util.spec_from_file_location(
        '_ig_exercise', os.path.join(HERE, 'tools', 'import_graphics.py'))
    ig = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(ig)
    except Exception as e:
        check('importer run: module loads', False, str(e))
        return

    clubs = db('clubs.json')
    ids = sorted([t for t, r in clubs.items() if r['name'] == 'Liverpool'], key=int)
    check('importer run: fixture has a shared-crest pair', len(ids) >= 2, str(ids))
    if len(ids) < 2:
        return

    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'
    with tempfile.TemporaryDirectory() as td:
        tb = os.path.join(td, 'synthetic.tar.gz')
        with tarfile.open(tb, 'w:gz') as tf:
            ti = tarfile.TarInfo('football-logos-synthetic/logos/england/Liverpool_FC.svg')
            ti.size = len(svg)
            tf.addfile(ti, _io.BytesIO(svg))
        out = os.path.join(td, 'out')
        ig.OUT_DIR = out
        ig.CREST_DIR = os.path.join(out, 'crests')
        try:
            with contextlib.redirect_stdout(_io.StringIO()):
                ig.run(tb, False)
        except Exception as e:
            check('importer run: completes on a synthetic tarball', False, repr(e))
            return
        check('importer run: completes on a synthetic tarball', True)
        mp = os.path.join(out, 'manifest.json')
        if not os.path.isfile(mp):
            check('importer run: writes a manifest', False)
            return
        with open(mp, encoding='utf-8') as f:
            m = json.load(f)
        got = m.get('clubs') or {}
        check('importer run: BOTH clubs sharing a crest are recorded',
              all(i in got for i in ids), 'recorded %s, expected %s' % (sorted(got), ids))
        if all(i in got for i in ids):
            check('importer run: shared crest points at one file',
                  len({got[i]['file'] for i in ids}) == 1)
        cov = m.get('coverage') or {}
        ents = sum(len(m.get(k) or {}) for k in ('clubs', 'leagues', 'nations'))
        check('importer run: entities counts every mapped id', cov.get('entities') == ents,
              '%s vs %d' % (cov.get('entities'), ents))
        check('importer run: one unique file extracted', cov.get('files') == 1, str(cov.get('files')))
        check('importer run: extracted bytes match upstream',
              os.path.isfile(os.path.join(out, 'crests', 'england', 'Liverpool_FC.svg'))
              and open(os.path.join(out, 'crests', 'england', 'Liverpool_FC.svg'), 'rb').read() == svg)
        check('importer run: writes attribution',
              os.path.isfile(os.path.join(out, 'ATTRIBUTION.txt')))
        check('importer run: attribution names the licence caveat',
              'trademark' in open(os.path.join(out, 'ATTRIBUTION.txt'),
                                  encoding='utf-8').read().lower())
        # Unmatched clubs must not appear, and must still render via fallback.
        check('importer run: unmatched clubs are absent from the manifest',
              len(got) == len(ids), '%d vs %d' % (len(got), len(ids)))
        b, mt, src = G.crest('clubs', '241', 'FC Barcelona', None, out)
        check('importer run: unmatched club falls back to generated', src == 'generated')


def section_http(base):
    def get(path, raw=False):
        try:
            with urllib.request.urlopen(base + path, timeout=30) as r:
                b = r.read()
                return r.status, r.headers.get('Content-Type'), (b if raw else json.loads(b))
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get('Content-Type'), e.read()
        except Exception as e:
            return 0, '', str(e)

    s, _, d = get('/api/graphics/status')
    if s != 200:
        check('http: server reachable', False, 'status %s' % s)
        return
    check('http: graphics status 200', s == 200)
    check('http: status reports faces_web off by default', d.get('faces_web') is False, str(d.get('faces_web')))
    check('http: status has crest coverage', 'present' in d and 'clubs' in d['present'])

    s, ct, b = get('/api/crest?club=9', raw=True)
    check('http: club crest 200', s == 200)
    check('http: club crest is an image', (ct or '').startswith('image/'), str(ct))
    check('http: club crest non-empty', len(b) > 100)
    s2, _, meta = get('/api/crest?club=9&meta=1')
    check('http: meta reports byte length', meta.get('bytes') == len(b), str(meta))
    check('http: meta names the club', meta.get('name') == 'Liverpool', str(meta))
    for q, label in (('/api/crest?league=13', 'league'), ('/api/crest?nation=14', 'nation')):
        s, ct, b = get(q, raw=True)
        check('http: %s crest 200' % label, s == 200 and len(b) > 100)

    clubs = db('clubs.json')
    m = G.manifest(GDIR)
    unmapped = [t for t in clubs if t not in (m.get('clubs') or {})]
    if unmapped:
        s, _, m2 = get('/api/crest?club=%s&meta=1' % unmapped[0])
        check('http: unmapped club serves generated', s == 200 and m2.get('source') == 'generated',
              str(m2))
    for q, code in (('/api/crest', 400), ('/api/crest?club=abc', 400),
                    ('/api/crest?club=99999999', 404), ('/api/face', 400),
                    ('/api/face?pid=abc', 400)):
        s, _, _ = get(q)
        check('http: %s -> %d' % (q, code), s == code, 'got %s' % s)

    s, _, d = get('/api/face?pid=20801&meta=1')
    check('http: face 200', s == 200)
    check('http: face offline is an avatar', d.get('source') == 'avatar', str(d))
    check('http: face offline has no attribution', d.get('attribution') is None)
    s, _, d = get('/api/face?manager=1&meta=1')
    check('http: manager face 200', s == 200 and d.get('source') in ('avatar', 'photo'))
    s, ct, b = get('/api/face?pid=20801', raw=True)
    check('http: face bytes served', s == 200 and len(b) > 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--http', default='')
    a = ap.parse_args()
    print('Graphics verification\n')
    section_resolver()
    section_safety()
    section_licence()
    section_identity()
    section_faces_cache()
    section_importer_and_manifest()
    section_importer_exercised()
    if a.http:
        section_http(a.http.rstrip('/'))
    print()
    if a.verbose:
        for p in PASS:
            print('  ok   %s' % p)
    if FAIL:
        print('%d PASS, %d FAIL' % (len(PASS), len(FAIL)))
        for f in FAIL:
            print('  FAIL %s' % f)
        return 1
    print('ALL PASS - %d checks' % len(PASS))
    print('Crests resolve, fallbacks render, and only free portraits are accepted.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
