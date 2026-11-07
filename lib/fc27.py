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
  contract.json   {pid: {value, contract, release, intRep, gender, natPos,
                         joinedClub, growthProfile}}
                  joinedClub is an ISO date (same 1582 epoch as birthdate).
                  growthProfile is a raw 1..6 career-stage id; upstream does not
                  name the curves. Observed: 6 = young with headroom (mean age
                  24.4, +9.4 potential), 4 = near-peak veteran (30.0, +1.4).

Engine-facing reference data (static; the engine's own save holds season state):
  stadiums.json   {stadiumid: {name, capacity, city, country, pitch, ...}}
  managers.json   {tid: {id, name, nation, stars, gender}}
  squad_meta.json {tid: {pid: [shirtNumber, role, eaPosition]}}
                  role 0 = starting XI, 1 = substitute, 2 = reserve
  rivals.json     {tid: [[otherTid, intensity, type], ...]} strongest first
  formations.json {tid: [{id, name, pos[11], role[11], xy[11], attack, lines}]}
  loans.json      [{pid, from, fromName, to, end, toBuy, futureOption}]
  traits.json     {pid: {t1, t2, retiring, smLikelihood, icon1, icon2}}
                  t1/t2 and icon1/icon2 are raw bitflags (meanings undocumented)
  cups.json       {compid: {name, kind, country, importance, teams, groups, ...}}
  prev_pos.json   {tid: {prev, prevLeague}}  last season's finishing position
  ea_attrs.json   {ab: [34 EA field names], p: {pid: [34 raw values]}}
  ea_positions.json {enum, slotCompat, p: {pid: [EA slot ids, best first]}}
  national_teams.json {teamid: {name, gender, ovr, colors, squad, nation}}

Career logic tables (static rules and history, still not season state):
  teamsheets.json {tid: {captain, penalty, freeKick, ...}}  ids, null if unset
  ovr_weights.json {positions: {eaPos: [[attrId, pct]]}, categories, stars}
                  EA's own per-position rating weights (sum 100). attrId is EA's
                  INTERNAL enum, NOT ea_attrs() field order, and is unresolved:
                  do not index attributes with it. stars() is rating-based and
                  safe. See ovr_weights.json attrIdSpace.
  coefficients.json {clubs: {tid: {points, years[5]}}, nations: {cid: ...}}
  calendar.json   {windows: [{open: {month, day}, close: {...}}]}  no year
  ownership.json  {tid: {group, seniority, siblings[]}}  multi-club groups
  league_groups.json {tid: groupId}  MLS conferences
  comp_venues.json {compid: [{stadium, final}]}  neutral/final venues
  prev_stats.json {p: {pid: [[comp, apps, goals, assists, Y, R, cleanSheets]]}}
  referees.json   {refs: {id: {name, cards, fouls, ...}}, leagues: {lid: [id]}}
  regen_names.json {first/last/common: [[name, poolId, gender]]}
  regen_templates.json {youth[], regen[]}  attribute templates by posGroup/age
  playstyles.json {id: {name, requires: [[attrId, minValue]]}}
                  attrId is the same unresolved EA enum - raw reference only
  affinities.json {pid: [[teamid, emotion]]}  strongest first; scale inferred
  former_clubs.json {pid: teamid}  verified not the player's current club
  counterparts.json {tid: otherTid}  men's <-> women's side, symmetric
  big_matches.json [[tidA, tidB]]  normalised marquee fixtures
  match_tuning.json {intensityMinutes, intensity, attendance}
  external_teams.json {tid: {name, competition, competitionName}}
                  teams referenced by the data but outside clubs.json (the
                  CONMEBOL sides). Resolve names via team_name().

Position granularity: formations and players share EA's 28-id enum but not its
granularity. A formation slot is side-specific (4 RCB, 6 LCB, 9 RDM, 24 RS);
a player only ever carries the coarse central id (5 CB, 10 CDM, 25 ST). Use
slot_compat() to compare them - fits_slot() does it for you. Comparing raw ids
directly leaves 1998 of 7887 designated starters unable to fill their own
club's formation; with the map, all 7887 fit.

About the two attribute sets: ratings.json carries the legacy 25 attributes the
existing algorithms read, which is a LOSSY projection of EA's data - it has no
slot for crossing, volleys, reactions, longshots, interceptions, vision,
penalties, composure or slidingtackle, and it blends agility into
TightPossession. ea_attrs.json keeps EA's 34 values raw and unblended, so a
match engine can tell an interceptor from a slider. Prefer ea_attrs for
simulation; the legacy 25 exist for backwards compatibility.

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


def teamsheet(tid):
    """Captain and set-piece takers for a club (player ids, None if unset)."""
    return (_load('teamsheets.json', {}) or {}).get(str(int(tid))) or {}


def ovr_weights():
    """Raw per-position rating weights. The attribute ids are EA's internal
    enum, NOT ea_attrs() field order, and could not be resolved - so no
    rating_in_pos() helper is offered. Use stars() for a safe derived value."""
    return _load('ovr_weights.json', {}) or {}


def stars(ovr):
    """EA's 0..5 star band for a rating (0.5 steps), from starratingboundaries."""
    try:
        v = int(ovr)
    except (TypeError, ValueError):
        return 0
    for b in ovr_weights().get('stars', []) or []:
        if b.get('from', 0) <= v <= b.get('to', 0):
            return b.get('stars', 0)
    return 0


def coefficients(tid=None, nation=None):
    """5-year coefficient scores. No args -> the whole table."""
    c = _load('coefficients.json', {}) or {}
    if tid is not None:
        return (c.get('clubs') or {}).get(str(int(tid))) or {}
    if nation is not None:
        return (c.get('nations') or {}).get(str(int(nation))) or {}
    return c


def transfer_windows():
    """Open/close as {month, day}. Deliberately year-less: the engine's save
    owns the season, and the template's absolute dates are a 2008 placeholder."""
    return (_load('calendar.json', {}) or {}).get('windows', []) or []


def in_transfer_window(month, day):
    v = int(month) * 100 + int(day)
    for w in transfer_windows():
        o, c = w.get('open') or {}, w.get('close') or {}
        if not o or not c:
            continue
        a, b = o['month'] * 100 + o['day'], c['month'] * 100 + c['day']
        if (a <= v <= b) if a <= b else (v >= a or v <= b):
            return True
    return False


def ownership(tid):
    """Multi-club ownership group for a club, or {}."""
    return (_load('ownership.json', {}) or {}).get(str(int(tid))) or {}


def same_owner(a, b):
    """True when two clubs share an ownership group (transfer usually blocked)."""
    if int(a) == int(b):
        return True
    return int(b) in (ownership(a).get('siblings') or [])


def league_group(tid):
    return (_load('league_groups.json', {}) or {}).get(str(int(tid)))


def comp_venues(compid):
    return (_load('comp_venues.json', {}) or {}).get(str(int(compid))) or []


def prev_stats(pid):
    """Last season's real per-competition stats for a player."""
    return (_load('prev_stats.json', {}) or {}).get('p', {}).get(str(int(pid))) or []


def referees(lid=None):
    r = _load('referees.json', {}) or {}
    if lid is None:
        return r.get('refs', {}) or {}
    return [r.get('refs', {}).get(str(i)) for i in (r.get('leagues', {}).get(str(int(lid))) or [])]


def regen_names():
    return _load('regen_names.json', {}) or {}


def regen_templates():
    return _load('regen_templates.json', {}) or {}


def playstyles():
    """PlayStyle unlock thresholds, raw. `requires` ids use EA's internal
    attribute enum (unresolved - see ovr_weights()), so they are deliberately
    not evaluated against a player's attributes here. This is also NOT a decode
    of traits.json: no defensible trait-bit mapping exists in the template."""
    return _load('playstyles.json', {}) or {}


def affinities(pid):
    """Clubs a player has an emotional tie to, strongest first: [[tid, level]].

    level_of_emotion is raw. Upstream does not document the scale; observed
    values (Iniesta -> Barcelona 7, -> Athletic Club 1) suggest low = grudge and
    high = affection, but that reading is inferred, not confirmed.
    """
    return (_load('affinities.json', {}) or {}).get(str(int(pid))) or []


def years_at_club(pid, as_of=None):
    """Whole years since the player joined his current club, or None.

    Uses the shipped joinedClub date. as_of defaults to the database's asOf
    snapshot, NOT today, so the value is stable for a given database.
    """
    d = (contracts().get(str(int(pid))) or {}).get('joinedClub') or ''
    if not d:
        return None
    ref = as_of or (meta().get('asOf') or '')
    try:
        y, m, dd = (int(x) for x in d.split('-'))
        ry, rm, rd = (int(x) for x in ref.split('-'))
    except (ValueError, AttributeError):
        return None
    n = ry - y
    if (rm, rd) < (m, dd):
        n -= 1
    return max(0, n)


def former_club(pid):
    """The player's previous club id, or None."""
    return (_load('former_clubs.json', {}) or {}).get(str(int(pid)))


def counterpart(tid):
    """The men's/women's counterpart of a club, or None."""
    return (_load('counterparts.json', {}) or {}).get(str(int(tid)))


def big_matches():
    return _load('big_matches.json', []) or []


def is_big_match(a, b):
    x, y = sorted((int(a), int(b)))
    return any(p[0] == x and p[1] == y for p in big_matches())


def match_tuning():
    """Intensity by score difference x minute bucket, plus attendance bands."""
    return _load('match_tuning.json', {}) or {}


def match_intensity(score_diff, minute):
    """EA's intensity modifier for a score state at a minute, or None.

    Clamps the score difference to the shipped -4..4 range and picks the
    nearest listed minute bucket at or above `minute`.
    """
    t = match_tuning()
    rows = t.get('intensity') or []
    if not rows:
        return None
    try:
        d, m = int(score_diff), int(minute)
    except (TypeError, ValueError):
        return None
    lo, hi = rows[0]['scoreDiff'], rows[-1]['scoreDiff']
    d = max(lo, min(hi, d))
    row = next((r for r in rows if r['scoreDiff'] == d), None)
    if not row:
        return None
    mins = t.get('intensityMinutes') or []
    idx = next((i for i, v in enumerate(mins) if m <= v), len(mins) - 1)
    vals = row.get('byMinute') or []
    return vals[idx] if 0 <= idx < len(vals) else None


def external_teams():
    return _load('external_teams.json', {}) or {}


def team_name(tid):
    """Name of any team id: club, national team, or external (CONMEBOL) side.

    Every team id referenced by the shipped data resolves through this.
    """
    k = str(int(tid))
    c = clubs().get(k)
    if c:
        return c.get('name') or ''
    n = national_teams().get(k)
    if n:
        return n.get('name') or ''
    e = external_teams().get(k)
    if e:
        return e.get('name') or ''
    return ''


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

    These are lossless. The legacy 25 attributes in ratings() are a projection of
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
        joinedClub=ct.get('joinedClub', ''), growthProfile=ct.get('growthProfile', 0),
        shirt=shirt(pid, tid), role=role(pid, tid),
        traits=traits().get(k) or {}, loan=loan_of(pid),
        eaAttrs=ea_attrs(pid), eaPositions=ea_positions(pid),
        stars=stars(r[0]), prevStats=prev_stats(pid),
        yearsAtClub=years_at_club(pid),
        affinities=[dict(id=t, name=team_name(t), level=lv) for t, lv in affinities(pid)],
        formerClub=(lambda f: dict(id=f, name=team_name(f)) if f else None)(former_club(pid)),
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
        teamsheets=len(_load('teamsheets.json', {}) or {}),
        referees=len(referees()), coefficients=len(coefficients().get('clubs') or {}),
        prevStatPlayers=len((_load('prev_stats.json', {}) or {}).get('p', {}) or {}),
        regenNames={k: len(v) for k, v in regen_names().items()},
        transferWindows=transfer_windows(),
        bigMatches=len(big_matches()), externalTeams=len(external_teams()),
        affinityPlayers=len(_load('affinities.json', {}) or {}),
        counterparts=len(_load('counterparts.json', {}) or {}),
        contracted=sum(1 for ps in sq.values() for _ in ps),
        freeAgents=len(players()) - sum(len(ps) for ps in sq.values()),
        source=m.get('source', ''), upstream=m.get('upstream', ''),
        generated=m.get('generated', ''), asOf=m.get('asOf', ''),
        skipped=m.get('skipped', {}),
    )
