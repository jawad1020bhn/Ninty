"""Mali DDS dekoder (DXT1, DXT3, DXT5, nekomprimirani 32-bit) -> PNG, bez vanjskih biblioteka."""
import struct
import zlib


def _c565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def _color_block(b, o, dxt1):
    c0, c1, bits = struct.unpack_from('<HHI', b, o)
    p0, p1 = _c565(c0), _c565(c1)
    if c0 > c1 or not dxt1:
        p2 = tuple((2 * x + y) // 3 for x, y in zip(p0, p1))
        p3 = tuple((x + 2 * y) // 3 for x, y in zip(p0, p1))
        pal = [p0 + (255,), p1 + (255,), p2 + (255,), p3 + (255,)]
    else:
        p2 = tuple((x + y) // 2 for x, y in zip(p0, p1))
        pal = [p0 + (255,), p1 + (255,), p2 + (255,), (0, 0, 0, 0)]
    return [pal[(bits >> (2 * i)) & 3] for i in range(16)]


def _alpha5(b, o):
    a0, a1 = b[o], b[o + 1]
    bits = int.from_bytes(b[o + 2:o + 8], 'little')
    if a0 > a1:
        pal = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    else:
        pal = [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]
    return [pal[(bits >> (3 * i)) & 7] for i in range(16)]


def _alpha3(b, o):
    v = int.from_bytes(b[o:o + 8], 'little')
    return [((v >> (4 * i)) & 15) * 17 for i in range(16)]


def decode(data):
    """-> (w, h, bytearray RGBA) ili None."""
    if data[:4] != b'DDS ':
        return None
    h, w = struct.unpack_from('<II', data, 12)
    pf_flags, fourcc, bits = struct.unpack_from('<I4sI', data, 80)
    rmask, gmask, bmask, amask = struct.unpack_from('<IIII', data, 92)
    off = 128
    if fourcc == b'DX10':
        off += 20
        fmt = struct.unpack_from('<I', data, 128)[0]
        fourcc = {71: b'DXT1', 72: b'DXT1', 74: b'DXT3', 75: b'DXT3', 77: b'DXT5', 78: b'DXT5'}.get(fmt, b'')
        if not fourcc and fmt in (28, 29, 87, 91):
            fourcc, bits = b'', 32
            rmask, gmask, bmask, amask = (0xff, 0xff00, 0xff0000, 0xff000000) if fmt in (28, 29) else (0xff0000, 0xff00, 0xff, 0xff000000)
    out = bytearray(w * h * 4)
    if fourcc in (b'DXT1', b'DXT3', b'DXT5'):
        bs = 8 if fourcc == b'DXT1' else 16
        bw, bh = (w + 3) // 4, (h + 3) // 4
        o = off
        for by in range(bh):
            for bx in range(bw):
                if fourcc == b'DXT1':
                    px = _color_block(data, o, True)
                else:
                    al = _alpha5(data, o) if fourcc == b'DXT5' else _alpha3(data, o)
                    px = [c[:3] + (al[i],) for i, c in enumerate(_color_block(data, o + 8, False))]
                o += bs
                for i in range(16):
                    x, y = bx * 4 + (i & 3), by * 4 + (i >> 2)
                    if x < w and y < h:
                        q = (y * w + x) * 4
                        out[q:q + 4] = bytes(px[i])
        return w, h, out
    if bits == 32:
        def sh(m):
            return (m & -m).bit_length() - 1 if m else 0
        sr, sg, sb, sa = sh(rmask), sh(gmask), sh(bmask), sh(amask)
        o = off
        for i in range(w * h):
            v = struct.unpack_from('<I', data, o + i * 4)[0]
            out[i * 4:i * 4 + 4] = bytes(((v & rmask) >> sr, (v & gmask) >> sg, (v & bmask) >> sb, ((v & amask) >> sa) if amask else 255))
        return w, h, out
    return None


def to_png(w, h, rgba):
    raw = b''.join(b'\x00' + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))
    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b'')


def dds_to_png(data):
    r = decode(data)
    return to_png(*r) if r else None
