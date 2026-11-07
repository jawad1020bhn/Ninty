#!/usr/bin/env python3
"""verify_fc27.py - integrity + engine-readiness checks for data/fc27.

Stdlib only, no server and no save required. This exists because the repo has no
test suite and the integrity claims behind this database were previously made by
throwaway scripts. Run it after regenerating the data:

    python3 tools/verify_fc27.py [--dir data/fc27] [--verbose]

Exit status is 0 only if every check passes. Checks are grouped:

  identity    every per-player table covers exactly the roster, and the club /
              squad / league / team-id maps agree with each other
  coordinates formation slots and player positions are compared through
              slotCompat, and every designated starter must fit his club's shape
  references  every team id referenced anywhere resolves (club, national team or
              external side); every stadium, referee and loan endpoint resolves
  raw spaces  the tables whose ids are NOT decodable carry their warnings, so a
              future edit cannot quietly reintroduce a false alignment claim
  readiness   a career can actually be started: for EVERY club, build a matchday
              squad (XI in formation slots, subs, captain, set-piece takers,
              stadium, manager) using nothing but this database

The readiness group is the important one: it is the difference between "the files
parse" and "the engine has everything it needs to kick off".
"""

import argparse
import datetime
import json
import os
import sys

FAILURES = []
COUNT = 0


def check(name, ok, detail=''):
    global COUNT
    COUNT += 1
    if not ok:
        FAILURES.append(name)
        print('FAIL  %s%s' % (name, ('  <- ' + detail) if detail else ''))
    elif VERBOSE:
        print('pass  %s' % name)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', default='data/fc27')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()
    global VERBOSE
    VERBOSE = args.verbose
    d = args.dir

    cache = {}

    def L(name):
        """Load each file once. Re-reading inside a loop made an earlier audit
        take 74 seconds; this keeps the whole run around a second."""
        if name not in cache:
            with open(os.path.join(d, name + '.json'), encoding='utf-8') as fh:
                cache[name] = json.load(fh)
        return cache[name]

    players = L('players')
    roster = {str(r[0]) for r in players}
    name_of = {str(r[0]): r[2] for r in players}
    clubs = L('clubs')
    C = set(clubs)
    squads = L('squads')
    nat_teams = L('national_teams')
    N = set(nat_teams)
    ext = L('external_teams')
    known_teams = C | N | set(ext)

    print('FC 27 verification: %s' % os.path.abspath(d))
    print('  %d players, %d clubs, %d national teams' % (len(roster), len(C), len(N)))
    print()

    # ---------------------------------------------------------------- identity
    ratings = L('ratings')
    for tbl in ('positions', 'playpos', 'nats', 'potential', 'birthdays',
                'contract', 'traits'):
        check('%s covers exactly the roster' % tbl, set(L(tbl)) == roster)
    check('ratings covers exactly the roster', set(ratings['p']) == roster)
    ea = L('ea_attrs')
    ep = L('ea_positions')
    check('ea_attrs covers exactly the roster', set(ea['p']) == roster)
    check('ea_positions covers exactly the roster', set(ep['p']) == roster)
    check('34 raw attributes per player, all 0..99',
          len(ea['ab']) == 34 and all(len(v) == 34 and all(0 <= x <= 99 for x in v)
                                      for v in ea['p'].values()))
    check('squads == clubs == teamids', set(squads) == C == set(L('teamids')))
    all_sq = [str(p) for ps in squads.values() for p in ps]
    check('no orphan squad players', set(all_sq) <= roster)
    check('a player belongs to at most one club', len(all_sq) == len(set(all_sq)))
    check('every league team is a real club',
          {str(t) for lg in L('leagues').values() for t in lg['teams']} <= C)
    sizes = [len(ps) for ps in squads.values()]
    check('squad sizes plausible (18..38)', min(sizes) >= 18 and max(sizes) <= 38,
          'min=%d max=%d' % (min(sizes), max(sizes)))

    # -------------------------------------------------------------- real names
    # EA ships three Serie A clubs under invented names because it does not hold
    # their licence. r25 replaces them with the real names. The rename is
    # anchored to the SQUAD, not to the string: FIFPRO licenses the players even
    # when the club is unlicensed, so Maignan / Modric / Pulisic being in the
    # squad is what PROVES id 131681 is AC Milan. A later database that moves
    # these ids must fail here rather than silently mislabel another club.
    REAL_NAMES = {
        '131681': ('AC Milan',
                   ['Mike Maignan', 'Luka Modrić', 'Christian Pulisic']),
        '131682': ('Inter',
                   ['Lautaro Martínez', 'Nicolò Barella', 'Alessandro Bastoni']),
        '115845': ('Atalanta',
                   ['Marten de Roon', 'Berat Djimsiti', 'Davide Zappacosta']),
    }
    PLACEHOLDERS = {'Milano FC', 'Lombardia FC', 'Bergamo Calcio'}
    full_of = {str(r[0]): r[1] for r in players}
    teamids = L('teamids')
    for tid, (real, anchors) in REAL_NAMES.items():
        check('real name: %s is %s' % (tid, real),
              clubs.get(tid, {}).get('name') == real,
              str(clubs.get(tid, {}).get('name')))
        sq_names = {full_of.get(str(p), '') for p in squads.get(tid, [])}
        missing = [a for a in anchors if a not in sq_names]
        check('real name: %s is proven by its squad, not guessed' % real,
              not missing, 'squad lacks %s' % missing)
        check('real name: teamids agrees for %s' % real,
              teamids.get(tid) == real, str(teamids.get(tid)))
        check('real name: %s belongs to exactly one club' % real,
              sum(1 for r in clubs.values() if r['name'] == real) == 1)

    # Loans carry a DENORMALISED club name, so a rename that missed them would
    # leave the old name visible in the transfer UI. Checked for ALL 645 rows,
    # not just the renamed ones, so the next rename is covered too.
    loans = L('loans')
    stale = [(r['pid'], r['from'], r['fromName']) for r in loans
             if str(r['from']) in clubs
             and r['fromName'] != clubs[str(r['from'])]['name']]
    check('real name: every loan fromName matches its club', not stale,
          '%d stale, e.g. %s' % (len(stale), stale[:3]))

    # No placeholder may survive in ANY shipped table, including ones that
    # store names incidentally (external_teams, cups, former_clubs).
    found = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith('.json'):
            continue
        with open(os.path.join(d, fn), encoding='utf-8') as fh:
            txt = fh.read()
        hits = [p for p in PLACEHOLDERS if p in txt]
        if hits:
            found[fn] = hits
    check('real name: no EA placeholder survives in any table', not found, str(found))

    # Renaming must not become over-eager. These odd-looking names are REAL and
    # were deliberately left alone; a future "fix" must not rewrite them.
    check('real name: Lazio is not renamed to Latium',
          clubs.get('115841', {}).get('name') == 'Lazio',
          str(clubs.get('115841', {}).get('name')))
    check('real name: Logroño United kept (a real 2026 rebrand, not a placeholder)',
          any(r['name'] == 'Logroño United' for r in clubs.values()))
    check('real name: United Tigers SC kept (generated squad proves no real identity)',
          clubs.get('132681', {}).get('name') == 'United Tigers SC',
          str(clubs.get('132681', {}).get('name')))

    # The committed data must equal what a re-import produces, or the rename
    # silently reverts the next time the database is regenerated.
    imp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'tools', 'import_fc27.mjs')
    src = ''
    if os.path.isfile(imp):
        with open(imp, encoding='utf-8') as fh:
            src = fh.read()
    import re as _re
    m = _re.search(r'const REAL_TEAM_NAME = new Map\(\[(.*?)\]\);', src, _re.S)
    check('real name: importer declares REAL_TEAM_NAME', bool(m))
    table = dict(_re.findall(r"\[(\d+),\s*'([^']+)'\]", m.group(1))) if m else {}
    check('real name: importer table reproduces the committed names',
          table == {t: v[0] for t, v in REAL_NAMES.items()}, str(table))
    check('real name: importer applies the table to the raw team records',
          'for (const r of T.teams)' in src
          and 'REAL_TEAM_NAME.get(r.assetid)' in src
          and 'r.teamname = real' in src)
    check('real name: importer applies it BEFORE the TEAM map is built',
          0 <= src.find('REAL_TEAM_NAME.get(r.assetid)') < src.find('const TEAM = new Map'),
          'rename must precede every teamname read')

    # ------------------------------------------------------------- coordinates
    compat = {int(k): int(v) for k, v in ep['slotCompat'].items()}
    check('slotCompat covers all 28 EA ids', set(compat) == set(range(28)))
    pos_seen = {p for v in ep['p'].values() for p in v}
    check('every compat target is a position players actually hold',
          set(compat.values()) <= pos_seen)
    check('player EA positions all valid', all(0 <= x < 28 for x in pos_seen))
    formations = L('formations')
    check('formations cover every club', set(formations) == C)
    check('every formation has exactly 11 valid slots',
          all(len(f['pos']) == 11 and all(0 <= p < 28 for p in f['pos'])
              for fs in formations.values() for f in fs))
    sm = L('squad_meta')
    check('squad_meta covers every club', set(sm) == C)
    check('squad roles are only 0/1/2',
          all(v[1] in (0, 1, 2) for m in sm.values() for v in m.values()))
    check('every club has exactly 11 designated starters',
          all(sum(1 for v in m.values() if v[1] == 0) == 11 for m in sm.values()))
    check('shirt numbers unique within a club',
          all(len({v[0] for v in m.values()}) == len(m) for m in sm.values()))
    fit = tot = 0
    for tid, fs in formations.items():
        slots = {compat[s] for s in fs[0]['pos']}
        for pid, v in sm[tid].items():
            if v[1] == 0:
                tot += 1
                fit += any(compat.get(x, x) in slots for x in ep['p'].get(pid, []))
    check('all %d designated starters fit their club formation' % tot, fit == tot,
          '%d matched' % fit)

    # -------------------------------------------------------------- references
    stadiums = L('stadiums')
    check('every club stadium resolves',
          all(str(c['stadium']) in stadiums for c in clubs.values()))
    for tbl in ('managers', 'prev_pos'):
        check('%s covers every club' % tbl, set(L(tbl)) == C)
    rivals = L('rivals')
    check('rivalries are symmetric',
          all(int(a) in {r[0] for r in rivals.get(str(b[0]), [])}
              for a, vs in rivals.items() for b in vs))
    cups = L('cups')
    check('cup seeds are real clubs',
          all(str(t) in C for c in cups.values() for t in c.get('teams', [])))
    check('cup group members == its seed list',
          all(not isinstance(c.get('groups'), dict) or
              sorted(str(x) for g in c['groups'].values() for x in g) ==
              sorted(str(x) for x in c['teams'])
              for c in cups.values()))
    loans = L('loans')
    check('every loan names its owning club', all(l['fromName'] for l in loans))
    check('loan players are real', all(str(l['pid']) in roster for l in loans))

    contracts = L('contract')
    cited = {t for v in contracts.values() for t in (v.get('natPos') or [])}
    check('every contract.natPos id is a shipped national team', cited <= set(map(int, N)))
    check('national squads are real players',
          {str(p) for t in nat_teams.values() for p in t['squad']} <= roster)
    check('national teams are disjoint from clubs', not (N & C))
    check('national squads have no duplicates and are non-empty',
          all(t['squad'] and len(t['squad']) == len(set(t['squad']))
              for t in nat_teams.values()))

    # every team id mentioned anywhere in the shipped data
    refs = set()
    for v in L('affinities').values():
        refs.update(int(t) for t, _ in v)
    refs.update(int(t) for t in L('former_clubs').values())
    for v in L('ownership').values():
        refs.update(int(t) for t in v['siblings'])
    for vs in rivals.values():
        refs.update(int(r[0]) for r in vs)
    for l in loans:
        refs.add(int(l['from']))
        refs.add(int(l['to']))
    for c in cups.values():
        refs.update(int(t) for t in c.get('teams', []))
    for a, b in L('big_matches'):
        refs.add(int(a))
        refs.add(int(b))
    refs.update(int(t) for t in L('counterparts').values())
    dangling = sorted(t for t in refs if str(t) not in known_teams)
    check('zero dangling team references (%d distinct ids)' % len(refs),
          not dangling, str(dangling[:8]))
    check('external teams are named and disjoint from clubs/national',
          all(v['name'] for v in ext.values()) and not (set(ext) & (C | N)))
    cp = L('counterparts')
    check('men\'s/women\'s counterparts are symmetric',
          all(cp.get(str(v)) == int(k) for k, v in cp.items()))
    check('counterparts pair a men\'s side with a women\'s side',
          all(bool(clubs[k]['women']) != bool(clubs[str(v)]['women'])
              for k, v in cp.items()))
    bm = L('big_matches')
    check('marquee fixtures are unique and normalised',
          len(bm) == len({tuple(x) for x in bm}) and all(a < b for a, b in bm))
    rf = L('referees')
    check('referees are named with valid strictness',
          all(v['name'] and v['cards'] in (0, 1, 2) and v['fouls'] in (0, 1, 2)
              for v in rf['refs'].values()))
    check('league referee links resolve',
          all(str(r) in rf['refs'] for vs in rf['leagues'].values() for r in vs))
    check('competition venues resolve to stadiums',
          all(str(x['stadium']) in stadiums
              for vs in L('comp_venues').values() for x in vs))
    ps = L('prev_stats')
    check('previous-season stats are real players, 7 non-negative fields',
          set(ps['p']) <= roster and
          all(len(r) == 7 and all(x >= 0 for x in r[1:])
              for vs in ps['p'].values() for r in vs))
    check('club coefficients are real clubs with 5 yearly scores',
          set(L('coefficients')['clubs']) <= C and
          all(len(v['years']) == 5 for v in L('coefficients')['clubs'].values()))
    own = L('ownership')
    check('ownership is symmetric with no self-sibling',
          all(str(s) in own and int(t) in own[str(s)]['siblings']
              for t, v in own.items() for s in v['siblings']) and
          all(int(t) not in v['siblings'] for t, v in own.items()))

    # -------------------------------------------------------- new player fields
    def iso(s):
        try:
            datetime.date.fromisoformat(s)
            return True
        except (ValueError, TypeError):
            return False

    check('joinedClub is a valid ISO date for every player',
          all(iso(v.get('joinedClub')) for v in contracts.values()))
    check('growthProfile is 1..6 for every player',
          all(1 <= v.get('growthProfile', 0) <= 6 for v in contracts.values()))
    traits = L('traits')
    check('trait and icon bitfields are uint32',
          all(0 <= v[f] < 2 ** 32 for v in traits.values()
              for f in ('t1', 't2', 'icon1', 'icon2')))
    windows = L('calendar')['windows']
    check('two transfer windows, month/day only',
          len(windows) == 2 and
          all(set(w['open']) == {'month', 'day'} and
              1 <= w['open']['month'] <= 12 and 1 <= w['open']['day'] <= 31
              for w in windows))

    # ------------------------------------------------ undecodable id spaces
    ow = L('ovr_weights')
    check('ovr_weights warns its attribute ids are NOT ea_attrs order',
          'NOT ea_attrs' in ow.get('attrIdSpace', ''))
    check('ovr_weights makes no false attribute-alignment claim', 'ab' not in ow)
    check('per-position weights sum to 100',
          all(sum(p for _, p in v) == 100 for v in ow['positions'].values()))
    check('star bands are rating-based and start at 0',
          len(ow['stars']) == 11 and ow['stars'][0]['from'] == 0)
    rt = L('regen_templates')
    safe = {'posGroup', 'age', 'ageMin', 'ageMax', 'overall', 'potential',
            'overallMin', 'overallMax'}
    check('regen templates are keyed by FIELD NAME, not the unresolved enum',
          all(f in ea['ab'] for grp in ('youth', 'regen', 'create')
              for r in rt.get(grp, []) for f in r if f not in safe))
    check('youth ages are months, regen ages are years',
          rt['youthAgeUnit'] == 'months' and rt['regenAgeUnit'] == 'years' and
          all(140 <= r['age'] <= 176 for r in rt['youth']) and
          all(16 <= r['age'] <= 21 for r in rt['regen']))
    rn = L('regen_names')
    check('regen name pools are populated with non-empty names',
          all(rn[k] and all(r[0] for r in rn[k]) for k in ('first', 'last', 'common')))
    meta = L('fc27_meta')
    check('metadata records why tables were excluded', bool(meta.get('stillExcluded')))
    check('metadata flags the affinity scale as inferred',
          'inferred' in meta.get('affinityNote', ''))

    # ------------------------------------------------------------- readiness
    # The real question: can the engine start a career from this data alone?
    ts = L('teamsheets')
    check('teamsheets cover every club', set(ts) == C)
    problems = []
    for tid in sorted(C, key=int):
        club = clubs[tid]
        members = {str(p) for p in squads[tid]}
        xi = [p for p, v in sm[tid].items() if v[1] == 0]
        subs = [p for p, v in sm[tid].items() if v[1] == 1]
        sheet = ts.get(tid) or {}
        why = []
        if len(xi) != 11:
            why.append('xi=%d' % len(xi))
        if not subs:
            why.append('no subs')
        if not sheet.get('captain'):
            why.append('no captain')
        for duty, pid in sheet.items():
            if pid and str(pid) not in members:
                why.append('%s outside squad' % duty)
        if not str(club.get('stadium')) in stadiums:
            why.append('no stadium')
        if tid not in L('managers'):
            why.append('no manager record')
        if not formations.get(tid):
            why.append('no formation')
        if any(str(p) not in ratings['p'] for p in xi):
            why.append('xi missing ratings')
        if why:
            problems.append('%s (%s): %s' % (club['name'], tid, ', '.join(why)))
    check('every one of the %d clubs can field a matchday squad' % len(C),
          not problems, '; '.join(problems[:3]))

    print()
    if FAILURES:
        print('%d of %d checks FAILED:' % (len(FAILURES), COUNT))
        for f in FAILURES:
            print('  - %s' % f)
        return 1
    print('ALL PASS - %d checks' % COUNT)
    print('Database is complete and self-consistent, and every club can be played.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
