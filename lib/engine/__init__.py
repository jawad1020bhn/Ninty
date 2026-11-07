"""The FC 27 career engine - a separate game with its own save.

This package is the engine the FC 27 database was prepared for.  It is
deliberately independent of the PES career: it never reads or writes a PES save,
never needs mlsave/mlwrite state, and keeps its own JSON careers under
data/saves/.  The database (lib/fc27.py) supplies static facts; everything that
changes during a career lives in the save.

    from engine import career
    st = career.new(club=9, manager='You')      # Liverpool
    career.play_next(st)                        # simulate the next fixture
    career.advance(st, days=7)                  # run a week of the season
    career.save(st)                             # atomic write
    st = career.load(st['id'])

Existing, credited algorithms are reused rather than reimplemented:
  lib/ailineup    how many changes to make for a big/normal/low match
  lib/mlwrite     position-distance matrix + Hungarian assignment (pure helpers)
  lib/formengine  the 0-7 Form level from real match ratings
  lib/revalue     the valuation curve used to seed market values

Match simulation uses EA's 34 raw attributes, because the 25-attribute PES
projection drops nine match-relevant fields (see lib/fc27.py).
"""
from . import store as _save
from . import world, fixtures, lineup, match, season

SaveError = _save.SaveError


def new(club, manager='You', leagues=None, seed=None, sid=None, year=None):
    """Create a career. Does not write it; call save() for that."""
    return world.build(club, manager=manager, leagues=leagues, seed=seed,
                       sid=sid, year=year)


def save(st, sid=None):
    return _save.save(st, sid)


def load(sid):
    return _save.load(sid)


def list_saves():
    return _save.list_saves()


def delete(sid):
    return _save.delete(sid)


def play_next(st, tid=None):
    return season.play_next(st, tid)


def advance(st, days=1, limit=None):
    return season.advance(st, days=days, limit=limit)


def play_fixture(st, fixture, seed=None):
    return season.play_fixture(st, fixture, seed=seed)


def table(st, lid=None):
    return season.table_for(st, lid)


def scorers(st, lid=None, limit=20):
    return season.top_scorers(st, lid, limit)


def summary(st):
    return season.summary(st)


def next_fixture(st, tid=None):
    return fixtures.next_for(st, tid if tid is not None else st['club'])


def upcoming(st, tid=None, limit=10):
    return fixtures.upcoming(st, tid, limit)


def squad(st, tid=None):
    """A club's squad with career state, sorted starters-first then by rating."""
    import fc27
    from . import roster as R
    tid = int(tid if tid is not None else st['club'])
    meta = fc27.squad_meta().get(str(tid)) or {}
    out = []
    for pid in _save.squad_of(st, tid):
        r = _save.pstate(st, pid)
        if r is None:
            continue
        s = _save.stats_of(st, pid)
        m = meta.get(str(pid)) or [0, 2, 0]
        out.append(dict(
            pid=int(pid), name=R.name(st, pid), shirt=m[0], role=m[1],
            pos=R.pos(st, pid), ovr=r[_save.P_OVR],
            age=R.age(st, pid), form=r[_save.P_FORM],
            fitness=r[_save.P_FIT], injury=r[_save.P_INJ],
            suspended=(st.get('suspended') or {}).get(str(pid), 0),
            value=r[_save.P_VALUE], contract=r[_save.P_CONTRACT],
            apps=s[_save.S_APP], goals=s[_save.S_GOAL], assists=s[_save.S_AST],
            rating=round(s[_save.S_RSUM] / s[_save.S_APP], 2) if s[_save.S_APP] else 0.0))
    out.sort(key=lambda p: (p['role'], -p['ovr']))
    return out


def select(st, tid=None, opp=None):
    tid = int(tid if tid is not None else st['club'])
    return lineup.select(st, tid, opp)


def move_player(st, pid, to_tid):
    return _save.move_player(st, pid, to_tid)


def season_finished(st):
    """True when every fixture in the career's leagues has been played."""
    fx = st.get('fixtures') or []
    return bool(fx) and all(f['played'] for f in fx)


def finish_season(st):
    """Play out every remaining fixture so the season can be closed."""
    return season.finish_season(st)


def close_season(st):
    """Roll the career into the next season. Raises SaveError if unfinished.

    Ages and develops every player, retires the old, revalues the market, brings
    through a youth intake, releases the surplus and opens the next fixture list.
    Returns the report; the caller decides when to save().
    """
    from . import rollover
    return rollover.close_season(st)


def history(st, limit=10):
    """Archived season reports, newest first (movers abbreviated on disk)."""
    return list(reversed((st.get('history') or [])[-int(limit):]))


__all__ = ['new', 'save', 'load', 'list_saves', 'delete', 'play_next', 'advance',
           'play_fixture', 'table', 'scorers', 'summary', 'next_fixture',
           'upcoming', 'squad', 'select', 'move_player', 'SaveError',
           'season_finished', 'finish_season', 'close_season', 'history']
