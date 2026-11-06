"""Read-only identity table for verified FL26 serialized team layouts.

This deliberately does not enable or change the career save writer.
"""
import struct
from collections import Counter

LAYOUTS = ((2400, 3400), (750, 1300))
STRIDE = 1680


def read_teams(data):
    if bytes(data[:8]) != struct.pack('<II', 10, 80):
        raise ValueError('Unsupported career header for team identity')
    candidates = []
    for capacity, coaches in LAYOUTS:
        boundary = 80 + capacity * STRIDE
        if boundary + coaches * 600 > len(data):
            continue
        # The full following coach index table distinguishes capacities; a
        # valid prefix of an expanded team table is not a legacy layout.
        if any(struct.unpack_from('<I', data, boundary + i * 600)[0]
               not in (i, 65535) for i in range(coaches)):
            continue
        rows, ids, human = [], set(), 0
        try:
            for ref in range(capacity):
                offset = 80 + ref * STRIDE
                key = struct.unpack_from('<I', data, offset)[0]
                if key == 0xffffffff:
                    continue
                tid = key >> 14
                if key & 0x3fff != ref or not tid or tid in ids:
                    raise ValueError('Invalid or duplicate team key')
                field = bytes(data[offset + 4:offset + 74])
                if b'\0' not in field:
                    raise ValueError('Unterminated team name')
                name = field.split(b'\0')[0].decode('utf-8')
                if not name.strip() or not name.isprintable():
                    raise ValueError('Invalid team name')
                owner = data[offset + 0x41d]
                if owner not in (0, 255):
                    raise ValueError('Unsupported controller assignment')
                human += owner == 0
                ids.add(tid)
                rows.append({'ref': ref, 'id': tid, 'name': name})
            # pc297: menadzer moze voditi i reprezentaciju uz klub (u igri prihvatis ponudu): tada su dvije ljudske momcadi
            if human not in (1, 2) or len(rows) < 100:
                raise ValueError('Career ownership/table not verified')
        except (ValueError, UnicodeError, struct.error):
            continue
        candidates.append({'capacity': capacity, 'rows': rows,
                           'teamids': {str(r['id']): r['name'] for r in rows}})
    if len(candidates) != 1:
        raise ValueError('No single verified career team identity layout')
    return candidates[0]


def name_index(teamids):
    counts = Counter(teamids.values())
    return ({name: int(tid) for tid, name in teamids.items()
             if counts[name] == 1}, {name for name, n in counts.items() if n > 1})
