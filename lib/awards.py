"""Nagrade iz odigranih utakmica: momcad kola (tjedna), Zlatna lopta, Golden Boy, Yashin i bonusi za trening.

Sve se racuna iz utakmica u saveu (ocjene, golovi, asistencije, primljeni golovi), deterministicno.
"""
import datetime

# ---------------------------------------------------------------- tjedan
def week_key(m):
    """(godina, tjedan) po ISO kalendaru za datum utakmice."""
    try:
        y, w, _ = datetime.date(m['y'], m['m'], m['dd']).isocalendar()
        return (y, w)
    except Exception:
        return (m['y'], 0)


def week_label(k):
    try:
        mon = datetime.date.fromisocalendar(k[0], k[1], 1)
        sun = mon + datetime.timedelta(days=6)
        return '%d.%d. – %d.%d.%d' % (mon.day, mon.month, sun.day, sun.month, sun.year)
    except Exception:
        return '%s/%s' % k


def week_end_ord(k):
    try:
        return datetime.date.fromisocalendar(k[0], k[1], 7).toordinal()
    except Exception:
        return 0


def grp(pos):
    return 'gk' if pos == 0 else 'cb' if pos == 1 else 'lb' if pos == 2 else 'rb' if pos == 3 else 'mf' if pos in (4, 5, 6, 7, 8) else 'fw'


def match_score(pos, g, a, r, conceded, won):
    """Ocjena nastupa za izbor momcadi kola."""
    if not r:
        return None
    s = r + {'fw': .45, 'mf': .4}.get(grp(pos), .35) * g + .25 * a
    if grp(pos) in ('gk', 'cb', 'lb', 'rb'):
        s += {0: .45, 1: .1}.get(conceded, -.15 if conceded == 2 else -.35) * (1.3 if pos == 0 else 1)
    s += .12 if won else 0
    return round(s, 2)


SHAPE = (('gk', 1), ('rb', 1), ('cb', 2), ('lb', 1), ('mf', 3), ('fw', 3))     # 4-3-3


def totw(ms, pos_of, info):
    """ms: utakmice tjedna jedne lige. -> dict(xi=[po redu formacije], potw, n)"""
    best = {}
    for m in ms:
        gh = (m['sc'][0] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] == m['home']))
        ga = (m['sc'][1] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] != m['home']))
        for pid, ci, g, a, r in m['rows']:
            home = ci == m['home']
            conc = ga if home else gh
            won = (gh > ga) if home else (ga > gh)
            sc = match_score(pos_of(pid), g, a, r, conc, won)
            if sc is None:
                continue
            e = best.get(pid)
            if not e or sc > e['sc']:
                best[pid] = dict(pid=pid, ci=ci, sc=sc, g=g, a=a, r=r, cs=conc == 0)
    pool = sorted(best.values(), key=lambda e: (-e['sc'], -e['r'], e['pid']))
    taken, xi = set(), []
    for slot, n in SHAPE:
        got = [e for e in pool if e['pid'] not in taken and grp(pos_of(e['pid'])) == slot][:n]
        if len(got) < n and slot in ('lb', 'rb', 'cb'):
            got += [e for e in pool if e['pid'] not in taken and e not in got and grp(pos_of(e['pid'])) in ('cb', 'lb', 'rb')][:n - len(got)]
        for e in got:
            taken.add(e['pid'])
            xi.append(dict(info(e['pid'], e['ci']), slot=slot, sc=e['sc'], g=e['g'], a=e['a'], r=round(e['r'], 1), cs=e['cs']))
    potw = max(xi, key=lambda e: e['sc']) if xi else None
    return dict(xi=xi, potw=potw, n=len(ms))


# ---------------------------------------------------------------- Zlatna lopta
def ballon(stats, league_w, club_bonus, pos_of, age_of, ovr_of):
    """stats: {pid: dict(app, g, a, rs, cs, ci, lg_apps={tid: n}, eu=n)}; league_w: {tid: tezina 0.5-1.25};
    club_bonus: {ci: bodovi uspjeha kluba}. -> sortirana lista dict(pid, pts, ...)"""
    out = []
    tot_r = sum(x['rs'] for x in stats.values())
    tot_n = sum(x['app'] for x in stats.values()) or 1
    base = max(5.8, min(6.8, tot_r / tot_n))
    for pid, x in stats.items():
        n = x['app']
        if n < 8:
            continue
        rating = x['rs'] / n
        pos = pos_of(pid)
        g = grp(pos)
        lw = 0.0
        tot = sum(x['lg_apps'].values()) or 1
        for t, k in x['lg_apps'].items():
            lw += league_w.get(t, 0.75) * k / tot
        if not x['lg_apps']:
            lw = 0.75
        ind = (rating - base) * 12 + x['g'] * (1.6 if g == 'fw' else 1.9 if g == 'mf' else 2.2) + x['a'] * 1.1
        if g in ('gk', 'cb', 'lb', 'rb'):
            ind += x['cs'] * (1.2 if pos == 0 else 0.7)
        ind += min(n, 50) * 0.35 + x.get('eu', 0) * 0.6
        pts = ind * lw + club_bonus.get(x['ci'], 0) + max(0, (ovr_of(pid) or 70) - 78) * 0.6
        if pos == 0:
            pts *= 0.72          # golmani rijetko osvajaju Zlatnu loptu
        out.append(dict(pid=pid, pts=round(pts, 1), app=n, g=x['g'], a=x['a'], cs=x['cs'], rating=round(rating, 2), ci=x['ci'],
                        age=age_of(pid), pos=pos))
    out.sort(key=lambda e: (-e['pts'], -e['rating'], e['pid']))
    return out


# ---------------------------------------------------------------- bonusi za trening
# bodovi atributa (razdijeljeni po ulozi pozicije) i moral (Affection)
BONUS = {
    'totw': (0.12, 2, 'Team of the Week'),
    'potw': (0.3, 4, 'Player of the Week'),
    'potm': (0.8, 8, 'Player of the Month'),
    'young': (0.6, 7, 'Young Player of the Month'),
    'gk': (0.6, 7, 'Goalkeeper of the Month'),
    'goal': (0.25, 5, 'Goal of the Month'),
    'pots': (1.5, 14, 'Player of the Season'),
    'young_season': (1.2, 12, 'Young Player of the Season'),
    'boot': (1.0, 10, 'Golden Boot'),
    'glove': (1.0, 10, 'Golden Glove'),
    'tots': (0.5, 6, 'Team of the Season'),
    'ballon': (2.0, 20, "Ballon d'Or"),
    'ballon_top3': (1.0, 12, "Ballon d'Or podium"),
    'ballon_top10': (0.5, 8, "Ballon d'Or top 10"),
    'golden_boy': (1.5, 16, 'Golden Boy'),
    'yashin': (1.2, 14, 'Yashin Trophy'),
}
POT_UP = {'golden_boy': 2, 'ballon': 1, 'young_season': 1}
