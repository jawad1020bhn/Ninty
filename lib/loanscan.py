"""Provjera tablica za transfere i posudbe (red dogadjaja, S16, dnevnik dogovora, tablica dogovora u repu, lista izvrsenja).

Svaka tablica ima svoj "potpis" (oblik redova), pa se provjerava na ocekivanom mjestu, a ako tamo ne pase,
trazi se u okolici (nova verzija exea moze je pomaknuti). Rezultat ide u provjeru savea i datoteku podrske; save se ne mijenja.
"""
import struct


def _date_ok(c):
    y, m, dd = c & 0xffff, (c >> 16) & 0xff, c >> 24
    return 2020 <= y <= 2060 and 1 <= m <= 12 and 1 <= dd <= 31


def _u(d, o):
    return struct.unpack_from('<I', d, o)[0]


# ---- potpisi: (d, base) -> (pogodak, broj zauzetih redova) ili None
def sig_queue(d, b, rows=40):
    """Red dogadjaja: 56 B, prazan red ima tip 0xff; zauzet red ima tip < 0x100 i datum na +52."""
    used = 0
    for k in range(rows):
        o = b + 56 * k
        t = _u(d, o)
        if t == 0xff:
            if _u(d, o + 52) not in (0xffff, ) and not _date_ok(_u(d, o + 52)):
                return None
            continue
        if t > 0xff or not _date_ok(_u(d, o + 52)):
            return None
        used += 1
    return used if used else None


def sig_s16(d, b, rows=128):
    """Odgovori klubova / poruke: 80 B, tip na +4 (0xff = prazno), zauzet red: datum na +8 i 0xff na +16."""
    used = 0
    for k in range(rows):
        o = b + 80 * k
        t = _u(d, o + 4)
        if t == 0xff:
            continue
        if t > 0xffff or not _date_ok(_u(d, o + 8)):
            return None
        used += 1
    return used if used >= 3 else None


def sig_dlog(d, b, rows=60):
    """Dnevnik dogovora: 52 B; prazan red ima 0xffff na +12; zauzet: pid na +16, vrsta (0..15) na +48."""
    used = 0
    for k in range(rows):
        o = b + 52 * k
        if _u(d, o + 12) == 0xffff:
            continue
        pid = _u(d, o + 16)
        if not (0 < pid < 400000) or _u(d, o + 48) > 15:
            return None
        used += 1
    return used if used else None


def sig_deals(d, b, rows=24):
    """Tablica dogovora u repu: 60 B; zauzet red: serijski (u16), status 1..6, pid na +40."""
    used = 0
    for k in range(rows):
        o = b + 60 * k
        if d[o:o + 2] == b'\xff\xff':
            continue
        st = d[o + 8]
        pid = _u(d, o + 36)
        if not (1 <= st <= 6) or not (0 < pid < 400000) or _u(d, o) & 0xffff > 0x4000:
            return None
        used += 1
    return used if used else None


def _search(d, sig, exp, window, step=4, align=None):
    """Najblizi pogodak potpisa oko ocekivane adrese."""
    best = None
    lo, hi = max(0, exp - window), min(len(d) - 8192, exp + window)
    o = exp
    for delta in range(0, window, step):
        for c in (exp - delta, exp + delta) if delta else (exp,):
            if c < lo or c > hi:
                continue
            r = sig(d, c)
            if r:
                return c, r
    return best


def scan(s):
    """s: mlwrite.Save -> dict(tables=[...], summary)"""
    import mlwrite
    d = bytes(s.d)
    ext = s.ext
    dx = s.dx if ext else 0
    _ch, e2 = s._chunks()
    if ext:
        exp = dict(queue=mlwrite.X(0x244eb70), s16=mlwrite.X(0x2454890) - 16 * 80)
    else:
        exp = dict(queue=12464992, s16=12488832 - 16 * 80)
    exp['dlog'] = s.D0 - 15 * 52
    exp['deals'] = e2 + mlwrite.Save.META0 - 4 * 60
    tabs = (
        ('queue', 'event queue (56 B)', sig_queue, 200000),
        ('s16', 'club responses (80 B)', sig_s16, 200000),
        ('dlog', 'deal log (52 B)', sig_dlog, 200000),
        ('deals', 'deals in the tail (60 B)', sig_deals, 100000),
    )
    out = []
    for name, desc, sig, win in tabs:
        e = exp[name]
        r = sig(d, e) if 0 <= e < len(d) - 8192 else None
        if not r and name == 'dlog' and 0 <= e < len(d) - 8192 and all(_u(d, e + 52 * k + 12) == 0xffff for k in range(60)):
            r = 'empty'   # nova karijera: dnevnik dogovora jos prazan (vanilla PES 2021 / prvi dani)
        row = dict(name=name, desc=desc, expected=e)
        if not r and name in ('deals', 'dlog', 's16'):
            # pocetak ovih tablica se pomice za cijele redove ovisno o broju redaka (app ih ionako trazi po redovima): unutar 12 redaka = na mjestu
            st_ = {'deals': 60, 'dlog': 52, 's16': 80}[name]
            for jj in range(1, 13):
                for c_ in (e - st_ * jj, e + st_ * jj):
                    if 0 <= c_ < len(d) - 8192:
                        r = sig(d, c_)
                        if r:
                            e = c_
                            row['expected'] = c_
                            break
                if r:
                    break
        if r:
            row.update(status='ok', rows=r)
            if name == 'deals':
                exp['deals'] = e
        else:
            f = _search(d, sig, e, win)
            if f:
                row.update(status='moved', found=f[0], moved_by=f[0] - e, rows=f[1])
            else:
                row['status'] = 'not_found'
        out.append(row)
    # lista izvrsenja: svaki zauzet serijski mora postojati u tablici dogovora
    try:
        sers = set()
        db = next(r for r in out if r['name'] == 'deals')
        base = db.get('found', db['expected'])
        for k in range(60):
            o = base + 60 * k
            if d[o:o + 2] != b'\xff\xff':
                sers.add(struct.unpack_from('<H', d, o)[0])
        L = e2 + mlwrite.Save.SERLIST
        vals = [struct.unpack_from('<H', d, L + 2 * i)[0] for i in range(16)]
        used = [v for v in vals if v != 0xffff]
        bad = [v for v in used if v not in sers]
        out.append(dict(name='exec', desc='execution list', expected=L, status='ok' if not bad else 'mismatch', rows=len(used), bad=bad))
    except Exception as ex:
        out.append(dict(name='exec', desc='execution list', status='error', note=str(ex)))
    # brojac S16 (klasicni format): nizi bajt = broj redaka
    if True:
        try:
            k = s._s16_slot()[2]
            out.append(dict(name='s16cnt', desc='club response counter', status='ok', rows=k + 16))
        except Exception as ex:
            out.append(dict(name='s16cnt', desc='club response counter', status='mismatch', note=str(ex)[:120]))
    bad = [r for r in out if r['status'] != 'ok']
    if not bad:
        summ = 'Transfer and loan tables: all %d found where expected.' % len(out)
    else:
        summ = 'Transfer and loan tables: ' + '; '.join(
            '%s %s' % (r['name'], ('moved %+d B' % r['moved_by']) if r['status'] == 'moved' else r['status']) for r in bad) + '.'
    return dict(tables=out, summary=summ)


if __name__ == '__main__':
    import json, os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mlwrite
    for f in sys.argv[1:]:
        r = scan(mlwrite.Save(f))
        print(f, r['summary'])
        print(json.dumps(r['tables'], indent=1))
