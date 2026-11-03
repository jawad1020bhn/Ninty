"""PES 2017 compatibility layer for The Gaffer (pc414).

This module is deliberately READ-ONLY.  PES 2021 / Football Life 26 / FL27
Master League saves and PES 2017 Master League saves share the same encrypted
*container* (pesXdecrypter, 320 B encryption header + 208 B file header), but
they use a different 64-byte master key and the decrypted ``data.dat`` inside
is a completely different database.

What is implemented here (verified against published PES 2017 reverse
engineering -- pesXdecrypter masterkey.c, the Rigged Wiki PES 2017 Edit file
page and the PES2017-Master-League-Transfer-Engine project):

* the PES 2017 master key and per-save key detection,
* description.dat parsing (club / league / date / next competition),
* the Master League team table (offset 80, 1312 B records, name at +4),
* the 32-player squad list of every club (offset +248, 8 B per slot),
* the league standings membership blocks (offset 8617528, 2600 B per league),
* the EDIT00000000 player database (188 B records from offset 120: name,
  age, registered position, playable positions, 22 attributes),
* an importer that turns that EDIT database into the app's own
  players/ratings/positions/playpos JSON files,
* a ``Pes17Save`` adapter that mimics the read side of ``mlwrite.Save`` and
  refuses every write.

Everything that needs writing into the PES 2017 ML save (transfers, contracts,
formation, tactics, budgets, loans, youth, AI transfers, ...) is intentionally
blocked: those tables have different offsets and row sizes in PES 2017 and
have not been measured on real PES 2017 save pairs yet.  lib/pes17_layout.py
is the companion tool for that measurement.
"""
import json
import os
import re
import struct

# --------------------------------------------------------------------------
# Container encryption
# --------------------------------------------------------------------------
# pesXdecrypter/src/masterkey.c: MasterKeyPes17 (public domain).
KEY_PES17 = bytes([
    0x9B, 0xC7, 0x13, 0x28, 0x2D, 0xE8, 0x47, 0x75,
    0x4D, 0x52, 0x9E, 0x35, 0x90, 0xAA, 0x6A, 0x7A,
    0x5C, 0xFA, 0x60, 0x9F, 0x6A, 0x32, 0x04, 0x57,
    0xB8, 0x9F, 0x59, 0xA5, 0x5F, 0xAC, 0x7D, 0x62,
    0xFE, 0x10, 0x2A, 0xD6, 0x95, 0xFA, 0xDF, 0xA0,
    0x68, 0xBD, 0x40, 0x95, 0x47, 0x9C, 0xBB, 0x40,
    0xF2, 0x94, 0x49, 0x3C, 0xC8, 0xE0, 0x94, 0x9D,
    0x7B, 0x01, 0x6F, 0xF2, 0xC5, 0x3A, 0x2C, 0xE5,
])

KEY_MARK = 'gaffer_key.txt'
PES17_GAME = 'pes17'
READ_ONLY_MSG = (
    'PES 2017 support is read-only: this build reads your Master League save '
    '(club, squad, players, standings) but does not write to it. Transfers, '
    'contracts, tactics, training and AI moves are not mapped for the PES 2017 '
    'save layout yet, so the save was left untouched.'
)

# --------------------------------------------------------------------------
# PES 2017 Master League data.dat layout (measured by the MLTE project)
# --------------------------------------------------------------------------
TEAM0 = 80                 # first club record
TEAM_STRIDE = 1312         # bytes per club record
TEAM_END = 854192          # end of club table (651 records)
TEAM_NAME_OFF = 4
TEAM_NAME_LEN = 64
SQUAD_OFF = 248            # 32 slots x 8 B: (roster pointer u32, player id u32)
SQUAD_SLOTS = 32
PID_LIMIT = 1 << 31           # PES 2017 player IDs are >= 1048576
STANDINGS0 = 8617528       # 0x837E38, start of active ML standing structures
STANDINGS_STRIDE = 2600
STANDINGS_TEAMS = 20       # u32 team ids at the head of each 2600 B block
STANDINGS_LEAGUES = (
    'English 1st Division', 'Ligue 1', 'Italian 1st Division', 'Eredivisie',
    'LaLiga Santander', 'Liga Portugal', 'Brazilian 1st Division',
    'Argentine 1st Division', 'Chilean 1st Division', 'PEU League',
    'PLA League', 'PAS League', 'English 2nd Division', 'Ligue 2',
    'Italian 2nd Division', 'Spanish 2nd Division',
)
# Blocks 12..15 are not at root + 12*2600: MLTE measured explicit offsets.
STANDINGS_EXTRA = {
    12: 62488, 13: 65080, 14: 67680, 15: 70272,
}

# --------------------------------------------------------------------------
# PES 2017 EDIT00000000 data.dat layout (Rigged Wiki + MLTE)
# --------------------------------------------------------------------------
EDIT_HEADER = 120           # 0x78: player entries start here
EDIT_COUNT_OFF = 0x5C       # u16 number of player entries
EDIT_RECORD = 188           # 116 B player entry + 72 B appearance entry
EDIT_ENTRY = 116
EDIT_END = 3948120
EDIT_NAME_OFF = 0x34
EDIT_NAME_LEN = 46
EDIT_HEIGHT = 0x0C
EDIT_WEIGHT = 0x0D

# 22 (of the app's 25) attributes can be read directly from the PES 2017
# player entry.  (name in the app, byte offset, bit offset, bit length)
ATTR_FIELDS = (
    ('OffensiveAwareness', 0x10, 0, 7),   # Attacking Prowess
    ('BallControl',        0x22, 0, 7),
    ('Dribbling',          0x12, 5, 7),
    ('TightPossession',    0x1C, 0, 7),   # Body Control
    ('LowPass',            0x14, 7, 7),
    ('LoftedPass',         0x15, 6, 7),
    ('Finishing',          0x14, 0, 7),
    ('Heading',            0x16, 5, 7),   # Header
    ('PlaceKicking',       0x2A, 6, 7),
    ('Curl',               0x18, 0, 7),   # Swerve
    ('Speed',              0x2C, 7, 7),
    ('Acceleration',       0x1E, 5, 7),   # Explosive Power
    ('KickingPower',       0x1D, 6, 7),
    ('Jump',               0x24, 0, 7),
    ('PhysicalContact',    0x1C, 7, 7),
    ('Balance',            0x1C, 0, 7),   # Body Control (PES 2017 has one field)
    ('Stamina',            0x2C, 0, 7),
    ('DefensiveAwareness', 0x10, 7, 7),   # Defensive Prowess
    ('BallWinning',        0x22, 7, 7),
    ('Aggression',         0x10, 7, 7),   # approximation: Defensive Prowess
    ('GKAwareness',        0x11, 6, 7),   # Goalkeeping
    ('GKCatching',         0x18, 7, 7),   # Catching
    ('GKClearing',         0x19, 6, 7),   # Clearing
    ('GKReflexes',         0x1A, 5, 7),   # Reflexes
    ('GKReach',            0x25, 5, 7),   # Coverage
)
AB = [a[0] for a in ATTR_FIELDS]
# PES 2017 playable-position bits (0x26:6, 13 x 2 bits), in wiki order.
PP_ORDER = (12, 11, 9, 10, 8, 4, 5, 6, 7, 1, 2, 3, 0)   # -> app POS codes
POS_NAMES = ('GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF',
             'AMF', 'LWF', 'RWF', 'SS', 'CF')


def _bits(b, byte, bit, n):
    """Little-endian bit field, e.g. (0x22, 7, 7) means bit 7 of byte 0x22."""
    return (int.from_bytes(b[byte:byte + 4], 'little') >> bit) & ((1 << n) - 1)


def _text(raw):
    return raw.split(b'\0')[0].decode('utf-8', 'replace').strip()


def _plausible_name(s):
    return (3 <= len(s) <= 64 and
            all(c.isprintable() and (c.isalnum() or c in " .-'&/()+,:") for c in s))


def _norm(s):
    """Loose club-name key: PES 2017 prefixes the club with a slot number."""
    s = re.sub(r'^\s*\d{1,3}[\s.\-]*', '', (s or '').lower())
    return re.sub(r'[^a-z0-9]', '', s)


def find_club(teams, club):
    """Match a description.dat club name to the ML club table."""
    if not club:
        return None
    key = _norm(club)
    for t in teams:
        if t['name'] == club:
            return t
    for t in teams:
        k = _norm(t['name'])
        if k and (k == key or k in key or key in k):
            return t
    return None


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------
_DETECT_CACHE = {}


def is_pes17(folder):
    """True for a decrypted PES 2017 save folder (marker or data.dat signature)."""
    try:
        mk = os.path.join(folder, KEY_MARK)
        if os.path.isfile(mk):
            with open(mk, encoding='utf-8', errors='ignore') as f:
                return f.read().strip() == PES17_GAME
        dp = os.path.join(folder, 'data.dat')
        st = os.stat(dp)
        key = (dp, st.st_mtime_ns, st.st_size)
        if key in _DETECT_CACHE:
            return _DETECT_CACHE[key]
        with open(dp, 'rb') as f:
            head = f.read(TEAM0 + TEAM_STRIDE * 4)
        v = _looks_pes17(head, st.st_size)
        if len(_DETECT_CACHE) > 64:
            _DETECT_CACHE.clear()
        _DETECT_CACHE[key] = v
        return v
    except Exception:
        return False


def _looks_pes17(head, size=0):
    """PES 2017 club table: u32 team id at +0, 64 B name at +4, stride 1312.

    PES 2021 / FL saves have their first club *name* at offset 84 and no team
    id at 80, so this signature cannot collide with them.
    """
    if len(head) < TEAM0 + 3 * TEAM_STRIDE or size and size < 1000000:
        return False
    ok = 0
    for k in range(3):
        o = TEAM0 + k * TEAM_STRIDE
        cid = struct.unpack_from('<I', head, o)[0]
        name = _text(head[o + TEAM_NAME_OFF:o + TEAM_NAME_OFF + TEAM_NAME_LEN])
        # A PES 2021 save has a club *name* at offset 84 but a zero/ASCII word
        # at 80, so requiring a real team id here prevents false positives.
        if 0 < cid < 1000000 and _plausible_name(name):
            ok += 1
    return ok >= 2


def game_label(folder):
    return 'PES 2017 (read-only)' if is_pes17(folder) else ''


def configured_date_order():
    """Read pes17_date_order from the app's config.json (default 'dmy')."""
    try:
        cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'config.json')
        with open(cfg, encoding='utf-8') as f:
            v = json.load(f).get('pes17_date_order', 'dmy')
        return 'mdy' if str(v).lower() == 'mdy' else 'dmy'
    except Exception:
        return 'dmy'


# --------------------------------------------------------------------------
# description.dat
# --------------------------------------------------------------------------
def _date_from_line(line, order='dmy'):
    m = re.search(r'(\d{1,2})[./\-](\d{1,2})[./\-](\d{4})', line or '')
    if not m:
        m = re.search(r'(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})', line or '')
        if not m:
            return ''
        y, mo, d = (int(x) for x in m.groups())
        return '%d/%d/%d' % (d, mo, y)
    a, b, y = (int(x) for x in m.groups())
    if a > 12:                 # unambiguous: day first
        d, mo = a, b
    elif b > 12:               # unambiguous: month first
        mo, d = a, b
    elif order == 'mdy':       # US locale, e.g. 07/01/2038 = January 7th
        mo, d = a, b
    else:                      # default: D/M/YYYY (PES 2017 EU saves)
        d, mo = a, b
    return '%d/%d/%d' % (d, mo, y)


def read_description(folder, date_order='dmy'):
    with open(os.path.join(folder, 'description.dat'), 'rb') as f:
        raw = f.read()
    parts = [p for p in raw.split(b'\0') if p.strip()]
    slot = parts[0].decode('utf-8', 'replace').strip() if parts else ''
    # The descriptive block is the one with a date and/or "Club / League".
    desc = b''
    for p in parts[1:] or parts[:1]:
        if b'/' in p and re.search(rb'\d{1,2}[./\-]\d{1,2}[./\-]\d{4}', p):
            desc = p
            break
    if not desc and len(parts) > 1:
        desc = parts[1]
    lines = [x.decode('utf-8', 'replace').strip()
             for x in desc.replace(b'\r\n', b'\n').split(b'\n') if x.strip()]
    head = lines[0] if lines else ''
    # PES 2017 prefixes the first line with "Master League <slot>".
    head = re.sub(r'^(?:Master\s+League|Become\s+a\s+Legend)\s+', '', head, flags=re.I).strip(' -')
    club, league = (head.split(' / ', 1) + [''])[:2] if ' / ' in head else (head, '')
    date = _date_from_line(lines[1] if len(lines) > 1 else '', date_order)
    comp = lines[2] if len(lines) > 2 else ''
    return dict(slot=slot, club=club.strip(), league=league.strip(),
                date=date, next_competition=comp)


def game_date_code(folder, date_order='dmy'):
    """The app packs the game date as (day << 24) | (month << 16) | year."""
    d = read_description(folder, date_order)['date']
    m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', d or '')
    if not m:
        return (1 << 24) | (7 << 16) | 2016
    day, mo, y = (int(x) for x in m.groups())
    return (day << 24) | (mo << 16) | y


# --------------------------------------------------------------------------
# Master League data.dat
# --------------------------------------------------------------------------
def team_records(data):
    out = []
    limit = min(TEAM_END, len(data))
    k = 0
    while TEAM0 + (k + 1) * TEAM_STRIDE <= limit:
        o = TEAM0 + k * TEAM_STRIDE
        cid = struct.unpack_from('<I', data, o)[0]
        if cid == 0xFFFFFFFF:
            break
        name = _text(bytes(data[o + TEAM_NAME_OFF:o + TEAM_NAME_OFF + TEAM_NAME_LEN]))
        # Empty rows (national teams, unused slots) can sit between clubs.
        if _plausible_name(name):
            # Stats fields are not mapped yet -- keep the shape mlsave returns.
            out.append(dict(idx=k, off=o, id=cid, name=name, pts=0, pl=0, w=0, d=0,
                            l=0, gf=0, ga=0, gd=0, pos=0))
        k += 1
    return out


def squad(data, team, names=None):
    names = names or {}
    o = team['off'] + SQUAD_OFF
    out = []
    for i in range(SQUAD_SLOTS):
        ptr, pid = struct.unpack_from('<II', data, o + i * 8)
        if 0 < pid < PID_LIMIT:          # PES 2017 IDs start at 1048576
            out.append(dict(slot=i, id=pid, tag=hex(ptr),
                            name=names.get(pid, '?'), roster_pointer=ptr))
    return out


def standings(data, teams):
    """Best-effort league membership/order from the standing structures.

    Each 2600 B block starts with 20 u32 team ids in table order.  Points,
    wins and goals are NOT mapped for PES 2017 yet, so those fields stay 0.
    """
    by_id = {t['id']: t for t in teams}
    blocks = []
    for i, league in enumerate(STANDINGS_LEAGUES):
        off = STANDINGS0 + (STANDINGS_EXTRA.get(i, i * STANDINGS_STRIDE))
        if off + STANDINGS_TEAMS * 4 > len(data):
            continue
        ids = [struct.unpack_from('<I', data, off + 4 * j)[0]
               for j in range(STANDINGS_TEAMS)]
        ids = [x for x in ids if 0 < x < 1000000]
        if not ids:
            continue
        rows = []
        for pos, cid in enumerate(ids, 1):
            t = by_id.get(cid)
            if not t:
                continue
            rows.append(dict(pos=pos, club=t['name'], pl=0, w=0, d=0, l=0,
                             gf=0, ga=0, gd=0, pts=0, idx=t['idx'], id=cid))
        if rows:
            blocks.append(dict(league=league, offset=off, rows=rows))
    return blocks


def read_save(folder, names=None, date_order='dmy'):
    """Same shape as mlsave.read_save(), for PES 2017 saves."""
    info = read_description(folder, date_order)
    with open(os.path.join(folder, 'data.dat'), 'rb') as f:
        data = f.read()
    teams = team_records(data)
    res = dict(info=info, clubs=len(teams))
    mine = find_club(teams, info['club'])
    if mine:
        info = dict(info, club=mine['name'], club_raw=info['club'])
        res['info'] = info
        res['squad'] = squad(data, mine, names)
        blocks = standings(data, teams)
        blk = next((b for b in blocks if any(r['idx'] == mine['idx'] for r in b['rows'])), None)
        if blk:
            res['league_table'] = blk['rows']
            res['league_name'] = blk['league']
        else:
            res['league_table'] = []
    return res


# --------------------------------------------------------------------------
# EDIT00000000 -> the app's player database
# --------------------------------------------------------------------------
def decrypt_edit(src, outdir):
    """Decrypt an EDIT00000000 file with the PES 2017 key; return the parts."""
    import pescrypt
    raw = open(src, 'rb').read()
    parts = pescrypt.decrypt_bytes(raw, KEY_PES17)
    os.makedirs(outdir, exist_ok=True)
    for k, v in parts.items():
        with open(os.path.join(outdir, k), 'wb') as f:
            f.write(v)
    with open(os.path.join(outdir, KEY_MARK), 'w') as f:
        f.write(PES17_GAME)
    return parts


def _edit_data(src):
    """Accept an encrypted EDIT00000000, a decrypted folder, or data.dat."""
    if os.path.isdir(src):
        p = os.path.join(src, 'data.dat')
    else:
        p = src
    with open(p, 'rb') as f:
        data = f.read()
    if os.path.basename(p) == 'data.dat' and len(data) > 1000000:
        return data
    # encrypted container (or decrypted single file)
    import pescrypt
    for name, key in pescrypt.key_candidates(None):
        if key is None:
            continue
        try:
            return pescrypt.decrypt_bytes(data, key)['data.dat']
        except ValueError:
            continue
    raise ValueError('EDIT00000000 is not a PES 2017 / PES 2021 save (no key worked)')


def parse_edit(data):
    """-> list of player dicts from the PES 2017 EDIT database."""
    n = struct.unpack_from('<H', data, EDIT_COUNT_OFF)[0] if len(data) > EDIT_COUNT_OFF + 2 else 0
    n = min(n or 21000, 21000, (min(len(data), EDIT_END) - EDIT_HEADER) // EDIT_RECORD)
    out, seen = [], set()
    for k in range(n):
        o = EDIT_HEADER + k * EDIT_RECORD
        pid = struct.unpack_from('<I', data, o)[0]
        name = _text(bytes(data[o + EDIT_NAME_OFF:o + EDIT_NAME_OFF + EDIT_NAME_LEN]))
        if not pid or pid in seen or not name:
            continue
        b = bytes(data[o:o + EDIT_ENTRY])
        age = _bits(b, 0x20, 0, 6)
        reg = _bits(b, 0x20, 6, 4)
        form = _bits(b, 0x17, 4, 3)
        attrs = {nm: max(40, min(99, _bits(b, by, bi, ln)))
                 for nm, by, bi, ln in ATTR_FIELDS}
        pp = [0] * 13
        bits = _bits(b, 0x26, 6, 26)
        for j, code in enumerate(PP_ORDER):
            pp[code] = (bits >> (2 * j)) & 3
        seen.add(pid)
        out.append(dict(id=pid, name=name, short=name, age=age if 15 <= age <= 50 else 25,
                        height=b[EDIT_HEIGHT], weight=b[EDIT_WEIGHT],
                        pos=reg if 0 <= reg <= 12 else 5, form=form,
                        playpos=''.join(str(min(x, 2)) for x in pp),
                        attrs=attrs, foot=(_bits(b, 0x2E, 3, 1) == 1)))
    return out


def _ovr(attrs, pos, form=3):
    a = [attrs[k] for k in AB]
    try:
        import dbimport
        return dbimport.ovr_of(a, pos, form)
    except Exception:
        return max(40, min(99, round(sum(a) / len(a))))


def import_edit(src, outdir):
    """Build players.json / ratings.json / positions.json / playpos.json.

    Returns a small stats dict.  The generated files use exactly the shapes
    the app's reload_db() expects.
    """
    players = parse_edit(_edit_data(src))
    os.makedirs(outdir, exist_ok=True)

    def dump(name, obj):
        with open(os.path.join(outdir, name), 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False)

    dump('players.json', [[p['id'], p['name'], p['short']] for p in players])
    dump('positions.json', {str(p['id']): p['pos'] for p in players})
    dump('playpos.json', {str(p['id']): p['playpos'] for p in players})
    ratings = {}
    for p in players:
        ratings[str(p['id'])] = [
            _ovr(p['attrs'], p['pos'], p['form']), p['age'], p['height'], p['weight'],
            'True' if p['foot'] else 'False', 0, 1, 2, 4, 1,
            [p['attrs'][k] for k in AB],
        ]
    dump('ratings.json', dict(ab=AB, f='PES 2017 EDIT00000000', p=ratings))
    return dict(players=len(players), dir=outdir, source=str(src))


def import_teams(folder, outdir):
    """teamids.json from the ML save club table (id -> club name)."""
    with open(os.path.join(folder, 'data.dat'), 'rb') as f:
        teams = team_records(f.read())
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'teamids.json'), 'w', encoding='utf-8') as f:
        json.dump({str(t['id']): t['name'] for t in teams if t['id']}, f,
                  ensure_ascii=False, indent=1)
    return dict(teams=len(teams))


# --------------------------------------------------------------------------
# Read-only Save adapter
# --------------------------------------------------------------------------
class _Neutral(int):
    """A zero that is also callable, empty-iterable and dict-ish.

    FL26 views call dozens of Save helpers that do not exist on a PES 2017
    save.  Returning this instead of raising keeps arithmetic, iteration,
    .items(), len() and truth tests from crashing; unmapped views simply show
    empty data.
    """
    def __new__(cls):
        return int.__new__(cls, 0)
    def __call__(self, *a, **kw):
        return self
    def __iter__(self):
        return iter(())
    def __len__(self):
        return 0
    def __bool__(self):
        return False
    def __getitem__(self, k):
        return self
    def __contains__(self, k):
        return False
    def get(self, *a):
        return None
    def items(self):
        return ()
    def keys(self):
        return ()
    def values(self):
        return ()


class Pes17Save:
    """Read-side stand-in for mlwrite.Save on a PES 2017 ML save.

    mlwrite.Save.__new__ returns one of these whenever the folder is a PES
    2017 save, so *every* mlwrite.Save(...) call in the app gets it.  All
    mutations are refused (self.d is immutable bytes; save()/write_guard()
    raise), which makes this mode safe by construction.
    """
    pes17 = True
    ro_note = READ_ONLY_MSG

    def __init__(self, folder, ro=False, date_order=None):
        self.folder = folder
        self.path = os.path.join(folder, 'data.dat')
        self.ro = True                     # always read-only, even if caller says ro=False
        with open(self.path, 'rb') as f:
            self.d = f.read()
        self.date_order = date_order or configured_date_order()
        self.info = read_description(folder, date_order)
        self.teams = team_records(self.d)
        self.REC0, self.STRIDE, self.SQUAD_OFF = TEAM0, TEAM_STRIDE, SQUAD_OFF
        self.F0 = 0
        self.PLAN0 = 0
        self.known_format = False
        self.layout_ok = False
        self.layout_note = ('PES 2017 save (read-only): club, squad, players and '
                            'standings are read; writing is disabled until the '
                            'PES 2017 save tables are mapped.')
        self.dx = 0
        self.dxa = 0
        self.sh = 0
        self.sh2 = 0
        self.ext = False
        self.beta_ok = False
        self.game27 = False
        self.fmt60 = False
        self.ADV_NEEDS_OWN = (8, 10, 15)
        self.ADV_NEEDS_OPP = (14,)
        try:
            import mlwrite
            self.ADV_ATT = dict(mlwrite.Save.ADV_ATT)
            self.ADV_DEF = dict(mlwrite.Save.ADV_DEF)
            self._presets = mlwrite.PRESETS
            self._rpos = mlwrite.RPOS
        except Exception:
            self.ADV_ATT = {1: 'Hug the Touchline', 2: 'False No. 9'}
            self.ADV_DEF = {11: 'Swarm the Box', 12: 'Deep Defensive Line'}
            self._presets = {}
            self._rpos = {}
        mine = find_club(self.teams, self.info['club'])
        if mine is None and self.teams:
            mine = self.teams[0]
        self._team = mine
        if mine:
            self.info = dict(self.info, club=mine['name'], club_raw=self.info['club'])
        self._squad = squad(self.d, mine, {}) if mine else []
        self._ids = [None] * 40
        for x in self._squad:
            if x['slot'] < 40:
                self._ids[x['slot']] = x['id']

    # -- read API used by the app -------------------------------------------
    def manager(self):
        return ''
    def club_name(self):
        return self.info['club']
    def club_offset(self):
        return self._team['off'] if self._team else TEAM0
    def squad_ids(self):
        return list(self._ids)
    def squad_numbers(self):
        return {}
    def lineup(self):
        return list(range(11)) + [0xff] * 24
    def formation(self, k):
        return [('?', 0, 0)] * 11
    def formation_rows(self, k):
        rows = self._presets.get('4-4-2') or [(5, 20, 50)] * 11
        return [dict(pos=r[0], x=r[1], y=r[2]) for r in rows]
    def my_tactics(self):
        return None
    def read_status(self, pids):
        return {}
    def read_contracts(self, pids):
        return {}
    def game_date_code(self):
        return game_date_code(self.folder, self.date_order)
    def budget(self):
        return 0
    def club_squad_ids(self, idx):
        if not 0 <= idx < len(self.teams):
            return []
        return [x['id'] for x in squad(self.d, self.teams[idx])]
    def my_squad_tags(self):
        return {x['id']: x['roster_pointer'] for x in self._squad}
    def cancelled_loans(self):
        return []
    def loans_waiting(self):
        return []
    def stale_pending(self):
        return []
    def free_agents(self):
        return {}
    def list_deals(self):
        return []
    def wage_commitment(self):
        return 0
    def loaned_in_pids(self):
        return []
    def _squad_len(self, off=None):
        return sum(1 for x in self._ids if x)
    def club_formation(self, idx):
        return ('4-4-2', [])
    def club_slots(self, idx):
        return [(0, 0, 0)] * 10
    def team_name(self, ref=None):
        if ref is not None:
            try:
                i = int(ref)
                return self.teams[i]['name'] if 0 <= i < len(self.teams) else ''
            except Exception:
                return ''
        return self._team['name'] if self._team else self.info['club']
    def club_presets(self, idx):
        return []
    def club_lineup(self, idx):
        return [p for p in self.club_squad_ids(idx) if p][:23]
    def budget_settings(self):
        return {}
    def club_tactics(self, *a, **kw):
        return None
    def player_values(self, pids=None):
        return {}

    # -- write API: always blocked ------------------------------------------
    def write_guard(self):
        raise ValueError(READ_ONLY_MSG)
    def save(self, *a, **kw):
        raise ValueError(READ_ONLY_MSG)
    def set_lineup_by_ids(self, *a, **kw):
        raise ValueError(READ_ONLY_MSG)
    def set_formation(self, *a, **kw):
        raise ValueError(READ_ONLY_MSG)
    def set_my_tactics(self, *a, **kw):
        raise ValueError(READ_ONLY_MSG)
    def set_squad_numbers(self, *a, **kw):
        raise ValueError(READ_ONLY_MSG)

    def __getattr__(self, name):
        # Constants (offsets) -> 0, unknown methods -> empty neutral result.
        if name.isupper():
            return 0
        return _Neutral()


def open_save(folder, ro=False, date_order=None):
    return Pes17Save(folder, ro=ro, date_order=date_order)


# --------------------------------------------------------------------------
# Helpers used by server.py
# --------------------------------------------------------------------------
def default_config(save_dir):
    """Setup defaults when the selected save folder belongs to PES 2017."""
    return dict(pes_process='PES2017', auto_menu=False,
                pes17_date_order='dmy', save_dir=save_dir)


def looks_like_pes17_path(path):
    p = os.path.normcase(os.path.normpath(path or ''))
    return 'pro evolution soccer 2017' in p or 'pes2017' in p


def find_exe(save_dir):
    """Try to locate PES2017.exe next to the save folder / known installs."""
    cands = []
    up = save_dir
    for _ in range(4):
        up = os.path.dirname(up)
        cands.append(up)
    for root in (r'C:\Program Files (x86)\Steam\steamapps\common\Pro Evolution Soccer 2017',
                 r'C:\Program Files\Steam\steamapps\common\Pro Evolution Soccer 2017',
                 r'D:\Program Files (x86)\Steam\steamapps\common\Pro Evolution Soccer 2017',
                 r'C:\Games\Pro Evolution Soccer 2017'):
        cands.append(root)
    for c in cands:
        p = os.path.join(c, 'PES2017.exe')
        if os.path.isfile(p):
            return p
    return ''


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='PES 2017 save info')
    ap.add_argument('folder', help='decrypted PES 2017 ML save folder')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    r = read_save(a.folder)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print('%s: %s | %s | %s (%d clubs, %d players in squad)' % (
            r['info']['slot'], r['info']['club'], r['info']['league'],
            r['info']['date'], r['clubs'], len(r.get('squad', []))))
        for t in r.get('league_table', []):
            print('%2d %s' % (t['pos'], t['club']))
