"""formengine.py - forma igraca iz stvarnih utakmica (ocjena, golovi, asistencije, primljeni golovi) + utjecaj pressa.
Rezultat je ciljna Form razina (0-7) po igracu; app je upisuje u igru preko GrowthBridge (op=set)."""

W = [1.0, 0.85, 0.7, 0.55, 0.4]      # tezine: najnovija utakmica najvise
LOOK = 6                              # promatra zadnjih 6 utakmica kluba, najvise 5 u kojima je igrac startao


def grp(pos):
    return 'gk' if pos == 0 else 'df' if pos in (1, 2, 3) else 'mf' if pos in (4, 5, 6, 7, 8) else 'fw'


def clamp(x, a, b):
    return max(a, min(b, x))


def compute(ms, my, pos_of):
    """ms: odigrane utakmice kluba (od najstarije), m['rows'] = (pid, club, g, a, rating).
    -> {pid: dict(level, f, why=[(kod, vrijednost)], n)}"""
    last = ms[-LOOK:]
    allr = [r[4] for m in last for r in m['rows'] if r[1] == my and r[4]]
    base = clamp(sum(allr) / len(allr), 6.0, 6.8) if allr else 6.4
    per = {}
    for m in last:
        mine = [r for r in m['rows'] if r[1] == my]
        gf = ((m['sc'] if m['home'] == my else m['sc'][::-1])[0] if m.get('sc') else sum(r[2] for r in mine))
        ga = ((m['sc'] if m['home'] == my else m['sc'][::-1])[1] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] != my))
        for pid, ci, g, a, r in mine:
            gr = grp(pos_of(pid))
            s = clamp((r or base) - base, -2.5, 2.5)
            s += {'fw': .5 * g + .25 * a, 'mf': .4 * g + .35 * a, 'df': .4 * g + .3 * a, 'gk': 0}[gr]
            if gr in ('df', 'gk'):
                k = 1.2 if gr == 'gk' else 1.0
                s += k * (.5 if ga == 0 else 0 if ga == 1 else -.3 if ga == 2 else -.7)
            if gr == 'fw' and not g and not a:
                s -= .25
            s += .15 if gf > ga else -.15 if gf < ga else 0
            per.setdefault(pid, []).append(dict(s=s, g=g, a=a, r=r, ga=ga))
    out = {}
    for pid, L in per.items():
        L = L[-5:][::-1]                       # najnovija prva
        sw = sum(W[i] for i in range(len(L)))
        f = sum(W[i] * x['s'] for i, x in enumerate(L)) / sw
        lvl = int(clamp(4 + round(f * 1.3), 1, 6))
        gr = grp(pos_of(pid))
        why = []
        avg = sum(x['r'] for x in L if x['r']) / max(1, sum(1 for x in L if x['r']))
        if avg:
            why.append(('rating', round(avg, 1)))
        if gr in ('df', 'gk'):
            conc = sum(x['ga'] for x in L[:3])
            if len(L) >= 2 and conc >= 5:
                why.append(('conceded', conc, min(3, len(L))))
            cs = sum(1 for x in L if x['ga'] == 0)
            if cs >= 2:
                why.append(('clean', cs, len(L)))
        if gr in ('fw', 'mf'):
            dry = 0
            for x in L:
                if x['g'] or x['a']:
                    break
                dry += 1
            if gr == 'fw' and dry >= 3:
                why.append(('dry', dry))
            gs = sum(x['g'] for x in L)
            if gs >= 3:
                why.append(('goals', gs, len(L)))
        out[pid] = dict(level=lvl, f=round(f, 2), why=why, n=len(L))
    return out


def with_bias(base, bias_v):
    return int(clamp(base + bias_v, 0, 7))
