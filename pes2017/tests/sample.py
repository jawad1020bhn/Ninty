"""Build synthetic (but structurally faithful) PES 2017 saves for tests.

These are NOT real Konami saves: they reproduce the measured PES 2017 table
shapes so the compatibility layer can be tested without a Windows install.
"""
import json
import os
import struct

import pes17
import pescrypt

CLUBS = [
    'Arsenal FC', 'Chelsea FC', 'Liverpool FC', 'Manchester United FC',
    'Manchester City FC', 'Tottenham Hotspur FC', 'Everton FC', 'Leicester City FC',
    'West Ham United FC', 'Newcastle United FC', 'Aston Villa FC', 'Leeds United FC',
    'Southampton FC', 'Wolverhampton Wanderers FC', 'Crystal Palace FC',
    'Brighton & Hove Albion FC', 'Fulham FC', 'Nottingham Forest FC',
    'Bournemouth AFC', 'Brentford FC',
]
PLAYERS = [
    (1048577, 'P. Check', 0, 35, 88),
    (1048578, 'H. Bellerin', 3, 24, 79),
    (1048579, 'L. Koscielny', 1, 33, 84),
    (1048580, 'N. Monreal', 2, 32, 81),
    (1048581, 'G. Xhaka', 4, 26, 82),
    (1048582, 'A. Ramsey', 5, 27, 83),
    (1048583, 'M. Ozil', 8, 30, 87),
    (1048584, 'A. Iwobi', 9, 22, 76),
    (1048585, 'H. Mkhitaryan', 10, 30, 84),
    (1048586, 'A. Lacazette', 12, 27, 86),
    (1048587, 'O. Giroud', 12, 32, 83),
] + [(1048600 + i, 'Player %02d' % i, 5, 21 + i % 12, 70 + i % 15) for i in range(21)]

DESC = (b'ML00000000\x00'
        b'Master League 01ARSENAL / Premier League\r\n'
        b'07/01/2038\r\n'
        b'Premier League\x00')


def _set_bits(b, byte, bit, n, v):
    cur = int.from_bytes(b[byte:byte + 4], 'little')
    mask = ((1 << n) - 1) << bit
    cur = (cur & ~mask) | ((v << bit) & mask)
    b[byte:byte + 4] = cur.to_bytes(4, 'little')


def make_edit_data():
    """PES 2017 EDIT data.dat: 120 B header + 188 B (116+72) player records."""
    d = bytearray(3948120)
    struct.pack_into('<H', d, 0x5C, len(PLAYERS))
    struct.pack_into('<H', d, 0x60, len(CLUBS))
    for i, (pid, name, pos, age, ovr) in enumerate(PLAYERS):
        o = pes17.EDIT_HEADER + i * pes17.EDIT_RECORD
        b = bytearray(pes17.EDIT_ENTRY)
        struct.pack_into('<I', b, 0, pid)
        b[0x0C] = 180 + i % 20
        b[0x0D] = 75 + i % 10
        for nm, by, bi, ln in pes17.ATTR_FIELDS:
            _set_bits(b, by, bi, ln, max(40, min(99, ovr + (i % 7) - 3)))
        _set_bits(b, 0x20, 0, 6, age)
        _set_bits(b, 0x20, 6, 4, pos)
        _set_bits(b, 0x17, 4, 3, 3)
        _set_bits(b, 0x2E, 3, 1, i % 2)
        pp = 0
        for j, code in enumerate(pes17.PP_ORDER):
            if code == pos:
                pp |= 2 << (2 * j)
        _set_bits(b, 0x26, 6, 26, pp)
        nb = name.encode('utf-8')[:45]
        b[0x34:0x34 + len(nb)] = nb
        d[o:o + pes17.EDIT_ENTRY] = b
        # appearance entry: first u32 = player id
        struct.pack_into('<I', d, o + pes17.EDIT_ENTRY, pid)
    return bytes(d)


def make_ml_data():
    """PES 2017 ML data.dat: club table + squads + standings."""
    d = bytearray(9900000)
    for i, name in enumerate(CLUBS):
        o = pes17.TEAM0 + i * pes17.TEAM_STRIDE
        struct.pack_into('<I', d, o, 100 + i)
        nb = name.encode('utf-8')[:63]
        d[o + 4:o + 4 + len(nb)] = nb
        for j in range(pes17.SQUAD_SLOTS):
            struct.pack_into('<II', d, o + pes17.SQUAD_OFF + 8 * j,
                             0x1000 + j, PLAYERS[j % len(PLAYERS)][0])
    # end-of-table marker
    struct.pack_into('<I', d, pes17.TEAM0 + len(CLUBS) * pes17.TEAM_STRIDE, 0xFFFFFFFF)
    # standings: first league holds the 20 clubs in order
    for i, name in enumerate(CLUBS):
        struct.pack_into('<I', d, pes17.STANDINGS0 + 4 * i, 100 + i)
    return bytes(d)


def make_parts(data, desc, name='ML'):
    return {
        'encryptHeader.dat': bytes(range(256)) + bytes(64),
        'header.dat': (name.encode() + b'\0' * 208)[:208],
        'description.dat': desc,
        'logo.png': b'\x89PNG\r\n\x1a\n' + b'\0' * 32,
        'data.dat': data,
        'version.txt': b'1.00\x00\x00',
    }


def make_parts17(data=None, desc=None):
    """Same parts as make_parts() but with the 176 B PES 2017 file header.

    Real t99p17v20 saves proved PES 2017 uses 176 B, not the 208 B PES 2021
    header.  Tests use this so the crypto path is exercised without Windows.
    """
    p = make_parts(data if data is not None else make_ml_data(),
                   desc if desc is not None else DESC)
    p['header.dat'] = p['header.dat'][:176]
    return p


def write_dec(folder, ml=True, marker=True):
    os.makedirs(folder, exist_ok=True)
    data = make_ml_data() if ml else make_edit_data()
    parts = make_parts(data, DESC if ml else b'EDIT00000000\x00',
                       'ML' if ml else 'EDIT')
    for k, v in parts.items():
        with open(os.path.join(folder, k), 'wb') as f:
            f.write(v)
    if marker:
        with open(os.path.join(folder, pes17.KEY_MARK), 'w') as f:
            f.write('pes17')
    return folder


def write_enc(folder, ml=True):
    os.makedirs(folder, exist_ok=True)
    data = make_ml_data() if ml else make_edit_data()
    parts = make_parts(data, DESC if ml else b'EDIT00000000\x00',
                       'ML' if ml else 'EDIT')
    raw = pescrypt.encrypt_parts(parts, pescrypt.KEY_PES17)
    name = 'ML00000000' if ml else 'EDIT00000000'
    with open(os.path.join(folder, name), 'wb') as f:
        f.write(raw)
    return os.path.join(folder, name)
