#!/usr/bin/env python3
"""Mutation test for the r25 real-name invariants in tools/verify_fc27.py.

    python3 tools/mutate_fc27.py

A check that passes before AND after a mutation is not a check. Each mutant
re-introduces one defect the rename could plausibly ship with, and declares
WHICH check must catch it. Asserting only "the verifier exited non-zero" is
too weak: an unrelated check could fail while the invariant under test is
dead. So every mutant names the substring it must trip.

Data mutants run against a THROWAWAY COPY of data/fc27 passed via --dir, so
the committed database is never written to. Importer mutants must edit the
real tools/import_fc27.mjs (the verifier locates it relative to its own
path); those are backed up and restored in a finally block.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
SRC_DB = os.path.join(ROOT, 'data', 'fc27')
IMPORTER = os.path.join(ROOT, 'tools', 'import_fc27.mjs')


def run(db_dir):
    p = subprocess.run([sys.executable, '-u', 'tools/verify_fc27.py', '--dir', db_dir],
                       capture_output=True, text=True, timeout=900)
    fails = [l[6:].strip() for l in (p.stdout + p.stderr).splitlines()
             if l.startswith('FAIL  ')]
    return p.returncode, fails, p.stdout + p.stderr


# --- data mutants: (name, file, transform, check substring that must fire) ---
def revert_name(tid, old):
    def f(o):
        o[tid]['name'] = old
    return f


def wrong_name(tid, bogus):
    def f(o):
        o[tid]['name'] = bogus
    return f


def swap_squads(a, b):
    def f(o):
        o[a], o[b] = o[b], o[a]
    return f


DATA_MUTANTS = [
    ('the rename is reverted to EA\'s placeholder', 'clubs',
     revert_name('131681', 'Milano FC'), '131681 is AC Milan'),
    # Not a placeholder string, so ONLY the real-name check can catch this.
    ('a renamed club gets an invented name', 'clubs',
     wrong_name('131682', 'Nerazzurri United'), '131682 is Inter'),
    ('the id drifts to a different club (squad no longer matches)', 'squads',
     swap_squads('131681', '115845'), 'proven by its squad'),
    ('teamids keeps the old name', 'teamids',
     lambda o: o.__setitem__('115845', 'Bergamo Calcio'), 'teamids agrees for Atalanta'),
    ('a loan keeps the old denormalised name', 'loans',
     lambda o: next(r for r in o if r['from'] == 131682).__setitem__('fromName', 'Lombardia FC'),
     'every loan fromName matches its club'),
    ('two clubs are given one real name', 'clubs',
     wrong_name('45', 'Inter'), 'Inter belongs to exactly one club'),
    ('an over-eager rename hits Lazio', 'clubs',
     wrong_name('115841', 'Latium'), 'Lazio is not renamed to Latium'),
    ('an over-eager rename hits a real 2026 rebrand', 'clubs',
     lambda o: next(r for r in o.values()
                    if r['name'] == 'Logroño United').__setitem__('name', 'DUX Logroño'),
     'Logroño United kept'),
    ('a generated filler squad is given a real identity', 'clubs',
     wrong_name('132681', 'East Bengal'), 'United Tigers SC kept'),
]

# --- importer mutants: (name, old, new, check substring that must fire) ------
IMPORTER_MUTANTS = [
    ('the importer loses the rename table entirely',
     'const REAL_TEAM_NAME = new Map([', 'const REMOVED_TEAM_NAME = new Map([',
     'importer declares REAL_TEAM_NAME'),
    ('the importer table disagrees with the committed data',
     "[131681, 'AC Milan'],", "[131681, 'Milan'],",
     'importer table reproduces the committed names'),
    ('the importer stops applying the table',
     'if (real && r.teamname !== real) { r.teamname = real; realNamed++; }',
     'if (real && r.teamname !== real) { realNamed++; }',
     'importer applies the table to the raw team records'),
]


def main():
    print('baseline')
    rc, fails, out = run(SRC_DB)
    if rc != 0:
        print('BASELINE FAILS - aborting\n' + out[-2500:])
        return 1
    print('  ' + ([l for l in out.splitlines() if 'ALL PASS' in l] or [''])[0].strip())

    caught, missed, skipped = [], [], []
    backups = {}
    tmp = tempfile.mkdtemp(prefix='mutate_fc27_')
    db = os.path.join(tmp, 'fc27')
    try:
        shutil.copytree(SRC_DB, db)
        for name, tbl, fn, expect in DATA_MUTANTS:
            path = os.path.join(db, tbl + '.json')
            raw = io.open(path, encoding='utf-8').read()
            obj = json.loads(raw)
            try:
                fn(obj)
            except StopIteration:
                skipped.append(name + ' (fixture row absent)')
                print('  SKIP    %s' % name)
                continue
            if obj == json.loads(raw):
                skipped.append(name + ' (no-op)')
                print('  SKIP    %s (mutation changed nothing)' % name)
                continue
            io.open(path, 'w', encoding='utf-8', newline='').write(json.dumps(obj))
            rc, fails, out = run(db)
            io.open(path, 'w', encoding='utf-8', newline='').write(raw)
            hit = [f for f in fails if expect in f]
            if rc != 0 and hit:
                caught.append(name)
                print('  CAUGHT  %-58s %s' % (name, hit[0][:70]))
            else:
                missed.append((name, expect, fails))
                print('  SURVIVED %-57s expected %r, got %s'
                      % (name, expect, fails[:3]))

        # The ordering mutant moves the rename AFTER the TEAM map is built.
        src = io.open(IMPORTER, encoding='utf-8').read()
        start = src.find('const REAL_TEAM_NAME = new Map([')
        end = src.find('const NAME = new Map(', start)
        block = src[start:end]
        anchor = 'const TLEAGUE = new Map(T.leagueteamlinks.map(r => [r.teamid, r.leagueid]));'
        IMPORTER_MUTANTS.append(
            ('the rename runs after the TEAM map is built', None, None,
             'importer applies it BEFORE the TEAM map is built'))
        for name, old, new, expect in IMPORTER_MUTANTS:
            cur = io.open(IMPORTER, encoding='utf-8').read()
            if IMPORTER not in backups:
                backups[IMPORTER] = cur
            if old is None:                     # the ordering mutant
                if not (start >= 0 and end > start and anchor in cur):
                    skipped.append(name + ' (anchor missing)')
                    print('  SKIP    %s' % name)
                    continue
                moved = cur[:start] + cur[end:]
                moved = moved.replace(anchor, anchor + '\n' + block, 1)
            else:
                if old not in cur:
                    skipped.append(name + ' (anchor missing)')
                    print('  SKIP    %s' % name)
                    continue
                moved = cur.replace(old, new, 1)
            io.open(IMPORTER, 'w', encoding='utf-8', newline='').write(moved)
            rc, fails, out = run(SRC_DB)
            io.open(IMPORTER, 'w', encoding='utf-8', newline='').write(cur)
            hit = [f for f in fails if expect in f]
            if rc != 0 and hit:
                caught.append(name)
                print('  CAUGHT  %-58s %s' % (name, hit[0][:70]))
            else:
                missed.append((name, expect, fails))
                print('  SURVIVED %-57s expected %r, got %s'
                      % (name, expect, fails[:3]))
    finally:
        for path, raw in backups.items():
            io.open(path, 'w', encoding='utf-8', newline='').write(raw)
        shutil.rmtree(tmp, ignore_errors=True)
        for p in (os.path.join(ROOT, 'tools', '__pycache__'),):
            shutil.rmtree(p, ignore_errors=True)

    total = len(DATA_MUTANTS) + len(IMPORTER_MUTANTS)
    print('\n%d/%d mutants caught (%d skipped)' % (len(caught), total, len(skipped)))
    rc, fails, out = run(SRC_DB)
    print('post-restore baseline: %s' % ('PASS' if rc == 0 else 'FAIL ' + str(fails)))
    if missed or skipped or rc != 0:
        for name, expect, got in missed:
            print('  SURVIVOR %s -> expected %r, failures %s' % (name, expect, got))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
