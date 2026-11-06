"""growth.py - plan mjesecnog rasta atributa i red naredbi za Sider modul GrowthBridge.lua."""
import jsafe  # pc251: sigurno spremanje JSON-a
import os, struct, json, time, random

# polje: (off, shift, len)  - isto kao u GrowthBridge.lua
FIELDS = {
    'OffensiveAwareness': (0x03, 0, 7), 'BallControl': (0x06, 5, 7), 'Dribbling': (0x05, 6, 7),
    'TightPossession': (0x08, 0, 7), 'Finishing': (0x08, 7, 7), 'LowPass': (0x09, 6, 7),
    'LoftedPass': (0x0A, 5, 7), 'Heading': (0x0C, 0, 7), 'PlaceKicking': (0x0E, 5, 7), 'Curl': (0x10, 0, 7),
    'Speed': (0x14, 7, 7), 'Acceleration': (0x18, 7, 7), 'KickingPower': (0x18, 0, 7), 'Jump': (0x19, 6, 7),
    'PhysicalContact': (0x15, 6, 7), 'Balance': (0x16, 5, 7), 'Stamina': (0x1A, 5, 7),
    'DefensiveAwareness': (0x04, 0, 7), 'BallWinning': (0x0C, 7, 7), 'Aggression': (0x0D, 6, 7),
    'GKAwareness': (0x04, 7, 7), 'GKCatching': (0x10, 7, 7), 'GKClearing': (0x11, 6, 7),
    'GKReflexes': (0x12, 5, 7), 'GKReach': (0x14, 0, 7),
}
FOCI = {
    'auto': None,
    'napad': ['Finishing', 'OffensiveAwareness', 'Curl', 'Dribbling'],
    'tehnika': ['BallControl', 'Dribbling', 'LowPass', 'LoftedPass', 'TightPossession'],
    'fizika': ['Speed', 'Acceleration', 'Stamina', 'PhysicalContact', 'Jump', 'Balance'],
    'obrana': ['DefensiveAwareness', 'BallWinning', 'Aggression', 'Heading'],
    'golman': ['GKAwareness', 'GKCatching', 'GKClearing', 'GKReflexes', 'GKReach'],
}
BY_POS = {0: 'golman', 1: 'obrana', 2: 'obrana', 3: 'obrana', 4: 'obrana', 5: 'tehnika', 6: 'tehnika', 7: 'tehnika', 8: 'tehnika',
          9: 'napad', 10: 'napad', 11: 'napad', 12: 'napad'}
DECLINE = ['Speed', 'Acceleration', 'Stamina', 'Jump', 'Balance']
BLOCK = 380


def attrs_from_block(b):
    out = {}
    for k, (off, sh, ln) in FIELDS.items():
        v = struct.unpack_from('<I', b, off)[0]
        out[k] = (v >> sh) & ((1 << ln) - 1)
    return out


_MP = ((0, 0), (40, 15), (50, 30), (70, 55), (100, 100))   # moral u igri (0-100) -> postotak u appu


def aff_of(b):
    """pc287: moral igraca iz bloka dumpa. U igri je to 7 bitova od +0x13E bit 2 (0-100; bitovi 0-1 su drugo), ne cijeli bajt
    (prije: bajt/2.55, pa je npr. 55 u igri ispalo 86 % "Happy", a 84 je ispalo 32 %). Vraca se na staroj skali appa 0-255
    (svi pragovi u appu ostaju): igra 40 -> 15 %, 50 -> 30 %, 70 -> 55 % (Happy od tud), 100 -> 100 %. Pocetak karijere u igri = 55-60."""
    g = (struct.unpack_from('<H', b, 0x13E)[0] >> 2) & 0x7F
    g = min(g, 100)
    for (g0, p0), (g1, p1) in zip(_MP, _MP[1:]):
        if g <= g1:
            return int(round((p0 + (g - g0) / (g1 - g0) * (p1 - p0)) * 2.55))
    return 255


def read_live(dump_path, pids):
    """{pid: dict(attrs, form, aff, inj)} iz zivog dumpa."""
    if not dump_path or not os.path.exists(dump_path):
        return {}
    want = set(pids)
    d = open(dump_path, 'rb').read()
    out = {}
    for i in range(len(d) // BLOCK):
        b = d[i * BLOCK:(i + 1) * BLOCK]
        pid = struct.unpack_from('<I', b, 0x30)[0]
        if pid in want:
            out[pid] = dict(attrs=attrs_from_block(b), form=(b[0x17] >> 4) & 7, aff=aff_of(b), inj=b[0x148])  # 0x148 = dani ozljede (potvrdjeno: M. Cunha 1 tjedan = 7)
    return out


# ---------------------------------------------------------------- FM -> PES
# Tablica pretvorbe: FM atribut -> {PES atribut: udio}. Popisi atributa po treningu preuzeti iz FM26 (training.fmf).
FM2PES = {
    'Finishing': {'Finishing': 1}, 'Crossing': {'LoftedPass': .6, 'Curl': .4}, 'Dribbling': {'Dribbling': 1},
    'First Touch': {'BallControl': 1}, 'Passing': {'LowPass': .6, 'LoftedPass': .4}, 'Technique': {'BallControl': .5, 'TightPossession': .5},
    'Long Shots': {'Finishing': .4, 'Curl': .3, 'KickingPower': .3}, 'Heading': {'Heading': 1}, 'Composure': {'TightPossession': .5, 'Finishing': .5},
    'Off The Ball': {'OffensiveAwareness': 1}, 'Vision': {'LowPass': .5, 'LoftedPass': .5}, 'Flair': {'Dribbling': .5, 'Curl': .5},
    'Anticipation': {'DefensiveAwareness': .5, 'OffensiveAwareness': .5}, 'Decisions': {'OffensiveAwareness': .5, 'DefensiveAwareness': .5},
    'Positioning': {'DefensiveAwareness': .7, 'OffensiveAwareness': .3}, 'Marking': {'DefensiveAwareness': 1}, 'Tackling': {'BallWinning': 1}, 'Aggression': {'Aggression': 1},
    'Concentration': {'DefensiveAwareness': .5}, 'Teamwork': {'OffensiveAwareness': .5, 'DefensiveAwareness': .5}, 'Work Rate': {'Stamina': 1},
    'Acceleration': {'Acceleration': 1}, 'Pace': {'Speed': .6, 'Acceleration': .4}, 'Agility': {'Balance': .5, 'Dribbling': .5}, 'Balance': {'Balance': 1},
    'Jumping Reach': {'Jump': 1}, 'Natural Fitness': {'Stamina': 1}, 'Stamina': {'Stamina': 1}, 'Strength': {'PhysicalContact': 1},
    'Aerial Reach': {'GKReach': .6, 'Jump': .4}, 'Command Of Area': {'GKAwareness': .5, 'GKReach': .5}, 'Communication': {'GKAwareness': 1},
    'Handling': {'GKCatching': 1}, 'Kicking': {'GKClearing': .7, 'KickingPower': .3}, 'One On Ones': {'GKReflexes': .5, 'GKAwareness': .5},
    'Reflexes': {'GKReflexes': 1}, 'Rushing Out': {'GKReach': 1}, 'Throwing': {'GKClearing': 1},
    'Free Kick Taking': {'PlaceKicking': 1}, 'Corners': {'Curl': .5, 'LoftedPass': .5}, 'Penalty Taking': {'PlaceKicking': 1},
}
# FM treninzi: (primarni atributi, sekundarni) - iz FM26
FM_SESS = {
    'Team Attacking': (['Crossing', 'Dribbling', 'Finishing', 'First Touch', 'Heading', 'Long Shots', 'Passing', 'Technique', 'Composure', 'Flair', 'Off The Ball', 'Vision'],
                       ['Marking', 'Tackling', 'Aggression', 'Anticipation', 'Concentration', 'Decisions', 'Positioning', 'Teamwork', 'Work Rate']),
    'Team Possession': (['Dribbling', 'First Touch', 'Passing', 'Technique', 'Anticipation', 'Composure', 'Decisions', 'Off The Ball', 'Teamwork', 'Vision'], ['Marking', 'Tackling', 'Positioning']),
    'Team Defending': (['Heading', 'Marking', 'Tackling', 'Aggression', 'Anticipation', 'Concentration', 'Decisions', 'Positioning', 'Teamwork', 'Work Rate'], ['Dribbling', 'Finishing', 'Passing']),
    'Team Tactical': (['Anticipation', 'Composure', 'Concentration', 'Decisions', 'Off The Ball', 'Positioning', 'Teamwork', 'Vision'], []),
    'Team Physical': (['Acceleration', 'Agility', 'Balance', 'Jumping Reach', 'Natural Fitness', 'Pace', 'Stamina', 'Strength', 'Work Rate'], []),
    'Team Goalkeeping': (['Aerial Reach', 'Agility', 'Anticipation', 'Command Of Area', 'Communication', 'Concentration', 'Decisions', 'Handling', 'Kicking', 'One On Ones', 'Positioning', 'Reflexes', 'Rushing Out', 'Throwing'], []),
    'Team Outfield': (['Aggression', 'Anticipation', 'Composure', 'Concentration', 'Crossing', 'Decisions', 'Dribbling', 'Finishing', 'First Touch', 'Flair', 'Heading', 'Long Shots', 'Marking', 'Off The Ball', 'Passing', 'Positioning', 'Tackling', 'Teamwork', 'Technique', 'Vision', 'Work Rate'], []),
    'Unit Attacking Direct': (['Dribbling', 'Finishing', 'First Touch', 'Long Shots', 'Passing', 'Technique', 'Anticipation', 'Off The Ball', 'Vision'], []),
    'Unit Attacking Patient': (['Finishing', 'First Touch', 'Passing', 'Technique', 'Composure', 'Decisions', 'Flair', 'Off The Ball', 'Vision', 'Teamwork'], []),
    'Unit Attacking Wings': (['Anticipation', 'Crossing', 'Dribbling', 'Finishing', 'Heading', 'Off The Ball', 'Technique'], []),
    'Unit Technical Chance Creation': (['Crossing', 'Passing', 'Technique', 'Decisions', 'Flair', 'Off The Ball', 'Vision'], []),
    'Unit Technical Play From the Back': (['Dribbling', 'First Touch', 'Passing', 'Composure', 'Flair', 'Vision', 'Teamwork'], []),
    'Set Pieces': (['Free Kick Taking', 'Corners', 'Penalty Taking', 'Long Shots', 'Heading'], []),
    'Physical Endurance': (['Stamina', 'Natural Fitness', 'Work Rate'], []),
}
# plan treninga -> koje FM treninge sadrzi
PLANS = {
    'attack': ['Team Attacking'], 'finishing': ['Unit Attacking Direct', 'Unit Attacking Patient', 'Unit Attacking Wings'],
    'possession': ['Team Possession'], 'technical': ['Unit Technical Chance Creation', 'Unit Technical Play From the Back'],
    'defending': ['Team Defending'], 'tactical': ['Team Tactical'], 'physical': ['Team Physical'],
    'set_pieces': ['Set Pieces'], 'goalkeeping': ['Team Goalkeeping'], 'overall': ['Team Outfield'], 'fitness': ['Physical Endurance'],
}
PLAN_NAMES = {'attack': ('Napad', 'Attacking'), 'finishing': ('Zaključivanje', 'Finishing'), 'possession': ('Posjed lopte', 'Possession'),
              'technical': ('Tehnika', 'Technical'), 'defending': ('Obrana', 'Defending'), 'tactical': ('Taktika', 'Tactical'),
              'physical': ('Fizička priprema', 'Physical'), 'set_pieces': ('Stajalice', 'Set pieces'), 'goalkeeping': ('Golman', 'Goalkeeping'),
              'overall': ('Opći trening', 'General'), 'fitness': ('Kondicija', 'Fitness')}
_GK_ATTRS = {'GKAwareness', 'GKCatching', 'GKClearing', 'GKReflexes', 'GKReach'}


PLAN_BOOST = {'finishing': {'Finishing': 2.2}, 'attack': {'Finishing': 1.5}, 'possession': {'LowPass': 1.5, 'BallControl': 1.3},
              'defending': {'BallWinning': 1.6}, 'goalkeeping': {'GKReflexes': 1.5, 'GKCatching': 1.4}}


def _build_plans():
    out = {}
    for pk, sess in PLANS.items():
        w = {}
        for sn in sess:
            pri, sec = FM_SESS[sn]
            for lst, k in ((pri, 1.0), (sec, 0.15)):
                for fa in lst:
                    for pa, sh in FM2PES.get(fa, {}).items():
                        w[pa] = w.get(pa, 0) + k * sh
        for a, m in PLAN_BOOST.get(pk, {}).items():
            if a in w: w[a] *= m
        tot = sum(w.values()) or 1.0
        out[pk] = {a: round(x / tot * 12.0, 3) for a, x in w.items()}
    return out


GROUPS = _build_plans()
GROUP_NAMES = PLAN_NAMES


def plan_weights(w, pos):
    """Filtrira tezine po poziciji: golman dobiva samo golmanske i fizicke atribute, igrac iz polja ne dobiva golmanske."""
    if pos == 0:
        return {a: x for a, x in w.items() if a in _GK_ATTRS or a in ('Stamina', 'Speed', 'Acceleration', 'Jump', 'Balance', 'PhysicalContact')}
    return {a: x for a, x in w.items() if a not in _GK_ATTRS}


# automatski plan po poziciji (0=GK, 1-3 obrana, 4 DMF, 5-8 sredina, 9-12 napad)
AUTO_FOCUS = {0: ('goalkeeping', 'physical'), 1: ('defending', 'physical'), 2: ('defending', 'physical'), 3: ('defending', 'physical'),
              4: ('defending', 'possession'), 5: ('possession', 'tactical'), 6: ('technical', 'physical'), 7: ('technical', 'physical'),
              8: ('technical', 'attack'), 9: ('attack', 'physical'), 10: ('attack', 'physical'), 11: ('attack', 'technical'), 12: ('finishing', 'physical')}
PTS_PER_OVR = 6.5       # priblizno: toliko neto bodova atributa = +1 OVR (za procjenu pri zatvaranju jaza do potencijala)
INTENSITY = {'light': 0.7, 'normal': 1.0, 'hard': 1.3}
GROWTH_SCALE = 1.0       # globalni regulator brzine rasta (1.0 = realisticno)
MAX_UP, MAX_DOWN = 2, 2  # najvise promjena po atributu u jednom obracunu
# --- meki zid potencijala i pad uz igranje (sve brojke ovdje, lako za doterati) ---
SOFT_ROOM = 0.3            # rast na/iznad POT-a ako igrac igra puno i dobro (obicni 'prostor' ide do 1.3)
SOFT_SHARE, SOFT_RATING = 0.7, 7.0
POT_BUMP_CHANCE, POT_BUMP_MAX = 0.5, 4   # sansa po obradi da POT poraste za 1, najvise +4 od pocetne procjene
DECLINE_TOP = (0.7, 7.3, 0.0)            # (udio minuta, ocjena, mnozitelj pada): top sezona = nema pada, igrac cak raste
TOP_MAX_AGE = 35                         # do koje dobi top forma donosi rast
TOP_BONUS_K = 0.6                        # jacina rasta (performance bonus) za 30+ igraca u top formi
DECLINE_STAR = (0.7, 7.0, 0.4)           # igra puno i odlicno
DECLINE_OK = (0.5, 6.7, 0.7)             # igra redovito i dobro
VET_AGES, VET_GAIN = (30, 35), 0.25      # iskusni igraci (30-33) koji igraju odlicno polako dobivaju procjenu igre
VET_ATTRS = ('OffensiveAwareness', 'DefensiveAwareness', 'LowPass', 'LoftedPass', 'TightPossession')
DECLINE_W = {'Speed': .35, 'Acceleration': .3, 'Stamina': .2, 'Jump': .08, 'Balance': .07}


def pos_group(pos):
    return 'gk' if pos == 0 else 'def' if pos <= 3 else 'mid' if pos <= 8 else 'fw'


def _h(pid, salt):
    return random.Random('%s|%s' % (pid, salt)).random()


def late_bloomer(pid):
    """Fiksna osobina po igracu (~12%): razvija se kasnije, sporije pada."""
    return _h(pid, 'late') < 0.12


_AGE_SHIFT = {'gk': 3, 'def': 1, 'mid': 0, 'fw': 0}      # golmani i obrana sazrijevaju kasnije
_DECL_START = {'gk': 34, 'def': 31, 'mid': 30, 'fw': 29}  # od koje dobi pocinje pad


def eff_age(pid, age, pos=None):
    """Razvojna dob: mlada = vise rasta. Ovisi o poziciji i late-bloomer osobini."""
    a = age - _AGE_SHIFT.get(pos_group(pos), 0) if pos is not None else age
    if late_bloomer(pid) and age <= 29:
        a -= 2
    return a


# pc199: sudbina kod starenja (ideja: Michele & Claude, "Declino Selettivo"): svaki igrac ima skrivenu, stalnu sudbinu.
#   early   pad pocinje 2 godine ranije (najranije 28) i brzi je (x1.5)
#   normal  kao dosad
#   long    pad pocinje 3 godine kasnije (najkasnije 34, golmani 35) i sporiji je (x0.6); od 30 do pocetka pada polako vraca
#           dio fizike koju uzima sama igra
# Udjeli: 20 / 60 / 20. Vrlo brzi igraci (Speed 85+) cesce su early; golmani, stoperi, defenzivni i centralni veznjaci
# te late bloomeri cesce long. Ne mijenja se: ovisi samo o id-u igraca (i poziciji / brzini).
DESTINY_EARLY = (2, 1.5, 28)      # (godina ranije, mnozitelj pada, najranija dob)
DESTINY_LONG = (3, 0.6, 34)       # (godina kasnije, mnozitelj pada, najkasnija dob)
LONG_RECOVER = 0.12               # bodova po mjesecu na fizici (DECLINE_W) za long igrace od 30 do pocetka pada
DESTINY_SHOW_AGE = 28             # u appu se sudbina vidi od ove dobi (prije je skrivena)


def destiny(pid, pos=None, speed=None):
    early, long_ = 0.20, 0.20
    if speed is not None and speed >= 85:
        early, long_ = 0.35, 0.10
    if pos is not None and pos in (0, 1, 4, 5):
        early, long_ = early * 0.6, min(0.45, long_ * 1.7)
    if late_bloomer(pid):
        early, long_ = early * 0.5, min(0.5, long_ * 1.5)
    x = _h(pid, 'destiny')
    return 'early' if x < early else 'long' if x >= 1 - long_ else 'normal'


def decl_start(pid, pos=None, speed=None):
    base = _DECL_START.get(pos_group(pos), 30) + (1 if late_bloomer(pid) else 0) if pos is not None else 30
    d = destiny(pid, pos, speed)
    if d == 'early':
        return max(DESTINY_EARLY[2], base - DESTINY_EARLY[0])
    if d == 'long':
        return min(base + DESTINY_LONG[0], max(DESTINY_LONG[2], base + 1))
    return base


def potential(pid, age, ovr, pos=None):
    """Procjena potencijala (igra ga ne izlaze): fiksna po igracu, ovisi o dobi (po poziciji) i trenutnom OVR-u."""
    ea = eff_age(pid, age, pos)
    base = {17: 15, 18: 14, 19: 12, 20: 10, 21: 8, 22: 6.5, 23: 5, 24: 4, 25: 3, 26: 2, 27: 1.5}.get(ea, 15 if ea < 17 else 0.5)
    gap = base * (0.55 + 0.9 * _h(pid, 'pot')) * max(0.15, 1 - max(0, ovr - 75) / 40.0)
    return min(95, round(ovr + gap))


def age_rate(age):
    t = {17: 1.7, 18: 1.6, 19: 1.5, 20: 1.3, 21: 1.1, 22: 0.9, 23: 0.7, 24: 0.55, 25: 0.4, 26: 0.3, 27: 0.2, 28: 0.1, 29: 0.1}
    return t.get(age, 1.7 if age < 17 else 0.0)


def settings_for(pid, pos, cfg):
    c = cfg.get(str(pid)) or {}
    if isinstance(c, str):                       # stari zapis: samo jedan fokus
        c = {'f1': c}
    a1, a2 = AUTO_FOCUS.get(pos, ('technical', 'physical'))
    f1 = c.get('f1') if c.get('f1') in GROUPS else a1
    f2 = c.get('f2') if c.get('f2') in GROUPS else a2
    if f2 == f1:
        f2 = a2 if a2 != f1 else a1
    it = c.get('int') if c.get('int') in INTENSITY else 'normal'
    return dict(f1=f1, f2=f2, int=it, auto=not (c.get('f1') in GROUPS))


def month_plan(pl, st, live, perf, mentor, months, period, pot=None, coach=None, load=1.0, bonus=None, bonus_why=None, bump=0, award=0.0, fac=None):
    """Jedan obracun za jednog igraca.
    pl: dict(id,pos,age,ovr); st: postavke; live: dict(attrs, form, aff, inj) ili None;
    perf: dict(share, rating) ili None; mentor: bool; months: duljina razdoblja u mjesecima.
    -> dict(points, factors, add=[(attr,delta)], prog=novo stanje, pot, pad)"""
    pid, age, ovr = pl['id'], pl['age'], pl['ovr']
    rnd = random.Random('%s|%s' % (period, pid))
    pot = pot if pot else potential(pid, age, ovr, pl.get('pos'))
    ea = eff_age(pid, age, pl.get('pos'))
    attrs = (live or {}).get('attrs') or {}
    form = (live or {}).get('form', 4)
    aff = (live or {}).get('aff', 200)
    inj = (live or {}).get('inj', 0)
    share = (perf or {}).get('share', 0.5)
    rating = (perf or {}).get('rating', 6.5)
    play = 0.55 + 0.6 * share + 0.1 * max(-1.0, min(1.5, rating - 6.5))
    fform = max(0.84, min(1.24, 1 + 0.08 * (form - 4)))
    faff = 0.9 + 0.2 * (aff / 255.0)
    inten = INTENSITY[st['int']]
    left = pot - ovr
    room = min(1.3, max(0.0, left) / 6.0) if left > 0 else 0.0
    why = []
    star = share >= SOFT_SHARE and rating >= SOFT_RATING
    top = share >= DECLINE_TOP[0] and rating >= DECLINE_TOP[1]
    soft = left <= 0 and age <= (TOP_MAX_AGE if top else 31) and star
    if soft:
        room = SOFT_ROOM; why.append('soft')
    fac = fac or {}   # pc316: ulaganja kluba (trening centar, akademija, medicinski centar)
    if inj > 0:
        ftrain = max(0.2, fac.get('injt', 0.2)); why.append('inj')
    else:
        ftrain = 1.0
    ment = 1.1 if (mentor and age <= 23) else 1.0
    if ment > 1: why.append('mentor')
    if share >= 0.7: why.append('plays')
    elif share < 0.3: why.append('bench')
    if form >= 5: why.append('form_hi')
    elif form <= 3: why.append('form_lo')
    if left <= 0 and age < 30 and not soft: why.append('cap')
    if late_bloomer(pid) and age <= 29: why.append('late')
    pts = age_rate(ea) * room * play * fform * faff * inten * ftrain * ment * months * GROWTH_SCALE
    if fac.get('train', 1.0) > 1.0 or (age <= 21 and fac.get('u21', 1.0) > 1.0):
        pts *= fac.get('train', 1.0) * (fac.get('u21', 1.0) if age <= 21 else 1.0)
        why.append('facility')
    if coach:
        cm = GRADE[coach['grade']][3]
        pts *= SOLO + (cm - SOLO) * max(0.0, min(1.0, load))
        why.append('coach')
        if load < 1: why.append('overload')
    else:
        pts *= SOLO
    prog = dict(((live or {}).get('_prog') or {}))
    # raspodjela: 60% glavni fokus, 30% sporedni, 10% ostalo
    ppos = pl['pos']
    def spread(group, amount):
        w = plan_weights(GROUPS[group], ppos); tot = sum(w.values())
        if tot <= 0:
            return
        for a, x in w.items():
            prog[a] = prog.get(a, 0.0) + amount * x / tot
    cw = plan_weights(coach_attr_weights(coach), ppos) if coach else {}
    if pts > 0 and cw:
        tot = sum(cw.values())
        for a, x in cw.items():
            prog[a] = prog.get(a, 0.0) + pts * 0.8 * x / tot
        spread('physical' if ppos else 'goalkeeping', pts * 0.2)
    elif pts > 0:
        spread(st['f1'], pts * 0.6); spread(st['f2'], pts * 0.3)
        rest = [g for g in ('overall', 'physical', 'technical', 'defending', 'attack') if g not in (st['f1'], st['f2'])] if ppos else ['physical', 'goalkeeping']
        for g in [x for x in rest if x not in (st['f1'], st['f2'])]:
            spread(g, pts * 0.1 / max(1, len(rest)))
    # pad kod 30+ (sporiji uz fizicki fokus, nema ga dok je ozlijedjen)
    dec = 0.0
    spd = pl.get('dbspeed') if pl.get('dbspeed') is not None else attrs.get('Speed')   # brzina iz baze: sudbina se ne mijenja kad uspori
    dst = destiny(pid, pl.get('pos'), spd)
    ds = decl_start(pid, pl.get('pos'), spd)
    if age >= DESTINY_SHOW_AGE and dst != 'normal':
        why.append('dest_' + dst)
    if dst == 'long' and 30 <= age < ds and inj == 0:
        for a, w in DECLINE_W.items():
            prog[a] = prog.get(a, 0.0) + LONG_RECOVER * months * w
    if age >= ds and inj == 0:
        dec = 0.15 * (age - ds + 1) * months * (DESTINY_EARLY[1] if dst == 'early' else DESTINY_LONG[1] if dst == 'long' else 1.0) * (0.5 if (('physical' in (st['f1'], st['f2']) or 'fitness' in (st['f1'], st['f2'])) or (coach and coach['role'] in ('physical', 'fitness'))) else 1.0)
        why.append('age')
        if fac.get('dec', 1.0) < 1.0:
            dec *= fac['dec']
        if top:
            dec *= DECLINE_TOP[2]; why.append('top')
        elif share >= DECLINE_STAR[0] and rating >= DECLINE_STAR[1]:
            dec *= DECLINE_STAR[2]; why.append('vet')
        elif share >= DECLINE_OK[0] and rating >= DECLINE_OK[1]:
            dec *= DECLINE_OK[2]; why.append('vet')
        for a, w in DECLINE_W.items():
            prog[a] = prog.get(a, 0.0) - dec * w
    if star and VET_AGES[0] <= age <= VET_AGES[1] and inj == 0:
        for a in (('GKAwareness',) if ppos == 0 else VET_ATTRS):
            prog[a] = prog.get(a, 0.0) + VET_GAIN * months * max(0.5, min(1.5, rating - 6.5))
        why.append('vet_up')
    if bonus and ((age <= 31 and left > 0) or (top and age <= TOP_MAX_AGE and inj == 0)):
        k = min(1.0, room * 1.2 + 0.2) if left > 0 else TOP_BONUS_K
        for a, x in plan_weights(bonus, ppos).items():
            prog[a] = prog.get(a, 0.0) + x * k
        why.extend(bonus_why or [])
    if award and award > 0:
        k = (1.0 if left > 0 else 0.6) * (0.5 if inj else 1.0) * (0.3 if age > TOP_MAX_AGE else 1.0)
        for a, x in plan_weights(award_points(ppos, award), ppos).items():
            prog[a] = prog.get(a, 0.0) + x * k
        why.append('award')
    add = []
    for a in list(prog):
        v = prog[a]; cur = attrs.get(a)
        if cur is None:
            continue
        if v >= 1 and cur < 99:
            n = min(MAX_UP, int(v)); n = min(n, 99 - cur)
            if n > 0: add.append((a, n)); prog[a] = v - n
        elif v <= -1 and cur > 40:
            n = min(MAX_DOWN, int(-v)); n = min(n, cur - 40)
            if n > 0: add.append((a, -n)); prog[a] = v + n
    prog = {a: round(v, 3) for a, v in prog.items() if abs(v) > 0.001}
    dform = 0
    if st['int'] == 'hard' and rnd.random() < 0.12 and inj == 0:
        dform = -1; why.append('tired')
    pot_up = 0
    if soft and bump < POT_BUMP_MAX and rnd.random() < POT_BUMP_CHANCE * min(1.0, age_rate(ea) * 2):
        pot_up = 1
    return dict(points=round(pts, 2), decline=round(dec, 2), pot=pot + pot_up, pot_up=pot_up, factors=why, add=add, prog=prog, dform=dform,
                play=round(play, 2), share=round(share, 2))


# ---------------------------------------------------------------- treneri
ROLES = {
    'attacking': ('Napadački trener', 'Attacking coach', {'Finishing': 3, 'OffensiveAwareness': 3, 'Curl': 1.5, 'Dribbling': 1.5}),
    'technical': ('Tehnički trener', 'Technical coach', {'BallControl': 3, 'Dribbling': 2.5, 'TightPossession': 2, 'LowPass': 1}),
    'possession': ('Trener posjeda', 'Possession coach', {'LowPass': 3, 'LoftedPass': 2.5, 'TightPossession': 2, 'BallControl': 1.5}),
    'defensive': ('Obrambeni trener', 'Defensive coach', {'DefensiveAwareness': 3, 'BallWinning': 3, 'Aggression': 1.5, 'Heading': 1.5}),
    'tactical': ('Taktički trener', 'Tactical coach', {'OffensiveAwareness': 2.5, 'DefensiveAwareness': 2.5, 'Balance': 1, 'LowPass': 1}),
    'set_piece': ('Trener stajalica', 'Set-piece coach', {'PlaceKicking': 3, 'Curl': 3, 'LoftedPass': 2, 'KickingPower': 1.5, 'Heading': 1}),
    'physical': ('Fizički trener', 'Physical coach', {'Speed': 2.5, 'Acceleration': 2.5, 'PhysicalContact': 2, 'Jump': 1.5, 'Balance': 1.5}),
    'goalkeeping': ('Trener golmana', 'Goalkeeping coach', {'GKAwareness': 2.5, 'GKCatching': 2.5, 'GKClearing': 1.5, 'GKReflexes': 3, 'GKReach': 2}),
    'youth': ('Trener mladih', 'Youth development coach', {'BallControl': 1.5, 'Dribbling': 1.5, 'LowPass': 1.5, 'OffensiveAwareness': 1.5, 'DefensiveAwareness': 1.5, 'Stamina': 1.5}),
    'fitness': ('Kondicijski trener', 'Fitness coach', {'Stamina': 4, 'PhysicalContact': 1.5, 'Balance': 1, 'Jump': 1}),
}
# razina: (kljuc, hr, en, mnozitelj rasta, kapacitet igraca, bodovi osoblja)
GRADES = [('developing', 'Početnik', 'Developing', 1.05, 3, 1), ('reliable', 'Pouzdan', 'Reliable', 1.12, 4, 2),
          ('specialist', 'Specijalist', 'Specialist', 1.2, 5, 3), ('expert', 'Stručnjak', 'Expert', 1.3, 6, 4),
          ('elite', 'Elitni', 'Elite', 1.45, 8, 6)]
ROLE_PLAN = {'attacking': 'attack', 'technical': 'technical', 'possession': 'possession', 'defensive': 'defending', 'tactical': 'tactical',
             'set_piece': 'set_pieces', 'physical': 'physical', 'goalkeeping': 'goalkeeping', 'youth': 'overall', 'fitness': 'fitness'}
for _k, _p in ROLE_PLAN.items():            # tezine uloga = tezine odgovarajuceg FM plana
    ROLES[_k] = (ROLES[_k][0], ROLES[_k][1], GROUPS[_p])
GRADE = {g[0]: g for g in GRADES}
WAGE = {1: 150000, 2: 300000, 3: 600000, 4: 1100000, 6: 2000000}   # godisnja placa trenera po 'cost' razini (EUR)
def coach_wage(c):
    return WAGE[GRADE[c['grade']][5]]
def staff_wages(coaches):
    return sum(coach_wage(c) for c in coaches)
def default_staff_budget(wage_bill):
    return int(max(1000000, round(wage_bill * 0.06 / 50000.0) * 50000))
STAFF_POINTS = 12          # "pokrice uprave": zbroj bodova osoblja koje mozes zaposliti
SOLO = 0.7                 # igrac bez trenera raste na 70% brzine
SECONDARY_W = 0.4
_FIRST = {'ES': ['Javier', 'Álvaro', 'Pablo', 'Iñaki', 'Rubén'], 'PT': ['Ricardo', 'Nuno', 'Tiago', 'Rui', 'Bruno'], 'IT': ['Giorgio', 'Matteo', 'Luca', 'Andrea', 'Enzo'],
          'DE': ['Lars', 'Jonas', 'Felix', 'Matthias', 'Stefan'], 'FR': ['Hugo', 'Étienne', 'Julien', 'Bastien', 'Mathieu'], 'NL': ['Joost', 'Bram', 'Daan', 'Wouter', 'Sander'],
          'GB': ['Neil', 'Gareth', 'Colin', 'Marcus', 'Declan'], 'HR': ['Davor', 'Ivica', 'Zoran', 'Marin', 'Tomislav'], 'AR': ['Matías', 'Facundo', 'Ezequiel', 'Santiago', 'Lucas']}
_LAST = {'ES': ['Etxeberria', 'Navarro', 'Castillo', 'Ferrer', 'Ortega'], 'PT': ['Salgueiro', 'Duarte', 'Pacheco', 'Cardoso', 'Moreira'], 'IT': ['Ferrante', 'Bellini', 'Conti', 'Sorrentino', 'Moretti'],
         'DE': ['Holmgren', 'Achterberg', 'Brandt', 'Keller', 'Vogt'], 'FR': ['Lemaire', 'Dufour', 'Garnier', 'Roussel', 'Marchand'], 'NL': ['de Wit', 'van Dalen', 'Koster', 'Bakker', 'Verhoeven'],
         'GB': ['Thornton', 'Whitfield', 'Hargreaves', 'Prentice', 'Calloway'], 'HR': ['Perić', 'Kovač', 'Matić', 'Babić', 'Lukić'], 'AR': ['Villanueva', 'Aguirre', 'Sosa', 'Ledesma', 'Ibarra']}
TRAITS = [('Strpljiv učitelj', 'Patient teacher'), ('Zahtjevan', 'Demanding'), ('Inovativne metode', 'Innovative methods'), ('Smiren pod pritiskom', 'Calm under pressure'),
          ('Stari kroj', 'Old school'), ('Odličan motivator', 'Excellent motivator'), ('Zaljubljen u detalje', 'Detail obsessive')]


def coach_pool():
    """Fiksan (deterministican) bazen od 50 trenera: 5 po ulozi, piramida razina."""
    rnd = random.Random('coach-pool-v1')
    countries = list(_FIRST)
    out, n = [], 0
    for role in ROLES:
        gr = ['developing', 'reliable', 'reliable', 'specialist', 'expert']
        gr[rnd.randrange(5)] = 'elite' if rnd.random() < 0.55 else gr[0]
        for k in range(5):
            n += 1
            c = countries[(n * 3 + k) % len(countries)]
            sec = rnd.sample([r for r in ROLES if r != role], 1 + (1 if GRADE[gr[k]][5] >= 3 else 0))
            out.append(dict(id='c%02d' % n, name='%s %s' % (rnd.choice(_FIRST[c]), rnd.choice(_LAST[c])), country=c, role=role, sec=sec,
                            grade=gr[k], trait=rnd.randrange(len(TRAITS))))
    return out


def coach_attr_weights(coach):
    w = {}
    for a, x in ROLES[coach['role']][2].items():
        w[a] = w.get(a, 0) + x
    for r in coach.get('sec', []):
        for a, x in ROLES[r][2].items():
            w[a] = w.get(a, 0) + x * SECONDARY_W
    return w


AWARD_ROLES = {0: ('goalkeeping',), 1: ('defensive', 'physical'), 2: ('defensive', 'physical'), 3: ('defensive', 'physical'),
               4: ('defensive', 'possession'), 5: ('possession', 'technical'), 6: ('technical', 'attacking'), 7: ('technical', 'attacking'),
               8: ('technical', 'attacking'), 9: ('attacking', 'technical'), 10: ('attacking', 'technical'), 11: ('attacking', 'technical'),
               12: ('attacking', 'physical')}


def award_points(pos, total):
    """Bodovi nagrade (ukupno) razdijeljeni po glavnim ulogama pozicije. -> {atribut: bodovi}"""
    roles = AWARD_ROLES.get(pos, ('technical',))
    out = {}
    for rl in roles:
        w = ROLES[rl][2]
        tw = float(sum(w.values()))
        for a, x in w.items():
            out[a] = out.get(a, 0.0) + total / len(roles) * x / tw
    return out


def performance_bonus(pos, st, n_win):
    """st: dict(app, g, a, cs, rating) u razdoblju; -> (bodovi po atributu, razlozi). Skalirano na duljinu razdoblja."""
    if not st or n_win < 2 or st.get('app', 0) < 2:
        return {}, []
    scale = max(0.3, min(1.5, n_win / 10.0))
    app, g, a, cs, r = st['app'], st['g'], st['a'], st['cs'], st['rating']
    grp = pos_group(pos)
    pts, why = {}, []
    def put(attrs, amount):
        tot = sum(attrs.values())
        for k, x in attrs.items():
            pts[k] = pts.get(k, 0.0) + amount * x / tot
    gr = g / float(n_win)
    if grp in ('fw', 'mid') and gr >= 0.25:
        put(ROLES['attacking'][2], (0.8 if gr >= 0.4 else 0.4) * scale); why.append('goals')
    if a / float(n_win) >= 0.3 and grp != 'gk':
        put(ROLES['possession'][2], 0.5 * scale); why.append('assists')
    if grp in ('def', 'gk') or pos == 4:
        if cs / float(n_win) >= 0.4 and app / float(n_win) >= 0.6:
            put(ROLES['goalkeeping'][2] if grp == 'gk' else ROLES['defensive'][2], 0.6 * scale); why.append('clean_sheet')
    if app >= 3 and r >= 7.3:
        base = ROLES['goalkeeping'][2] if grp == 'gk' else ROLES['technical'][2] if grp in ('mid', 'fw') else ROLES['defensive'][2]
        put(base, 0.4 * scale); why.append('rating')
    return pts, why


def bridge_dir(cfg):
    return os.path.dirname(cfg['dump'])


def queue(cfg, rows, batch):
    """rows: [(pid, field, delta)] -> append u growth.csv. txid je jedinstven po batchu."""
    p = os.path.join(bridge_dir(cfg), 'growth.csv')
    lines = []
    for pid, f, dl in rows:
        lines.append('%s-%d-%s,%d,%s,add,%d' % (batch, pid, f, pid, f, dl))
    if not lines:
        return 0
    with open(p, 'a', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines) + '\n')
    return len(lines)


def read_results(cfg, prefix=None, limit=2000):
    p = os.path.join(bridge_dir(cfg), 'growth-result.csv')
    if not os.path.exists(p):
        return []
    out = {}
    for ln in open(p, encoding='utf-8', errors='replace').read().splitlines():
        r = ln.split(',')
        if len(r) < 4 or (prefix and not r[0].startswith(prefix)):
            continue
        out[r[0]] = dict(tx=r[0], status=r[1], old=r[2], new=r[3])  # zadnji status pobjeduje
    return list(out.values())[-limit:]


def enabled(cfg):
    return os.path.exists(os.path.join(bridge_dir(cfg), 'growth.enabled'))


def set_enabled(cfg, on):
    p = os.path.join(bridge_dir(cfg), 'growth.enabled')
    if on:
        open(p, 'w').write('1')
    elif os.path.exists(p):
        os.remove(p)


def load_focus(here):
    try:
        return json.load(open(os.path.join(here, 'data', 'growth_focus.json'), encoding='utf-8'))
    except Exception:
        return {}


def save_focus(here, d):
    jsafe.jdump(d, os.path.join(here, 'data', 'growth_focus.json'))


def load_state(here):
    try:
        return json.load(open(os.path.join(here, 'data', 'growth_state.json'), encoding='utf-8'))
    except Exception:
        return {}


def save_state(here, st):
    jsafe.jdump(st, os.path.join(here, 'data', 'growth_state.json'))
