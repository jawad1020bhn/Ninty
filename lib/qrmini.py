"""pc363: mali QR generator (bajtni nacin, razina ispravka M, verzije 1-6) za adresu appa na mobitelu.
Algoritam prema standardu ISO/IEC 18004 (struktura kao u Nayukijevom qrcodegen). Bez vanjskih paketa; vraca SVG."""

ECC_CW = [-1, 10, 16, 26, 18, 24, 16]      # razina M: kodnih rijeci ispravka po bloku
BLOCKS = [-1, 1, 1, 1, 2, 2, 4]            # razina M: broj blokova


def _mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z & 0xFF


def _rs_divisor(n):
    res = [0] * (n - 1) + [1]
    root = 1
    for _ in range(n):
        for j in range(n):
            res[j] = _mul(res[j], root)
            if j + 1 < n:
                res[j] ^= res[j + 1]
        root = _mul(root, 0x02)
    return res


def _rs_rem(data, div):
    res = [0] * len(div)
    for b in data:
        f = b ^ res.pop(0)
        res.append(0)
        for i, c in enumerate(div):
            res[i] ^= _mul(c, f)
    return res


def _raw_modules(ver):
    r = (16 * ver + 128) * ver + 64
    if ver >= 2:
        na = ver // 7 + 2
        r -= (25 * na - 10) * na - 55
    return r


def _align_pos(ver, size):
    if ver == 1:
        return []
    na = ver // 7 + 2
    step = (ver * 4 + na * 2 + 1) // (na * 2 - 2) * 2
    res = [6]
    pos = size - 7
    for _ in range(na - 1):
        res.insert(1, pos)
        pos -= step
    return res


def matrix(text):
    data = text.encode('utf-8')
    for ver in range(1, 7):
        cap = _raw_modules(ver) // 8 - ECC_CW[ver] * BLOCKS[ver]
        if 4 + 8 + len(data) * 8 <= cap * 8:
            break
    else:
        raise ValueError('text too long for a small QR code')
    size = ver * 4 + 17
    # bitovi podataka
    bits = []
    app = lambda v, n: bits.extend((v >> i) & 1 for i in range(n - 1, -1, -1))
    app(4, 4)
    app(len(data), 8)
    for b in data:
        app(b, 8)
    app(0, min(4, cap * 8 - len(bits)))
    app(0, (-len(bits)) % 8)
    pad = 0xEC
    while len(bits) < cap * 8:
        app(pad, 8)
        pad ^= 0xEC ^ 0x11
    cw = [int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    # ispravak gresaka i preplitanje
    nb, ecl = BLOCKS[ver], ECC_CW[ver]
    raw = _raw_modules(ver) // 8
    nshort = nb - raw % nb
    slen = raw // nb
    div = _rs_divisor(ecl)
    blocks, k = [], 0
    for i in range(nb):
        dat = cw[k:k + slen - ecl + (0 if i < nshort else 1)]
        k += len(dat)
        ecc = _rs_rem(dat, div)
        if i < nshort:
            dat = dat + [0]
        blocks.append(dat + ecc)
    allcw = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != slen - ecl or j >= nshort:
                allcw.append(blk[i])
    # funkcijski uzorci
    M = [[False] * size for _ in range(size)]
    F = [[False] * size for _ in range(size)]

    def fset(x, y, d):
        M[y][x] = d
        F[y][x] = True
    for i in range(size):
        fset(6, i, i % 2 == 0)
        fset(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    dist = max(abs(dx), abs(dy))
                    fset(x, y, dist not in (2, 4))
    ap = _align_pos(ver, size)
    for i, ax in enumerate(ap):
        for j, ay in enumerate(ap):
            if (i == 0 and j == 0) or (i == 0 and j == len(ap) - 1) or (i == len(ap) - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    fset(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def fmt(mask):
        d = (0 << 3) | mask          # razina M = 00
        r = d
        for _ in range(10):
            r = (r << 1) ^ ((r >> 9) * 0x537)
        b = ((d << 10) | r) ^ 0x5412
        bit = lambda i: ((b >> i) & 1) != 0
        for i in range(6):
            fset(8, i, bit(i))
        fset(8, 7, bit(6))
        fset(8, 8, bit(7))
        fset(7, 8, bit(8))
        for i in range(9, 15):
            fset(14 - i, 8, bit(i))
        for i in range(8):
            fset(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            fset(8, size - 15 + i, bit(i))
        fset(8, size - 8, True)
    fmt(0)
    # podaci
    i = 0
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                up = ((right + 1) & 2) == 0
                y = size - 1 - vert if up else vert
                if not F[y][x] and i < len(allcw) * 8:
                    M[y][x] = ((allcw[i >> 3] >> (7 - (i & 7))) & 1) != 0
                    i += 1
        right -= 2
    masks = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
             lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
             lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

    def apply(m):
        for y in range(size):
            for x in range(size):
                if not F[y][x] and masks[m](x, y):
                    M[y][x] = not M[y][x]

    def penalty():
        p = 0
        for line in [M[y] for y in range(size)] + [[M[y][x] for y in range(size)] for x in range(size)]:
            run, prev = 0, None
            for v in line + [None]:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        p += run - 2
                    run, prev = 1, v
        for y in range(size - 1):
            for x in range(size - 1):
                if M[y][x] == M[y][x + 1] == M[y + 1][x] == M[y + 1][x + 1]:
                    p += 3
        dark = sum(sum(r) for r in M)
        p += (abs(dark * 20 - size * size * 10) // (size * size)) * 10
        return p
    best, bm = None, 0
    for m in range(8):
        apply(m)
        fmt(m)
        pv = penalty()
        if best is None or pv < best:
            best, bm = pv, m
        apply(m)
    apply(bm)
    fmt(bm)
    return M


def svg(text, scale=6, border=4, dark='#000', light='#fff'):
    M = matrix(text)
    n = len(M) + border * 2
    path = ''.join('M%d,%dh1v1h-1z' % (x + border, y + border) for y, row in enumerate(M) for x, v in enumerate(row) if v)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" shape-rendering="crispEdges">'
            '<rect width="100%%" height="100%%" fill="%s"/><path d="%s" fill="%s"/></svg>') % (n, n, n * scale, n * scale, light, path, dark)
