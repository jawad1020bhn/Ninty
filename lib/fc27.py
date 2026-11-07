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

Engine-facing reference data (static; the engine's own save holds season state):
  stadiums.json   {stadiumid: {name, capacity, city, country, pitch, ...}}
  managers.json   {tid: {id, name, nation, stars, gender}}
  squad_meta.json {tid: {pid: [shirtNumber, role, eaPosition]}}
                  role 0 = starting XI, 1 = substitute, 2 = reserve
  rivals.json     {tid: [[otherTid, intensity, type], ...]} strongest first
  formations.json {tid: [{id, name, pos[11], role[11], xy[11], attack, lines}]}
  loans.json      [{pid, from, fromName, to, end, toBuy, futureOption}]
  traits.json     {pid: {t1, t2, retiring, smLikelihood}}  t1/t2 are raw bitflags
  cups.json       {compid: {name, kind, country, importance, teams, groups, ...}}
  prev_pos.json   {tid: {prev, prevLeague}}  last season's finishing position
  ea_attrs.json   {ab: [34 EA field names], p: {pid: [34 raw values]}}
  ea_positions.json {enum, slotCompat, p: {pid: [EA slot ids, best first]}}
  national_teams.json {teamid: {name, gender, ovr, colors, squad}}

Position granularity: formations and players share EA's 28-id enum but not its
granularity. A formation slot is side-specific (4 RCB, 6 LCB, 9 RDM, 24 RS);
a player only ever carries the coarse central id (5 CB, 10 CDM, 25 ST). Use
slot_compat() to compare them - fits_slot() does it for you. Comparing raw ids
directly leaves 1998 of 7887 designated starters unable to fill their own
club's formation; with the map, all 7887 fit.

About the two attribute sets: ratings.json carries the 25 PES attributes the
existing algorithms read, which is a LOSSY projection of EA's data - it has no
slot for crossing, volleys, reactions, longshots, interceptions, vision,
penalties, composure or slidingtackle, and it blends agility into
TightPossession. ea_attrs.json keeps EA's 34 values raw and unblended, so a
match engine can tell an interceptor from a slider. Prefer ea_attrs for
simulation; the PES 25 exist for backwards compatibility.

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


def ea_ab():
    """The 34 EA attribute names, in ea_attrs() row order."""
    return (_load('ea_attrs.json', {}) or {}).get('ab', []) or []


def ea_attrs(pid=None):
    """Raw EA attributes. With pid, a {name: value} dict; else the whole table.

    These are lossless. The 25 PES attributes in ratings() are a projection of
    this data and drop nine match-relevant fields.
    """
    tbl = (_load('ea_attrs.json', {}) or {}).get('p', {}) or {}
    if pid is None:
        return tbl
    row = tbl.get(str(int(pid)))
    return dict(zip(ea_ab(), row)) if row else {}


def ea_positions(pid=None):
    """Raw EA position ids, most preferred first. None -> the whole table."""
    tbl = (_load('ea_positions.json', {}) or {}).get('p', {}) or {}
    return tbl if pid is None else (tbl.get(str(int(pid))) or [])


def slot_compat():
    """{formation slot id -> the coarse EA id a player can hold}."""
    raw = (_load('ea_positions.json', {}) or {}).get('slotCompat', {}) or {}
    return {int(k): int(v) for k, v in raw.items()}


def fits_slot(pid, slot):
    """Can this player fill a formation slot? Compares in the coarse space."""
    cm = slot_compat()
    want = cm.get(int(slot), int(slot))
    return any(cm.get(p, p) == want for p in ea_positions(pid))


def national_teams():
    return _load('national_teams.json', {}) or {}


def national_team(tid):
    return national_teams().get(str(int(tid)))


def stadiums():
    return _load('stadiums.json', {}) or {}


def managers():
    return _load('managers.json', {}) or {}


def squad_meta():
    """{tid: {pid: [shirt, role, eaPos]}}; role 0 XI, 1 sub, 2 reserve."""
    return _load('squad_meta.json', {}) or {}


def rivals():
    return _load('rivals.json', {}) or {}


def formations():
    return _load('formations.json', {}) or {}


def loans():
    return _load('loans.json', []) or []


def traits():
    return _load('traits.json', {}) or {}


def cups():
    return _load('cups.json', {}) or {}


def prev_pos():
    return _load('prev_pos.json', {}) or {}


def stadium(tid):
    """Venue for a club, or None. Capacity here is the linked stadium's own."""
    c = club(tid) or {}
    return stadiums().get(str(c.get('stadium', '')))


def manager(tid):
    return managers().get(str(int(tid)))


def shirt(pid, tid=None):
    """Squad number, or 0. Pass tid when known to skip the club lookup."""
    tid = club_of(pid) if tid is None else int(tid)
    row = (squad_meta().get(str(tid)) or {}).get(str(int(pid)))
    return row[0] if row else 0


def role(pid, tid=None):
    """0 starting XI, 1 substitute, 2 reserve, -1 free agent."""
    tid = club_of(pid) if tid is None else int(tid)
    row = (squad_meta().get(str(tid)) or {}).get(str(int(pid)))
    return row[1] if row else -1


def starting_xi(tid):
    """The template's designated XI, ordered by shirt number.

    This is a starting point for a career, not a live lineup: the engine owns
    selection once the career is running.
    """
    m = squad_meta().get(str(int(tid))) or {}
    xi = [(int(p), v[0]) for p, v in m.items() if v[1] == 0]
    return [p for p, _ in sorted(xi, key=lambda x: x[1])]


def club_formations(tid):
    return formations().get(str(int(tid))) or []


def club_rivals(tid):
    """[{id, name, intensity, type}], strongest rivalry first."""
    cs = clubs()
    return [dict(id=b, name=(cs.get(str(b)) or {}).get('name', ''), intensity=i, type=t)
            for b, i, t in (rivals().get(str(int(tid))) or [])]


def loan_of(pid):
    """Active loan record for a player, or None."""
    return next((l for l in loans() if l['pid'] == int(pid)), None)


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
        shirt=shirt(pid, tid), role=role(pid, tid),
        traits=traits().get(k) or {}, loan=loan_of(pid),
        eaAttrs=ea_attrs(pid), eaPositions=ea_positions(pid),
        nationalTeams=[national_team(t) or {'id': t} for t in (ct.get('natPos') or [])],
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
        stadiums=len(stadiums()), managers=len(managers()), cups=len(cups()),
        loans=len(loans()), formations=sum(len(v) for v in formations().values()),
        rivalPairs=sum(len(v) for v in rivals().values()) // 2,
        nationalTeams=len(national_teams()),
        cappedPlayers=sum(len(t.get('squad') or []) for t in national_teams().values()),
        contracted=sum(1 for ps in sq.values() for _ in ps),
        freeAgents=len(players()) - sum(len(ps) for ps in sq.values()),
        source=m.get('source', ''), upstream=m.get('upstream', ''),
        generated=m.get('generated', ''), asOf=m.get('asOf', ''),
        skipped=m.get('skipped', {}),
    )
