"""Price (storylines): povezani lanci dogadjaja izvedeni iz rezultata, forme, ugovora i zahtjeva igraca.
Bez vlastitog stanja: svaki poziv racuna lance iz trenutnog save-a (deterministicno), pa se lanac sam nastavlja kako igra napreduje.
Svaka faza: k (kljuc teksta), on (dostignuta), cur (trenutna), p (parametri teksta). Tekstove slaze frontend."""
import hashlib


def _r(*a):
    h = hashlib.md5('|'.join(str(x) for x in a).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _st(keys, reached, params=None):
    """keys: redoslijed faza; reached: broj dostignutih faza (>=1)."""
    params = params or {}
    return [dict(k=k, on=i < reached, cur=(i == reached - 1), p=params.get(k, {})) for i, k in enumerate(keys)]


def build(slot, mk, results, form, contracts, requests, rivals, my_avg):
    """results: najnovija prva [{res,gf,ga,opp,date,n}]; form: [{pid,name,pos,ovr,target,level,n}], contracts: [{pid,name,ovr,age,months,sal,mv}],
    requests: [{pid,name,status,reason,rank,strikes}], rivals: [(ime, snaga)] jaci klubovi; my_avg: prosjek OVR prve 11."""
    out = []
    last5 = results[:5]
    w = sum(1 for m in last5 if m['res'] == 'W')
    l = sum(1 for m in last5 if m['res'] == 'L')
    gf = sum(m['gf'] for m in last5)
    ga = sum(m['ga'] for m in last5)
    series = [m['res'] for m in last5]
    byp = {f['pid']: f for f in form}
    low = sorted([f for f in form if f['target'] <= 2 and f['n'] >= 2], key=lambda f: (f['target'], -f['ovr']))
    hot = sorted([f for f in form if f['target'] >= 6 and f['n'] >= 2], key=lambda f: (-f['target'], -f['ovr']))

    # 1) Kriza momcadi
    if len(last5) >= 3 and (l >= 3 or (w == 0 and l >= 2 and len(last5) >= 4)):
        reached = 1 + (l >= 3) + (len(low) >= 2) + (l >= 4 and len(low) >= 3)
        out.append(dict(id='crisis', kind='crisis', sev=3 if reached >= 3 else 2, pid=None,
                        stages=_st(['results', 'media', 'dressing', 'boiling'], reached,
                                   dict(results=dict(w=w, l=l, gf=gf, ga=ga, series=series), media=dict(l=l), dressing=dict(names=[f['name'] for f in low[:3]], n=len(low)),
                                        boiling=dict(n=len(low)))),
                        actions=[dict(go='press', k='a_press'), dict(go='squad', k='a_lineup')], pids=[f['pid'] for f in low[:3]]))
    # 2) Uzlet momcadi
    if len(last5) >= 3 and (w >= 4 or (w >= 3 and l == 0)):
        top = hot[:3]
        reached = 1 + 1 + (len(top) >= 1) + (len(top) >= 2 and w >= 4)
        out.append(dict(id='surge', kind='surge', sev=1, pid=None,
                        stages=_st(['results', 'buzz', 'stars', 'rivals'], reached,
                                   dict(results=dict(w=w, l=l, gf=gf, ga=ga, series=series), stars=dict(names=[f['name'] for f in top]),
                                        rivals=dict(club=(rivals[int(_r(slot, mk, 'sg') * len(rivals))][0] if rivals else ''), name=(top[0]['name'] if top else '')))),
                        actions=[dict(go='press', k='a_press'), dict(go='inbox', k='a_contracts')], pids=[f['pid'] for f in top]))
    # 3) Zvijezda u formi: zanimanje velikih klubova (po igracu, najvise 2)
    done = set()
    for f in hot:
        if len(done) >= 2:
            break
        c = next((x for x in contracts if x['pid'] == f['pid']), None)
        if not c or f['ovr'] < my_avg - 2 or not rivals:
            continue
        months = c.get('months')
        club = rivals[int(_r(slot, mk, f['pid'], 'rv') * len(rivals))][0]
        reached = 1 + (f['target'] >= 6) + (months is not None and months <= 24) + (months is not None and months <= 12)
        out.append(dict(id='star%d' % f['pid'], kind='star', sev=2 if months is not None and months <= 12 else 1, pid=f['pid'],
                        stages=_st(['form', 'buzz', 'interest', 'agent'], reached,
                                   dict(form=dict(level=f['target'], name=f['name']), interest=dict(club=club, name=f['name']),
                                        agent=dict(months=months, name=f['name']))),
                        actions=[dict(go='contract', k='a_extend', pid=f['pid']), dict(go='press', k='a_press')], pids=[f['pid']]))
        done.add(f['pid'])
    # 4) Pad forme igraca (po igracu, najvise 2): osnovni igraci s forma<=1
    n = 0
    for f in low:
        if n >= 2 or f['target'] > 1:
            continue
        reached = 1 + (f['n'] >= 3) + (l >= 2)
        out.append(dict(id='slump%d' % f['pid'], kind='slump', sev=2 if reached >= 3 else 1, pid=f['pid'],
                        stages=_st(['form', 'fans', 'manager'], reached, dict(form=dict(name=f['name'], pos=f['pos']), fans=dict(name=f['name']), manager=dict(name=f['name']))),
                        actions=[dict(go='squad', k='a_lineup'), dict(go='press', k='a_press')], pids=[f['pid']]))
        n += 1
    # 5) Klupa -> nezadovoljstvo -> zahtjev za odlazak
    for q in requests:
        if q['status'] not in ('open', 'promised', 'refused', 'forced'):
            continue
        st = {'promised': 2, 'open': 2, 'refused': 3, 'forced': 4}.get(q['status'], 2)
        out.append(dict(id='req%d' % q['pid'], kind='bench', reason=q.get('reason'), sev=3 if q['status'] in ('open', 'forced') else 2, pid=q['pid'],
                        stages=_st(['bench', 'grumble', 'request', 'forced'], st,
                                   dict(bench=dict(name=q['name'], rank=q.get('rank'), reason=q.get('reason')), grumble=dict(name=q['name'], reason=q.get('reason')), request=dict(name=q['name'], reason=q.get('reason')),
                                        forced=dict(name=q['name'], strikes=q.get('strikes', 0)))),
                        actions=[dict(go='inbox', k='a_talk', pid=q['pid'])], pids=[q['pid']]))
    # 6) Ugovor istice (dobar igrac, <=6 mj.), ako nema vec lanca za igraca
    have = {o['pid'] for o in out if o['pid']}
    k = 0
    for c in sorted([c for c in contracts if c.get('months') is not None and c['months'] <= 6 and c['ovr'] >= my_avg - 4], key=lambda c: (c['months'], -c['ovr'])):
        if c['pid'] in have or k >= 2:
            continue
        club = rivals[int(_r(slot, mk, c['pid'], 'ct') * len(rivals))][0] if rivals else ''
        out.append(dict(id='exp%d' % c['pid'], kind='expiring', sev=3 if c['months'] <= 2 else 2, pid=c['pid'],
                        stages=_st(['expiring', 'agent', 'rival'], 1 + (c['months'] <= 5) + (c['months'] <= 3 and bool(club)),
                                   dict(expiring=dict(name=c['name'], months=c['months']), agent=dict(name=c['name']), rival=dict(name=c['name'], club=club))),
                        actions=[dict(go='contract', k='a_extend', pid=c['pid'])], pids=[c['pid']]))
        k += 1
    out.sort(key=lambda o: -o['sev'])
    return out
