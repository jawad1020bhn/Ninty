"""Pregovori o dovođenju igrača (klub -> igrač). Čista logika bez ulaza/izlaza osim JSON stanja.

Sve je deterministično: raspoloženje kluba i agenta računa se iz (slot, igrač, mjesec igre), pa
ponovno učitavanje ne daje drugu priliku. Tražena cijena/plaća se NIKAD ne šalje klijentu,
samo odgovor (prihvaća / protuponuda / odbija / odustaje) i naznaka "hladno-toplo".
"""
import jsafe  # pc251: sigurno spremanje JSON-a
import hashlib
import json
import math
import os
import random

CLUB_ROUNDS = 3
PLAYER_ROUNDS = 2
MOODS = ('eager', 'balanced', 'hard')
ROLES = ('key', 'starter', 'rotation', 'prospect')   # od najviše do najniže
LOCK_DAYS = 14

MV_BASE, MV_GROWTH = 4000, 1.31      # procjena trzisne vrijednosti kad nema dumpa
SAL_FROM_MV = 0.25


def _rng(*parts):
    h = hashlib.md5('|'.join(str(p) for p in parts).encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def rnd100(x, step=100):
    return int(round(x / step) * step)


def estimate_value(ovr, age):
    mv = MV_BASE * MV_GROWTH ** max(0, ovr - 50)
    if age >= 31:
        mv *= 0.8 ** ((age - 30) / 2)
    elif age <= 21 and ovr >= 60:
        mv *= 1.2
    return rnd100(mv, 1000)


# ---- pojas fer vrijednosti (pc194; ideja i dobna krivulja: Michele & Claude, "Sorvegliante dei Valori" / "Economia Lunga")
# fer = BAZA[ovr] (medijan vrijednosti igre za taj OVR, 24-27 god.) x DOB[age]; vrijednost iz igre se drzi u pojasu:
# strop = fer x margina(dob) (siroko za mlade, usko od 33 god.), pod do 30 god. = fer / 4. Ne mijenja save, samo cijene u appu.
_AGE_PTS = [(16, 3.0), (19, 2.6), (22, 2.0), (25, 1.0), (31, 0.45), (35, 0.2), (40, 0.08)]
VALUE_BASE = {}


def age_mult(age):
    a = max(16, min(40, age or 25))
    for (a0, m0), (a1, m1) in zip(_AGE_PTS, _AGE_PTS[1:]):
        if a0 <= a <= a1:
            return m0 + (m1 - m0) * (a - a0) / float(a1 - a0)
    return 1.0


def set_value_base(table):
    """table: {ovr: medijan vrijednosti 24-27 god.}; rupe se popune, krivulja je rastuca."""
    VALUE_BASE.clear()
    ks = sorted(o for o in table if 40 <= o <= 99)
    if len(ks) < 5:
        return
    for o in range(40, 100):
        if o in table:
            v = table[o]
        elif o < ks[0]:
            v = table[ks[0]] / MV_GROWTH ** (ks[0] - o)
        elif o > ks[-1]:
            v = table[ks[-1]] * MV_GROWTH ** (o - ks[-1])
        else:
            a = max(k for k in ks if k < o)
            b = min(k for k in ks if k > o)
            v = table[a] + (table[b] - table[a]) * (o - a) / float(b - a)
        VALUE_BASE[o] = v
    run = 0
    for o in range(40, 100):   # rastuca: medijan susjednih OVR-a ponekad padne
        run = max(run, VALUE_BASE[o])
        VALUE_BASE[o] = run


def fair_value(ovr, age):
    b = VALUE_BASE.get(int(ovr or 50)) or estimate_value(ovr or 50, 25)
    return b * age_mult(age)


def value_band(mv, ovr, age):
    """Vrijednost iz igre stisnuta u fer pojas (stari 'slavni' igraci nisu vise vrijedni desetke milijuna)."""
    if not mv or not ovr:
        return mv
    fv = fair_value(ovr, age)
    marg = 8.0 if age <= 21 else 5.0 if age <= 23 else 2.5 if age <= 28 else 1.8 if age <= 32 else 1.3   # mladi: vrijednost po potencijalu
    hi = fv * marg
    lo = fv / 4.0 if age <= 30 else 0
    return rnd100(min(max(mv, lo), hi), 1000)


def facts(ovr, age, mv, sal, months_left, listed):
    """Normalizira ulaz: ako nema zivih podataka, procijeni."""
    est = not mv
    if not mv:
        mv = estimate_value(ovr, age)
    elif VALUE_BASE:
        mv = value_band(mv, ovr, age)
    if not sal:
        sal = rnd100(mv * SAL_FROM_MV, 100)
    return dict(ovr=ovr, age=age, mv=mv, sal=sal, months_left=months_left, listed=bool(listed), est=est)


# ---------------------------------------------------------------- klub
BUY_K = 0.9    # pc165: kad ti kupujes, klub trazi ~90% vrijednosti (igra za Zirkzeea 25 M trazi 19,1 M, app je trazio 25 M)


def club_ask(f, mood, k=1.0):
    """Tražena naknada (ne šalje se klijentu)."""
    a = f['mv'] * k
    age = f['age']
    if age >= 31:
        a *= max(0.55, 1 - 0.07 * (age - 30))
    elif age <= 21 and f['ovr'] >= 62:
        a *= 1.15
    ml = f['months_left']
    if ml is not None:
        a *= 0.5 if ml <= 6 else 0.8 if ml <= 12 else 1.0
    if f['listed']:
        a *= 0.9
    a *= {'eager': 0.92, 'balanced': 1.0, 'hard': 1.12}[mood]
    return rnd100(a, 100)


def club_mood(slot, pid, month_key):
    r = _rng('club', slot, pid, month_key)
    x = r.random()
    return 'eager' if x < 0.25 else 'balanced' if x < 0.75 else 'hard'


def club_reply(f, mood, offer, rnd_no, budget_left=None):
    """-> dict(decision, counter, hint). decision: accept | counter | reject | walk."""
    ask = club_ask(f, mood, BUY_K)
    flex = {'eager': 0.12, 'balanced': 0.07, 'hard': 0.03}[mood]
    floor = ask * (1 - flex)
    ratio = offer / ask if ask else 9
    if offer >= ask:
        return dict(decision='accept', counter=offer, hint='hot')
    if ratio < 0.65:
        return dict(decision='walk', hint='cold')                # uvreda: klub prekida
    if offer >= floor:
        mid = rnd100(max(offer, (offer + ask) / 2), 1000 if ask > 20000 else 100)
        mid = min(mid, ask)
        return dict(decision='counter', counter=mid, hint='hot')
    if rnd_no >= CLUB_ROUNDS:
        return dict(decision='walk', hint='cold')
    hint = 'warm' if ratio >= 0.8 else 'cold'
    return dict(decision='reject', hint=hint)


def loan_reply(ask, fee, buy, mood, rnd_no):
    """Pregovor o posudbi (igrac dolazi k meni): ask = dict(fee, buy) (buy 0 = bez opcije otkupa). Vrijednost = naknada + 30% cijene otkupa.
    -> dict(decision, counter=dict(fee,buy)|None, hint)."""
    ask_v = ask['fee'] + 0.3 * ask['buy']
    off_v = fee + 0.3 * buy
    flex = {'eager': 0.12, 'balanced': 0.07, 'hard': 0.03}[mood]
    ratio = off_v / ask_v if ask_v else 9
    if off_v >= ask_v:
        return dict(decision='accept', counter=None, hint='hot')
    if ratio < 0.65:
        return dict(decision='walk', hint='cold')
    if off_v >= ask_v * (1 - flex):
        st = 1000 if ask['fee'] > 20000 else 100
        cf = min(ask['fee'], rnd100(max(fee, (fee + ask['fee']) / 2), st))
        cb = min(ask['buy'], rnd100(max(buy, (buy + ask['buy']) / 2), 1000)) if ask['buy'] else 0
        return dict(decision='counter', counter=dict(fee=cf, buy=cb), hint='hot')
    if rnd_no >= CLUB_ROUNDS:
        return dict(decision='walk', hint='cold')
    return dict(decision='reject', hint='warm' if ratio >= 0.8 else 'cold')


# ---------------------------------------------------------------- igrač
def squad_rank(my_ovrs, ovr):
    """Koliko igrača u tvojoj momčadi (prvih 11 po OVR-u) je bolje od njega."""
    top = sorted(my_ovrs, reverse=True)[:11]
    return sum(1 for o in top if o > ovr)


def role_demand(my_ovrs, f):
    rk = squad_rank(my_ovrs, f['ovr'])
    if rk <= 2:
        return 'key'
    if rk <= 10:
        return 'starter'
    return 'prospect' if f['age'] <= 21 else 'rotation'


def player_mood(slot, pid, month_key):
    r = _rng('agent', slot, pid, month_key)
    x = r.random()
    return 'modest' if x < 0.25 else 'normal' if x < 0.75 else 'greedy'


def wage_ask(f, mood, my_ovrs, role, years, premium=1.0):
    # pc165: blize igri (Zirkzee: placa 2,88 M, igra nudi 2,28 M, app je trazio 3,75 M) -> otprilike sadasnja placa
    base = max(f['sal'] * 1.0, f['mv'] * 0.09)
    base *= {'modest': 0.93, 'normal': 1.03, 'greedy': 1.15}[mood]
    dem = role_demand(my_ovrs, f)
    di, ri = ROLES.index(dem), ROLES.index(role)
    if ri <= di:
        base *= 0.93 if ri < di else 1.0      # obecana veca uloga snizuje trazenje
    else:
        base *= 1 + 0.08 * (ri - di)          # obecana manja uloga od zasluzene: skuplje
    if f['age'] >= 31:
        base *= 1 + 0.04 * max(0, years - 2)  # stariji igrac trazi vise za duze ugovore
    elif f['age'] <= 22:
        base *= 1 - 0.02 * max(0, years - 3)  # mladi voli dugorocnu sigurnost
    return rnd100(base * premium, 100)


def player_reply(f, mood, my_ovrs, offer, years, role, rnd_no, premium=1.0):
    ask = wage_ask(f, mood, my_ovrs, role, years, premium)
    ratio = offer / ask if ask else 9
    if offer >= ask:
        return dict(decision='accept', counter=offer, hint='hot')
    if ratio >= 0.9:
        return dict(decision='counter', counter=min(ask, rnd100((offer + ask) / 2, 100)), hint='hot')
    if rnd_no >= PLAYER_ROUNDS or ratio < 0.6:
        return dict(decision='walk', hint='cold')
    return dict(decision='reject', hint='warm' if ratio >= 0.75 else 'cold')


# ---------------------------------------------------------------- prodaja (kupac -> ti)
SELL_ROUNDS = 3
SELL_P_ROUNDS = 3
BUYER_F = {'eager': 1.05, 'balanced': 1.0, 'hard': 0.96}
BONUS_MAX = 15.0


def buyer_mood(slot, pid, off, mk):
    x = _rng('sellmood', slot, pid, off, mk).random()
    return 'eager' if x < 0.25 else 'balanced' if x < 0.75 else 'hard'


def seller_player_mood(slot, pid, off, mk):
    x = _rng('sellp', slot, pid, off, mk).random()
    return 'modest' if x < 0.25 else 'normal' if x < 0.75 else 'greedy'


def buyer_reply(ceil, mood, cur, want, rnd_no):
    """Klub kupac odgovara na tvoju traženu cijenu. -> dict(decision accept|counter|reject|walk, counter, hint)."""
    eff = ceil * BUYER_F[mood]
    if want <= eff:
        return dict(decision='accept', counter=want, hint='hot')
    ratio = want / eff if eff else 9
    last = rnd_no >= SELL_ROUNDS
    if ratio > 1.35:
        return dict(decision='walk', hint='cold')
    if ratio <= 1.08:
        k = {'eager': 0.8, 'balanced': 0.65, 'hard': 0.5}[mood]
        mid = rnd100(cur + (min(eff, want) - cur) * k, 100)
        mid = min(mid, rnd100(eff, 100))
        if mid > cur and not (last and ratio > 1.04):
            return dict(decision='counter', counter=mid, hint='hot')
        if last:
            return dict(decision='walk', hint='cold')
        return dict(decision='reject', hint='warm')
    if last:
        return dict(decision='walk', hint='cold')
    if ratio <= 1.2:
        return dict(decision='reject', hint='warm')
    if rnd_no >= 2:
        return dict(decision='walk', hint='cold')
    return dict(decision='reject', hint='cold')


def bonus_ask(score, tr, pmood):
    """Koliki dio naknade (%) igrač traži za pristanak na nezgodan odlazak (ne šalje se klijentu)."""
    base = 2.0 + max(0.0, -0.12 - score) * 22 + tr['money'] * 5
    base *= {'modest': 0.8, 'normal': 1.0, 'greedy': 1.3}[pmood]
    return round(min(BONUS_MAX, max(1.5, base)) * 2) / 2


def bonus_reply(ask, pct, rnd_no):
    if pct >= ask:
        return dict(decision='accept', counter=pct, hint='hot')
    if pct >= 0.7 * ask:
        return dict(decision='counter', counter=min(ask, round((pct + ask) / 2 * 2) / 2), hint='hot')
    if rnd_no >= SELL_P_ROUNDS:
        return dict(decision='walk', hint='cold')
    return dict(decision='reject', hint='warm' if pct >= 0.55 * ask else 'cold')


# ---------------------------------------------------------------- stanje
class Store:
    def __init__(self, path):
        self.path = path
        try:
            self.d = json.load(open(path, encoding='utf-8'))
        except Exception:
            self.d = {}

    @staticmethod
    def key(slot, pid):
        return '%s:%d' % (slot, pid)

    def get(self, slot, pid):
        return self.d.get(self.key(slot, pid))

    def put(self, slot, pid, rec):
        self.d[self.key(slot, pid)] = rec
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        jsafe.jdump(self.d, self.path, ensure_ascii=False, indent=1)

    def drop(self, slot, pid):
        self.d.pop(self.key(slot, pid), None)
        jsafe.jdump(self.d, self.path, ensure_ascii=False, indent=1)

    def for_slot(self, slot):
        pre = slot + ':'
        return {int(k.split(':')[1]): v for k, v in self.d.items() if k.startswith(pre)}
