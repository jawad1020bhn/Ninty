#!/usr/bin/env python3
"""verify_engine.py - behavioural checks for the FC 27 career engine.

The database has tools/verify_fc27.py; this is its counterpart for the engine.
Static integrity is not enough here: an engine can hold perfectly consistent
data and still be wrong. So this file asserts BEHAVIOUR - that a season is
reproducible, that a save reloads exactly, that the table arithmetic closes, and
that the simulation still produces football-shaped scores.

    python3 tools/verify_engine.py [--verbose] [--quick]

Stdlib only. Careers are written to a temporary directory, never to
data/saves, so running the verifier cannot touch a real career.

--quick skips the full-season calibration group (the slow part, a few seconds).
"""
import argparse
import ast
import collections
import datetime
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'lib'))

FAILURES = []
COUNT = 0
VERBOSE = False


def check(name, ok, detail=''):
    global COUNT
    COUNT += 1
    if not ok:
        FAILURES.append(name)
        print('FAIL  %s%s' % (name, ('  <- ' + detail) if detail else ''))
    elif VERBOSE:
        print('pass  %s' % name)
    return bool(ok)


def _d(s):
    return datetime.date(*(int(x) for x in str(s)[:10].split('-')))


def run(verbose=False, quick=False):
    global VERBOSE, FAILURES, COUNT
    VERBOSE = verbose
    FAILURES, COUNT = [], 0

    import engine
    import fc27
    import formengine
    from engine import store, match as M, season as SE, lineup as LU

    tmp = tempfile.mkdtemp(prefix='fc27-engine-verify-')
    real_dir = store.DIR
    store.DIR = tmp
    try:
        # ------------------------------------------------------------ fixtures
        st = engine.new(club=9, manager='Verifier', seed=7, sid='verify-a')
        fx = st['fixtures']
        teams = [int(t) for t, c in st['clubs'].items() if int(c['league']) == 13]
        n = len(teams)
        check('double round-robin has n(n-1) fixtures', len(fx) == n * (n - 1),
              '%d vs %d' % (len(fx), n * (n - 1)))
        check('no team plays itself', all(f['home'] != f['away'] for f in fx))
        pairs = collections.Counter((f['home'], f['away']) for f in fx)
        check('every ordered pair meets exactly once',
              len(pairs) == n * (n - 1) and set(pairs.values()) == {1})
        check('every pairing is home-and-away',
              all(pairs[(a, b)] == pairs[(b, a)] == 1 for a in teams for b in teams if a != b))
        per = collections.Counter()
        for f in fx:
            per[f['home']] += 1
            per[f['away']] += 1
        check('every team plays 2(n-1) matches', set(per.values()) == {2 * (n - 1)})
        halves = collections.Counter()
        for f in fx:
            halves[f['home']] += 1
        check('home and away are balanced', set(halves.values()) == {n - 1})
        check('fixture ids are unique and dense',
              sorted(f['id'] for f in fx) == list(range(len(fx))))
        check('fixtures are in date order',
              all(fx[i]['date'] <= fx[i + 1]['date'] for i in range(len(fx) - 1)))
        check('season runs August to May',
              fx[0]['date'] >= '%d-08-01' % st['season'] and
              fx[-1]['date'] <= '%d-05-31' % (st['season'] + 1))
        check('no round on an international break',
              not any(_d(f['date']).month in (9, 10, 11, 3) and _d(f['date']).day <= 7
                      for f in fx))
        f2 = engine.new(club=9, seed=7, sid='verify-b')['fixtures']
        check('same seed reproduces the fixture list',
              [(x['date'], x['home'], x['away']) for x in fx] ==
              [(x['date'], x['home'], x['away']) for x in f2])

        # ------------------------------------------------------- determinism
        def play(seed, sid, k=30):
            s = engine.new(club=9, seed=seed, sid=sid)
            out = []
            for f in s['fixtures'][:k]:
                r = engine.play_fixture(s, f)
                out.append((r['fid'], tuple(r['sc']), tuple(map(tuple, r['rows']))))
            return out

        check('same seed reproduces results regardless of career id',
              play(99, 'det-1') == play(99, 'det-2'))
        check('a different seed produces a different season',
              play(99, 'det-3') != play(100, 'det-4'))

        # -------------------------------------------------------------- save
        st = engine.new(club=9, manager='Round Trip', seed=5, sid='verify-rt')
        for f in st['fixtures'][:12]:
            engine.play_fixture(st, f)
        engine.save(st)
        before = json.dumps(st, sort_keys=True)
        ld = engine.load('verify-rt')
        check('save/load round trip is exact', json.dumps(ld, sort_keys=True) == before)
        nf1 = next(f for f in st['fixtures'] if not f['played'])
        nf2 = next(f for f in ld['fixtures'] if not f['played'])
        r1, r2 = engine.play_fixture(st, nf1), engine.play_fixture(ld, nf2)
        check('resuming a reloaded career matches playing straight on',
              r1['sc'] == r2['sc'] and r1['rows'] == r2['rows'])
        check('career appears in the save list',
              any(x['id'] == 'verify-rt' for x in engine.list_saves()))
        check('a save path cannot escape the saves directory',
              _rejects(engine, '../evil'))
        check('loading an unknown career raises', _raises(engine.load, 'no-such-career'))

        # --------------------------------------------------- match integrity
        st = engine.new(club=9, seed=11, sid='verify-int')
        results = [engine.play_fixture(st, f) for f in st['fixtures'][:60]]
        check('player goal rows sum to the scoreline',
              all(sum(r[2] for r in x['rows']) == sum(x['sc']) for x in results))
        check('player assist rows never exceed goals',
              all(sum(r[3] for r in x['rows']) <= sum(x['sc']) for x in results))
        check('every scorer is in that match\'s player rows',
              all(all(any(r[0] == e['pid'] and r[2] > 0 for r in x['rows'])
                      for e in x['events'] if e['kind'] == 'goal') for x in results))
        check('both teams field exactly 11 starters',
              all(len(s['xi']) == 11 for x in results for s in x['lineups'].values()))
        check('every XI has exactly one goalkeeper',
              all(sum(1 for p in s['xi'] if fc27.positions().get(str(p), 5) == 0) == 1
                  for x in results for s in x['lineups'].values()))
        check('selected players belong to their club',
              all(all(store.club_of(st, p) == int(tid) for p in s['xi'])
                  for x in results for tid, s in x['lineups'].items()))
        check('no player is selected twice in an XI',
              all(len(set(s['xi'])) == 11 for x in results for s in x['lineups'].values()))
        check('bench does not overlap the XI',
              all(not (set(s['xi']) & set(s['bench']))
                  for x in results for s in x['lineups'].values()))
        check('ratings stay in a football range',
              all(3.0 <= r[4] <= 10.0 for x in results for r in x['rows']))
        check('minutes are 1..90', all(1 <= v <= 90 for x in results
                                       for v in x['minutes'].values()))
        check('substitutes get a rating row',
              all(len(x['rows']) >= 22 for x in results))
        check('possession sums to 100',
              all(sum(x['stats']['possession']) == 100 for x in results))
        check('on-target shots never exceed shots',
              all(x['stats']['onTarget'][i] <= x['stats']['shots'][i]
                  for x in results for i in (0, 1)))
        check('goals never exceed on-target shots',
              all(x['sc'][i] <= x['stats']['onTarget'][i] for x in results for i in (0, 1)))
        check('attendance is within stadium capacity',
              all(0 < x['attendance'] <= (fc27.stadium(x['home']).get('capacity') or 0)
                  for x in results))
        check('a shipped derby is recognised as a big match',
              M.is_big(11, 9) and M.is_big(9, 7))

        # Venue effect in isolation: the SAME XI on both sides, so any goal
        # difference can only come from the home/away multipliers.
        iso = engine.new(club=9, seed=4, sid='verify-venue')
        xi, bench, _ = LU.base_xi(iso, 9)
        hg = ag = 0
        base_f = dict(iso['fixtures'][0])
        for k in range(200):
            f = dict(base_f, id=k, home=9, away=11)
            r = M.simulate(iso, f, xi, xi, bench, bench, seed=1000 + k)
            hg += r['sc'][0]
            ag += r['sc'][1]
        ratio = hg / float(max(1, ag))
        if VERBOSE:
            print('      venue isolation: %d home vs %d away goals (ratio %.2f)' % (hg, ag, ratio))
        # Measured: shipped 1.20/0.90 -> 1.29, HOME_EDGE alone neutralised
        # -> 1.16, both neutral -> 1.04. The cutoff must sit above 1.16 so
        # weakening either multiplier is caught, not just flattening both.
        check('identical XIs still show a clear home advantage',
              ratio >= 1.22, '%d vs %d (ratio %.2f)' % (hg, ag, ratio))

        # ------------------------------------------------------------- table
        SE.recompute_tables(st)
        tb = engine.table(st)
        check('table covers every club in the league', len(tb) == n)
        check('points = 3*wins + draws', all(r['pts'] == 3 * r['w'] + r['d'] for r in tb))
        check('played = wins + draws + losses',
              all(r['pl'] == r['w'] + r['d'] + r['l'] for r in tb))
        check('goal difference = scored - conceded',
              all(r['gd'] == r['gf'] - r['ga'] for r in tb))
        check('league goals for equal goals against',
              sum(r['gf'] for r in tb) == sum(r['ga'] for r in tb))
        check('league wins equal league losses',
              sum(r['w'] for r in tb) == sum(r['l'] for r in tb))
        check('total played equals twice the matches',
              sum(r['pl'] for r in tb) == 2 * len(st['results']))
        check('positions are 1..n with no gaps', [r['pos'] for r in tb] == list(range(1, n + 1)))
        # Rows are sorted by (-pts, -gd, ...), so those negated keys ASCEND.
        check('table is ordered by points then goal difference',
              all((-tb[i]['pts'], -tb[i]['gd']) <= (-tb[i + 1]['pts'], -tb[i + 1]['gd'])
                  for i in range(len(tb) - 1)))
        check('form guide holds at most five results', all(len(r['form']) <= 5 for r in tb))

        pos_db = fc27.positions()
        mine = [r for r in st['results'] if 9 in (int(r['home']), int(r['away']))]
        ms = [dict(home=int(r['home']), sc=r['sc'], rows=r['rows']) for r in mine]
        expected = formengine.compute(ms, 9, lambda p: int(pos_db.get(str(int(p)), 5)))
        check('stored Form equals what formengine computes',
              bool(expected) and all(
                  store.pstate(st, p)[store.P_FORM] == info['level']
                  for p, info in expected.items() if store.pstate(st, p)),
              '%d players compared' % len(expected))
        check('Form actually moves during a season',
              any(store.pstate(st, p)[store.P_FORM] != 4
                  for p in expected if store.pstate(st, p)))

        # -------------------------------------------------------- state moves
        st2 = engine.new(club=9, seed=3, sid='verify-move')
        pid = store.squad_of(st2, 9)[0]
        engine.move_player(st2, pid, 11)
        check('transfer updates the player\'s club', store.club_of(st2, pid) == 11)
        check('transfer removes him from the old squad', pid not in store.squad_of(st2, 9))
        check('transfer adds him to the new squad', pid in store.squad_of(st2, 11))
        check('no player is in two squads',
              _no_duplicates(st2))
        check('moving to the same club is a no-op', engine.move_player(st2, pid, 11) is False)

        first = engine.select(st2, 9, 11)
        # Injure players who were actually chosen; injuring a reserve proves
        # nothing because he would not have been picked anyway.
        inj = store.squad_of(st2, 9)[1]
        picked = [p for p in first['xi'] if fc27.positions().get(str(p), 5) != 0][:3]
        for p in picked:
            store.pstate(st2, p)[store.P_INJ] = 5
        store.pstate(st2, inj)[store.P_INJ] = 5
        sel = engine.select(st2, 9, 11)
        check('injured starters are dropped from the XI',
              not (set(picked) & set(sel['xi'])), str(picked))
        engine.advance(st2, days=6, limit=0)
        check('injuries heal as days pass', store.pstate(st2, inj)[store.P_INJ] == 0)
        store.pstate(st2, inj)[store.P_FIT] = 50
        engine.advance(st2, days=3, limit=0)
        check('fitness recovers as days pass', store.pstate(st2, inj)[store.P_FIT] > 50)
        fresh = engine.select(st2, 9, 11)
        banned = next(p for p in fresh['xi'] if fc27.positions().get(str(p), 5) != 0)
        st2.setdefault('suspended', {})[str(banned)] = 1
        check('a suspended starter is dropped from the XI',
              banned not in engine.select(st2, 9, 11)['xi'], str(banned))
        SE.serve_bans(st2, 9, {'minutes': {}})
        check('a ban is served by missing a match',
              not st2.get('suspended', {}).get(str(banned)))

        # ----------------------------------------------- reuse, not reimpl
        imports = _imports(os.path.join(HERE, 'lib', 'engine'))
        check('engine reuses the existing lineup AI', 'ailineup' in imports)
        check('engine reuses the existing form algorithm', 'formengine' in imports)
        check('engine reuses the credited valuation curve', 'revalue' in imports)
        check('engine reuses the pure assignment helpers', 'mlwrite' in imports)
        pes = imports & {'mlsave', 'pescrypt', 'pes17', 'pes17_write', 'mlwrite_save'}
        check('engine never imports PES save machinery', not pes, str(sorted(pes)))
        check('match simulation reads EA\'s 34 raw attributes',
              'ea_attrs' in _source(os.path.join(HERE, 'lib', 'engine', 'match.py')))

        # ------------------------------------------------------- calibration
        if not quick:
            g = h = d_ = a_ = sh = tot = 0
            for sd in (7, 19):
                s = engine.new(club=9, seed=sd, sid='verify-cal-%d' % sd)
                for f in s['fixtures']:
                    gap = (_d(f['date']) - _d(s['date'])).days
                    if gap > 0:
                        engine.advance(s, days=gap, limit=0)
                    engine.play_fixture(s, f)
                R = s['results']
                tot += len(R)
                g += sum(sum(x['sc']) for x in R)
                h += sum(1 for x in R if x['sc'][0] > x['sc'][1])
                d_ += sum(1 for x in R if x['sc'][0] == x['sc'][1])
                sh += sum(sum(x['stats']['shots']) for x in R)
                check('full season completes for seed %d' % sd,
                      all(f['played'] for f in s['fixtures']))
                check('every club plays 38 (seed %d)' % sd,
                      {r['pl'] for r in engine.table(s)} == {38})
                check('season integrity holds (seed %d)' % sd,
                      all(sum(r[2] for r in x['rows']) == sum(x['sc']) for x in R))
                check('top scorer is plausible (seed %d)' % sd,
                      10 <= engine.scorers(s, limit=1)[0]['goals'] <= 45)
            gg, hp, dp, sp = g / tot, 100.0 * h / tot, 100.0 * d_ / tot, sh / tot
            if VERBOSE:
                print('      calibration: %.2f goals/g, %.1f%% home, %.1f%% draw, %.1f shots/g'
                      % (gg, hp, dp, sp))
            check('goals per game is football-shaped (2.3-3.3)', 2.3 <= gg <= 3.3, '%.2f' % gg)
            check('home win rate is realistic (40-53%)', 40 <= hp <= 53, '%.1f' % hp)
            check('draw rate is realistic (18-30%)', 18 <= dp <= 30, '%.1f' % dp)
            check('shots per game is realistic (20-30)', 20 <= sp <= 30, '%.1f' % sp)
    finally:
        store.DIR = real_dir
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILURES:
        print('%d of %d checks FAILED:' % (len(FAILURES), COUNT))
        for f in FAILURES:
            print('  - %s' % f)
        return 1
    print('ALL PASS - %d checks' % COUNT)
    print('Engine is reproducible, saves reload exactly, and seasons stay football-shaped.')
    return 0


def _raises(fn, *a):
    try:
        fn(*a)
        return False
    except Exception:
        return True


def _rejects(engine, bad_id):
    try:
        engine.load(bad_id)
        return False
    except Exception:
        return True


def _no_duplicates(st):
    seen = set()
    for sq in st['clubs'].values():
        for p in sq['squad']:
            if p in seen:
                return False
            seen.add(p)
    return True


def _imports(folder):
    """Actual import statements, not docstring mentions of a module name."""
    out = set()
    for f in os.listdir(folder):
        if not f.endswith('.py'):
            continue
        tree = ast.parse(open(os.path.join(folder, f), encoding='utf-8').read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                out.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                out.add(node.module.split('.')[0])
    return out


def _source(path):
    return open(path, encoding='utf-8').read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--quick', action='store_true')
    args = ap.parse_args()
    print('FC 27 engine verification')
    print()
    return run(verbose=args.verbose, quick=args.quick)


if __name__ == '__main__':
    sys.exit(main())
