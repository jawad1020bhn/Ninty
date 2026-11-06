"""Statistika sezone iz ML save-a: zapisi igraca po utakmici (tag,id,golovi/asistencije,ocjena) uz zaglavlje utakmice
(natjecanje = nizi bajt prve rijeci zaglavlja, datum d<<24|m<<16|god). Potvrdeno na 5 kola: poklapa se s ranking ekranima igre."""
import struct

SCAN0, SCAN1 = 1700000, 13600000
REC0, STRIDE = 84, 1680


def _club_range(d):
    try:
        import mlsave
        lim, nat = mlsave.club_layout(d)
        return [k for k in range(lim) if k not in nat] if nat else range(lim)
    except Exception:
        return range(580)


def _pairs(d):
    pairs = {}
    for ci in _club_range(d):
        r = REC0 + ci * STRIDE
        if r + STRIDE > len(d):
            break
        n = d[r + 1058]
        if n > 40:
            continue
        for k in range(n):
            t, i = struct.unpack_from('<II', d, r + 328 + 8 * k)
            if 0 < i < 400000:
                pairs[(t, i)] = ci
    return pairs


def club_name(d, ci):
    r = REC0 + ci * STRIDE
    return bytes(d[r:r + 48]).split(b'\0')[0].decode('utf-8', 'replace')


def compute(d):
    """Parsira sve utakmice (odigrane i buduce) iz save-a.
    Zaglavlje (4 rijeci + 2 rijeci timova): w0 niz bajt = natjecanje; w1 = dan<<24|mjesec<<16|godina; w[j+4] i w[j+5] = domaci/gost (nizih 12 bita = indeks kluba).
    Iza zaglavlja (ako je odigrana): 22 reda igraca, prvih 11 domaci, drugih 11 gost.
    -> dict(matches=[{n,tid,y,m,dd,season,home,away,played,rows:[(pid,club,g,a,rating)]}], cur={pid: sadasnji klub})"""
    if not isinstance(d, bytes):
        d = bytes(d)
    # pc371: isti save (isti sadrzaj) -> isti rezultat; prije se racunalo iznova za svaki zahtjev (~2 s na velikom savu)
    import zlib as _z, sys as _sy
    _mm = _sy.modules.get('mlwrite')
    key = (len(d), getattr(_mm, 'SH2', 0) if _mm else 0, _z.crc32(d), _z.adler32(d))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    r = _compute(d)
    while len(_CACHE) >= 3:
        _CACHE.pop(next(iter(_CACHE)), None)
    _CACHE[key] = r
    return r


_CACHE = {}


def _compute(d):
    pairs = _pairs(d)
    cur_of = {k[1]: ci for k, ci in pairs.items()}
    import sys as _sys
    _m = _sys.modules.get('mlwrite')
    hi = min(SCAN1 + (getattr(_m, 'SH2', 0) if _m else 0), len(d))
    hi -= hi % 4
    base = SCAN0 - SCAN0 % 4
    cnt = (hi - base) // 4
    # pc261: memoryview umjesto tuplea od ~15 M Python intova (60 MB save: ~300 MB privremene memorije po izracunu)
    import sys as _s2
    w = memoryview(d)[base:hi].cast('I') if _s2.byteorder == 'little' else struct.unpack('<%dI' % cnt, d[base:hi])
    n = cnt - 6
    matches = []
    cur = None
    # pc259: broj natjecanja je 10-bitni (tester 60 MB, Report 07: Conference kvalifikacije 259, lige 276/306/315/316...).
    # Na 60 MB (2.400 klubova) ima ~1.500 takvih utakmica i nizi bajt ih mijesa s drugim ligama (276 -> 20 Bundesliga).
    # Klasicni/45 MB: iznad 255 su samo smece-zapisi pa ostaje stari nizi bajt (isto ponasanje kao prije).
    tmask = 0x3ff if len(d) > 50000000 else 0xff
    for j in range(n):
        x1 = w[j + 1]
        if (x1 & 0xffff) >= 0x07e0 and (x1 & 0xffff) <= 0x0800:
            dd = x1 >> 24
            mm = (x1 >> 16) & 0xff
            if 1 <= dd <= 31 and 1 <= mm <= 12:
                y = x1 & 0xffff
                cur = dict(n=len(matches), tid=w[j] & tmask, y=y, m=mm, dd=dd, season=y if mm >= 7 else y - 1,
                           home=w[j + 4] & 0xfff, away=w[j + 5] & 0xfff, played=False, rows=[])
                if j + 7 < cnt:
                    # pc413: rezultat iz zaglavlja utakmice (ukljucuje autogolove; strijelci ih nemaju). +6: b0 domaci, b1 domaci produzeci,
                    # b2 domaci penali, b3 gosti; +7: b0 gosti produzeci, b1 gosti penali (izmjereno na FL26 45/classic saveovima)
                    h6, h7 = w[j + 6], w[j + 7]
                    cur['hs'] = ((h6 & 0xff) + ((h6 >> 8) & 0xff), (h6 >> 24) + (h7 & 0xff))
                    if (h6 >> 16) & 0xff or (h7 >> 8) & 0xff:
                        cur['pens'] = ((h6 >> 16) & 0xff, (h7 >> 8) & 0xff)
                j0 = j
                matches.append(cur)
                continue
        if cur is None:
            continue
        x3 = w[j + 3]
        if (x3 >> 24) == 0:
            b2 = (x3 >> 16) & 0xff
            # pc168: 0x4x = igrac koji je zamijenjen / usao s klupe (samo u utakmicama koje igras ti; AI simulacije imaju 11 na 11).
            # Prije su se preskakali, pa golovi zamjena nisu ulazili u rezultat (Como - Lazio 0:2 prikazan kao 0:0).
            if 0x40 <= b2 <= 0xa0 and 0 < x1 < 400000 and w[j] > 0:
                ci = pairs.get((w[j], x1))
                if ci is None:
                    continue
                off = j - j0 - 8
                si = off // 4 if off >= 0 and off % 4 == 0 else -1
                if b2 < 0x50 and not 0 <= si < 34:
                    continue
                g_, a_ = w[j + 2] & 0xff, (w[j + 2] >> 8) & 0xff
                if b2 < 0x50 and (g_ > 9 or a_ > 9):
                    continue
                rows = cur['rows']
                if ci in (cur['home'], cur['away']):
                    club = ci
                elif 0 <= si < 34:
                    club = cur['home'] if si < 17 else cur['away']   # 17 mjesta po momcadi (11 + klupa)
                else:
                    club = cur['home'] if len(rows) < 11 else cur['away']
                v = (x3 >> 8) & 0x3f
                rating = 0.2 * v + (0.1 if (x3 & 0x80) else 0.0)
                if b2 < 0x50 and v == 0:
                    rating = 6.0   # kratko u igri: igra ne daje ocjenu
                rows.append((x1, club, g_, a_, rating))
                cur['played'] = True
    # pc413: zaglavlje se koristi samo ako se na ovom saveu slaze sa strijelcima (>= 90 % odigranih) - drugi formati ostaju na strijelcima
    pl_ = [m for m in matches if m['played'] and 'hs' in m]
    agree = sum(1 for m in pl_ if m['hs'] == _rows_score(m))
    hdr_ok = bool(pl_) and agree >= 0.9 * len(pl_)
    for m in matches:
        hs = m.pop('hs', None)
        if m['played']:
            rs = _rows_score(m)
            m['sc'] = hs if (hdr_ok and hs and hs[0] >= 0 and hs[1] >= 0 and hs[0] + hs[1] <= 30) else rs
            if m['sc'] != rs:
                m['og'] = True
        if not hdr_ok:
            m.pop('pens', None)
    return dict(matches=matches, cur=cur_of, hdr_ok=hdr_ok)


def _rows_score(m):
    return (sum(r[2] for r in m['rows'] if r[1] == m['home']), sum(r[2] for r in m['rows'] if r[1] != m['home']))


def match_score(m):
    """pc413: (domaci, gosti) - iz zaglavlja utakmice kad je pouzdano (autogolovi!), inace zbroj strijelaca."""
    return m.get('sc') or _rows_score(m)


def match_score_for(m, club):
    """(za, protiv) iz perspektive kluba."""
    h, a = match_score(m)
    return (h, a) if club == m['home'] else (a, h)


def sort_key(m):
    return (m['y'], m['m'], m['dd'], m['n'])


def played_seasons(M):
    return sorted({m['season'] for m in M['matches'] if m['played']})


def agg(M, season, tid=None, club=None, last_ids=None):
    """-> {pid: dict(app,g,a,rs,clubs=[ci po redu])}; club filtrira po klubu U TOJ UTAKMICI."""
    out = {}
    for m in sorted(M['matches'], key=sort_key):
        if not m['played'] or m['season'] != season:
            continue
        if tid is not None and m['tid'] != tid:
            continue
        if last_ids is not None and m['n'] not in last_ids:
            continue
        for pid, ci, g, a, r in m['rows']:
            if club is not None and ci != club:
                continue
            x = out.setdefault(pid, dict(app=0, g=0, a=0, rs=0.0, clubs=[]))
            x['app'] += 1
            x['g'] += g
            x['a'] += a
            x['rs'] += r
            if not x['clubs'] or x['clubs'][-1] != ci:
                x['clubs'].append(ci)
    return out


def score(x):
    n = x['app']
    return round(3 * x['g'] + 2 * x['a'] + 0.5 * n + (1.5 * n * (x['rs'] / n - 6.0) if n else 0), 1)


def last_n(M, season, club, k=5):
    ms = [m for m in sorted(M['matches'], key=sort_key) if m['played'] and m['season'] == season and club in (m['home'], m['away'])]
    return {m['n'] for m in ms[-k:]}
