"""AI postave prema vaznosti utakmice.

Za sljedecu utakmicu svakog AI kluba procijeni vaznost (natjecanje, protivnik, polozaj na tablici, gust raspored)
i slozi prvih 11 iz cijelog sastava: u velikim utakmicama najjaci i igraci u formi, u nebitnima mladi i rezerve,
uz gust raspored odmor za umorne. Uloge u formaciji kluba (plan igre) se ne mijenjaju, samo tko ih igra.
"""
import random

EU_TIDS = (3, 5)


def importance(ctx):
    """ctx: dict(kind 'league'|'eu'|'cup', my_str, opp_str, pos, n, pts, leader_pts, safe_pts, progress 0-1,
    days_since, days_to_next, next_kind). -> (razina 'big'|'normal'|'low', rezultat, razlozi)"""
    s, why = 1.0, []
    k = ctx.get('kind')
    if k == 'eu':
        s += 0.45; why.append('europe')
    elif k == 'cup':
        s -= 0.25; why.append('cup')
    d = (ctx.get('opp_str') or 0) - (ctx.get('my_str') or 0)
    if d >= 7:
        s += 0.3; why.append('strong_opponent')
    elif d >= 4:
        s += 0.15; why.append('strong_opponent')
    elif d <= -6:
        s -= 0.3; why.append('weak_opponent')
    if k == 'league' and ctx.get('pos') and ctx.get('n'):
        pos, n, pr = ctx['pos'], ctx['n'], ctx.get('progress', 0)
        gap_top = (ctx.get('leader_pts') or 0) - (ctx.get('pts') or 0)
        gap_safe = (ctx.get('pts') or 0) - (ctx.get('safe_pts') or 0)
        if pos <= 3 and gap_top <= 6 and pr >= 0.4:
            s += 0.45; why.append('title_race')
        elif pos >= n - 3 and gap_safe <= 4 and pr >= 0.5:
            s += 0.3; why.append('relegation_fight')
        elif pr >= 0.8 and 6 <= pos <= n - 5 and gap_top > 12 and gap_safe > 10:
            s -= 0.45; why.append('nothing_to_play_for')
    if ctx.get('days_to_next') is not None and ctx['days_to_next'] <= 3 and ctx.get('next_kind') == 'eu' and k != 'eu':
        s -= 0.25; why.append('europe_next')
    lvl = 'big' if s >= 1.4 else 'low' if s <= 0.75 else 'normal'
    return lvl, round(s, 2), why


def pick_xi(roles, squad, dist, level, congested, seed, cur):
    """roles: [0] + 10 kodova uloga; squad: [dict(i, pid, pos, ovr, age, form, tired)]; cur: trenutnih 11 indeksa (izbor igre).
    Polazi od izbora igre (igra zna ozljede i kondiciju) i radi ogranicen broj zamjena:
    velika utakmica do 3 (samo bitno bolji), nebitna do 5 (mladi i rezerve, odmor zvijezdama), gust raspored do 2 (umorni).
    -> (xi indeksi po ulogama, klupa indeksi)"""
    rnd = random.Random(seed)
    by = {p['i']: p for p in squad}
    top = sorted(squad, key=lambda p: -p['ovr'])
    stars = {p['i'] for p in top[:3] if (p['age'] or 25) >= 27}
    regulars = {p['i'] for p in top[:11]}
    val = {}
    for p in squad:
        v = p['ovr'] + max(-2.0, min(2.0, (p.get('form') or 0) * 1.5))
        if congested and p.get('tired'):
            v -= 4 if level != 'big' else 1.5
        if level == 'low':
            if (p['age'] or 25) <= 21:
                v += 5
            elif (p['age'] or 25) <= 23:
                v += 2
            if p['i'] in stars:
                v -= 6
        v += rnd.uniform(-0.3, 0.3)
        val[p['i']] = v
    limit, need = {'big': (3, 3.0), 'low': (5, 0.8)}.get(level, (2, 2.0))
    xi = list(cur)
    used = set(xi)
    swaps = []
    for k, r in enumerate(roles):
        inc = by.get(xi[k])
        v_in = (val[inc['i']] - 2.2 * dist[r][inc['pos']]) if inc else -99
        best = None
        for p in squad:
            if p['i'] in used or dist[r][p['pos']] > (0 if r == 0 else 2):
                continue
            if level == 'low' and p['i'] in regulars and (p['age'] or 25) > 21:
                continue
            v = val[p['i']] - 2.2 * dist[r][p['pos']]
            if best is None or v > best[0]:
                best = (v, p['i'])
        if best and best[0] - v_in >= need:
            swaps.append((best[0] - v_in, k, best[1]))
    swaps.sort(reverse=True)
    for g, k, i in swaps:
        if len([1 for a, b in zip(xi, cur) if a != b]) >= limit:
            break
        if i in xi:
            continue
        xi[k] = i
    rest = [p for p in sorted(squad, key=lambda p: -val[p['i']]) if p['i'] not in xi]
    gks = [p['i'] for p in rest if p['pos'] == 0]
    bench = gks[:1] + [p['i'] for p in rest if p['i'] not in gks[:1]][:6]
    return xi, bench
