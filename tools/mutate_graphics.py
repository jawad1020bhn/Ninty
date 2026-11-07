"""Mutation test for tools/verify_graphics.py.

    python3 tools/mutate_graphics.py

A check that passes before AND after a mutation is not a check. Each mutant
re-introduces one defect the graphics layer is supposed to prevent: serving a
non-free portrait, shipping the wrong human's face, publishing trademarked
artwork, or failing to render when the crest cache is absent. The verifier must
FAIL for every one. Files are always restored, even on error.
"""
import io
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

MUTANTS = [
    # --- licence gate -----------------------------------------------------
    ('a missing licence is treated as free', 'lib/faces.py',
     '    if not code and not short and not terms:\n        return False, \'\'',
     '    if not code and not short and not terms:\n        return True, \'\'', 'REPLACE'),
    ('fair-use images are accepted', 'lib/faces.py',
     '    for bad in _NONFREE:\n        if bad in blob:\n            return False, short',
     '    for bad in _NONFREE:\n        if False:\n            return False, short', 'REPLACE'),
    ('the NonFree flag is ignored', 'lib/faces.py',
     "    if _norm(_meta(extmetadata, 'NonFree')) in ('true', '1', 'yes'):",
     '    if False:', 'REPLACE'),
    ('NC/ND detection reverts to the hyphen bug', 'lib/faces.py',
     '            toks = set(code.split()) | set(_norm(short).split()) | set(_norm(terms).split())',
     "            toks = set() if '-nc' not in code and '-nd' not in code else {'nc'}", 'REPLACE'),
    ('every licence is accepted', 'lib/faces.py',
     '    return False, short\n\n\ndef attribution_of',
     '    return True, short\n\n\ndef attribution_of', 'REPLACE'),
    # --- identity gate ----------------------------------------------------
    ('the wrong person can be shipped', 'lib/faces.py',
     '    if not any(p in ft.split() for p in parts):\n        return False',
     '    if False:\n        return False', 'REPLACE'),
    ('football context is no longer required', 'lib/faces.py',
     '    return bool(_FOOTBALL.search(ctx))', '    return True', 'REPLACE'),
    ('crests/kits/statues pass as portraits', 'lib/faces.py',
     "    if not ft or _BAD_FILE.search(str(file_title or '')):",
     '    if not ft:', 'REPLACE'),
    # --- candidate selection ---------------------------------------------
    ('selection ignores the licence', 'lib/faces.py',
     '            ok, _ = licence_ok(ext)\n            if not ok:\n                continue',
     '            ok, _ = licence_ok(ext)\n            if False:\n                continue', 'REPLACE'),
    ('selection ignores identity', 'lib/faces.py',
     '            if not identity_ok(wanted, title, desc, cats):\n                continue',
     '            if False:\n                continue', 'REPLACE'),
    ('selection takes the smallest image', 'lib/faces.py',
     '            if best is None or cand[0] > best[0]:',
     '            if best is None or cand[0] < best[0]:', 'REPLACE'),
    # --- cache / network behaviour ---------------------------------------
    ('a non-free cached photo is served', 'lib/faces.py',
     "            if att.get('free') and time.time() - os.path.getmtime(img) < POS_TTL:",
     '            if time.time() - os.path.getmtime(img) < POS_TTL:', 'REPLACE'),
    ('the negative cache is ignored', 'lib/faces.py',
     '    if os.path.isfile(none) and time.time() - os.path.getmtime(none) < NEG_TTL:',
     '    if False:', 'REPLACE'),
    ('network is used even when disabled', 'lib/faces.py',
     '    if not allow_network or not str(name or \'\').strip():',
     "    if not str(name or '').strip():", 'REPLACE'),
    ('a network error is cached as "no photo"', 'lib/faces.py',
     '    except Exception:\n        # Network failure is not a "no photo" answer: do not poison the cache.\n        return graphics.avatar_svg(name, seed=key), \'image/svg+xml\', \'avatar\', None',
     '    except Exception:\n        try:\n            os.makedirs(d, exist_ok=True)\n            open(none, "w").write("0")\n        except OSError:\n            pass\n        return graphics.avatar_svg(name, seed=key), \'image/svg+xml\', \'avatar\', None', 'REPLACE'),
    ('accepted photos are not credited', 'lib/faces.py',
     '        _append_credit(d, key, att)', '        pass', 'REPLACE'),
    # --- crest resolution / fallbacks -------------------------------------
    ('a missing crest returns nothing instead of a shield', 'lib/graphics.py',
     "    return shield_svg(name or ident, colors, kind), 'image/svg+xml', 'generated'",
     "    return b'', 'image/svg+xml', 'generated'", 'REPLACE'),
    ('generated art ignores the club colours', 'lib/graphics.py',
     '    c1, c2, c3 = colors_of(colors)', '    c1, c2, c3 = colors_of(None)', 'REPLACE'),
    ('avatars use the process-salted hash()', 'lib/graphics.py',
     "    return int.from_bytes(hashlib.sha256(str(s).encode('utf-8')).digest()[:8], 'big')",
     '    return abs(hash(str(s)))', 'REPLACE'),
    # --- safety -----------------------------------------------------------
    ('names are no longer XML-escaped', 'lib/graphics.py',
     "    return (str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')\n            .replace('\"', '&quot;').replace(\"'\", '&apos;'))",
     '    return str(s)', 'REPLACE'),
    ('any string is accepted as a colour', 'lib/graphics.py',
     '    if not _HEX.match(s):\n        return None',
     '    if False:\n        return None', 'REPLACE'),
    ('manifest paths may traverse out of the cache', 'lib/graphics.py',
     "    if not s or s.startswith('/') or '..' in s.split('/'):",
     '    if not s:', 'REPLACE'),
    # --- publishing / importer -------------------------------------------
    ('trademarked artwork stops being git-ignored', '.gitignore',
     'data/graphics/crests/', 'data/graphics/NOT-crests/', 'REPLACE'),
    ('the block list is ignored (wrong crests return)', 'tools/import_graphics.py',
     "    if fold(name) in BLOCK:\n        return None, 'blocked'",
     "    if False:\n        return None, 'blocked'", 'REPLACE'),
    ('reserve sides inherit the parent crest', 'tools/import_graphics.py',
     '        if RESERVE_RE.search(name):', '        if False:', 'REPLACE'),
    ('aliases lose to the lossy exact key', 'tools/import_graphics.py',
     "    al = ALIAS.get(fold(name))\n    if al:\n        for kk in (key(al, stop=False), key(al)):",
     "    al = ALIAS.get(fold(name))\n    if False:\n        for kk in (key(al, stop=False), key(al)):", 'REPLACE'),
    ('ambiguous stripped keys are registered again', 'tools/import_graphics.py',
     '            if len({m.name for m in ms}) == 1:', '            if True:', 'REPLACE'),
    ('two different clubs may share one crest', 'tools/import_graphics.py',
     "        if len(names_by_member[mem]) > 1 and how in ('token', 'global'):",
     '        if False:', 'REPLACE'),
    ('the importer loses clubs that share a crest', 'tools/import_graphics.py',
     "            entries.append(('clubs', str(tid), row['name'], how, m.name))",
     "            entries[:] = [e for e in entries if e[4] != m.name]\n            entries.append(('clubs', str(tid), row['name'], how, m.name))", 'REPLACE'),
]


def run_verifier():
    p = subprocess.run([sys.executable, '-u', 'tools/verify_graphics.py'],
                       capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


print('baseline')
rc, out = run_verifier()
if rc != 0:
    print('BASELINE FAILS - aborting\n' + out[-2000:])
    sys.exit(1)
print('  baseline passes: %s' % [l for l in out.splitlines() if 'ALL PASS' in l])

backups = {}
caught, missed, skipped = [], [], []
try:
    for name, rel, old, new, kind in MUTANTS:
        path = os.path.join(ROOT, rel)
        src = io.open(path, encoding='utf-8').read()
        if old not in src:
            skipped.append(name)
            print('  SKIP (anchor missing): %s' % name)
            continue
        if path not in backups:
            backups[path] = src
        io.open(path, 'w', encoding='utf-8').write(src.replace(old, new, 1))
        rc, out = run_verifier()
        io.open(path, 'w', encoding='utf-8').write(backups[path])
        del backups[path]
        if rc != 0:
            fails = [l.strip() for l in out.splitlines() if l.strip().startswith('FAIL')]
            caught.append(name)
            print('  CAUGHT  %-50s %s' % (name, fails[0][:88] if fails else ''))
        else:
            missed.append(name)
            print('  MISSED  %-50s (verifier still passed!)' % name)
finally:
    for path, src in backups.items():
        io.open(path, 'w', encoding='utf-8').write(src)
    for d in ('lib/__pycache__', 'lib/engine/__pycache__', 'tools/__pycache__'):
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)

print()
print('%d/%d mutants caught (%d skipped)' % (len(caught), len(MUTANTS), len(skipped)))
rc, out = run_verifier()
print('post-restore baseline: %s' % ('PASS' if rc == 0 else 'FAIL'))
if missed:
    print('WEAK CHECKS (mutant survived):')
    for m in missed:
        print('  - %s' % m)
sys.exit(1 if missed or skipped or rc else 0)
