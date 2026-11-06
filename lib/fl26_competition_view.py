"""Read-only competition identity reconciliation, using active regulation IDs.

Career fixture tables outrank database/static-name fallbacks. Membership
overlap is not an identity test: promotion and relegation change the members.
"""
from pathlib import Path
import collections, struct
from fl26_europe_view import regulations, header_words


def _fixture_headers(data, season_module, shift):
    """Publisher header sequence plus verified 60 MB score bytes, read-only."""
    lo = season_module.SCAN0 - season_module.SCAN0 % 4
    hi = min(season_module.SCAN1 + shift, len(data)); hi -= hi % 4
    out = []
    for off in range(lo, hi - 24, 4):
        v = struct.unpack_from('<I', data, off + 4)[0]
        if 0x7e0 <= v & 65535 <= 0x800 and 1 <= v >> 24 <= 31 and 1 <= (v >> 16) & 255 <= 12:
            w, hw, aw = struct.unpack_from('<I12xII', data, off)
            score = None
            if len(data) > 50000000 and off + 30 <= len(data) and w & 0x40000000:
                b = data[off+24:off+30]
                if b[1:3] == b'\0\0' and b[4:6] == b'\0\0' and max(b[0], b[3]) <= 30:
                    score = (b[0], b[3])
            out.append((w, hw, aw, score))
    return out


def reconcile(result, catalog, data, matches, roots, season_module, shift, save_module, my_idx):
    path = next((Path(r)/'common/etc/pesdb/CompetitionRegulation.bin' for r in roots
                 if (Path(r)/'common/etc/pesdb/CompetitionRegulation.bin').is_file()), None)
    if path is None:
        raise ValueError('No active regulation source for competition identity')
    regs, _ = regulations(path)
    domestic = {l['cid'] for l in catalog['leagues']}
    main = [r for r in regs.values() if r['kind'] == 4 and r['competition'] in domestic]
    by_rid = {r['parent'] or r['key']: r['competition'] for r in main}
    by_name = collections.defaultdict(set)
    for r in main:
        by_name[r['name'].casefold()].add(r['competition'])
    candidates = collections.defaultdict(list)
    comps = result.get('comps', [])
    for i, c in enumerate(comps):
        if c.get('kind') != 'league':
            continue
        tid, cid, source = c.get('tid'), None, None
        if isinstance(tid, int) and tid in by_rid:
            cid, source = by_rid[tid], 'career-fixture-table'
        elif isinstance(tid, str) and tid.startswith('db:'):
            try:
                value = int(tid[3:])
                if value in domestic:
                    cid, source = value, 'database-fallback'
            except ValueError:
                pass
        elif isinstance(tid, str) and tid.startswith('n:'):
            ids = by_name.get(str(c.get('name', '')).casefold(), set())
            if len(ids) == 1:
                cid, source = next(iter(ids)), 'static-name-fallback'
        if cid is not None:
            candidates[cid].append((i, source))

    # Full saved fixture keys establish current-season fallback membership.
    # Do not reinterpret unrelated records or rely on the generic low-byte ID.
    headers = _fixture_headers(data, season_module, shift)
    if len(headers) != len(matches):
        raise ValueError('Fixture/header sequence changed')
    teams = {r['ref']: r for r in catalog['identity']['rows']}
    fixtures = collections.defaultdict(list)
    needed = {cid for cid, cc in candidates.items() if not any(s == 'career-fixture-table' for _, s in cc)}
    for m, (word, hw, aw, score) in zip(matches, headers):
        reg = regs.get(word & 65535)
        if not reg or reg['kind'] != 4 or reg['competition'] not in needed or m['season'] != result.get('season'):
            continue
        h, a = teams.get(m['home']), teams.get(m['away'])
        if (not h or not a or h['ref'] == a['ref'] or not word & 0x60000000
                or hw >> 14 != h['id'] or aw >> 14 != a['id']
                or word & 1023 != (reg['parent'] or reg['key'])):
            continue
        fixtures[reg['competition']].append(dict(m, _rulebook=reg['key'], _saved_score=score))

    drop, replacements, log = set(), {}, []
    for cid, cc in candidates.items():
        native = [(i, s) for i, s in cc if s == 'career-fixture-table']
        if native:
            # Keep all actual subdivisions, if the career has multiple groups.
            gone = [i for i, source in cc if source != 'career-fixture-table']
            drop.update(gone)
            if gone:
                log.append(dict(competition_id=cid, kept=[comps[i]['tid'] for i, _ in native],
                                removed=[comps[i]['tid'] for i in gone], reason='same-active-regulation-identity'))
            continue
        # Prefer complete database membership over the publisher's old name list
        # if the save has no verifiable full domestic schedule yet.
        winner = next((i for i, source in cc if source == 'database-fallback'), cc[0][0])
        display = next((comps[i]['name'] for i, source in cc if source == 'static-name-fallback'), comps[winner]['name'])
        c = dict(comps[winner], name=display)
        mm = fixtures.get(cid, [])
        members = {m[k] for m in mm for k in ('home', 'away')}
        opponents = {i: set() for i in members}
        for m in mm:
            opponents[m['home']].add(m['away']); opponents[m['away']].add(m['home'])
        # Require at least a complete round-robin participant graph. This avoids
        # declaring a few isolated/partial fixtures to be an entire league.
        complete = 8 <= len(members) <= 40 and all(len(v) == len(members)-1 for v in opponents.values())
        if complete:
            rows = []
            for idx in sorted(members):
                off = 84 + idx * 1680
                values = {key: data[off + rel] for key, rel in save_module.OFF.items()}
                if values['pl'] != values['w'] + values['d'] + values['l']:
                    raise ValueError('Inconsistent native domestic statistics')
                rows.append(dict(idx=idx, name=teams[idx]['name'], **values))
            c['rows'] = [dict(club=t['name'], **{k:t[k] for k in ('idx','pl','w','d','l','gf','ga','pts','gd','pos')})
                         for t in save_module.table(rows, save_module.results_of(mm) if hasattr(save_module, 'results_of') else None)]
            c.update(membership_source='current-career-full-fixtures', mine=my_idx in members)
            # A split league's parent club counters can remain all zero while
            # its regular-season fixtures have results. Use only complete,
            # identity-verified current-season fixtures from one kind-4 phase;
            # leave every populated native table and partial fixture set alone.
            phase_ids = {m['_rulebook'] for m in mm}
            played = [m for m in mm if m['played']]
            parent_ids = [r for r in regs.values() if r['competition'] == cid and r['kind'] == 9]
            empty = all(not any(t[k] for k in ('pl','w','d','l','gf','ga','pts')) for t in c['rows'])
            if empty and played and len(phase_ids) == 1 and len(parent_ids) == 1:
                phase = next(iter(phase_ids))
                totals = {i:dict(idx=i, name=teams[i]['name'], pl=0,w=0,d=0,l=0,gf=0,ga=0,pts=0) for i in members}
                valid = len({(m['y'],m['m'],m['dd'],m['home'],m['away']) for m in played}) == len(played)
                for m in played:
                    h,a = m['home'],m['away']
                    home = [r for r in m['rows'] if r[1] == h]
                    away = [r for r in m['rows'] if r[1] == a]
                    score = m.get('_saved_score')
                    if score is not None:
                        gh,ga = score
                    elif m.get('sc'):
                        gh,ga = m['sc']   # pc413: rezultat iz zaglavlja (autogolovi)
                    elif len(home) == 11 and len(away) == 11 and len(m['rows']) == 22:
                        gh,ga = sum(r[2] for r in home),sum(r[2] for r in away)
                    else:
                        valid = False; break
                    if not (0 <= gh <= 30 and 0 <= ga <= 30):
                        valid = False; break
                    for i,f,g in ((h,gh,ga),(a,ga,gh)):
                        t=totals[i];t['pl']+=1;t['gf']+=f;t['ga']+=g
                        t['w']+=int(f>g);t['d']+=int(f==g);t['l']+=int(f<g)
                if valid:
                    c['rows'] = [dict(club=t['name'], **{k:t[k] for k in ('idx','pl','w','d','l','gf','ga','pts','gd','pos')})
                                 for t in save_module.table([totals[i] for i in sorted(members)], [(m['home'],m['away'],*m['_saved_score']) for m in played] if all(m.get('_saved_score') is not None for m in played) else (save_module.results_of(played) if hasattr(save_module, 'results_of') else None))]
                    c.update(tid=phase, name=regs[phase]['name'], standings_source='verified-current-season-phase-results',
                             standings_rulebook=phase, standings_matches=len(played))
        c['competition_id'] = cid
        replacements[winner] = c
        gone = [i for i, _ in cc if i != winner]
        drop.update(gone)
        if gone:
            log.append(dict(competition_id=cid, kept=[c['tid']], removed=[comps[i]['tid'] for i in gone],
                            reason='one-fallback-per-active-competition', membership=c.get('membership_source')))
    result['comps'] = [replacements.get(i, c) for i, c in enumerate(comps) if i not in drop]
    result['competition_identity_cleanup'] = log
    return result
