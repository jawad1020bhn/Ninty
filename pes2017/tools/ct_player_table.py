#!/usr/bin/env python3
"""Cross-check the Cheat Engine table against the real PES 2017 ML save.

"Needed files/cheat engine variations.CT" is a *live process memory* table:
it hooks PES2017.exe with an AOB scan and describes one player's runtime
struct (height +0, weight +1, age +1C, name +38, contract year +b0, ...).

It contains NO save-file offsets.  But its field semantics let us locate the
ML player-record table inside the decrypted data.dat and interpret it:

  * search for a club's squad player IDs (u32) -> a table with 232 B records,
  * each record: pid at +0, pid again at +4, 46 B name at +8,
  * CT offset X maps to file offset (X - 0x30), because CT name +0x38 lines
    up with the file name at +8.

Measured on ML00000011 (Birmingham City FC): the table starts at 2,221,628.
The CONTRACT block lines up convincingly across all 26 players:
  contract year 2029..2032, month 8, day 31  (u16 / byte / byte at CT +b0/+b2/+b3)
Other CT fields (affection, form, stamina, team role, attributes) do NOT line
up with this single constant shift -- their values are implausible.  So the CT
is a semantic hint and a way to FIND the table, not a 1:1 file layout.  A
before/after pair is still needed before writing those fields.

This tool reports every field so the mismatch is visible; only the contract
fields should be trusted as measured.

Usage:
  python3 pes2017/tools/ct_player_table.py <decrypted_data.dat> [club name]
  python3 pes2017/tools/ct_player_table.py <ML00000011> --edit EDIT00000000
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'overlay', 'lib'))
import pes17  # noqa: E402

STRIDE = 232
CT_SHIFT = -0x30          # CT offset -> file record offset
CT_FIELDS = {
    'contract_year': (0xb0, '<H'),
    'contract_month': (0xb2, 'B'),
    'contract_day': (0xb3, 'B'),
    'affection': (0xb7, 'B'),
    'nationality': (0xbc, 'B'),
    'team_role_level': (0xbb, 'B'),
    'team_role': (0xc4, 'B'),
    'nickname': (0xc8, '<H'),
    'nickname_enable': (0xca, 'B'),
    'form_arrow': (0x1e, 'B'),
    'stamina_bar': (0x1c, 'B'),
    'age': (0x1c, 'B'),
}


def find_table(data, pids, window=(2000000, 3000000)):
    """Find a 232 B-stride run containing the given player IDs."""
    for pid in pids:
        q = struct.pack('<I', pid)
        start = 0
        while True:
            p = data.find(q, start)
            if p < 0:
                break
            start = p + 1
            if not (window[0] <= p <= window[1]):
                continue
            # the next squad id should be exactly STRIDE bytes later
            j = pids.index(pid)
            if j + 1 < len(pids):
                nxt = data.find(struct.pack('<I', pids[j + 1]), p, p + STRIDE * 2)
                if nxt == p + STRIDE:
                    return p
    return None


def read_records(data, start, count):
    out = []
    for i in range(count):
        o = start + i * STRIDE
        if o + STRIDE > len(data):
            break
        pid = struct.unpack_from('<I', data, o)[0]
        name = data[o + 8:o + 8 + 46].split(b'\0')[0].decode('utf-8', 'replace')
        row = dict(index=i, offset=o, id=pid, name=name)
        for field, (ct_off, fmt) in CT_FIELDS.items():
            p = o + ct_off + CT_SHIFT
            if p + struct.calcsize(fmt) <= len(data):
                row[field] = struct.unpack_from(fmt, data, p)[0]
        out.append(row)
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = sys.argv[1]
    if os.path.isdir(src):
        src = os.path.join(src, 'data.dat')
    with open(src, 'rb') as f:
        raw = f.read()
    if raw[:4] in (b'\x0a\x00\x00\x00', b'\x0e\x00\x00\x00') or len(raw) > 1000000 and bytes(100) in raw[:256]:
        data = raw                       # already decrypted
    else:
        import pescrypt
        data = pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES17)['data.dat']
    club = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else 'Birmingham City FC'
    teams = pes17.team_records(data)
    mine = pes17.find_club(teams, club)
    if not mine:
        print('club not found:', club)
        return 1
    pids = [x['id'] for x in pes17.squad(data, mine)]
    start = find_table(data, pids)
    if start is None:
        print('232 B player table not found for', club)
        return 1
    rows = read_records(data, start, len(pids))
    print(json.dumps(dict(club=mine['name'], table_offset=start, stride=STRIDE,
                          ct_shift=hex(CT_SHIFT), records=rows),
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
