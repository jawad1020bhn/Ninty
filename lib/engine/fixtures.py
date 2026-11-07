"""Fixture generation.

Upstream `fixtures` ships with 0 rows, so the schedule is the engine's job.
This is a seeded double round-robin (every pair meets home and away) laid onto
a Saturday calendar with midweek rounds added only when a division has more
rounds than available Saturdays.

Engine conventions, stated because they are choices and not database facts:
  * the season opens on the first Saturday of August and ends in May;
  * the first Saturday of September, October, November and March is an
    international break, so no domestic round is placed there;
  * extra rounds go on the Wednesday of an existing match week.

Everything is deterministic for a given (league, year, seed).
"""
import datetime
import random

BREAK_MONTHS = (9, 10, 11, 3)


def _round_robin(teams, seed):
    """Circle method -> list of rounds, each a list of (home, away)."""
    teams = [int(t) for t in teams]
    if len(teams) < 2:
        return []
    random.Random(seed).shuffle(teams)
    bye = len(teams) % 2
    if bye:
        teams.append(None)
    n = len(teams)
    idx = list(range(n))
    rounds = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = teams[idx[i]], teams[idx[n - 1 - i]]
            if a is None or b is None:
                continue
            if r % 2:
                a, b = b, a
            pairs.append((a, b))
        rounds.append(pairs)
        idx = [idx[0], idx[-1]] + idx[1:-1]
    return rounds


def _match_dates(n_rounds, year):
    """Saturdays Aug->May, minus international breaks, plus Wednesdays if needed."""
    from .world import season_start
    d = season_start(year)
    end = datetime.date(year + 1, 5, 31)
    sat = []
    while d <= end:
        broken = d.month in BREAK_MONTHS and d.day <= 7
        if not broken:
            sat.append(d)
        d += datetime.timedelta(days=7)
    dates = list(sat)
    if n_rounds > len(dates):
        need = n_rounds - len(dates)
        wed = [s + datetime.timedelta(days=4) for s in sat]
        # spread midweek rounds evenly instead of bunching them at the start
        step = max(1, len(wed) // max(1, need))
        picked = wed[::step][:need]
        if len(picked) < need:
            picked += [w for w in wed if w not in picked][:need - len(picked)]
        dates = sorted(dates + picked)
    if len(dates) < n_rounds:
        raise ValueError('cannot fit %d rounds into the season (%d slots)'
                         % (n_rounds, len(dates)))
    return dates[:n_rounds]


def build_league_fixtures(leagues, year, seed):
    """-> (fixtures list, {league id: [fixture index, ...]})."""
    import fc27
    db = fc27.leagues()
    fixtures = []
    by_league = {}
    for lid in leagues:
        lg = db.get(str(int(lid)))
        if not lg:
            raise ValueError('unknown league %s' % lid)
        teams = lg['teams']
        first = _round_robin(teams, seed + int(lid))
        second = [[(b, a) for a, b in rd] for rd in first]
        rounds = first + second
        dates = _match_dates(len(rounds), year)
        ids = []
        for ri, (rd, day) in enumerate(zip(rounds, dates), start=1):
            for home, away in rd:
                ids.append(len(fixtures))
                fixtures.append(dict(
                    id=len(fixtures), comp=int(lid), kind='league', round=ri,
                    date=day.isoformat(), home=int(home), away=int(away),
                    played=False))
        by_league[str(int(lid))] = ids
    fixtures.sort(key=lambda f: (f['date'], f['comp'], f['id']))
    for i, f in enumerate(fixtures):
        f['id'] = i
    by_league = {}
    for f in fixtures:
        by_league.setdefault(str(f['comp']), []).append(f['id'])
    return fixtures, by_league


def upcoming(st, tid=None, limit=10):
    out = []
    for f in st['fixtures']:
        if f['played']:
            continue
        if tid is not None and int(tid) not in (f['home'], f['away']):
            continue
        out.append(f)
        if len(out) >= limit:
            break
    return out


def next_for(st, tid):
    u = upcoming(st, tid, limit=1)
    return u[0] if u else None


def due(st, date):
    return [f for f in st['fixtures'] if not f['played'] and f['date'] <= date]
