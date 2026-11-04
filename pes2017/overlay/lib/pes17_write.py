"""PES 2017 save writer -- limited, measured, round-trip-verified operations.

This is deliberately NOT a port of mlwrite.py.  Only the tables whose layout
was confirmed on a real t99p17v20 PES 2017 save (and/or published, in-game
validated by the MLTE project) are writable here:

  * the encrypted container itself (176 B file header, PES 2017 master key),
  * transfer negotiation slots at 9,591,148 (280 B blocks / 16 B slots),
  * the 32 shirt numbers at club+512 (one byte per squad slot),
  * (experimental) one 8-byte squad slot at club+248,
  * four tables measured from real before/after save pairs supplied by the
    user: formation records (1,256,248), tactics (1,256,348), XI/squad order
    (1,256,728) and the budget u32 words (8,812,904 / 8,812,936) -- see
    lib/pes17_pairs.py.

Contracts, wages (other than the measured u32), loans, youth players, AI
transfers and forced transfers are still refused by the read-only Pes17Save
adapter used by the FL26 write endpoints.  See README_PES2017.txt.

Every write is done on a decrypted copy, re-encrypted with the PES 2017 key,
decrypted again in memory and compared byte-for-byte before the original
file is replaced.  A timestamped backup of the original save is kept.
"""
import json
import os
import shutil
import struct
import tempfile
import time

import pes17
import pes17_pairs
import pescrypt

KEY = pescrypt.KEY_PES17
PARTS = ('encryptHeader.dat', 'header.dat', 'description.dat', 'logo.png',
         'data.dat', 'version.txt')


class Pes17Container:
    """A decrypted PES 2017 save container (header.dat must be 176 bytes)."""

    def __init__(self, parts):
        self.parts = {k: bytes(v) for k, v in parts.items()}

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as f:
            raw = f.read()
        parts = pescrypt.decrypt_bytes(raw, KEY)
        if len(parts.get('header.dat', b'')) != 176:
            raise ValueError('Not a PES 2017 container: header.dat is %d bytes '
                             '(expected 176). PES 2021 / FL saves use 208.' %
                             len(parts.get('header.dat', b'')))
        if parts['header.dat'][144:146] not in (b'ML', b'ED'):
            raise ValueError('Not a PES 2017 ML/EDIT container (bad type string)')
        return cls(parts)

    @property
    def data(self):
        return self.parts['data.dat']

    def set_data(self, d):
        self.parts['data.dat'] = bytes(d)

    def encrypt(self):
        """Re-encrypt and PROVE the result decrypts back to the same parts."""
        raw = pescrypt.encrypt_parts(self.parts, KEY)
        back = pescrypt.decrypt_bytes(raw, KEY)
        for k in PARTS:
            if back[k] != self.parts[k]:
                raise ValueError('round-trip verification failed for %s' % k)
        if len(raw) != 320 + 176 + sum(len(self.parts[k]) for k in
                                       ('description.dat', 'logo.png',
                                        'data.dat', 'version.txt')):
            raise ValueError('round-trip size mismatch')
        return raw

    def save(self, path):
        raw = self.encrypt()
        tmp = path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(raw)
        os.replace(tmp, path)
        return len(raw)


def _decrypted_folder(container):
    """Write the parts to a temp folder so pes17.read_save() can parse them."""
    tmp = tempfile.mkdtemp(prefix='pes17view_')
    for k, v in container.parts.items():
        with open(os.path.join(tmp, k), 'wb') as f:
            f.write(v)
    with open(os.path.join(tmp, pes17.KEY_MARK), 'w') as f:
        f.write(pes17.PES17_GAME)
    return tmp


def _read_u32(data, off):
    """Little-endian u32, or 0 if the block is too short (never raise)."""
    return (struct.unpack_from('<I', data, off)[0]
            if off >= 0 and off + 4 <= len(data) else 0)


def info(container, edit_container=None, date_order=None):
    """Human-readable, real-save-derived state (no synthetic fallbacks)."""
    folder = _decrypted_folder(container)
    try:
        edit_data = edit_container.data if edit_container else None
        names = {}
        if edit_data:
            names = {p['id']: p['name'] for p in pes17.parse_edit(edit_data)}
        r = pes17.read_save(folder, names, date_order or pes17.configured_date_order(),
                            edit_data)
        data = container.data
        teams = pes17.team_records(data)
        mine = pes17.find_club(teams, r['info']['club'])
        sq = r.get('squad', [])
        out = dict(
            ok=True, pes17=True,
            container=dict(file_header=len(container.parts['header.dat']),
                           data_size=len(data),
                           type=container.parts['header.dat'][144:176].split(b'\0')[0].decode('ascii', 'replace'),
                           version=container.parts['version.txt'].decode('utf-16-le', 'replace').strip('\0')),
            info=r['info'], clubs=r['clubs'],
            squad=[dict(slot=x['slot'], id=x['id'], name=x['name'],
                        shirt=(pes17.shirt_numbers(data, mine)[x['slot']] if mine else 0))
                   for x in sq],
            league_table=r.get('league_table', []),
            league_name=r.get('league_name', ''),
            offers=pes17.read_offers(data, teams),
            teams=[dict(tid=t['tid'], name=t['name']) for t in teams],
            budget=dict(
                transfer_raw=_read_u32(data, pes17_pairs.BUDGET_MAIN),
                salary_raw=_read_u32(data, pes17_pairs.BUDGET_WAGE),
                transfer_offset=pes17_pairs.BUDGET_MAIN,
                salary_offset=pes17_pairs.BUDGET_WAGE,
                raw=True,
                note=('Raw u32 words measured from the budget pair; PES 2017 '
                      'currency scale is not confirmed in-game.')),
            measured_pairs={k: dict(offsets=len(v),
                                    first_offset=v[0][0], last_offset=v[-1][0])
                            for k, v in pes17_pairs.PAIRS.items()},
        )
        return out
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _allowed_ranges(teams):
    ranges = [(pes17.OFFERS0, pes17.OFFERS_END)]
    for t in teams:
        ranges.append((t['off'] + pes17.SHIRT_OFF,
                       t['off'] + pes17.SHIRT_OFF + pes17.SHIRT_SLOTS))
        ranges.append((t['off'] + pes17.SQUAD_OFF,
                       t['off'] + pes17.SQUAD_OFF + pes17.SQUAD_SLOTS * 8))
    # Tables measured from the user's four real before/after save pairs.
    ranges.extend(pes17_pairs.writable_ranges())
    return ranges


def apply_ops(container, ops, edit_data=None):
    """Apply a list of explicit operations to the decrypted data block.

    Supported ops:
      {"op":"offer_add",   "buyer":201, "slot":3, "pid":55246}
      {"op":"offer_clear", "buyer":"Birmingham City FC", "slot":3}
      {"op":"shirt",       "club":201, "slot":3, "number":9}
      {"op":"squad",       "club":201, "slot":3, "pid":0, "experimental":true}
      {"op":"pair",        "name":"formation|tactics|xi|budget"}
      {"op":"formation",   "index":0, "record":"<33-byte hex>"}
      {"op":"tactics",     "values":{"1256356":3}}
      {"op":"xi",          "order":[0,15,4,12,23,21,8,18,5,1,25, ...26 ints]}
      {"op":"budget",      "value":3088641, "wage":10245745}

    Returns (list of results, changed byte count).  No disk write occurs here.
    """
    original = container.data
    d = bytearray(original)
    teams = pes17.team_records(d)
    results = []
    for i, op in enumerate(ops or []):
        try:
            kind = str(op.get('op', '')).lower()
            if kind in ('offer_add', 'offer'):
                results.append(pes17.write_offer(d, teams, op.get('buyer'),
                                                 op.get('slot', 0), op.get('pid'),
                                                 op.get('source', 'auto'),
                                                 bool(op.get('claim', False))))
            elif kind in ('offer_clear', 'offer_del', 'offer_cancel'):
                results.append(pes17.clear_offer(d, teams, op.get('buyer'),
                                                 op.get('slot', 0),
                                                 bool(op.get('claim', False))))
            elif kind in ('shirt', 'shirt_number'):
                club = pes17.club_by(teams, op.get('club'))
                if not club:
                    raise ValueError('unknown club: %r' % op.get('club'))
                results.append(pes17.set_shirt_number(d, club, op.get('slot', 0),
                                                      op.get('number')))
            elif kind == 'squad':
                results.append(pes17.set_squad_slot(
                    d, teams, op.get('club'), op.get('slot', 0), op.get('pid'),
                    op.get('source'), bool(op.get('experimental', False))))
            elif kind == 'pair':
                results.append(pes17_pairs.apply_pair(
                    d, str(op.get('name')), strict=bool(op.get('strict', True))))
            elif kind == 'formation':
                results.append(pes17_pairs.set_formation_record(
                    d, op.get('record'), int(op.get('index', 0))))
            elif kind in ('tactics', 'tactic'):
                results.append(pes17_pairs.set_tactic_bytes(d, op.get('values')))
            elif kind in ('xi', 'lineup', 'xi_order'):
                results.append(pes17_pairs.set_xi_order(d, op.get('order')))
            elif kind == 'budget':
                results.append(pes17_pairs.set_budget(d, op.get('value'),
                                                      op.get('wage')))
            elif kind == 'raw':
                # Escape hatch for offsets the user measured with
                # pes17_layout.py diff.  Values are little-endian u32 words.
                off, vals = int(op['offset']), [int(x) for x in op['values']]
                if not (0 <= off and off + 4 * len(vals) <= len(d)):
                    raise ValueError('raw offset out of range')
                if str(op.get('mode', 'u32')) != 'u32':
                    raise ValueError('only u32 raw writes are supported')
                old = list(struct.unpack_from('<%dI' % len(vals), d, off))
                struct.pack_into('<%dI' % len(vals), d, off, *vals)
                results.append(dict(op='raw', offset=off, old=old, new=vals))
            else:
                raise ValueError('unknown op %r' % kind)
        except Exception as e:
            raise ValueError('op %d (%s) failed: %s' % (i, op.get('op'), e)) from e

    # Safety net: every changed byte must lie inside a measured table.
    allowed = _allowed_ranges(teams)
    changed = 0
    for j, (a, b) in enumerate(zip(original, d)):
        if a != b:
            changed += 1
            if not any(lo <= j < hi for lo, hi in allowed):
                raise ValueError('refusing to write: byte %d is outside every '
                                 'measured PES 2017 table' % j)
    container.set_data(d)
    return results, changed


def save_with_backup(path, container, work_dir, dry=False):
    """Round-trip verify, back up the original and replace it."""
    raw = container.encrypt()                     # proves decryptability
    result = dict(ok=True, size=len(raw), sha256=None)
    if dry:
        result['dry'] = True
        result['backup'] = None
        return result
    os.makedirs(os.path.join(work_dir, 'backup'), exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    backup = os.path.join(work_dir, 'backup',
                          '%s_%s_pes17' % (os.path.basename(path), stamp))
    shutil.copy2(path, backup)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(raw)
    os.replace(tmp, path)
    # Prove the on-disk file decrypts to the parts we intended.
    back = Pes17Container.load(path)
    if back.data != container.data:
        raise ValueError('on-disk verification failed: restore from %s' % backup)
    result['backup'] = backup
    result['sha256'] = __import__('hashlib').sha256(raw).hexdigest()
    return result


def _data_only(data):
    """A minimal container holding just a decrypted data.dat (no encrypt())."""
    return Pes17Container({'header.dat': bytes(176), 'data.dat': bytes(data),
                           'description.dat': b'', 'logo.png': b'',
                           'version.txt': b'', 'encryptHeader.dat': bytes(320)})


def load_edit(path):
    """Load an encrypted EDIT00000000 (or a decrypted folder / data.dat)."""
    if os.path.isdir(path):
        with open(os.path.join(path, 'data.dat'), 'rb') as f:
            return _data_only(f.read())
    with open(path, 'rb') as f:
        raw = f.read()
    # A decrypted data.dat has a long zero run near its start; an encrypted
    # container starts with high-entropy bytes.
    if len(raw) > 1000000 and bytes(100) in raw[:256]:
        return _data_only(raw)
    return Pes17Container.load(path)


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description='PES 2017 save tools')
    ap.add_argument('cmd', choices=('info', 'offers', 'roundtrip', 'apply'))
    ap.add_argument('save', help='encrypted ML00000000-style save')
    ap.add_argument('--edit', help='encrypted EDIT00000000')
    ap.add_argument('--ops', help='JSON file with a list of write ops')
    ap.add_argument('--work', default='.', help='backup directory')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    c = Pes17Container.load(a.save)
    if a.cmd == 'roundtrip':
        raw = c.encrypt()
        print('OK: %d bytes decrypt back byte-for-byte to all 6 parts' % len(raw))
        return
    ec = load_edit(a.edit) if a.edit else None
    if a.cmd == 'info':
        print(json.dumps(info(c, ec), ensure_ascii=False, indent=1))
        return
    if a.cmd == 'offers':
        print(json.dumps(pes17.read_offers(c.data, pes17.team_records(c.data)),
                         ensure_ascii=False, indent=1))
        return
    with open(a.ops, encoding='utf-8') as f:
        ops = json.load(f)
    res, changed = apply_ops(c, ops, ec.data if ec else None)
    print(json.dumps(dict(results=res, changed_bytes=changed), ensure_ascii=False, indent=1))
    print(json.dumps(save_with_backup(a.save, c, a.work, a.dry), indent=1))


if __name__ == '__main__':
    _cli()
