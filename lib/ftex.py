"""ftex.py - citanje Fox Engine FTEX tekstura (PES 2021 / FL26, npr. dresovi u0194p1.ftex) u RGBA, preko lib/dds.py dekodera."""
import struct
import zlib
import dds

FMT = {0: 'RGBA', 4: 'DXT5', 0xC: 'DXT1', 0xD: 'DXT3', 0xE: 'DXT5', 0xB: 'DXT5'}   # 4 = DXT5 (Sider kit-server, Como 28.10.)


def mip_data(d, level):
    """Nekomprimirani podaci jedne mip razine (0 = najveca)."""
    n = d[0x10]
    level = max(0, min(level, n - 1))
    off, dec, comp, idx, fn, cc = struct.unpack_from('<IIIBBH', d, 0x40 + 16 * level)
    out = bytearray()
    for k in range(cc):
        cs, ds, co = struct.unpack_from('<HHI', d, off + 8 * k)
        co &= 0x7fffffff
        cs = cs or 0x10000
        ds = ds or 0x10000
        raw = d[off + co:off + co + cs]
        out += raw if cs == ds else zlib.decompress(raw)
    return bytes(out), level


def decode(d, level=1):
    """-> (w, h, RGBA bytearray)."""
    if d[:4] != b'FTEX':
        raise ValueError('not FTEX')
    fmt, w, h = struct.unpack_from('<HHH', d, 8)
    data, lv = mip_data(d, level)
    w, h = max(1, w >> lv), max(1, h >> lv)
    f = FMT.get(fmt)
    if f is None:
        raise ValueError('nepoznat format %d' % fmt)
    if f == 'RGBA':
        out = bytearray(w * h * 4)
        for i in range(w * h):
            b, g, r, a = data[i * 4:i * 4 + 4]
            out[i * 4:i * 4 + 4] = bytes((r, g, b, a))
        return w, h, out
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<I', hdr, 4, 124)
    struct.pack_into('<II', hdr, 12, h, w)
    struct.pack_into('<I', hdr, 76, 32)
    struct.pack_into('<I4s', hdr, 80, 4, f.encode())
    return dds.decode(bytes(hdr) + data)
