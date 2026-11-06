"""Dubinsko trziste: price oko AI transfera (glasine, ponude, rat ponuda, otmice, propali poslovi),
stanje klubova (budzet kroz rokove, preuzimanja, krize), interes za igrace korisnika i pamcenje trzista.

Sve je deterministicno za zadani seed (isti prozor -> iste price). Nista se ovdje ne upisuje u save:
modul samo mijenja plan prozora (kupac kod otmice, dan kod odgode, otkazani potez) i vraca price za vijesti.
"""
import datetime
import random

GROUP = {0: 'GK', 1: 'DF', 2: 'DF', 3: 'DF', 4: 'MF', 5: 'MF', 6: 'MF', 7: 'MF', 8: 'MF', 9: 'FW', 10: 'FW', 11: 'FW', 12: 'FW'}
POS_NAME = {0: 'GK', 1: 'CB', 2: 'LB', 3: 'RB', 4: 'DMF', 5: 'CMF', 6: 'LMF', 7: 'RMF', 8: 'AMF', 9: 'LWF', 10: 'RWF', 11: 'SS', 12: 'CF'}

# vjerojatnosti (po potezu s pricom)
P_WAR = 0.07            # osnovna sansa za rat ponuda
P_WAR_STAR = 0.12       # dodatno za OVR >= 80
P_WAR_FEE = 0.08        # dodatno za naknadu >= 20 M
P_HIJACK = 0.30         # u ratu ponuda: drugi klub otme igraca
P_AGENT = 0.06          # agent trazi vise -> posao kasni
P_MEDICAL = 0.025       # pao na lijecnickom -> posao propada
P_REFUSE = 0.03         # igrac odbije mali klub
P_SHOCK = 0.35          # ljetni rok: jedan sok transfer (veliki klub placa mladog)
P_TAKEOVER = 0.30       # po roku: novi vlasnik u jednom klubu (budzet x2.5)
P_CRISIS = 0.25         # po roku: financijska kriza u jednom klubu (budzet x0.35)
STORY_TOP = 45          # koliko najzvucnijih poteza dobije cijelu pricu
STORY_RANDOM = 0.08     # i nasumicni dio ostalih


def win_start(wkey):
    y = int(wkey[1:])
    return datetime.date(y, 7, 1) if wkey[0] == 'S' else datetime.date(y, 1, 1)


def day_date(wkey, day):
    d = win_start(wkey) + datetime.timedelta(days=int(day))
    return '%d.%d.%d' % (d.day, d.month, d.year)


def _rnd(seed, *k):
    return random.Random('|'.join(str(x) for x in (seed,) + k))


def _round_fee(x):
    step = 100000 if x >= 1000000 else 10000
    return int(round(x / step) * step)


# ---------------------------------------------------------------- stanje klubova prije roka

def pre_window(prev_windows, clubs, seed, wkey):
    """Budzetni modifikatori za novi rok iz povijesti (tko je pretjerao s trosenjem ima manje) + slucajni dogadjaji.
    -> (bmod {idx: faktor}, events [dict])"""
    r = _rnd(seed, 'pre', wkey)
    bmod = {}
    spent, recv, b0 = {}, {}, {}
    if prev_windows:
        last = prev_windows[-1]
        b0 = {int(k): v for k, v in (last.get('b0') or {}).items()}
        for m in last.get('plan', []):
            if m.get('done') and not m.get('skip') and m.get('fee'):
                spent[int(m['to'])] = spent.get(int(m['to']), 0) + m['fee']
                recv[int(m['from'])] = recv.get(int(m['from']), 0) + m['fee']
    for idx in set(spent) | set(recv):
        b = b0.get(idx) or 0
        if b <= 0:
            continue
        ratio = (spent.get(idx, 0) - recv.get(idx, 0)) / float(b)
        if ratio > 0.7:
            bmod[idx] = 0.7
        elif ratio > 0.4:
            bmod[idx] = 0.85
        elif ratio < -0.5:
            bmod[idx] = 1.25
    events = []
    cl = [c for c in clubs.values() if c.get('tier') in ('mid', 'small') and c['size'] >= 18]
    cl.sort(key=lambda c: c['idx'])
    if cl and r.random() < P_TAKEOVER:
        c = r.choice(cl)
        bmod[c['idx']] = bmod.get(c['idx'], 1.0) * 2.5
        events.append(dict(k='takeover', club=c['idx'], club_name=c['name'], day=r.randint(0, 6)))
    mids = [c for c in cl if c.get('tier') == 'mid' and not any(e['club'] == c['idx'] for e in events)]
    if mids and r.random() < P_CRISIS:
        c = r.choice(mids)
        bmod[c['idx']] = bmod.get(c['idx'], 1.0) * 0.35
        events.append(dict(k='crisis', club=c['idx'], club_name=c['name'], day=r.randint(0, 10)))
    return bmod, events


# ---------------------------------------------------------------- sok transfer

def shock_move(clubs, plan, seed, wkey, L, val_of, names, blocked):
    """Ljeti, rijetko: veliki klub kupi mladog (<=21) igraca iz manjeg kluba za puno vise od vrijednosti."""
    if wkey[0] != 'S':
        return None
    r = _rnd(seed, 'shock', wkey)
    if r.random() >= P_SHOCK:
        return None
    used = {int(m['pid']) for m in plan} | set(blocked)
    big = sorted((c for c in clubs.values() if c.get('tier') == 'big' and c['size'] < 33), key=lambda c: c['idx'])
    if not big:
        return None
    cands = []
    for c in sorted(clubs.values(), key=lambda c: c['idx']):
        if c.get('tier') == 'big' or c['size'] <= 21:
            continue
        for p in c['players']:
            if p['pid'] in used or not p['ovr'] or (p['age'] or 30) > 21:
                continue
            if p['ovr'] >= max(68, c['strength'] - 2):
                cands.append((c, p))
    if not cands:
        return None
    cands.sort(key=lambda x: (-x[1]['ovr'], x[1]['age'], x[1]['pid']))
    s, p = r.choice(cands[:6])
    b = r.choice(big)
    v = val_of(p['pid'], p['ovr'], p['age'])
    fee = _round_fee(max(v * r.uniform(2.2, 3.2), r.uniform(12e6, 25e6)))
    day = r.randint(3, L - 2)
    return dict(pid=p['pid'], to=b['idx'], **{'from': s['idx']}, day=day, name=names.get(p['pid'], str(p['pid'])), pos=POS_NAME.get(p['pos'], '?'),
                ovr=p['ovr'], age=p['age'], from_name=s['name'], to_name=b['name'], done=False, tier='big', from_tier=s.get('tier'),
                to_str=round(b['strength'], 1), from_str=round(s['strength'], 1), fee=fee, shock=True)


# ---------------------------------------------------------------- price

def _notable(plan, seed, wkey):
    r = _rnd(seed, 'notable', wkey)
    sc = sorted(range(len(plan)), key=lambda i: -((plan[i].get('ovr') or 60) * 3 + min(60, (plan[i].get('fee') or 0) / 1e6)))
    top = set(sc[:STORY_TOP])
    for i in sc[STORY_TOP:]:
        if r.random() < STORY_RANDOM:
            top.add(i)
    for i, m in enumerate(plan):
        if m.get('shock'):
            top.add(i)
    return sorted(top)


def _rivals(clubs, m, r, n):
    buyer = clubs.get(int(m['to']))
    bs = buyer['strength'] if buyer else 70
    pool = [c for c in clubs.values() if c['idx'] not in (int(m['to']), int(m['from'])) and c['size'] < 33 and c['strength'] >= bs - 4 and c['strength'] >= (m.get('ovr') or 70) - 9]
    pool.sort(key=lambda c: c['idx'])
    r.shuffle(pool)
    return pool[:n]


def build(plan, clubs, my, wkey, L, seed, events, val_of, names, start=0):
    """Napravi price za prozor i promijeni plan (samo nedovrsene poteze). -> lista prica.
    my: dict(idx, name, strength, players) za interes za tvoje igrace."""
    sagas = []
    sid = 0
    for i in _notable(plan, seed, wkey):
        m = plan[i]
        r = _rnd(seed, 'saga', wkey, m['pid'])
        D = int(m['day'])
        live = not m.get('done')
        st = []
        fee = m.get('fee') or 0
        ovr = m.get('ovr') or 60
        st.append(dict(k='rumour', day=D - r.randint(4, 14), club=m['to_name']))
        if fee:
            st.append(dict(k='bid', day=D - r.randint(2, 4), club=m['to_name'], fee=_round_fee(fee * r.uniform(0.75, 0.92))))
            if r.random() < 0.45:
                st.append(dict(k='rejected', day=D - r.randint(1, 2), club=m['from_name']))
        outcome = 'done'
        # rat ponuda
        pw = P_WAR + (P_WAR_STAR if ovr >= 80 else 0) + (P_WAR_FEE if fee >= 20e6 else 0)
        rivals = []
        if r.random() < pw:
            rivals = _rivals(clubs, m, r, r.choice([1, 1, 2]))
            for c in rivals:
                st.append(dict(k='rival_bid', day=D - r.randint(1, 3), club=c['name'], fee=_round_fee((fee or val_of(m['pid'], ovr, m.get('age'))) * r.uniform(1.0, 1.2))))
            if rivals and live and r.random() < P_HIJACK:
                c = rivals[0]
                nf = _round_fee((fee or val_of(m['pid'], ovr, m.get('age'))) * r.uniform(1.08, 1.3))
                st.append(dict(k='hijack', day=D - 1, club=c['name'], lost=m['to_name'], fee=nf))
                m['hijack_from'] = m['to_name']
                m['to'] = c['idx']
                m['to_name'] = c['name']
                m['tier'] = c.get('tier', m.get('tier'))
                m['to_str'] = round(c['strength'], 1)
                m['best_here'] = m['second_here'] = None
                m['fee'] = nf
                outcome = 'hijack'
            elif rivals and fee:
                m_fee = _round_fee(fee * r.uniform(1.05, 1.2))
                if live:
                    m['fee'] = m_fee
                st.append(dict(k='war_won', day=D - 1, club=m['to_name'], fee=m_fee))
        # agent / odgoda
        if outcome == 'done' and r.random() < P_AGENT:
            delay = r.randint(2, 6)
            st.append(dict(k='agent', day=D - 1, club=m['to_name']))
            if live:
                D = min(L - 1, D + delay)
                m['day'] = D
        # propast posla
        if live and outcome == 'done':
            buyer = clubs.get(int(m['to']))
            if r.random() < P_MEDICAL:
                outcome = 'collapse'
                st.append(dict(k='medical_fail', day=D, club=m['to_name']))
            elif buyer and buyer.get('tier') == 'small' and ovr >= 74 and r.random() < P_REFUSE * 3:
                outcome = 'collapse'
                st.append(dict(k='refuse', day=D, club=m['to_name']))
            if outcome == 'collapse':
                m['done'] = True
                m['skip'] = 'saga'
                m['when'] = day_date(wkey, D)
                m['win'] = wkey
        if outcome in ('done', 'hijack'):
            if D >= L - 1:
                st.append(dict(k='deadline', day=D, club=m['to_name']))
            if not m.get('shock'):
                st.append(dict(k='medical', day=max(st[-1]['day'], D - r.randint(0, 1)), club=m['to_name']))
        sid += 1
        sagas.append(dict(id=sid, kind='shock' if m.get('shock') else 'real', pid=m['pid'], name=m['name'], pos=m.get('pos'), ovr=ovr, age=m.get('age'),
                          frm=m['from_name'], to=m['to_name'], fee=m.get('fee'), outcome=outcome, rivals=[c['name'] for c in rivals],
                          stages=sorted(st, key=lambda x: x['day'])))
    # lazne price (propadaju)
    used = {int(m['pid']) for m in plan}
    r = _rnd(seed, 'fake', wkey)
    n_fake = max(4, int(len(sagas) * 0.35))
    cl = sorted(clubs.values(), key=lambda c: c['idx'])
    pool = []
    for c in cl:
        for p in c['players']:
            if p['pid'] not in used and p['ovr'] and p['ovr'] >= 75 and (p['age'] or 30) <= 32:
                pool.append((c, p))
    r.shuffle(pool)
    for c, p in pool[:n_fake * 3]:
        if n_fake <= 0:
            break
        buyers = [b for b in cl if b['idx'] != c['idx'] and b['strength'] >= c['strength'] - 1 and b['strength'] >= p['ovr'] - 8]
        if not buyers:
            continue
        b = r.choice(buyers)
        D = r.randint(max(2, start), L - 1)
        v = val_of(p['pid'], p['ovr'], p['age'])
        reason = r.choices(['seller', 'refuse', 'agent', 'pullout', 'medical_fail'], [35, 20, 25, 15, 5])[0]
        st = [dict(k='rumour', day=D - r.randint(3, 10), club=b['name'])]
        if reason in ('seller', 'pullout', 'agent', 'medical_fail'):
            st.append(dict(k='bid', day=D - r.randint(1, 3), club=b['name'], fee=_round_fee(v * r.uniform(0.8, 1.1))))
        st.append(dict(k='collapse', day=D, club=b['name'], reason=reason, seller=c['name']))
        sid += 1
        sagas.append(dict(id=sid, kind='fake', pid=p['pid'], name=names.get(p['pid'], str(p['pid'])), pos=POS_NAME.get(p['pos'], '?'), ovr=p['ovr'], age=p['age'],
                          frm=c['name'], to=b['name'], fee=None, outcome='collapse', reason=reason, rivals=[], stages=sorted(st, key=lambda x: x['day'])))
        used.add(p['pid'])
        n_fake -= 1
    # interes za tvoje igrace
    if my and my.get('players'):
        r = _rnd(seed, 'mine', wkey)
        n_int = r.choice([1, 2, 2, 3]) if wkey[0] == 'S' else r.choice([0, 1, 1, 2])
        mp = sorted((p for p in my['players'] if p['ovr'] and (p['age'] or 30) <= 31), key=lambda p: -p['ovr'])[:8]
        r.shuffle(mp)
        stronger = [c for c in cl if c['strength'] >= my.get('strength', 70) + 1]
        for p in mp[:n_int]:
            if not stronger:
                break
            b = r.choice(stronger)
            D = r.randint(max(1, start), L - 3)
            st = [dict(k='rumour', day=D, club=b['name']), dict(k='interest', day=D + r.randint(1, 3), club=b['name'])]
            out = 'cooled' if r.random() < 0.6 else 'watch'
            st.append(dict(k=out, day=min(L - 1, st[-1]['day'] + r.randint(3, 8)), club=b['name']))
            sid += 1
            sagas.append(dict(id=sid, kind='interest', mine=True, pid=p['pid'], name=names.get(p['pid'], str(p['pid'])), pos=POS_NAME.get(p['pos'], '?'),
                              ovr=p['ovr'], age=p['age'], frm=my.get('name', ''), to=b['name'], club_idx=b['idx'], fee=None, outcome=out, rivals=[], stages=st))
    for e in events:
        sid += 1
        sagas.append(dict(id=sid, kind=e['k'], pid=0, name='', frm='', to=e['club_name'], fee=None, outcome=e['k'], rivals=[],
                          stages=[dict(k=e['k'], day=e['day'], club=e['club_name'])]))
    return sagas


# ---------------------------------------------------------------- pamcenje trzista

def summary(wkey, w, over, upto=10 ** 6):
    done = [m for m in w.get('plan', []) if m.get('done') and not m.get('skip')]
    fees = [m for m in done if m.get('fee')]
    spent, recv = {}, {}
    for m in fees:
        spent[m['to_name']] = spent.get(m['to_name'], 0) + m['fee']
        recv[m['from_name']] = recv.get(m['from_name'], 0) + m['fee']
    net = {k: spent.get(k, 0) - recv.get(k, 0) for k in set(spent) | set(recv)}
    rec = max(fees, key=lambda m: m['fee']) if fees else None
    grp = {}
    for m in fees:
        g = {'GK': 'GK', 'CB': 'DF', 'LB': 'DF', 'RB': 'DF', 'DMF': 'MF', 'CMF': 'MF', 'LMF': 'MF', 'RMF': 'MF', 'AMF': 'MF'}.get(m.get('pos'), 'FW')
        a = grp.setdefault(g, [0, 0])
        a[0] += m['fee']
        a[1] += 1
    sg = [x for x in (w.get('sagas') or []) if x['stages'] and x['stages'][-1]['day'] <= upto]
    L = 62 if wkey[0] == 'S' else 31
    return dict(win=wkey, over=bool(over), end=day_date(wkey, L - 1), n=len(done), total=sum(m['fee'] for m in fees),
                record=(dict(pid=rec['pid'], name=rec['name'], fee=rec['fee'], frm=rec['from_name'], to=rec['to_name']) if rec else None),
                spenders=sorted(([k, v] for k, v in net.items() if v > 0), key=lambda x: -x[1])[:5],
                sellers=sorted(([k, -v] for k, v in net.items() if v < 0), key=lambda x: -x[1])[:5],
                avg={g: int(a[0] / a[1]) for g, a in grp.items()},
                deadline=sum(1 for m in done if int(m.get('day', 0)) >= L - 1),
                hijacks=sum(1 for x in sg if x.get('outcome') == 'hijack'),
                collapses=sum(1 for x in sg if x.get('outcome') == 'collapse'),
                shock=next((dict(name=x['name'], to=x['to'], fee=x.get('fee')) for x in sg if x.get('kind') == 'shock'), None))
