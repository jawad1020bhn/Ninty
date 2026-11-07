"""Match simulation for the FC 27 engine.

Uses EA's 34 RAW attributes (fc27.ea_attrs), not the legacy 25-attribute projection:
the projection has no slot for interceptions, vision, reactions, composure,
crossing, volleys, longshots, penalties or slidingtackle, so a defence built from
it cannot tell an interceptor from a slider.  See lib/fc27.py.

Model: a per-minute chance process.  Midfield strength decides how many chances
each side creates; attack against defence+goalkeeper decides how many are taken.
Everything is driven by a seeded RNG, so a fixture replays identically - which
is what makes the engine testable and a save reloadable mid-season.

The constants below are calibration choices, not database facts.  They are
grouped here so they can be tuned against the season-level assertions in
tools/verify_engine.py (goals per game, home advantage, draw rate).
"""
import random

import fc27

from . import store as S
from . import roster as R
from .lineup import units


def is_big(home, away):
    """Is this a marquee fixture?

    EA's bigmatchups table is a curated list, not 'every derby': it omits
    Manchester United-Liverpool, which rivals.json rates intensity 5. So the
    engine treats a fixture as big if EITHER source says so. fc27.is_big_match()
    is left reporting exactly what upstream ships.
    """
    if fc27.is_big_match(home, away):
        return True
    for r in fc27.club_rivals(home):
        if int(r['id']) == int(away) and int(r.get('intensity') or 0) >= 4:
            return True
    return False

# --- calibration -----------------------------------------------------------
# Fitted, not guessed: three full 380-match Premier League seasons (seeds 7, 19,
# 31) were simulated across a grid of these values. This setting produced
#   goals/game 2.74   home 45.7%   draw 24.8%   away 29.5%   shots/game 25.0
# against real Premier League reference values of roughly
#   goals/game 2.8    home 46%     draw 24%     away 30%      shots/game 25
# Shots were already correct at CHANCE_BASE=0.128, so conversion (not chance
# volume) was the lever for goals; the home/away pair sets the result split.
# tools/verify_engine.py asserts these ranges so a future edit cannot silently
# drift the simulation into arcade scores.
CHANCE_BASE = 0.128        # chance per team per minute at equal strength
HOME_EDGE = 1.20           # home chance multiplier
AWAY_EDGE = 0.90
CONV_BASE = 0.086          # baseline chance -> goal
RATING_BASE = 6.15
INJURY_P = 0.018           # per player per match
YELLOW_P = 0.11
RED_P = 0.004

def attr(st, pid, name, default=50):
    """One raw EA attribute, save-aware (generated players + career growth)."""
    return R.ea_attrs(st, pid).get(name, default)


def _mean(vals, default=50.0):
    return sum(vals) / float(len(vals)) if vals else default


def _group(st, pids, names, weights=None):
    if not pids:
        return 50.0
    weights = weights or [1.0] * len(names)
    tot = sum(weights)
    per = []
    for pid in pids:
        per.append(sum(attr(st, pid, n) * w for n, w in zip(names, weights)) / tot)
    return _mean(per)


ATT_ATTRS = ['finishing', 'positioning', 'shotpower', 'composure',
             'dribbling', 'ballcontrol', 'acceleration', 'longshots']
ATT_W = [3.0, 2.0, 1.2, 1.2, 1.5, 1.2, 1.0, 0.8]
MID_ATTRS = ['shortpassing', 'longpassing', 'vision', 'ballcontrol',
             'dribbling', 'stamina', 'positioning']
MID_W = [2.0, 1.5, 1.8, 1.5, 1.2, 1.0, 0.8]
DEF_ATTRS = ['defensiveawareness', 'standingtackle', 'interceptions',
             'slidingtackle', 'headingaccuracy', 'strength', 'jumping']
DEF_W = [3.0, 2.2, 2.2, 1.2, 1.5, 1.2, 1.0]
GK_ATTRS = ['gkdiving', 'gkhandling', 'gkreflexes', 'gkpositioning', 'gkkicking']
GK_W = [1.2, 1.2, 1.4, 1.4, 0.5]


def unit_ratings(st, xi):
    """-> dict(att, mid, def, gk) on roughly the same 0-99 scale as attributes."""
    gk, df, mf, at = units(st, xi)
    # Lines help each other: midfield feeds attack, defence is shielded by it.
    a = _group(st, at, ATT_ATTRS, ATT_W)
    m = _group(st, mf, MID_ATTRS, MID_W)
    d = _group(st, df, DEF_ATTRS, DEF_W)
    g = _group(st, gk, GK_ATTRS, GK_W)
    if not at:
        a = m * 0.85
    if not mf:
        m = (a + d) / 2.0
    if not df:
        d = m * 0.85
    # 'def' is a Python keyword, so this is a dict literal, not dict(**kwargs).
    return {
        'att': 0.60 * a + 0.30 * m + 0.10 * d,
        'mid': 0.70 * m + 0.15 * a + 0.15 * d,
        'def': 0.60 * d + 0.20 * m + 0.20 * g,
        'gk': g,
    }


def _ovr_scale(st, xi):
    """Nudge units by the squad's current overall relative to its raw attributes.

    Career growth changes OVR in the save; the static EA attributes do not
    change.  This keeps a developed player better than his rookie self without
    pretending we know which of the 34 attributes grew.
    """
    if not xi:
        return 1.0
    deltas = []
    for pid in xi:
        r = S.pstate(st, pid)
        if r:
            deltas.append(r[S.P_OVR] - R.base_ovr(st, pid))
    return 1.0 + (_mean(deltas, 0.0) / 100.0)


def _fitness_factor(st, xi):
    if not xi:
        return 1.0
    fit = _mean([(S.pstate(st, p) or [0, 0, 0, 100])[S.P_FIT] for p in xi], 100.0)
    return 0.88 + 0.12 * (fit / 100.0)


def simulate(st, fixture, home_xi, away_xi, home_bench=(), away_bench=(), seed=None):
    """Play one fixture. -> result dict (does not mutate the save)."""
    home, away = int(fixture['home']), int(fixture['away'])
    seed = int(seed if seed is not None else (st.get('seed', 1) * 1000003 + int(fixture['id'])))
    rnd = random.Random(seed)

    hu, au = unit_ratings(st, home_xi), unit_ratings(st, away_xi)
    for u, xi in ((hu, home_xi), (au, away_xi)):
        k = _ovr_scale(st, xi) * _fitness_factor(st, xi)
        for key in u:
            u[key] *= k

    big = is_big(home, away)
    lid = st['clubs'][str(home)]['league']
    refs = fc27.referees(lid)
    ref = refs[rnd.randrange(len(refs))] if refs else None
    strict = (ref or {}).get('cards', 1)

    goals = {home: [], away: []}
    events = []
    shots = {home: 0, away: 0}
    on_target = {home: 0, away: 0}
    cards = {}
    injuries = {}
    played = {}
    for pid in list(home_xi) + list(away_xi):
        played[int(pid)] = 90

    # Substitutions: three per side, from the bench, around the hour.
    subs = []
    for tid, xi, bench in ((home, home_xi, home_bench), (away, away_xi, away_bench)):
        outfield = [p for p in xi if R.pos(st, p) != 0]
        pool = [p for p in bench if R.pos(st, p) != 0]
        for out_pid, in_pid in zip(outfield[-3:][::-1], pool[:3]):
            minute = rnd.randint(58, 78)
            subs.append((minute, tid, out_pid, in_pid))
    subs.sort()
    live = {home: list(home_xi), away: list(away_xi)}
    # Everyone who gets minutes, not just the starters: a substitute can score,
    # be booked or get injured, and must appear in the player rows or the
    # scoreline would not equal the sum of its scorers.
    team_players = {home: list(home_xi), away: list(away_xi)}
    si = 0

    for minute in range(1, 91):
        while si < len(subs) and subs[si][0] <= minute:
            _, tid, out_pid, in_pid = subs[si]
            si += 1
            if out_pid in live[tid]:
                live[tid].remove(out_pid)
                live[tid].append(in_pid)
                played[out_pid] = minute - 1
                played[in_pid] = 90 - minute + 1
                if in_pid not in team_players[tid]:
                    team_players[tid].append(in_pid)
                events.append(dict(min=minute, kind='sub', tid=tid, out=out_pid, inn=in_pid))

        diff = len(goals[home]) - len(goals[away])
        for tid, opp, u, ou, edge in ((home, away, hu, au, HOME_EDGE),
                                      (away, home, au, hu, AWAY_EDGE)):
            side_diff = diff if tid == home else -diff
            # Trailing sides push; the shipped intensity table says how hard.
            push = 1.0 + 0.045 * fc27.match_intensity(-side_diff, minute)
            create = (u['mid'] / max(30.0, ou['mid'])) ** 1.35
            finish = (u['att'] / max(30.0, 0.62 * ou['def'] + 0.38 * ou['gk'])) ** 1.55
            p = CHANCE_BASE * create * edge * push
            if rnd.random() >= p:
                continue
            shots[tid] += 1
            scorer = _pick_scorer(st, live[tid], rnd)
            if scorer is None:
                continue
            conv = CONV_BASE * finish
            conv *= 0.72 + 0.56 * (attr(st, scorer, 'finishing') / 100.0)
            conv *= 0.80 + 0.40 * (attr(st, scorer, 'composure') / 100.0)
            if rnd.random() < 0.68:
                on_target[tid] += 1
            if rnd.random() < max(0.02, min(0.55, conv)):
                assister = _pick_assister(st, live[tid], scorer, rnd)
                goals[tid].append((minute, scorer, assister))
                events.append(dict(min=minute, kind='goal', tid=tid, pid=scorer,
                                   assist=assister, score=[len(goals[home]), len(goals[away])]))

    # Discipline and injuries, resolved per player over the minutes he played.
    for tid, xi in team_players.items():
        for pid in xi:
            mins = played.get(pid, 0) / 90.0
            if mins <= 0:
                continue
            agg = attr(st, pid, 'aggression') / 100.0
            if rnd.random() < YELLOW_P * mins * (0.55 + agg) * (0.75 + 0.35 * strict):
                cards[pid] = cards.get(pid, 0) + 1
                events.append(dict(min=rnd.randint(1, 90), kind='yellow', tid=tid, pid=pid))
                if rnd.random() < 0.035:
                    cards[pid] = 2
            if rnd.random() < RED_P * mins * (0.5 + agg):
                cards[pid] = 2
                events.append(dict(min=rnd.randint(1, 90), kind='red', tid=tid, pid=pid))
            if rnd.random() < INJURY_P * mins:
                injuries[pid] = rnd.choice([7, 10, 14, 21, 28, 42, 60])
                events.append(dict(min=rnd.randint(1, 90), kind='injury', tid=tid,
                                   pid=pid, days=injuries[pid]))

    hg, ag = len(goals[home]), len(goals[away])
    rows = _ratings(st, home, away, team_players, goals, cards, played, hg, ag, rnd)
    events.sort(key=lambda e: e['min'])
    poss = hu['mid'] / max(1.0, hu['mid'] + au['mid'])
    poss = int(round(100 * max(0.28, min(0.72, poss * 0.55 + 0.225))))
    return dict(
        fid=int(fixture['id']), comp=int(fixture['comp']), kind=fixture['kind'],
        date=fixture['date'], home=home, away=away, sc=[hg, ag], played=True,
        rows=rows, events=events,
        cards={str(k): v for k, v in cards.items()},
        injuries={str(k): v for k, v in injuries.items()},
        minutes={str(k): v for k, v in played.items()},
        stats=dict(possession=[poss, 100 - poss],
                   shots=[shots[home], shots[away]],
                   onTarget=[on_target[home], on_target[away]]),
        referee=(ref or {}).get('id'), big=bool(big),
        atmosphere=atmosphere(home, away, big),
        attendance=_attendance(st, home, away, big))


def _pick_scorer(st, xi, rnd):
    """Weight by line and by the attributes that actually put the ball away."""
    weights, pids = [], []
    for pid in xi:
        p = R.pos(st, pid)
        if p == 0:
            continue
        line = 3 if p >= 9 else 2 if p >= 4 else 1
        base = {3: 6.0, 2: 2.4, 1: 0.7}[line]
        w = base * (0.45 + attr(st, pid, 'finishing') / 100.0) * (0.55 + attr(st, pid, 'positioning') / 100.0)
        weights.append(w)
        pids.append(pid)
    if not pids:
        return None
    return rnd.choices(pids, weights=weights, k=1)[0]


def _pick_assister(st, xi, scorer, rnd):
    weights, pids = [], []
    for pid in xi:
        if pid == scorer or R.pos(st, pid) == 0:
            continue
        p = R.pos(st, pid)
        base = 2.6 if p >= 9 else 3.2 if p >= 4 else 1.0
        w = base * (0.4 + attr(st, pid, 'vision') / 100.0) * (0.5 + attr(st, pid, 'shortpassing') / 100.0)
        weights.append(w)
        pids.append(pid)
    if not pids or rnd.random() > 0.72:
        return None
    return rnd.choices(pids, weights=weights, k=1)[0]


def _ratings(st, home, away, team_players, goals, cards, played, hg, ag, rnd):
    """Per-player ratings, in the (pid, club, goals, assists, rating) shape that
    lib/formengine.compute and lib/seasonstats already consume."""
    scored = {}
    assisted = {}
    for tid, gl in goals.items():
        for _, s, a in gl:
            scored[s] = scored.get(s, 0) + 1
            if a:
                assisted[a] = assisted.get(a, 0) + 1
    rows = []
    for tid, xi in team_players.items():
        gf, ga = (hg, ag) if tid == home else (ag, hg)
        for pid in xi:
            pid = int(pid)
            mins = played.get(pid, 0)
            if mins <= 0:
                continue
            pos = R.pos(st, pid)
            r = RATING_BASE + rnd.uniform(-0.45, 0.45)
            r += 0.85 * scored.get(pid, 0) + 0.55 * assisted.get(pid, 0)
            r += 0.22 if gf > ga else -0.22 if gf < ga else 0.0
            if pos == 0:
                r += 0.45 if ga == 0 else 0.12 if ga == 1 else -0.18 * (ga - 1)
                r += 0.03 * max(0, attr(st, pid, 'gkreflexes') - 70)
            elif pos <= 3:
                r += 0.35 if ga == 0 else -0.16 * max(0, ga - 1)
            elif pos >= 9 and not scored.get(pid) and not assisted.get(pid):
                r -= 0.15
            r -= {1: 0.22, 2: 0.85}.get(cards.get(pid, 0), 0.0)
            # Shrink a short appearance towards the baseline rather than
            # scaling the whole rating: a sub on 20 minutes is ~6.0, not 4.0.
            r = RATING_BASE + (r - RATING_BASE) * (0.55 + 0.45 * (mins / 90.0))
            rows.append([pid, tid, scored.get(pid, 0), assisted.get(pid, 0),
                         round(max(3.0, min(10.0, r)), 2)])
    return rows


def atmosphere(home, away, big):
    """Crowd emotion on the shipped 0-10 scale.

    match_tuning.attendance.{big,none} maps an emotion LEVEL (0-6) to a min/max
    band on a 0-10 scale. It is NOT a stadium fill fraction - reading it as one
    produced 100% capacity for every fixture. The level itself is career state
    the engine does not model yet, so the midpoint is reported as ambient
    atmosphere and used only as a small home-edge modifier.
    """
    bands = (fc27.match_tuning().get('attendance') or {}).get('big' if big else 'none') or []
    level = 5 if big else 3
    band = next((b for b in bands if b.get('emotion') == level), None)
    if not band:
        return 5.0
    lo, hi = band.get('min'), band.get('max')
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        return round((lo + hi) / 2.0, 2)
    return 5.0


def _attendance(st, home, away, big):
    """Crowd size from capacity, club reputation and fixture importance.

    Fill is an engine choice, not a database fact: upstream ships no attendance
    figures. Bigger clubs and marquee fixtures fill more of their ground.
    """
    stad = fc27.stadium(home) or {}
    cap = int(stad.get('capacity') or 20000)
    rep = int((fc27.clubs().get(str(int(home))) or {}).get('prestige') or 5)
    fill = 0.62 + 0.030 * max(0, min(10, rep)) + (0.08 if big else 0.0)
    fill = max(0.40, min(0.99, fill))
    return int(cap * fill)
