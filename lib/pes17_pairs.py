"""Measured PES 2017 write tables from real before/after save pairs.

The user supplied one common ``ML00000011`` (before) and four game-generated
saves, one per in-game action: ``formation/after``, ``tactics/after``,
``xi/after`` and ``budget/after`` (13,342,176 B each).  Each was decrypted with
the PES 2017 master key / 176-byte file header and byte-diffed against the
common before file.

211 bytes changed in ALL FOUR saves: a 32-byte per-save token at
``data.dat[48:80]`` (different in each save), a 170-byte stable save-state
delta, and two UI-state words.  Those are NOT action tables and are never
written here.  The offsets below are the bytes that changed in exactly ONE
pair, i.e. the tables the game itself writes for that action.

These are absolute offsets into the decrypted 13,304,607-byte ``data.dat`` of
THIS save.  Every write is checked against the observed before-byte, so a save
from a different season / patch state is refused instead of corrupted.

The game also rewrites ``header.dat[80:144]`` (64-byte hash) on every save.
Its algorithm is unknown; we keep the original hash, exactly as the public
MLTE tool does.  In-game load validation is still required -- see
REAL_SAVE_REPORT.md.
"""
import struct

DATA_SIZE = 13304607

# ---- table bases (measured, absolute) -------------------------------------
FORMATION0 = 1256248          # first of the 33-byte formation records
FORMATION_STRIDE = 33
FORMATION_RECORDS = 3
TACTICS0 = 1256348            # 15-byte tactics block (13 bytes changed)
TACTICS_LEN = 15
XI_ORDER = 1256728            # 26-byte lineup/squad order (permutation 0..25)
XI_ORDER_LEN = 26
XI_ORDER_BLOCK = 42           # 1256728..1256769 (order + subs/flags)
XI_FLOATS = 2230192           # 6 float32 formation sliders
XI_FLOATS_LEN = 24
XI_FLOATS2 = 2230322          # 2 more bytes changed by the XI edit
BUDGET_MAIN = 8812904         # u32, 2535240 -> 3088641 in the budget pair
BUDGET_WAGE = 8812936         # u32, 9692344 -> 10245745 in the budget pair

# ---- per-pair measured bytes ----------------------------------------------
# (offset, before_byte, after_byte).  Kept verbatim so a write can be proven
# to reproduce exactly what PES 2017 wrote.
PAIRS = {
    'formation': [
        (1256252, 0x05, 0x04), (1256254, 0x07, 0x05), (1256255, 0x06, 0x07),
        (1256256, 0x0a, 0x06), (1256257, 0x09, 0x0b), (1256267, 0x1a, 0x15),
        (1256268, 0x44, 0x34), (1256269, 0x1a, 0x1b), (1256270, 0x24, 0x44),
        (1256271, 0x1f, 0x1b), (1256272, 0x54, 0x24), (1256273, 0x1f, 0x1b),
        (1256274, 0x10, 0x58), (1256275, 0x29, 0x1b), (1256276, 0x54, 0x10),
        (1256278, 0x14, 0x40), (1256280, 0x34, 0x28),
    ],
    'tactics': [
        (1256348, 0x00, 0x01), (1256349, 0x01, 0x00), (1256350, 0x00, 0x01),
        (1256351, 0x00, 0x01), (1256352, 0x00, 0x01), (1256353, 0x00, 0x01),
        (1256356, 0x07, 0x03), (1256357, 0x13, 0x3c), (1256358, 0x00, 0x40),
        (1256359, 0x00, 0x03), (1256360, 0xff, 0x00), (1256361, 0x87, 0x77),
        (1256362, 0x02, 0x00),
    ],
    'xi': [
        (1256728, 0x09, 0x00), (1256732, 0x0d, 0x17), (1256733, 0x16, 0x15),
        (1256734, 0x13, 0x08), (1256735, 0x11, 0x12), (1256737, 0x03, 0x01),
        (1256738, 0x06, 0x19), (1256739, 0x19, 0x06), (1256741, 0x12, 0x11),
        (1256743, 0x15, 0x16), (1256744, 0x08, 0x13), (1256749, 0x17, 0x0d),
        (1256752, 0x00, 0x09), (1256753, 0x01, 0x03), (1256760, 0x16, 0x08),
        (1256761, 0x06, 0x05), (1256762, 0x05, 0x15), (1256765, 0x06, 0x05),
        (1256769, 0x06, 0x12),
        (2230194, 0x80, 0x00), (2230195, 0x3f, 0x40), (2230198, 0xe0, 0x00),
        (2230202, 0xa0, 0x00), (2230203, 0x3f, 0x00), (2230206, 0x80, 0x00),
        (2230207, 0x40, 0x00), (2230210, 0xa0, 0x00), (2230211, 0x40, 0x00),
        (2230322, 0x20, 0x00), (2230323, 0x41, 0x00),
    ],
    'budget': [
        (8812904, 0x48, 0x01), (8812905, 0xaf, 0x21), (8812906, 0x26, 0x2f),
        (8812936, 0xb8, 0x71), (8812937, 0xe4, 0x56), (8812938, 0x93, 0x9c),
        (9836708, 0x22, 0x26), (9836711, 0x01, 0x00), (9837055, 0x01, 0x00),
        (9840896, 0x16, 0x19), (9840992, 0x23, 0x26), (9840994, 0xc0, 0x40),
        (9840995, 0x02, 0x00), (9841338, 0x01, 0x00), (9841339, 0x01, 0x00),
        (9842324, 0x16, 0x19), (9842766, 0x01, 0x00), (9842767, 0x01, 0x00),
        (9844704, 0x16, 0x19), (9845146, 0x01, 0x00), (9845147, 0x01, 0x00),
    ],
}

# Blocks we are willing to rewrite as a whole (used by the safety net).
BLOCKS = (
    (FORMATION0, FORMATION0 + FORMATION_STRIDE * FORMATION_RECORDS, 'formation records'),
    (TACTICS0, TACTICS0 + TACTICS_LEN, 'tactics block'),
    (XI_ORDER, XI_ORDER + XI_ORDER_BLOCK, 'XI / squad order block'),
    (XI_FLOATS, XI_FLOATS + XI_FLOATS_LEN, 'XI formation sliders'),
    (XI_FLOATS2, XI_FLOATS2 + 2, 'XI slider tail'),
    (BUDGET_MAIN, BUDGET_MAIN + 4, 'budget u32'),
    (BUDGET_WAGE, BUDGET_WAGE + 4, 'wage budget u32'),
    (9836708, 9836712, 'budget companion A'),
    (9837055, 9837056, 'budget companion B'),
    (9840896, 9840897, 'budget companion C'),
    (9840992, 9840996, 'budget companion D'),
    (9841338, 9841340, 'budget companion E'),
    (9842324, 9842325, 'budget companion F'),
    (9842766, 9842768, 'budget companion G'),
    (9844704, 9844705, 'budget companion H'),
    (9845146, 9845148, 'budget companion I'),
)


# ---------------------------------------------------------------------------
# r5 layout guard
# ---------------------------------------------------------------------------
# The measured offsets above are ABSOLUTE and belong to ONE save: 13,304,607 B
# of decrypted data.dat from t99p17v20.  `pair` already refuses a save whose
# before-bytes differ, but the custom ops (formation/tactics/xi/budget) used to
# write arbitrary values with no layout check at all.  A save from another
# season or patch could therefore be silently corrupted.
#
# The guard below runs once, before any op is applied.  It checks:
#   * the exact data size (a hard requirement for real-sized saves),
#   * four season-tolerant structural markers inside the measured tables,
#   * a fingerprint of stable bytes sampled around those tables and across the
#     file (bytes identical in BEFORE and in ALL FOUR game-generated AFTERs,
#     and outside every writable range).
#
# The structural markers are deliberately generic (record prefixes, a
# permutation, plausible u32 words) so that a save the game has legitimately
# advanced still passes.  Synthetic test buffers (<10 MB) are reported as
# "synthetic" and are not user saves, so they are never written to disk.
MIN_REAL_SAVE = 10000000
MIN_ANCHOR_RATIO = 0.6

# (offset, expected byte) -- sampled from the five real saves, outside all
# writable ranges.  These never change between BEFORE and the four AFTERs.
TABLE_ANCHORS = {
    'formation': [(1255737, 203), (1255753, 203), (1255777, 1), (1255793, 13),
                  (1255810, 1), (1255826, 13), (1255843, 1), (1255859, 13)],
    'tactics':   [(1255836, 31), (1255852, 12), (1255868, 88), (1255885, 114),
                  (1255901, 114), (1255917, 1), (1255937, 1), (1255953, 13)],
    'xi':        [(1256242, 192), (1256347, 1), (1256364, 2), (1256381, 60),
                  (1256409, 1), (1256425, 13), (1256442, 1), (1256458, 13)],
    'xi_floats': [(2229680, 28), (2229696, 80), (2229712, 82), (2229728, 92),
                  (2229744, 71), (2229760, 29), (2229776, 59), (2229792, 39)],
    'budget':    [(8812394, 3), (8812410, 3), (8812426, 3), (8812442, 3),
                  (8812458, 3), (8812474, 3), (8812490, 3), (8812506, 3)],
}
GLOBAL_ANCHORS = [
    (1000000, 40), (2000411, 7), (3005343, 4), (4000822, 51),
    (5000137, 9), (6000137, 235), (8000000, 181), (9001096, 199),
    (10000000, 40), (12000000, 45),
]
ALL_ANCHORS = [(o, v) for rows in TABLE_ANCHORS.values() for o, v in rows] + \
              GLOBAL_ANCHORS


def structural_checks(d):
    """Season-tolerant structural markers for the four measured tables."""
    out = {}
    try:
        out['formation_markers'] = (
            bytes(d[FORMATION0:FORMATION0 + 4]) == b'\x00\x01\x01\x01' and
            bytes(d[FORMATION0 + 33:FORMATION0 + 37]) == b'\x00\x01\x01\x03' and
            bytes(d[FORMATION0 + 66:FORMATION0 + 70]) == b'\x00\x01\x01\x03')
    except (IndexError, TypeError):
        out['formation_markers'] = False
    try:
        out['tactics_markers'] = (d[TACTICS0 + 6] == 0 and d[TACTICS0 + 7] == 0)
    except (IndexError, TypeError):
        out['tactics_markers'] = False
    try:
        out['xi_permutation'] = (sorted(bytes(d[XI_ORDER:XI_ORDER + XI_ORDER_LEN]))
                                 == list(range(XI_ORDER_LEN)))
    except (IndexError, TypeError):
        out['xi_permutation'] = False
    try:
        main = struct.unpack_from('<I', d, BUDGET_MAIN)[0]
        wage = struct.unpack_from('<I', d, BUDGET_WAGE)[0]
        out['budget_plausible'] = (
            0 < main < (1 << 24) and 0 < wage < (1 << 24) and
            d[BUDGET_MAIN + 3] == 0 and d[BUDGET_WAGE + 3] == 0)
    except (struct.error, IndexError, TypeError):
        out['budget_plausible'] = False
    return out


def verify_layout(d, strict=True, require_real=False):
    """Prove ``d`` has the measured t99p17v20 layout before writing to it.

    Returns a report dict.  Raises ValueError when ``strict`` and a real-sized
    save fails the size check, a structural marker, or the anchor fingerprint.
    With ``strict=False`` the report carries the failures as warnings instead.
    Short buffers are synthetic test data and are reported, never refused --
    unless ``require_real`` is set by an explicit caller (HTTP / CLI), in
    which case any size other than DATA_SIZE is a hard refusal.
    """
    size = len(d)
    rep = dict(ok=True, mode='verified', data_size=size,
               expected_data_size=DATA_SIZE,
               note=('Measured offsets belong to one 13,304,607 B t99p17v20 '
                     'data.dat. This is a layout check, NOT in-game validation.'))
    if size < MIN_REAL_SAVE and not require_real:
        rep.update(mode='synthetic',
                   note='Buffer smaller than 10 MB: synthetic test data, no save is written.')
        return rep
    problems = []
    if size != DATA_SIZE:
        problems.append('data.dat is %d bytes, expected %d -- offsets would '
                        'point at unrelated data' % (size, DATA_SIZE))
        # Never read measured offsets from a shorter buffer: that raises
        # IndexError instead of producing a useful refusal.
        checks = dict.fromkeys(('formation_markers', 'tactics_markers',
                               'xi_permutation', 'budget_plausible'))
        matched, total, ratio = 0, len(ALL_ANCHORS), 0.0
        rep['skipped_checks'] = 'wrong data size'
    else:
        checks = structural_checks(d)
        failed = [k for k, v in checks.items() if not v]
        if failed:
            problems.append('table structure differs: ' + ', '.join(sorted(failed)))
        matched = sum(1 for o, v in ALL_ANCHORS if d[o] == v)
        total = len(ALL_ANCHORS)
        ratio = matched / float(total) if total else 1.0
        if ratio < MIN_ANCHOR_RATIO:
            problems.append('only %d/%d layout anchors match (need %.0f%%)' %
                            (matched, total, MIN_ANCHOR_RATIO * 100))
    rep['checks'] = checks
    rep.update(anchors_matched=matched, anchors_total=total,
               anchor_ratio=round(ratio, 3))
    rep['problems'] = problems
    if problems:
        rep['ok'] = False
        if strict:
            raise ValueError('PES 2017 layout verification FAILED: ' +
                             '; '.join(problems) +
                             '. Refusing to write. Re-measure this save with '
                             'tools/diff_saves.py, or explicitly disable the '
                             'layout check (advanced, at your own risk).')
        rep['mode'] = 'override'
        rep['warning'] = '; '.join(problems)
    return rep


def all_offsets():
    """Every allow-listed byte offset (union of all four measured pairs)."""
    return sorted({o for rows in PAIRS.values() for o, _, _ in rows})


def writable_ranges():
    """(lo, hi) ranges for the byte-level safety net in apply_ops()."""
    return [(lo, hi) for lo, hi, _ in BLOCKS] + [(o, o + 1) for o in all_offsets()]


def apply_pair(d, name, strict=True):
    """Reproduce the exact measured change of one in-game action.

    ``d`` is a bytearray of decrypted ``data.dat``.  With ``strict`` (default)
    every current byte must equal the observed before-byte, so a different
    save cannot be silently corrupted.  Returns a report dict.
    """
    if not isinstance(d, bytearray):
        raise ValueError('apply_pair needs a bytearray')
    if name not in PAIRS:
        raise ValueError('unknown measured pair %r' % name)
    rows = PAIRS[name]
    mismatched = [(o, bef, d[o]) for o, bef, _ in rows
                  if o >= len(d) or (strict and d[o] != bef)]
    if mismatched:
        raise ValueError('%s: save does not match the measured before-state '
                         'at %d byte(s); first: %r' % (name, len(mismatched),
                                                       mismatched[:3]))
    changed = 0
    for o, bef, aft in rows:
        if d[o] != aft:
            d[o] = aft
            changed += 1
    return dict(op='pair', name=name, offsets=len(rows), changed_bytes=changed,
                first_offset=rows[0][0], last_offset=rows[-1][0])


def set_formation_record(d, record, index=0):
    """Write one complete 33-byte formation record.

    ``record`` is bytes/hex of exactly 33 bytes.  The four-byte prefix
    ``00 01 01 01`` is a fixed marker and must be preserved; every other byte
    must be <= 0x60 (the observed coordinate/role value range).
    """
    if isinstance(record, str):
        record = bytes.fromhex(record.replace(' ', '').replace('0x', ''))
    record = bytes(record)
    if len(record) != FORMATION_STRIDE:
        raise ValueError('formation record must be exactly %d bytes' %
                         FORMATION_STRIDE)
    if not 0 <= index < FORMATION_RECORDS:
        raise ValueError('formation index out of range (0..%d)' %
                         (FORMATION_RECORDS - 1))
    if record[:4] != b'\x00\x01\x01\x01':
        raise ValueError('formation record prefix must be 00 01 01 01')
    if any(x > 0x60 for x in record[4:]):
        raise ValueError('formation coordinate/role byte out of range (>0x60)')
    off = FORMATION0 + index * FORMATION_STRIDE
    old = bytes(d[off:off + FORMATION_STRIDE])
    d[off:off + FORMATION_STRIDE] = record
    return dict(op='formation', offset=off, old=old.hex(), new=record.hex(),
                changed_bytes=sum(1 for a, b in zip(old, record) if a != b))


def set_tactic_bytes(d, values):
    """Write allow-listed bytes inside the 15-byte tactics block.

    ``values`` maps either an absolute offset or a 0-based index in the block
    to a byte (0..255).  Only the 13 offsets the game actually changed are
    writable.
    """
    allowed = {o for o, _, _ in PAIRS['tactics']}
    report = []
    for key, val in dict(values).items():
        k = int(key)
        off = k if k >= TACTICS0 else TACTICS0 + k
        if off not in allowed:
            raise ValueError('tactics offset %d is not a measured byte' % off)
        if not 0 <= int(val) <= 255:
            raise ValueError('tactics value must be 0..255')
        old = d[off]
        d[off] = int(val)
        report.append(dict(offset=off, old=old, new=int(val)))
    return dict(op='tactics', writes=report,
                changed_bytes=sum(1 for r in report if r['old'] != r['new']))


def set_xi_order(d, order):
    """Write the 26-byte squad-order table (a permutation of 0..25).

    The first 11 entries are the starting XI in the game's slot order; the
    rest are the bench/reserve order.  A permutation check prevents duplicate
    or out-of-range squad slots.
    """
    order = [int(x) for x in order]
    if len(order) != XI_ORDER_LEN:
        raise ValueError('XI order must contain exactly %d slots' % XI_ORDER_LEN)
    if sorted(order) != list(range(XI_ORDER_LEN)):
        raise ValueError('XI order must be a permutation of 0..%d' %
                         (XI_ORDER_LEN - 1))
    old = bytes(d[XI_ORDER:XI_ORDER + XI_ORDER_LEN])
    d[XI_ORDER:XI_ORDER + XI_ORDER_LEN] = bytes(order)
    return dict(op='xi', offset=XI_ORDER, old=list(old), new=order,
                changed_bytes=sum(1 for a, b in zip(old, order) if a != b))


def set_budget(d, value, wage=None):
    """Write the two measured budget u32 words (little-endian).

    Only ``BUDGET_MAIN`` (8812904) and optionally ``BUDGET_WAGE`` (8812936)
    are written.  The other 15 companion bytes the game touched are available
    through the exact ``pair`` op instead of being guessed here.
    """
    v = int(value)
    if not 0 <= v <= 0xffffffff:
        raise ValueError('budget must be a u32')
    old = struct.unpack_from('<I', d, BUDGET_MAIN)[0]
    struct.pack_into('<I', d, BUDGET_MAIN, v)
    res = dict(op='budget', offset=BUDGET_MAIN, old=old, new=v,
               changed_bytes=sum(1 for a, b in zip(
                   struct.pack('<I', old), struct.pack('<I', v)) if a != b))
    if wage is not None:
        w = int(wage)
        if not 0 <= w <= 0xffffffff:
            raise ValueError('wage must be a u32')
        oldw = struct.unpack_from('<I', d, BUDGET_WAGE)[0]
        struct.pack_into('<I', d, BUDGET_WAGE, w)
        res['wage'] = dict(offset=BUDGET_WAGE, old=oldw, new=w)
        res['changed_bytes'] += sum(1 for a, b in zip(
            struct.pack('<I', oldw), struct.pack('<I', w)) if a != b)
    return res
