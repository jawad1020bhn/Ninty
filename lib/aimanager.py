"""AI menadzeri: dodjela i promjena taktike AI klubova (igra ih sama ne mijenja). Deterministicno za zadani seed.
Profil kluba (stalni 'identitet' trenera) + raspolozenje po formi zadnjih 5 utakmica."""
import random

ADV = {'tiki': 6, 'fullbacks': 4, 'centring': 7, 'false_fb': 3, 'gegen': 13, 'deepline': 12, 'swarm': 11, 'wingback': 16, 'rotation': 5, 'touch': 1}

PROFILES = {
    'possession': dict(style='possession', build='short', pos='flexible', area='centre', defstyle='frontline', cont='centre', press='aggressive', support=7, line=7, compact=6, adv=['tiki']),
    'highpress': dict(style='possession', build='short', pos='flexible', area='wide', defstyle='frontline', cont='wide', press='aggressive', support=6, line=9, compact=8, adv=['gegen']),
    'wings': dict(style='possession', build='short', pos='flexible', area='wide', defstyle='frontline', cont='wide', press='conservative', support=6, line=6, compact=5, adv=['fullbacks', 'centring']),
    'balanced': dict(style='possession', build='short', pos='maintain', area='centre', defstyle='frontline', cont='centre', press='conservative', support=5, line=5, compact=5, adv=[]),
    'counter': dict(style='counter', build='long', pos='maintain', area='wide', defstyle='allout', cont='wide', press='conservative', support=4, line=3, compact=6, adv=['touch']),
    'lowblock': dict(style='counter', build='long', pos='maintain', area='centre', defstyle='allout', cont='centre', press='conservative', support=3, line=2, compact=8, adv=['deepline']),
}
WEIGHTS = {
    'big': dict(possession=3, highpress=3, wings=2, balanced=1, counter=.5, lowblock=0),
    'mid': dict(possession=1.5, highpress=1, wings=1.5, balanced=2, counter=1.5, lowblock=.5),
    'small': dict(possession=.7, highpress=.3, wings=1, balanced=1.5, counter=2, lowblock=2),
}
ATTACKY = ('possession', 'highpress', 'wings')
DEFENSIVE = ('counter', 'lowblock')
COOLDOWN = 14          # najmanje dana igre izmedju dviju sitnih korekcija istog kluba
EVAL_EVERY = 5         # klub se ocjenjuje najvise svakih 5 dana igre
SWITCH_COOLDOWN = 42   # najmanje dana igre izmedju dviju promjena sustava


def _clamp(v):
    return max(1, min(10, int(v)))


def tactics_for(profile, mood=None):
    t = dict(PROFILES[profile])
    # slotovi: napad A1/A2, obrana D1/D2
    a = d = 0
    out = []
    for k in t['adv']:
        if ADV[k] <= 10:
            a += 1
            out.append(dict(slot='A%d' % a, id=ADV[k]))
        else:
            d += 1
            out.append(dict(slot='D%d' % d, id=ADV[k]))
    t['adv'] = out
    if mood == 'bad':
        t['line'] = _clamp(t['line'] - 2); t['support'] = _clamp(t['support'] - 1); t['compact'] = _clamp(t['compact'] + 1); t['press'] = 'conservative'
    elif mood == 'good':
        t['line'] = _clamp(t['line'] + 1); t['support'] = _clamp(t['support'] + 1)
    elif mood == 'leaky':
        t['compact'] = _clamp(t['compact'] + 2); t['line'] = _clamp(t['line'] - 1)
    elif mood == 'blunt':
        t['support'] = _clamp(t['support'] + 2)
    return t


def pick_profile(c, rnd, exclude=None, bias=None):
    w = dict(WEIGHTS[c['tier']])
    if bias == 'defend':      # puno primljenih golova: oprezniji sustav
        for k in w:
            w[k] *= 3 if k in DEFENSIVE or k == 'balanced' else (0.1 if k in ATTACKY else 1)
    elif bias == 'attack':    # ne postize golove: napadackiji sustav
        for k in w:
            w[k] *= 2.5 if k in ATTACKY else (0.4 if k in DEFENSIVE else 1)
    lean = c.get('lean', 0)
    for k in w:
        if lean >= 2 and k in ATTACKY:
            w[k] *= 1.5
        if lean <= -2 and k in DEFENSIVE:
            w[k] *= 1.5
    if exclude:
        w.pop(exclude, None)
    ks = [k for k in w if w[k] > 0]
    return rnd.choices(ks, [w[k] for k in ks])[0]


def lean_of(players):
    """Razlika napad - obrana u top igracima (OVR): >0 jaci napad."""
    def top(ps, n):
        v = sorted((p['ovr'] for p in ps if p['ovr']), reverse=True)[:n]
        return sum(v) / len(v) if v else 0
    fw = top([p for p in players if p['pos'] in (9, 10, 11, 12)], 3)
    df = top([p for p in players if p['pos'] in (1, 2, 3)], 4)
    return fw - df


def mood_of(f):
    """f = dict(n, pts, gf, ga, streak_l) iz zadnjih <=5 utakmica."""
    if not f or f['n'] < 4:
        return None
    if f['pts'] <= 3:
        return 'bad'
    if f['pts'] >= 12:
        return 'good'
    if f['ga'] >= 9:
        return 'leaky'
    if f['gf'] <= 2:
        return 'blunt'
    return None


def form_table(M, max_idx=750):
    """club idx -> chronological [(gf, ga)] za odigrane utakmice zadnje sezone."""
    import seasonstats
    ms = [m for m in M['matches'] if m['played'] and m['home'] != m['away'] and m['home'] < max_idx and m['away'] < max_idx]
    if not ms:
        return {}
    season = max(m['season'] for m in ms)
    out = {}
    for m in sorted(ms, key=seasonstats.sort_key):
        if m['season'] != season:
            continue
        gh = (m['sc'][0] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] == m['home']))
        ga = (m['sc'][1] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] == m['away']))
        out.setdefault(m['home'], []).append((gh, ga))
        out.setdefault(m['away'], []).append((ga, gh))
    return out


def form_of(res):
    last = res[-5:]
    if not last:
        return None
    pts = sum(3 if a > b else 1 if a == b else 0 for a, b in last)
    streak = 0
    for a, b in reversed(res):
        if a < b:
            streak += 1
        else:
            break
    return dict(n=len(last), pts=pts, gf=sum(a for a, b in last), ga=sum(b for a, b in last), streak_l=streak)


def plan(clubs, forms, state, daynum, seed, skip=()):
    """clubs: aitransfers.load_clubs (idx -> dict(tier,players,name,...)); state: {str(idx): dict(p, mood, day)}.
    Vraca (promjene, novo stanje). Promjena = dict(idx, name, kind, prof_from, prof_to, mood_from, mood_to, tactics)."""
    changes = []
    new = {k: dict(v) for k, v in state.items()}
    for idx, c in clubs.items():
        if idx in skip:
            continue
        c['lean'] = lean_of(c['players'])
        k = str(idx)
        rnd = random.Random(seed * 100003 + idx)
        f = form_of(forms.get(idx, []))
        st = new.get(k)
        if st is None:
            p = pick_profile(c, rnd)
            st = new[k] = dict(p=p, mood=None, day=daynum)
            changes.append(dict(idx=idx, name=c['name'], kind='init', prof_from=None, prof_to=p, mood_from=None, mood_to=None, tactics=tactics_for(p)))
            continue
        if f is None or daynum - st.get('eval', 0) < EVAL_EVERY:
            continue
        st['eval'] = daynum
        # promjena sustava: 4 poraza zaredom, rijetko (najmanje SWITCH_COOLDOWN dana od prethodne)
        if f['streak_l'] >= 4 and daynum - st.get('sw', -999) >= SWITCH_COOLDOWN:
            rnd2 = random.Random(seed * 7907 + idx * 31 + daynum)
            bias = 'defend' if f['ga'] >= f['gf'] + 3 else 'attack' if f['gf'] <= 3 else None
            p = pick_profile(c, rnd2, exclude=st['p'], bias=bias)
            ch = dict(idx=idx, name=c['name'], kind='switch', prof_from=st['p'], prof_to=p, mood_from=st.get('mood'), mood_to=None, tactics=tactics_for(p), form=f)
            st.update(p=p, mood=None, day=daynum, sw=daynum, pend=None)
            changes.append(ch)
            continue
        # sitne korekcije: isto raspolozenje mora biti vidjeno dva puta zaredom, i najmanje COOLDOWN dana od prethodne promjene
        m = mood_of(f)
        if m == st.get('mood'):
            st['pend'] = None
        elif m != st.get('pend'):
            st['pend'] = m
        elif daynum - st.get('day', 0) >= COOLDOWN:
            changes.append(dict(idx=idx, name=c['name'], kind='mood', prof_from=st['p'], prof_to=st['p'], mood_from=st.get('mood'), mood_to=m, tactics=tactics_for(st['p'], m), form=f))
            st.update(mood=m, day=daynum, pend=None)
    return changes, new
