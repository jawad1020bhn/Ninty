"""Mutation test for tools/verify_backend.py.

    python3 tools/mutate_backend.py

A check that passes before AND after a mutation is not a check. Each mutant
re-introduces one coupling or defect that r23 removed; the verifier must FAIL.
Files are always restored, even on error.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

MUTANTS = [
    ('a deleted PES module reappears', 'lib/mlsave.py', None,
     '"""reintroduced"""\n', 'CREATE'),
    ('a kept module imports PES machinery', 'lib/regrules.py',
     'FREE_AGE = 21', 'import mlsave\nFREE_AGE = 21', 'REPLACE'),
    ('engine drops the extracted pitch helpers', 'lib/engine/lineup.py',
     'import pitch', 'import json as pitch', 'REPLACE'),
    ('aitransfers reads save bytes again', 'lib/aitransfers.py',
     'def ai_world(clubs, my_idx=0):', 'def ai_world(clubs, my_idx=0):\n    _ = struct.unpack_from("<I", save.d, 0)', 'REPLACE'),
    ('ai_world stops excluding the managed club', 'lib/aitransfers.py',
     '        if n == my_idx:\n            continue', '        if False:\n            continue', 'REPLACE'),
    ('ai_world returns the caller dict (no copy)', 'lib/aitransfers.py',
     '        pl = [dict(p) for p in (c.get(\'players\') or [])]', '        pl = c.get(\'players\') or []', 'REPLACE'),
    ('ai_world admits any squad size', 'lib/aitransfers.py',
     'if len(nm) < 3 or not nm.isprintable() or not 16 <= len(pl) <= 40:',
     'if len(nm) < 3 or not nm.isprintable():', 'REPLACE'),
    ('ai_world admits unrated squads', 'lib/aitransfers.py',
     '        if len(top) < 11:\n            continue', '        if False:\n            continue', 'REPLACE'),
    ('strength uses the whole squad, not the top 14', 'lib/aitransfers.py',
     "        top = sorted((p.get('ovr') or 0 for p in pl), reverse=True)[:14]",
     "        top = sorted((p.get('ovr') or 0 for p in pl), reverse=True)", 'REPLACE'),
    ('plan ignores the budget callback', 'lib/aitransfers.py',
     "            if budget_of:   # the club's real starting transfer budget, in EUR",
     '            if False:   # mutant', 'REPLACE'),
    ('regrules loses an EU member', 'lib/regrules.py',
     'EU = {4, 7, 9, 10,', 'EU = {7, 9, 10,', 'REPLACE'),
    ('regrules gets a wrong domestic code', 'lib/regrules.py',
     "DOMESTIC = {31: 'IT',", "DOMESTIC = {31: 'ES',", 'REPLACE'),
    ('the free age is raised', 'lib/regrules.py',
     'FREE_AGE = 21', 'FREE_AGE = 30', 'REPLACE'),
    ('the non-EU cap stops being enforced', 'lib/regrules.py',
     "    if r.get('extra') is not None:", "    if False:", 'REPLACE'),
    ('venues expose a foreign club id again', 'lib/venues.py',
     "            result.update(venue_sources=row.get('sources', {}),",
     "            result['team_id'] = int(tid)\n            result.update(venue_sources=row.get('sources', {}),", 'REPLACE'),
    ('venues stop rejecting ambiguous names', 'lib/venues.py',
     '            if len(candidates) != 1:', '            if len(candidates) < 1:', 'REPLACE'),
    ('venues let a reserve side inherit a ground', 'lib/venues.py',
     "    elif re.search(r'\\s(?:B|II|III|U-?\\d\\d|Reserves?|Youth|Juniors?|Castilla|Atletic)$', name or '', re.I):",
     '    elif False:', 'REPLACE'),
    ('venue capacity is no longer formatted', 'lib/venues.py',
     "                result['cap'] = format(cap, ',')", "                result['cap'] = str(cap)", 'REPLACE'),
    ('the attribute API reverts to PES keys', 'server.py',
     "ab25=_m.get('ab', []), ab25Source=_m.get('abSource', []),",
     "pes=_m.get('ab', []), pesSource=_m.get('abSource', []),", 'REPLACE'),
    ('a PES career route comes back', 'server.py',
     "            if u.path == '/api/version':", "            if u.path == '/api/slots':\n                return self.send(200, dict(ok=True))\n            if u.path == '/api/version':", 'REPLACE'),
    ('the TightPossession blend is replaced by a copy', 'lib/engine/roster.py',
     "            out.append(_clamp((_clamp(ea.get('ballcontrol', 0)) * 2 +\n                               _clamp(ea.get('dribbling', 0)) +\n                               _clamp(ea.get('agility', 0))) / 4.0))",
     "            out.append(_clamp(ea.get('ballcontrol', 0)))", 'REPLACE'),
    ('the 25-attribute order is truncated', 'lib/engine/roster.py',
     "'GKCatching', 'GKClearing', 'GKReflexes', 'GKReach']",
     "'GKCatching', 'GKClearing', 'GKReflexes']", 'REPLACE'),
]


def run_verifier():
    p = subprocess.run([sys.executable, '-u', 'tools/verify_backend.py'],
                       capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


print('baseline')
rc, out = run_verifier()
if rc != 0:
    print('BASELINE FAILS - aborting\n' + out[-2000:])
    sys.exit(1)
print('  baseline passes: %s' % [l for l in out.splitlines() if 'ALL PASS' in l])

backups = {}
caught, missed = [], []
try:
    for name, rel, old, new, kind in MUTANTS:
        path = os.path.join(ROOT, rel)
        if kind == 'CREATE':
            if os.path.exists(path):
                print('  SKIP (exists): %s' % name)
                continue
            io.open(path, 'w', encoding='utf-8').write(new)
            backups[path] = None
        else:
            src = io.open(path, encoding='utf-8').read()
            if old not in src:
                print('  SKIP (anchor missing): %s' % name)
                continue
            if path not in backups:
                backups[path] = src
            io.open(path, 'w', encoding='utf-8').write(src.replace(old, new, 1))
        rc, out = run_verifier()
        # restore immediately so mutants never stack
        if backups[path] is None:
            os.remove(path)
        else:
            io.open(path, 'w', encoding='utf-8').write(backups[path])
        del backups[path]
        if rc != 0:
            fails = [l.strip() for l in out.splitlines() if l.strip().startswith('FAIL')]
            caught.append(name)
            print('  CAUGHT  %-52s %s' % (name, fails[0][:90] if fails else ''))
        else:
            missed.append(name)
            print('  MISSED  %-52s (verifier still passed!)' % name)
finally:
    for path, src in backups.items():
        if src is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            io.open(path, 'w', encoding='utf-8').write(src)
    # clear stale bytecode so a restored file is never shadowed
    for d in ('lib/__pycache__', 'lib/engine/__pycache__', 'tools/__pycache__'):
        shutil.rmtree(os.path.join(ROOT, d), ignore_errors=True)

print()
print('%d/%d mutants caught' % (len(caught), len(MUTANTS)))
rc, out = run_verifier()
print('post-restore baseline: %s' % ('PASS' if rc == 0 else 'FAIL'))
if missed:
    print('WEAK CHECKS (mutant survived):')
    for m in missed:
        print('  - %s' % m)
sys.exit(1 if missed or rc else 0)
