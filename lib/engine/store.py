"""The FC 27 career save: the engine's own state, independent of any PES file.

Design rule: the database is authoritative for STATIC facts (names, attributes,
nationality, birthday, stadium, formation shape).  The save holds only what the
career CHANGES.  That keeps saves small, makes a database update non-destructive,
and means there is exactly one source of truth for each fact.

Nothing here reads or writes a PES save.  lib/mlsave.py and lib/mlwrite.py are
not imported for storage; the engine's state is plain JSON under data/saves/.

Player rows are compact arrays, matching the convention of data/fc27/ratings.json.
Use the P_* / S_* constants and the helpers rather than raw indices.
"""
import json
import os
import re
import time

import jsafe

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(HERE, 'data', 'saves')

SCHEMA = 1

# player row: mutable career state only
P_CLUB, P_OVR, P_FORM, P_FIT, P_INJ, P_MORALE, P_VALUE, P_CONTRACT = range(8)
P_LEN = 8
# season stats row, present only for players who have actually played
S_APP, S_GOAL, S_AST, S_RSUM, S_MIN, S_YEL, S_RED, S_CS = range(8)
S_LEN = 8

ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


class SaveError(Exception):
    pass


def path_for(sid):
    if not ID_RE.match(str(sid or '')):
        raise SaveError('invalid save id: %r' % (sid,))
    return os.path.join(DIR, '%s.json' % sid)


def new_id(club_name='career'):
    slug = re.sub(r'[^a-z0-9]+', '-', str(club_name).lower()).strip('-')[:24] or 'career'
    return '%s-%x' % (slug, int(time.time() * 1000) & 0xFFFFFFFFFF)


def player_row(club, ovr, value, contract, form=4, fit=100, morale=70):
    return [int(club), int(ovr), int(form), int(fit), 0, int(morale),
            int(value), int(contract)]


def stats_row():
    return [0] * S_LEN


def save(state, sid=None):
    """Atomically write a career. Returns the path."""
    sid = sid or state.get('id')
    p = path_for(sid)
    os.makedirs(DIR, exist_ok=True)
    state['id'] = sid
    state['modified'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    state.setdefault('v', SCHEMA)
    jsafe.jdump(state, p, ensure_ascii=False, separators=(',', ':'))
    return p


def load(sid):
    p = path_for(sid)
    if not os.path.exists(p):
        raise SaveError('no such career: %s' % sid)
    with open(p, encoding='utf-8') as fh:
        st = json.load(fh)
    v = int(st.get('v') or 0)
    if v > SCHEMA:
        raise SaveError('career %s is schema %d, this build understands %d'
                        % (sid, v, SCHEMA))
    if v < SCHEMA:
        st = _migrate(st, v)
    _validate(st)
    return st


def _migrate(st, v):
    """Forward migration hook. Schema 1 is the first, so nothing to do yet."""
    st['v'] = SCHEMA
    return st


def _validate(st):
    for k in ('id', 'club', 'date', 'season', 'players', 'clubs', 'fixtures'):
        if k not in st:
            raise SaveError('career is missing %r' % k)
    bad = [p for p, r in st['players'].items() if not isinstance(r, list) or len(r) != P_LEN]
    if bad:
        raise SaveError('%d player rows have the wrong shape (e.g. %s)' % (len(bad), bad[0]))
    if str(st['club']) not in st['clubs']:
        raise SaveError('managed club %s is not in the career world' % st['club'])


def list_saves():
    if not os.path.isdir(DIR):
        return []
    out = []
    for f in sorted(os.listdir(DIR)):
        if not f.endswith('.json'):
            continue
        try:
            with open(os.path.join(DIR, f), encoding='utf-8') as fh:
                st = json.load(fh)
            out.append(dict(id=st.get('id', f[:-5]), club=st.get('club'),
                            clubName=st.get('clubName', ''), date=st.get('date'),
                            season=st.get('season'), manager=(st.get('manager') or {}).get('name', ''),
                            modified=st.get('modified', '')))
        except (ValueError, OSError):
            continue
    return sorted(out, key=lambda r: r.get('modified') or '', reverse=True)


def delete(sid):
    p = path_for(sid)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False


# ------------------------------------------------------------------ accessors
def pstate(st, pid):
    return st['players'].get(str(int(pid)))


def club_of(st, pid):
    r = pstate(st, pid)
    return r[P_CLUB] if r else None


def ovr_of(st, pid):
    r = pstate(st, pid)
    return r[P_OVR] if r else 0


def stats_of(st, pid):
    return st['stats'].get(str(int(pid))) or stats_row()


def bump(st, pid, idx, n=1):
    k = str(int(pid))
    row = st['stats'].get(k)
    if row is None:
        row = st['stats'][k] = stats_row()
    row[idx] += n
    return row[idx]


def squad_of(st, tid):
    """Current squad of a club, from mutable state (transfers move players)."""
    return st['clubs'][str(int(tid))]['squad']


def move_player(st, pid, to_tid):
    """Transfer a player between clubs, keeping both squads consistent."""
    k = str(int(pid))
    row = st['players'].get(k)
    if row is None:
        raise SaveError('unknown player %s' % pid)
    frm = row[P_CLUB]
    to_tid = int(to_tid)
    if frm == to_tid:
        return False
    a = st['clubs'].get(str(frm))
    b = st['clubs'].get(str(to_tid))
    if b is None:
        raise SaveError('unknown destination club %s' % to_tid)
    if a and int(pid) in a['squad']:
        a['squad'].remove(int(pid))
    if int(pid) not in b['squad']:
        b['squad'].append(int(pid))
    row[P_CLUB] = to_tid
    return True
