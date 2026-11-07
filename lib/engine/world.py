"""Build a career world from the FC 27 database.

The database supplies every static fact; this module turns it into mutable
career state (squads that can change, ratings that can grow, budgets, morale)
and generates a fixture list, because upstream ships `fixtures` with 0 rows -
the schedule is genuinely the engine's job, not missing data.

Scope of this increment: domestic league football for the chosen competitions.
Every club and player in the database exists in the world (so the transfer
market is global), but only `leagues` get a fixture list. Cup and continental
scheduling is a later increment; see README.
"""
import datetime
import random

import fc27
import revalue

from . import store as S
from .positions import formation_roles

SEASON_START_MONTH = 8
FIRST_MATCH_DAY = 1


def _budget(club, squad):
    """Transfer budget from club worth.

    `worth` is a valuation in thousands of EUR (Liverpool 5,430,000 -> 5.43bn).
    A transfer kitty is a fraction of that, floored so tiny clubs can still buy.
    """
    worth = int(club.get('worth') or 0) * 1000
    return max(250000, int(worth * 0.03))


def _wage_budget(squad, contracts):
    weekly = sum(int((contracts.get(str(p)) or {}).get('value') or 0) for p in squad)
    return max(20000, int(weekly * 1.15))


def season_start(year):
    """First Saturday of August - the conventional European season opener."""
    d = datetime.date(year, SEASON_START_MONTH, FIRST_MATCH_DAY)
    while d.weekday() != 5:
        d += datetime.timedelta(days=1)
    return d


def build(club, manager='You', leagues=None, seed=None, sid=None, year=None):
    club = int(club)
    clubs_db = fc27.clubs()
    if str(club) not in clubs_db:
        raise S.SaveError('unknown club %s' % club)
    meta = fc27.meta()
    if year is None:
        year = int((meta.get('asOf') or '2026-08-01')[:4])
    if leagues is None:
        leagues = [int(clubs_db[str(club)]['league'])]
    leagues = [int(x) for x in leagues]
    seed = int(seed if seed is not None else random.randrange(1 << 30))

    ratings = fc27.ratings()
    contracts = fc27.contracts()
    squads_db = fc27.squads()
    formations = fc27.formations()

    # Invert the squad map once: scanning 717 squads for each of 21,623 players
    # is 15M membership tests, which made world creation take ~20s.
    club_of = {}
    for tid, sq in squads_db.items():
        for p in sq:
            club_of[str(p)] = int(tid)

    players = {}
    for pid_s, r in ratings.items():
        ct = contracts.get(pid_s) or {}
        players[pid_s] = S.player_row(
            club=club_of.get(pid_s, 0),
            ovr=r[0], value=_market_value(r),
            contract=ct.get('contract') or (year + 2),
            form=4, fit=100, morale=70)

    clubs = {}
    for tid, c in clubs_db.items():
        squad = [int(p) for p in squads_db.get(tid, [])]
        fs = formations.get(tid) or []
        clubs[tid] = dict(
            name=c['name'], league=int(c['league']),
            squad=squad, budget=_budget(c, squad), wageBudget=_wage_budget(squad, contracts),
            formation=int(fs[0]['id']) if fs else 0,
            xi=[int(p) for p in fc27.starting_xi(int(tid))],
            reputation=int(c.get('prestige') or 5))

    # Free agents are in the database with no club; keep them available to sign.
    free = [int(r[0]) for r in fc27.players()
            if str(r[0]) in players and players[str(r[0])][S.P_CLUB] == 0]

    from .fixtures import build_league_fixtures
    fixtures, by_league = build_league_fixtures(leagues, year, seed)

    st = dict(
        v=S.SCHEMA, id=sid or S.new_id(clubs_db[str(club)]['name']),
        created='', club=club, clubName=clubs_db[str(club)]['name'],
        manager=dict(name=str(manager)[:48], nation=0),
        date=season_start(year).isoformat(), season=year, seed=seed,
        dbAsOf=meta.get('asOf', ''), leagues=leagues,
        players=players, clubs=clubs, stats={}, freeAgents=free,
        fixtures=fixtures, results=[], news=[], transfers=[],
        tables={str(l): [] for l in leagues}, nextFixture=0)
    st['created'] = st['modified'] = ''
    from .season import recompute_tables
    recompute_tables(st)
    return st


def _market_value(r):
    """Seed market value from the existing, credited valuation curve."""
    return int(revalue.fair_units(r[0], r[1]) * 100)


def formation_of(st, tid):
    """The club's chosen formation as EA slot ids, plus its POSN roles."""
    c = st['clubs'][str(int(tid))]
    for f in fc27.club_formations(int(tid)):
        if int(f['id']) == int(c.get('formation') or 0):
            return f, formation_roles(f['pos'])
    fs = fc27.club_formations(int(tid))
    if not fs:
        raise S.SaveError('club %s has no formation' % tid)
    return fs[0], formation_roles(fs[0]['pos'])
