"""Usporedba dva dekriptirana savea (prije/poslije necega u igri) po imenovanim tablicama.

Za autora: python lib/savediff.py <mapa_prije> <mapa_poslije> [--rows 40] [--pid 165696]
Ispisuje:
  - zapise igraca (zlib dio) koji su se promijenili, s imenovanim poljima (+44 tag, +136 posudba/prijasnji klub, +140 vlasnik, +152 kraj posudbe ...)
  - promijenjene redove poznatih tablica srednjeg dijela (red dogadjaja, S16, dnevnik dogovora, budzet, klubovi, S8/S10/S11/S15 ...)
  - promijenjene redove tablica u repu (uvjeti ugovora, dogovori, cijene otkupa, lista izvrsenja)
  - nepoznata promijenjena podrucja (adresa + duljina), da se vidi sto jos treba dekodirati
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlwrite  # noqa: E402

PF = {0: 'hdr', 44: 'tag', 48: 'pid', 136: 'loan/prev club', 140: 'owner club', 144: 'contract end', 148: 'joined', 152: 'loan end'}


def _date(c):
    y, m, d = c & 0xffff, (c >> 16) & 0xff, c >> 24
    return '%d.%d.%d' % (d, m, y) if 2000 <= y <= 2070 and 1 <= m <= 12 and 1 <= d <= 31 else None


def _u32s(b):
    out = []
    for i in range(0, len(b) - 3, 4):
        v = struct.unpack_from('<I', b, i)[0]
        dt = _date(v)
        out.append(dt or ('%x' % v))
    return ' '.join(out)


def tables(s):
    """(ime, pocetak, velicina reda, broj redova) za srednji dio savea."""
    T = []
    if s.ext:
        dx = s.dx
        T += [('event queue', mlwrite.X(0x244eb70), 56, 200), ('club responses S16', mlwrite.X(0x2454890) - 16 * 80, 80, 128), ('S16 counter', mlwrite.X(0x2459a94), 4, 1)]
        T += [('S8 squad slots', mlwrite.X(0x2474f94), 44, 200), ('S10 player season', mlwrite.X(0x24bf54c), 368, 120), ('S11 player data', mlwrite.X(0x24e8c84), 192, 140),
              ('S15 player records', mlwrite.X(0x28b886c), 5628, 60)]
    else:
        T += [('event queue', 12464992, 56, 200), ('club responses S16', 12488832 - 16 * 80, 80, 128), ('S16 counter', 12509828, 4, 1), ('messages POOL', 12489744, 80, 60)]
    T += [('deal log D', s.D0 - 30 * 52, 52, 430), ('transfer budget', s.BUDGET, 4, 1)]
    T += [('club records', mlwrite.REC0, mlwrite.STRIDE, 1400)]
    return T


def tail_tables(e2):
    return [('contract terms (tail)', e2 + 16, 48, 120), ('deals (tail)', e2 + mlwrite.Save.META0 - 60 * 60, 60, 120),
            ('buy option prices', e2 + 0x24e10, 12, 30), ('execution list', e2 + mlwrite.Save.SERLIST, 2, 64)]


def ranges(a, b, lo, hi, gap=12):
    out = []
    i = lo
    n = min(hi, len(a), len(b))
    while i < n:
        if a[i] != b[i]:
            j = i
            k = i
            while k < n and (k - j) <= gap:
                if a[k] != b[k]:
                    j = k
                k += 1
            out.append((i, j + 1))
            i = j + 1
        else:
            i += 1
    return out


def fast_ranges(a, b, lo, hi, gap=12):
    """Brzo: prvo po blokovima od 4 KB, pa bajt po bajt samo u promijenjenim blokovima."""
    out = []
    B = 4096
    n = min(hi, len(a), len(b))
    o = lo
    while o < n:
        e = min(n, o + B)
        if a[o:e] != b[o:e]:
            out += ranges(a, b, o, e, gap)
        o = e
    # spoji susjedne
    m = []
    for r in out:
        if m and r[0] - m[-1][1] <= gap:
            m[-1] = (m[-1][0], r[1])
        else:
            m.append(r)
    return m


def label(off, T):
    for name, base, size, n in T:
        if base <= off < base + size * n:
            return name, base, size, (off - base) // size
    return None


def diff(fa, fb, max_rows=40, pid=None, names=None):
    A, Bs = mlwrite.Save(fa), mlwrite.Save(fb)
    a, b = bytes(A.d), bytes(Bs.d)
    L = []
    L.append('A: %s  (%s, %d B, date %s)' % (fa, '45MB' if A.ext else '19.9MB', len(a), _date(A.game_date_code())))
    L.append('B: %s  (%s, %d B, date %s)' % (fb, '45MB' if Bs.ext else '19.9MB', len(b), _date(Bs.game_date_code())))
    if len(a) != len(b):
        L.append('(file sizes differ: normal, the compressed player chunks changed length; the tail is compared relative to its start)')
    # 1) zapisi igraca
    ca, ea = A._chunks()
    cb, eb = Bs._chunks()
    ba, bb = b''.join(ca), b''.join(cb)
    L.append('\n== player records (decompressed) ==')
    n = 0
    for k in range((min(len(ba), len(bb)) - 144) // 156):
        o = 144 + 156 * k
        ra, rb = ba[o:o + 156], bb[o:o + 156]
        if ra == rb:
            continue
        p_ = struct.unpack_from('<I', rb, 48)[0]
        if pid and p_ != pid:
            continue
        ch = []
        for f in range(0, 156, 4):
            va, vb = struct.unpack_from('<I', ra, f)[0], struct.unpack_from('<I', rb, f)[0]
            if va != vb:
                nm = PF.get(f, '+%d' % f)
                ch.append('%s %s->%s' % (nm, _date(va) or '%x' % va, _date(vb) or '%x' % vb))
        n += 1
        if n <= max_rows * 3:
            L.append('  pid %d %s: %s' % (p_, (names or {}).get(p_, ''), '; '.join(ch[:8])))
    if n > max_rows * 3:
        L.append('  ... %d records changed in total' % n)
    if not n:
        L.append('  (none)')
    # 2) srednji dio
    T = tables(A)
    L.append('\n== head / middle (before the compressed chunks) ==')
    rs = fast_ranges(a, b, 0, A.CH0)
    seen, unk, shown = set(), [], 0
    hits = []
    for s0, s1 in rs:
        o = s0
        while o < s1:
            lb = label(o, T)
            if not lb:
                unk.append((o, o + 1))
                o += 1
                continue
            hits.append(lb)
            o = lb[1] + lb[2] * (lb[3] + 1)
    for lb in hits:
        name, base, size, row = lb
        key = (name, row)
        if key in seen:
            continue
        seen.add(key)
        ro = base + size * row
        w = min(size, 96)
        if pid and struct.pack('<I', pid) not in a[ro:ro + size] + b[ro:ro + size] and name != 'S16 counter' and name != 'transfer budget':
            tot_hidden = 1
            continue
        shown += 1
        if shown > max_rows:
            continue
        L.append('  %s row %d @%x' % (name, row - (16 if name.startswith('club responses') else 0), ro))
        L.append('     A: ' + _u32s(a[ro:ro + w]))
        L.append('     B: ' + _u32s(b[ro:ro + w]))
    if shown > max_rows:
        L.append('  ... %d matching rows in total' % shown)
    L.append('  (%d known table rows changed%s)' % (len(seen), ', filtered by pid' if pid else ''))
    # 3) rep
    L.append('\n== tail (after the compressed chunks) ==')
    if ea != eb:
        L.append('  !! tail starts at a different offset (%x vs %x): chunk chain length changed' % (ea, eb))
    ta, tb = a[ea:], b[eb:]
    TT = tail_tables(0)
    rs = fast_ranges(ta, tb, 0, min(len(ta), len(tb)))
    seen = set()
    hits = []
    for s0, s1 in rs:
        o = s0
        while o < s1:
            lb = label(o, TT)
            if not lb:
                unk.append(('tail', o))
                o += 1
                continue
            hits.append(lb)
            o = lb[1] + lb[2] * (lb[3] + 1)
    a_, b_ = a, b
    a, b = ta, tb
    for lb in hits:
        name, base, size, row = lb
        if (name, row) in seen:
            continue
        seen.add((name, row))
        ro = base + size * row
        if pid and size > 4 and struct.pack('<I', pid) not in a[ro:ro + size] + b[ro:ro + size]:
            continue
        if size <= 4:
            L.append('  %s [%d]: %s -> %s' % (name, row, a[ro:ro + size].hex(), b[ro:ro + size].hex()))
        else:
            L.append('  %s row %d @e2+%d' % (name, row, ro))
            L.append('     A: ' + _u32s(a[ro:ro + min(size, 64)]))
            L.append('     B: ' + _u32s(b[ro:ro + min(size, 64)]))
    # 4) nepoznato: zbroj promijenjenih bajtova po podrucju od 64 KB (sto jos nije dekodirano)
    reg = {}
    for u in unk:
        if u[0] == 'tail':
            k_ = 'tail+%x' % (u[1] // 65536 * 65536)
        else:
            k_ = '%x' % (u[0] // 65536 * 65536)
        reg[k_] = reg.get(k_, 0) + 1
    L.append('\n== unknown changed areas (bytes changed per 64 KB block) ==')
    for k_, v in sorted(reg.items(), key=lambda kv: -kv[1])[:max_rows]:
        L.append('  @%s: %d bytes' % (k_, v))
    return '\n'.join(L)


if __name__ == '__main__':
    args = sys.argv[1:]
    mr, pid = 40, None
    if '--rows' in args:
        i = args.index('--rows'); mr = int(args[i + 1]); del args[i:i + 2]
    if '--pid' in args:
        i = args.index('--pid'); pid = int(args[i + 1]); del args[i:i + 2]
    print(diff(args[0], args[1], mr, pid))
