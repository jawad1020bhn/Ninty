"""Season progression: play fixtures, update state, derive tables and form.

The engine owns everything upstream does not ship: fixtures, results, league
tables, minutes, discipline and injuries.  Static facts stay in the database.

Form is NOT recomputed with a new formula.  Each result is appended to a
per-player recent-ratings list and lib/formengine.compute derives the 0-7 Form
level exactly as it does for the PES career, so the UI keeps its existing
meaning.
"""
import datetime

import fc27
import formengine

from . import store as S
from . import lineup, match
from . import roster as R
from .positions import line_of

POINTS_WIN, POINTS_DRAW = 3, 1
FITNESS_MATCH_COST = 22
FITNESS_DAILY_RECOVERY = 9
SUSPENSION_YELLOW_TOT = 5


def _date(s):
    return datetime.date(*(int(x) for x in str(s)[:10].split('-')))


def _iso(d):
    return d.isoformat()


def recompute_tables(st):
    """Rebuild every league table from the results list (single source of truth)."""
    tables = {}
    for lid in st.get('leagues', []):
        teams = [int(t) for t, c in st['clubs'].items() if int(c['league']) == int(lid)]
        row = {t: dict(tid=t, name=st['clubs'][str(t)]['name'], pl=0, w=0, d=0, l=0,
                       gf=0, ga=0, pts=0, form=[]) for t in teams}
        for r in st['results']:
            if int(r['comp']) != int(lid) or r.get('kind') != 'league':
                continue
            h, a = int(r['home']), int(r['away'])
            if h not in row or a not in row:
                continue
            hg, ag = int(r['sc'][0]), int(r['sc'][1])
            rh, ra = row[h], row[a]
            for x in (rh, ra):
                x['pl'] += 1
            rh['gf'] += hg; rh['ga'] += ag
            ra['gf'] += ag; ra['ga'] += hg
            if hg > ag:
                rh['w'] += 1; ra['l'] += 1; rh['pts'] += POINTS_WIN
                rh['form'].append('W'); ra['form'].append('L')
            elif hg < ag:
                ra['w'] += 1; rh['l'] += 1; ra['pts'] += POINTS_WIN
                ra['form'].append('W'); rh['form'].append('L')
            else:
                rh['d'] += 1; ra['d'] += 1
                rh['pts'] += POINTS_DRAW; ra['pts'] += POINTS_DRAW
                rh['form'].append('D'); ra['form'].append('D')
        ordered = sorted(row.values(),
                         key=lambda r: (-r['pts'], -(r['gf'] - r['ga']), -r['gf'], r['name']))
        for i, r in enumerate(ordered, start=1):
            r['pos'] = i
            r['gd'] = r['gf'] - r['ga']
            r['form'] = r['form'][-5:]
        tables[str(int(lid))] = ordered
    st['tables'] = tables
    return tables


def play_fixture(st, fixture, seed=None):
    """Simulate one fixture and apply it to the save. -> result."""
    if fixture.get('played'):
        raise S.SaveError('fixture %s already played' % fixture.get('id'))
    home, away = int(fixture['home']), int(fixture['away'])
    hsel = lineup.select(st, home, away, kind=fixture.get('kind', 'league'))
    asel = lineup.select(st, away, home, kind=fixture.get('kind', 'league'))
    res = match.simulate(st, fixture, hsel['xi'], asel['xi'],
                         hsel['bench'], asel['bench'], seed=seed)
    res['lineups'] = {str(home): hsel, str(away): asel}
    _apply(st, fixture, res)
    return res


def _apply(st, fixture, res):
    fixture['played'] = True
    fixture['score'] = list(res['sc'])
    st['results'].append(res)
    home, away = int(res['home']), int(res['away'])

    for pid, tid, g, a, rating in res['rows']:
        pid = int(pid)
        S.bump(st, pid, S.S_APP, 1)
        S.bump(st, pid, S.S_GOAL, g)
        S.bump(st, pid, S.S_AST, a)
        S.bump(st, pid, S.S_RSUM, rating)
        S.bump(st, pid, S.S_MIN, res['minutes'].get(str(pid), 0))
        ga = res['sc'][1] if tid == home else res['sc'][0]
        if ga == 0 and R.pos(st, pid) <= 3:
            S.bump(st, pid, S.S_CS, 1)
        rec = st.setdefault('recent', {}).setdefault(str(pid), [])
        rec.append([res['date'], rating, tid])
        del rec[:-12]

    for pid, n in (res.get('cards') or {}).items():
        pid = int(pid)
        if n >= 2:
            S.bump(st, pid, S.S_RED, 1)
            st.setdefault('suspended', {})[str(pid)] = 2
        else:
            S.bump(st, pid, S.S_YEL, 1)
            tot = S.stats_of(st, pid)[S.S_YEL]
            if tot and tot % SUSPENSION_YELLOW_TOT == 0:
                st.setdefault('suspended', {})[str(pid)] = 1

    for pid, days in (res.get('injuries') or {}).items():
        r = S.pstate(st, pid)
        if r:
            r[S.P_INJ] = max(r[S.P_INJ], int(days))

    for pid, mins in (res.get('minutes') or {}).items():
        r = S.pstate(st, pid)
        if r and mins > 0:
            cost = int(FITNESS_MATCH_COST * (mins / 90.0))
            r[S.P_FIT] = max(20, r[S.P_FIT] - cost)

    # A ban is served by MISSING a match, so decrement only squad members who
    # did not play. Doing this here (not in play_next) means advance() serves
    # bans too - previously they were never cleared on that path.
    serve_bans(st, home, res)
    serve_bans(st, away, res)
    _update_form(st, home)
    _update_form(st, away)
    recompute_tables(st)


def _update_form(st, tid):
    """Derive Form via the existing, credited algorithm - no new formula."""
    mine = [r for r in st['results'] if tid in (int(r['home']), int(r['away']))]
    if not mine:
        return
    ms = [dict(home=int(r['home']), sc=r['sc'], rows=r['rows']) for r in mine]
    out = formengine.compute(ms, int(tid), lambda p: R.pos(st, p))
    for pid, info in out.items():
        r = S.pstate(st, pid)
        if r:
            r[S.P_FORM] = int(info['level'])


def advance(st, days=1, limit=None):
    """Move the clock forward, playing every fixture that falls due.

    -> dict(date, played=[result...], news=[...])
    """
    days = max(0, int(days))
    target = _iso(_date(st['date']) + datetime.timedelta(days=days))
    played = []
    for _ in range(days + 1):
        _tick_day(st)
        due = [f for f in st['fixtures'] if not f['played'] and f['date'] <= st['date']]
        for f in due:
            if limit is not None and len(played) >= limit:
                break
            played.append(play_fixture(st, f))
        if st['date'] >= target:
            break
        st['date'] = _iso(_date(st['date']) + datetime.timedelta(days=1))
    st['date'] = target
    return dict(date=st['date'], played=played, count=len(played))


def _tick_day(st):
    """One day of recovery: fitness back up, injuries and bans served."""
    for r in st['players'].values():
        if r[S.P_FIT] < 100:
            r[S.P_FIT] = min(100, r[S.P_FIT] + FITNESS_DAILY_RECOVERY)
        if r[S.P_INJ] > 0:
            r[S.P_INJ] -= 1
    return st


def serve_bans(st, tid, res=None):
    """After a club plays, decrement bans for players who sat it out."""
    susp = st.get('suspended') or {}
    if not susp:
        return
    played = {int(p) for p in (res or {}).get('minutes', {}) if res['minutes'][p] > 0}
    for pid in S.squad_of(st, tid):
        k = str(pid)
        if susp.get(k, 0) > 0 and int(pid) not in played:
            susp[k] -= 1
            if susp[k] <= 0:
                susp.pop(k, None)


def play_next(st, tid=None):
    """Play the managed club's next fixture (or the next overall). -> result|None."""
    f = lineup_next(st, tid if tid is not None else st['club'])
    if f is None:
        return None
    st['date'] = f['date']
    return play_fixture(st, f)


def lineup_next(st, tid):
    for f in st['fixtures']:
        if not f['played'] and int(tid) in (int(f['home']), int(f['away'])):
            return f
    return None


def table_for(st, lid=None):
    lid = int(lid if lid is not None else st['clubs'][str(st['club'])]['league'])
    return st['tables'].get(str(lid)) or []


def top_scorers(st, lid=None, limit=20):
    lid = int(lid if lid is not None else st['clubs'][str(st['club'])]['league'])
    teams = {int(t) for t, c in st['clubs'].items() if int(c['league']) == lid}
    rows = []
    for pid_s, s in st['stats'].items():
        r = S.pstate(st, pid_s)
        if not r or r[S.P_CLUB] not in teams or not s[S.S_APP]:
            continue
        rows.append(dict(pid=int(pid_s), name=R.name(st, int(pid_s)),
                         club=r[S.P_CLUB], clubName=fc27.team_name(r[S.P_CLUB]),
                         apps=s[S.S_APP], goals=s[S.S_GOAL], assists=s[S.S_AST],
                         rating=round(s[S.S_RSUM] / s[S.S_APP], 2)))
    rows.sort(key=lambda r: (-r['goals'], -r['assists'], -r['rating']))
    return rows[:limit]


def finish_season(st):
    """Simulate every remaining fixture, so the season can be closed.

    play_next() only advances the MANAGED club's fixtures, so after its 38 games
    the other 342 league matches are still unplayed and close_season() rightly
    refuses. This walks the calendar day by day to the last fixture date, which
    keeps recovery, injuries, bans and form ticking exactly as advance() does
    rather than playing the tail in one undated batch.

    -> dict(count, date, complete)
    """
    left = [f for f in st['fixtures'] if not f['played']]
    if not left:
        return dict(count=0, date=st['date'], complete=True)
    last = max(f['date'] for f in left)
    days = (_date(last) - _date(st['date'])).days
    if days > 0:
        r = advance(st, days=days)
        n = r['count']
    else:
        n = 0
    # Anything still due on the final date itself.
    for f in [f for f in st['fixtures'] if not f['played'] and f['date'] <= st['date']]:
        play_fixture(st, f)
        n += 1
    return dict(count=n, date=st['date'], complete=season_complete(st))


def season_complete(st):
    return all(f['played'] for f in st['fixtures'])


def summary(st):
    done = sum(1 for f in st['fixtures'] if f['played'])
    return dict(id=st['id'], club=st['club'], clubName=st.get('clubName'),
                manager=(st.get('manager') or {}).get('name'), date=st['date'],
                season=st['season'], played=done, total=len(st['fixtures']),
                complete=season_complete(st), results=len(st['results']))
