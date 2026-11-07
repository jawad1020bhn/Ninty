"""Team selection for the FC 27 engine.

This does NOT reimplement selection logic.  lib/ailineup.py already decides how
many changes to make for a big/normal/low-importance match and how to rest
players in a congested spell; lib/pitch.py supplies the position-distance
matrix and a min-cost assignment.  Both are pure functions with no save-format coupling,
so the engine drives them directly.

Two stages:
  base_xi()   pick the best legal XI for the formation shape (Hungarian on the
              position-distance matrix).  Used for a club's default selection.
  select()    ask ailineup how important the next match is, then let it rotate
              that XI.  Injured and suspended players are removed first, so the
              algorithm never picks someone who cannot play.
"""

import ailineup
import fc27
import pitch

from . import store as S
from . import roster as R
from .positions import formation_roles, line_of

RECENT_LOOK = 6


def age_on(st, pid, date=None):
    """Age at an in-game date. Save-aware: generated players have no db row."""
    return R.age(st, pid, date)


def available(st, tid):
    """Squad members who can play: not injured, not suspended."""
    out = []
    for pid in S.squad_of(st, tid):
        r = S.pstate(st, pid)
        if r is None:
            continue
        if r[S.P_INJ] > 0:
            continue
        if st.get('suspended', {}).get(str(pid), 0) > 0:
            continue
        out.append(int(pid))
    return out


def _squad_rows(st, tid, pids, date):
    """Shape ailineup.pick_xi expects: i, pid, pos, ovr, age, form, tired."""
    recent = st.get('recent', {})
    rows = []
    for i, pid in enumerate(pids):
        r = S.pstate(st, pid)
        rr = recent.get(str(pid)) or []
        form = (sum(x[1] for x in rr[-RECENT_LOOK:]) / len(rr[-RECENT_LOOK:]) - 6.3) if rr else 0.0
        rows.append(dict(i=i, pid=int(pid), pos=R.pos(st, pid),
                         ovr=r[S.P_OVR], age=age_on(st, pid, date),
                         form=round(form, 2), tired=r[S.P_FIT] < 70))
    return rows


def _pool(st, tid, need=11):
    """Playable squad, with an emergency fallback so a career cannot hard-crash.

    Injuries and bans can strip a small squad below 11. Rather than raise, the
    least-unavailable players are called up (shortest injury first, then bans)
    and the selection is flagged 'emergency'. Youth call-ups are the proper
    long-term answer and are a later increment.
    """
    pool = available(st, tid)
    if len(pool) >= need:
        return pool, False
    squad = [int(p) for p in S.squad_of(st, tid)]
    extra = [p for p in squad if p not in pool]

    def penalty(p):
        r = S.pstate(st, p) or [0] * S.P_LEN
        return (r[S.P_INJ], (st.get('suspended') or {}).get(str(p), 0))

    extra.sort(key=penalty)
    return pool + extra[:need - len(pool)], True


def base_xi(st, tid, pids=None, date=None):
    """Best legal XI for the club's formation. -> (xi pids, bench pids, roles)."""
    f, roles = _formation(st, tid)
    pool = _pool(st, tid)[0] if pids is None else [int(p) for p in pids]
    rows = _squad_rows(st, tid, pool, date or st['date'])
    if len(rows) < 11:
        raise S.SaveError('club %s has a squad of only %d players' % (tid, len(rows)))
    # Cost = how far the player is from the role, minus a small rating tiebreak.
    # Distance dominates (x100) so a striker is never preferred in goal merely
    # for being better; rating only breaks ties between equally legal options.
    cost = []
    for role in roles:
        cost.append([pitch.DIST[role][p['pos']] * 100 - p['ovr'] for p in rows])
    cols = pitch.hungarian(cost)
    xi = [rows[c]['pid'] for c in cols]
    used = set(xi)
    rest = [p for p in sorted(rows, key=lambda r: -r['ovr']) if p['pid'] not in used]
    gk = [p['pid'] for p in rest if p['pos'] == 0]
    bench = gk[:1] + [p['pid'] for p in rest if p['pid'] not in gk[:1]][:6]
    return xi, bench, roles


def _formation(st, tid):
    c = st['clubs'][str(int(tid))]
    want = int(c.get('formation') or 0)
    fs = fc27.club_formations(int(tid))
    if not fs:
        raise S.SaveError('club %s has no formation' % tid)
    f = next((x for x in fs if int(x['id']) == want), fs[0])
    return f, formation_roles(f['pos'])


def strength(tid):
    c = fc27.clubs().get(str(int(tid))) or {}
    return int(c.get('ovr') or 60)


def select(st, tid, opp=None, kind='league', congested=False):
    """Full selection for the next match, honouring importance and rotation.

    -> dict(xi, bench, roles, level, score, why, formation)
    """
    tid = int(tid)
    date = st['date']
    pool, emergency = _pool(st, tid)
    xi, bench, roles = base_xi(st, tid, pool, date)

    ctx = dict(kind=kind, my_str=strength(tid),
               opp_str=strength(opp) if opp is not None else None)
    table = st.get('tables', {}).get(str(st['clubs'][str(tid)]['league'])) or []
    if table:
        me = next((r for r in table if int(r['tid']) == tid), None)
        if me:
            ctx.update(pos=me['pos'], n=len(table), pts=me['pts'],
                       leader_pts=table[0]['pts'],
                       safe_pts=table[max(0, len(table) - 4)]['pts'],
                       progress=_progress(st))
    level, score, why = ailineup.importance(ctx)
    from .match import is_big
    if opp is not None and is_big(tid, opp):
        why = why + ['marquee']
        if level == 'low':
            level, score = 'normal', max(score, 1.0)

    rows = _squad_rows(st, tid, pool, date)
    by_pid = {r['pid']: r['i'] for r in rows}
    cur = [by_pid[p] for p in xi]
    if len(rows) >= 14 and any(r['pos'] == 0 for r in rows):
        xi_i, bench_i = ailineup.pick_xi(roles, rows, pitch.DIST, level,
                                         congested, '%s|%s|%s' % (st.get('seed', 1), tid, date), cur)
        xi = [rows[i]['pid'] for i in xi_i]
        bench = [rows[i]['pid'] for i in bench_i]
    if emergency:
        why = why + ['emergency_squad']
    return dict(xi=xi, bench=bench, roles=roles, level=level, score=score,
                why=why, emergency=emergency,
                formation=int(_formation(st, tid)[0]['id']))


def _progress(st):
    fs = [f for f in st['fixtures'] if f['kind'] == 'league']
    if not fs:
        return 0.0
    done = sum(1 for f in fs if f['played'])
    return round(done / float(len(fs)), 3)


def units(st, xi):
    """Split an XI into goalkeeper / defence / midfield / attack pid lists."""
    out = [[], [], [], []]
    for pid in xi:
        out[line_of(R.pos(st, pid))].append(int(pid))
    return out
