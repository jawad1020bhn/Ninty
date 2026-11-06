"""Osobnost igraca i njegova procjena ponude (faza 1 dubinskih transfera). Cista logika, deterministicna iz ID-a igraca.

traits(pid)  -> ambicija, lojalnost, ego (zeli igrati), novac: stalne vrijednosti 0..1.
appeal(...)  -> koliko mu je ponuda privlacna: score (-1..1) + razlozi (sifre) koje UI prevodi.
"""
import hashlib
import random

REFUSE = -0.42      # ispod toga igrac odbija dolazak bez obzira na placu
RELUCTANT = -0.12   # ispod toga trazi doplatu za nezgodnu odluku
ROLES = ('key', 'starter', 'rotation', 'prospect')


def _rng(*parts):
    h = hashlib.md5('|'.join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def traits(pid):
    r = _rng('persona', pid)
    return dict(ambition=round(r.random(), 3), loyalty=round(r.random(), 3), ego=round(r.random(), 3), money=round(r.random(), 3))


def squad_rank(my_ovrs, ovr):
    return sum(1 for o in sorted(my_ovrs, reverse=True)[:11] if o > ovr)


def demanded_role(rk, age):
    if rk <= 2:
        return 'key'
    if rk <= 10:
        return 'starter'
    return 'prospect' if age <= 21 else 'rotation'


def appeal(f, tr, my_ovrs, cur_strength, my_strength, role, crowd=0):
    """f: facts (ovr, age, months_left); role: obecana uloga. -> dict(score, neg=[sifre], pos=[sifre], rk, dem)."""
    rk = squad_rank(my_ovrs, f['ovr'])
    dem = demanded_role(rk, f['age'])
    parts = []
    # minute igranja (vazno egoistima)
    base = {'key': 0.6, 'starter': 0.3, 'rotation': -0.3, 'prospect': -0.1}[dem]
    if dem == 'prospect' or f['age'] <= 21:
        base = max(base, -0.05)
    parts.append(('minutes' if base < 0 else 'minutes_ok', base * (0.5 + tr['ego'])))
    # korak naprijed / unatrag
    if cur_strength is not None and my_strength is not None:
        delta = my_strength - cur_strength
        step = max(-1.0, min(1.0, delta / 6.0)) * (0.5 + tr['ambition']) * 0.6
        parts.append(('step_up' if step > 0 else 'step_down', step))
    # lojalnost postojecem klubu (dug ugovor)
    ml = f.get('months_left')
    if ml is not None and ml > 24:
        parts.append(('loyal', -(tr['loyalty'] - 0.4) * 0.5 if tr['loyalty'] > 0.4 else 0.0))
    # prenatrpana pozicija: ima dovoljno boljih na njegovom mjestu; obecana uloga (starter/key) to djelomicno ublazi
    if crowd:
        parts.append(('crowded', -(0.22 + 0.12 * min(crowd, 2)) * (0.5 + tr['ego'])))
    # obecana uloga
    if role in ROLES and ROLES.index(role) < ROLES.index(dem):
        parts.append(('role_promise', 0.12))
    if crowd and role in ('key', 'starter'):
        parts.append(('role_promise', 0.30 if role == 'starter' else 0.42))
    score = sum(v for _, v in parts)
    neg = [k for k, v in sorted(parts, key=lambda x: x[1]) if v < -0.05]
    pos = [k for k, v in sorted(parts, key=lambda x: -x[1]) if v > 0.05]
    return dict(score=round(score, 3), neg=neg, pos=pos, rk=rk, dem=dem)


def premium(score):
    """Doplata (mnozitelj place) za nezgodnu odluku."""
    return 1.0 + max(0.0, RELUCTANT - score) * 0.9 if score < RELUCTANT else 1.0


def interest(score):
    return 'high' if score >= 0.2 else 'mid' if score >= RELUCTANT else 'low' if score >= REFUSE else 'none'


def wants_clause(tr):
    return tr['ambition'] > 0.65 and tr['loyalty'] < 0.4


def changed_mind(rec_dem, now_dem, tr):
    """Igrac se predomislio ako je mjesto u momcadi znatno slabije nego kad je pristao (dovedena konkurencija)."""
    if rec_dem not in ROLES or now_dem not in ROLES:
        return False
    return ROLES.index(now_dem) - ROLES.index(rec_dem) >= 1 and tr['ego'] >= 0.35


def exit_view(f, tr, my_str, buyer_str, listed, rk=None, wage=0, wage_offer=0):
    """Hoce li igrac napustiti tvoj klub za kupca? Odlucuju: korak naprijed/nazad, MINUTE (klupa kod tebe -> prva postava kod kupca),
    PLACA (nudi vise), lojalnost. -> dict(score, status: willing|reluctant|refuses, why=[sifre protiv], pro=[sifre za])."""
    parts = []
    if my_str is not None and buyer_str is not None:
        d = buyer_str - my_str
        step = max(-1.0, min(1.0, d / 6.0)) * (0.5 + tr['ambition']) * 0.5
        parts.append(('step_up' if step > 0 else 'step_down', step))
        bench_here = (rk is not None and rk >= 11) or (rk is None and f['ovr'] < my_str - 3)
        plays_there = f['ovr'] >= buyer_str - 3
        if not bench_here and not plays_there:
            parts.append(('minutes', -0.35 * (0.5 + tr['ego'])))
        elif bench_here and plays_there:
            parts.append(('minutes_ok', 0.5 * (0.5 + tr['ego'])))
    if wage and wage_offer:
        g = wage_offer / wage - 1.0
        parts.append(('wage_up' if g > 0 else 'wage_down', max(-0.1, min(0.6, g)) * (0.4 + tr['money'])))
    ml = f.get('months_left')
    if ml is not None and ml > 24 and tr['loyalty'] > 0.4:
        parts.append(('loyal', -(tr['loyalty'] - 0.4) * 0.5))
    if listed:
        parts.append(('listed', 0.2))
    score = round(sum(v for _, v in parts), 3)
    why = [k for k, v in sorted(parts, key=lambda x: x[1]) if v < -0.05][:2]
    pro = [k for k, v in sorted(parts, key=lambda x: -x[1]) if v > 0.05 and k in ('minutes_ok', 'wage_up', 'step_up')][:2]
    st = 'refuses' if score < REFUSE else 'reluctant' if score < RELUCTANT else 'willing'
    return dict(score=score, status=st, why=why, pro=pro)
