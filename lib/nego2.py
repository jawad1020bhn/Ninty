"""Pregovori v2 (dovodjenje): vrijeme u danima igre, dogadjaji izmedju rundi, agent i lijecnicki.

Sve je deterministicno iz (slot, igrac, runda), pa ponovno otvaranje ne daje drugi ishod.
Server odlucuje kad je odgovor dospio (datum igre); ovdje su samo pravila.
"""
import hashlib
import random


def rng(*parts):
    h = hashlib.md5('|'.join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(h[:12], 16))


# ---------------------------------------------------------------- vrijeme odgovora
def club_delay(slot, pid, rnd_no, mood, decision_hint=None):
    """Koliko dana klub ceka s odgovorom na ponudu. Eager klub brzo, tvrd klub razvlaci."""
    r = rng('cdelay', slot, pid, rnd_no)
    lo, hi = {'eager': (0, 1), 'balanced': (1, 2), 'hard': (1, 3)}.get(mood, (1, 2))
    if rnd_no >= 3:
        lo, hi = 0, max(1, hi - 1)   # kasne runde idu brze
    return r.randint(lo, hi)


def agent_delay(slot, pid, rnd_no, pmood):
    r = rng('adelay', slot, pid, rnd_no)
    return 0 if pmood == 'modest' else r.randint(0, 1)


# ---------------------------------------------------------------- dogadjaji (kad odgovor dospije)
def club_event(slot, pid, rnd_no, f, used, has_rival, seller_rank):
    """-> None ili kod dogadjaja: stall (klub sutí), coach_block (trener ne pusta), soften (klub popusta), rival (novi konkurent).
    used: skup vec iskoristenih dogadjaja (svaki najvise jednom)."""
    r = rng('cevent', slot, pid, rnd_no)
    x = r.random()
    opts = []
    if 'stall' not in used:
        opts.append(('stall', 0.09))
    if 'coach_block' not in used and seller_rank is not None and seller_rank < 5:
        opts.append(('coach_block', 0.07))
    if 'soften' not in used and ((f.get('months_left') is not None and f['months_left'] <= 12) or f.get('listed')):
        opts.append(('soften', 0.10))
    if 'rival' not in used and not has_rival and (f.get('ovr') or 0) >= 70:
        opts.append(('rival', 0.08))
    acc = 0.0
    for k, p in opts:
        acc += p
        if x < acc:
            return k
    return None


# razlozi (samo tekst u pregovoru, mehanika ista)
STALL_WHY = ('director_away', 'replacement', 'board', 'paperwork', 'owner_abroad', 'sale_first', 'coach_holiday', 'valuation')
BLOCK_WHY = ('coach', 'fans', 'captain', 'president', 'derby')
SOFT_WHY = ('player_push', 'finance', 'surplus', 'wage_bill', 'new_coach')


def stall_days(slot, pid, rnd_no):
    return rng('stall', slot, pid, rnd_no).randint(2, 4)


# ---------------------------------------------------------------- agent
def agent_ask(slot, pid, f, fee, free, money, wage):
    """Naknada agentu: postotak transfera (vise za pohlepne), za slobodnog igraca bonus za potpis (dio godisnje place)."""
    r = rng('agent', slot, pid)
    if free:
        a = wage * (0.25 + 0.5 * money) * r.uniform(0.9, 1.1)
    else:
        a = max(fee * (0.04 + 0.08 * money) * r.uniform(0.9, 1.15), min(150000, (f.get('mv') or 0) * 0.03))
    step = 10000 if a >= 100000 else 1000
    return max(step, int(round(a / step) * step))


def agent_haggle(slot, pid, loyalty):
    """Pokusaj spustiti naknadu agentu. -> ('cut', faktor) | ('firm', None) | ('offended', walks?)"""
    r = rng('haggle', slot, pid)
    x = r.random()
    if x < 0.55:
        return 'cut', round(r.uniform(0.55, 0.75), 2)
    if x < 0.85:
        return 'firm', None
    return 'offended', loyalty < 0.45


def agent_refused(slot, pid, loyalty, ambition):
    """Odbijes platiti agenta: igrac ga nadglasa (zeli doci) ili odlazi s njim."""
    r = rng('refuse_ag', slot, pid)
    p_stay = 0.25 + 0.35 * ambition * (1 - loyalty * 0.3)
    return r.random() < p_stay


# ---------------------------------------------------------------- lijecnicki
def medical(slot, pid, age, inj_low=False):
    """-> 'pass' | 'concern' | 'fail'. Stariji i igraci niske otpornosti na ozljede cesce imaju nalaz."""
    r = rng('med', slot, pid)
    fail = 0.015 + 0.012 * max(0, age - 30) + (0.02 if inj_low else 0)
    concern = 0.07 + 0.015 * max(0, age - 29) + (0.06 if inj_low else 0)
    x = r.random()
    if x < fail:
        return 'fail'
    if x < fail + concern:
        return 'concern'
    return 'pass'


def medical_discount(slot, pid):
    """Trazis nizu cijenu zbog nalaza: klub pristane (faktor) ili odbije."""
    r = rng('meddisc', slot, pid)
    if r.random() < 0.6:
        return round(r.uniform(0.82, 0.92), 2)
    return None
