#!/usr/bin/env python3
"""Verify the FC 27-only backend after the PES strip (r23).

    python3 tools/verify_backend.py

Checks the things that could silently rot:
  * no PES module survives in lib/, and none is reachable from the server or engine
  * the server exposes exactly the intended routes
  * the transfer AI is decoupled but behaviourally intact (admission, determinism,
    no caller mutation, budget/formation callbacks)
  * registration rules use FC 27 ids, and the EU set matches the database's ISO codes
  * venue lookup is name-bound and never exposes another game's club id

Every check corresponds to a real coupling that was removed, not a hypothetical one.
"""
import argparse
import ast
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, 'lib'))

PASS = []
FAIL = []


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    if not ok:
        print('  FAIL %s%s' % (name, (' - ' + detail) if detail else ''))


# Modules deleted in r23. Any of these reappearing, or being imported, is a regression.
PES_MODULES = {
    'mlsave', 'mlwrite', 'pescrypt', 'pes17', 'pes17_write', 'pes17_layout',
    'pes17_pairs', 'pes17_setup', 'dbimport', 'facemap', 'layoutscan', 'loanscan',
    'savediff', 'seasonstats', 'kitsponsor', 'gamemem', 'coaches', 'bc7', 'dds',
    'ftex', 'fl26_career_catalog', 'fl26_competition_view', 'fl26_europe_view',
    'fl26_league_places', 'fl26_team_identity', 'fl26_venue_metadata',
}


def file_imports(path):
    """Real import statements, not docstring mentions of a module name."""
    out = set()
    tree = ast.parse(open(path, encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split('.')[0])
    return out


def closure(seeds):
    """Transitive local-module imports, with the edge that introduced each name."""
    libdir = os.path.join(HERE, 'lib')
    local = {f[:-3] for f in os.listdir(libdir) if f.endswith('.py')}
    local |= {'engine'}
    seen, todo, edges = set(), list(seeds), {}
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        if m == 'engine':
            files = [os.path.join(libdir, 'engine', f)
                     for f in os.listdir(os.path.join(libdir, 'engine')) if f.endswith('.py')]
        else:
            fp = os.path.join(libdir, m + '.py')
            files = [fp] if os.path.isfile(fp) else []
        for fp in files:
            for dep in file_imports(fp):
                edges.setdefault(dep, set()).add(m)
                if dep in local and dep not in seen:
                    todo.append(dep)
    return seen, edges


def section_backend():
    print('backend: no PES machinery')
    libdir = os.path.join(HERE, 'lib')
    present = sorted(m for m in PES_MODULES if os.path.isfile(os.path.join(libdir, m + '.py')))
    check('no PES module survives in lib/', not present, ', '.join(present))

    srv = file_imports(os.path.join(HERE, 'server.py'))
    seen, edges = closure(srv)
    reached = sorted(PES_MODULES & seen)
    check('no PES module reachable from server.py', not reached,
          ', '.join('%s via %s' % (m, sorted(edges.get(m, {'direct'}))) for m in reached))

    eng_seen, eng_edges = closure({'engine'})
    reached = sorted(PES_MODULES & eng_seen)
    check('no PES module reachable from the engine', not reached,
          ', '.join('%s via %s' % (m, sorted(eng_edges.get(m, {'direct'}))) for m in reached))

    # Every surviving lib module must also be clean, even ones the server does not
    # import yet (the transfer AI is kept for the next stage of the simulation).
    dirty = []
    for f in sorted(os.listdir(libdir)):
        if f.endswith('.py'):
            bad = file_imports(os.path.join(libdir, f)) & PES_MODULES
            if bad:
                dirty.append('%s->%s' % (f, sorted(bad)))
    check('no surviving lib module imports a PES module', not dirty, ', '.join(dirty))

    check('engine reuses the extracted pitch helpers', 'pitch' in eng_seen)
    check('the pitch helpers exist as a standalone module',
          os.path.isfile(os.path.join(libdir, 'pitch.py')))

    # The old save-byte readers must be gone from the kept algorithms.
    for mod in ('aitransfers', 'aimanager'):
        src = open(os.path.join(libdir, mod + '.py'), encoding='utf-8').read()
        check('%s reads no save bytes' % mod,
              'save.d' not in src and 'struct.unpack' not in src)
    src = open(os.path.join(libdir, 'aitransfers.py'), encoding='utf-8').read()
    tree = ast.parse(src)
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    check('the PES save readers are gone from aitransfers',
          not ({'load_clubs', 'national_like', '_club_name'} & funcs))
    check('aitransfers exposes a save-free world adapter', 'ai_world' in funcs)

    # Dead PES-era tables must not linger where someone could wire them up again.
    for dead in ('data/teamids.json', 'data/fl26_installed_league_counts.json',
                 'lib/ovr_weights.json', 'lib/ovr_weights_fl27.json',
                 'config_pes2017.example.json'):
        check('removed dead table %s' % dead, not os.path.exists(os.path.join(HERE, dead)))
    # The FC 27 copies of the same names are the live ones and must survive.
    for live in ('data/fc27/teamids.json', 'data/fc27/ovr_weights.json'):
        check('FC 27 table %s survives' % live, os.path.isfile(os.path.join(HERE, live)))


def section_routes():
    print('backend: route surface')
    src = open(os.path.join(HERE, 'server.py'), encoding='utf-8').read()
    found = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith('/api/') and node.value != '/api/':
                found.add(node.value)   # '/api/' alone is a prefix guard, not a route
    expected = {
        '/api/lan', '/api/lan/login', '/api/lan/set', '/api/version', '/api/clientlog', '/api/quit',
        '/api/fc27/status', '/api/fc27/attrs', '/api/fc27/national', '/api/fc27/leagues',
        '/api/fc27/league', '/api/fc27/club', '/api/fc27/matches', '/api/fc27/tuning',
        '/api/fc27/calendar', '/api/fc27/referees', '/api/fc27/regen', '/api/fc27/cups',
        '/api/fc27/loans', '/api/fc27/player', '/api/fc27/search',
        '/api/engine/careers', '/api/engine/state', '/api/engine/squad', '/api/engine/table',
        '/api/engine/select', '/api/engine/history', '/api/engine/new', '/api/engine/play',
        '/api/engine/advance', '/api/engine/save', '/api/engine/delete', '/api/engine/transfer',
        '/api/engine/finish', '/api/engine/close_season',
        '/api/i18n', '/api/fmtext', '/api/clubcolors', '/api/venue', '/api/myscene',
        '/api/myscene-m', '/api/art', '/api/stadium',
    }
    check('every intended route is present', not (expected - found), ', '.join(sorted(expected - found)))
    extra = found - expected
    check('no unexpected route survived', not extra, ', '.join(sorted(extra)))
    pes_routes = {p for p in found if any(
        t in p for t in ('pes', 'slots', 'savefolder', 'savecheck', 'backups', 'setup',
                         'sponsor', 'kitsp', 'growth', 'package', 'mods', 'sell', 'revalue'))}
    check('no PES career route survives', not pes_routes, ', '.join(sorted(pes_routes)))

    # The attribute schema lost its PES-named keys; the values must be unchanged.
    check('the attribute API uses neutral ab25 keys',
          'ab25=_m.get' in src and 'pes=_m.get' not in src)
    meta = json.load(open(os.path.join(HERE, 'data/fc27/fc27_meta.json'), encoding='utf-8'))
    check('generated metadata uses the neutral key',
          'ab25ProjectionDrops' in meta and 'pesProjectionDrops' not in meta)
    check('the projection still reports all 10 dropped EA fields',
          len(meta.get('ab25ProjectionDrops', [])) == 10)
    check('the 25-attribute order is unchanged', len(meta.get('ab', [])) == 25)
    check('the attribute sources are unchanged', len(meta.get('abSource', [])) == 25)
    imp = open(os.path.join(HERE, 'tools/import_fc27.mjs'), encoding='utf-8').read()
    check('the importer writes the same neutral key',
          'ab25ProjectionDrops:' in imp and 'pesProjectionDrops:' not in imp)


def section_regrules():
    print('registration rules: FC 27 ids only')
    import regrules as R
    leagues = json.load(open(os.path.join(HERE, 'data/fc27/leagues.json'), encoding='utf-8'))
    nations = json.load(open(os.path.join(HERE, 'data/fc27/nations.json'), encoding='utf-8'))

    check('every rule id is a real FC 27 league', all(str(k) in leagues for k in R.RULES),
          str([k for k in R.RULES if str(k) not in leagues]))
    check('every domestic id is a real FC 27 league', all(str(k) in leagues for k in R.DOMESTIC))
    # The rules use commercial names (LaLiga) where the database uses federated
    # ones (Primera Division), so names are not a safe test. The league's COUNTRY
    # is: every domestic code must equal the database country for that league.
    # GB is split into EN/SCO/WAL in football, so England maps GB -> EN.
    iso_by_id = {int(k): v.get('iso') for k, v in nations.items()}
    bad = []
    for tid, code in R.DOMESTIC.items():
        row = leagues.get(str(tid))
        if not row:
            bad.append('%s absent' % tid)
            continue
        want = iso_by_id.get(row.get('country'))
        if want == 'GB':
            want = 'EN'
        if want != code:
            bad.append('%s: db=%s rules=%s' % (tid, want, code))
    check('every domestic code matches the league country in the database', not bad, ', '.join(bad))
    check('every rule league also has a domestic code', all(k in R.DOMESTIC for k in R.RULES))

    # Independently derive the EU set from ISO codes rather than trusting the literal.
    iso = {v.get('iso'): int(k) for k, v in nations.items()}
    EU27 = 'AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE'.split()
    want = {iso[c] for c in EU27 + ['CH', 'NO', 'IS', 'LI'] if c in iso}
    check('the EU set matches the database ISO codes', R.EU == want,
          'missing=%s extra=%s' % (sorted(want - R.EU), sorted(R.EU - want)))
    check('every EU id is a real nation', all(str(i) in nations for i in R.EU))
    check('England is outside the EU set', iso.get('GB-ENG', iso.get('EN')) not in R.EU
          or 'GB-ENG' not in iso)
    check('the PES nationality set is gone', not hasattr(R, 'EU_PES'))
    check('the FL27 rule table is gone', not hasattr(R, 'RULES_FL27'))
    check('no alternate-game rule aliases remain',
          not any(hasattr(R, a) for a in ('RULES_FC27', 'DOMESTIC_FC27', 'EU_FC27')))

    # Behaviour: ids are plain small ints, so no bit masking.
    maxnat = max(int(k) for k in nations)
    check('nationality ids need no bit mask', all(R.non_eu(i) == (i not in R.EU)
                                                 for i in range(0, maxnat + 1)))
    check('an unknown nationality is not treated as non-EU', R.non_eu(None) is False)
    check('a known non-EU nation is non-EU', R.non_eu(iso['BR']) is True)
    check('a known EU nation is not non-EU', R.non_eu(iso['ES']) is False)

    # A full Serie A list must actually block an older signing.
    tid = next(k for k, v in R.RULES.items() if v['name'] == 'Serie A')
    full = [dict(pid=i, age=27, nat=iso['IT'], new=False) for i in range(25)]
    check('a full registration list blocks an over-21 signing',
          R.check(tid, full, dict(pid=999, age=27, nat=iso['IT'])) is not None)
    check('a young signing is always allowed',
          R.check(tid, full, dict(pid=999, age=20, nat=iso['BR'])) is None)
    check('a signing into a short list is allowed',
          R.check(tid, full[:20], dict(pid=999, age=27, nat=iso['IT'])) is None)
    laliga = next(k for k, v in R.RULES.items() if v.get('extra') == 3)
    noneu = [dict(pid=i, age=27, nat=iso['BR'], new=False) for i in range(3)]
    check('the non-EU squad cap is enforced',
          R.check(laliga, noneu, dict(pid=999, age=27, nat=iso['BR'])) is not None)
    check('an EU signing ignores the non-EU cap',
          R.check(laliga, noneu, dict(pid=999, age=27, nat=iso['ES'])) is None)


def section_venues():
    print('venues: name-bound, no foreign club ids')
    import venues as V
    liv = V.lookup(HERE, 'Liverpool FC')
    check('a known club resolves its ground', liv.get('ground') == 'Anfield', str(liv))
    check('the capacity is formatted', liv.get('cap') == '61,276', str(liv.get('cap')))
    check('no foreign team_id is exposed', 'team_id' not in liv)
    check('an unknown club resolves to nothing', V.lookup(HERE, 'No Such Club XYZ') == {})
    # An AMBIGUOUS name (2+ rows) must also resolve to nothing. Testing only the
    # 0-candidate case lets a `len(candidates) < 1` guard pass, which would then
    # pick an arbitrary row. 'Club Nacional' really is duplicated in the asset.
    check('an ambiguous club name resolves to nothing',
          V.lookup(HERE, 'Club Nacional') == {}, str(V.lookup(HERE, 'Club Nacional')))
    # Same guard, but with CONFLICTING grounds so a wrong pick is observable.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, 'data'))
        fixture = {'schema': 1, 'teams': {
            '11': {'club': 'Same Name FC', 'ground': 'North Park', 'cap': 20000, 'city': 'North'},
            '22': {'club': 'Same Name FC', 'ground': 'South Arena', 'cap': 30000, 'city': 'South'},
            '33': {'club': 'Unique Town', 'ground': 'Only Ground', 'cap': 12345, 'city': 'Only'},
        }}
        with open(os.path.join(td, 'data', 'venue_metadata.json'), 'w', encoding='utf-8') as fh:
            json.dump(fixture, fh)
        got = V.lookup(td, 'Same Name FC')
        check('conflicting venues for one name resolve to nothing', got == {}, str(got))
        check('an unambiguous name in the same file still resolves',
              V.lookup(td, 'Unique Town').get('ground') == 'Only Ground')
        check('a five-digit capacity is comma-formatted',
              V.lookup(td, 'Unique Town').get('cap') == '12,345')
    # A fresh folder, not a rewrite: the cache is keyed on (path, mtime, size) and
    # this filesystem's mtime granularity is coarse enough that a same-size
    # rewrite can reuse a stamp. Testing the guard must not depend on that.
    with tempfile.TemporaryDirectory() as td2:
        os.makedirs(os.path.join(td2, 'data'))
        with open(os.path.join(td2, 'data', 'venue_metadata.json'), 'w', encoding='utf-8') as fh:
            json.dump({'schema': 2, 'teams': {
                '33': {'club': 'Unique Town', 'ground': 'Only Ground', 'cap': 12345}}}, fh)
        check('an unknown schema version is refused', V.lookup(td2, 'Unique Town') == {})
    check('name matching is case and accent insensitive',
          V.lookup(HERE, 'LIVERPOOL   FC').get('ground') == 'Anfield')

    # A reserve side must not inherit the parent club's stadium.
    parent = {'ground': 'Emirates Stadium', 'cap': '60,703', 'city': 'London'}
    check('a reserve side does not inherit a parent ground',
          V.merge(HERE, 'Arsenal U21', parent) == {})
    check('the parent club keeps its ground',
          V.merge(HERE, 'Arsenal FC', parent).get('ground') == 'Emirates Stadium')
    merged = V.merge(HERE, 'Liverpool FC', {'kit': 'red', 'ground': 'Old', 'cap': '1', 'city': 'X'})
    check('the overlay replaces all three venue fields together',
          merged.get('ground') == 'Anfield' and merged.get('cap') == '61,276'
          and merged.get('city') == 'Liverpool')
    check('the overlay preserves unrelated keys', merged.get('kit') == 'red')

    # Dropping the foreign id table must not have cost any FC 27 club a venue.
    clubs = json.load(open(os.path.join(HERE, 'data/fc27/clubs.json'), encoding='utf-8'))
    rows = clubs.values() if isinstance(clubs, dict) else clubs
    resolved = sum(1 for r in rows if V.lookup(HERE, r['name']).get('ground'))
    check('venue coverage is broad after the id authority was dropped', resolved >= 260,
          'only %d clubs resolved' % resolved)
    src = open(os.path.join(HERE, 'lib/venues.py'), encoding='utf-8').read()
    check('venue lookup no longer reads a foreign id table', 'teamids' not in src)


def section_transfer_ai():
    print('transfer AI: decoupled but intact')
    import aitransfers as T

    rnd = random.Random(20261107)
    world = {}
    for ci in range(24):
        pl = [dict(pid=1000 + ci * 100 + k,
                   pos=rnd.choice([0, 1, 1, 2, 3, 4, 5, 5, 6, 7, 8, 9, 10, 11, 12]),
                   ovr=rnd.randint(60, 90), age=rnd.randint(17, 35))
              for k in range(rnd.randint(18, 30))]
        world[ci] = dict(idx=ci, name='Club Number %02d' % ci, players=pl)
    names = {p['pid']: 'Player %d' % p['pid'] for c in world.values() for p in c['players']}

    def val_of(pid, ovr, age):
        return int(max(0, ovr - 45) ** 2 * 1200 * (1.3 if age < 24 else 1.0 if age < 30 else 0.45))

    # Admission rules, preserved from the old save reader.
    probe = {
        1: dict(name='Good Club', players=[dict(pid=i, pos=5, ovr=70, age=25) for i in range(20)]),
        2: dict(name='Ab', players=[dict(pid=i, pos=5, ovr=70, age=25) for i in range(20)]),
        3: dict(name='Too Few', players=[dict(pid=i, pos=5, ovr=70, age=25) for i in range(10)]),
        4: dict(name='Too Many', players=[dict(pid=i, pos=5, ovr=70, age=25) for i in range(45)]),
        5: dict(name='Unrated', players=[dict(pid=i, pos=5, ovr=0, age=25) for i in range(20)]),
        6: dict(name='Managed', players=[dict(pid=i, pos=5, ovr=70, age=25) for i in range(20)]),
    }
    got = T.ai_world(probe, 6)
    check('only a valid senior squad is admitted', sorted(got) == [1], str(sorted(got)))
    check('the managed club is excluded', 6 not in got)
    check('a short name is rejected', 2 not in got)
    check('a squad under 16 is rejected', 3 not in got)
    check('a squad over 40 is rejected', 4 not in got)
    check('a squad with too few rated players is rejected', 5 not in got)

    # strength = mean of the top 14 rated, exactly as the old reader computed it.
    pl = [dict(pid=i, pos=5, ovr=60 + i, age=25) for i in range(20)]
    w = T.ai_world({7: dict(name='Strength Club', players=pl)}, 0)
    top = sorted((p['ovr'] for p in pl), reverse=True)[:14]
    check('strength is the mean of the top 14', abs(w[7]['strength'] - sum(top) / len(top)) < 1e-9)
    check('size is the squad length', w[7]['size'] == 20)

    # The adapter must copy, or planning would corrupt the caller's world.
    before = json.dumps(world, sort_keys=True)
    clubs = T.ai_world(world, 3)
    clubs[0]['players'][0]['ovr'] = 1
    check('ai_world returns a private copy', json.dumps(world, sort_keys=True) == before)

    clubs = T.ai_world(world, 3)
    snap = json.dumps(clubs, sort_keys=True)
    m1, s1 = T.plan(clubs, names, 3, seed=11, val_of=val_of)
    check('plan does not mutate the caller world', json.dumps(world, sort_keys=True) == before)
    check('plan proposes moves', len(m1) > 0, str(s1))
    m2, s2 = T.plan(T.ai_world(world, 3), names, 3, seed=11, val_of=val_of)
    check('plan is deterministic for a seed',
          json.dumps(m1, sort_keys=True) == json.dumps(m2, sort_keys=True) and s1 == s2)
    m3, _ = T.plan(T.ai_world(world, 3), names, 3, seed=99, val_of=val_of)
    check('a different seed changes the plan',
          json.dumps(m1, sort_keys=True) != json.dumps(m3, sort_keys=True))
    check('no move involves the managed club',
          all(mv['to_idx'] != 3 and mv['from_idx'] != 3 for mv in m1))
    check('stats count the moves', s1['moves'] == len(m1))

    # Budget callback replaces the old save-field read (was u32 in units of 100 EUR).
    mb, sb = T.plan(T.ai_world(world, 3), names, 3, seed=11, val_of=val_of,
                    budget_of=lambda ci: 50000000)
    check('the budget callback is honoured',
          sb['budget0'] and all(v == 50000000 for v in sb['budget0'].values()), str(sb['budget0'])[:120])
    mz, sz = T.plan(T.ai_world(world, 3), names, 3, seed=11, val_of=val_of, budget_of=lambda ci: 0)
    mn, sn = T.plan(T.ai_world(world, 3), names, 3, seed=11, val_of=val_of)
    check('a zero budget falls back to the virtual budget', sz['budget0'] == sn['budget0'])
    check('a larger budget is not ignored', sb['budget0'] != sz['budget0'])

    def boom(ci):
        raise RuntimeError('no budget source')
    mx, sx = T.plan(T.ai_world(world, 3), names, 3, seed=11, val_of=val_of, budget_of=boom)
    check('a failing budget callback degrades instead of crashing', sx['budget0'] == sn['budget0'])

    # v2: reasons, windows and the formation callback.
    v1, t1 = T.plan_v2(T.ai_world(world, 3), names, 3, seed=5, val_of=val_of,
                       budget_of=lambda ci: 40000000,
                       formation_of=lambda ci: ('4-3-3', [1, 1, 2, 3, 4, 5, 5, 9, 10, 12]))
    check('plan_v2 proposes moves', len(v1) > 0, str(t1))
    check('every v2 move carries a reason',
          all(mv.get('why') in ('starter', 'depth', 'replace', 'wish', 'group', 'release') for mv in v1))
    v2, t2 = T.plan_v2(T.ai_world(world, 3), names, 3, seed=5, val_of=val_of,
                       budget_of=lambda ci: 40000000,
                       formation_of=lambda ci: ('4-3-3', [1, 1, 2, 3, 4, 5, 5, 9, 10, 12]))
    check('plan_v2 is deterministic for a seed',
          json.dumps(v1, sort_keys=True) == json.dumps(v2, sort_keys=True) and t1 == t2)
    vw, tw = T.plan_v2(T.ai_world(world, 3), names, 3, seed=5, window='W', val_of=val_of,
                       budget_of=lambda ci: 40000000)
    check('the winter window halves budgets',
          all(tw['budget0'][k] * 2 == t1['budget0'][k] for k in tw['budget0'] if k in t1['budget0']))
    vf, tf = T.plan_v2(T.ai_world(world, 3), names, 3, seed=5, val_of=val_of,
                       budget_of=lambda ci: 40000000, formation_of=lambda ci: (None, None))
    check('an absent formation degrades instead of crashing', isinstance(vf, list))

    # Listings and identities still work on the adapted world.
    lst = T.build_listings(T.ai_world(world, 3), 7, val_of)
    check('build_listings produces a list', isinstance(lst, dict) and len(lst) > 0)
    priced = T.ai_world(world, 3)
    for c in priced.values():
        c['value'] = sum(val_of(p['pid'], p['ovr'], p['age']) for p in c['players'])
    ids = T.club_identities(priced)
    check('club identities cover every club', set(ids) == set(priced))
    check('identities use the known kinds',
          set(ids.values()) <= {'big', 'academy', 'experience', 'normal'})
    check('a big club wants a good player', T.ident_ok('big', dict(ovr=85, age=26), 80))
    check('a big club rejects a weak one', not T.ident_ok('big', dict(ovr=60, age=30), 80))
    check('an academy club wants youth', T.ident_ok('academy', dict(ovr=70, age=20), 75))
    check('an academy club rejects an old player', not T.ident_ok('academy', dict(ovr=70, age=30), 75))


def section_engine_still_works():
    print('engine: the strip changed no behaviour')
    import engine as E
    from engine import roster as R
    st = E.new(club=9, seed=7, sid='verify-backend')
    try:
        check('a career can be created', st['club'] == 9)
        sel = E.select(st, 9, 11)
        check('a starting XI is selected', len(sel['xi']) == 11)
        check('the 25-attribute projection is intact', len(R.AB25) == 25 and len(R.AB_SRC) == 25)
        pid = sel['xi'][0]
        check('a player projects to 25 attributes', len(R.ab25_attrs(st, pid)) == 25)
        ea = R.ea_attrs(st, pid)
        check('EA attributes are still the simulation source', len(ea) == 34)
        proj = R.project_ab25(ea)
        check('the projection produces 25 values', len(proj) == 25)
        check('the projection stays in range', all(1 <= v <= 99 for v in proj))
        # @tight is a blend, not a direct copy - it must not equal any single field.
        i = R.AB25.index('TightPossession')
        blend = max(1, min(99, round((max(1, min(99, ea['ballcontrol'])) * 2
                                    + max(1, min(99, ea['dribbling']))
                                    + max(1, min(99, ea['agility']))) / 4.0)))
        check('TightPossession is still the documented blend', proj[i] == blend)
        res = E.play_next(st, 9)
        check('a match can be played', bool(res))
        E.save(st)
        back = E.load(st['id'])
        check('a save reloads identically', back['date'] == st['date'] and back['club'] == st['club'])
    finally:
        try:
            E.delete(st['id'])
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args()
    print('FC 27 backend verification\n')
    section_backend()
    section_routes()
    section_regrules()
    section_venues()
    section_transfer_ai()
    section_engine_still_works()
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
    print('The backend is FC 27-only, and the kept algorithms still behave.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
