"""pc320: sponzor na dresu (Sider kit-server). Mijenja SAMO blokove teksture na prsima, u istom formatu kao original
(BC7 ostaje BC7, DXT5 ostaje DXT5), pa igra dobiva datoteku jednaku originalu osim tog dijela. Bez numpy/PIL (cisti Python).

Tijek: region(): RGBA piksela pravokutnika na prsima (iz .orig ako postoji) -> preglednik obrise stari logo i nacrta novi ->
apply(): enkodira samo blokove pravokutnika i zapise teksturu (original prvo spremi kao .orig, samo jednom)."""
import os
import shutil
import struct
import zlib

import bc7
import ftex

# pc323: dijelovi dresa (2048 px raspored, poravnato na 64 px). Kalibrirano u igri na Man Utd dresu (FL26, 1.11.2026):
# rukav bez znacke lige = desni kraj trake s prugama na ramenima (tekst okrenut 90 stupnjeva), leda = gornji srednji blok
# naopako, sponzor ispod broja oko y 370.
PARTS = {
    'sleeve': dict(rect=(1344, 832, 1600, 1088), inner=(1392, 872, 1544, 1056), center=(1460, 962), box=(150, 95), rot=90),
    'back': dict(rect=(704, 256, 1344, 448), inner=(800, 300, 1248, 432), center=(1022, 370), box=(320, 64), rot=180),
}
# izvlacenje sponzora s tudih dresova: gdje u teksturi stoji sponzor (prsa / rukav bez znacke)
DONOR = {"chest": (832, 1200, 1216, 1472), "sleeve": (1384, 860, 1552, 1088)}

# podrucje sponzora na prsima (PES 2021 raspored teksture, 2048 px): poravnato na 64 px zbog mip razina
REGION = (768, 1152, 1280, 1472)   # x0, y0, x1, y1 (bez izvora zakrpe)
SRC_DY = 192                       # zakrpa tkanine: isti stupci, 192 px nize
FULL = (768, 1152, 1280, 1472 + 192)


def scaled(rect, w):
    k = w / 2048.0
    return tuple(int(round(v * k)) for v in rect)


# ---------------------------------------------------------------- FTEX
def _parse(d):
    if d[:4] != b'FTEX':
        raise ValueError('not an FTEX file')
    fmt, w, h = struct.unpack_from('<HHH', d, 8)
    n = d[0x10]
    mips = []
    for l in range(n):
        off, dec, comp, idx, fn, cc = struct.unpack_from('<IIIBBH', d, 0x40 + 16 * l)
        raw, _ = ftex.mip_data(d, l)
        mips.append(bytearray(raw))
    return fmt, w, h, mips


def _build(d, mips):
    """Nova FTEX datoteka: zaglavlje i tablica mip razina kao u originalu, podaci ponovno u zlib komadima od 16 KB."""
    n = d[0x10]
    hdr = bytearray(d[:0x40 + 16 * n])
    body = bytearray()
    off = len(hdr)
    for l, data in enumerate(mips):
        CH = 16384
        parts = [bytes(data[i:i + CH]) for i in range(0, len(data), CH)]
        table, blob = bytearray(), bytearray()
        base = 8 * len(parts)
        for p in parts:
            c = zlib.compress(p, 9)
            if len(c) >= len(p):
                c = p   # nekomprimirani komad (cs == ds)
            table += struct.pack('<HHI', len(c) & 0xffff, len(p) & 0xffff, base + len(blob))
            blob += c
        mipblob = bytes(table) + bytes(blob)
        _o, _dec, _comp, idx, fn, _cc = struct.unpack_from('<IIIBBH', hdr, 0x40 + 16 * l)
        struct.pack_into('<IIIBBH', hdr, 0x40 + 16 * l, off + len(body), len(data), len(mipblob), idx, fn, len(parts))
        body += mipblob
    return bytes(hdr) + bytes(body)


BPB = {0xB: 16, 0xE: 16, 0x4: 16, 0xC: 8}   # bajtova po bloku 4x4


def _blocks_get(data, w, x0, y0, x1, y1, bpb):
    bw = w // 4
    out = bytearray()
    for by in range(y0 // 4, y1 // 4):
        row = (by * bw + x0 // 4) * bpb
        out += data[row:row + (x1 - x0) // 4 * bpb]
    return bytes(out)


def _blocks_put(data, w, x0, y0, x1, y1, bpb, blocks):
    bw = w // 4
    n = (x1 - x0) // 4 * bpb
    for i, by in enumerate(range(y0 // 4, y1 // 4)):
        row = (by * bw + x0 // 4) * bpb
        data[row:row + n] = blocks[i * n:(i + 1) * n]


def _decode_region(fmt, blocks, rw, rh):
    if fmt == 0xB:
        return bc7.decode(blocks, rw, rh)
    f = ftex.FMT.get(fmt)
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<I', hdr, 4, 124)
    struct.pack_into('<II', hdr, 12, rh, rw)
    struct.pack_into('<I', hdr, 76, 32)
    struct.pack_into('<I4s', hdr, 80, 4, f.encode())
    import dds
    r = dds.decode(bytes(hdr) + blocks)
    # pc382: dds.decode vraca (w, h, rgba); prije se cijeli tuple pretvarao u bytes -> 'bytes must be in range(0, 256)' za
    # sve dresove koji nisu BC7 (DXT1/DXT5, npr. Botafogo SP iz kit-servera)
    return r[2] if isinstance(r, tuple) else r


def region(path, rect=FULL):
    """-> dict(w, h, x0, y0, rw, rh, fmt, rgba) za pravokutnik (iz .orig ako postoji, da se logo ne slaze na logo)."""
    src = path + '.orig' if os.path.isfile(path + '.orig') else path
    d = open(src, 'rb').read()
    fmt, w, h, mips = _parse(d)
    if fmt not in BPB:
        raise ValueError('kit texture format %d is not supported yet' % fmt)
    x0, y0, x1, y1 = scaled(rect, w)
    rw, rh = x1 - x0, y1 - y0
    px = _decode_region(fmt, _blocks_get(mips[0], w, x0, y0, x1, y1, BPB[fmt]), rw, rh)
    return dict(w=w, h=h, x0=x0, y0=y0, rw=rw, rh=rh, fmt=fmt, rgba=bytes(px), mips=len(mips))


# ---------------------------------------------------------------- enkoderi (jedan blok 4x4, RGBA 64 bajta)
def _axis_ends(px):
    mn = [min(px[i + c] for i in range(0, 64, 4)) for c in range(4)]
    mx = [max(px[i + c] for i in range(0, 64, 4)) for c in range(4)]
    ax = [mx[c] - mn[c] for c in range(4)]
    best_lo = best_hi = None
    lo = hi = None
    for i in range(0, 64, 4):
        p = sum(px[i + c] * ax[c] for c in range(4))
        if lo is None or p < lo:
            lo, best_lo = p, i
        if hi is None or p > hi:
            hi, best_hi = p, i
    return list(px[best_lo:best_lo + 4]), list(px[best_hi:best_hi + 4])


W4 = [0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64]


def _q7(v):
    """8-bitna vrijednost -> (7 bita, p bit) za BC7 mode 6 (krajevi s p bitom: 7+1 bit)."""
    best = None
    for p in (0, 1):
        q = max(0, min(127, int(round((v - p) / 2.0))))
        e = abs(((q << 1) | p) - v)
        if best is None or e < best[0]:
            best = (e, q, p)
    return best[1], best[2]


def bc7_mode6(px):
    a, b = _axis_ends(px)
    # zajednicki p bit po kraju: odaberi onaj s manjom ukupnom greskom
    def endpoint(c):
        res = None
        for p in (0, 1):
            q = [max(0, min(127, int(round((c[k] - p) / 2.0)))) for k in range(4)]
            e = sum(abs(((q[k] << 1) | p) - c[k]) for k in range(4))
            if res is None or e < res[0]:
                res = (e, q, p)
        return res[1], res[2]
    q0, p0 = endpoint(a)
    q1, p1 = endpoint(b)
    e0 = [(v << 1) | p0 for v in q0]
    e1 = [(v << 1) | p1 for v in q1]
    pal = [[(e0[k] * (64 - wt) + e1[k] * wt + 32) >> 6 for k in range(4)] for wt in W4]
    idx = []
    for i in range(0, 64, 4):
        c = px[i:i + 4]
        best, bi = None, 0
        for j, q in enumerate(pal):
            e = (q[0] - c[0]) ** 2 + (q[1] - c[1]) ** 2 + (q[2] - c[2]) ** 2 + (q[3] - c[3]) ** 2
            if best is None or e < best:
                best, bi = e, j
        idx.append(bi)
    if idx[0] >= 8:   # sidreni indeks mora imati MSB 0: zamijeni krajeve
        q0, q1, p0, p1 = q1, q0, p1, p0
        idx = [15 - i for i in idx]
    bits, pos = 0, 0
    def put(v, n):
        nonlocal bits, pos
        bits |= (v & ((1 << n) - 1)) << pos
        pos += n
    put(1 << 6, 7)   # mode 6: sest nula pa jedinica
    for k in range(4):
        put(q0[k], 7)
        put(q1[k], 7)
    put(p0, 1)
    put(p1, 1)
    put(idx[0], 3)
    for i in idx[1:]:
        put(i, 4)
    return bits.to_bytes(16, 'little')


def _565(c):
    return ((c[0] * 31 + 127) // 255 << 11) | ((c[1] * 63 + 127) // 255 << 5) | ((c[2] * 31 + 127) // 255)


def _un565(v):
    return [(((v >> 11) & 31) * 255 + 15) // 31, (((v >> 5) & 63) * 255 + 31) // 63, ((v & 31) * 255 + 15) // 31]


def dxt5_block(px):
    al = [px[i + 3] for i in range(0, 64, 4)]
    a0, a1 = max(al), min(al)
    lv = [a0, a1] + [((6 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)]
    ai = [min(range(8), key=lambda j: abs(lv[j] - v)) if a0 != a1 else 0 for v in al]
    abits = 0
    for k, v in enumerate(ai):
        abits |= v << (3 * k)
    a, b = _axis_ends(px)
    e0, e1 = _565(a), _565(b)
    if e0 < e1:
        e0, e1 = e1, e0
    c0, c1 = _un565(e0), _un565(e1)
    pal = [c0, c1, [(2 * c0[k] + c1[k]) // 3 for k in range(3)], [(c0[k] + 2 * c1[k]) // 3 for k in range(3)]]
    cbits = 0
    for k in range(16):
        c = px[4 * k:4 * k + 3]
        j = 0 if e0 == e1 else min(range(4), key=lambda t: sum((pal[t][m] - c[m]) ** 2 for m in range(3)))
        cbits |= j << (2 * k)
    return bytes([a0, a1]) + abits.to_bytes(6, 'little') + struct.pack('<HH', e0, e1) + cbits.to_bytes(4, 'little')


def dxt1_block(px):
    """pc382: DXT1 (8 B po bloku, bez alfe): isti boje kao dxt5_block. Prije je DXT1 tekstura dobivala 16-bajtne DXT5 blokove."""
    b = dxt5_block(px)
    e0, e1 = struct.unpack_from('<HH', b, 8)
    if e0 == e1:
        return b[8:16]
    return b[8:16]   # e0 > e1 (dxt5_block ih vec poreda) -> 4-bojni nacin, isti indeksi


def _encode_region(fmt, rgba, rw, rh, ref=None, ref_blocks=None):
    """pc338: ref = pikseli originala istog pravokutnika; blok koji se nije promijenio zadrzava ORIGINALNI komprimirani blok
    (prije se cijeli pravokutnik ponovno komprimirao jednostavnijim BC7 nacinom, pa se uzorak dresa oko loga vidljivo zamutio)."""
    enc = bc7_mode6 if fmt == 0xB else dxt1_block if BPB.get(fmt) == 8 else dxt5_block
    bpb = BPB[fmt]
    out = bytearray()
    k = 0
    for by in range(rh // 4):
        for bx in range(rw // 4):
            px = bytearray(64)
            same = ref is not None
            for yy in range(4):
                o = ((by * 4 + yy) * rw + bx * 4) * 4
                px[yy * 16:yy * 16 + 16] = rgba[o:o + 16]
                if same and bytes(rgba[o:o + 16]) != bytes(ref[o:o + 16]):
                    same = False
            if same and ref_blocks is not None:
                out += ref_blocks[k * bpb:(k + 1) * bpb]
            else:
                out += enc(px)
            k += 1
    return bytes(out)


def _down(rgba, rw, rh):
    w2, h2 = rw // 2, rh // 2
    out = bytearray(w2 * h2 * 4)
    for y in range(h2):
        for x in range(w2):
            for c in range(4):
                s = 0
                for dy in (0, 1):
                    for dx in (0, 1):
                        s += rgba[((2 * y + dy) * rw + 2 * x + dx) * 4 + c]
                out[(y * w2 + x) * 4 + c] = (s + 2) >> 2
    return bytes(out), w2, h2


def apply(path, rgba, rect=REGION):
    """rgba = novi pikseli pravokutnika rect (bez dijela za zakrpu). Original -> path.orig (jednom). Vraca velicinu nove datoteke.
    pc323: osnova je TRENUTNA tekstura (prsa, rukav i leda se upisuju zasebno i ne smiju brisati jedno drugo); citanje
    pravokutnika (region) i dalje ide iz .orig, pa se isti dio uvijek crta na cisti original."""
    if not os.path.isfile(path + '.orig'):
        shutil.copy2(path, path + '.orig')
    d = open(path, 'rb').read()
    fmt, w, h, mips = _parse(d)
    x0, y0, x1, y1 = scaled(rect, w)
    rw, rh = x1 - x0, y1 - y0
    if len(rgba) != rw * rh * 4:
        raise ValueError('wrong region size')
    try:
        fo, wo, ho, omips = _parse(open(path + '.orig', 'rb').read())
        if (fo, wo, ho, len(omips)) != (fmt, w, h, len(mips)):
            omips = None
    except Exception:
        omips = None
    cur, cw, ch = rgba, rw, rh
    ref = None
    for l in range(len(mips)):
        lw = max(4, w >> l)
        lx0, ly0 = x0 >> l, y0 >> l
        if cw < 4 or ch < 4 or lx0 % 4 or ly0 % 4:
            break
        rb = None
        if omips is not None:
            rb = _blocks_get(omips[l], lw, lx0, ly0, lx0 + cw, ly0 + ch, BPB[fmt])
            if l == 0:
                try:
                    ref = bytes(_decode_region(fmt, rb, cw, ch))
                except Exception:
                    ref = None
        _blocks_put(mips[l], lw, lx0, ly0, lx0 + cw, ly0 + ch, BPB[fmt], _encode_region(fmt, cur, cw, ch, ref if ref is not None else None, rb if ref is not None else None))
        cur, cw, ch = _down(cur, cw, ch)
        ref = _down(ref, cw * 2, ch * 2)[0] if ref is not None else None
    out = _build(d, mips)
    tmp = path + '.tmp'
    open(tmp, 'wb').write(out)
    os.replace(tmp, path)
    return len(out)


def restore(path):
    if os.path.isfile(path + '.orig'):
        os.replace(path + '.orig', path)
        return True
    return False


# ---------------------------------------------------------------- pc323: sponzor s tudeg dresa (bez numpy/PIL)
def _kmeans(pts, k=5, it=10):
    if not pts:
        return []
    step = max(1, len(pts) // k)
    c = [list(pts[i * step]) for i in range(k)]
    for _ in range(it):
        acc = [[0, 0, 0, 0] for _ in c]
        for p in pts:
            bi, bd = 0, None
            for j, q in enumerate(c):
                d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2
                if bd is None or d < bd:
                    bi, bd = j, d
            a = acc[bi]
            a[0] += p[0]; a[1] += p[1]; a[2] += p[2]; a[3] += 1
        c = [[a[0] / a[3], a[1] / a[3], a[2] / a[3], a[3]] if a[3] else c[j] + [0] for j, a in enumerate(acc)]
        c = [x[:3] + [x[3] if len(x) > 3 else 0] for x in c]
        cnt = [x[3] for x in c]
        c = [x[:3] for x in c]
    return [q for q, n in zip(c, cnt) if n >= len(pts) * 0.07]   # pc334: rijetka boja na rubu = logo koji dotice rub, ne pozadina


def logo(path, part, lo=22, hi=60):
    """Sponzor s glavnog dresa drugog kluba: pozadina = boje ruba pravokutnika (k-means), logo = sve sto se od njih razlikuje,
    bez sitnih mrlja. -> dict(w, h, rgba, cover) ili None (nema loga / previse uzorka na dresu)."""
    r = region(path, DONOR[part])
    W, H, px = r['rw'], r['rh'], r['rgba']
    B = max(3, W // 64)
    pts = []
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            if y < B or y >= H - B or x < B or x >= W - B:
                o = (y * W + x) * 4
                pts.append((px[o], px[o + 1], px[o + 2]))
    C = _kmeans(pts)
    if not C:
        return None
    al = bytearray(W * H)
    span = float(hi - lo)
    for i in range(W * H):
        o = i * 4
        r_, g_, b_ = px[o], px[o + 1], px[o + 2]
        d = min((r_ - q[0]) ** 2 + (g_ - q[1]) ** 2 + (b_ - q[2]) ** 2 for q in C) ** 0.5
        if d > lo:
            al[i] = 255 if d >= hi else int((d - lo) / span * 255)
    # komponente na mrezi 4x4 (jedna celija razmaka spaja slova istog loga)
    G = 4
    gw, gh = (W + G - 1) // G, (H + G - 1) // G
    cnt = [0] * (gw * gh)
    for y in range(H):
        for x in range(W):
            if al[y * W + x] > 127:
                cnt[(y // G) * gw + x // G] += 1
    lab = [0] * (gw * gh)
    sizes = [0]
    cents = [(0, 0)]
    boxes = [(0, 0)]
    for c0 in range(gw * gh):
        if not cnt[c0] or lab[c0]:
            continue
        n = len(sizes)
        lab[c0] = n
        st, tot = [c0], 0
        sy = sx = sw = 0
        by0 = bx0 = 10 ** 9
        by1 = bx1 = -1
        while st:
            c1 = st.pop()
            tot += cnt[c1]
            cy, cx = divmod(c1, gw)
            sy += cy * cnt[c1]
            sx += cx * cnt[c1]
            sw += cnt[c1]
            by0, by1, bx0, bx1 = min(by0, cy), max(by1, cy), min(bx0, cx), max(bx1, cx)
            for dy in (-2, -1, 0, 1, 2):
                for dx in (-2, -1, 0, 1, 2):
                    yy, xx = cy + dy, cx + dx
                    if 0 <= yy < gh and 0 <= xx < gw:
                        c2 = yy * gw + xx
                        if cnt[c2] and not lab[c2]:
                            lab[c2] = n
                            st.append(c2)
        sizes.append(tot)
        cents.append((sy / float(sw or 1) / gh, sx / float(sw or 1) / gw))
        boxes.append((by1 - by0 + 1, bx1 - bx0 + 1))
    if len(sizes) < 2:
        return None
    # pc328: tanke duge crte (rub rukava, pruge) nisu logo
    for i in range(1, len(sizes)):
        hc, wc = boxes[i]
        if (hc <= 3 and wc >= 8 and wc >= 4 * hc) or (wc <= 3 and hc >= 8 and hc >= 4 * wc) or \
                (part == 'sleeve' and max(hc, wc) >= 4 * min(hc, wc) and max(hc, wc) >= 10):
            sizes[i] = 0
    # pc325: na prsima grb kluba i znak proizvodaca stoje gore i uz rub: to nije sponzor
    if part == 'chest':
        for i in range(1, len(sizes)):
            cy_, cx_ = cents[i]
            if cy_ < 0.2 or cx_ < 0.08 or cx_ > 0.92:
                sizes[i] = 0
    mx = max(sizes)
    if not mx:
        return None
    keep = {i for i, t in enumerate(sizes) if i and t >= max(80, mx * 0.05)}
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for y in range(H):
        for x in range(W):
            i = y * W + x
            if al[i] and lab[(y // G) * gw + x // G] not in keep:
                al[i] = 0
            elif al[i] > 76:
                x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
    if x1 < 0:
        return None
    _fill_hollow(px, al, W, H, x0, y0, x1, y1)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    if w < W * 0.12 or h < H * 0.12:
        return None
    on = sum(1 for i in range(W * H) if al[i] > 127)
    cover = on / float(w * h)
    out = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            i = (y + y0) * W + x + x0
            o = (y * w + x) * 4
            out[o:o + 3] = px[i * 4:i * 4 + 3]
            out[o + 3] = al[i]
    # kad je logo cijela ploha (npr. zuta zakrpa), vrati i nju; kad je skoro sav pravokutnik "logo" a nije ploha, to je uzorak dresa
    noisy = w > W * 0.92 and h > H * 0.92 and cover < 0.6
    return None if noisy else dict(w=w, h=h, rgba=bytes(out), cover=round(cover, 3), size=(W, H), box=(x0, y0, x1 + 1, y1 + 1), scale=r['w'] / 2048.0)


def restore_part(path, part):
    """pc328: vrati samo jedan dio dresa (prsa / rukav / leda) iz .orig, ostalo ostaje kako je."""
    if not os.path.isfile(path + '.orig') or not os.path.isfile(path):
        return False
    rect = PARTS[part]['rect'] if part in PARTS else REGION
    o = open(path + '.orig', 'rb').read()
    d = open(path, 'rb').read()
    fo, w, h, mo = _parse(o)
    fc, wc, hc, mc = _parse(d)
    if (fo, w, h, len(mo)) != (fc, wc, hc, len(mc)):
        return False
    x0, y0, x1, y1 = scaled(rect, w)
    for l in range(len(mo)):
        lw = max(4, w >> l)
        lx0, ly0, lx1, ly1 = x0 >> l, y0 >> l, x1 >> l, y1 >> l
        if lx1 - lx0 < 4 or ly1 - ly0 < 4 or lx0 % 4 or ly0 % 4 or lx1 % 4 or ly1 % 4:
            break
        _blocks_put(mc[l], lw, lx0, ly0, lx1, ly1, BPB[fo], _blocks_get(mo[l], lw, lx0, ly0, lx1, ly1, BPB[fo]))
    out = _build(d, mc)
    tmp = path + '.tmp'
    open(tmp, 'wb').write(out)
    os.replace(tmp, path)
    return True


def old_logo_box(path, part):
    """pc333: gdje je stari sponzor na mom dresu (u koordinatama 2048 teksture) ili None. Brise se samo taj pravokutnik,
    ne cijelo podrucje (prije su se na dresovima s uzorkom, npr. Liverpool, krpale i crte uzorka oko loga)."""
    src = path + '.orig' if os.path.isfile(path + '.orig') else path
    try:
        L = logo(src, 'sleeve' if part == 'sleeve' else 'chest')
    except Exception:
        return None
    if not L:
        return None
    k = L['scale'] or 1.0
    dx, dy = DONOR['sleeve' if part == 'sleeve' else 'chest'][:2]
    x0, y0, x1, y1 = L['box']
    return (dx + x0 / k, dy + y0 / k, dx + x1 / k, dy + y1 / k)


def _fill_hollow(px, al, W, H, x0, y0, x1, y1):
    """pc334: "supalj" logo: slova iste boje kao neki dio dresa (npr. crveni deel na bijelom rukavu kad je i tijelo crveno)
    ostanu samo kao obrub. Zatvorene rupe unutar loga cija se boja razlikuje od pozadine oko loga popune se (prave rupe,
    npr. u "9" ili "o", su boje pozadine i ostaju prazne)."""
    from collections import deque
    low = lambda i: al[i] < 100
    out = bytearray(W * H)
    q = deque()
    for x in range(W):
        for y in (0, H - 1):
            i = y * W + x
            if low(i) and not out[i]:
                out[i] = 1
                q.append(i)
    for y in range(H):
        for x in (0, W - 1):
            i = y * W + x
            if low(i) and not out[i]:
                out[i] = 1
                q.append(i)
    while q:
        i = q.popleft()
        y, x = divmod(i, W)
        for j in ((i - 1) if x else -1, (i + 1) if x < W - 1 else -1, (i - W) if y else -1, (i + W) if y < H - 1 else -1):
            if j >= 0 and not out[j] and low(j):
                out[j] = 1
                q.append(j)
    # boja pozadine tik uz logo (prsten oko okvira)
    ring = []
    for y in range(max(0, y0 - 6), min(H, y1 + 7), 2):
        for x in range(max(0, x0 - 6), min(W, x1 + 7), 2):
            i = y * W + x
            if out[i] and (x < x0 or x > x1 or y < y0 or y > y1):
                ring.append(px[i * 4:i * 4 + 3])
    if not ring:
        return
    bg = [sorted(c[k] for c in ring)[len(ring) // 2] for k in range(3)]
    seen = bytearray(W * H)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            i0 = y * W + x
            if not low(i0) or out[i0] or seen[i0]:
                continue
            comp, q2 = [], deque([i0])
            seen[i0] = 1
            while q2:
                i = q2.popleft()
                comp.append(i)
                yy, xx = divmod(i, W)
                for j in ((i - 1) if xx else -1, (i + 1) if xx < W - 1 else -1, (i - W) if yy else -1, (i + W) if yy < H - 1 else -1):
                    if j >= 0 and not seen[j] and low(j) and not out[j]:
                        seen[j] = 1
                        q2.append(j)
            if len(comp) < 12:
                continue
            cs = sorted(comp, key=lambda i: px[i * 4] + px[i * 4 + 1] + px[i * 4 + 2])
            mid = cs[len(cs) // 2]
            hc = px[mid * 4:mid * 4 + 3]
            if abs(hc[0] - bg[0]) + abs(hc[1] - bg[1]) + abs(hc[2] - bg[2]) > 70:
                for i in comp:
                    al[i] = 255
