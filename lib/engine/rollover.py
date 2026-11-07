"""End-of-season rollover: age, grow, decline, retire, revalue, restock, restart.

A career that stops after one season is not a career. This module closes a season
and opens the next one, reusing the existing credited algorithms rather than
inventing new curves:

  lib/growth      month_plan() - development, decline, destiny, late bloomers
                  (Michele & Claude "Declino Selettivo", credited in that module)
  lib/revalue     merit()/new_value() - end-of-season revaluation
                  (Michele & Claude "Economia Lunga - rivalutazione")

Attribute deltas are stored in the SAVE as an overlay on the static database
rows, so the database is never mutated and stays the single source of truth for
a player's starting point.

All player facts are resolved through lib/engine/roster.py, because a career
contains generated players whose ids do not exist in the database.

Retirement and youth intake are engine choices, not database facts: upstream
ships `isretiring` = 0 for every player and no youth-intake rules. The choices
are documented at each function.
"""
import random

import fc27
import growth
import revalue

from . import store as S
from . import roster as R
from .posgroup import group_for
from .names import make_name

MONTHS_PER_SEASON = 12
RETIRE_MIN_AGE = 33
GK_ALLOWANCE = 3            # keepers are treated as this many years younger
RETIRE_BASE = 0.18          # per-year chance at RETIRE_MIN_AGE, scaled up by age
YOUTH_PER_CLUB = 2
MAX_SQUAD = 32              # hard ceiling during intake
TARGET_SQUAD = 26           # registration-list size clubs are trimmed back to
MIN_SQUAD = 20              # never strip a club below a playable squad
PROTECT_AGE = 21            # academy players are never the release valve
FREE_PATIENCE = 2           # seasons a free agent stays in the pool unsigned
HISTORY_KEEP = 20           # seasons of history retained in the save
HISTORY_MOVERS = 25         # risers/fallers kept per season, not all ~1,500

# A 17-year-old at a simulated club gets no first-team minutes, so scoring his
# development on minutes alone gave him ~0 growth and he could never close the
# gap to the seniors ahead of him. Real academies train and play reserve
# football, so young players get a training floor regardless of selection.
YOUTH_TRAIN_SHARE = 0.45
YOUTH_TRAIN_AGE = 21
NEW_PID_BASE = 9000000      # generated players live far above the real id space


def _team_matches(st, tid):
    return sum(1 for r in st['results'] if int(tid) in (int(r['home']), int(r['away'])))


# A career simulates one league (or a few), but the world holds all 717 clubs.
# Players at unsimulated clubs have no minutes - that is ABSENT evidence, not
# evidence of bad form. Treating zero apps as "benchwarmer" retired 1,224 of them
# in a single close. They get a neutral regular instead.
NEUTRAL_SHARE = 0.55
NEUTRAL_RATING = 6.3


def _simulated(st, tid):
    return _team_matches(st, tid) > 0


def develop(st, tid, pid, months=MONTHS_PER_SEASON, period=None):
    """Run one season of development for a player through lib/growth.month_plan.

    Returns the plan (points, decline, add, factors) without applying it.
    """
    pid = int(pid)
    row = S.pstate(st, pid)
    if row is None:
        return None
    pos = R.pos(st, pid)
    age = R.age(st, pid)
    s = S.stats_of(st, pid)
    played = _team_matches(st, tid)
    if played:
        share = min(1.0, s[S.S_MIN] / float(played * 90))
        rating = (s[S.S_RSUM] / s[S.S_APP]) if s[S.S_APP] else NEUTRAL_RATING
    else:
        share, rating = NEUTRAL_SHARE, NEUTRAL_RATING
    # Academy floor: a young player who is not selected still trains.
    if age <= YOUTH_TRAIN_AGE and share < YOUTH_TRAIN_SHARE:
        share = YOUTH_TRAIN_SHARE
        rating = max(rating, NEUTRAL_RATING)
    attrs = R.ab25_attrs(st, pid)
    prog = R.prog_of(st, pid)
    live = dict(attrs=attrs, form=row[S.P_FORM], aff=200, inj=0, _prog=prog)
    settings = growth.settings_for(pid, pos, (st.get('training') or {}))
    pot = R.potential(st, pid) or growth.potential(pid, age, row[S.P_OVR], pos)
    pl = dict(id=pid, pos=pos, age=age, ovr=row[S.P_OVR], dbspeed=attrs.get('Speed'))
    return growth.month_plan(pl, settings, live, dict(share=share, rating=rating),
                             False, months, period or ('%s-%s' % (st['season'], tid)),
                             pot=pot)


def _apply_plan(st, pid, plan):
    """Fold a growth plan into the save's attribute overlay and OVR."""
    if not plan:
        return 0
    pid_s = str(int(pid))
    ov = R.overlay_of(st, pid)
    for attr, delta in plan.get('add') or []:
        ov[attr] = int(ov.get(attr, 0)) + int(delta)
    R.set_overlay(st, pid, ov)
    R.set_prog(st, pid, plan.get('prog') or {})
    # Net attribute movement drives OVR at the module's own documented rate.
    net = sum(int(d) for _, d in (plan.get('add') or []))
    row = S.pstate(st, pid)
    if row is None:
        return 0
    carry = st.setdefault('ovrCarry', {}).get(pid_s, 0.0) + net / growth.PTS_PER_OVR
    step = int(carry) if carry > 0 else -int(-carry)
    st['ovrCarry'][pid_s] = round(carry - step, 3)
    if step:
        pot = plan.get('pot') or R.potential(st, pid) or 99
        row[S.P_OVR] = max(40, min(int(pot), row[S.P_OVR] + step))
    return step


def revalue_player(st, tid, pid):
    """End-of-season market value via the credited rivalutazione formula."""
    pid = int(pid)
    row = S.pstate(st, pid)
    if row is None:
        return None
    s = S.stats_of(st, pid)
    age = R.age(st, pid)
    played = _team_matches(st, tid)
    if played:
        apps, rsum = s[S.S_APP], s[S.S_RSUM]
    else:
        # No season here: assume a neutral regular season rather than scoring
        # him as someone who never played.
        apps, rsum = int(NEUTRAL_SHARE * 38), NEUTRAL_RATING * int(NEUTRAL_SHARE * 38)
    merit, vote, reg = revalue.merit(apps, played or 38, rsum,
                                     s[S.S_GOAL], s[S.S_AST], age)
    cur = max(1, int(row[S.P_VALUE] / 100))
    fair = revalue.fair_units(row[S.P_OVR], age)
    nv = revalue.new_value(cur, merit, fair)
    row[S.P_VALUE] = int(nv * 100)
    return dict(pid=pid, merit=round(merit, 3), value=row[S.P_VALUE])


def should_retire(st, pid, rnd):
    """Retirement is an engine rule; upstream ships isretiring = 0 for everyone.

    Chance rises with age past 33 and with a lack of minutes, and falls for
    players still performing. Goalkeepers get three extra years, matching the
    later maturity/decline ages lib/growth already uses for them.
    """
    pid = int(pid)
    row = S.pstate(st, pid)
    if row is None:
        return False
    pos = R.pos(st, pid)
    # Keepers last longer, so SUBTRACT the allowance: a 36-year-old keeper is
    # treated as 33. Adding it retired 30-year-old keepers as if they were 33.
    age = R.age(st, pid) - (GK_ALLOWANCE if pos == 0 else 0)
    if age < RETIRE_MIN_AGE:
        return False
    if age >= 40:
        return True
    p = RETIRE_BASE * (1.0 + 0.55 * (age - RETIRE_MIN_AGE))
    # Only judge by playing time where a season was actually simulated.
    if _simulated(st, S.club_of(st, pid) or 0):
        s = S.stats_of(st, pid)
        if s[S.S_APP] < 5:
            p *= 1.6
        elif s[S.S_APP] >= 25 and row[S.P_OVR] >= 75:
            p *= 0.35
    return rnd.random() < min(0.95, p)


def _new_pid(st):
    used = st.setdefault('nextPid', NEW_PID_BASE)
    st['nextPid'] = used + 1
    return used


def make_youth(st, tid, rnd, role=None):
    """Generate a 16-18 year old for a club's squad.

    Ability comes from regen_templates.regen, whose ages are YEARS (16-21) and
    which carry a matching `overall`, so attributes and rating stay consistent.
    The youth templates are 140-176 MONTHS (11-14 years old) - too young for a
    first-team squad - so they are used only for their shipped `potential`
    ceiling, never for a senior player's ability.

    Names come from regen_names.json; its pool ids are language groups, NOT
    nation ids, so no nationality is inferred from them.
    """
    templates = fc27.regen_templates()
    if role is None:
        counts = {}
        for p in S.squad_of(st, tid):
            r = R.pos(st, p)
            counts[r] = counts.get(r, 0) + 1
        # restock the thinnest line; a club with no keeper gets one first
        role = 0 if not counts.get(0) else min(range(13), key=lambda r: (counts.get(r, 0), r))
    grp = group_for(role)
    pool = [t for t in templates.get('regen', [])
            if int(t['posGroup']) == grp and 16 <= int(t['age']) <= 18]
    if not pool:
        pool = [t for t in templates.get('regen', []) if int(t['posGroup']) == grp]
    tpl = rnd.choice(pool) if pool else None
    ab = fc27.ea_ab()
    ea = {k: int(tpl.get(k, 45)) for k in ab} if tpl else {k: 45 for k in ab}
    ovr = int(tpl['overall']) if tpl else 50
    age = int(tpl['age']) if tpl else 17
    ceilings = [t.get('potential') for t in templates.get('youth', [])
                if int(t['posGroup']) == grp and t.get('potential')]
    pot = int(max(ceilings)) if ceilings else ovr + 18
    pot = max(ovr + 6, min(94, pot + rnd.randint(-6, 2)))
    # One language pool, and the gender flag of the club (85 of 717 are women's
    # sides). See lib/engine/names.py for how the flags were verified.
    full = make_name(rnd, tid)
    pid = _new_pid(st)
    year = int(st['season']) - age
    st.setdefault('generated', {})[str(pid)] = dict(
        name=full, role=int(role), age=age,
        ea=R.encode_named(ea, ab), startOvr=ovr,
        born='%d-%02d-%02d' % (year, rnd.randint(1, 12), rnd.randint(1, 28)),
        potential=pot, tid=int(tid), season=st['season'])
    S.squad_of(st, tid).append(pid)
    st['players'][str(pid)] = S.player_row(tid, ovr, revalue.fair_units(ovr, age) * 100,
                                           int(st['season']) + 3)
    st.setdefault('potentials', {})[str(pid)] = pot
    return pid


def release_player(st, pid, season):
    """Move a player out of his club into the free-agent pool.

    S.move_player cannot do this: club 0 is not a row in st['clubs'], it is the
    free-agent sentinel. The player stays in st['players'] so he can be signed
    again, and carries the season he was released for the patience rule.
    """
    pid = int(pid)
    row = S.pstate(st, pid)
    if row is None:
        return False
    tid = row[S.P_CLUB]
    club = st['clubs'].get(str(tid))
    if club and pid in club['squad']:
        club['squad'].remove(pid)
    row[S.P_CLUB] = 0
    free = st.setdefault('freeAgents', [])
    if pid not in free:
        free.append(pid)
    st.setdefault('freeSince', {})[str(pid)] = int(season)
    return True


def _release_value(st, pid):
    """Who a club lets go first: low ability, and no development left.

    Young players are protected separately - a club releasing its own academy
    intake to make room for that same intake would be nonsense.
    """
    row = S.pstate(st, pid)
    pot = R.potential(st, pid) or row[S.P_OVR]
    headroom = max(0, pot - row[S.P_OVR])
    return row[S.P_OVR] + 0.5 * headroom


def trim_squads(st, season, report, reserve=0):
    """Release surplus players so squads stay at a registration-list size.

    Without this the world only ever grows: intake added ~2 players per club per
    season and nothing ever left except retirees, so the population climbed
    21,623 -> 24,355 in three seasons while mean OVR fell 66.55 -> 64.75, and
    every squad clogged at the 32-man ceiling with youth who could never be
    selected. Clubs now carry TARGET_SQUAD and the surplus becomes signable.

    `reserve` leaves that many slots free for the incoming youth intake, so a
    club already at the target still gets an academy group.
    """
    target = max(MIN_SQUAD, TARGET_SQUAD - max(0, int(reserve)))
    for tid_s, club in st['clubs'].items():
        squad = club['squad']
        if len(squad) <= target:
            continue
        keepers = [p for p in squad if R.pos(st, p) == 0]
        # a club must keep two keepers and a playable squad
        protected = set(keepers[:2])
        protected.update(p for p in squad if R.age(st, p) <= PROTECT_AGE)
        pool = [p for p in squad if p not in protected]
        pool.sort(key=lambda p: (_release_value(st, p), -R.age(st, p), p))
        for pid in pool:
            if len(club['squad']) <= target:
                break
            if release_player(st, pid, season):
                report['released'].append(dict(pid=int(pid), name=R.name(st, pid),
                                               club=int(tid_s), age=R.age(st, pid)))
    return report


def cycle_free_agents(st, season, rnd, report):
    """Age the free-agent pool: retire the old, drop the long-unsigned.

    Only squad players used to be iterated at rollover, so the 1,920 database
    free agents never aged, never retired and never left - an immortal pool that
    grew with every release. An unsigned player is more likely to retire than a
    contracted one, and after FREE_PATIENCE seasons without a club he leaves the
    game entirely.
    """
    since = st.setdefault('freeSince', {})
    for pid in list(st.get('freeAgents') or []):
        row = S.pstate(st, pid)
        if row is None or row[S.P_CLUB] != 0:
            st['freeAgents'].remove(pid)
            since.pop(str(pid), None)
            continue
        born_season = since.get(str(pid))
        if born_season is None:
            since[str(pid)] = int(season)
            born_season = int(season)
        age = R.age(st, pid)
        # An unattached veteran has no club to keep training him.
        gone = age >= 34 and rnd.random() < min(0.9, 0.25 + 0.12 * (age - 34))
        if not gone and int(season) - int(born_season) >= FREE_PATIENCE:
            gone = age >= 28 or R.ovr(st, pid) < 62
        if gone:
            report['walked'].append(dict(pid=int(pid), name=R.name(st, pid), age=age))
            _remove_player(st, pid, season)


def _remove_player(st, pid, season):
    """Delete a player from the career and every index that references him.

    The club's squad list is an index too: leaving the pid there produced a
    squad slot with no player row, which crashed the next pass that read it.
    """
    k = str(int(pid))
    row = st['players'].get(k)
    if row is not None:
        club = st['clubs'].get(str(row[S.P_CLUB]))
        if club and int(pid) in club['squad']:
            club['squad'].remove(int(pid))
    xi = st['clubs'].get(str(row[S.P_CLUB])) if row is not None else None
    if xi and int(pid) in (xi.get('xi') or []):
        xi['xi'].remove(int(pid))
    st['players'].pop(k, None)
    for key in ('attrOverlay', 'growthProg', 'ovrCarry', 'potentials', 'stats',
                'previousStats', 'recent', 'suspended', 'generated', 'freeSince'):
        d = st.get(key)
        if isinstance(d, dict):
            d.pop(k, None)
    if int(pid) in (st.get('freeAgents') or []):
        st['freeAgents'].remove(int(pid))
    st.setdefault('retired', {})[k] = int(season)


def close_season(st):
    """Finish the season and start the next one. -> report dict.

    Order matters: develop and revalue using THIS season's minutes and ratings,
    then retire, then restock, then clear the per-season counters.
    """
    from .world import season_start
    from .fixtures import build_league_fixtures
    from .season import recompute_tables

    if not all(f['played'] for f in st['fixtures']):
        raise S.SaveError('the season is not finished')
    rnd = random.Random('%s|rollover|%s' % (st.get('seed', 1), st['season']))
    old = int(st['season'])
    report = dict(season=old, developed=0, risers=[], fallers=[], retired=[],
                  youth=[], released=[], walked=[], revalued=0, champions={})

    for lid, rows in (st.get('tables') or {}).items():
        if rows:
            report['champions'][lid] = dict(tid=rows[0]['tid'], name=rows[0]['name'],
                                            pts=rows[0]['pts'])

    # 1. development + revaluation, on this season's playing time
    for tid_s, club in st['clubs'].items():
        tid = int(tid_s)
        for pid in list(club['squad']):
            plan = develop(st, tid, pid)
            before = S.pstate(st, pid)[S.P_OVR]
            step = _apply_plan(st, pid, plan)
            if step:
                report['developed'] += 1
                rec = dict(pid=int(pid), name=R.name(st, pid), club=tid,
                           old=before, new=S.pstate(st, pid)[S.P_OVR], delta=step,
                           age=R.age(st, pid))
                (report['risers'] if step > 0 else report['fallers']).append(rec)
            if revalue_player(st, tid, pid):
                report['revalued'] += 1

    # 2. retirement
    lost_by_club = {}
    for tid_s, club in st['clubs'].items():
        for pid in list(club['squad']):
            if should_retire(st, pid, rnd):
                report['retired'].append(dict(pid=int(pid), name=R.name(st, pid),
                                              club=int(tid_s), age=R.age(st, pid)))
                lost_by_club[tid_s] = lost_by_club.get(tid_s, 0) + 1
                _remove_player(st, pid, old)

    # 3. make room BEFORE the intake. Trimming after it meant a club already at
    # TARGET_SQUAD had no space, so its academy produced nobody at all - which
    # silently excluded exactly the big clubs a manager is most likely to run.
    trim_squads(st, old, report, reserve=YOUTH_PER_CLUB)

    # 4. youth intake: a standard academy group, plus cover for retirees
    for tid_s, club in st['clubs'].items():
        lost = lost_by_club.get(tid_s, 0)
        for _ in range(lost + YOUTH_PER_CLUB):
            if len(club['squad']) >= min(MAX_SQUAD, TARGET_SQUAD):
                break
            pid = make_youth(st, int(tid_s), rnd)
            report['youth'].append(dict(pid=pid, name=R.name(st, pid), club=int(tid_s)))
        # A club must always be able to field a side. R.pos, NOT
        # fc27.positions: a generated keeper is invisible to the database, so
        # the old test never became true and this loop span forever.
        for _ in range(4):
            if len([p for p in club['squad'] if R.pos(st, p) == 0]) >= 2:
                break
            pid = make_youth(st, int(tid_s), rnd, role=0)
            report['youth'].append(dict(pid=pid, name=R.name(st, pid), club=int(tid_s)))

    # 5. age the free-agent pool (squads were already trimmed before intake)
    cycle_free_agents(st, old, rnd, report)

    report['risers'].sort(key=lambda r: -r['delta'])
    report['fallers'].sort(key=lambda r: r['delta'])
    report['counts'] = {k: len(report[k]) for k in
                        ('risers', 'fallers', 'retired', 'youth', 'released', 'walked')}
    # Keep the headline movers, not all ~1,500 rows: three seasons of full lists
    # cost 2.26 MB and pushed a 3-season save to 15 MB. The caller still gets the
    # complete report; only the archived copy is abbreviated.
    archive = dict(report)
    for k in ('risers', 'fallers', 'retired', 'youth', 'released', 'walked'):
        archive[k] = report[k][:HISTORY_MOVERS]
    hist = st.setdefault('history', [])
    hist.append(archive)
    del hist[:-HISTORY_KEEP]

    # 4. new season
    st['season'] = old + 1
    st['date'] = season_start(old + 1).isoformat()
    st['previousStats'] = st.get('stats') or {}
    st['stats'] = {}
    st['recent'] = {}
    st['suspended'] = {}
    st['results'] = []
    for row in st['players'].values():
        row[S.P_FIT] = 100
        row[S.P_INJ] = 0
        row[S.P_FORM] = 4
        if row[S.P_CONTRACT] <= old + 1:
            row[S.P_CONTRACT] = old + 1 + rnd.randint(2, 4)
    fx, _ = build_league_fixtures(st['leagues'], old + 1, int(st.get('seed', 1)) + old + 1)
    st['fixtures'] = fx
    st['nextFixture'] = 0
    recompute_tables(st)
    return report
