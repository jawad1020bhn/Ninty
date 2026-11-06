"""Read-only European stages. Never changes seasonstats or a career writer.

The serialized fixture key is 16 bits (10-bit parent + child index), not
the low byte used by the generic reader. Regulations come from the winning
LiveCPK database, so added qualifying stages retain their actual identity.
"""
import collections
import hashlib
import struct
import zlib
from pathlib import Path

EUROPE = {2: (3, 'UEFA Champions League'), 3: (5, 'UEFA Europa League'),
          174: (186, 'UEFA Conference League')}
# Verified installed DR_UCL_LeaguePhase.lua KO calendar: 46 play-offs,
# 47 last 16, 51 quarters, 52 semis, 53 final.
KO = {46: ('playoffs', 'Knockout play-offs'), 47: ('r16', 'Round of 16'),
      51: ('qf', 'Quarter-finals'), 52: ('sf', 'Semi-finals'),
      53: ('final', 'Final')}


def regulations(path):
    raw = Path(path).read_bytes()
    if raw[3:8] != b'WESYS':
        raise ValueError('Unknown regulation envelope')
    data = zlib.decompress(raw[16:])
    if not data or len(data) % 2352:
        raise ValueError('Unknown regulation row size')
    rows = {}
    for p in range(0, len(data), 2352):
        r = data[p:p+2352]
        key, parent = struct.unpack_from('<H', r, 2)[0], struct.unpack_from('<H', r, 6)[0]
        if key in rows:
            raise ValueError('Duplicate regulation key')
        rows[key] = dict(key=key, parent=parent, competition=r[8], kind=r[9],
                         name=r[20:135].split(b'\0')[0].decode('utf-8'))
    return rows, hashlib.sha256(raw).hexdigest()


def header_words(data, season_module, shift):
    """Same header sequence as the publisher scanner; enrich its read results."""
    lo = season_module.SCAN0 - season_module.SCAN0 % 4
    hi = min(season_module.SCAN1 + shift, len(data)); hi -= hi % 4
    # pc261 (publisher): memoryview instead of a tuple of ~15 M ints (~300 MB transient on a 60 MB save); same values
    import sys as _sys
    if _sys.byteorder == 'little':
        mv = memoryview(bytes(data[lo:hi]))
        words = mv.cast('I')
    else:
        mv = None
        words = struct.unpack('<%dI' % ((hi-lo)//4), data[lo:hi])
    out = []
    try:
        for j in range(len(words)-6):
            v = words[j+1]
            if 0x7e0 <= (v & 65535) <= 0x800 and 1 <= v >> 24 <= 31 and 1 <= (v >> 16) & 255 <= 12:
                out.append((words[j], words[j+4], words[j+5]))
    finally:
        if mv is not None:
            words.release()
            mv.release()
    return out


def build(data, matches, season, roots, season_module, shift, my_idx, names=None):
    path = next((Path(r)/'common/etc/pesdb/CompetitionRegulation.bin' for r in roots
                 if (Path(r)/'common/etc/pesdb/CompetitionRegulation.bin').is_file()), None)
    if path is None:
        raise ValueError('No active regulation source')
    regs, regsha = regulations(path)
    headers = header_words(data, season_module, shift)
    if len(headers) != len(matches):
        raise ValueError('Fixture header sequence changed; European enrichment refused')
    from fl26_team_identity import read_teams
    identity = read_teams(data)
    teams = {r['ref']: r for r in identity['rows']}
    selected = collections.defaultdict(list)
    legacy = set()
    rejected = 0
    for m, (word, hw, aw) in zip(matches, headers):
        if m['season'] != season:
            continue
        reg = regs.get(word & 65535)
        if not reg or reg['competition'] not in EUROPE or reg['kind'] not in (1, 2, 3):
            continue
        h, a = teams.get(m['home']), teams.get(m['away'])
        if not h or not a or h['ref'] == a['ref'] or hw >> 14 != h['id'] or aw >> 14 != a['id']:
            rejected += 1
            continue
        # Real fixture flags: bit29 scheduled or bit30 played; reject loose
        # date-like data accidentally found elsewhere by the generic scanner.
        if not word & 0x60000000:
            rejected += 1
            continue
        key = reg['parent'] or reg['key']
        if key != (word & 1023):
            raise ValueError('Regulation parent does not match serialized fixture')
        row = dict(m, regulation=key, regulation_key=reg['key'], stage_kind=reg['kind'], tag=(word >> 16) & 63)
        selected[reg['competition']].append(row)
        legacy.add(m['tid'])

    def date(m):
        return (m['y'], m['m'], m['dd'], m['n'])

    def score(m):
        if not m['played']:
            return None, None
        return ((m['sc'][0] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] == m['home'])),
                (m['sc'][1] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] == m['away'])))

    def fixture(m):
        hg, ag = score(m)
        return dict(n=m['n'], h=teams[m['home']]['name'], a=teams[m['away']]['name'],
                    hi=m['home'], ai=m['away'], date='%02d/%02d/%04d' % (m['dd'],m['m'],m['y']),
                    y=m['y'], m=m['m'], d=m['dd'], played=m['played'], hg=hg, ag=ag,
                    mine=my_idx in (m['home'],m['away']), regulation=m['regulation'], tag=m['tag'])

    def table(ms, clubs):
        rows = {c: dict(club=teams[c]['name'],idx=c,pl=0,w=0,d=0,l=0,gf=0,ga=0,pts=0,gd=0) for c in clubs}
        for m in ms:
            if m['home'] not in rows or m['away'] not in rows:
                continue
            hg, ag = score(m)
            if hg is None:
                continue
            for c, f, g in ((m['home'],hg,ag),(m['away'],ag,hg)):
                t=rows[c];t['pl']+=1;t['gf']+=f;t['ga']+=g
                t['w']+=f>g;t['d']+=f==g;t['l']+=f<g
        out=list(rows.values())
        for t in out:
            t['pts']=3*t['w']+t['d'];t['gd']=t['gf']-t['ga']
        out.sort(key=lambda t:(-t['pts'],-t['gd'],-t['gf'],t['club']))
        for i,t in enumerate(out,1):t['pos']=i
        return out

    def ties(ms):
        pairs=collections.defaultdict(list)
        for m in ms:
            pairs[tuple(sorted((m['home'],m['away'])))].append(m)
        out=[]
        for pair,legs in sorted(pairs.items(),key=lambda x:date(min(x[1],key=date))):
            legs.sort(key=date)
            a,b=legs[0]['home'],legs[0]['away']
            total={a:0,b:0}
            for m in legs:
                hg,ag=score(m)
                if hg is not None:total[m['home']]+=hg;total[m['away']]+=ag
            out.append(dict(h=teams[a]['name'],a=teams[b]['name'],hi=a,ai=b,legs=[fixture(m) for m in legs],
                            aggregate=[total[a],total[b]] if len(legs)>1 and all(m['played'] for m in legs) else None))
        return out

    result=[]
    for comp,(tid,nm) in EUROPE.items():
        ms=selected.get(comp,[])
        phases=[]
        lp=[m for m in ms if m['stage_kind']==2]
        lp_clubs={c for m in lp for c in (m['home'],m['away'])}
        lp_end=max((date(m)[:3] for m in lp),default=None)
        # Earlier installed European formats reused a qualifying rulebook for
        # February's 16-club play-offs, then used native tag46 for the last16.
        # Require the actual complete two-leg/16-club structure AFTER the main
        # phase, drawn exclusively from its 36 entrants; never classify by month.
        late=[m for m in ms if m['stage_kind']==1 and lp_end and date(m)[:3]>lp_end]
        late_clubs={c for m in late for c in (m['home'],m['away'])}
        late_pairs=collections.Counter(tuple(sorted((m['home'],m['away']))) for m in late)
        legacy_playoff=(len(lp_clubs)==36 and len(late)==16 and len(late_clubs)==16
                        and late_clubs<=lp_clubs and len(late_pairs)==8 and set(late_pairs.values())=={2})
        late_ids={m['n'] for m in late} if legacy_playoff else set()
        qs=collections.defaultdict(list)
        for m in ms:
            if m['stage_kind']==1 and m['n'] not in late_ids:qs[m['regulation']].append(m)
        for rid,q in sorted(qs.items(),key=lambda x:date(min(x[1],key=date))):
            dd=sorted(q,key=date)
            # No invented Q1/Q2/Q3 designation: custom builders may omit earlier
            # rounds or run parallel paths. Preserve native rulebook + dates.
            phases.append(dict(id='qual-%d'%rid,kind='qualifying',label='Qualifying',
                               regulation=rid,date_from=fixture(dd[0])['date'],date_to=fixture(dd[-1])['date'],
                               fixtures=[fixture(m) for m in dd],ties=ties(dd)))
        par={}
        def find(c):
            while par.setdefault(c,c)!=c:c=par[c]
            return c
        for m in lp:par[find(m['home'])]=find(m['away'])
        components=collections.defaultdict(set)
        for c in par:components[find(c)].add(c)
        groups=[dict(name=chr(65+i),rows=table(lp,cs)) for i,cs in enumerate(sorted(components.values(),key=min))]
        league_phase=len(groups)==1 and len(groups[0]['rows'])==36
        games=collections.Counter(c for m in lp for c in (m['home'],m['away']))
        matchdays=max(games.values(),default=0)
        phases.append(dict(id='league',kind='league_phase' if league_phase else 'groups',
                           label='League phase' if league_phase else 'Group stage',groups=groups,
                           matchdays=matchdays,fixtures=[fixture(m) for m in sorted(lp,key=date)]))
        for tag,(ident,label) in KO.items():
            if legacy_playoff and tag==46:
                ko=late
            elif legacy_playoff and tag==47:
                ko=[m for m in ms if m['stage_kind']==3 and m['tag'] in (46,47)]
            else:
                ko=[m for m in ms if m['stage_kind']==3 and m['tag']==tag]
            phases.append(dict(id=ident,kind='knockout',label=label,
                               fixtures=[fixture(m) for m in sorted(ko,key=date)],ties=ties(ko)))
        unknown=[m for m in ms if m['stage_kind']==3 and m['tag'] not in KO]
        if unknown:
            phases.append(dict(id='other-ko',kind='knockout',label='Other recorded knockout rounds',
                               fixtures=[fixture(m) for m in sorted(unknown,key=date)],ties=ties(unknown)))
        # Publisher-compatible main groups represent ONLY the actual main phase.
        played=sorted([m for m in lp if m['played']],key=date)
        future=sorted([m for m in lp if not m['played']],key=date)
        def short(m):
            f=fixture(m)
            return dict(h=f['h'],a=f['a'],d=f['date'],mine=f['mine'],s='%s:%s'%(f['hg'],f['ag']) if m['played'] else '')
        def leaders(col):
            counts={}
            for m in played:
                for row in m['rows']:
                    if row[col]:
                        key=(row[0],row[1]);counts[key]=counts.get(key,0)+row[col]
            return [dict(pid=pid,name=(names or {}).get(pid,str(pid)),club=teams[club]['name'],n=v)
                    for (pid,club),v in sorted(counts.items(),key=lambda kv:-kv[1])[:8] if club in teams]
        result.append(dict(tid=tid,kind='groups',name=nm,name_en=nm,mine=False,groups=groups,europe_projection=True,
                           matchdays=matchdays,europe_stages=phases,
                           playoff_layout='qualifying-rulebook-reused' if legacy_playoff else 'native-knockout-tags',
                           stage_source=dict(regulation_path=str(path),sha256=regsha,read_only=True),
                           side=dict(res=[short(m) for m in reversed(played[-10:])],nxt=[short(m) for m in future[:10]],
                                     scorers=leaders(2),assists=leaders(3),md=max((r['pl'] for g in groups for r in g['rows']),default=0))))
    return dict(comps=result, legacy_tids=sorted(legacy),
                qualifier_alias_tids=sorted({r['parent'] & 255 for r in regs.values()
                                              if r['competition'] in EUROPE and r['kind'] == 1}), rejected=rejected,
                source=str(path),regulation_sha256=regsha)
