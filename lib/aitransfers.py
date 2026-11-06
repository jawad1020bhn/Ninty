"""Pravila AI transfera: predlaze listu (igrac, iz kluba, u klub) bez ikakvog upisa u save.
Izvrsenje je mlwrite.Save.ai_apply. Sve je deterministicno za zadani seed."""
import random
import struct

POS_NAME = {0: 'GK', 1: 'CB', 2: 'LB', 3: 'RB', 4: 'DMF', 5: 'CMF', 6: 'LMF', 7: 'RMF', 8: 'AMF', 9: 'LWF', 10: 'RWF', 11: 'SS', 12: 'CF'}
GROUP = {0: 'GK', 1: 'DF', 2: 'DF', 3: 'DF', 4: 'MF', 5: 'MF', 6: 'MF', 7: 'MF', 8: 'MF', 9: 'FW', 10: 'FW', 11: 'FW', 12: 'FW'}
MIN_GROUP = {'GK': 2, 'DF': 6, 'MF': 6, 'FW': 3}
WANT_POS = [1, 1, 2, 3, 4, 5, 5, 8, 9, 10, 12, 12]   # tezine po poziciji za kupnju (vanjski igraci)


def _club_name(d, idx):
    o = 84 + 1680 * idx
    return bytes(d[o:o + 48]).split(b'\0')[0].decode('utf-8', 'replace')


def national_like(save):
    """Skup indeksa zapisa koji su reprezentacije/posebne momcadi: skoro svi njihovi igraci su u jos jednom zapisu."""
    d = save.d
    recs = {}
    n = 0
    import mlsave
    lim, nat = mlsave.club_layout(d)   # pc256: granica i reprezentacije iz club_layout (60 MB: klubovi i iznad 750)
    while 84 + 1680 * (n + 1) <= len(d) and n < lim:
        o = 84 + 1680 * n
        L = save._squad_len(o)
        if n in nat:   # reprezentacije se ne broje: inace su veliki klubovi (Atletico, Arsenal) 'duplikati' i ispadnu iz AI svijeta
            n += 1
            continue
        if 0 < L <= 40:
            recs[n] = [struct.unpack_from('<I', d, o + save.PAIR_OFF + 8 * i + 4)[0] for i in range(L)]
        n += 1
    cnt = {}
    for ids in recs.values():
        for pid in set(ids):
            cnt[pid] = cnt.get(pid, 0) + 1
    out = set()
    for n, ids in recs.items():
        dup = sum(1 for pid in ids if cnt[pid] > 1)
        if dup >= 0.6 * len(ids):
            out.add(n)
    # reprezentacije su jedan neprekinut blok na kraju: sve od prve prepoznate nadalje (slabe reprezentacije imaju malo duplikata)
    hi = [n for n in out if n >= 500 and n < 750]
    if hi and lim <= 750:
        out |= set(range(min(hi), 750))
    out |= set(nat)
    return out


def load_clubs(save, rat, pos_of, my_idx):
    d = save.d
    clubs = {}
    skip = national_like(save)
    n = 0
    import mlsave
    _lim = mlsave.club_layout(d)[0]   # pc256
    while 84 + 1680 * (n + 1) <= len(d) and n < _lim:
        o = 84 + 1680 * n
        nm = bytes(d[o:o + 48]).split(b'\0')[0]
        try:
            nm = nm.decode('utf-8')
        except UnicodeDecodeError:
            n += 1
            continue
        L = save._squad_len(o)
        if n != my_idx and n not in skip and len(nm) >= 3 and nm.isprintable() and 16 <= L <= 40:
            pl = []
            for i in range(L):
                pid = struct.unpack_from('<I', d, o + save.PAIR_OFF + 8 * i + 4)[0]
                ov, ag = rat(pid)
                pl.append(dict(pid=pid, pos=pos_of.get(pid, 5), ovr=ov, age=ag))
            top = sorted((p['ovr'] for p in pl if p['ovr']), reverse=True)[:14]
            if len(top) >= 11:
                clubs[n] = dict(idx=n, name=nm, players=pl, strength=sum(top) / len(top), size=L)
        n += 1
    return clubs


def build_listings(clubs, seed, val_of=None):
    """Realna transfer lista i lista posudbi AI klubova (deterministicno iz seed-a).
    transfer: visak momcadi (22+ po OVR-u), stariji (>=32) izvan prve postave, rijetko 'trazi odlazak' (zvijezda u slabijem klubu).
    posudba: mladi (<=21/23) koji ne igraju (daleko od prve postave). -> {pid: dict(kind, reason, club_idx, club, ask|share/buy)}"""
    out = {}
    for c in clubs.values():
        r = random.Random('%s|%s' % (seed, c['idx']))
        pl = sorted((p for p in c['players'] if p['ovr']), key=lambda q: -q['ovr'])
        n = len(pl)
        if n < 18:
            continue
        gc = {'GK': 0, 'DF': 0, 'MF': 0, 'FW': 0}
        for q in pl:
            gc[GROUP[q['pos']]] += 1
        cap_t = 4 if c['strength'] > 78 else 3
        nt = nl = 0

        def val(q):
            return q['val'] if q.get('val') else (val_of(q['pid'], q['ovr'], q['age']) if val_of else 0)
        for rk, q in enumerate(pl):
            g = GROUP[q['pos']]
            ok_pos = gc[g] - 1 >= MIN_GROUP[g]
            # posudba van (omjer ~7-8 % momcadi, 1-3 po klubu): mladi koji ne igraju (glavnina), marginalni 24-29 (rjedje, cesto s opcijom otkupa)
            lp = 0.0
            if q['age'] <= 21 and rk >= 14 and q['ovr'] <= c['strength'] - 5:
                lp = 0.30
            elif q['age'] <= 23 and rk >= 15 and q['ovr'] <= c['strength'] - 6:
                lp = 0.16
            elif 24 <= q['age'] <= 29 and rk >= 19 and q['ovr'] <= c['strength'] - 10:
                lp = 0.09
            if nl < (3 if n >= 24 else 2) and lp and r.random() < lp:
                v = val(q)
                sh = round(r.uniform(0.5, 1.0), 2)
                out[q['pid']] = dict(kind='loan', reason='minutes', club_idx=c['idx'], club=c['name'], share=sh,
                                     buy=(rnd100(v * r.uniform(1.0, 1.25)) if r.random() < (0.5 if q['age'] <= 23 else 0.7) else None), val=v)
                nl += 1
                continue
            if nt >= cap_t or not ok_pos or q['pid'] in out:
                continue
            reason, f = None, 1.0
            if rk >= 22 and q['age'] >= 24 and r.random() < 0.55:
                reason, f = 'surplus', r.uniform(0.95, 1.15)
            elif q['age'] >= 32 and rk >= 12 and r.random() < 0.5:
                reason, f = 'aging', r.uniform(0.6, 0.85)
            elif rk <= 8 and q['ovr'] >= c['strength'] + 1 and c['strength'] < 78 and r.random() < 0.02:
                reason, f = 'wants_out', r.uniform(1.15, 1.4)
            if reason:
                v = val(q)
                out[q['pid']] = dict(kind='transfer', reason=reason, club_idx=c['idx'], club=c['name'], ask=rnd100(v * f), val=v)
                gc[g] -= 1
                nt += 1
    return out


def rnd100(x, step=None):
    step = step or (100000 if x >= 1000000 else 10000)
    return int(round(x / step) * step)


SAL_RESERVE = 0.06
BUDGET_FRAC = 0.18   # virtualni transfer budzet kluba u prozoru = udio vrijednosti momcadi (top 25 igraca)


def plan(save, rat, pos_of, names, my_idx, seed=1, scale=1.0, protect_pids=(), val_of=None, wage_of=None, listed=None, bmod=None):
    """val_of(pid, ovr, age) -> trzisna vrijednost u EUR; ako je zadan, klubovi imaju virtualne budzete i potezi nose cijenu (fee)."""
    rnd = random.Random(seed)
    clubs = load_clubs(save, rat, pos_of, my_idx)
    vals = {}
    budget = {}
    if val_of:
        for c in clubs.values():
            for p in c['players']:
                p['val'] = val_of(p['pid'], p['ovr'], p['age'])
            top = sorted((p['val'] for p in c['players']), reverse=True)[:25]
            c['value'] = sum(top)
            budget[c['idx']] = c['value'] * (BUDGET_FRAC * scale + 0.01)
            try:  # pravi pocetni transfer budzet kluba iz igre (club+1600, u jedinicama od 100 EUR)
                import struct as _st
                b0 = _st.unpack_from('<I', save.d, 84 + 1680 * c['idx'] + 1600)[0]
                if 0 < b0 < 0xFFFFFFFF:
                    budget[c['idx']] = b0 * 100 * scale
            except Exception:
                pass
        for k, f in (bmod or {}).items():   # stanje kluba iz proslih rokova / preuzimanje / kriza
            if k in budget:
                budget[k] *= f
    budget0 = {k: int(v) for k, v in budget.items()}
    wres = {}
    if wage_of:   # procjena salary budgeta: rezerva = SAL_RESERVE zbroja placa momcadi (kalibrirano na igru: 4-6 %)
        for c in clubs.values():
            for p in c['players']:
                p['wage'] = wage_of(p['pid']) or 0
            wres[c['idx']] = SAL_RESERVE * sum(p['wage'] for p in c['players'])
    order = sorted(clubs.values(), key=lambda c: -c['strength'])
    nb = max(1, int(len(order) * 0.09))
    nm_ = int(len(order) * 0.49)
    for i, c in enumerate(order):
        c['tier'] = 'big' if i < nb else 'mid' if i < nm_ else 'small'
        c['rank'] = i
    group_cnt = {}
    for c in clubs.values():
        g = {'GK': 0, 'DF': 0, 'MF': 0, 'FW': 0}
        for p in c['players']:
            g[GROUP[p['pos']]] += 1
        group_cnt[c['idx']] = g
    moved, sold, bought = set(protect_pids), {}, {}
    stars = 0
    moves = []

    def quota(c):
        t = c['tier']
        if t == 'big':
            q = rnd.choice([2, 3])
        elif t == 'mid':
            q = rnd.choice([1, 2])
        else:
            q = 1 if rnd.random() < 0.5 else 0
        r = q * scale
        q = int(r) + (1 if rnd.random() < r - int(r) else 0)
        return q

    buyers = [(c, quota(c)) for c in order]
    rnd.shuffle(buyers)
    tasks = []
    for c, q in buyers:
        tasks += [c] * q
    rnd.shuffle(tasks)
    sellers_pool = list(clubs.values())
    for b in tasks:
        bi = b['idx']
        if b['size'] + bought.get(bi, 0) - sold.get(bi, 0) >= 34:
            continue
        g = group_cnt[bi]
        need = [k for k, v in MIN_GROUP.items() if g[k] < v]
        if need:
            cand_pos = [p for p in WANT_POS if GROUP[p] in need] or ([0] if 'GK' in need else WANT_POS)
            if 'GK' in need:
                cand_pos = [0]
        else:
            cand_pos = list(WANT_POS)
            if g['GK'] < 3 and b['tier'] == 'big' and rnd.random() < 0.15:
                cand_pos = [0]
        pc = rnd.choice(cand_pos)
        mine_at = sorted((p['ovr'] for p in b['players'] if p['pos'] == pc and p['ovr']), reverse=True)
        grp_at = sorted((p['ovr'] for p in b['players'] if GROUP[p['pos']] == GROUP[pc] and p['ovr']), reverse=True)
        base = b['strength']
        if mine_at:
            floor = mine_at[1] if len(mine_at) > 1 and pc != 0 else mine_at[0] - 2
        else:
            floor = (grp_at[2] if len(grp_at) > 2 else base - 5)
        hi_gap = {'big': 8, 'mid': 6, 'small': 5}[b['tier']]
        lo = max(base - 5, floor - 1) if pc != 0 else floor - 1
        hi = base + hi_gap
        max_age = 34 if b['tier'] == 'small' else 32
        cands = []
        for s in sellers_pool:
            if s['idx'] == bi:
                continue
            if s['strength'] > b['strength'] + 3:
                continue
            top5 = {q['pid'] for q in sorted(s['players'], key=lambda q: -q['ovr'])[:5]}
            ssz = s['size'] - sold.get(s['idx'], 0) + bought.get(s['idx'], 0)
            if ssz <= 21 or sold.get(s['idx'], 0) >= 3:
                continue
            sg = group_cnt[s['idx']]
            for p in s['players']:
                if p['pos'] != pc or p['pid'] in moved or not p['ovr'] or p['age'] > max_age:
                    continue
                if not lo <= p['ovr'] <= hi:
                    continue
                if val_of and p['val'] * 1.15 > budget.get(bi, 0):
                    continue   # kupac si ne moze priustiti
                if wage_of and p.get('wage', 0) > wres.get(bi, 0):
                    continue   # placa ne stane u salary budget kupca
                if sg[GROUP[p['pos']]] - 1 < MIN_GROUP[GROUP[p['pos']]]:
                    continue
                if p['ovr'] >= 85 and (b['rank'] > 20 or stars >= 6):
                    continue
                if p['pid'] in top5 and b['strength'] < s['strength'] - 1:
                    continue   # zvijezdu ne prodaje klub jaci od kupca
                # prodavac ne gubi svoju zvijezdu ako je veci klub od kupca
                cands.append((s, p))
        if not cands:
            continue
        # tezina: blize idealu (osrednje poboljsanje) i stariji/mladi bez posebne preferencije
        target = (floor + hi) / 2 if pc != 0 else floor + 2
        wts = [(1.0 / (1 + abs(p['ovr'] - target))) * (8.0 if (listed and listed.get(p['pid'], {}).get('kind') == 'transfer') else 1.0) for s, p in cands]
        s, p = rnd.choices(cands, wts)[0]
        fee = None
        lst = (listed or {}).get(p['pid'])
        if val_of:
            fee = min(((lst['ask'] * rnd.uniform(0.9, 1.0)) if lst and lst.get('kind') == 'transfer' else p['val'] * rnd.uniform(0.85, 1.15)), budget[bi])
            step = 100000 if fee >= 1000000 else 10000
            fee = int(round(fee / step) * step)
            budget[bi] -= fee
            budget[s['idx']] = budget.get(s['idx'], 0) + fee
        if wage_of:
            wres[bi] = wres.get(bi, 0) - p.get('wage', 0)
            wres[s['idx']] = wres.get(s['idx'], 0) + p.get('wage', 0)
        moved.add(p['pid'])
        sold[s['idx']] = sold.get(s['idx'], 0) + 1
        bought[bi] = bought.get(bi, 0) + 1
        group_cnt[s['idx']][GROUP[p['pos']]] -= 1
        group_cnt[bi][GROUP[p['pos']]] += 1
        if p['ovr'] >= 85:
            stars += 1
        moves.append(dict(pid=p['pid'], name=names.get(p['pid'], str(p['pid'])), pos=POS_NAME.get(p['pos'], '?'), ovr=p['ovr'], age=p['age'],
                          from_idx=s['idx'], from_name=s['name'], to_idx=bi, to_name=b['name'], tier=b['tier'], fee=fee, wage=p.get('wage'), from_tier=s['tier'], to_rank=b['rank'], from_rank=s['rank'],
                          best_here=(mine_at[0] if mine_at else None), second_here=(mine_at[1] if len(mine_at) > 1 else None),
                          short=bool(need), to_str=round(b['strength'], 1), from_str=round(s['strength'], 1),
                          reason='reinforcement at %s (first/second in club: %s)' % (POS_NAME.get(pc), mine_at[0] if mine_at else '-'),
                          listed=bool(lst and lst.get('kind') == 'transfer'), list_reason=(lst or {}).get('reason')))
    stats = dict(clubs=len(clubs), moves=len(moves), big=sum(1 for m in moves if m['tier'] == 'big'),
                 mid=sum(1 for m in moves if m['tier'] == 'mid'), small=sum(1 for m in moves if m['tier'] == 'small'),
                 stars=stars, fees=sum((m.get('fee') or 0) for m in moves), budget0=budget0)
    return moves, stats


# ============================================================ v2: realni prijelazni rok (pc86)
# Svaki klub ima broj dolazaka iz realne raspodjele (ljeto ~3-4, zima ~1). Kad klub izgubi vaznog igraca, dobiva
# zadatak zamjene (ista pozicija, slicna razina). Mete prema razini kluba: veliki ciljaju najbolje iz manjih klubova,
# srednji vrijednost i mlade, mali jeftine, starije i viskove vecih klubova (cesto bez naknade).
# Pamcenje: zelje koje klub nije mogao ostvariti idu u sljedeci rok. Vlasnicke grupe: igraci kruze unutar grupe.

FAMILY = {0: 'GK', 1: 'CB', 2: 'LB', 3: 'RB', 4: 'DM', 5: 'CM', 8: 'AM', 6: 'LW', 9: 'LW', 7: 'RW', 10: 'RW', 11: 'ST', 12: 'ST'}
IDEAL = {'GK': 3, 'CB': 4, 'LB': 2, 'RB': 2, 'DM': 2, 'CM': 3, 'AM': 2, 'LW': 2, 'RW': 2, 'ST': 3}
FAM_NAME = {'GK': 'GK', 'CB': 'CB', 'LB': 'LB', 'RB': 'RB', 'DM': 'DMF', 'CM': 'CMF', 'AM': 'AMF', 'LW': 'left wing', 'RW': 'right wing', 'ST': 'striker'}
SUMMER_DIST = [(0, 2), (1, 5), (2, 12), (3, 21), (4, 23), (5, 17), (6, 10), (7, 5), (8, 3), (9, 2)]
WINTER_DIST = [(0, 38), (1, 33), (2, 18), (3, 8), (4, 3)]
MIN_SIZE, MAX_SIZE = 22, 33
INJ_LONG, INJ_NOBUY = 45, 14   # pc198: dana ozljede: dugo ozlijedjen (trazi se zamjena) / klub ga ne kupuje


def _pick_n(rnd, dist):
    return rnd.choices([k for k, _ in dist], [w for _, w in dist])[0]


def _age_w(tier, age, why):
    if why == 'release':
        return 1.0
    if tier == 'big':
        return 1.25 if 21 <= age <= 28 else 0.9 if age <= 30 else 0.35 if age <= 32 else 0.1
    if tier == 'mid':
        return 1.5 if age <= 24 else 1.1 if age <= 28 else 0.6 if age <= 31 else 0.25
    return 1.0 if age <= 31 else 0.7 if age <= 33 else 0.3



# ---- identitet kluba (pc194; pravila: Michele & Claude, "Identita dei Club", FL26 Master League Realism Mods)
#   big        kupuje samo zvijezde (78+) ili talente do 21 god. (72+)
#   academy    kupuje samo igrace do 24 god.
#   experience kupuje od 27 god. nadalje (osim zvijezda 80+)
#   normal     bez pravila
# Rucni popis (data/club_identity.json, po imenu kluba) ima prednost; ostali automatski po vrijednosti i dobi momcadi.
# Jedna kupnja od pet ne slijedi pravilo (da ne bude mehanicki).
_IDENT = None


def _ident_manual():
    global _IDENT
    if _IDENT is None:
        try:
            import json as _j
            import os as _o
            _IDENT = _j.load(open(_o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), 'data', 'club_identity.json'),
                                  encoding='utf-8')).get('clubs', {})
        except Exception:
            _IDENT = {}
    return _IDENT


def club_identities(clubs):
    """{idx: 'big'|'academy'|'experience'|'normal'} za klubove iz load_clubs (s 'value' i 'players')."""
    man = _ident_manual()
    vals = sorted((c.get('value', 0) for c in clubs.values()), reverse=True)
    if not vals:
        return {}
    top = vals[max(0, int(len(vals) * 0.03) - 1)]
    upper = vals[max(0, int(len(vals) * 0.35) - 1)]
    out = {}
    for c in clubs.values():
        k = man.get(c['name'])
        if not k:
            best = sorted((p for p in c['players'] if p['ovr']), key=lambda q: -q['ovr'])[:16]
            age = sum(p['age'] for p in best) / len(best) if best else 26
            v = c.get('value', 0)
            if v >= top and v > 0:
                k = 'big'
            elif v >= upper and age <= 24.6:
                k = 'academy'
            elif v >= upper and age >= 29.0:
                k = 'experience'
            else:
                k = 'normal'
        out[c['idx']] = k
    return out


def ident_ok(kind, p, base):
    if kind == 'big':
        return p['ovr'] >= min(78, base) or (p['age'] <= 21 and p['ovr'] >= min(72, base - 6))
    if kind == 'academy':
        return p['age'] <= 24
    if kind == 'experience':
        return p['age'] >= 27 or p['ovr'] >= 80
    return True


def plan_v2(save, rat, pos_of, names, my_idx, seed=1, scale=1.0, protect_pids=(), val_of=None, wage_of=None, listed=None, bmod=None,
            window='S', memory=None, owners=None, reg=None, inj=None, past=None):
    """Isti izlaz kao plan(); dodatno: m['why'] (starter/depth/replace/wish/group/release), m['repl'] (ime igraca kojeg zamjenjuje),
    m['after'] (pid prodaje koja je pokrenula zamjenu), m['group'] (vlasnicka grupa). stats['wish'] = zelje za sljedeci rok."""
    rnd = random.Random('v2|%s|%s' % (seed, window))
    memory = memory or {}
    owners = owners or {}
    inj = inj or {}   # pc198: {pid: dani ozljede} (Injuries For All / F7 dump)
    # pc352: povijest igraca {pid: {block: {klub}, back: {klub}, home: klub}}: ne vraca se u klub iz kojeg je tek otisao,
    # povratak u bivsi klub (nakon 2+ sezone) i stariji igraci 'kuci' u maticni klub (prvi mladi klub koji postoji u igri)
    past = past or {}

    def _blocked(pid, ci):
        h = past.get(pid)
        return bool(h and ci in h.get('block', ()))

    def _ret(p, ci):
        h = past.get(p['pid'])
        if not h:
            return None
        if h.get('home') == ci and p['age'] >= 30:
            return 'home'
        if ci in h.get('back', ()):
            return 'back'
        return None
    clubs = load_clubs(save, rat, pos_of, my_idx)
    budget = {}
    for c in clubs.values():
        for p in c['players']:
            p['val'] = val_of(p['pid'], p['ovr'], p['age']) if val_of else 0
            p['fam'] = FAMILY.get(p['pos'], 'CM')
        top = sorted((p['val'] for p in c['players']), reverse=True)[:25]
        c['value'] = sum(top)
        budget[c['idx']] = c['value'] * (BUDGET_FRAC * scale + 0.01)
        try:
            b0 = struct.unpack_from('<I', save.d, 84 + 1680 * c['idx'] + 1600)[0]
            if 0 < b0 < 0xFFFFFFFF:
                budget[c['idx']] = b0 * 100 * max(scale, 0.35)
        except Exception:
            pass
    if window == 'W':
        for k in budget:
            budget[k] *= 0.5
    for k, f in (bmod or {}).items():
        if k in budget:
            budget[k] *= f
    budget0 = {k: int(v) for k, v in budget.items()}
    wres = {}
    if wage_of:
        for c in clubs.values():
            for p in c['players']:
                p['wage'] = wage_of(p['pid']) or 0
            wres[c['idx']] = SAL_RESERVE * 1.6 * sum(p['wage'] for p in c['players'])
    order = sorted(clubs.values(), key=lambda c: -c['strength'])
    nb = max(1, int(len(order) * 0.09))
    nm_ = int(len(order) * 0.49)
    ident = club_identities(clubs)
    for i, c in enumerate(order):
        c['tier'] = 'big' if i < nb else 'mid' if i < nm_ else 'small'
        c['ident'] = ident.get(c['idx'], 'normal')
        c['rank'] = i
        c['grp'] = owners.get(c['idx'])
    # zivo stanje momcadi (mijenja se kako se transferi planiraju)
    roster = {c['idx']: list(c['players']) for c in clubs.values()}

    _rk = {}

    def ranked(ci):
        r = _rk.get(ci)
        if r is None:
            r = _rk[ci] = sorted((p for p in roster[ci] if p['ovr']), key=lambda q: -q['ovr'])
        return r

    def prank(ci):
        k = ('p', ci)
        r = _rk.get(k)
        if r is None:
            r = _rk[k] = {q['pid']: i for i, q in enumerate(ranked(ci))}
        return r

    def fam_list(ci, f):
        # dugo ozlijedjeni (INJ_LONG+ dana) ne broje se kao raspolozivi igraci na poziciji
        return sorted((p['ovr'] for p in roster[ci] if p['fam'] == f and p['ovr'] and inj.get(p['pid'], 0) < INJ_LONG), reverse=True)

    def grp_cnt(ci, g):
        return sum(1 for p in roster[ci] if GROUP[p['pos']] == g)

    groups = {}
    for c in clubs.values():
        if c['grp']:
            groups.setdefault(c['grp'], []).append(c)
    for g, cl in groups.items():
        m = max(cl, key=lambda c: c['strength'])
        for c in cl:
            c['grp_main'] = (c is m)

    # broj dolazaka po klubu
    dist = SUMMER_DIST if window == 'S' else WINTER_DIST
    prev_in = {int(k): v for k, v in (memory.get('prev_in') or {}).items()}
    new_coach = set(int(x) for x in (memory.get('new_coach') or []))
    quota = {}
    for c in clubs.values():
        q = _pick_n(rnd, dist)
        L = len(roster[c['idx']])
        if L <= 23 and (window == 'S' or L <= 21):
            q += 1 + (L <= 21 and window == 'S')
        elif L >= 31:
            q = max(0, q - 1 - (L >= 33))
        if window == 'W' and prev_in.get(c['idx'], 0) >= 5:
            q = max(0, q - 1)
        if c['idx'] in new_coach:
            q += 1   # novi trener trazi svoje igrace
        # dio roka koji jos nije prosao: svaki dolazak ostaje s vjerojatnoscu 'scale'
        if scale < 0.999:
            q = sum(1 for _ in range(q) if rnd.random() < scale)
        quota[c['idx']] = q

    def need_fams(ci, purpose):
        c = clubs[ci]
        out = []
        for f, ideal in ideal_of(ci).items():
            lst = fam_list(ci, f)
            d = len(lst)
            w = 0.25
            w += max(0, ideal - d) * 2.2
            b1 = lst[0] if lst else c['strength'] - 10
            w += max(0, (c['strength'] - 1) - b1) / 2.5
            olds = [p for p in roster[ci] if p['fam'] == f and p['ovr'] == b1 and p['age'] >= 32]
            if olds:
                w += 0.8
            if d >= ideal + 2:
                w *= 0.2
            out.append((f, w))
        return out

    listed = listed or {}
    moved = set(protect_pids)
    sold, bought = {}, {}
    # pc353 (Alex): kadar prema formaciji kluba (novi trener s tri stopera trazi treceg stopera i bocne; 4-3-3 prava krila).
    # Iz plana igre kluba u saveu: svaka uloga u formaciji = 2 igraca te obitelji (titular + zamjena), ostale obitelji 1.
    _ideal = {}

    def ideal_of(ci):
        r = _ideal.get(ci)
        if r is None:
            r = dict(IDEAL)
            try:
                _lab, roles = save.club_formation(ci)
                if _lab and roles and len(roles) == 10:
                    cnt = {}
                    for x in roles:
                        f_ = FAMILY.get(x)
                        if f_:
                            cnt[f_] = cnt.get(f_, 0) + 1
                    r = {f_: (3 if f_ == 'GK' else min(5, 2 * cnt.get(f_, 0)) if cnt.get(f_) else 1) for f_ in IDEAL}
                    if cnt.get('CB', 0) >= 3:
                        r['CB'] = max(r['CB'], 5)
                    for f_ in ('LB', 'RB', 'LW', 'RW'):
                        if cnt.get(f_):
                            r[f_] = max(r[f_], 2)
            except Exception:
                pass
            _ideal[ci] = r
        return r

    def misfit(ci, p):
        """Igrac cija obitelj u formaciji kluba nema mjesta, a klub ih ima vise nego treba (npr. krila u 3-5-2)."""
        f_ = p['fam']
        if f_ == 'GK':
            return False
        idl = ideal_of(ci).get(f_, 2)
        return idl <= 1 and sum(1 for q in roster[ci] if q['fam'] == f_) > idl
    moves, wish_out = [], {}
    stars = 0
    sale_cap = 6 if window == 'S' else 3
    wish_in = {int(k): [int(x) for x in v] for k, v in (memory.get('wish') or {}).items()}
    where = {}
    for c in clubs.values():
        for p in c['players']:
            where[p['pid']] = c['idx']

    elite = {}   # kandidati za 'zelje' (meta malo iznad mogucnosti kluba)
    for c in order:
        for p in c['players']:
            if p['ovr'] and p['ovr'] >= 68 and p['age'] <= 29:
                elite.setdefault(p['fam'], []).append((c, p))

    def pool_for(b, f, lo, hi, why, max_age, group_only=False):
        bi = b['idx']
        cands = []
        for s in order:
            si = s['idx']
            if si == bi:
                continue
            if group_only and (not b['grp'] or s['grp'] != b['grp']):
                continue
            same_grp = bool(b['grp'] and s['grp'] == b['grp'])
            if sold.get(si, 0) >= sale_cap or len(roster[si]) <= MIN_SIZE:
                continue
            pos_rank = prank(si)
            stronger = s['strength'] > b['strength'] + 3
            for p in roster[si]:
                home_ = past and _ret(p, bi) == 'home'   # pc352: povratak kuci: malo blazi uvjeti (stariji, malo slabiji)
                if p['fam'] != f or p['pid'] in moved or not p['ovr'] or p['age'] > max_age + (3 if home_ else 0):
                    continue
                if past and _blocked(p['pid'], bi):
                    continue   # pc352: ne vraca se u klub iz kojeg je tek otisao
                if inj.get(p['pid'], 0) >= INJ_NOBUY:
                    continue   # pc198: klub ne kupuje igraca koji je ozlijedjen (lijecnicki pregled)
                if not (lo - (6 if home_ else 0)) <= p['ovr'] <= hi:
                    continue
                r_ = pos_rank.get(p['pid'], 99)
                lst = listed.get(p['pid'])
                is_listed = bool(lst and lst.get('kind') == 'transfer')
                mis_ = misfit(si, p)
                if stronger and not (r_ >= 16 or is_listed or (same_grp and p['age'] <= 23) or (mis_ and r_ >= 6)):
                    continue   # veci klub ne prodaje igraca koji mu igra (pc353: osim ako mu ne pase u formaciju)
                if r_ < 5 and b['strength'] < s['strength'] - 1 and not (lst and lst.get('reason') in ('wants_out', 'unhappy', 'contract')):
                    continue   # zvijezdu ne prodaje klub jaci od kupca
                if p['ovr'] >= 85 and (b['rank'] > 20 or stars >= 8):
                    continue
                if grp_cnt(si, GROUP[p['pos']]) - 1 < MIN_GROUP[GROUP[p['pos']]]:
                    continue
                if wage_of and p.get('wage', 0) > max(wres.get(bi, 0), 0) * (1.3 if why == 'replace' else 1.0):
                    continue
                free = (why == 'release' or (r_ >= 20 and not is_listed and (p['age'] >= 29 or (p['age'] >= 25 and p['ovr'] <= s['strength'] - 10))))
                price = 0 if free else (lst['ask'] if is_listed else p['val'])
                if same_grp:
                    price *= 0.7
                if val_of and price * 0.9 > budget.get(bi, 0):
                    continue
                cands.append((s, p, r_, free, is_listed, same_grp, price))
        return cands

    def do_move(b, s, p, fee, why, repl=None, after=None, grp=None, ctx=None):
        nonlocal stars
        bi, si = b['idx'], s['idx']
        if val_of:
            budget[bi] = budget.get(bi, 0) - fee
            budget[si] = budget.get(si, 0) + fee
        if wage_of:
            wres[bi] = wres.get(bi, 0) - p.get('wage', 0)
            wres[si] = wres.get(si, 0) + p.get('wage', 0)
        moved.add(p['pid'])
        sold[si] = sold.get(si, 0) + 1
        bought[bi] = bought.get(bi, 0) + 1
        roster[si] = [q for q in roster[si] if q['pid'] != p['pid']]
        roster[bi] = roster[bi] + [p]
        for k in (si, bi, ('p', si), ('p', bi)):
            _rk.pop(k, None)
        if p['ovr'] >= 85:
            stars += 1
        ctx = ctx or {}
        lst = listed.get(p['pid'])
        moves.append(dict(pid=p['pid'], name=names.get(p['pid'], str(p['pid'])), pos=POS_NAME.get(p['pos'], '?'), ovr=p['ovr'], age=p['age'],
                          from_idx=si, from_name=s['name'], to_idx=bi, to_name=b['name'], tier=b['tier'], fee=fee, wage=p.get('wage'),
                          from_tier=s['tier'], to_rank=b['rank'], from_rank=s['rank'],
                          best_here=ctx.get('b1'), second_here=ctx.get('b2'), short=bool(ctx.get('short')),
                          to_str=round(b['strength'], 1), from_str=round(s['strength'], 1),
                          reason=ctx.get('reason', ''), listed=bool(lst and lst.get('kind') == 'transfer'), list_reason=(lst or {}).get('reason'),
                          why=why, repl=repl, after=after, group=grp, free=(fee == 0), ident=b.get('ident', 'normal'), ret=ctx.get('ret')))
        return moves[-1]

    def fee_cap(bi):
        """pc398: najvise sto klub plati za jednog igraca: dio vrijednosti vlastite momcadi (veliki 40 %, srednji 30 %, mali 20 %),
        najmanje 1,5 mil. Prije je granica bila samo budzet (s prihodima od prodaja), pa su srednji klubovi kupovali zvijezde."""
        sv = sum(q.get('val', 0) or 0 for q in roster.get(bi) or [])
        k = {'big': 0.4, 'mid': 0.3, 'small': 0.2}.get(clubs[bi]['tier'], 0.3)
        return max(1500000, sv * k)

    def fee_of(b, s, p, free, is_listed, same_grp, urgent):
        if free or not val_of:
            return 0
        lst = listed.get(p['pid'])
        if is_listed:
            f = lst['ask'] * rnd.uniform(0.88, 1.0)
        else:
            f = p['val'] * rnd.uniform(0.85, 1.2)
            if b['strength'] > s['strength'] + 4:
                f *= rnd.uniform(1.0, 1.15)   # manji klub cijeni svog igraca
        if same_grp:
            f *= rnd.uniform(0.55, 0.8)
        if urgent:
            f *= rnd.uniform(1.0, 1.15)
        f = min(f, p['val'] * 1.45, max(budget.get(b['idx'], 0), 0))
        step = 100000 if f >= 1000000 else 10000
        return int(round(f / step) * step)

    def attempt(b, why, f=None, target=None, repl=None, after=None):
        """Jedan pokusaj kupnje; vraca potez ili None."""
        bi = b['idx']
        if len(roster[bi]) >= MAX_SIZE:
            return None
        base = b['strength']
        tier = b['tier']
        grp_only = (why == 'group')
        if f is None:
            needs = need_fams(bi, why)
            # najprije pozicije ispod minimuma grupe
            short = [g for g, v in MIN_GROUP.items() if grp_cnt(bi, g) < v]
            if short:
                needs = [(ff, w * (6 if GROUP_OF_FAM[ff] in short else 1)) for ff, w in needs]
            f = rnd.choices([x for x, _ in needs], [w for _, w in needs])[0]
        lstf = fam_list(bi, f)
        b1 = lstf[0] if lstf else None
        b2 = lstf[1] if len(lstf) > 1 else None
        gap = {'big': 8, 'mid': 6, 'small': 5}[tier]
        if why == 'replace' and target:
            lo, hi = target - 4, target + (4 if tier == 'big' else 3)
            sub = 'replace'
        elif b1 is None or b1 < base - 3:
            lo, hi = base - 4, base + gap
            sub = 'starter'
        elif rnd.random() < (0.55 if tier == 'big' else 0.4 if tier == 'mid' else 0.3):
            lo, hi = max(b1 + 1, base - 2), base + gap
            sub = 'starter'
        else:
            lo, hi = base - 8, max(base + 1, (b2 or base) + 2)
            sub = 'depth'
        if f == 'GK' and sub == 'depth':
            lo = base - 12
        if grp_only:
            lo -= 6
        max_age = 34 if tier == 'small' else 32 if tier == 'mid' else 31
        cands = pool_for(b, f, lo, hi, sub, max_age, grp_only)
        if not cands and sub != 'starter':
            cands = pool_for(b, f, lo - 4, hi, sub, max_age, grp_only)
        if reg and cands:
            # pc195: pravila registracije (Michele & Claude) i za AI klubove: lista 25, igraci izvan EU
            import regrules as _rr
            tb = reg['tid'].get(bi)
            if tb in _rr.RULES:
                nat, new0 = reg['nat'], reg['new']
                sq_ = [dict(pid=q['pid'], age=q['age'], nat=nat.get(q['pid']), new=(q['pid'] in new0 or q['pid'] in moved)) for q in roster[bi]]
                cands = [c_ for c_ in cands if not _rr.check(tb, sq_, dict(pid=c_[1]['pid'], age=c_[1]['age'], nat=nat.get(c_[1]['pid'])),
                                                              reg['tid'].get(c_[0]['idx']))]
        if b.get('ident', 'normal') != 'normal' and not grp_only and rnd.random() >= 0.2:
            # identitet kluba (Michele & Claude): slobodni igraci ne podlijezu pravilu
            cands = [c_ for c_ in cands if c_[3] or ident_ok(b['ident'], c_[1], base)]
        if not cands:
            return None
        tgt = target if target else ((lo + hi) / 2.0 if sub == 'starter' else (lo + hi) / 2.0 - 1)
        wl = wish_in.get(bi, [])
        wts = []
        for s, p, r_, free, is_listed, same_grp, price in cands:
            w = 1.0 / (1 + abs(p['ovr'] - tgt))
            w *= _age_w(tier, p['age'], 'release' if free else sub)
            if is_listed:
                w *= 5
            if r_ < 5 and not is_listed:
                w *= 0.3   # klub nerado pusta svog najboljeg
            if same_grp:
                w *= 6
            if p['pid'] in wl:
                w *= 12
            if free and tier == 'small':
                w *= 2.5
            if free and tier == 'big':
                w *= 0.15
            if tier == 'mid' and p['age'] <= 23 and p['ovr'] >= base - 3:
                w *= 1.6   # mladi s potencijalom (preprodaja)
            if len(roster[s['idx']]) >= 30:
                w *= 1.5   # klub s prevelikom momcadi prodaje
            if misfit(s['idx'], p) and r_ >= 4:
                w *= 3   # pc353: prodavac se rjesava igraca koji ne pase u njegovu formaciju
            rt_ = _ret(p, bi) if past else None
            if rt_ == 'home':
                w *= 15   # pc352: stari igrac se vraca u klub iz kojeg je nikao
            elif rt_ == 'back':
                w *= 4 if p['age'] >= 30 else 2
            wts.append(w)
        s, p, r_, free, is_listed, same_grp, price = rnd.choices(cands, wts)[0]
        if not free and val_of and p.get('val', 0) > fee_cap(bi):
            return None   # pc398: klub ne placa jednog igraca vise od svoje 'klase' (Cagliari 45 mil. za Souléa)
        # pamcenje: najjaca meta koju klub nije mogao platiti (veliki i srednji)
        if tier != 'small' and sub == 'starter' and val_of:
            best = None
            bud = max(budget.get(bi, 0), 1)
            for c2, q in elite.get(f, ()):
                if (q['pid'] not in moved and base + 1 <= q['ovr'] <= base + gap and bud < q['val'] <= 2.5 * bud
                        and c2['strength'] <= b['strength'] + 2 and c2['idx'] != bi and (lstf[0] if lstf else 0) < q['ovr']):
                    if best is None or q['ovr'] > best['ovr']:
                        best = q
            if best is not None and rnd.random() < 0.5:
                wish_out.setdefault(bi, [])
                if best['pid'] not in wish_out[bi] and len(wish_out[bi]) < 2:
                    wish_out[bi].append(best['pid'])
        fee = fee_of(b, s, p, free, is_listed, same_grp, why == 'replace')
        w_ = 'release' if free else ('wish' if p['pid'] in wl else ('group' if same_grp else (why if why == 'replace' else sub)))
        reason = {'replace': 'replacement for %s' % repl, 'starter': 'new starter at %s' % FAM_NAME[f], 'depth': 'squad depth at %s' % FAM_NAME[f],
                  'release': 'free transfer (released by %s)' % s['name'], 'wish': 'long-time target, second attempt',
                  'group': 'transfer within %s' % (b['grp'] or '')}[w_]
        rt_ = _ret(p, bi) if past else None
        if rt_ == 'home':
            reason = 'homecoming: back at the club where he came through the youth ranks'
        elif rt_ == 'back':
            reason = 'return to a former club'
        m = do_move(b, s, p, fee, w_, repl=repl, after=after, grp=(b['grp'] if same_grp else None),
                    ctx=dict(b1=b1, b2=b2, short=bool(grp_cnt(bi, GROUP_OF_FAM[f]) <= MIN_GROUP[GROUP_OF_FAM[f]]), reason=reason, ret=rt_))
        # prodavac je izgubio vaznog igraca -> zadatak zamjene
        if r_ < 12 and not free:
            queue.insert(min(len(queue), rnd.randint(0, 6)), dict(club=s['idx'], why='replace', f=p['fam'], target=p['ovr'], repl=m['name'], after=p['pid'], extra=True))
        return m

    def try_wish(b, pid):
        """Klub se vraca po igraca kojeg prosli put nije mogao platiti: vecom ponudom (do 1.5x budzeta), uspije otprilike svaki drugi put."""
        bi = b['idx']
        si = next((c for c in roster if any(q['pid'] == pid for q in roster[c])), None)
        if si is None or si == bi or pid in moved or len(roster[bi]) >= MAX_SIZE or _blocked(pid, bi):
            return None
        s = clubs[si]
        p = next(q for q in roster[si] if q['pid'] == pid)
        if len(roster[si]) <= MIN_SIZE or grp_cnt(si, GROUP[p['pos']]) - 1 < MIN_GROUP[GROUP[p['pos']]]:
            return None
        r_ = prank(si).get(pid, 99)
        if r_ < 5 and b['strength'] < s['strength'] - 1:
            return None
        fee = p['val'] * rnd.uniform(1.05, 1.3) if val_of else 0
        if val_of and (fee > max(budget.get(bi, 0), 0) * 1.5 or p.get('val', 0) > fee_cap(bi)):
            return None
        if rnd.random() < 0.45:
            return None
        if val_of:
            fee = int(round(fee / 100000.0) * 100000)
        lst = fam_list(bi, p['fam'])
        m = do_move(b, s, p, fee, 'wish', ctx=dict(b1=lst[0] if lst else None, b2=lst[1] if len(lst) > 1 else None,
                                                   reason='long-time target, they came back with a bigger offer'))
        if r_ < 16:
            queue.insert(min(len(queue), rnd.randint(0, 6)), dict(club=si, why='replace', f=p['fam'], target=p['ovr'], repl=m['name'], after=pid, extra=True))
        return m

    # red zadataka: najprije veliki klubovi (njihove kupnje pokrecu lance prodaja), pa svi ostali izmijesano
    queue = []
    rounds = max(quota.values() or [0])
    for r in range(rounds):
        layer = [c for c in order if quota[c['idx']] > r]
        rnd.shuffle(layer)
        layer.sort(key=lambda c: (0 if c['tier'] == 'big' else 1 if c['tier'] == 'mid' else 2) + rnd.random() * 1.6)
        queue += [dict(club=c['idx'], why='buy') for c in layer]
    # pc198: dugo ozlijedjen igrac iz prve postave -> klub trazi zamjenu (sto dulja ozljeda, to vjerojatnije)
    inj_need = 0
    if inj:
        for c in order:
            if c['idx'] == my_idx:
                continue
            pr = prank(c['idx'])
            for p in roster[c['idx']]:
                d = inj.get(p['pid'], 0)
                if d >= INJ_LONG and pr.get(p['pid'], 99) < 11 and p['ovr']:
                    ch = 0.85 if d >= 120 else 0.6 if d >= 75 else 0.35
                    if window == 'W':
                        ch = min(0.95, ch + 0.1)
                    if rnd.random() < ch * max(scale, 0.35):
                        inj_need += 1
                        queue.insert(rnd.randint(0, min(len(queue), 40)),
                                     dict(club=c['idx'], why='replace', f=p['fam'], target=p['ovr'], extra=True, inj=d,
                                          repl='%s (injured, out for about %d days)' % (names.get(p['pid'], str(p['pid'])), d)))
    # zelje iz proslog roka: probaj ponovno (na pocetku)
    for ci, pids in wish_in.items():
        if ci in clubs:
            for pid in pids:
                si = where.get(pid)
                if si is not None and si != ci:
                    p = next((q for q in roster[si] if q['pid'] == pid), None)
                    if p:
                        queue.insert(rnd.randint(0, min(len(queue), 50)), dict(club=ci, why='wish', pid=pid, extra=False))
    # vlasnicke grupe: sestrinski klubovi dobivaju igraca iz grupe
    for g, cl in groups.items():
        for c in cl:
            if not c.get('grp_main') and rnd.random() < (0.6 if window == 'S' else 0.25):
                queue.insert(rnd.randint(0, len(queue)), dict(club=c['idx'], why='group', extra=True))
    done_n = {}
    guard = 0
    while queue and guard < 20000:
        guard += 1
        t = queue.pop(0)
        ci = t['club']
        b = clubs[ci]
        if not t.get('extra') and done_n.get(ci, 0) >= quota.get(ci, 0) and t['why'] != 'wish':
            continue
        if t['why'] == 'replace' and rnd.random() < (0.15 if window == 'S' else 0.45):
            continue   # klub ne nadje zamjenu / promovira mladog
        m = None
        if t['why'] == 'wish':
            m = try_wish(b, t['pid'])
            if m:
                done_n[ci] = done_n.get(ci, 0) + 1
            continue
        for _ in range(3 if t['why'] == 'buy' else 2):
            m = attempt(b, 'replace' if t['why'] == 'replace' else ('group' if t['why'] == 'group' else 'buy'),
                        f=t.get('f'), target=t.get('target'), repl=t.get('repl'), after=t.get('after'))
            if m:
                break
        if m:
            done_n[ci] = done_n.get(ci, 0) + 1
            if t.get('inj'):
                m['inj_repl'] = t['inj']
    by = {}
    for m in moves:
        by[m['why']] = by.get(m['why'], 0) + 1
    stats = dict(clubs=len(clubs), moves=len(moves), big=sum(1 for m in moves if m['tier'] == 'big'),
                 mid=sum(1 for m in moves if m['tier'] == 'mid'), small=sum(1 for m in moves if m['tier'] == 'small'),
                 stars=stars, fees=sum((m.get('fee') or 0) for m in moves), budget0=budget0, why=by,
                 wish={str(k): v for k, v in wish_out.items()}, quota_total=sum(quota.values()), v=2,
                 ident={k: sum(1 for c in clubs.values() if c.get('ident') == k) for k in ('big', 'academy', 'experience')},
                 inj_need=inj_need, inj_moves=sum(1 for m in moves if m.get('inj_repl')), inj_known=len(inj))
    return moves, stats


GROUP_OF_FAM = {'GK': 'GK', 'CB': 'DF', 'LB': 'DF', 'RB': 'DF', 'DM': 'MF', 'CM': 'MF', 'AM': 'MF', 'LW': 'FW', 'RW': 'FW', 'ST': 'FW'}
