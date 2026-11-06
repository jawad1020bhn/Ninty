"""pc277: minimalni citac CRI CPK arhiva (PES 2021 / Football Life): popis datoteka i izvlacenje (ukljucujuci CRILAYLA i WESYS/zlib).
Samo citanje; koristi se za bazu natjecanja (Competition.bin) iz SP-ovih cpk datoteka."""
import struct


def _unxor(b):
    out = bytearray(len(b))
    m, t = 0x0000655f, 0x00004115
    for i, c in enumerate(b):
        out[i] = c ^ (m & 0xff)
        m = (m * t) & 0xffffffff
    return bytes(out)


def _utf(packet):
    if packet[:4] != b'@UTF':
        packet = _unxor(packet)
    if packet[:4] != b'@UTF':
        raise ValueError('not a @UTF table')
    size = struct.unpack_from('>I', packet, 4)[0]
    t = packet[8:8 + size]
    rows_off, str_off, data_off, name_off, ncols, rowlen, nrows = struct.unpack_from('>IIIIHHI', t, 0)
    def s(o):
        e = t.index(b'\0', str_off + o)
        return t[str_off + o:e].decode('utf-8', 'replace')
    p = 24
    cols = []
    for _ in range(ncols):
        flag = t[p]; p += 1
        name = s(struct.unpack_from('>I', t, p)[0]); p += 4
        storage, typ = flag & 0xf0, flag & 0x0f
        const = None
        if storage == 0x30:
            const, p = _val(t, p, typ, s, data_off)
        cols.append((name, storage, typ, const))
    rows = []
    for r in range(nrows):
        q = rows_off + r * rowlen
        row = {}
        for name, storage, typ, const in cols:
            if storage == 0x50:
                row[name], q = _val(t, q, typ, s, data_off)
            elif storage == 0x30:
                row[name] = const
            else:
                row[name] = None
        rows.append(row)
    return rows


def _val(t, p, typ, s, data_off):
    fm = {0: '>B', 1: '>b', 2: '>H', 3: '>h', 4: '>I', 5: '>i', 6: '>Q', 7: '>q', 8: '>f'}
    if typ in fm:
        v = struct.unpack_from(fm[typ], t, p)[0]
        return v, p + struct.calcsize(fm[typ])
    if typ == 0xa:
        return s(struct.unpack_from('>I', t, p)[0]), p + 4
    if typ == 0xb:
        o, n = struct.unpack_from('>II', t, p)
        return t[data_off + o:data_off + o + n], p + 8
    raise ValueError('utf type %x' % typ)


def _crilayla(src):
    usize, hsize = struct.unpack_from('<II', src, 8)
    prefix = src[16 + hsize:16 + hsize + 0x100]
    out = bytearray(usize + 0x100)
    body = src[16:16 + hsize]
    pos = [len(body) - 1, 0]   # bajt, bitovi preostali
    cur = [0]

    def bits(n):
        v = 0
        while n:
            if pos[1] == 0:
                cur[0] = body[pos[0]]; pos[0] -= 1; pos[1] = 8
            take = min(n, pos[1])
            v = (v << take) | ((cur[0] >> (pos[1] - take)) & ((1 << take) - 1))
            pos[1] -= take; n -= take
        return v
    w = usize + 0x100 - 1
    end = 0x100
    while w >= end:
        if bits(1):
            off = bits(13) + 3
            ln = 3
            for lv in (2, 3, 5, 8):
                x = bits(lv)
                ln += x
                if x != (1 << lv) - 1:
                    break
            else:
                while True:
                    x = bits(8)
                    ln += x
                    if x != 255:
                        break
            for _ in range(ln):
                out[w] = out[w + off]; w -= 1
        else:
            out[w] = bits(8); w -= 1
    out[:0x100] = prefix
    return bytes(out)


class Cpk:
    """pc283: cita samo zaglavlje i TOC (seek), ne cijelu arhivu, pa radi i na arhivama od nekoliko GB."""
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            head = f.read(0x800)
            if head[:4] != b'CPK ':
                raise ValueError('not a CPK archive')
            hdr = _utf(head[16:16 + struct.unpack_from('<I', head, 8)[0]])[0]
            self.content = hdr.get('ContentOffset') or 0
            toc_off = hdr['TocOffset']
            f.seek(toc_off)
            th = f.read(16)
            if th[:4] != b'TOC ':
                raise ValueError('CPK without TOC')
            n = struct.unpack_from('<I', th, 8)[0]
            toc = f.read(n)
        self.files = {}
        for r in _utf(toc):
            name = ((r.get('DirName') or '') + '/' + r['FileName']).lstrip('/')
            self.files[name] = r
        self.base = min(toc_off, self.content) if self.content else toc_off

    def read(self, name):
        r = self.files[name]
        with open(self.path, 'rb') as f:
            f.seek(self.base + r['FileOffset'])
            raw = f.read(r['FileSize'])
        if raw[:8] == b'CRILAYLA':
            raw = _crilayla(raw)
        return raw
