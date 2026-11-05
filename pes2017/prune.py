#!/usr/bin/env python3
"""Remove FL26 / FL27 / Sider-only files from the PES 2017 build.

Called by ``build.py`` after ``patch.apply()``.  This is deliberately a
**curated allowlist of removals**, not a "delete everything FL26" sweep:

* Sider addons (regen fix, Michele & Claude Lua mods, F7 dump modules) are
  for Football Life 26 / 27 with Sider.  PES 2017 has no Sider install in this
  build and every server reference to them is guarded (``_regen_src()``,
  ``_mich_src()``, ``put()``), so Setup simply reports "not available".
* ``FL_key.bin`` is the FL27 save key.  PES 2017 saves use ``KEY_PES17``;
  ``_fl_key()`` already returns None when the file is missing.
* The five FL26 player databases are **shadowed** on a PES 2017 save: r1
  writes ``data/pes17/{players,positions,playpos,ratings,teamids}.json`` from
  the user's real ``EDIT00000000`` and ``_dbf()`` resolves those first once
  ``_GAME['v'] == 'pes17'``.  ``mlwrite.load_names()`` / ``load_positions()``
  return ``{}`` when a file is absent, ``PLAYPOS`` is in a try/except, and
  ``ratings.json`` is guarded by ``os.path.exists`` — so startup is safe.
  ``realmoves.json`` is a Wikipedia-derived FL26 transfer cache.

Everything else is KEPT on purpose: the classic app is still reachable at
``/index.html`` and uses ``static/index.html``, ``static/art/*``,
``static/leagues/*``, ``data/art/*``, ``data/myscenes/*``,
``data/stadiums/*``, the i18n strings, ``fm_text.json``, ``scenes.json``,
``teamids.json`` and the small FL26 metadata JSONs.  All ``lib/*.py`` stay
(server.py imports most of them at startup).  The bundled ``python/*`` stays
(this is a portable Windows build).

No file is deleted from the source repository or the original zip — only from
the freshly extracted build tree.  Every removal is recorded in
``CLEANUP_MANIFEST.txt`` inside the shipped program.
"""
import os

# (relative path, is_directory, reason)
RULES = (
    ('addons/regenfix', True,
     'FL26 Sider regen fix (fl26regen.dll/.lua/.bin + 90 regen DDS faces); no Sider in PES 2017'),
    ('addons/michele', True,
     'FL26 Sider Master League Realism Lua modules (Michele & Claude); no Sider in PES 2017'),
    ('lua', True,
     'Sider F7 PlayerDump / GrowthBridge Lua modules; PES 2017 has no F7 dump'),
    ('FL_key.bin', False,
     'FL27 save key; PES 2017 uses KEY_PES17 and _fl_key() tolerates a missing file'),
    ('FL_key_README.txt', False,
     'FL27 key note; only relevant to the removed FL_key.bin'),
    ('data/players.json', False,
     'FL26 player names; PES 2017 builds data/pes17/players.json from EDIT00000000'),
    ('data/positions.json', False,
     'FL26 positions; shadowed by data/pes17/positions.json'),
    ('data/playpos.json', False,
     'FL26 preferred positions; shadowed by data/pes17/playpos.json'),
    ('data/ratings.json', False,
     'FL26 ratings; shadowed by data/pes17/ratings.json'),
    ('data/realmoves.json', False,
     'FL26 Wikipedia-derived real-transfer cache; not used by PES 2017'),
)

# Must survive, otherwise the classic app / PES 2017 runtime would break.
KEEP = (
    'server.py', 'VERSION.txt', 'README.txt', 'README_PES2017.txt',
    'config_pes2017.example.json', 'CPK_ASSET_INVENTORY.md',
    'CLEANUP_REPORT.md',
    'The Gaffer.vbs', 'The Gaffer.bat', 'TheGaffer.ico',
    'static/index.html', 'static/pes17.html', 'static/favicon.png',
    'static/hud-icons.svg', 'static/hud-icons.js', 'static/hud-ui.css',
    'static/game-shell.css', 'static/game-shell.js', 'static/pes17-face-refresh.js',
    'static/art/gaffer-mark-180.png', 'static/leagues/premier-league.png',
    'data/teamids.json', 'data/venue_metadata.json', 'data/club_identity.json',
    'data/owners.json', 'data/fl26_installed_league_counts.json',
    'data/fm_text.json', 'data/myscenes/scenes.json',
    'data/art/banner.jpg', 'data/stadiums/168c2dd70223be0d.jpg',
    'data/i18n/strings_en.json', 'data/i18n/it.json',
    'lib/pes17.py', 'lib/pes17_write.py', 'lib/pes17_pairs.py',
    'lib/pes17_crests.py', 'lib/pes17_faces.py', 'lib/pes17_assets.py',
    'lib/pes17_setup.py',
    'FIRST_RUN.md', 'lib/pescrypt.py',
    'lib/mlwrite.py', 'lib/cpkread.py', 'lib/dds.py', 'lib/ftex.py', 'lib/bc7.py',
    'python/python.exe', 'python/python312.dll',
    'tools/harvest_cpk.py',
)


def plan(root):
    """List (relative path, size, reason) of everything that would be removed."""
    out = []
    for rel, isdir, why in RULES:
        base = os.path.join(root, *rel.split('/'))
        if isdir:
            if not os.path.isdir(base):
                continue
            for d, _, files in os.walk(base):
                for f in files:
                    p = os.path.join(d, f)
                    r = os.path.relpath(p, root).replace(os.sep, '/')
                    try:
                        sz = os.path.getsize(p)
                    except OSError:
                        sz = 0
                    out.append((r, sz, why))
        else:
            if os.path.isfile(base):
                out.append((rel, os.path.getsize(base), why))
    return sorted(out)


def apply(root):
    """Remove the curated files, write a manifest, and verify the keep set."""
    removed = plan(root)
    for rel, _, _ in removed:
        p = os.path.join(root, *rel.split('/'))
        try:
            os.remove(p)
        except OSError:
            pass
    # Drop the now-empty directories (addons/, lua/, and their children).
    for rel, isdir, _ in RULES:
        if not isdir:
            continue
        base = os.path.join(root, *rel.split('/'))
        for d, _, _ in os.walk(base, topdown=False):
            try:
                os.rmdir(d)
            except OSError:
                pass
    for parent in ('addons',):
        p = os.path.join(root, parent)
        if os.path.isdir(p):
            try:
                os.rmdir(p)
            except OSError:
                pass

    total = sum(sz for _, sz, _ in removed)
    lines = [
        'THE GAFFER - PES 2017 BUILD: SAFE CLEANUP MANIFEST',
        '==================================================',
        '',
        'Only files listed below were removed from this build. They are',
        'FL26 / FL27 / Sider-only, or FL26 databases that the PES 2017',
        'build replaces with data/pes17/*.json generated from your real',
        'EDIT00000000. No file was changed in the game, patch or save folder.',
        '',
        'Removed: %d files, %d bytes (%.2f MB)' % (len(removed), total, total / 1e6),
        '',
    ]
    for rel, sz, why in removed:
        lines.append('  %-72s %9d  %s' % (rel, sz, why))
    lines += [
        '',
        'KEPT ON PURPOSE',
        '----------------',
        'The classic UI is the default landing page at / (index.html), so its',
        'HTML, art, scenes, stadium photos, i18n strings, fm_text.json,',
        'teamids.json and small metadata JSONs stay. All lib/*.py stay because',
        'server.py imports them at startup or lazily. The bundled portable',
        'python/* stays because this is a Windows build. The PES 2017',
        'tools (/pes17.html), crest/face readers, CPK harvester,',
        'measured writes, layout guard and backups are untouched.',
        '',
        'Nothing here is an in-game save-load test. Keep a backup.',
        '',
    ]
    with open(os.path.join(root, 'CLEANUP_MANIFEST.txt'), 'w',
              encoding='utf-8', newline='\r\n') as f:
        f.write('\n'.join(lines))

    missing = [k for k in KEEP if not os.path.isfile(os.path.join(root, *k.split('/')))]
    if missing:
        raise RuntimeError('cleanup removed a file that must be kept: %s' % ', '.join(missing))
    left = [r for r, _, _ in removed if os.path.exists(os.path.join(root, *r.split('/')))]
    if left:
        raise RuntimeError('cleanup failed to remove: %s' % ', '.join(left[:5]))
    return dict(removed=len(removed), bytes=total, files=[r for r, _, _ in removed],
                kept=len(KEEP), manifest='CLEANUP_MANIFEST.txt')


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    print(apply(sys.argv[1]))
