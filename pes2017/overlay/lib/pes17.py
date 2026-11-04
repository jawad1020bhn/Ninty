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
  refuses every write,
* the two measured budget u32 words (8,812,904 / 8,812,936), exposed raw on
  the read side -- previously this adapter returned a hardcoded 0, which is
  why the app showed "Budget EUR 0".

Four tables (formation, tactics, XI, budget) WERE measured on real
before/after save pairs and are writable only through lib/pes17_write.py on
the PES 2017 tools page.  Everything else (transfers, contracts, loans,
youth, AI transfers, ...) is still blocked: those PES 2017 tables have
different offsets and have not been measured.  lib/pes17_layout.py is the
companion tool for that measurement.
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
    'English 1st Division', 'English 2nd Division', 'Ligue 1', 'Ligue 2',
    'Italian 1st Division', 'Italian 2nd Division', 'Eredivisie',
    'Spanish 1st Division', 'Spanish 2nd Division', 'Portuguese 1st Division',
    'Brazilian 1st Division', 'Argentine 1st Division', 'PEU League',
    'PLA League', 'PAS League', 'Other European Teams',
    'Other Latin American Teams', 'Other Asian Teams',
)
# Blocks 12..15 are not at root + 12*2600: MLTE measured explicit offsets.
STANDINGS_EXTRA = {
    12: 62488, 13: 65080, 14: 67680, 15: 70272,
}
# MLTE LeagueMaps: EDIT league-block index -> competition-name record index.
LEAGUE_COMP_INDEX = (10, 37, -1, -1, 11, 39, -1, 12, 38, 13, 22, 20,
                     29, 30, 31, -1, -1, -1)
LEAGUE_COUNT = 18
COMP_NAMES0 = 4333942        # EDIT competition-name table
COMP_NAME_STRIDE = 124
COMP_NAME_LEN = 64
TEAM_ARRAY0 = 4782840        # EDIT league member arrays (18 x 80 B)
EDIT_SENTINEL = 262143       # 0x3FFFF, unused standings/offer slot

# Two u32 words that changed ONLY in the user's real "budget" before/after
# save pair (see lib/pes17_pairs.py).  These are RAW SAVE UNITS, not confirmed
# EUR amounts: FL26 stores its budget in 100-EUR units (mlwrite.Save.budget()
# multiplies by 100), but PES 2017's currency scale has NOT been checked in
# game, so no conversion is applied here.  Compare the number below with the
# number PES 2017 shows on screen before trusting the € sign in the app.
BUDGET_MAIN = 8812904         # 2535240 -> 3088641 in the budget pair
BUDGET_WAGE = 8812936         # 9692344 -> 10245745 in the budget pair

# 26-byte starting-XI / squad-order permutation measured on the XI pair
# (see lib/pes17_pairs.py).  Read only: the app's lineup() expects 35 slots.
XI_ORDER = 1256728
XI_ORDER_LEN = 26

# Measured on a real t99p17v20 save (see pes2017/REAL_SAVE_REPORT.md):
# the u32 at club+0 is a bit-packed value: (stable PES Team ID << 14) |
# Master League record index.  Standings and EDIT league arrays use the
# *stable* ID, so tid = cid >> 14 is the key that links the two tables.
TEAM_ID_SHIFT = 14
SHIRT_OFF = 512              # 32 one-byte shirt numbers, in squad-slot order
SHIRT_SLOTS = 32

# Transfer negotiation (offer) table -- audited by the MLTE project and
# confirmed on the real t99p17v20 ML save.
OFFERS0 = 9591148
OFFERS_END = 9829596
OFFER_BLOCK = 280            # 4 B buyer club id + 16 x 16 B slots + 20 B pad
OFFER_SLOT = 16
OFFER_SLOTS = 16
OFFER_EMPTY = (6488064, 65535, 0, 1664)
OFFER_ACTIVE = (0, 0, 0, 4210816)   # +4 source roster ptr, +8 player id

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
EDIT_TEAM0 = 3948120        # 800-slot x 480 B EDIT team table (before COMP_NAMES0)
EDIT_TEAM_STRIDE = 480
EDIT_TEAM_SLOTS = 800
EDIT_TEAM_NAME_OFF = 152
EDIT_TEAM_NAME_LEN = 70
EDIT_TEAM_ABBR_OFF = 222
EDIT_TEAM_ABBR_LEN = 10

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
        raw = head[o:o + 4]
        tid = cid >> TEAM_ID_SHIFT
        name = _text(head[o + TEAM_NAME_OFF:o + TEAM_NAME_OFF + TEAM_NAME_LEN])
        # PES 2021 / FL saves put the club *name* at 84 and a zero/ASCII word
        # at 80.  Real PES 2017 (and patched PES 2017) uses either a small
        # plain id or a bit-packed (tid << 14 | index) id -- never four
        # printable ASCII bytes.  Requiring 2+ named rows at stride 1312 also
        # rejects PES 2021's stride-1680 club table.
        ascii_word = all(32 <= b < 127 for b in raw)
        good_id = (0 < cid < 1000000) or (0 < tid < 20000)
        if (cid not in (0, 0xFFFFFFFF) and good_id and not ascii_word
                and _plausible_name(name)):
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
            # tid = stable PES Team ID (cid >> 14) for patched saves; for
            # unpatched/synthetic saves the plain id is already the team id.
            tid = (cid >> TEAM_ID_SHIFT) or cid
            # Stats fields are not mapped yet -- keep the shape mlsave returns.
            out.append(dict(idx=k, off=o, id=cid, tid=tid, name=name,
                            pts=0, pl=0, w=0, d=0,
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


def competition_names(edit_data):
    """Custom competition names from the user's EDIT00000000 (patch-aware)."""
    out = list(STANDINGS_LEAGUES)
    if not edit_data:
        return out
    for i, comp in enumerate(LEAGUE_COMP_INDEX):
        if comp < 0 or i >= len(out):
            continue
        o = COMP_NAMES0 + comp * COMP_NAME_STRIDE
        if o + COMP_NAME_LEN > len(edit_data):
            continue
        name = _text(bytes(edit_data[o:o + COMP_NAME_LEN]))
        if name:
            out[i] = name
    return out


def standings_offsets(data, edit_data):
    """Locate each league's standings block from the EDIT member arrays.

    A patch (e.g. t99p17v20) moves and reorders these blocks, so the static
    MLTE offsets are only a fallback.  Matching the first four member team
    ids of each EDIT league array against the ML data finds the real block.
    """
    offs = {}
    if not edit_data:
        return offs
    for i in range(LEAGUE_COUNT):
        o = TEAM_ARRAY0 + i * 80
        if o + 80 > len(edit_data):
            break
        ids = [x for x in struct.unpack_from('<20I', edit_data, o)
               if 0 < x < EDIT_SENTINEL]
        if len(ids) < 4:
            continue
        seq = struct.pack('<4I', *ids[:4])
        best, best_score = None, -1
        start = 0
        while True:
            p = data.find(seq, start)
            if p < 0:
                break
            start = p + 1
            if p + 80 > len(data):
                continue
            row = struct.unpack_from('<20I', data, p)
            score = sum(1 for x in row if 0 < x < EDIT_SENTINEL)
            if score > best_score:
                best, best_score = p, score
        # A stray 4-id match inside another table scores low; the real
        # standings block has most of its 20 member ids present.
        if best is not None and best_score >= 8:
            offs[i] = best
    return offs


def standings(data, teams, edit_data=None):
    """League membership/order from the standing structures.

    Each block starts with 20 u32 *stable* team ids in table order.  On
    patched saves those ids are the club record's ``tid`` (cid >> 14), not
    the raw bit-packed cid.  Points, wins and goals are NOT mapped for
    PES 2017 yet, so those fields stay 0.
    """
    by_ref = {t['id']: t for t in teams}
    by_ref.update({t['tid']: t for t in teams})
    found = standings_offsets(data, edit_data)
    blocks = []
    for i, league in enumerate(competition_names(edit_data)):
        off = found.get(i)
        if off is None:
            off = STANDINGS0 + (STANDINGS_EXTRA.get(i, i * STANDINGS_STRIDE))
        if off + STANDINGS_TEAMS * 4 > len(data):
            continue
        ids = [struct.unpack_from('<I', data, off + 4 * j)[0]
               for j in range(STANDINGS_TEAMS)]
        ids = [x for x in ids if 0 < x < EDIT_SENTINEL]
        if not ids:
            continue
        rows = []
        for pos, cid in enumerate(ids, 1):
            t = by_ref.get(cid)
            if not t:
                continue
            rows.append(dict(pos=pos, club=t['name'], pl=0, w=0, d=0, l=0,
                             gf=0, ga=0, gd=0, pts=0, idx=t['idx'], id=cid))
        if rows:
            blocks.append(dict(league=league, offset=off, rows=rows))
    return blocks


def read_save(folder, names=None, date_order='dmy', edit_data=None):
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
        blocks = standings(data, teams, edit_data)
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
    # Patches can carry far more than the vanilla 21,000 players, and EDIT
    # data.dat is larger than the vanilla 3,948,120 B.  Trust the header count
    # but bound it by the actual file length so a patched EDIT file is fully
    # imported and a truncated one cannot read past the end.
    by_len = max(0, (len(data) - EDIT_HEADER) // EDIT_RECORD)
    if not (0 < n <= 100000):
        n = by_len
    n = min(n, by_len)
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


def edit_teams(data):
    """-> list of {tid, name, abbr, idx} from EDIT00000000's 480 B team table."""
    if len(data) < EDIT_TEAM0 + EDIT_TEAM_STRIDE:
        return []
    end = min(len(data) - EDIT_TEAM_STRIDE, COMP_NAMES0 - EDIT_TEAM_STRIDE,
              EDIT_TEAM0 + EDIT_TEAM_SLOTS * EDIT_TEAM_STRIDE)
    out, seen = [], set()
    idx = 0
    for o in range(EDIT_TEAM0, end + 1, EDIT_TEAM_STRIDE):
        tid = struct.unpack_from('<I', data, o)[0]
        name = _text(bytes(data[o + EDIT_TEAM_NAME_OFF:o + EDIT_TEAM_NAME_OFF + EDIT_TEAM_NAME_LEN]))
        abbr = _text(bytes(data[o + EDIT_TEAM_ABBR_OFF:o + EDIT_TEAM_ABBR_OFF + EDIT_TEAM_ABBR_LEN]))
        if 0 < tid < EDIT_SENTINEL and tid not in seen and _plausible_name(name):
            seen.add(tid)
            out.append(dict(tid=tid, name=name, abbr=abbr, idx=idx))
        idx += 1
    return out


def import_edit(src, outdir):
    """Build players.json / ratings.json / positions.json / playpos.json.

    Returns a small stats dict.  The generated files use exactly the shapes
    the app's reload_db() expects.
    """
    ed = _edit_data(src)
    players = parse_edit(ed)
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
    eteams = edit_teams(ed)
    if eteams:
        tp = os.path.join(outdir, 'teamids.json')
        ids = {}
        if os.path.isfile(tp):
            try:
                with open(tp, encoding='utf-8') as f:
                    ids = json.load(f)
            except Exception:
                ids = {}
        for t in eteams:
            ids.setdefault(str(t['tid']), t['name'])
        dump('teamids.json', ids)
    return dict(players=len(players), teams=len(eteams), dir=outdir, source=str(src))


def import_teams(folder, outdir, edit_src=None):
    """teamids.json from the ML save club table (+ optional EDIT00000000)."""
    with open(os.path.join(folder, 'data.dat'), 'rb') as f:
        teams = team_records(f.read())
    os.makedirs(outdir, exist_ok=True)
    ids = {}
    if os.path.isfile(os.path.join(outdir, 'teamids.json')):
        try:
            with open(os.path.join(outdir, 'teamids.json'), encoding='utf-8') as f:
                old = json.load(f)
            if isinstance(old, dict):
                ids.update(old)
        except Exception:
            pass
    for t in teams:
        # Stable team id is what standings / EDIT league arrays / negotiations
        # use; keep the raw bit-packed id as an alias too.
        if t['tid']:
            ids[str(t['tid'])] = t['name']
        if t['id'] and str(t['id']) not in ids:
            ids[str(t['id'])] = t['name']
    if edit_src and os.path.exists(edit_src):
        try:
            for t in edit_teams(_edit_data(edit_src)):
                ids.setdefault(str(t['tid']), t['name'])
        except Exception:
            pass
    with open(os.path.join(outdir, 'teamids.json'), 'w', encoding='utf-8') as f:
        json.dump(ids, f, ensure_ascii=False, indent=1)
    return dict(teams=len(teams))


_TEAMIDS_SIG = {'key': None}


def ensure_teamids(cfg, outdir, force=False):
    """Populate `outdir/teamids.json` directly from `save_dir` (ML* + EDIT00000000).

    Works on the very first request to `/` or `/pes17.html` without requiring
    `/api/state` or `slot_folder()` to decrypt a working copy first.  Read-only
    against `save_dir`; writes only inside `outdir`.
    """
    if not cfg or not outdir:
        return False
    sd = (cfg.get('save_dir') or '').strip()
    ed = (cfg.get('edit_dat') or (os.path.join(sd, 'EDIT00000000') if sd else '')).strip()
    tp = os.path.join(outdir, 'teamids.json')

    ml_path = ''
    if sd and os.path.isdir(sd):
        try:
            mls = []
            for fn in os.listdir(sd):
                if fn.upper().startswith('ML') and len(fn) >= 10:
                    fp = os.path.join(sd, fn)
                    if os.path.isfile(fp):
                        mls.append((os.path.getmtime(fp), fp))
            if mls:
                mls.sort(reverse=True)
                ml_path = mls[0][1]
        except OSError:
            pass

    if not ml_path and not (ed and os.path.exists(ed)):
        return os.path.isfile(tp)

    sig_parts = []
    for p in (ml_path, ed):
        if p and os.path.exists(p):
            try:
                st = os.stat(p)
                sig_parts.append((p, int(st.st_mtime), st.st_size))
            except OSError:
                pass
    sig = (outdir, tuple(sig_parts))
    if not force and _TEAMIDS_SIG['key'] == sig and os.path.isfile(tp):
        return True

    ids = {}
    if os.path.isfile(tp):
        try:
            with open(tp, encoding='utf-8') as f:
                cur = json.load(f)
            if isinstance(cur, dict):
                ids.update(cur)
        except Exception:
            pass

    wrote = False
    if ml_path:
        try:
            import pescrypt
            with open(ml_path, 'rb') as f:
                raw = f.read()
            parts = pescrypt.decrypt_bytes(raw, KEY_PES17)
            for t in team_records(parts['data.dat']):
                if t['tid']:
                    ids[str(t['tid'])] = t['name']
                    wrote = True
                if t['id'] and str(t['id']) not in ids:
                    ids[str(t['id'])] = t['name']
                    wrote = True
        except Exception:
            pass

    if ed and os.path.exists(ed):
        try:
            for t in edit_teams(_edit_data(ed)):
                if str(t['tid']) not in ids:
                    ids[str(t['tid'])] = t['name']
                wrote = True
        except Exception:
            pass

    if wrote and ids:
        try:
            os.makedirs(outdir, exist_ok=True)
            tmp = tp + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(ids, f, ensure_ascii=False, indent=1)
            os.replace(tmp, tp)
            _TEAMIDS_SIG['key'] = sig
            return True
        except OSError:
            pass
    return os.path.isfile(tp)


# --------------------------------------------------------------------------
# Measured write tables (used by lib/pes17_write.py)
# --------------------------------------------------------------------------
def club_by(teams, ref):
    """Resolve a club by stable tid / raw id / name (or a loose name prefix)."""
    if ref is None or ref == '':
        return None
    s = str(ref).strip()
    try:
        n = int(s)
    except ValueError:
        n = None
    if n is not None:
        for t in teams:
            if n in (t['tid'], t['id']):
                return t
        for t in teams:
            if n == t['idx']:
                return t
    key = _norm(s)
    for t in teams:
        if _norm(t['name']) == key:
            return t
    for t in teams:
        if key and key in _norm(t['name']):
            return t
    return None


def shirt_numbers(data, team):
    """32 one-byte shirt numbers at club + SHIRT_OFF, in squad-slot order."""
    o = team['off'] + SHIRT_OFF
    return list(bytes(data[o:o + SHIRT_SLOTS]))


def set_shirt_number(data, team, slot, number):
    """Write one shirt number.  ``data`` must be a bytearray."""
    slot, number = int(slot), int(number)
    if not 0 <= slot < SHIRT_SLOTS:
        raise ValueError('shirt slot must be 0..31')
    if not 1 <= number <= 99:
        raise ValueError('shirt number must be 1..99')
    o = team['off'] + SHIRT_OFF + slot
    old = data[o]
    data[o] = number
    return dict(offset=o, old=old, new=number)


def offer_blocks(data, teams=None):
    """-> [(block offset, raw buyer id, stable buyer tid), ...]

    The buyer field is the *raw* bit-packed club id from the club table, not
    the shifted team id.  Passing ``teams`` filters out the 0xFFFFFFFF
    sentinel blocks and any garbage blocks.
    """
    raw_ids = {t['id'] for t in teams} if teams else None
    out = []
    end = min(OFFERS_END, len(data) - OFFER_BLOCK)
    for off in range(OFFERS0, end + 1, OFFER_BLOCK):
        cid = struct.unpack_from('<I', data, off)[0]
        if 0 < cid < 0xFFFFFFFF and (raw_ids is None or cid in raw_ids):
            out.append((off, cid, cid >> TEAM_ID_SHIFT))
    return out


def find_offer_block(data, teams, buyer, claim=False):
    """Find the 280 B negotiation block of a club.

    Human-controlled clubs normally have no AI negotiation block (the MLTE
    project skips them).  With ``claim=True`` an unused 0xFFFFFFFF block is
    claimed by writing the club's raw id at its start.  That step is a
    structural inference, NOT in-game validated, and is reported as such.
    """
    club = club_by(teams, buyer)
    if not club:
        raise ValueError('unknown buyer club: %r' % buyer)
    hits = [(o, cid) for o, cid, tid in offer_blocks(data, teams)
            if cid == club['id']]
    if len(hits) > 1:
        raise ValueError('ambiguous negotiation blocks for %s' % club['name'])
    if hits:
        return hits[0][0], club, False
    if not claim:
        raise ValueError('no negotiation block for %s (tid %d). This is '
                         'usually the human-controlled club; pass claim=true '
                         'to use an unused block (experimental).' %
                         (club['name'], club['tid']))
    for off in range(OFFERS0, min(OFFERS_END, len(data) - OFFER_BLOCK) + 1,
                     OFFER_BLOCK):
        if struct.unpack_from('<I', data, off)[0] == 0xFFFFFFFF:
            struct.pack_into('<I', data, off, club['id'])
            return off, club, True
    raise ValueError('no unused negotiation block available')


def find_player_source(data, teams, pid):
    """Roster pointer (first u32 of the 8 B squad slot) of a player."""
    for t in teams:
        o = t['off'] + SQUAD_OFF
        for i in range(SQUAD_SLOTS):
            ptr, p = struct.unpack_from('<II', data, o + i * 8)
            if p == pid:
                return ptr, t, i
    return 0, None, None


def read_offers(data, teams):
    """Active negotiations currently in the save (garbage blocks excluded)."""
    by_raw = {t['id']: t for t in teams}
    out = []
    for off, cid, tid in offer_blocks(data, teams):
        club = by_raw.get(cid)
        for i in range(OFFER_SLOTS):
            s = off + 4 + i * OFFER_SLOT
            status, source, pid, transfer = struct.unpack_from('<4I', data, s)
            if 0 < pid < 1000000 and pid != 6488064:
                out.append(dict(buyer=club['name'] if club else str(tid),
                                buyer_tid=club['tid'] if club else tid,
                                slot=i, offset=s, pid=pid,
                                source=source, status=status, transfer=transfer))
    return out


def _offer_slot(data, teams, buyer, slot, claim=False):
    off, club, claimed = find_offer_block(data, teams, buyer, claim)
    slot = int(slot)
    if not 0 <= slot < OFFER_SLOTS:
        raise ValueError('offer slot must be 0..15')
    return off + 4 + slot * OFFER_SLOT, club, claimed, off


def write_offer(data, teams, buyer, slot, pid, source=None, claim=False):
    """Inject an active transfer negotiation (MLTE-verified slot layout)."""
    s, club, claimed, block = _offer_slot(data, teams, buyer, slot, claim)
    pid = int(pid)
    if pid <= 0:
        raise ValueError('player id must be positive')
    if source is None or source == 'auto':
        source, owner, sq = find_player_source(data, teams, pid)
        if owner is None:
            raise ValueError('player %d is not in any PES 2017 squad' % pid)
    else:
        source, owner, sq = int(source), None, None
    old = struct.unpack_from('<4I', data, s)
    struct.pack_into('<4I', data, s, OFFER_ACTIVE[0], source, pid, OFFER_ACTIVE[3])
    return dict(op='offer_add', offset=s, buyer=club['name'], buyer_tid=club['tid'],
                slot=int(slot), pid=pid, source=source,
                source_club=owner['name'] if owner else '', old=list(old),
                claimed_block=block if claimed else None,
                experimental=bool(claimed))


def clear_offer(data, teams, buyer, slot, claim=False):
    """Restore the exact empty-slot pattern seen in real PES 2017 saves."""
    s, club, claimed, block = _offer_slot(data, teams, buyer, slot, claim)
    old = struct.unpack_from('<4I', data, s)
    struct.pack_into('<4I', data, s, *OFFER_EMPTY)
    return dict(op='offer_clear', offset=s, buyer=club['name'], slot=int(slot),
                old=list(old), claimed_block=block if claimed else None,
                experimental=bool(claimed))


def set_squad_slot(data, teams, club_ref, slot, pid, source=None, experimental=False):
    """Experimental: edit one 8-byte squad slot (roster pointer, player id).

    THIS IS NOT IN-GAME VALIDATED.  A real transfer also touches player
    ownership/contract tables that are not mapped yet.  Kept behind an
    explicit ``experimental`` flag so it cannot be triggered by accident.
    """
    if not experimental:
        raise ValueError('squad edits are experimental (no before/after save '
                         'pair was supplied); pass experimental=true')
    club = club_by(teams, club_ref)
    if not club:
        raise ValueError('unknown club: %r' % club_ref)
    slot, pid = int(slot), int(pid)
    if not 0 <= slot < SQUAD_SLOTS:
        raise ValueError('squad slot must be 0..31')
    if source is None:
        source = 65535 if pid == 0 else (pid * 0 + 0x1000 + slot)
    o = club['off'] + SQUAD_OFF + slot * 8
    old = struct.unpack_from('<II', data, o)
    struct.pack_into('<II', data, o, int(source), pid)
    return dict(op='squad', offset=o, club=club['name'], slot=slot, pid=pid,
                source=int(source), old=list(old), experimental=True)


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
        self.layout_note = ('PES 2017 save: club, squad, players, standings '
                            'and the measured budget u32 words are read; '
                            'FL26-style writes are blocked. Budget is shown '
                            'as a RAW save value (currency scale unverified). '
                            'Limited measured writes (offers, shirts, '
                            'formation, tactics, XI, budget) are on the '
                            'PES 2017 tools page. r5 reads real shirt '
                            'numbers and the starting XI order, and '
                            'verifies the save layout before any write.')
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
        """Real shirt numbers from club+512, keyed by squad slot (r5)."""
        if not self._team:
            return {}
        nums = shirt_numbers(self.d, self._team)
        return {i: n for i, n in enumerate(nums) if 0 < n <= 99}
    def lineup(self):
        """Real starting XI order from the measured 26-byte table (r5).

        mlwrite.Save.lineup() returns 35 slots; PES 2017 stores a 26-slot
        permutation, so the remaining 9 are padded with 0xFF like an empty
        slot.  A malformed table falls back to the old neutral placeholder.
        """
        fallback = list(range(11)) + [0xff] * 24
        if XI_ORDER + XI_ORDER_LEN > len(self.d):
            return fallback
        order = list(bytes(self.d[XI_ORDER:XI_ORDER + XI_ORDER_LEN]))
        if sorted(order) != list(range(XI_ORDER_LEN)):
            return fallback
        return order + [0xff] * (35 - XI_ORDER_LEN)
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
    def measured_budget(self):
        """Raw u32 budget words measured from the budget before/after pair.

        Deliberately unscaled: the FL26 app multiplies its own budget word by
        100, but PES 2017's currency scale is not in-game confirmed.  The app
        shows these numbers with a € sign; treat them as raw save units until
        they are compared with the figure PES 2017 displays.
        """
        def u32(off):
            if off < 0 or off + 4 > len(self.d):
                return 0
            return struct.unpack_from('<I', self.d, off)[0]
        return dict(transfer=u32(BUDGET_MAIN), salary=u32(BUDGET_WAGE),
                    offsets=dict(transfer=BUDGET_MAIN, salary=BUDGET_WAGE),
                    raw=True, currency_verified=False,
                    unit='raw u32 save units', label='RAW (not confirmed EUR)',
                    note=('Raw u32 words measured from the budget pair; '
                          'PES 2017 currency scale is not confirmed in-game. '
                          'The EUR sign in the FL26 UI is presentation only.'))
    def budget(self):
        """Read-side transfer budget (raw measured u32, NOT scaled to EUR)."""
        return self.measured_budget()['transfer']
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
        # FL26's sum-of-squad-salaries is not mapped for PES 2017.  The
        # measured salary u32 word is exposed through measured_budget() and
        # /api/pes17/info instead; returning it here would mislabel it as a
        # wage total in the finance views.
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
    up = save_dir or ''
    for _ in range(4):
        if not up:
            break
        up = os.path.dirname(up)
        cands.append(up)
    for root in (r'C:\Program Files (x86)\Steam\steamapps\common\Pro Evolution Soccer 2017',
                 r'C:\Program Files\Steam\steamapps\common\Pro Evolution Soccer 2017',
                 r'D:\Program Files (x86)\Steam\steamapps\common\Pro Evolution Soccer 2017',
                 r'C:\Games\Pro Evolution Soccer 2017',
                 r'D:\Games\Pro Evolution Soccer 2017'):
        cands.append(root)
    for c in cands:
        p = os.path.join(c, 'PES2017.exe')
        if os.path.isfile(p):
            return p
    try:
        import pes17_setup
        return pes17_setup.autodetect_exe(save_dir=save_dir)
    except Exception:
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
