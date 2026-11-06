"""fc27.py - EA SPORTS FC 27 database for The Gaffer as a standalone game.

The JSON under data/fc27 is produced at BUILD time by tools/import_fc27.mjs
from the eafc-db-kit FC 27 templates.  At runtime this module is pure stdlib:
no Node, no npm, no network.  That keeps the double-click launch working.

Files (see data/fc27/fc27_meta.json for the exact field mapping):
  players.json    [[pid, full_name, short_name], ...]      app-wide contract
  ratings.json    {ab: [25 attrs], f: '...', p: {pid: [ovr,age,h,w,foot,
                   style,wfu,wfa,form,inj,attrs]}}         app-wide contract
  positions.json  {pid: 0..12}                             index into POSN
  playpos.json    {pid: '13 digits'}                       0 none, 1 B, 2 A
  teamids.json    {tid: club name}                         app-wide contract
  comps.json      {lid: {name, name_en, kind}}             app-wide contract
  clubs.json      {tid: {colours, stadium, prestige, worth, ...}}
  leagues.json    {lid: {name, country, level, kind, women, teams}}
  squads.json     {tid: [pid, ...]}
  nations.json    {nationid: {name, iso, confed}}
  nats.json       {pid: nationid}
  potential.json  {pid: potential}
  birthdays.json  {pid: 'YYYY-MM-DD'}
  contract.json   {pid: {value, contract, release, intRep, gender, natPos}}

The first six files are the same schema the existing algorithms already read
through server._dbf(), so market/growth/negotiate/aitransfers keep working
unchanged on FC 27 data.
"""
import json
import os
import threading
import unicodedata

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(HERE, 'data', 'fc27')

# Same order as server.POSN_ABBR and lib/dbimport.py positions.
POSN = ['GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF', 'AMF', 'LWF', 'RWF', 'SS', 'CF']

_LOCK = threading.RLock()
_CACHE = {}          # name -> (mtime, obj)


def clear():
    """Drop the cache (called after a re-import or a config reload)."""
    with _LOCK:
        _CACHE.clear()
        _NAMES.clear()
        _CLUB_OF.clear()


def _load(name, default=None):
    """Read data/fc27/<name>, cached by mtime so a re-import is picked up."""
    p = os.path.join(DIR, name)
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return default
    with _LOCK:
        hit = _CACHE.get(name)
        if hit and hit[0] == mt:
            return hit[1]
    try:
        with open(p, encoding='utf-8') as f:
            obj = json.load(f)
    except Exception:
        return default
    with _LOCK:
        _CACHE[name] = (mt, obj)
    return obj


def available():
    """True when the FC 27 database has been generated."""
    return os.path.isfile(os.path.join(DIR, 'players.json'))


def meta():
    return _load('fc27_meta.json', {}) or {}


def players():
    return _load('players.json', []) or []


def ratings():
    return (_load('ratings.json', {}) or {}).get('p', {}) or {}


def positions():
    return _load('positions.json', {}) or {}


def playpos():
    return _load('playpos.json', {}) or {}


def clubs():
    return _load('clubs.json', {}) or {}


def leagues():
    return _load('leagues.json', {}) or {}


def squads():
    return _load('squads.json', {}) or {}


def nations():
    return _load('nations.json', {}) or {}


def nats():
    return _load('nats.json', {}) or {}


def potential():
    return _load('potential.json', {}) or {}


def birthdays():
    return _load('birthdays.json', {}) or {}


def contracts():
    return _load('contract.json', {}) or {}


_NAMES = {}


def _names():
    if not _NAMES:
        for row in players():
            try:
                _NAMES[int(row[0])] = (row[1], row[2])
            except Exception:
                continue
    return _NAMES


def name(pid):
    """Short/display name (common name where the player has one)."""
    return (_names().get(int(pid)) or ('', ''))[1]


def full_name(pid):
    return (_names().get(int(pid)) or ('', ''))[0]


def club(tid):
    return clubs().get(str(int(tid)))


def league(lid):
    return leagues().get(str(int(lid)))


def squad(tid):
    """Player ids at a club, best first."""
    ps = squads().get(str(int(tid))) or []
    r = ratings()
    return sorted(ps, key=lambda p: -(r.get(str(p), [0])[0] or 0))


_CLUB_OF = {}


def _club_of():
    """pid -> club id, built once. Without this each player lookup scanned all
    717 squads (and re-scanned per player when rendering a whole squad)."""
    if not _CLUB_OF:
        for t, ps in squads().items():
            try:
                ti = int(t)
            except (TypeError, ValueError):
                continue
            for pid in ps:
                _CLUB_OF[int(pid)] = ti
    return _CLUB_OF


def club_of(pid):
    """Club id for a player, or 0 when he is a free agent."""
    return _club_of().get(int(pid), 0)


def player(pid):
    """Everything the game knows about one player, or None."""
    pid = int(pid)
    k = str(pid)
    r = ratings().get(k)
    if not r:
        return None
    tid = club_of(pid)
    c = clubs().get(str(tid)) or {}
    nat = nations().get(str(nats().get(k) or nats().get(pid) or 0)) or {}
    ct = contracts().get(k) or {}
    pos = positions().get(k, 0)
    pp = playpos().get(k, '')
    return dict(
        id=pid, name=name(pid), full=full_name(pid),
        ovr=r[0], age=r[1], height=r[2], weight=r[3],
        foot='L' if r[4] == 'True' else 'R',
        pos=pos, posName=POSN[pos] if 0 <= pos < len(POSN) else '',
        positions=[POSN[i] for i, v in enumerate(pp) if v.isdigit() and int(v) > 0],
        attrs=r[10], potential=potential().get(k, r[0]),
        birthday=birthdays().get(k, ''),
        club=tid, clubName=c.get('name', ''), league=c.get('league', 0),
        nation=nat.get('name', ''), nationIso=nat.get('iso', ''),
        wage=ct.get('value', 0), contractUntil=ct.get('contract', 0),
        release=ct.get('release', 0), gender=ct.get('gender', 0),
    )


def league_clubs(lid):
    """Clubs in a league, each with its squad size."""
    lg = league(lid)
    if not lg:
        return []
    cs, sq = clubs(), squads()
    out = []
    for t in lg.get('teams') or []:
        c = cs.get(str(t))
        if c:
            out.append(dict(id=t, squad=len(sq.get(str(t)) or []), **c))
    return out


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    return ''.join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()


def search(q, limit=40, club_id=None, pos=None):
    """Substring search over full & short names, best-rated first."""
    nq = _norm(q)
    if not nq:
        return []
    r, ps = ratings(), positions()
    sq = squads()
    allowed = set(sq.get(str(int(club_id))) or []) if club_id else None
    hits = []
    for pid, (full, short) in _names().items():
        if allowed is not None and pid not in allowed:
            continue
        if nq not in _norm(full) and nq not in _norm(short):
            continue
        rr = r.get(str(pid))
        if not rr:
            continue
        if pos is not None and ps.get(str(pid)) != int(pos):
            continue
        hits.append((-(rr[0] or 0), pid, short, rr))
    hits.sort()
    return [dict(id=pid, name=nm, ovr=rr[0], age=rr[1],
                 pos=POSN[ps.get(str(pid), 0)] if 0 <= ps.get(str(pid), 0) < len(POSN) else '')
            for _, pid, nm, rr in hits[:max(1, int(limit))]]


def summary():
    """Counts + provenance, for the setup/diagnostic surface."""
    m = meta()
    cs, lg, sq = clubs(), leagues(), squads()
    return dict(
        ok=available(), dir=DIR,
        players=len(players()), clubs=len(cs), leagues=len(lg),
        nations=len(nations()), squads=len(sq),
        contracted=sum(1 for ps in sq.values() for _ in ps),
        freeAgents=len(players()) - sum(len(ps) for ps in sq.values()),
        source=m.get('source', ''), upstream=m.get('upstream', ''),
        generated=m.get('generated', ''), asOf=m.get('asOf', ''),
        skipped=m.get('skipped', {}),
    )
