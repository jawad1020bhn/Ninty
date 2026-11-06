#!/usr/bin/env python3
"""mlwrite.py - cita i pise formacije i sastav za TVOJ klub u dekriptiranom ML save-u (FL26 v1.3).

Izmjereno (v1.3, potvrdeno u igri na Hull karijeri):
  blok korisnickog kluba: F0 = 1675944 (isti u svim testiranim save-ovima)
    F0-56        ime menadzera (kluba)
    F0 + 33*k    k=0 kick-off, k=1 u posjedu, k=2 bez posjeda; svaka 33 B:
                 11 kodova pozicija, pa 11 parova (x dubina, y sirina 5=lijevo..99=desno)
    F0 + 480     niz od 35 indeksa u sastav kluba: [0..10] prvih 11 (redom kao pozicije),
                 [11..22] klupa, ostalo pricuva
  sastav kluba: zapis kluba (korak 1680 od offseta 84), +332 parovi (u32 id igraca, u32 oznaka)
Piše SAMO u kopiju koju mu das; originalni save ne dira.
"""
import struct
import zlib, argparse, json, os, struct, sys

F0_BASE = 1675944
F0 = F0_BASE
TAC_BASE = 1260140
SH2 = 0
SH2A = 0      # pc187: pomak prednjeg dijela srednjeg bloka (red dogadjaja, S16, L5, L4...) kad se razlikuje od straznjeg
DXA = 0
DX = 0        # pomak srednjeg dijela u odnosu na referentni prosireni (45 MB) save; nova verzija exea = drugi DX
SHIFT = 0     # pomak rasporeda u prosirenom (fl26caps) save-u: 850 klubova vise * 1680 B
NAME_OFF = -56
LINEUP_OFF = 480
BETA_FLAG = lambda k: False   # pc247: server postavlja citanje beta prekidaca iz config.json
FORM_SZ = 33
REC0, STRIDE, SQUAD_OFF = 84, 1680, 332

POS = dict(GK=0, CB=1, LB=2, RB=3, DMF=4, CMF=5, LMF=6, RMF=7, AMF=8, LWF=9, RWF=10, SS=11, CF=12)
RPOS = {v: k for k, v in POS.items()}

# (pozicija, x dubina, y sirina)  - y: 5 lijevo .. 99 desno
def _f(*rows):
    return [(POS[p], x, y) for p, x, y in rows]

PRESETS = {
 '4-3-3': _f(('GK',3,52),('RB',12,89),('CB',10,63),('CB',10,41),('LB',12,15),('DMF',20,52),('CMF',26,67),('CMF',26,37),('RWF',40,88),('CF',43,52),('LWF',40,16)),
 '4-4-2': _f(('GK',3,52),('RB',12,89),('CB',10,63),('CB',10,41),('LB',12,15),('RMF',27,88),('CMF',24,62),('CMF',24,42),('LMF',27,16),('CF',42,62),('CF',42,42)),
 '4-2-3-1': _f(('GK',3,52),('RB',12,89),('CB',10,63),('CB',10,41),('LB',12,15),('DMF',20,63),('DMF',20,41),('RMF',33,86),('AMF',32,52),('LMF',33,18),('CF',43,52)),
 '4-1-4-1': _f(('GK',3,52),('RB',12,89),('CB',10,63),('CB',10,41),('LB',12,15),('DMF',18,52),('RMF',29,88),('CMF',27,62),('CMF',27,42),('LMF',29,16),('CF',43,52)),
 '4-3-2-1': _f(('GK',3,52),('RB',12,89),('CB',10,63),('CB',10,41),('LB',12,15),('CMF',22,52),('CMF',24,70),('CMF',24,34),('AMF',34,64),('AMF',34,40),('CF',43,52)),
 '3-5-2': _f(('GK',3,52),('CB',10,68),('CB',9,52),('CB',10,36),('RMF',26,90),('DMF',20,52),('CMF',26,64),('CMF',26,40),('LMF',26,14),('CF',42,62),('CF',42,42)),
 '3-4-3': _f(('GK',3,52),('CB',10,68),('CB',9,52),('CB',10,36),('RMF',25,88),('CMF',24,62),('CMF',24,42),('LMF',25,16),('RWF',40,86),('CF',43,52),('LWF',40,18)),
 '5-3-2': _f(('GK',3,52),('RB',16,92),('CB',10,68),('CB',9,52),('CB',10,36),('LB',16,12),('CMF',24,66),('CMF',23,52),('CMF',24,38),('CF',42,62),('CF',42,42)),
}


# --- automatsko slaganje po pozicijama ---
def _dist():
    n = 13
    INF = 99
    D = [[INF] * n for _ in range(n)]
    for i in range(n):
        D[i][i] = 0
    E = [('CB','LB',2),('CB','RB',2),('LB','RB',3),('CB','DMF',3),('LB','LMF',2),('RB','RMF',2),
         ('DMF','CMF',1),('CMF','AMF',1),('CMF','LMF',2),('CMF','RMF',2),('LMF','RMF',3),
         ('LMF','LWF',1),('RMF','RWF',1),('AMF','SS',1),('AMF','LWF',2),('AMF','RWF',2),
         ('SS','CF',1),('CF','LWF',2),('CF','RWF',2),('LWF','RWF',3),('DMF','LB',4),('DMF','RB',4)]
    for a, b, w in E:
        D[POS[a]][POS[b]] = D[POS[b]][POS[a]] = w
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if D[i][k] + D[k][j] < D[i][j]:
                    D[i][j] = D[i][k] + D[k][j]
    for i in range(1, n):
        D[0][i] = D[i][0] = 60   # golman samo na gol
    return D
DIST = _dist()


def hungarian(cost):
    """min-cost assignment, cost: n x m (n<=m). Vraca listu stupaca po retku."""
    n, m = len(cost), len(cost[0])
    INF = float('inf')
    u = [0] * (n + 1); v = [0] * (m + 1); p = [0] * (m + 1); way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i; j0 = 0
        minv = [INF] * (m + 1); used = [False] * (m + 1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = INF; j1 = 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur; way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]; j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta; v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0:
                break
    res = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            res[p[j] - 1] = j - 1
    return res


def plan_label(roles):
    """Oznaka formacije kao u igri (npr. 4-2-1-3, 4-2-3-1, 4-4-2) iz kodova uloga:
    1 CB, 2 LB, 3 RB, 4 DMF, 5 CMF, 6 LMF, 7 RMF, 8 AMF, 9 LWF, 10 RWF, 11 SS, 12 CF."""
    c = lambda *rs: sum(1 for r in roles if r in rs)
    df, dm, cm, wm, am, ss, fw = c(1, 2, 3), c(4), c(5), c(6, 7), c(8), c(11), c(9, 10, 12)
    parts = [df]
    if am:
        parts += [dm + cm, am + wm]
    elif dm == 1 and cm + wm == 4:
        parts += [1, 4]
    else:
        parts += [dm + cm + wm]
    parts += [ss, fw]
    return '-'.join(str(x) for x in parts if x)



# ---------------------------------------------------------------- raspored savea (verzije exea)
EXT_SH, EXT_SH2 = 1428000, 25619760          # referentni prosireni (fl26caps, 45 MB) save
EXT_CH0 = 18088904 + EXT_SH2                 # pocetak niza zlib dijelova u referentnom saveu
# staticni dijelovi savea (isti u svim karijerama i bazama), jedinstveni u datoteci: (adresa u referentnom saveu, potpis)
LAYOUT_ANCHORS = (
    (37540896, 'ffff0300ffff03001517000092090000551700008a0700009309000094090000131400000c1000008b070000ca090000'),
    (38203713, '000000ab013101290200002a032a0300000000164227022a0200002903290300000000040183052b0200002903290300'),
    (38203896, '340200002603260300000000d5c02500350200002603260300000000af41f001360200002503250300000000ac413105'),
    (38927432, 'ffffffffffffffff0200000002000000e90700003400000035000000360000003700000038000000390000003a000000'),
)
_LAYOUT_CACHE = {}


def _chain_ok(d, p, need=3):
    try:
        for _ in range(need):
            raw, cl, cum = struct.unpack('>III', bytes(d[p:p + 12]))
            if raw == 0 or raw > 0x40000 or cl == 0 or cl > 0x40000 or d[p + 12] != 0x78:
                return False
            p += 12 + cl
        return True
    except Exception:
        return False


BOUND_X = 0x2470000                # granica prednjeg/straznjeg dijela (referentni 45 MB save); izmedju je blok nula koji raste
BOUND_C = BOUND_X - EXT_SH2         # ista granica u koordinatama klasicnog (19,9 MB) savea
TAIL_LEN = 476556                   # rep iza niza zlib dijelova: isti u 45 MB i 60 MB saveu
ZB_END, ZB_LEN = 0x24703e4, 1596    # kraj bloka nula iza tablice rangova (750 x 16 B) i njegova duljina u referentnom saveu


def X(a):
    """Adresa iz referentnog 45 MB savea -> adresa u ovom saveu (prednji dio DXA, straznji DX)."""
    return a + (DXA if a < BOUND_X else DX)


def Y(n):
    """Adresa iz klasicnog (19,9 MB) savea -> adresa u ovom saveu (prednji dio SH2A, straznji SH2)."""
    return n + (SH2A if n < BOUND_C else SH2)


def _chain_len(d, p):
    n = 0
    try:
        while p + 13 <= len(d):
            raw, cl, cum = struct.unpack('>III', bytes(d[p:p + 12]))
            if raw == 0 or raw > 0x40000 or cl == 0 or cl > 0x40000 or d[p + 12] != 0x78:
                break
            p += 12 + cl
            n += 1
    except Exception:
        pass
    return n, p


def find_chain(d):
    """Pronadji niz zlib dijelova po strukturi (ne po sadrzaju): niz koji zavrsava tocno TAIL_LEN B prije kraja datoteke.
    -> pocetak ili None. Radi za svaki format/verziju exea koja doda klubove ili tablice."""
    import re as _re
    mv = bytes(d)
    best = None
    lo = max(0, EXT_CH0 - 2000000) if len(mv) > EXT_CH0 else 0
    for m in _re.compile(rb'\x00[\x00-\x04][\x00-\xff]{2}\x00[\x00-\x04][\x00-\xff]{6}\x78[\x01\x5e\x9c\xda]', _re.S).finditer(mv, lo):
        p = m.start()
        n, e = _chain_len(mv, p)
        if n < 4:
            continue
        if e == len(mv) - TAIL_LEN:
            return p
        if best is None or n > best[0]:
            best = (n, p)
    return best[1] if best and best[0] >= 8 else None


def front_dx(d, dx):
    """Prednji pomak: blok nula prije ZB_END (straznje koordinate) je u novom formatu veci (60 MB: +12.800 B).
    -> (dxa, ok). Provjera: struktura reda dogadjaja (u32 na +36 svakog retka = ffffffff)."""
    e = ZB_END + dx
    if e > len(d) or e < 4:
        return dx, False
    z = e
    while z > 0 and d[z - 1] == 0 and e - z < 400000:
        z -= 1
    zl = e - z
    if zl < ZB_LEN:
        return dx, False
    dxa = dx - 16 * ((zl - ZB_LEN) // 16)
    def good(a):
        # red dogadjaja (200 x 56 B): u svakom retku (praznom i punom) je u32 na +36 = ffffffff (pc189; S16 red 0 nije
        # pouzdan jer je S16 kruzni i red 0 moze biti zauzet, npr. PAOK 1.7.2027)
        try:
            q = 0x244eb70 + a
            return sum(struct.unpack_from('<I', d, q + 56 * k + 36)[0] == 0xffffffff for k in range(200)) >= 150
        except Exception:
            return False
    return dxa, good(dxa)


def layout_probe(d, sh, path=None):
    """Prosireni save: koliko je srednji dio pomaknut u odnosu na referentni (nova verzija exea koja doda klubove ili tablice).
    -> (dx, ok, napomena, dxa). ok=True samo kad su sva sidra na istom pomaku i niz zlib dijelova je na ocekivanom mjestu.
    dxa = pomak prednjeg dijela (do BOUND_X); jednak dx osim u formatima gdje izmedju naraste blok (60 MB tester)."""
    if not sh:
        return 0, True, '', 0
    key = None
    try:
        if path:
            st = os.stat(path)
            key = (path, st.st_mtime, st.st_size)
            if key in _LAYOUT_CACHE:
                return _LAYOUT_CACHE[key]
    except Exception:
        key = None
    mv = bytes(d)
    deltas = []
    for ref, hx in LAYOUT_ANCHORS:
        sig = bytes.fromhex(hx)
        if mv[ref:ref + len(sig)] == sig:
            deltas.append(0)
            continue
        p = mv.find(sig)
        if p >= 0 and mv.find(sig, p + 1) < 0:
            deltas.append(p - ref)
        else:
            deltas.append(None)
    found = [x for x in deltas if x is not None]
    dx = max(set(found), key=found.count) if found else 0
    same = bool(found) and all(x == dx for x in found) and len(found) == len(deltas)
    chain = bool(found) and _chain_ok(d, EXT_CH0 + dx)
    if same and chain:
        res = (dx, True, '' if dx == 0 else 'new save version: tables moved by %+d B (adapted automatically)' % dx, dx)
    else:
        # sidra (podaci karijere) ne pomognu: nadji niz zlib dijelova po strukturi, pa prednji dio po bloku nula
        p = find_chain(mv)
        if p is not None:
            dxb = p - EXT_CH0
            dxa, fok = front_dx(mv, dxb)
            if not fok:
                dxa = dxb
            note = 'new save layout (%.0f MB): reads adapted (%s); buying/selling players, contract renewals, youth signings and transfer/loan lists work (beta), other writing is locked until verified' % (
                len(mv) / 1e6, ('front %+d B, back %+d B' % (dxa, dxb)) if dxa != dxb else ('tables moved by %+d B' % dxb))
            res = (dxb, False, note, dxa)
        else:
            why = []
            if not found:
                why.append('no reference tables found')
            elif not same:
                why.append('tables moved by different amounts %s' % deltas)
            if not chain:
                why.append('compressed block not where expected')
            res = (dx, False, 'unknown layout: ' + '; '.join(why), dx)
    if sh % 1680 and res[1]:
        # blok kluba pomaknut za iznos koji nije visekratnik zapisa kluba: tablica klubova se promijenila, pisanje nije sigurno
        res = (res[0], False, 'unknown layout: club records changed (offset %d B)' % sh, res[3])
    if key:
        _LAYOUT_CACHE[key] = res
    return res


class SaveFormatError(ValueError):
    """Save se ne moze procitati (druga verzija igre ili neocekivan sadrzaj)."""


class Save:
    _RO_CACHE = {}

    def __new__(cls, *args, **kwargs):
        # PES 2017 compatibility: every mlwrite.Save(...) call on a PES 2017
        # save transparently returns the read-only adapter.  Python skips
        # __init__ when __new__ returns an object that is not an instance of
        # cls, so no FL26 layout code ever runs on a PES 2017 save.
        try:
            folder = args[0] if args else kwargs.get('folder')
            ro = kwargs.get('ro', args[1] if len(args) > 1 else False)
            if folder:
                import pes17
                if pes17.is_pes17(folder):
                    return pes17.open_save(folder, ro=ro)
        except Exception:
            pass
        return super(Save, cls).__new__(cls)

    def __init__(self, folder, ro=False):
        self.folder = folder
        self.path = os.path.join(folder, 'data.dat')
        self.ro = ro
        if ro:
            # pc262: samo za CITANJE (pogledi): jedan dijeljeni nepromjenjivi bytes po (datoteka, mtime, velicina) umjesto
            # 60 MB kopije po zahtjevu. Pokusaj pisanja u self.d baca TypeError (bytes), nikad ne mijenja tudji save.
            st_ = os.stat(self.path)
            k_ = (self.path, st_.st_mtime_ns, st_.st_size)
            raw = Save._RO_CACHE.get(k_)
            if raw is None:
                raw = open(self.path, 'rb').read()
                for _k in [x for x in Save._RO_CACHE if x[0] == self.path or len(Save._RO_CACHE) > 3]:
                    Save._RO_CACHE.pop(_k, None)
                Save._RO_CACHE[k_] = raw
            self.d = raw
        else:
            self.d = bytearray(open(self.path, 'rb').read())
        self.sh = self._detect_shift()
        global F0, SHIFT
        SHIFT = self.sh
        F0 = F0_BASE + self.sh
        self.TAC0 = TAC_BASE + self.sh
        self.MY_TIDX = 693
        if self.sh:
            self.TAC0, self.MY_TIDX = self._detect_tac0()
            # pc255: provjera preko trenera. Zapis taktike (600 B) je zapis TRENERA: u32 id trenera na TAC0 - 56 + 600 * k mora biti
            # id trenera kluba (zapis kluba +652). Klasicni/45 MB: pomak 0. 60 MB (Mod Studio 0.2.2+): AI klubovi su 1175 zapisa
            # ranije (Nottingham -> Nuno Santo, Newcastle -> Eddie Howe); bez ovoga su izvjestaj o protivniku, AI taktike i AI postave
            # citali i pisali zapise drugih klubova (tester 60 MB, Report 05). Korisnikov zapis (MY_TAC) ostaje isti.
            _dk = self._coach_shift()
            if _dk:
                self.TAC0 += 600 * _dk
                self.MY_TIDX -= _dk
        self.MY_TAC = self.TAC0 + 600 * self.MY_TIDX
        self.PLAN0 = self.TAC0 + 5
        self.F0 = F0   # pc306: blok momcadi kojom se upravlja (klub; use_nation() -> reprezentacija, zapis taktike odmah iza)
        self._team_off = None
        # srednji dio (stanje igre, 12-13 MB) u prosirenom save-u: potvrdeno budzetom iz igre (145.000.800) u dva save-a
        self.ext = bool(self.sh)
        self.dx, self.layout_ok, self.layout_note, self.dxa = layout_probe(self.d, self.sh, self.path)
        if self.ext and self.game27:
            self.layout_note = 'Football Life 2027 save: the app reads and writes it (transfers, loans, free agents, youth, contracts, tactics and AI transfers checked in the game; one pending deal at a time)'
        self.sh2 = (EXT_SH2 + self.dx) if self.ext else 0
        self.sh2a = (EXT_SH2 + self.dxa) if self.ext else 0
        if self.ext and self.game27:
            self.sh2a = self._fl27_front_sh2a(self.sh2a)   # fl27-layout: struktura odlucuje, ne fiksni broj
        global SH2, DX, SH2A, DXA
        SH2 = self.sh2
        SH2A = self.sh2a
        DX = self.dx if self.ext else 0
        DXA = self.dxa if self.ext else 0
        for _n in ('CH0', 'BUDGET', 'ENTRY7', 'POOL0', 'ENT0', 'S16CNT', 'S2_R', 'D0', 'C0'):
            setattr(self, _n, Y(getattr(Save, _n)))
        if self.ext:
            self.S2_R = X(0x23eb8b0)
        if self.ext and self.game27:
            # fl27-layout: literal vrijedi samo za izmjereni raspored (FL27_SH); inace isti razmak prema BUDGET kao u klasicnom (9940 B)
            self.D0 = 13108180 if self.sh in self.FL27_KNOWN_SH else self.BUDGET + (13108180 - Save.BUDGET)   # pc273: FL27 dnevnik dogovora (izmjereno: Alvaro Rodriguez, 4.8.2026); placa C0, budzet, unos isti kao klasicni
        self.check_block()
        # pc261: kopija ucitanog savea (za zastite _guard_extended / changed_outside) se cita s diska tek kad zatreba.
        # Prije: svaki Save na 45/60 MB je drzao dvije kopije (60 MB save = 115 MB po objektu), a pogledi ga nikad ne koriste.
        self._orig_c = None
        self._orig_k = None
        if self.sh:
            try:
                _st = os.stat(self.path)
                self._orig_k = (_st.st_mtime_ns, _st.st_size)
            except Exception:
                self._orig_c = bytes(self.d)

    @property
    def _orig(self):
        if not self.sh:
            return None
        if self._orig_c is None:
            _st = os.stat(self.path)
            if (_st.st_mtime_ns, _st.st_size) != self._orig_k:
                raise RuntimeError('The save file changed on disk while the app was editing it. Nothing was written; try again.')
            with open(self.path, 'rb') as fh:
                self._orig_c = fh.read()
        return self._orig_c

    # ---- blok
    def manager(self):
        return bytes(self.d[F0 + NAME_OFF:F0 + NAME_OFF + 40]).split(b'\0')[0].decode('utf-8', 'replace')

    _SHIFT_CACHE = {}
    _TAC_CACHE = {}

    def _coach_shift(self):
        """pc255: pomak (u zapisima od 600 B) izmedju indeksa kluba i zapisa njegovog trenera: id trenera iz zapisa kluba (+652)
        trazi se medju zapisima oko TAC0. Vraca 0 ako je sve na mjestu ili ako dokaz nije jasan (vecina i barem 50 klubova)."""
        from collections import Counter
        d = self.d
        T = self.TAC0 - 56
        ids = {}
        for k in range(-3000, 3000):
            o = T + 600 * k
            if o < 0 or o + 4 > len(d):
                continue
            ids.setdefault(struct.unpack_from('<I', d, o)[0], k)
        c = Counter()
        n = 0
        for idx in range(2400):
            o = REC0 + STRIDE * idx + 652
            if o + 4 > len(d):
                break
            cid = struct.unpack_from('<I', d, o)[0]
            if 0 < cid < (1 << 24) and cid in ids:
                c[ids[cid] - idx] += 1
                n += 1
        if not c:
            return 0
        dk, cnt = c.most_common(1)[0]
        if dk and cnt >= 50 and cnt >= 0.8 * n:
            return dk
        return 0

    def _detect_tac0(self):
        """pc239: tablica taktika klubova (600 B po klubu) i indeks korisnikovog zapisa u njoj. Na poznatim formatima korisnik je na
        indeksu 693 (TAC0 = TAC_BASE + pomak), ali baza s vise klubova (npr. Michele, UML 45 MB: 842) pomakne korisnikov zapis, a
        tablica ostaje na istom mjestu. Bira se pocetak na kojem su popisi Game Plana klubova ispravni (permutacije)."""
        key = None
        try:
            st = os.stat(self.path)
            key = (self.path, st.st_mtime, st.st_size)
            if key in Save._TAC_CACHE:
                return Save._TAC_CACHE[key]
        except Exception:
            key = None
        d = self.d
        my_tac = F0_BASE + self.sh - (F0_BASE - (TAC_BASE + 600 * 693))   # korisnikov zapis (F0 - 4)

        def score(t0, idxs):
            ok = 0
            tot = 0
            for i in idxs:
                so = REC0 + STRIDE * i
                n = 0
                for k in range(40):
                    if struct.unpack_from('<I', d, so + self.PAIR_OFF + 8 * k)[0] & 0xffff == 0xffff:
                        break
                    n += 1
                if n < 11:
                    continue
                tot += 1
                lo = t0 + 600 * i + 484
                if lo + n > len(d):
                    return -1, tot
                L = list(d[lo:lo + n])
                nv = L.index(0xff) if 0xff in L else n
                if nv >= 11 and sorted(L[:nv]) == list(range(nv)) and all(x == 0xff for x in L[nv:]):
                    ok += 1
            return ok, tot
        sc0, tot0 = score(TAC_BASE + self.sh, range(0, 120, 3))
        best = (sc0, 693)
        if tot0 and sc0 < 0.9 * tot0:
            t1 = TAC_BASE + EXT_SH   # najcesce: tablica na mjestu 45 MB formata, samo korisnik na drugom indeksu
            if (my_tac - t1) % 600 == 0 and my_tac > t1:
                sc, tot = score(t1, range(0, 120, 3))
                if sc >= 0.9 * tot:
                    best = (sc, (my_tac - t1) // 600)
        if tot0 and best[0] < 0.9 * tot0:
            for k in range(600, 2500):
                t0 = my_tac - 600 * k
                if t0 < 0:
                    break
                sc, tot = score(t0, range(0, 120, 3))
                if sc > best[0]:
                    best = (sc, k)
                    if sc >= tot:
                        break
        k = best[1]
        res = (my_tac - 600 * k, k)
        if key:
            Save._TAC_CACHE[key] = res
        return res

    def _detect_shift(self):
        try:
            st = os.stat(self.path)
            key = (self.path, st.st_mtime, st.st_size)
        except Exception:
            key = None
        if key and key in Save._SHIFT_CACHE:
            return Save._SHIFT_CACHE[key]
        r = self._detect_shift0()
        if key:
            Save._SHIFT_CACHE[key] = r
        return r

    def _detect_shift0(self):
        """Raspored blokova je isti kao u starom save-u, samo pomaknut za k*1680 B kad je tablica klubova veca (fl26caps)."""
        d = self.d
        def ok(f):
            if f - 56 < 0 or f + NAME_OFF < 0 or f + FORM_SZ * 3 + LINEUP_OFF > len(d):
                return False
            for k in range(3):
                pc = d[f + FORM_SZ * k:f + FORM_SZ * k + 11]
                if pc[0] != 0 or any(c > 12 for c in pc):
                    return False
            nm = bytes(d[f + NAME_OFF:f + NAME_OFF + 40]).split(b'\0')[0]
            try:
                t = nm.decode('utf-8')
            except Exception:
                return False
            if not (3 <= len(t) <= 30 and all(c.isalpha() or c in " .-'" for c in t)):
                return False
            # zapis taktike korisnika je dupliran (isto ime +600 B), AI klubovi to nemaju
            return bytes(d[f + NAME_OFF + 600:f + NAME_OFF + 600 + 40]).split(b'\0')[0] == nm
        if ok(F0_BASE):
            return 0
        # vanilla PES 2021: ime trenera u bloku taktike zna biti prazno; blok formacija je ipak na istom mjestu (oba zapisa jednaka)
        def ok_blank(f):
            for k in range(3):
                pc = d[f + FORM_SZ * k:f + FORM_SZ * k + 11]
                if pc[0] != 0 or any(c > 12 for c in pc):
                    return False
            a_ = bytes(d[f + NAME_OFF:f + NAME_OFF + 40]).split(b'\0')[0]
            b_ = bytes(d[f + NAME_OFF + 600:f + NAME_OFF + 600 + 40]).split(b'\0')[0]
            xi = d[f + LINEUP_OFF:f + LINEUP_OFF + 11]
            return a_ == b'' and b_ == b'' and len(set(xi)) == 11
        if ok_blank(F0_BASE):
            return 0
        # pc313: izmjereni pomaci (FL27 22.800 nije visekratnik od 1680) prije pretrage: pretraga ide od pocetka datoteke i
        # zna naci AI klub ciji je trener i u sljedecem zapisu (FL27 Liverpool 26.12.2026: Di Francesco na -398.400), pa bi app
        # citao tudju formaciju i krivo prepoznao karijeru
        for sh_ in (22800, 1428000, 3477000):
            if ok(F0_BASE + sh_):
                return sh_
        for k in range(1, 1500):
            if ok(F0_BASE + k * 1680):
                return k * 1680
        # nova verzija igre (npr. drukcija velicina zapisa kluba): trazi blok formacija bilo gdje u prvih 30 MB
        import re as _re
        pat = _re.compile(rb'(?=\x00[\x00-\x0c]{10}.{22}\x00[\x00-\x0c]{10}.{22}\x00[\x00-\x0c]{10})', _re.S)
        for m in pat.finditer(bytes(d[:30000000])):
            if ok(m.start()):
                return m.start() - F0_BASE
        return 0

    def check_block(self):
        F0 = self.F0
        for k in range(3):
            pc = self.d[F0 + FORM_SZ * k:F0 + FORM_SZ * k + 11]
            if pc[0] != 0 or any(c > 12 for c in pc):
                raise SaveFormatError('This save version is not supported yet: your club block was not found where expected. Your career is safe (nothing was written). In Setup click "Create support file" and send it to the app author.')
        xi = self.d[F0 + LINEUP_OFF:F0 + LINEUP_OFF + 11]
        if len(set(xi)) != 11:
            raise SaveFormatError('This save version is not supported yet (lineup block not recognised). Nothing was written. In Setup click "Create support file" and send it to the app author.')

    def club_name(self):
        desc = open(os.path.join(self.folder, 'description.dat'), 'rb').read().split(b'\0')
        parts = [p for p in desc if p]
        return parts[1].decode('utf-8', 'replace').split('\n')[0].split(' / ')[0] if len(parts) > 1 else ''

    def use_nation(self, ref):
        """pc306: reprezentacija koju menadzer vodi. Igra joj drzi formacije, upute i niz sastava u zapisu taktike ODMAH IZA
        korisnikova (MY_TAC + 600; izmjereno: ML2 Brentford + Japan, promjena formacije i 2 igraca u igri mijenja samo F0+600..+1100).
        Sastav (id-evi, brojevi) je u zapisu momcadi reprezentacije. Nakon poziva squad_ids/lineup/formation/taktika/brojevi rade na njoj."""
        o = REC0 + int(ref) * STRIDE
        f = self.F0 + 600
        n = self._squad_len(o)
        if not 11 <= n <= 40 or f + LINEUP_OFF + 35 > len(self.d):
            raise SaveFormatError('national team squad not found')
        for k in range(3):
            pc = self.d[f + FORM_SZ * k:f + FORM_SZ * k + 11]
            if pc[0] != 0 or any(c > 12 for c in pc):
                raise SaveFormatError('national team formation block not recognised')
        lu = list(self.d[f + LINEUP_OFF:f + LINEUP_OFF + 35])
        used = [c for c in lu if c != 0xff]
        if len(set(lu[:11])) != 11 or any(c >= n for c in used) or len(set(used)) != len(used):
            raise SaveFormatError('national team lineup not recognised (open the national squad once in the game and save)')
        self.F0 = f
        self.MY_TAC += 600
        self._team_off = o
        return self

    def club_offset(self):
        if self._team_off is not None:
            return self._team_off
        club = self.club_name().encode('utf-8')
        n = 0
        while True:
            o = REC0 + n * STRIDE
            if o + STRIDE > len(self.d):
                raise SaveFormatError('Club %r was not found in the save. If this is a new game version, in Setup click "Create support file" and send it to the app author.' % club.decode('utf-8', 'replace'))
            if bytes(self.d[o:o + 48]).split(b'\0')[0] == club:
                return o
            n += 1

    def table_ghosts(self):
        """pc202: stare verzije appa su pri svakoj posudbi mom klubu u tablici lige dodavale laznu utakmicu
        (45 MB: odigrano +1, poraz +1, golovi +1/+2 ili +2/+4; klasicni: odigrano +1, remi +1, bod +1, golovi +1/+1 ili +2/+2).
        Usporedi zapis kluba sa stvarno odigranim ligaskim utakmicama iz savea (seasonstats) -> dict ili None."""
        import seasonstats as _ss
        from collections import Counter
        d = self.d
        o = self.club_offset()
        ci = (o - REC0) // STRIDE
        M = _ss.compute(bytes(d))
        allm = [m for m in M['matches'] if ci in (m['home'], m['away'])]
        if not allm:
            return None
        cd = self.game_date_code()
        season = (cd & 0xffff) if ((cd >> 16) & 0xff) >= 7 else (cd & 0xffff) - 1
        allm = [m for m in allm if m['season'] == season]
        if not allm:
            return None
        tid = Counter(m['tid'] for m in allm).most_common(1)[0][0]   # liga = natjecanje s najvise utakmica (i buducih)
        lg = [m for m in allm if m['tid'] == tid and m['played']]
        W = D = L = gf = ga = 0
        for m in lg:
            h = (m['sc'][0] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] == m['home']))
            a = (m['sc'][1] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] == m['away']))
            mine, opp = (h, a) if m['home'] == ci else (a, h)
            gf += mine; ga += opp
            W += mine > opp; D += mine == opp; L += mine < opp
        rec = dict(pts=d[o + 746], p=d[o + 747], w=d[o + 748], d=d[o + 749], l=d[o + 750], gf=d[o + 752], ga=d[o + 756])
        n = rec['p'] - len(lg)
        # provjera s ostalim klubovima iste lige (njihov zapis nije diran)
        others = {c for m in M['matches'] if m['tid'] == tid and m['season'] == season for c in (m['home'], m['away'])} - {ci}
        op = Counter(d[REC0 + c * STRIDE + 747] for c in others if REC0 + c * STRIDE + 760 < len(d))
        mode = op.most_common(1)[0][0] if op else None
        out = dict(n=n, ext=bool(self.ext), club_index=ci, competition=tid, record=rec, real=dict(p=len(lg), w=W, d=D, l=L, gf=gf, ga=ga), league_mode=mode)
        if n < 1 or n > 12 or mode is None or abs((rec['p'] - n) - mode) > 1:
            out['n'] = 0
            return out
        dgf, dga = rec['gf'] - gf, rec['ga'] - ga
        if self.ext:
            if not (rec['l'] >= n and rec['w'] == W and rec['d'] == D):
                out['n'] = 0
                return out
            if not (dga == 2 * dgf and n <= dgf <= 2 * n):
                dgf, dga = n, 2 * n   # vlastiti golovi u rezultatima: najmanja lazna vrijednost
        else:
            if not (rec['d'] >= n and rec['w'] == W and rec['l'] == L):
                out['n'] = 0
                return out
            if not (dga == dgf and n <= dgf <= 2 * n):
                dgf = dga = n
        out.update(dgf=dgf, dga=dga)
        return out

    def fix_table_ghosts(self):
        """Oduzme lazne utakmice iz table_ghosts (samo moj klub). -> opis ili None."""
        g = self.table_ghosts()
        if not g or not g.get('n'):
            return None
        d = self.d
        o = self.club_offset()
        n, dgf, dga = g['n'], g['dgf'], g['dga']
        if self.beta_ok:
            self._beta_write = True   # samo zapis kluba (tablica lige), citanje na 60 MB izmjereno
        sub = [(747, n), (752, dgf), (756, dga)]
        if self.ext:
            sub.append((750, n))
        else:
            sub += [(746, n), (749, n)]
            if d[o + 760] >= dgf:
                sub.append((760, dgf))
        for off_, v in sub:
            d[o + off_] = max(0, d[o + off_] - v)
        self._allow = list(getattr(self, '_allow', [])) + [(o + 740, o + 770)]
        return 'removed %d fake league match(es): goals %d:%d' % (n, dgf, dga)

    def fix_points(self):
        """Bodovi kluba = 3*pobjede + nerijeseno (vraca staru vrijednost ako je ispravljeno, inace None)."""
        o = self.club_offset()
        w, d, pts = self.d[o + 748], self.d[o + 749], self.d[o + 746]
        want = 3 * w + d
        if pts != want and want < 256:
            self.d[o + 746] = want
            return pts
        return None

    def squad_ids(self):
        """id igraca po indeksu sastava (indeksi koje koristi niz sastava)."""
        o = self.club_offset()
        ids = []
        for i in range(40):
            pid, _ = struct.unpack_from('<II', self.d, o + SQUAD_OFF + 8 * i)
            ids.append(pid if 0 < pid < 400000 else None)
        return ids

    MY_TAC = 1260140 + 600 * 693  # zapis taktike korisnikovog tima (potvrdeno TAK_1-8); u instanci: + SHIFT
    ADV_NEEDS_OWN = (8, 10, 15)   # uputa trazi igraca iz vlastitog sastava
    ADV_NEEDS_OPP = (14,)         # Tight Marking: igrac protivnickog kluba

    def my_tactics(self):
        b = self.MY_TAC
        if b + 150 > len(self.d) or any(self.d[b + 103 + i] > 1 for i in range(7)):
            return None
        return self.club_tactics(0, rec_base=b, own=True)

    def set_club_tactics(self, idx, t):
        """Taktika AI kluba (bitovi pozicioniranja/podrucja nisu obrnuti kao kod korisnikova kluba)."""
        import mlsave
        if not 0 <= idx < mlsave.club_layout(self.d)[0] or self.club_tactics(idx) is None:   # pc258: i klubovi iznad 691 (60 MB)
            raise ValueError('club %s has no recognised tactics record' % idx)
        self.set_my_tactics(t, base=self.PLAN0 - 5 + 600 * idx, own=False)

    def set_my_tactics(self, t, base=None, own=True):
        """t: dict kao club_tactics (style,build,pos,area,defstyle,cont,press,support,line,compact,adv=[{slot,id,player}])."""
        b = self.MY_TAC if base is None else base
        d = self.d
        if base is None and self.my_tactics() is None:
            raise ValueError('tactics record not recognised in this save')
        def bit(k, yes, off):
            if k in t:
                d[b + off] = 1 if t[k] == yes else 0
        bit('style', 'possession', 103); bit('build', 'short', 104); bit('pos', 'flexible' if own else 'maintain', 105)
        bit('area', 'centre' if own else 'wide', 106); bit('defstyle', 'allout', 107); bit('cont', 'wide', 108); bit('press', 'conservative', 109)
        for k, off in (('support', 144), ('line', 146), ('compact', 147)):
            if k in t:
                v = int(t[k])
                if not 1 <= v <= 10:
                    raise ValueError('klizac mora biti 1-10')
                d[b + off] = v
        if 'adv' in t:
            slots = {'A1': 112, 'A2': 120, 'D1': 128, 'D2': 136}
            given = {a['slot']: a for a in t['adv']}
            seen = set()
            for nm, off in slots.items():
                a = given.get(nm)
                i = int(a['id']) if a and a.get('id') else 0
                valid = self.ADV_ATT if nm[0] == 'A' else self.ADV_DEF
                if i and i not in valid:
                    raise ValueError('nepoznata uputa %s' % i)
                if i and i in seen:
                    raise ValueError('ista uputa dvaput')
                seen.add(i)
                pl = int(a.get('player') or 0) if a else 0
                if i and i in self.ADV_NEEDS_OWN + self.ADV_NEEDS_OPP and a.get('player') is None:
                    raise ValueError('uputa %s trazi igraca' % valid[i])
                if i not in self.ADV_NEEDS_OWN + self.ADV_NEEDS_OPP:
                    pl = 0
                d[b + off:b + off + 8] = struct.pack('<II', i, pl)

    def club_squad_ids(self, idx):
        o = REC0 + idx * STRIDE + 328
        n = self.d[REC0 + idx * STRIDE + 1058]
        ids = []
        for i in range(min(n, 40)):
            _, pid = struct.unpack_from('<II', self.d, o + 8 * i)
            ids.append(pid if 0 < pid < 400000 else None)
        return ids

    # ---- citanje
    def formation(self, k):
        F0 = self.F0
        f = self.d[F0 + FORM_SZ * k:F0 + FORM_SZ * (k + 1)]
        return [(RPOS.get(f[i], '?'), f[11 + 2 * i], f[12 + 2 * i]) for i in range(11)]

    def lineup(self):
        F0 = self.F0
        return list(self.d[F0 + LINEUP_OFF:F0 + LINEUP_OFF + 35])

    # ---- pisanje
    def set_formation(self, k, preset):
        F0 = self.F0
        rows = PRESETS[preset] if isinstance(preset, str) else preset
        b = bytearray(FORM_SZ)
        for i, (p, x, y) in enumerate(rows):
            b[i] = p; b[11 + 2 * i] = x; b[12 + 2 * i] = y
        self.d[F0 + FORM_SZ * k:F0 + FORM_SZ * (k + 1)] = b

    def changed_outside(self, ranges):
        """pc209: prvi promijenjeni bajt izvan zadanih raspona [(lo, hi)] u odnosu na ucitani save, ili None."""
        orig, cur = self._orig, bytes(self.d)
        if len(orig) != len(cur):
            return 0
        B = 65536
        for p in range(0, len(cur), B):
            if cur[p:p + B] == orig[p:p + B]:
                continue
            for i in range(p, min(p + B, len(cur))):
                if cur[i] != orig[i] and not any(lo <= i < hi for lo, hi in ranges):
                    return i
        return None

    def set_lineup_by_ids(self, xi_ids, bench_ids=()):
        """xi_ids: 11 id-eva igraca REDOM kao pozicije u formaciji; bench_ids: do 12 id-eva klupe.
        Ostali igraci ostaju u nizu kako su bili (pricuva)."""
        ids = self.squad_ids()
        idx = {pid: i for i, pid in enumerate(ids) if pid}
        miss = [p for p in list(xi_ids) + list(bench_ids) if p not in idx]
        if miss:
            raise SaveFormatError('players are not in the club squad: %s' % miss)
        if len(xi_ids) != 11 or len(set(xi_ids) | set(bench_ids)) != len(xi_ids) + len(bench_ids):
            raise SaveFormatError('the starting XI needs exactly 11 different players')
        cur = self.lineup()
        want = [idx[p] for p in xi_ids] + [idx[p] for p in bench_ids]
        # pc209: kao igra (60 MB Arsenal, Konsa <-> Clarke 29.10.): igrac koji ispadne iz XI/klupe uzme mjesto u pricuvi
        # onoga tko je usao; ostali iz pricuve ostaju na svojim mjestima
        w = len(want)
        disp = [c for c in cur[:w] if c != 0xff and c not in want]
        rest = []
        for c in cur[w:]:
            if c == 0xff:
                continue
            if c in want:
                if disp:
                    rest.append(disp.pop(0))
            else:
                rest.append(c)
        rest += disp
        new = (want + rest)[:35]
        new += [0xff] * (35 - len(new))
        F0 = self.F0
        self.d[F0 + LINEUP_OFF:F0 + LINEUP_OFF + 35] = bytes(new)
        self._beta_write = self.beta_ok   # pc209: 60 MB izmjereno (samo ovaj niz se mijenja, F0 + 480)

    def auto_lineup(self, preset, positions, pool_ids=None):
        """Poslozi XI za formaciju iz bazena igraca (default: trenutnih 23 u nizu) po registriranim pozicijama.
        Vraca (xi_ids, bench_ids). positions: {id: kod pozicije}."""
        ids = self.squad_ids()
        if pool_ids is None:
            pool_ids = [ids[ix] for ix in self.lineup()[:23] if ix != 0xff and ix < len(ids) and ids[ix]]
        rows = PRESETS[preset] if isinstance(preset, str) else preset
        slots = [r[0] for r in rows]
        cost = [[DIST[s][positions.get(p, 5)] for p in pool_ids] for s in slots]
        pick = hungarian(cost)
        xi = [pool_ids[j] for j in pick]
        rest = [p for p in pool_ids if p not in xi]
        # klupa: najprije golman (ako ga ima), pa po redu
        gks = [p for p in rest if positions.get(p) == 0]
        bench = gks[:1] + [p for p in rest if p not in gks[:1]]
        return xi, bench[:12]

    # ---- transfer lista (zapisi od 56 B; slobodan zapis pocinje s 255)
    LIST_REC = 56

    def list_entries(self):
        """Svi zapisi transfer liste: [(offset, club_code, tag, id, date)] i pocetak niza."""
        import re
        d = self.d
        out = []
        hi = self.own_hi()
        for mt in re.finditer(re.escape(struct.pack('<H', hi)), bytes(d[Y(12000000):Y(13200000)])):
            p = Y(12000000) + mt.start()
            o = p - 6
            if o < 0 or p + 14 > len(d):
                continue
            code, tag, pid, w = struct.unpack_from('<IIII', d, o)
            if (tag >> 16) == hi and 0 < pid < 400000 and w == 0xffff and code < 0x400 and struct.unpack_from('<I', d, o + 48)[0] in (0xffff, 0xffffffff):
                out.append((o, code, tag, pid, struct.unpack_from('<I', d, o + 52)[0]))
        return sorted(out)

    def own_hi(self):
        """Visi 16 bitova oznake (tag) igraca ovog kluba: razlicit po karijeri/klubu; igraci na posudbi imaju drugu. Uzima se najcesca vrijednost u momcadi."""
        from collections import Counter
        c = Counter(t >> 16 for t in self.my_squad_tags().values())
        return c.most_common(1)[0][0] if c else 0x489f

    def my_squad_tags(self):
        """{pid: tag} iz momcadi kluba. Parovi u savu su (tag, id) od club+328."""
        o = self.club_offset() + 328
        res = {}
        for i in range(40):
            tag, pid = struct.unpack_from('<II', self.d, o + i * 8)
            if 0 < pid < 400000:
                res[pid] = tag
        return res

    # ---- pc250: igraci s istim brojem (PID) u vise zapisa ----
    def dup_pids(self):
        """{pid: [(offset zapisa, tag, vlasnik +140)]} za PID-ove koji imaju vise od jednog zapisa igraca.
        Klasicni/45 MB: 4 broja pripadaju dvojici igraca u dva kluba; 60 MB: 24 broja = igrac u klubu + kopija slobodnog igraca."""
        if getattr(self, '_dup_cache', None) is None:
            chunks, _e = self._chunks()
            big = b''.join(chunks)
            h = {}
            for r in range(144, len(big) - 155, 156):
                tag, pid = struct.unpack_from('<II', big, r + 44)
                if 0 < pid < 0x7fffffff:
                    h.setdefault(pid, []).append((r, tag, struct.unpack_from('<I', big, r + 140)[0]))
            self._dup_cache = {k: v for k, v in h.items() if len(v) > 1}
        return self._dup_cache

    def _canon_map(self):
        """pc252: za svaki dupli PID koji je zapis 'pravi' -> {pid: offset zapisa ili None}.
        Moj sastav: zapis ciji je par (oznaka, broj) u mom sastavu (ako je tocno jedan). Inace: zapis ciji je par u PRVOM klubu
        (po indeksu) koji ga ima u sastavu = klub koji app prikazuje (players_data, find_club_of). Inace None (nejasno)."""
        if getattr(self, '_canon_cache', None) is None:
            D = self.dup_pids()
            out = {}
            if D:
                my = self.club_offset()
                first, mine = {}, {}
                n = 0
                while REC0 + n * STRIDE + STRIDE <= min(len(self.d), 6000000):
                    o = REC0 + n * STRIDE
                    for i in range(40):
                        tag, p = struct.unpack_from('<II', self.d, o + self.PAIR_OFF + 8 * i)
                        if tag & 0xffff == 0xffff:
                            break
                        if p in D:
                            if o == my:
                                mine.setdefault(p, []).append(tag)
                            elif p not in first:
                                first[p] = tag
                    n += 1
                for p, h in D.items():
                    if p in mine:
                        tg = mine[p][0] if len(mine[p]) == 1 else None
                    else:
                        tg = first.get(p)
                    hit = [x for x in h if x[1] == tg] if tg is not None else []
                    out[p] = hit[0][0] if len(hit) == 1 else None
            self._canon_cache = out
        return self._canon_cache

    def _bf(self, big, needle, start=0):
        """pc252: big.find za 4-bajtni PID; za dupli PID vraca samo polozaj 'pravog' zapisa (_canon_map), ostale ne vidi."""
        if len(needle) == 4:
            cm = self._canon_map()
            if cm:
                pid = struct.unpack('<I', bytes(needle))[0]
                if pid in cm and cm[pid] is not None:
                    pos = cm[pid] + 48
                    return pos if start <= pos else -1
        return big.find(needle, start)

    def pid_guard(self, pid, strict=False):
        """Upisi koji igraca traze po PID-u. Dupli PID: dopusteno kad je jasno koji je zapis pravi (_canon_map, pc252);
        strict (AI potezi, mogu ciljati drugi klub): samo kad je prvi zapis jedini igrac u klubu. Inace odbij prije ikakvog upisa."""
        h = self.dup_pids().get(int(pid))
        if not h:
            return
        if not strict and self._canon_map().get(int(pid)) is not None:
            return
        owned = [x for x in h if x[2] not in (0, 0xffffffff)]
        if len(owned) == 1 and owned[0] is h[0]:
            return
        raise ValueError('This player shares his game ID (%d) with another player in this save, so the app cannot tell them apart safely. '
                         'Do this one in the game. The save was not touched.' % int(pid))

    def list_player(self, pid):
        """Stavlja igraca iz svog kluba na transfer listu (isti zapis kao igra). Vraca poruku.
        pc189: klasicni format pise isto kao prosireni: red 0x37 (tag, id, danasnji datum) u prvi prazan red reda dogadjaja
        (56 B od Y(12464992)) + bit0 u zapisu igraca. Prije je app trazio postojece unose po visim bitovima oznake, sto ne radi
        kad je oznaka kluba 0 (tester Palermo) ili kad jos nitko nije na listi (F1/R1: 'unknown club code')."""
        self.pid_guard(pid)   # pc250
        if self.ext:
            return self._list_x(pid, tl=True)
        squad = self.my_squad_tags()
        if pid not in squad:
            raise ValueError('player is not in your club')
        if (squad[pid] >> 16) != self.own_hi():
            raise ValueError('player is on loan or a promoted youth player: transfer listing from the app is not supported for him yet (works in game)')
        if Save.flag_map(self.d).get(pid, (False, False))[0]:
            return 'already on the list'
        QB = Y(12464992)
        free = None
        for k in range(0, 200):
            if struct.unpack_from('<I', self.d, QB + 56 * k)[0] == 0xff:
                free = QB + 56 * k
                break
        if free is None:
            raise ValueError('no free slot on the transfer list (event queue full: simulate a day in the game)')
        tmpl = bytearray(self.LIST_REC)
        struct.pack_into('<14I', tmpl, 0, 0x37, squad[pid], pid, 0xffff, 0, 0xffff, 0, 0xffffffff, 0xffff,
                         0xffffffff, 0, 0xffff, 0xffff, self.game_date_code())
        self.d[free:free + self.LIST_REC] = tmpl
        self.set_flags(pid, tl=True)
        return 'ok'


    # ---- spremljeni zapisi igraca (zlib dijelovi, 156 B po igracu) ----
    CH0 = 18088904  # pocetak niza zlib dijelova (zaglavlje 12 B po dijelu)

    def _chunks(self):
        d = self.d
        p = self.CH0
        out = []
        while True:
            raw, cl, cum = struct.unpack('>III', bytes(d[p:p + 12]))
            if raw == 0 or raw > 0x40000 or d[p + 12] != 0x78:
                break
            out.append(zlib.decompress(bytes(d[p + 12:p + 12 + cl])))
            p += 12 + cl
        return out, p

    @staticmethod
    def _deflate_exact(data, target):
        """zlib tok TOCNE duljine target (igra trazi rep datoteke na fiksnom mjestu, pa cijeli lanac mora
        zadrzati izvornu duljinu). Isti sadrzaj, drukcija kompresija: razina/memLevel kombinacije (uzme se ona
        koja je kraca od cilja) pa se razlika nadoknadi 'sync flush' tockama (svaka dodaje ~5 B)
        u zadnjih nekoliko tisuca bajtova bloka."""
        import random
        L = len(data)
        rnd = random.Random(5)
        bases = []
        for lvl in (9, 8, 7, 6):
            for mem in (9, 8, 7):
                co = zlib.compressobj(lvl, zlib.DEFLATED, 15, mem)
                z = co.compress(data) + co.flush()
                if len(z) == target:
                    return z
                if len(z) < target:
                    bases.append((target - len(z), lvl, mem))
        if not bases:
            # pc283: kad ni najjace sazimanje ne stane, probaj i druge strategije (Z_FILTERED, Z_RLE) prije odustajanja
            for strat in (zlib.Z_FILTERED, zlib.Z_RLE):
                co = zlib.compressobj(9, zlib.DEFLATED, 15, 9, strat)
                z = co.compress(data) + co.flush()
                if len(z) == target:
                    return z
            raise ValueError('The game keeps player data in packed blocks of a fixed size, and after the last change today this block is full '
                             '(%d bytes). Advance one day in the game and save (the game repacks its data), then try again. Nothing was written.' % target)
        bases.sort()
        for D, lvl, mem in bases[:3]:
            pre = {}
            for W in (1500, 4000, 8000, 16000):
                W = min(W, L - 1)
                co0 = zlib.compressobj(lvl, zlib.DEFLATED, 15, mem)
                pre[W] = (co0, co0.compress(data[:L - W]))
            Ws = list(pre)
            for _ in range(1500):
                W = rnd.choice(Ws)
                co0, z0 = pre[W]
                m = rnd.randint(1, max(1, min(16, D // 5 + 1)))
                cuts = sorted(rnd.sample(range(L - W + 1, L), m))
                co = co0.copy()
                z, prev = z0, L - W
                for k in cuts:
                    z += co.compress(data[prev:k]) + co.flush(zlib.Z_SYNC_FLUSH)
                    prev = k
                z += co.compress(data[prev:]) + co.flush()
                if len(z) == target:
                    return z
        raise ValueError('The game keeps player data in packed blocks of a fixed size, and this change does not fit the block right now '
                         '(%d bytes). Advance one day in the game and save (the game repacks its data), then try again. Nothing was written.' % target)

    def _rebuild(self, chunks, end):
        """Izmijenjene blokove sazima na TOCNO izvornu duljinu (spremanje mora ostati iste velicine);
        neizmijenjeni blokovi zadrzavaju izvorne bajtove."""
        old = []
        p = self.CH0
        while True:
            raw, cl, cum = struct.unpack('>III', bytes(self.d[p:p + 12]))
            if raw == 0 or raw > 0x40000 or self.d[p + 12] != 0x78:
                break
            old.append(bytes(self.d[p + 12:p + 12 + cl]))
            p += 12 + cl
        comp = []
        for i, c in enumerate(chunks):
            if i < len(old) and zlib.decompress(old[i]) == bytes(c):
                comp.append(old[i])
            else:
                comp.append(self._deflate_exact(bytes(c), len(old[i])))
        total = sum(len(c) for c in comp)
        buf = bytearray()
        cum = 28
        last = len(comp) - 1
        for i, (c, r) in enumerate(zip(comp, chunks)):
            cum += len(c)
            buf += struct.pack('>III', len(r), len(c), 0 if i == last else cum)
            buf += c
            cum += 12
        self.d[self.CH0 - 4:end] = struct.pack('>I', total) + bytes(buf)
        self._allow = list(getattr(self, '_allow', [])) + [(self.CH0 - 4, end)]

    def _check_own(self, pid):
        squad = self.my_squad_tags()
        if pid not in squad:
            raise ValueError('player is not in your club')
        if (squad[pid] >> 16) != self.own_hi():
            raise ValueError('player is on loan or a promoted youth player: this action from the app is not supported for him yet (works in game)')

    def _list_x(self, pid, tl=None, loan=None):
        """45 MB format: transfer lista / lista posudbi kao u igri (izmjereno 14.10. na Dinamu: Kravtsov na listu, Stojkovic na posudbu).
        Zapis igraca (bajt zastavica): bit0 transfer lista, bit1 lista posudbi; uz transfer listu bajt ispred dobije 0x10.
        Red dogadjaja (56 B od X(0x244eb70)): prvi prazan red (tip 0xff) dobiva tip 0x37, par (tag, id) i danasnji datum na +52.
        Skidanje s transfer liste (izmjereno, Kravtsov): samo bit0 se brise; bez reda dogadjaja, 0x10 ostaje."""
        self._check_own(pid)
        tag = self.my_squad_tags()[pid]
        cur = Save.flag_map(self.d).get(pid, (False, False))
        on = tl if tl is not None else loan
        if (cur[0] if tl is not None else cur[1]) == on:
            return 'already set'
        chunks, end = self._chunks()
        big = bytearray(b''.join(chunks))
        j = None
        for k in range((len(big) - 144) // 156):
            if struct.unpack_from('<I', big, 144 + 156 * k + 48)[0] == pid:
                j = k
                break
        if j is None:
            raise ValueError('player is not in the saved database')
        o = 144 + 156 * (j + 1) + 10
        qo = None
        if on and not (self.fmt60 and tl is None):   # 60 MB (Arsenal, Ibraimi): lista posudbi bez reda dogadjaja
            QB = X(0x244eb70)
            for k in range(0, 200):
                q = QB + 56 * k
                if struct.unpack_from('<I', self.d, q)[0] == 0xff:
                    qo = q
                    break
            if qo is None and not self.fmt60:
                raise ValueError('The game\'s event list in this save is full right now (this happens around the start of the transfer window). Simulate a day or two in the game, save, and try again. Nothing was written.')
            # pc205: na 60 MB je red dogadjaja na pocetku roka cesto pun (200/200: Arsenal 1.7. i 24.7.2027, PAOK 1.7.);
            # igra tada ni sama ne dodaje red (posudba van Konse) -> stavi samo oznaku liste
        if tl is not None:
            big[o] = (big[o] | 1) if tl else (big[o] & ~1)
            if tl and not self.fmt60:   # 60 MB (Arsenal, Kepa): igra NE postavlja 0x10
                big[o - 1] |= 0x10  # skidanje s liste (izmjereno: Kravtsov) brise samo bit0, 0x10 ostaje
        else:
            big[o] = (big[o] | 2) if loan else (big[o] & ~2)
        sizes = [len(c) for c in chunks]
        new, pos = [], 0
        for sz in sizes:
            new.append(bytes(big[pos:pos + sz]))
            pos += sz
        self._rebuild(new, end)
        if qo is not None:
            struct.pack_into('<III', self.d, qo, 0x37, tag, pid)
            struct.pack_into('<I', self.d, qo + 52, self.game_date_code())
            # pc190: red dogadjaja mora biti dopusten u zastiti prosirenog savea (prije je spremanje odbijalo listu s prozora igraca)
            self._allow = list(getattr(self, '_allow', [])) + [(qo, qo + 56)]
        self._beta_write = self.beta_ok   # pc190: liste na 60 MB izmjerene (Arsenal Kepa, Ibraimi)
        if tl is not None:
            return 'ok' if tl else 'removed from the list'
        return 'loan listed' if loan else 'removed from the loan list'

    def unlist_player(self, pid):
        """Skida kvacicu 'Place on Transfer List' (kao igra: samo bit, unos ostaje)."""
        self.pid_guard(pid)   # pc250
        self._check_own(pid)
        if self.ext:
            return self._list_x(pid, tl=False)
        if not Save.flag_map(self.d).get(pid, (False, False))[0]:
            return 'was not on the list'
        self.set_flags(pid, tl=False)
        return 'skinut s liste'

    def loan_player(self, pid, on=True):
        """'Place on Loan List' (kao igra: samo bit)."""
        self.pid_guard(pid)   # pc250
        self._check_own(pid)
        if self.ext:
            return self._list_x(pid, loan=on)
        cur = Save.flag_map(self.d).get(pid, (False, False))[1]
        if cur == on:
            return 'already set' if on else 'was not on the loan list'
        self.set_flags(pid, loan=on)
        return 'loan listed' if on else 'removed from the loan list'

    @staticmethod
    def flag_map(data):
        """{pid: (na_transfer_listi, na_listi_posudbi)} iz spremljenih zapisa igraca."""
        # PES 2017: no FL26 zlib player-record chain in this save.
        try:
            import pes17
            if pes17._looks_pes17(bytes(data[:pes17.TEAM0 + 3 * pes17.TEAM_STRIDE]), len(data)):
                return {}
        except Exception:
            pass
        d = bytes(data)
        p = Y(Save.CH0)
        buf = b''
        while True:
            raw, cl, cum = struct.unpack('>III', d[p:p + 12])
            if raw == 0 or raw > 0x40000 or d[p + 12] != 0x78:
                break
            buf += zlib.decompress(d[p + 12:p + 12 + cl])
            p += 12 + cl
        res = {}
        for k in range((len(buf) - 144) // 156 - 1):
            pid = struct.unpack_from('<I', buf, 144 + 156 * k + 48)[0]
            v = buf[144 + 156 * (k + 1) + 10]
            if 0 < pid < 400000:
                res[pid] = (bool(v & 1), bool(v & 2))
        return res

    def set_flags(self, pid, tl=None, loan=None):
        """Postavlja/skida zastavicu 'na transfer listi' (bit0) i 'na listi posudbi' (bit1) u spremljenom zapisu igraca."""
        chunks, end = self._chunks()
        big = bytearray(b''.join(chunks))
        j = None
        n = (len(big) - 144) // 156
        for k in range(n):
            if struct.unpack_from('<I', big, 144 + 156 * k + 48)[0] == pid:
                j = k
                break
        if j is None:
            raise ValueError('player is not in the saved database')
        o = 144 + 156 * (j + 1) + 10
        v = big[o]
        if tl is not None:
            v = (v | 1) if tl else (v & ~1)
        if loan is not None:
            v = (v | 2) if loan else (v & ~2)
        big[o] = v
        sizes = [len(c) for c in chunks]
        new, pos = [], 0
        for sz in sizes:
            new.append(bytes(big[pos:pos + sz]))
            pos += sz
        self._rebuild(new, end)


    # ---- novi dogovor (kupnja igraca) ----
    D0, DS = 13108960, 52     # dnevnik dogovora: [0,0,ffff,tag,id,0*6,-naknada,1]
    C0, CS = 13113456, 12     # placa po dogovoru: [tag,id,placa/100]
    BUDGET = 13098240         # transfer budzet /100
    ENTRY7 = 12464992 + 56 * 7

    def player_tag(self, pid):
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        for k in range((len(big) - 144) // 156):
            if struct.unpack_from('<I', big, 144 + 156 * k + 48)[0] == pid:
                return struct.unpack_from('<I', big, 144 + 156 * k + 44)[0]
        raise ValueError('player is not in the database')

    def _free_slot(self, start, size, limit=400):
        for k in range(limit):
            o = start + k * size
            tag_off = 12 if size == self.DS else 0
            if struct.unpack_from('<I', self.d, o + tag_off)[0] == 0xffff:
                return o, k
        raise ValueError('no free slot')

    def add_deal(self, pid, fee, salary, release=None, end=0x1f0807eb, date=None, level=2):
        """fee, salary, release u EUR. level 1 = samo dnevnik+placa+budzet, 2 = + tablice u repu (A, B)."""
        tag = self.player_tag(pid)
        f, sal = fee // 100, salary // 100
        rel = (release if release is not None else fee) // 100
        fl27 = bool(self.ext and self.game27)
        if fl27:
            self._fl27_layout_check()
            if level >= 2:
                self._fl27_one_pending()
        # pc273 FL27 (izmjereno na pravom dogovoru, Alvaro Rodriguez, Liverpool, 4.8.2026): dnevnik dogovora 780 B ranije (D0 u __init__),
        # rijec +8 je 0 (klasicni ffff); placa, budzet, unos i tablice A/B na istim mjestima kao klasicni
        src = self.find_club_of(pid)
        if not src:
            raise ValueError('player is not in any club')
        seller = struct.unpack_from('<I', self.d, 80 + 1680 * self.club_idx_of_offset(src[0]))[0]
        # dnevnik dogovora
        o, k = self._free_slot(self.D0, self.DS)
        struct.pack_into('<13I', self.d, o, 0, 0, 0 if fl27 else 0xffff, tag, pid, 0, 0, 0, 0, 0, 0,
                         struct.unpack('<I', struct.pack('<i', -f))[0], 1)
        # placa
        oc = self.C0 + k * self.CS
        assert struct.unpack_from('<I', self.d, oc)[0] == 0xffff, 'C and D are not in sync'
        struct.pack_into('<3I', self.d, oc, tag, pid, sal)
        # budzet
        b = struct.unpack_from('<I', self.d, self.BUDGET)[0]
        if f > b:
            raise ValueError('not enough money in the transfer budget')
        struct.pack_into('<I', self.d, self.BUDGET, b - f)
        # unos (zadnji dogovor)
        if date is None:
            date = self.game_date_code()
        if fl27:
            # pc273: FL27 igra pri prihvacanju igraca upise red 0x1b u S16 (odgovori klubova) i poveca brojac; bez toga igra
            # skine novac, ali igrac nikad ne dode (test Kluivert, 31.10.). Isti red kao _pending_x (izmjereno: Alvaro, s1)
            S16, CNT, k16 = self._s16_slot()
            o16 = S16 + 80 * k16
            row = struct.pack('<IIIIIIIII', 0x1b, date, 3, 0xff, 1, 0, 0xffffffff, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
                bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
            self.d[o16 + 4:o16 + 80] = row
            if o16 + 80 < S16 + 80 * 112:
                self.d[o16 + 80:o16 + 84] = bytes.fromhex('09414100')
            struct.pack_into('<I', self.d, CNT, struct.unpack_from('<I', self.d, CNT)[0] + 1)
        ent = self.ENTRY7
        if fl27:
            # FL27: igra pise unos u prvi prazan red dnevnika (0xff), ne u fiksni red 7
            ent = next((self.ENT0 + 56 * j for j in range(40) if self.d[self.ENT0 + 56 * j] == 0xff), None)
            if ent is None:
                raise ValueError('event log is full; advance a day in the game and try again')
        struct.pack_into('<14I', self.d, ent, 110, tag, pid, 0xffff, 0, 0xffff, 0, 0xffffffff, 0xffff,
                         0xffffffff, 0, 0xffff, 0xffff, date)
        if fl27 and level >= 2:
            self._fl27_deal_tail(tag, pid, sal, rel, end, f, seller, date)
            # pc273: kupnja je izmjerena i provjerena u igri (Kluivert dosao, 31.10.); dopusteni su samo dijelovi koje ovaj upis dira
            _ch, e_ = self._chunks()
            self._allow = list(getattr(self, '_allow', [])) + [
                (ent, ent + 56), (o16, o16 + 84), (CNT, CNT + 4), (self.BUDGET, self.BUDGET + 4), (o, o + self.DS), (oc, oc + self.CS),
                (e_ + 16, e_ + 16 + 48 * 200), (e_ + 54736, e_ + 54736 + 60 * 110), (e_ + self.SERLIST, e_ + self.SERLIST + 80)]
            self._beta_write = True
        elif level >= 2:
            chunks, end_ = self._chunks()
            tail = end_
            a0 = tail + 140
            for i in range(120):
                oa = a0 + 48 * i
                if struct.unpack_from('<I', self.d, oa)[0] == 0xffff:
                    struct.pack_into('<5I', self.d, oa, tag, pid, sal, rel, end)
                    break
            else:
                raise ValueError('tablica A puna')
            b0 = tail + 54752
            for i in range(120):
                ob = b0 + 60 * i
                if struct.unpack_from('<I', self.d, ob + 12)[0] == 0xffffffff and struct.unpack_from('<I', self.d, ob + 16)[0] == 0xffff:
                    struct.pack_into('<5I', self.d, ob + 12, seller, tag, pid, f, f)   # pc273: +12 = kod prodajnog kluba (0x018d4013 je bio kod kluba 19 iz uzorka)
                    break
            else:
                raise ValueError('tablica B puna')
        return 'dogovor dodan (tag %08x)' % tag

    FL27_KNOWN_SH = (22800,)   # pc273: izmjereni FL27 raspored (FL 2027 27.1.0, 750 mjesta za klubove); samo tu vrijede fiksne adrese
    FL27_SH = FL27_KNOWN_SH + (1450800,)   # fl27-layout: 731 klub / 1600 mjesta (850 mjesta x 1680 + trenerov red 731 umjesto 693 x 600)
    FL27_SH = FL27_SH + (29400,)   # pc414: 22800 + 6600 (11 trenerovih redova, isti dodatak klubova kao 1457400 na 1450800), Reddit 2.11.: provjera rasporeda i suhi upisi prolaze
    FL27_SH = FL27_SH + (1457400,)   # pc402: 742 kluba (FL27 s Classic Teams, Forchettone/Napoli 23.9.2026): 11 trenerovih redova vise (6600 B); prednji dio, brojac S16 (0x10228) i dnevnik dogovora kao kod 1450800, provjera rasporeda prolazi

    def _fl27_log_ok(self, ent, cnt_at):
        """Struktura prednjeg dijela: red dogadjaja (200 x 56 B, u32 na +36 = ffffffff u >= 150 redaka) i brojac S16 (256 + broj upisanih redaka; red = broj % 128)."""
        d = self.d
        try:
            if sum(struct.unpack_from('<I', d, ent + 56 * k + 36)[0] == 0xffffffff for k in range(200)) < 150:
                return False
            c = struct.unpack_from('<I', d, cnt_at)[0]
            # pc390: nizi bajt = indeks sljedeceg reda (0..127), gornji bajtovi su zastavice (vidi _s16_slot). FL27 s Carabao Cup
            # modom (Man Utd, 9.9.2026) ima 0x10228, ne 0x1xx; isti uvjet kao u _fl27_layout_check, uz bar jednu zastavicu
            return 0x100 <= (c & 0xffff) < 0x8000 and not c >> 24   # pc395: tekuci broj, vidi _fl27_layout_check
        except Exception:
            return False

    def _fl27_front_sh2a(self, sh2a):
        """Prednji pomak za Y(): ostaje kako jest ako red dogadjaja i brojac S16 tamo izgledaju ispravno. Inace se proba pomak koji
        daje front_dx() (isti 'red dogadjaja' kao u X(), 13.600 B prije Y()); prihvati se samo ako TADA struktura stoji, inace ostaje stari
        (pa _fl27_layout_check i dalje odbija)."""
        ent0, cnt0 = Save.ENT0, Save.S16CNT
        if self._fl27_log_ok(ent0 + sh2a, cnt0 + sh2a):
            return sh2a
        alt = sh2a + (0x244eb70 - ent0 - EXT_SH2)
        return alt if self._fl27_log_ok(ent0 + alt, cnt0 + alt) else sh2a
    FL27_LOANOUT_OK = True   # pc281: provjereno u igri (Kim Ji-Soo -> Leeds, slot 13)
    FL27_OPTION_OK = True    # pc281: provjereno u igri (Emerson, slot 17)
    FL27_FREE_OK = True      # pc281: provjereno u igri (Mahrez, slot 16)
    FL27_YOUTH_OK = True     # pc281: provjereno u igri (S. Viner, slot 14)
    FL27_AI_OK = True   # pc281: provjereno u igri (3 AI transfera, slot 12)
    FL27_EXTEND_OK = True   # pc275: produljenje 'na mjestu' provjereno u igri (Bradley, slot 11: ugovor, klauzula, komentar direktora)

    def _fl27_layout_check(self):
        """pc273: prije svakog FL27 upisa provjeri da je raspored isti kao izmjereni. Ako SP patch promijeni velicinu tablica,
        app i dalje cita, a upis se odbije (save netaknut) dok se novi raspored ne izmjeri."""
        d = self.d
        msg = ('This Football Life 2027 save has a different layout than the one the app was checked on (%s). '
               'Reading still works, but the app will not write to it until the new layout is checked. The save was not touched. '
               'Send this save to the app author.')
        if self.sh not in self.FL27_SH:
            raise ValueError(msg % ('club table shift %d' % self.sh))
        b = struct.unpack_from('<I', d, self.BUDGET)[0]
        if not (0 <= b < 50000000):
            raise ValueError(msg % 'budget')
        # dnevnik dogovora i place: red je prazan (ffff) ili nosi par (tag, id igraca). pc278: tag je razlicit po svijetu
        # (Liverpool 7a2a....,  druga karijera 887e.... / e71a....), pa se provjerava id igraca, ne tag
        okpid = lambda v: 0 < v < 1000000
        for k in range(40):
            t, tp = struct.unpack_from('<II', d, self.D0 + 52 * k + 12)
            c, cp = struct.unpack_from('<II', d, self.C0 + 12 * k)
            for v, vp in ((t, tp), (c, cp)):
                if v != 0xffff and not okpid(vp):
                    raise ValueError(msg % 'deal table')
        if d[self.ENT0] not in range(0, 0x100) or struct.unpack_from('<I', d, self.ENT0)[0] > 0xff:
            raise ValueError(msg % 'event log')
        cnt = struct.unpack_from('<I', d, 12509828 if self.sh in self.FL27_KNOWN_SH else self.S16CNT)[0]
        # pc395: brojac je tekuci broj (256 + svi upisani redovi, red = broj % 128), ne indeks: nakon ~128 odgovora prelazi 0x180
        # (Linux tester: provjera je tada odbijala svaki upis). Gornja 2 bajta su zastavice (Man Utd/Carabao: 0x10228).
        if (cnt & 0xffff) >= 0x8000 or cnt >> 24:
            raise ValueError(msg % 'club response counter')
        _ch, e = self._chunks()
        for k in range(200):
            o = e + 16 + 48 * k
            if bytes(d[o + 4:o + 8]) == b'\xff\xff\xff\xff':
                break
            if not okpid(struct.unpack_from('<I', d, o + 32)[0]):
                raise ValueError(msg % 'contract terms table')
        else:
            raise ValueError(msg % 'contract terms table')
        for k in range(110):
            o = e + 54736 + 60 * k
            sv = struct.unpack_from('<H', d, o)[0]
            if sv not in (0, 0xffff) and not okpid(struct.unpack_from('<I', d, o + 36)[0]):
                raise ValueError(msg % 'deal table in the tail')

    def _fl27_deal_tail(self, tag, pid, sal, rel, endc, f, seller, date, buyer=None):
        """pc273: FL27 rep dogovora, izmjereno na pravom dogovoru (Alvaro Rodriguez: s1 igrac prihvatio, s2 korisnik prihvatio).
        Uvjeti (rep+16, 48 B, sortirano po serijskom): [ser, kupac, status 4, datum izvrsenja, ff*8, ffff, tag, id, placa, klauzula, kraj].
        Dogovor (rep+54736, 60 B): [ser, kupac, 4, datum, ff*8, ffff, prodavac, tag, id, naknada, naknada, ffff, ffff, 0].
        Lista za izvrsenje (rep+SERLIST): oba serijska. Datum izvrsenja = sutra (igra: dogovor 4.8 -> 5.8, dolazak 7.8).
        Bez zaglavlja (ser/kupac/status) igra red smatra praznim i prepise ga (test Kluivert 2, 31.10.)."""
        d = self.d
        _ch, e = self._chunks()
        buyer = buyer or self.my_club_code()
        move = self._next_day_code(date)
        cbase = e + 16
        crows, k = [], 0
        while bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff':
            crows.append(bytes(d[cbase + 48 * k:cbase + 48 * k + 48]))
            k += 1
            if k > 200:
                raise ValueError('terms table: no end')
        mbase = e + 54736
        mrows, j0 = [], None
        for j in range(0, 120):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv not in (0, 0xffff):
                if j0 is None:
                    j0 = j
                mrows.append((sv, bytes(d[o2:o2 + 60])))
            elif j0 is not None:
                break
        if j0 is None:
            j0 = 0   # izmjereno: prazna tablica, igra pise u red 0
        if j0 + len(mrows) + 1 > 110:
            raise ValueError('deal table in the tail is full')
        used = {x[0] for x in mrows} | {struct.unpack_from('<H', x, 0)[0] for x in crows}
        free = [v for v in range(1, 0x400) if v not in used and v > max(used | {0})]
        ser_m, ser_t = free[0], free[1]   # igra: dogovor 0x22, uvjeti 0x23
        nr = struct.pack('<HHIII', ser_t, 0, buyer, 4, move) + b'\xff' * 8 + struct.pack('<IIIIII', 0xffff, tag, pid, sal, rel, endc)
        assert len(nr) == 48
        allc = sorted(crows + [nr], key=lambda x: struct.unpack_from('<H', x, 0)[0])
        if bytes(d[cbase + 48 * len(allc) + 4:cbase + 48 * len(allc) + 8]) != b'\xff\xff\xff\xff' and len(allc) > len(crows) + 1:
            raise ValueError('terms table is full')
        for n_, rb in enumerate(allc):
            d[cbase + 48 * n_:cbase + 48 * n_ + 48] = rb
        mrow = struct.pack('<HHIII', ser_m, 0, buyer, 4, move) + b'\xff' * 8 + \
            struct.pack('<IIIIIIIII', 0xffff, seller, tag, pid, f, f, 0xffff, 0xffff, 0)
        assert len(mrow) == 60
        allm = sorted(mrows + [(ser_m, mrow)], key=lambda t: t[0])
        for n_, (_, rb) in enumerate(allm):
            d[mbase + 60 * (j0 + n_):mbase + 60 * (j0 + n_) + 60] = rb
        self._serial_list_add(e, ser_m)
        self._serial_list_add(e, ser_t)
        return ser_m, ser_t

    def _loan_in_fl27(self, pid, fee, end_code):
        """pc274: FL27 dolazna posudba kao u igri (izmjereno: Benjamin Fredrick, klub idx 8 -> Liverpool, 3.699.400, do 30.6.2027;
        saveovi: ponuda poslana 25.8, dogovoreno 28.8, dosao 29.8). Pri dogovoru igra: budzet -naknada, D red [0,0,ffff,tag,id,..,-naknada,2],
        unos 0x6e, S16 red 0x1b (int6 ffffffff), dogovor M [ser, moj klub, 4, sutra, ff*8, ffff, vlasnik, tag, id, naknada, naknada,
        kraj posudbe, ffff, 0], serijski u listi. Bez reda placa (C) i bez reda uvjeta (T). Dolazak igra obavi sama sljedeci dan."""
        self._fl27_one_pending()
        self._fl27_layout_check()
        d = self.d
        if pid in self.my_squad_tags():
            raise ValueError('player is already in your club')
        if self._squad_len(self.club_offset()) >= 40:
            raise ValueError('squad is full (40)')
        src = self.find_club_of(pid)
        if not src:
            raise ValueError('player is not in any club')
        owner = struct.unpack_from('<I', d, src[0] - 4)[0]
        if (owner & 0x3fff) != self.club_idx_of_offset(src[0]):
            raise ValueError('club code not found')
        chunks, e = self._chunks()
        big = b''.join(chunks)
        i = self._bf(big, struct.pack('<I', pid))
        while i >= 0 and not (i >= 192 and (i - 192) % 156 == 0):
            i = self._bf(big, struct.pack('<I', pid), i + 1)
        if i < 0:
            raise ValueError('player record not found')
        if struct.unpack_from('<I', big, i - 48 + 136)[0] != 0xffffffff:
            raise ValueError('player is already on loan or moved in this window')
        tag = struct.unpack_from('<I', big, i - 4)[0]
        f = fee // 100
        b = struct.unpack_from('<I', d, self.BUDGET)[0]
        if f > b:
            raise ValueError('not enough money in the transfer budget')
        today = self.game_date_code()
        move = self._next_day_code(today)
        if ((today >> 16) & 0xff, today >> 24) in ((8, 31), (1, 31)):
            move = today
        mbase = e + 54736
        mrows, j0 = [], None
        for j in range(110):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv not in (0, 0xffff):
                if struct.unpack_from('<I', d, o2 + 36)[0] == pid:
                    raise ValueError('There is already an offer or deal for this player in the game. Finish or cancel it in the game. The save was not touched.')
                if j0 is None:
                    j0 = j
                mrows.append((sv, bytes(d[o2:o2 + 60])))
            elif j0 is not None:
                break
        if j0 is None:
            j0 = 0
        if j0 + len(mrows) + 1 > 110:
            raise ValueError('deal table in the tail is full')
        used = {x[0] for x in mrows}
        k = 0
        while bytes(d[e + 16 + 48 * k + 4:e + 16 + 48 * k + 8]) != b'\xff\xff\xff\xff' and k < 200:
            used.add(struct.unpack_from('<H', d, e + 16 + 48 * k)[0])
            k += 1
        ser = max(used | {0}) + 1
        ent = next((self.ENT0 + 56 * j for j in range(40) if d[self.ENT0 + 56 * j] == 0xff), None)
        if ent is None:
            raise ValueError('event log is full; advance a day in the game and try again')
        o, _k = self._free_slot(self.D0, self.DS)
        S16, CNT, k16 = self._s16_slot()
        o16 = S16 + 80 * k16
        mycode = struct.unpack_from('<I', d, self.club_offset() - 4)[0]
        # --- upisi
        struct.pack_into('<I', d, self.BUDGET, b - f)
        struct.pack_into('<13I', d, o, 0, 0, 0xffff, tag, pid, 0, 0, 0, 0, 0, 0, struct.unpack('<I', struct.pack('<i', -f))[0], 2)
        struct.pack_into('<14I', d, ent, 0x6e, tag, pid, 0xffff, 0, 0xffff, 0, 0xffffffff, 0xffff, 0xffffffff, 0, 0xffff, 0xffff, today)
        row = struct.pack('<IIIIIIIII', 0x1b, today, 3, 0xff, 1, 0, 0xffffffff, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
            bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
        d[o16 + 4:o16 + 80] = row
        if o16 + 80 < S16 + 80 * 112:
            d[o16 + 80:o16 + 84] = bytes.fromhex('09414100')
        struct.pack_into('<I', d, CNT, struct.unpack_from('<I', d, CNT)[0] + 1)
        mrow = struct.pack('<HHIII', ser, 0, mycode, 4, move) + b'\xff' * 8 + \
            struct.pack('<IIIIIIIII', 0xffff, owner, tag, pid, f, f, end_code, 0xffff, 0)
        allm = sorted(mrows + [(ser, mrow)], key=lambda t: t[0])
        for n_, (_, rb) in enumerate(allm):
            d[mbase + 60 * (j0 + n_):mbase + 60 * (j0 + n_) + 60] = rb
        self._serial_list_add(e, ser)
        self._allow = list(getattr(self, '_allow', [])) + [
            (ent, ent + 56), (o16, o16 + 84), (CNT, CNT + 4), (self.BUDGET, self.BUDGET + 4), (o, o + self.DS),
            (mbase, mbase + 60 * 110), (e + self.SERLIST, e + self.SERLIST + 80)]
        self._beta_write = True
        return 'loan agreed %d: arrives %s, until %s (deal %d)' % (pid, hex(move), hex(end_code), ser)

    def _fl27_one_pending(self):
        """pc281: na FL27 samo jedan dogovor smije cekati izvrsenje (lista izvrsenja prazna). Test 31.10. (slot 13): tri dogovora
        odjednom -> igra je dva ponistila (novac ostao pomaknut), a treci izvrsila krivo. Jedan po jedan su sva tri prosla."""
        d = self.d
        _ch, e = self._chunks()
        if any(struct.unpack_from('<H', d, e + self.SERLIST + 2 * j)[0] != 0xffff for j in range(40)):
            raise ValueError('Another deal is already waiting to be completed by the game. On Football Life 2027 the game can cancel deals '
                             'when several wait at once, so the app does one at a time: advance a day in the game, save, then do the next one. '
                             'The save was not touched.')

    def _fl27_common(self):
        """pc278: zajednicko za FL27 dogovore: (kraj repa, kod mog kluba, slobodni red dnevnika dogadjaja, S16 red, brojac)."""
        d = self.d
        _ch, e = self._chunks()
        mycode = struct.unpack_from('<I', d, self.club_offset() - 4)[0]
        ent = next((self.ENT0 + 56 * j for j in range(60) if d[self.ENT0 + 56 * j] == 0xff), None)
        if ent is None:
            raise ValueError('event log is full; advance a day in the game and try again')
        S16, CNT, k16 = self._s16_slot()
        return e, mycode, ent, S16, CNT, S16 + 80 * k16

    def _fl27_s16(self, S16, CNT, o16, code, tag, pid, date):
        d = self.d
        row = struct.pack('<IIIIIIIII', 0x1b, date, 3, 0xff, 1, 0, code, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
            bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
        d[o16 + 4:o16 + 80] = row
        if o16 + 80 < S16 + 80 * 112:
            d[o16 + 80:o16 + 84] = bytes.fromhex('09414100')
        struct.pack_into('<I', d, CNT, struct.unpack_from('<I', d, CNT)[0] + 1)

    def _fl27_serials(self, e, n=1):
        """Najmanji slobodni serijski brojevi (kao igra): nisu u uvjetima (T), dogovorima (M) ni listi izvrsenja."""
        d = self.d
        used = set()
        k = 0
        while bytes(d[e + 16 + 48 * k + 4:e + 16 + 48 * k + 8]) != b'\xff\xff\xff\xff' and k < 200:
            used.add(struct.unpack_from('<H', d, e + 16 + 48 * k)[0])
            k += 1
        for j in range(110):
            v = struct.unpack_from('<H', d, e + 54736 + 60 * j)[0]
            if v not in (0, 0xffff):
                used.add(v)
        for j in range(40):
            v = struct.unpack_from('<H', d, e + self.SERLIST + 2 * j)[0]
            if v != 0xffff:
                used.add(v)
        out = [v for v in range(1, 0x400) if v not in used][:n]
        if len(out) < n:
            raise ValueError('deal serial out of range')
        return out

    def _fl27_insert_T(self, e, row):
        d = self.d
        cbase = e + 16
        crows, k = [], 0
        while bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff':
            crows.append(bytes(d[cbase + 48 * k:cbase + 48 * k + 48]))
            k += 1
            if k > 200:
                raise ValueError('terms table: no end')
        allc = sorted(crows + [row], key=lambda x: struct.unpack_from('<H', x, 0)[0])
        for n_, rb in enumerate(allc):
            d[cbase + 48 * n_:cbase + 48 * n_ + 48] = rb
        return (cbase, cbase + 48 * (len(allc) + 1))

    def _fl27_insert_M(self, e, ser, row, pid):
        d = self.d
        mbase = e + 54736
        mrows, j0 = [], None
        for j in range(110):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv not in (0, 0xffff):
                if struct.unpack_from('<I', d, o2 + 36)[0] == pid:
                    raise ValueError('There is already an offer or deal for this player in the game. Finish or cancel it in the game. The save was not touched.')
                if j0 is None:
                    j0 = j
                mrows.append((sv, bytes(d[o2:o2 + 60])))
            elif j0 is not None:
                break
        if j0 is None:
            j0 = 0
        if j0 + len(mrows) + 1 > 110:
            raise ValueError('deal table in the tail is full')
        allm = sorted(mrows + [(ser, row)], key=lambda t: t[0])
        for n_, (_, rb) in enumerate(allm):
            d[mbase + 60 * (j0 + n_):mbase + 60 * (j0 + n_) + 60] = rb
        return (mbase, mbase + 60 * 110)

    def _fl27_rec(self, pid):
        chunks, _e = self._chunks()
        big = b''.join(chunks)
        i = self._bf(big, struct.pack('<I', pid))
        while i >= 0 and not (i >= 192 and (i - 192) % 156 == 0):
            i = self._bf(big, struct.pack('<I', pid), i + 1)
        if i < 0:
            raise ValueError('player record not found')
        return big, i - 48

    def _fl27_open_offer(self, e, pid):
        d = self.d
        k = 0
        while bytes(d[e + 16 + 48 * k + 4:e + 16 + 48 * k + 8]) != b'\xff\xff\xff\xff' and k < 200:
            o = e + 16 + 48 * k
            if struct.unpack_from('<I', d, o + 32)[0] == pid and d[o + 8] in (1, 2, 3, 4):
                raise ValueError('There is already an offer or deal for this player in the game. Finish or cancel it in the game. The save was not touched.')
            k += 1

    def _free_fl27(self, pid, salary, end_year, release=0):
        """pc278: FL27 slobodni igrac kao u igri (izmjereno: pid 63509, ponuda 21.8, potpis 24.8, dolazak 25.8.2026). Pri potpisu igra:
        red uvjeta T [ser, moj klub, 4, sutra, ff*8, ffff, tag, id, placa, klauzula, kraj], red place C [tag, id, placa], unos 0x6e,
        S16 red 0x1b (int6 ffffffff), serijski u listi izvrsenja. Bez naknade: nema reda D ni dogovora M. Dolazak igra obavi sama."""
        self._fl27_one_pending()
        self._fl27_layout_check()
        d = self.d
        if pid in self.my_squad_tags():
            raise ValueError('player is already in your club')
        if self._squad_len(self.club_offset()) >= 40:
            raise ValueError('squad is full (40)')
        big, r = self._fl27_rec(pid)
        fc = self.find_club_of(pid)
        if fc:
            import mlsave
            lim, nat = mlsave.club_layout(self.d)
            if self.club_idx_of_offset(fc[0]) in nat or self.club_idx_of_offset(fc[0]) >= lim:
                fc = None   # reprezentacija ili posebna momcad (igra ga i tamo drzi), nije klub
        if struct.unpack_from('<I', big, r + 140)[0] != 0xffffffff or fc:
            raise ValueError('player is not a free agent (has a club)')
        tag = struct.unpack_from('<I', big, r + 44)[0]
        today = self.game_date_code()
        move = self._next_day_code(today)
        if ((today >> 16) & 0xff, today >> 24) in ((8, 31), (1, 31)):
            move = today
        e, mycode, ent, S16, CNT, o16 = self._fl27_common()
        self._fl27_open_offer(e, pid)
        oc = next((self.C0 + 12 * j for j in range(40) if struct.unpack_from('<I', d, self.C0 + 12 * j)[0] == 0xffff), None)
        if oc is None:
            raise ValueError('wage table is full')
        ser = self._fl27_serials(e, 1)[0]
        sal, endc = salary // 100, (31 << 24) | (8 << 16) | end_year
        struct.pack_into('<3I', d, oc, tag, pid, sal)
        struct.pack_into('<14I', d, ent, 0x6e, tag, pid, 0xffff, 0, 0xffff, 0, 0xffffffff, 0xffff, 0xffffffff, 0, 0xffff, 0xffff, today)
        self._fl27_s16(S16, CNT, o16, 0xffffffff, tag, pid, today)
        trow = struct.pack('<HHIII', ser, 0, mycode, 4, move) + b'\xff' * 8 + struct.pack('<IIIIII', 0xffff, tag, pid, sal, (release or 0) // 100, endc)
        tr = self._fl27_insert_T(e, trow)
        self._serial_list_add(e, ser)
        self._allow = list(getattr(self, '_allow', [])) + [(oc, oc + 12), (ent, ent + 56), (o16, o16 + 84), (CNT, CNT + 4), tr,
                                                            (e + self.SERLIST, e + self.SERLIST + 80)]
        self._beta_write = True
        return 'Free-agent agreement for %d; he arrives after the next day in the game (deal %d).' % (pid, ser)

    def _loan_out_fl27(self, pid, club_offset, fee, end_code):
        """pc278: FL27 posudba MOG igraca van kao u igri (izmjereno: pid 184469 -> klub 0x424036, 5.770.200, do 30.6.2027; ponuda 13.8,
        prihvat 14.8, odlazak 15.8.2026). Ponuda iz igre ima S16 red 0x1b (kod kluba) i dogovor M (status 1); pri prihvatu igra:
        budzet +naknada, D red [0,0,0,tag,id,..,+naknada,2], unos 0x6f, M status 4 sutra, serijski u listi. App pise sve to (i S16 red)."""
        self._fl27_one_pending()
        self._fl27_layout_check()
        d = self.d
        sq = self.my_squad_tags()
        if pid not in sq:
            raise ValueError('player is not in your squad')
        tag = sq[pid]
        my = self.club_offset()
        if self._squad_len(my) <= 12:
            raise ValueError('your squad would be too small (the game needs at least 12 players)')
        if club_offset == my or self._squad_len(club_offset) >= 40:
            raise ValueError('loan club not possible (full or your club)')
        code = struct.unpack_from('<I', d, club_offset - 4)[0]
        if (code & 0x3fff) != self.club_idx_of_offset(club_offset):
            raise ValueError('club code not found')
        big, r = self._fl27_rec(pid)
        if struct.unpack_from('<I', big, r + 136)[0] != 0xffffffff:
            raise ValueError('he joined your club in this transfer window or is on loan, so he cannot be loaned out now')
        f = fee // 100
        today = self.game_date_code()
        move = self._next_day_code(today)
        if ((today >> 16) & 0xff, today >> 24) in ((8, 31), (1, 31)):
            move = today
        e, mycode, ent, S16, CNT, o16 = self._fl27_common()
        self._fl27_open_offer(e, pid)
        o, _k = self._free_slot(self.D0, self.DS)
        ser = self._fl27_serials(e, 1)[0]
        mrow = struct.pack('<HHIII', ser, 0, code, 4, move) + b'\xff' * 8 + \
            struct.pack('<IIIIIIIII', 0xffff, mycode, tag, pid, f, f, end_code, 0xffff, 0)
        mr = self._fl27_insert_M(e, ser, mrow, pid)
        struct.pack_into('<I', d, self.BUDGET, struct.unpack_from('<I', d, self.BUDGET)[0] + f)
        struct.pack_into('<13I', d, o, 0, 0, 0, tag, pid, 0, 0, 0, 0, 0, 0, f, 2)
        d[ent:ent + 56] = struct.pack('<III', 0x6f, tag, pid) + bytes.fromhex(
            'ffff000000000000ffff000000000000ffffffffffff0000ffffffff00001700ffff000080ff0000') + struct.pack('<I', today)
        self._fl27_s16(S16, CNT, o16, code, tag, pid, today)
        self._serial_list_add(e, ser)
        self._allow = list(getattr(self, '_allow', [])) + [(o, o + self.DS), (ent, ent + 56), (o16, o16 + 84), (CNT, CNT + 4), mr,
                                                            (self.BUDGET, self.BUDGET + 4), (e + self.SERLIST, e + self.SERLIST + 80)]
        self._beta_write = True
        return 'loan agreed %d: leaves %s, until %s (deal %d)' % (pid, hex(move), hex(end_code), ser)

    def _loan_opt_fl27(self, pid, fee, end_code, option):
        """pc278: FL27 dolazna posudba S OPCIJOM otkupa (izmjereno: pid 138047, 12.749.800, do 30.6.2027, opcija 29.749.700;
        dogovoreno 30.8, dosao 31.8.2026). Kao obicna posudba + red uvjeta T [ser_t, moj klub, 4, ffff, ff*8, ffff, tag, id, placa,
        klauzula, kraj] (uvjeti ako se opcija iskoristi) + cijena opcije (12 B od rep+0x24e10: oid u16, cijena/100, ser_t u16) i
        oid na M+16 (igra: prvi oid = 0). Stanje 'potvrdeno' nije snimljeno (samo prije i poslije) -> ceka test u igri."""
        self._fl27_layout_check()
        d = self.d
        r = self._loan_in_fl27(pid, fee, end_code)
        _ch, e = self._chunks()
        mbase = e + 54736
        om = next((mbase + 60 * j for j in range(110) if struct.unpack_from('<I', d, mbase + 60 * j + 36)[0] == pid
                   and struct.unpack_from('<H', d, mbase + 60 * j)[0] not in (0, 0xffff)), None)
        if om is None:
            raise ValueError('internal: loan row not found')
        tag = struct.unpack_from('<I', d, om + 32)[0]
        mycode = struct.unpack_from('<I', d, self.club_offset() - 4)[0]
        pb = e + 0x24e10
        kb, oid = None, -1
        for m_ in range(30):
            w0, w1 = struct.unpack_from('<II', d, pb + 12 * m_)
            if (w0 & 0xffff) == 0xffff and w1 == 0:
                if kb is None:
                    kb = m_
            else:
                oid = max(oid, w0 & 0xffff)
        if kb is None:
            raise ValueError('buy option price table is full')
        oid += 1
        ser_t = self._fl27_serials(e, 1)[0]
        trow = struct.pack('<HHIII', ser_t, 0, mycode, 4, 0xffff) + b'\xff' * 8 + \
            struct.pack('<IIIIII', 0xffff, tag, pid, option['wage'] // 100, option['release'] // 100, option['end'])
        tr = self._fl27_insert_T(e, trow)
        struct.pack_into('<HHIH', d, pb + 12 * kb, oid, struct.unpack_from('<H', d, pb + 12 * kb + 2)[0], option['buy'] // 100, ser_t)
        struct.pack_into('<H', d, om + 16, oid)
        self._allow = list(getattr(self, '_allow', [])) + [tr, (pb + 12 * kb, pb + 12 * kb + 12), (om + 16, om + 18)]
        return r + ', option to buy (deal %d)' % ser_t

    def sell_pending_fl27(self, pid, fee, buyer_offset):
        """pc274: FL27 prodaja MOG igraca kao u igri (izmjereno: Virgil van Dijk -> Newcastle, 64.749.000, 21.8.2026; saveovi prije,
        nakon prihvacanja, nakon odlaska). Pri prihvacanju igra: budzet +naknada, D red [0,0,ffff,tag,id,..,+naknada,5],
        C red [tag,id,placa], unos 0x6f, S16 red 0x1b s kodom kupca, uvjeti T i dogovor M (kupac, status 4, sutra), oba serijska u listu.
        Odlazak (sastav, zapis igraca, S16 0x21) igra obavi sama sljedeci dan."""
        self._fl27_one_pending()
        if not (self.ext and self.game27):
            raise ValueError('internal: FL27 only')
        self.pid_guard(pid)
        self._fl27_layout_check()
        d = self.d
        sq = self.my_squad_tags()
        if pid not in sq:
            raise ValueError('player is not in your squad')
        tag = sq[pid]
        my = self.club_offset()
        if self._squad_len(my) <= 12:
            raise ValueError('your squad would be too small (the game needs at least 12 players)')
        if buyer_offset == my or self._squad_len(buyer_offset) >= 40:
            raise ValueError('buying club not possible')
        buyer = struct.unpack_from('<I', d, buyer_offset - 4)[0]
        mycode = struct.unpack_from('<I', d, my - 4)[0]
        if (buyer & 0x3fff) != self.club_idx_of_offset(buyer_offset) or (mycode & 0x3fff) != self.club_idx_of_offset(my):
            raise ValueError('club code not found')
        chunks, _e = self._chunks()
        big = b''.join(chunks)
        i = self._bf(big, struct.pack('<I', pid))
        while i >= 0 and not (i >= 192 and (i - 192) % 156 == 0):
            i = self._bf(big, struct.pack('<I', pid), i + 1)
        if i < 0:
            raise ValueError('player record not found')
        r = i - 48
        if struct.unpack_from('<I', big, r + 136)[0] != 0xffffffff:
            raise ValueError('he joined your club in this transfer window or is on loan, so he cannot be sold now')
        wage = struct.unpack_from('<I', big, r + 128)[0]
        endc = struct.unpack_from('<I', big, r + 144)[0]
        f = fee // 100
        today = self.game_date_code()
        for k in range(40):
            q = self.ENT0 + 56 * k
            if d[q] in (0x6e, 0x6f) and struct.unpack_from('<I', d, q + 8)[0] == pid:
                raise ValueError('a deal for this player is already waiting to be executed')
        _ch0, e0 = self._chunks()
        for j in range(110):
            o2 = e0 + 54736 + 60 * j
            if struct.unpack_from('<H', d, o2)[0] not in (0, 0xffff) and struct.unpack_from('<I', d, o2 + 36)[0] == pid:
                raise ValueError('There is already an offer or deal for this player in the game. Accept or reject it in the game. The save was not touched.')
        ent = next((self.ENT0 + 56 * j for j in range(40) if d[self.ENT0 + 56 * j] == 0xff), None)
        if ent is None:
            raise ValueError('event log is full; advance a day in the game and try again')
        o, k = self._free_slot(self.D0, self.DS)
        oc = next((self.C0 + 12 * j for j in range(40) if struct.unpack_from('<I', d, self.C0 + 12 * j)[0] == 0xffff), None)
        if oc is None:
            raise ValueError('wage table is full')
        S16, CNT, k16 = self._s16_slot()
        o16 = S16 + 80 * k16
        # --- upisi
        struct.pack_into('<I', d, self.BUDGET, struct.unpack_from('<I', d, self.BUDGET)[0] + f)
        struct.pack_into('<13I', d, o, 0, 0, 0xffff, tag, pid, 0, 0, 0, 0, 0, 0, f, 5)
        struct.pack_into('<3I', d, oc, tag, pid, wage)
        d[ent:ent + 56] = struct.pack('<III', 0x6f, tag, pid) + bytes.fromhex(
            'ffff000000000000ffff000000000000ffffffffffff0000ffffffff00001800ffff000080ff0000') + struct.pack('<I', today)
        row = struct.pack('<IIIIIIIII', 0x1b, today, 3, 0xff, 1, 0, buyer, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
            bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
        d[o16 + 4:o16 + 80] = row
        if o16 + 80 < S16 + 80 * 112:
            d[o16 + 80:o16 + 84] = bytes.fromhex('09414100')
        struct.pack_into('<I', d, CNT, struct.unpack_from('<I', d, CNT)[0] + 1)
        ser_m, ser_t = self._fl27_deal_tail(tag, pid, wage, f, endc, f, mycode, today, buyer=buyer)
        _ch, e_ = self._chunks()
        self._allow = list(getattr(self, '_allow', [])) + [
            (ent, ent + 56), (o16, o16 + 84), (CNT, CNT + 4), (self.BUDGET, self.BUDGET + 4), (o, o + self.DS), (oc, oc + 12),
            (e_ + 16, e_ + 16 + 48 * 200), (e_ + 54736, e_ + 54736 + 60 * 110), (e_ + self.SERLIST, e_ + self.SERLIST + 80)]
        self._beta_write = True
        return 'sold %d: leaves after the next day in the game (deal %d/%d)' % (pid, ser_m, ser_t)

    # ---- prenamjena prihvacenog dogovora (provjereno u igri: igra dovede zamijenjenog igraca s upisanim uvjetima)
    POOL0 = 12489744   # poruke 80 B
    ENT0 = 12464992    # dnevnik dogadjaja 56 B

    def _tail(self):
        return self._chunks()[1]

    def list_deals(self):
        """Prihvaceni dogovori koje igra drzi zivima: igrac je istovremeno u D, C, A i B.
        Svaki se moze prenamijeniti (swap_deal)."""
        end = self._tail()
        d = self.d
        out = []
        for k in range(40):
            o = self.D0 + k * self.DS
            tag, pid = struct.unpack_from('<2I', d, o + 12)
            if tag == 0xffff:
                continue
            ia = next((i for i in range(120) if struct.unpack_from('<2I', d, end + 140 + 48 * i) == (tag, pid)), None)
            ib = next((i for i in range(120) if struct.unpack_from('<2I', d, end + 54752 + 60 * i + 16) == (tag, pid)), None)
            if ia is None or ib is None:
                continue
            fee = -struct.unpack_from('<i', d, o + 44)[0] * 100
            oc = self.C0 + k * self.CS
            sal = struct.unpack_from('<I', d, oc + 8)[0] * 100
            a = end + 140 + 48 * ia
            rel = struct.unpack_from('<I', d, a + 12)[0] * 100
            endc = struct.unpack_from('<I', d, a + 16)[0]
            out.append(dict(k=k, pid=pid, tag=tag, fee=fee, salary=sal, release=rel, end_year=endc & 0xffff))
        return out

    def placeholders(self, days=30, max_salary=400000):
        """Nedavno dovedeni jeftini igraci u momcadi (slotovi za izravnu zamjenu u prijelaznom roku)."""
        gd = self.game_date_code()
        gdd, gm, gy = gd >> 24, (gd >> 16) & 0xff, gd & 0xffff
        gnum = gy * 372 + gm * 31 + gdd
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        squad = {p for p in self.squad_ids() if p}
        out = []
        for k in range((len(big) - 144) // 156):
            r = 144 + 156 * k
            pid = struct.unpack_from('<I', big, r + 48)[0]
            if pid not in squad:
                continue
            st = struct.unpack_from('<I', big, r + 148)[0]
            sd, sm, sy = st >> 24, (st >> 16) & 0xff, st & 0xffff
            if not (1 <= sd <= 31 and 1 <= sm <= 12 and 2000 < sy < 2100):
                continue
            age = gnum - (sy * 372 + sm * 31 + sd)
            sal = struct.unpack_from('<I', big, r + 128)[0] * 100
            end = struct.unpack_from('<I', big, r + 144)[0]
            if 0 <= age <= days * 372 // 365 and sal <= max_salary:
                out.append(dict(pid=pid, tag=None, fee=0, salary=sal, release=0, end_year=end & 0xffff, kind='squad'))
        return out

    def squad_swap(self, old_pid, new_pid, fee, salary, end_year=2027):
        """Izravna zamjena u momcadi: new_pid dolazi na mjesto old_pid, old_pid ide u stari klub novog igraca."""
        my = self.club_offset()
        n = self._squad_len(my)
        if new_pid in self.my_squad_tags():
            raise ValueError('player is already in your club')
        src = self.find_club_of(new_pid)
        if not src or src[0] == my:
            raise ValueError('player club not found')
        if old_pid not in {p['pid'] for p in self.placeholders(days=45, max_salary=10 ** 9)}:
            raise ValueError('that player was not signed recently')
        mi = next(k for k in range(n) if struct.unpack_from('<I', self.d, my + self.PAIR_OFF + 8 * k + 4)[0] == old_pid)
        so, si = src
        tag_new = self.player_tag(new_pid)
        tag_old = struct.unpack_from('<I', self.d, my + self.PAIR_OFF + 8 * mi)[0]
        end = (31 << 24) | (8 << 16) | end_year
        msg = self.sign_player(new_pid, fee, salary, end=end, _old=False, _my=False, _num=False)
        struct.pack_into('<II', self.d, my + self.PAIR_OFF + 8 * mi, tag_new, new_pid)
        struct.pack_into('<II', self.d, so + self.PAIR_OFF + 8 * si, tag_old, old_pid)
        self.fix_squad_counts()
        return 'zamjena u momcadi: %d -> %d (%s)' % (old_pid, new_pid, msg)

    @staticmethod
    def window_key(code):
        """Prijelazni rok iz datuma igre: ('S', god) za 1.7.-31.8., ('W', god) za sijecanj, inace None."""
        d, m, y = code >> 24, (code >> 16) & 0xff, code & 0xffff
        if m in (7, 8):
            return ('S', y)
        if m == 1:
            return ('W', y)
        return None

    def moved_this_window(self):
        """Skup id-eva igraca ciji je ugovor poceo u trenutnom prijelaznom roku (promijenili su klub)."""
        wk = self.window_key(self.game_date_code())
        if wk is None:
            return set()
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        out = set()
        for k in range((len(big) - 144) // 156):
            r = 144 + 156 * k
            st = struct.unpack_from('<I', big, r + 148)[0]
            if 1 <= (st >> 24) <= 31 and self.window_key(st) == wk and not (st >> 24 == 1 and ((st >> 16) & 0xff) in (1, 7)):
                out.add(struct.unpack_from('<I', big, r + 48)[0])
        return out

    def recent_joins(self, days=400):
        """pc307: {pid: dani od dolaska} za igrace koji su u zadnjih `days` dana promijenili klub (datum dolaska +148; 1.1. i 1.7.
        su zadane vrijednosti baze pa se ne broje). Koristi se da AI ne proda igraca odmah nakon dolaska."""
        import datetime as _dt
        def dd(c):
            try:
                return _dt.date(c & 0xffff, (c >> 16) & 0xff, c >> 24)
            except Exception:
                return None
        now = dd(self.game_date_code())
        if now is None:
            return {}
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        out = {}
        for k in range((len(big) - 144) // 156):
            r = 144 + 156 * k
            st = struct.unpack_from('<I', big, r + 148)[0]
            if st >> 24 == 1 and ((st >> 16) & 0xff) in (1, 7):
                continue
            d = dd(st)
            if d is None:
                continue
            n = (now - d).days
            if 0 <= n <= days:
                pid = struct.unpack_from('<I', big, r + 48)[0]
                if 0 < pid < 400000:
                    out[pid] = min(n, out.get(pid, n))
        return out

    def set_contract_start(self, pid, date):
        self.pid_guard(pid)   # pc250
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        pat = struct.pack('<I', pid)
        i = self._bf(big, pat)
        r = None
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        struct.pack_into('<I', big, r + 148, date)
        new, pos = [], 0
        for c in chunks:
            new.append(bytes(big[pos:pos + len(c)]))
            pos += len(c)
        self._rebuild(new, end_)

    def set_contract_start_many(self, pids, date):
        """Kao set_contract_start, ali za vise igraca odjednom (jedna dekompresija/kompresija)."""
        pids = list(pids)
        if not pids:
            return 0
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        want = {pid: struct.pack('<I', pid) for pid in pids}
        # indeks svih zapisa: pid na r+48
        n = (len(big) - 144) // 156
        pos = {}
        for k in range(n):
            r = 144 + 156 * k
            v = struct.unpack_from('<I', big, r + 48)[0]
            if v in want and v not in pos:
                pos[v] = r
        miss = [x for x in pids if x not in pos]
        if miss:
            raise ValueError('player record not found: %s' % miss[:5])
        for pid, r in pos.items():
            struct.pack_into('<I', big, r + 148, date)
        new, p = [], 0
        for c in chunks:
            new.append(bytes(big[p:p + len(c)]))
            p += len(c)
        self._rebuild(new, end_)
        return len(pos)

    def fix_squad_counts(self, limit=800):
        """Brojac igraca kluba (club+1058) mora biti jednak duljini popisa sastava. Vraca broj ispravljenih klubova."""
        n = 0
        for k in range(limit):
            o = REC0 + k * STRIDE
            if o + STRIDE > len(self.d):
                break
            ln = self._squad_len(o)
            if self.d[o + 1058] != ln and 0 < ln <= 40 and bytes(self.d[o:o + 3]).isalnum() is not None:
                nm = bytes(self.d[o:o + 48]).split(b'\0')[0]
                if len(nm) >= 3 and nm.isascii() is not None and all(32 <= c < 127 or c >= 128 for c in nm):
                    self.d[o + 1058] = ln
                    n += 1
        return n

    PLAN0 = 1260145  # uloge 10 igraca u polju prvog kluba (zapis plana 600 B po klubu, indeks kluba = (offset-84)/1680)

    def club_presets(self, idx):
        """Tri formacije kluba (fluidna): [{'formation','slots':[(uloga,x,y)x10]}] po redu u zapisu (0 = otvaranje; redoslijed 1/2 jos treba potvrditi)."""
        out = []
        for k in range(3):
            o = self.PLAN0 + 600 * idx + 33 * k
            roles = list(self.d[o:o + 10])
            # pc255: iza 10 uloga je 11 parova (dubina, bok), PRVI je golman (3, 52); igrac i = par i+1. Prije se citalo od +11
            # pa je bok bio od prethodnog igraca (zadnji vezni s bokom lijevog beka, napadac s bokom lijevog krila).
            co = self.d[o + 10:o + 32]
            ok = all(1 <= r <= 12 for r in roles)
            c = lambda lo, hi: sum(1 for r in roles if lo <= r <= hi)
            name = plan_label(roles) if ok else None
            out.append(dict(formation=name, slots=[(roles[i], 104 - co[2 * i + 3], co[2 * i + 2]) for i in range(10)]))   # bok zrcaljen: veliki = njihova lijeva (konvencija appa)
        return out

    # --- taktika kluba (dekodirano iz pokusa TAK_1..5): zapis kluba = PLAN0-5+600*idx
    ADV_ATT = {1: 'Hug the Touchline', 2: 'False No. 9', 3: 'False Full Backs', 4: 'Attacking Full Backs', 5: 'Wing Rotation', 6: 'Tiki-Taka', 7: 'Centring Targets', 8: 'Defensive', 9: 'False Winger', 10: 'Anchoring'}
    ADV_DEF = {11: 'Swarm the Box', 12: 'Deep Defensive Line', 13: 'Gegenpress', 14: 'Tight Marking', 15: 'Counter Target', 16: 'Wing Back'}

    def club_tactics(self, idx, rec_base=None, own=False):
        b = rec_base if rec_base is not None else self.PLAN0 - 5 + 600 * idx
        d = self.d
        if b + 150 > len(d):
            return None
        adv = []
        for nm, off in (('A1', 112), ('A2', 120), ('D1', 128), ('D2', 136)):
            i = d[b + off]
            pl = d[b + off + 4]
            if i:
                att = nm[0] == 'A'
                adv.append(dict(slot=nm, id=i, name=(self.ADV_ATT if att else self.ADV_DEF).get(i), player=pl if pl not in (0, 255) or i in (8, 10, 14, 15) else None))
        return dict(
            style='possession' if d[b + 103] else 'counter',
            build='short' if d[b + 104] else 'long',
            # u zapisu korisnikovog tima (own) su ova dva bita obrnuta (potvrdeno testom u igri)
            pos=('flexible' if d[b + 105] else 'maintain') if own else ('maintain' if d[b + 105] else 'flexible'),
            area=('centre' if d[b + 106] else 'wide') if own else ('wide' if d[b + 106] else 'centre'),
            defstyle='allout' if d[b + 107] else 'frontline',
            cont='wide' if d[b + 108] else 'centre',
            press='conservative' if d[b + 109] else 'aggressive',
            support=d[b + 144], line=d[b + 146], compact=d[b + 147], adv=adv)

    def club_formation(self, idx):
        """Formacija AI kluba iz 'game plan' bloka: (oznaka npr. '4-2-1-3', lista kodova uloga). Kodovi:
        1 CB, 2 LB, 3 RB, 4 DMF, 5 CMF, 6 LMF, 7 RMF, 8 AMF, 9 LWF, 10 RWF, 11 SS, 12 CF."""
        o = self.PLAN0 + 600 * idx
        roles = list(self.d[o:o + 10])
        if not roles or any(r < 1 or r > 12 for r in roles):
            return None, roles
        return plan_label(roles), roles

    def club_slots(self, idx):
        """10 igraca u polju: [(kod uloge, x, y)] iz plana kluba (x 0..~104, y 0=vlastiti gol)."""
        o = self.PLAN0 + 600 * idx
        roles = list(self.d[o:o + 10])
        co = self.d[o + 10:o + 32]   # pc255: 11 parova (dubina, bok), prvi je golman
        return [(roles[i], 104 - co[2 * i + 3], co[2 * i + 2]) for i in range(10)]   # bok zrcaljen: veliki = njihova lijeva (konvencija appa); u igri veliki = desno

    def club_lineup(self, idx):
        """Postava AI kluba: indeksi sastava (prvih 11 = prva postava, ostali klupa) -> [player id]. Potvrdeno na Aston Villi."""
        o = REC0 + idx * STRIDE
        n = self.d[o + 1058]
        sq = [struct.unpack_from('<I', self.d, o + SQUAD_OFF + 8 * k)[0] for k in range(n)]
        base = self.TAC0 + 600 * idx + 484
        order = [i for i in self.d[base:base + n] if i < n]
        return [sq[i] for i in order]

    def ai_clubs(self, limit=None):
        """Popis klubova koji mogu kupiti: [(offset, naziv, velicina sastava)] bez tvog kluba.
        pc260: granica iz club_layout (60 MB: klubovi i iznad 580, bez reprezentacija); klasicni/45 MB i dalje 580."""
        my = self.club_offset()
        out = []
        nat = frozenset()
        if limit is None:
            try:
                import mlsave
                limit, nat = mlsave.club_layout(self.d)
            except Exception:
                limit = 580
        for n in range(limit):
            if n in nat:
                continue
            o = REC0 + n * STRIDE
            if o + STRIDE > len(self.d) or o == my:
                continue
            nm = bytes(self.d[o:o + 48]).split(b'\0')[0].decode('utf-8', 'replace')
            if len(nm) < 3 or not all(c.isprintable() for c in nm):
                continue
            k = self._squad_len(o)
            if 16 <= k <= 36:
                out.append((o, nm, k))
        return out

    def ai_apply(self, moves, pos=None, skip_errors=False, ovr_of=None):
        """moves: [(pid, buyer_idx)]. Izvrsava redom, ugovore i brojace na kraju. Vraca listu poruka."""
        if self.ext and self.game27 and not self.FL27_AI_OK:
            raise ValueError('AI transfers are not unlocked yet on Football Life 2027 saves (waiting for the in-game test). The save was not touched.')
        defer, out = [], []
        self.ai_skipped = []
        self.ai_xi = set()
        for mv in moves:
            pid, to = mv[0], mv[1]
            try:
                # pc253: AI potez seli samo par (oznaka, broj) iz sastava izvornog kluba, zapis igraca ne dira -> i igraci s duplim
                # brojem mogu u AI transfere (ai_move odbije samo ako izvorni klub ima oba igraca s istim brojem)
                out.append(self.ai_move(int(pid), int(to), pos, defer, int(mv[2]) if len(mv) > 2 and mv[2] is not None else None, ovr_of))
            except ValueError as e:
                if not skip_errors:
                    raise
                self.ai_skipped.append((int(pid), str(e)))
        # datum pocetka ugovora se NE mijenja: zapisi igraca su u zlib lancu fiksne duljine, pa masovna izmjena ne stane
        # pc209: 60 MB beta - AI->AI pise samo zapise klubova (sastav, brojevi) i popise Game Plana; _guard_extended i dalje
        # odbija sve ostalo (provjereno na Panetolikos/Dinamo Batumi, tester 29.10.)
        self._beta_write = self.beta_ok
        if self.ext and self.game27 and self.FL27_AI_OK:
            # pc277: FL27 AI->AI potez: isti zapisi klubova (sastav, brojevi) i popis Game Plana kao igra (izmjereno na 2 AI transfera
            # iz igre, 22.8. -> 25.8.: Kauan Jesus, Martin James; razlika samo izbor broja dresa i igrino preslagivanje postave)
            self._fl27_layout_check()
            self._allow = list(getattr(self, '_allow', [])) + [(self.TAC0, self.TAC0 + 600 * 760)]
            self._beta_write = True
        return out

    def club_idx_of_offset(self, o):
        return (o - REC0) // STRIDE

    @staticmethod
    def _lineup_shape(L, n):
        """pc209: popis Game Plana kluba (n igraca): 'full' = permutacija 0..n-1; 'part' = prvih nv mjesta su permutacija 0..nv-1,
        ostalo ff (igra drzi kraci popis, npr. Panetolikos 23 od 30, PAOK 23 od 31; igraci nv..n-1 nisu u popisu); inace None."""
        nv = L.index(0xff) if 0xff in L else len(L)
        if any(x != 0xff for x in L[nv:]) or sorted(L[:nv]) != list(range(nv)):
            return None, nv
        if nv == n:
            return 'full', nv
        return ('part', nv) if nv >= 11 else (None, nv)

    def ai_move(self, pid, buyer_idx, pos=None, defer=None, src_idx=None, ovr_of=None):
        """AI->AI (ili AI->bilo koji klub osim mog) transfer: sastav, brojevi, postava izvornog kluba, ugovor.
        pos: {pid: pozicijski kod} (0 = golman) za odabir zamjene u postavi. Vraca poruku."""
        my = self.club_offset()
        if src_idx is not None:
            so = REC0 + src_idx * STRIDE
            si = next((i for i in range(40) if struct.unpack_from('<I', self.d, so + self.PAIR_OFF + 8 * i + 4)[0] == pid), None)
            if si is None:
                raise ValueError('player %d is not in club %d' % (pid, src_idx))
        else:
            src = self.find_club_of(pid)
            if not src:
                raise ValueError('player is not in any club')
            so, si = src
        if pid in self.dup_pids():
            # pc253: dupli broj: izvorni klub smije imati samo jednog igraca s tim brojem (inace ne znamo kojeg seliti)
            nn = sum(1 for i in range(self._squad_len(so)) if struct.unpack_from('<I', self.d, so + self.PAIR_OFF + 8 * i + 4)[0] == pid)
            if nn != 1:
                raise ValueError('club has two players with game ID %d' % pid)
            if defer is None:
                raise ValueError('player with a shared game ID: contract date is only changed in bulk')
        bo = REC0 + buyer_idx * STRIDE
        if so == my or bo == my:
            raise ValueError('this is for AI clubs, not yours')
        if so == bo:
            raise ValueError('same club')
        sn, bn = self._squad_len(so), self._squad_len(bo)
        if sn <= 18:
            raise ValueError('source club would be too small')
        if bn >= 36:
            raise ValueError('buying club is full')
        pos = pos or {}
        # kupceva postava mora biti valjana permutacija prije bilo kakve izmjene (inace preskoci potez, ne pisi nista)
        _blo = self.TAC0 + 600 * buyer_idx + 484
        bshape, _bnv = self._lineup_shape([int(x) for x in self.d[_blo:_blo + bn]], bn)
        if bshape is None:
            raise ValueError('buying club lineup is not in the expected form')
        sidx = self.club_idx_of_offset(so)
        lo = self.TAC0 + 600 * sidx + 484
        L = [int(x) for x in self.d[lo:lo + sn]]
        ids = [struct.unpack_from('<I', self.d, so + self.PAIR_OFF + 8 * k + 4)[0] for k in range(sn)]
        sshape, snv = self._lineup_shape(L, sn)
        if sshape is None:
            raise ValueError('source club lineup is not in the expected form')
        tag = struct.unpack_from('<I', self.d, so + self.PAIR_OFF + 8 * si)[0]
        L = L[:snv]
        # pc209: igrac izvan kraceg popisa (indeks >= snv): popis ostaje isti (pomak sastava ne dira indekse < snv)
        if si in L:
            j = L.index(si)
            if j < 11:
                gk_out = pos.get(pid, 5) == 0
                cand = [k for k in range(11, len(L)) if k != j and L[k] != si]
                best = [k for k in cand if (pos.get(ids[L[k]], 5) == 0) == gk_out]
                if not best:
                    raise ValueError('no replacement in the lineup')
                k = best[0]
                L[j] = L[k]
                del L[k]
            else:
                del L[j]
            L = [x - 1 if x > si else x for x in L]
        L += [0xff] * (sn - len(L))
        # izvorni klub: sastav + brojevi pomak ulijevo
        for k in range(si, sn - 1):
            a = so + self.PAIR_OFF + 8 * k
            self.d[a:a + 8] = self.d[a + 8:a + 16]
            a = so + self.NUM_OFF + 2 * k
            self.d[a:a + 2] = self.d[a + 2:a + 4]
        struct.pack_into('<II', self.d, so + self.PAIR_OFF + 8 * (sn - 1), 0xffff, 0)
        struct.pack_into('<H', self.d, so + self.NUM_OFF + 2 * (sn - 1), 0)
        self.d[lo:lo + sn] = bytes(L)
        # kupac: na kraj sastava i postave (kao rezerva), prvi slobodan broj
        struct.pack_into('<II', self.d, bo + self.PAIR_OFF + 8 * bn, tag, pid)
        used = {struct.unpack_from('<H', self.d, bo + self.NUM_OFF + 2 * k)[0] for k in range(bn)}
        num = next(x for x in range(2, 100) if x not in used)
        struct.pack_into('<H', self.d, bo + self.NUM_OFF + 2 * bn, num)
        blo = self.TAC0 + 600 * buyer_idx + 484
        BL = [int(x) for x in self.d[blo:blo + bn]]
        if sorted(BL) == list(range(bn)):
            self.d[blo + bn] = bn
            if ovr_of is not None and self._into_xi(buyer_idx, bo, bn, BL, pid, pos, ovr_of):
                if not hasattr(self, 'ai_xi'):
                    self.ai_xi = set()
                self.ai_xi.add(pid)
        self.d[so + 1058] = sn - 1
        self.d[bo + 1058] = bn + 1
        if defer is None:
            self.set_contract_start(pid, self.game_date_code())
        else:
            defer.append(pid)
        sname = bytes(self.d[so:so + 48]).split(b'\0')[0].decode('utf-8', 'replace')
        bname = bytes(self.d[bo:bo + 48]).split(b'\0')[0].decode('utf-8', 'replace')
        return '%d: %s -> %s (broj %d)' % (pid, sname, bname, num)

    # ---- po-slotne tablice mog kluba (dekodirano usporedbom savea prije/poslije pravog potpisa u igri)
    _S10A = bytes.fromhex('b725b047481e01003b3b1d3b1d3b1d3b3b3b3b3b1d3b00000000000000000000000000000000000000001027881388130000141bcc2600008a096c00ef1f0f00711d9e08430f21168f1df4029c1c00000000000000009809911ffb20e70ea803851c411dbd050e11d01e')[8:]
    _S10B = bytes.fromhex('0c000000000000000000000505')
    _S10C = bytes.fromhex('0c00000028')
    _S11 = bytes.fromhex('b725b047481e010013282828292a2a2b2c2d2e2f303132333334353638')[8:]
    _S15 = bytes.fromhex('b725b047481e0100ffffffff0000000014000800ffff0000e907081fffff000000000000000000006a01fa010500000000000000000000000000000003000000ffff0000000000000000000000000000e907081fffff0000000000000000000008402c000100000000000000000000000000000003')[8:]
    _S15_LOAN = bytes.fromhex('ffffffff0000000014000400ffff0000e907081fffff00000000000000000000068019000200000000000000000000000000000003000000ffff0000000000000000000000000000ffff0000ffff00000000000000000000ffffffff0000000000000000000000000000000000')
    _S16_LOAN = bytes.fromhex('ffffff001b000000e907081f03000000ff000000000000000a000000ffffffffffff0000ffffffff11002090a2b70200ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')

    def _slot_plan(self, tag, pid, fee, date, loan=False, rec116=None, mycode=None, posv=None):
        """Vraca listu (offset, bytes) upisa u po-slotne tablice za novog igraca; baca ValueError ako struktura nije ocekivana."""
        d = self.d
        pair = struct.pack('<II', tag, pid)
        ds = struct.pack('<I', date)
        fu = fee // 100
        W = []

        def empty_pair(o):
            return d[o] == 0xff and d[o + 1] == 0xff

        sq = {bytes(d[self.club_offset() + self.PAIR_OFF + 8 * k:self.club_offset() + self.PAIR_OFF + 8 * k + 8]) for k in range(self._squad_len(self.club_offset()))}

        def is_empty(o):
            return empty_pair(o) or not any(d[o:o + 8])

        def anchor(ref, stride, what):
            """red iza zadnjeg reda s parom igraca mog sastava (tablice sa 'po-igracu' redovima)"""
            lo = max(0, ref - 80 * stride)
            o = lo
            last = None
            while o <= ref + 3 * stride:
                if bytes(d[o:o + 8]) in sq:
                    last = o
                o += stride
            if last is None:
                raise ValueError('table %s: none of your players (unknown start)' % what)
            o = last + stride
            while not is_empty(o):
                o += stride
                if o > ref + 40 * stride:
                    raise ValueError('table %s: no empty row' % what)
            return last, o

        # S1: log (24 B)
        last1, o1 = anchor(Y(12477032), 24, 'S1')
        W.append((o1, pair + (rec116 if (loan and rec116) else bytes.fromhex('01509c5c64090000')) + ds + b'\0\0\0\0'))

        def fwd(ref, stride, payload, what, first=None):
            try:
                _, o = anchor(ref, stride, what)
            except ValueError:
                if first is None:
                    raise
                # tablica-popis (transferi) je u novoj karijeri prazna: nema mog igraca kao sidra, novi red ide na prvi prazan red od pocetka tablice
                o = first
                for _k in range(400):
                    if is_empty(o):
                        break
                    o += stride
                else:
                    raise ValueError('table %s: no empty row' % what)
            W.append((o, pair + payload))
            return o
        fwd(Y(13292344), 108, b'', 'S14a')
        fwd(Y(13283940), 108, b'', 'S14b', first=Y(13283940) - 2 * 108)
        fwd(Y(13297940), 108, b'', 'S14c')
        if not loan:
            fwd(Y(12611968), 8, b'', 'S9', first=Y(12611968) - 3 * 8)
        fwd(Y(12609332), 44, b'\0' * 36, 'S8')
        o = fwd(Y(13106960), 52, struct.pack('<I', 6), 'S12')
        W.append((o + 40, b'\0'))
        o = fwd(Y(13108296), 52, b'', 'S13', first=Y(13108296) - 2 * 52)
        W.append((o + 32, struct.pack('<i', -fu) + b'\1'))
        o = fwd(Y(12935116), 368, self._S10A, 'S10')
        W.append((o + 248, self._S10B))
        W.append((o + 344, self._S10C))
        fwd(Y(13094164), 192, self._S11, 'S11')
        s15 = self._S15.replace(bytes.fromhex('e907081f'), ds)
        if loan:
            s15 = self._S15_LOAN.replace(bytes.fromhex('e907081f'), ds).replace(bytes.fromhex('06801900'), struct.pack('<I', mycode))
        fwd(Y(17242312), 5628, s15, 'S15')
        # liste 12 B (par + broj): prvi prazan red
        for start, val in ((Y(12487240), 7 if loan else 5), (Y(12585188), 6 if loan else 4)):
            for k in range(60):
                o = start + 12 * k
                if empty_pair(o):
                    W.append((o, pair + struct.pack('<I', val)))
                    break
            else:
                raise ValueError('list is not in the expected form')
        # S6: povijest (20 B) - novi na pocetak, ostali dolje
        H = Y(12588388)
        rows = []
        k = 0
        while not empty_pair(H + 20 * k):
            rows.append(bytes(d[H + 20 * k:H + 20 * k + 20]))
            k += 1
            if k > 60:
                raise ValueError('history is not in the expected form')
        if not empty_pair(H + 20 * (k + 1) - 20 + 20):
            pass
        newrow = pair + ds + struct.pack('<I', fu) + (b'\3\0\0\0' if loan else b'\1\0\0\0')
        W.append((H, newrow + b''.join(rows)))
        # S7: poredano silazno po oznaci kluba, 24 B redovi, prazni na vrhu
        F = Y(12607428)
        while not empty_pair(F - 24) and F > Y(12606000):
            F -= 24
        k = 0
        while not empty_pair(F + 24 * k) and k < 80:
            if d[F + 24 * k + 4:F + 24 * k + 8] == b'\0\0\0\0':
                break
            k += 1
        # prvi popunjeni red = F (u ovom savea); ostali slijede dok oznaka ne pada na 0xffff/nulu
        rows = []
        k = 0
        while True:
            o = F + 24 * k
            if empty_pair(o) or not any(d[o:o + 8]) or k > 60:
                break
            rows.append(bytes(d[o:o + 24]))
            k += 1
        # povlaci i zadnji red posebne strukture
        if rows and rows[-1][8:12] == b'\x02\0\x02\0':
            pass
        ins = pair + struct.pack('<H', 0x28) + b'\0' * 14
        pos = 0
        while pos < len(rows) and struct.unpack_from('<I', rows[pos], 0)[0] > tag:
            pos += 1
        newrows = rows[:pos] + [ins] + rows[pos:]
        # jedan prazan red na vrhu se troši: ispis redova pocinje 24 B ranije
        top = F - 24
        if not empty_pair(top):
            raise ValueError('no empty row in S7')
        if not loan:
            W.append((top, b''.join(newrows)))
        else:
            W.append((top, ins))
        # S2: sortirana lista (16 B): nakon zadnjeg igraca mog kluba ubaci razdjelnik + novog
        R = Y(12056764)
        rr = []
        k = 0
        while k < 40:
            rr.append(bytes(d[R + 16 * k:R + 16 * k + 16]))
            k += 1
        st = set(self._s2_stale())
        if st:
            padr = next((r for r in rr if r[:2] == b'\xff\xff'), b'\xff\xff\0\0\0\0\0\0\0\0\0\0\xc7\0\0\0')
            rr = [r for k, r in enumerate(rr) if k not in st]
            rr += [padr] * (40 - len(rr))
        last = bytes(d[last1:last1 + 8])
        ix = [i for i, r in enumerate(rr) if r[:8] == last]
        if not ix:
            raise ValueError('S2: last player is not in the list')
        i = ix[0] + 1
        if not (rr[-1][:2] == b'\xff\xff' and rr[-2][:2] == b'\xff\xff'):
            # igra sama gura "ostatak" (redovi cijih igraca nema u mom sastavu) s kraja liste: zadnja dva reda tog ostatka se ukidaju
            sqs = {p_ for p_ in self.squad_ids() if p_}
            padr = next((r for r in rr if r[:2] == b'\xff\xff'), b'\xff\xff\0\0\0\0\0\0\0\0\0\0\xc7\0\0\0')
            for j in (len(rr) - 1, len(rr) - 2):
                if j > ix[0] and rr[j][:2] != b'\xff\xff' and struct.unpack_from('<I', rr[j], 4)[0] not in sqs:
                    rr[j] = padr
        if not (rr[-1][:2] == b'\xff\xff' and rr[-2][:2] == b'\xff\xff'):
            raise ValueError('S2: no room')
        ins = [rr[0], pair + (b'\0\0\0\0\xc2\0\0\0' if loan else b'\0\0\0\0\xc1\0\0\0')]
        rr2 = (rr[:i] + ins + rr[i:])[:40]
        W.append((R, b''.join(rr2)))
        if loan:
            # S16: 80 B redovi (sazetak potpisa/posudbi), par igraca na +40; posudba: tip 0x1b, 3
            S16 = Y(12488832)
            last = None
            for k in range(-1, 31):
                o = S16 + 80 * k
                if struct.unpack_from('<I', d, o + 4)[0] not in (0xff, 0):
                    last = k
            k = 0 if last is None else last + 1
            o = S16 + 80 * k
            if struct.unpack_from('<I', d, o + 4)[0] != 0xff:
                raise ValueError('S16: no empty row')
            row = bytearray(d[o:o + 80])
            row[4:72] = self._S16_LOAN[4:72]
            struct.pack_into('<I', row, 8, date)
            struct.pack_into('<I', row, 24, posv if posv is not None else 10)
            row[40:48] = pair
            W.append((o, bytes(row)))
        return W

    @property
    def _X_H(self):
        return X(0x246cd74)
    _X_S15 = bytes.fromhex('0d00190000000000d4060800ffff0000ea07071dffff00000000000000000000004019000500000000000000000000000000000003000000ffff0000000000000000000000000000ea07071dffff000000000000000000000d0019000100000000000000000000000000000003')
    _X_S15L = bytes.fromhex('ffffffff0000000014000400ffff0000ea07081bffff000000000000000000000d0019000200000000000000000000000000000003000000ffff0000000000000100000000000000ffff0000ffff00000000000000000000ffffffff0000000000000000000000000000000000000000ffff000000000000')
    @property
    def _X_S8B(self):
        return X(0x2474f94)
    _X_FIRSTEMPTY_MAX = 39

    def _s1_free60(self):
        """pc204: 60 MB: slobodan red S1 (24 B, 40 mjesta). Red koji je igra oslobodila ima ffff na pocetku; redovi koje klub jos nikad
        nije koristio su sve nule (Arsenal 2025 i 2027, PAOK: iza zadnjeg igraca nule, ostale tablice ffff). Prvo ffff, inace prvi nulti red."""
        d = self.d
        base = X(0x24517d8)
        for k in range(40):
            if d[base + 24 * k] == 0xff and d[base + 24 * k + 1] == 0xff:
                return k
        for k in range(40):
            if not any(d[base + 24 * k:base + 24 * k + 24]):
                return k
        return None

    @property
    def game27(self):
        """pc264: save iz Football Life 2027 (header.dat u dekriptiranoj mapi nosi verziju igre)."""
        g = getattr(self, '_game27', None)
        if g is None:
            try:
                g = b'Football Life 2027' in open(os.path.join(self.folder, 'header.dat'), 'rb').read()
            except Exception:
                g = False
            self._game27 = g
        return g

    @property
    def beta_ok(self):
        """pc239: beta pisanje (kupnja, prodaja, liste, produljenja, juniori, budzet, AI potezi): 60 MB format i prosireni format
        kojem sidra karijere ne odgovaraju, ali je niz zlib dijelova nadjen i cijeli srednji blok ima JEDAN pomak (npr. Michele, UML 45 MB,
        -373760 B). Logika upisa je ista kao na izmjerenom 45 MB formatu, samo s pomaknutim tablicama; _guard_extended i dalje vrijedi."""
        if not self.ext:
            return False
        if self.game27:
            return False   # pc264: Football Life 2027: nijedan upis dok raspored tablica nije izmjeren na pravim FL27 saveovima
        if self.dxa != self.dx:
            return True
        return (not self.layout_ok) and str(getattr(self, 'layout_note', '')).startswith('new save layout')

    @property
    def fmt60(self):
        """60 MB format (FL Mod Studio 0.2.2+: 2.400 klubova): prednji i straznji dio srednjeg bloka imaju razlicit pomak."""
        return bool(self.ext and self.dxa != self.dx)

    def _comp_block(self, big):
        """+64..+88 zapisa igraca: 6 x (u16 id natjecanja, u16 kod), ffff0000 = prazno. Novi igrac (izmjereno na 60 MB: Dibango,
        Kal, Ibraimi; 45 MB juniori: 05 c002, 11, 17) dobije SORTIRANI skup natjecanja svojih suigraca + jedan unos s kodom c002
        (60 MB: id 3, 45 MB: id 5) ako ga suigraci nemaju."""
        sq = set(self.squad_ids())
        ent = {}
        for k in range((len(big) - 144) // 156):
            r = 144 + 156 * k
            if struct.unpack_from('<I', big, r + 48)[0] in sq:
                for j in range(6):
                    cid, code = struct.unpack_from('<HH', big, r + 64 + 4 * j)
                    if cid != 0xffff:
                        ent.setdefault(cid, code)
        if not ent:
            return None
        if 0x02c0 not in ent.values():
            ent.setdefault(3 if self.fmt60 else 5, 0x02c0)
        items = sorted(ent.items())[:6]
        out = b''.join(struct.pack('<HH', c, v) for c, v in items)
        return out + b'\xff\xff\0\0' * (6 - len(items))

    def _s2_list(self):
        """Lista S2 (16 B: tag, id, 0, tip c0 svoj / c1 potpisan / c2 posudba / c3 prodan). U saveu su 3 kopije u razmaku 0x7e4
        (ref 0x23eb0cc, 0x23eb8b0, 0x23ec094). 45 MB: igra mijenja drugu (S2_R, izmjereno). 60 MB: igra mijenja TRECU
        (izmjereno: PAOK Dibango, Arsenal Zubimendi/Porter/Nongo/Ibraimi/Kal), prve dvije ostaju."""
        if not self.fmt60:
            return self.S2_R
        d = self.d
        my = self.club_offset()
        first = bytes(d[my + self.PAIR_OFF:my + self.PAIR_OFF + 8])
        # pc204: nova karijera (Arsenal 4.8.2025, tester) ima popunjenu samo PRVU kopiju (druge dvije: ffff, c7) ->
        # zadnja kopija koja pocinje prvim igracem momcadi (3. kad postoji, kao u izmjerenim uzorcima)
        for o in (self.S2_R + 0x7e4, self.S2_R, self.S2_R - 0x7e4):
            if bytes(d[o:o + 8]) == first and d[o + 12] in (0xc0, 0xc1, 0xc2, 0xc3):
                return o
        raise ValueError('S2: squad list not found (60 MB format)')

    def sign_outside_x(self, pid, fee, salary, end_year, number=None, pos=None, loan_end=None, free=False, release=0):
        """Potpis igraca iz drugog kluba (naknada fee EUR, placa salary EUR/god) na prosirenom 45 MB formatu.
        Sadrzaj izmjeren na pravom potpisu u igri (slot = prvi prazan red u S8, S14/L5/L4/S2 se dodaju na kraj).
        free=True: slobodan igrac (zapis igraca bez kluba, +140 = ffffffff). EKSPERIMENT, nije izmjereno na pravom potpisu
        slobodnog igraca u igri: isti upis kao potpis iz kluba, bez naknade i bez diranja ijednog drugog sastava (reprezentacija ostaje)."""
        if self.ext and self.game27:
            if free and not loan_end:
                if not self.FL27_FREE_OK:
                    raise ValueError('Signing free agents is not unlocked yet on Football Life 2027 saves; do it in the game. The save was not touched.')
                return self._free_fl27(pid, salary, end_year, release)   # pc278: slobodni igrac kao dogovor u igri
            raise ValueError('Signing this way is not unlocked yet on Football Life 2027 saves; do it in the game. The save was not touched.')
        if not (self.fmt60 and free and not loan_end):
            self.pid_guard(pid)   # pc250
        if self.fmt60 and free and not loan_end:
            # pc235: 60 MB slobodni igrac (izvjestaj testera papandreas5, 30.10.): app samo upise dogovor i dolazak za sutra,
            # igra sama obavi dolazak. Beta, ukljucuje se u config.json ("free60_beta": true); inace ostaje zakljucano.
            if not getattr(self, '_free60_ok', False):
                raise ValueError('Signing free agents is not unlocked yet on the 60 MB format (beta, off). The save was not touched.')
            import fl26_freeagent60 as _fa60
            _fa60.queue_new_agreement(self, sys.modules[__name__], pid, salary, end_year, release)
            self._beta_write = True
            return 'Free-agent agreement queued for %d; load the career and advance one day for his arrival.' % pid
        if not self.ext:
            if free and not loan_end:
                return self.classic_join(pid, 'fa', salary, end_year, number)
            raise ValueError('only works on the verified (45 MB) format')
        d = self.d
        my = self.club_offset()
        n = self._squad_len(my)
        if n >= 40:
            raise ValueError('squad is full (40)')
        if pid in self.my_squad_tags():
            raise ValueError('player is already in your club')
        if free:
            fee = 0
            if loan_end:
                raise ValueError('slobodan igrac se ne posuduje')
            if self._free_code(pid) != 0xffffffff:
                raise ValueError('player is not a free agent (has a club)')
            src = None
        else:
            src = self.find_club_of(pid)
            if not src:
                raise ValueError('player is not in any club')
        f = fee // 100
        if src:
          so, si = src
          if so == my:
            raise ValueError('player is already in your club')
          sn = self._squad_len(so)
          if sn <= 18:
            raise ValueError('source club would be too small')
        b = struct.unpack_from('<I', d, self.BUDGET)[0]
        if f > b:
            raise ValueError('not enough money in the transfer budget')
        pos = pos or {}
        if src:
          sidx = self.club_idx_of_offset(so)
          lo = self.TAC0 + 600 * sidx + 484
          L = [int(x) for x in d[lo:lo + sn]]
          ids = [struct.unpack_from('<I', d, so + self.PAIR_OFF + 8 * k + 4)[0] for k in range(sn)]
          # pc189: popis sastava moze biti kraci od momcadi (60 MB PAOK 2027: 23 mjesta + ff, momcad 31); tada igrac izvan
          # popisa ne mijenja popis (izmjereno: igra pri kupnji Dibanga nije dirala popis prodajnog kluba)
          nv = L.index(0xff) if 0xff in L else len(L)
          if sorted(L[:nv]) != list(range(nv)) or any(x != 0xff for x in L[nv:]):
            raise ValueError('source club lineup is not in the expected form')
          if si not in L[:nv] or self.fmt60:
            L = None   # 60 MB: igra pri kupnji (Dibango) nije dirala popis prodajnog kluba
        if src and L is not None:
          j = L.index(si)
          if j < 11:
            gk_out = pos.get(pid, 5) == 0
            cand = [k for k in range(11, sn) if k != j and L[k] != si]
            best = [k for k in cand if (pos.get(ids[L[k]], 5) == 0) == gk_out]
            if not best:
                raise ValueError('no replacement in the source club lineup')
            k = best[0]
            L[j] = L[k]
            del L[k]
          else:
            del L[j]
          L = [x - 1 if x > si else x for x in L if x != 0xff]
          L += [0xff] * (sn - len(L))
        tag = self.player_tag(pid)
        pair = struct.pack('<II', tag, pid)
        date = self.game_date_code()
        ds = struct.pack('<I', date)
        mycode = self.my_club_code()
        sq = {bytes(d[my + self.PAIR_OFF + 8 * k:my + self.PAIR_OFF + 8 * k + 8]) for k in range(n)}
        # ---- slot: prvi prazan red u S8
        slot = None
        for k in range(self._X_FIRSTEMPTY_MAX):
            o = self._X_S8B + 44 * k
            if d[o] == 0xff and d[o + 1] == 0xff:
                slot = k
                break
        if slot is None:
            raise ValueError('no free slot in the tables; release a player in the game and try again')
        W = []
        # Svaka tablica ima svoj red (izmjereno 15.10. na pravom potpisu u igri, Tripaldelli, nakon posudbi i prodaja):
        # S8/S12/S15/S10/S11 = prvi prazan (ffff) red svake tablice posebno; S1 = red iza zadnjeg zauzetog (rupe prodanih se ne pune).
        # U cistoj karijeri sve to pada na isti indeks (stari model 'slot').
        def first_ff(base, st, n, nm):
            for k in range(n):
                o = base + st * k
                if d[o] == 0xff and d[o + 1] == 0xff:
                    return k
            raise ValueError('table %s: no empty row' % nm)
        try:
            i12 = first_ff(X(0x24ee690), 52, 40, 'S12')
        except ValueError:
            # registar igraca kluba ima 40 mjesta i u njega se broje i igraci posudjeni van
            lo = len([1 for k in range(40) if struct.unpack_from('<I', d, X(0x24ee690) + 52 * k + 8)[0] == 0 and struct.unpack_from('<I', d, X(0x24ee690) + 52 * k + 4)[0]])
            raise ValueError('The squad register in the save is full: 40 players, %d of them out on loan. '
                             'Sell or release a player before signing a new one through the app.' % lo)
        i10 = first_ff(X(0x24bf54c), 368, 120, 'S10')
        i11 = first_ff(X(0x24e8c84), 192, 120, 'S11')
        i15 = first_ff(X(0x28b886c), 5628, 60, 'S15')
        i1 = None
        for k in range(80):
            o = X(0x24517d8) + 24 * k
            if not (d[o] == 0xff and d[o + 1] == 0xff) and any(d[o:o + 8]):
                i1 = k
        i1 = 0 if i1 is None else i1 + 1
        if self.fmt60:
            # pc189 (60 MB, izmjereno na Dibangu): igra puni PRVI prazan red S1 (isti indeks kao mjesto u S8)
            i1 = self._s1_free60()
            if i1 is None:
                raise ValueError('S1: no empty row')
        if any(d[X(0x24517d8) + 24 * i1:X(0x24517d8) + 24 * i1 + 8]) and not (d[X(0x24517d8) + 24 * i1] == 0xff and d[X(0x24517d8) + 24 * i1 + 1] == 0xff):
            raise ValueError('S1: no empty row')
        o8 = self._X_S8B + 44 * slot
        W.append((o8, pair + b'\0' * 36))
        # +8..16: 8 B iz zapisa igraca (+116) -> dodaje se nize
        o1 = X(0x24517d8) + 24 * i1
        o = X(0x24ee690) + 52 * i12
        W.append((o, pair + struct.pack('<I', 0x1a if loan_end else 6)))
        o13 = X(0x24ef0dc)
        for _k in range(60):
            o13 += 52
            if d[o13] == 0xff and d[o13 + 1] == 0xff:
                break
        else:
            raise ValueError('S13: no empty row')
        W.append((o13, pair))
        W.append((o13 + 32, struct.pack('<i', -f) + (b'\2\0\0\0' if loan_end else b'\1\0\0\0')))
        o = X(0x24bf54c) + 368 * i10
        W.append((o, pair + self._S10A))
        W.append((o + 248, self._S10B))
        W.append((o + 344, self._S10C))
        o = X(0x24e8c84) + 192 * i11
        W.append((o, pair + self._S11))
        o15 = X(0x28b886c) + 5628 * i15

        def empty(o):
            return (d[o] == 0xff and d[o + 1] == 0xff) or not any(d[o:o + 8])

        def seq(name, ref, st):
            last = None
            for k in sorted(range(-70, 70), key=abs):
                oo = ref + st * k
                if oo > 0 and bytes(d[oo:oo + 8]) in sq:
                    last = oo
                    break
            if last is None:
                if name not in ('L5', 'L4'):
                    raise ValueError('table %s: your players are not where expected' % name)
                # popis (L5/L4) je u novoj karijeri bez tvojih igraca: nema sidra, novi red ide na prvi prazan red od izmjerenog pocetka
                oo = ref
                for _k in range(200):
                    if empty(oo):
                        return oo
                    oo += st
                raise ValueError('table %s: no empty row' % name)
            while bytes(d[last + st:last + st + 8]) in sq:
                last += st
            oo = last + st
            for _k in range(80):
                if empty(oo):
                    return oo
                oo += st
            raise ValueError('table %s: no empty row' % name)
        W.append((seq('S14a', X(0x251c434), 108), pair))
        W.append((seq('S14c', X(0x251da10), 108), pair))
        o14 = self._PR_S14B
        for _k in range(80):
            if empty(o14):
                break
            o14 += 108
        W.append((o14, pair))
        if not loan_end:
            o9 = self._PR_REF['S9'][0]
            for _k in range(80):
                if empty(o9):
                    break
                o9 += 8
            W.append((o9, pair))
        W.append((seq('L5', X(0x24542c4), 12), pair + struct.pack('<I', 7 if loan_end else 5)))
        W.append((seq('L4', X(0x246c13c), 12), pair + struct.pack('<I', 6 if loan_end else 4)))
        # S2: red ide na kraj svoje grupe (po tipu c1 potpisani / c2 posudjeni), redovi iza se pomicu dolje
        R2 = self._s2_list() if self.fmt60 else self.S2_R
        rr2 = [bytes(d[R2 + 16 * k:R2 + 16 * k + 16]) for k in range(48)]
        tt = 0xc2 if loan_end else 0xc1
        if self.fmt60:
            # 60 MB: novi red ide iza zadnjeg reda igraca koji je jos u momcadi (otisli c2/c3 ostaju na kraju), bez obzira na tip
            ip = next((i for i, r_ in enumerate(rr2) if r_[:2] == b'\xff\xff' or r_[:8] not in sq), None)
        else:
            ip = next((i for i, r_ in enumerate(rr2) if r_[12] > tt or r_[:2] == b'\xff\xff'), None)
        if ip is None:
            raise ValueError('S2: no room')
        rr2.insert(ip, pair + b'\0\0\0\0' + bytes([tt]) + b'\0\0\0')
        W.append((R2, b''.join(rr2[:48])))
        # S6 povijest
        H = self._X_H
        rows, k = [], 0
        while not (d[H + 20 * k] == 0xff and d[H + 20 * k + 1] == 0xff):
            rows.append(bytes(d[H + 20 * k:H + 20 * k + 20]))
            k += 1
            if k > 60:
                raise ValueError('S6: history is not in the expected form')
        W.append((H, pair + ds + struct.pack('<I', f) + (b'\3\0\0\0' if loan_end else b'\1\0\0\0') + b''.join(rows)))
        # S7: redovi (24 B) poredani silazno po oznaci; otpusteni igrac ostavlja prazan red, novi ide u njega na mjestu
        F = Y(12607428)
        F = F - 24 * ((F - X(0x2474a00)) // 24)

        def valid(o):
            v = struct.unpack_from('<I', d, o + 4)[0]
            return 1000 < v < 400000
        top = None
        for k in range(0, 120):
            if valid(F + 24 * k):
                top = F + 24 * k
                break
        if top is None:
            raise ValueError('S7: table not found')
        rows, k, hole, bad = [], 0, None, 0
        while k < 90:
            o = top + 24 * k
            if valid(o):
                bad = 0
                rows.append((o, bytes(d[o:o + 24])))
            else:
                bad += 1
                if bad >= 3:
                    break
                if hole is None:
                    hole = o
            k += 1
        ins = pair + (struct.pack('<H', 0x28) + struct.pack('<H', 0x8cf7) if loan_end else struct.pack('<H', 0x1e) + struct.pack('<H', 0x063e)) + b'\0' * 12
        last_o = rows[-1][0]
        holes_ = [o_ for o_ in range(top, last_o, 24) if not valid(o_)]
        if holes_:
            hole = holes_[-1]
        if self.fmt60:
            # pc189 (60 MB, izmjereno na Dibangu): igra prepise PRVI red liste (onaj s datumom 4 B ispred) i stavi danasnji datum
            W.append((top, ins))
            W.append((top - 4, ds))
        elif hole is not None and hole < last_o:
            W.append((hole, ins))
        else:
            p = 0
            while p < len(rows) and struct.unpack_from('<I', rows[p][1], 0)[0] > tag:
                p += 1
            rr = [r for _o, r in rows]
            if valid(top - 24) or not (d[top - 24] == 0xff and d[top - 24 + 1] == 0xff):
                raise ValueError('S7: no empty row')
            W.append((top - 24, b''.join(rr[:p] + [ins] + rr[p:])))
        # ---- zapis igraca (zlib)
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        srccode = struct.unpack_from('<I', big, r + 140)[0]
        rec116 = bytes(big[r + 116:r + 124])
        W.append((o1, pair + rec116 + ds + b'\0\0\0\0'))
        s15 = self._X_S15.replace(bytes.fromhex('ea07071d'), ds).replace(bytes.fromhex('0d001900'), struct.pack('<I', mycode)).replace(bytes.fromhex('00401900'), struct.pack('<I', srccode))
        if loan_end:
            s15 = self._X_S15L.replace(bytes.fromhex('ea07081b'), ds).replace(bytes.fromhex('0d001900'), struct.pack('<I', mycode))
        W.append((o15, pair + s15))
        if loan_end:
            # posudba: igrac ostaje ugovorom kod vlasnika; +136 = +140 = kod kluba vlasnika, +152 = kraj posudbe (kao posudjeni igraci u savu)
            big[r + 72:r + 80] = bytes.fromhex('0500c002ffff0000')
            big[r + 116] = 0
            big[r + 136:r + 140] = big[r + 140:r + 144]
            struct.pack_into('<I', big, r + 152, loan_end)
            end = struct.unpack_from('<I', big, r + 144)[0]
        elif self.fmt60:
            # 60 MB (Dibango, izmjereno): natjecanja kluba u +64..+88, +136 = kod prodajnog kluba, +140 ostaje
            cb = self._comp_block(big)
            if cb:
                big[r + 64:r + 88] = cb
            struct.pack_into('<I', big, r + 128, salary // 100)
            struct.pack_into('<I', big, r + 136, srccode)
            end = (31 << 24) | (8 << 16) | end_year
            struct.pack_into('<I', big, r + 144, end)
            struct.pack_into('<I', big, r + 148, date)
        else:
            big[r + 72:r + 80] = bytes.fromhex('0500c002ffff0000')
            struct.pack_into('<I', big, r + 128, salary // 100)
            struct.pack_into('<I', big, r + 136, 0xffffffff)
            struct.pack_into('<I', big, r + 140, mycode)
            end = (31 << 24) | (8 << 16) | end_year
            struct.pack_into('<I', big, r + 144, end)
            struct.pack_into('<I', big, r + 148, date)
        new, p0 = [], 0
        for c in chunks:
            new.append(bytes(big[p0:p0 + len(c)]))
            p0 += len(c)
        # ---- brojevi, sastav, izvorni klub
        used = {struct.unpack_from('<H', d, my + self.NUM_OFF + 2 * k)[0] for k in range(n)}
        if number is None:
            number = next(x for x in range(2, 100) if x not in used)
        elif number in used or not (1 <= number < 100):
            raise ValueError('shirt number is taken')
        blo = self.TAC0 + 600 * self.MY_TIDX + 484
        BL = [int(x) for x in d[blo:blo + n]]
        self._allow = [(self.CH0 - 4, end_), (self.BUDGET, self.BUDGET + 4)] + [(o, o + len(bb)) for o, bb in W]
        # pc189: 60 MB format - kupnja iz kluba je beta (pravila izmjerena na jednom pravom transferu u igri); ostalo ostaje zakljucano
        self._beta_write = bool(self.beta_ok and not loan_end)   # pc240: slobodni igrac na 45 MB obitelji (isti upis kao 45 MB); 60 MB slobodni ide ranije kroz fl26_freeagent60
        for o, bb in W:
            d[o:o + len(bb)] = bb
        self._rebuild(new, end_)
        try:
            self._xfer_append(end_, tag, pid, mycode, srccode, 0 if loan_end else f, date)
        except Exception:
            pass
        if src:
          for k in range(si, sn - 1):
            a = so + self.PAIR_OFF + 8 * k
            d[a:a + 8] = d[a + 8:a + 16]
            a = so + self.NUM_OFF + 2 * k
            d[a:a + 2] = d[a + 2:a + 4]
          struct.pack_into('<II', d, so + self.PAIR_OFF + 8 * (sn - 1), 0xffff, 0)
          struct.pack_into('<H', d, so + self.NUM_OFF + 2 * (sn - 1), 0)
          if L is not None:
              d[lo:lo + sn] = bytes(L)
          d[so + 1058] = sn - 1
        struct.pack_into('<II', d, my + self.PAIR_OFF + 8 * n, tag, pid)
        struct.pack_into('<H', d, my + self.NUM_OFF + 2 * n, number)
        if sorted(BL) == list(range(n)):
            d[blo + n] = n
        d[my + 1058] = n + 1
        struct.pack_into('<I', d, self.BUDGET, b - f)
        if not loan_end:
            self._join_tail(tag, pid, salary // 100, end)   # pc207: red ugovora + popis igraca u repu (kao igra)
        try:
            if not loan_end:
                self._sync_tail([pid], {pid: (salary // 100, end)})
        except Exception:
            pass
        # igrac dolazi s oznakama liste iz starog kluba (Bedja 14.10. stigao na transfer listi i listi posudbi): novi igrac nije na listama
        try:
            fl = Save.flag_map(self.d).get(pid, (False, False))
            if fl[0] or fl[1]:
                self.set_flags(pid, tl=False, loan=False)
        except Exception:
            pass
        if loan_end:
            return 'posudjen %d (broj %d, slot %d, naknada %d EUR)' % (pid, number, slot, fee)
        if free:
            return 'potpisan slobodan igrac %d (broj %d, slot %d)' % (pid, number, slot)
        return 'potpisan %d (broj %d, slot %d, naknada %d EUR)' % (pid, number, slot, fee)

    def _free_code(self, pid):
        """Kod kluba iz zapisa igraca (+140); ffffffff = bez kluba (slobodan)."""
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        i = self._bf(big, struct.pack('<I', pid))
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                return struct.unpack_from('<I', big, i - 48 + 140)[0]
            i = self._bf(big, struct.pack('<I', pid), i + 1)
        return None

    def free_agents(self):
        """{pid: (kraj_ugovora_kod, kod)} igraca bez kluba u spremljenoj bazi (+140 = ffffffff) koji nisu ni u jednom klupskom sastavu."""
        if self.fmt60:
            # pc235: puni kljuc (tag, PID), PID-ovi s vise slobodnih igraca se preskacu (izvjestaj testera 03)
            try:
                from fl26_freeagent60 import free_catalog
                return {pid: item[1] for pid, item in free_catalog(self).items()}
            except Exception:
                pass
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        out = {}
        for k in range((len(big) - 144) // 156):
            o = 144 + 156 * k
            pid = struct.unpack_from('<I', big, o + 48)[0]
            if 0 < pid < 400000 and struct.unpack_from('<I', big, o + 140)[0] == 0xffffffff:
                out[pid] = struct.unpack_from('<I', big, o + 144)[0]
        return out

    def repair_slot(self, pid, fee=0):
        """Popravlja igraca koji je u sastavu, ali nema redove u po-slotnim tablicama (prazan red u Squad Listi)."""
        my = self.club_offset()
        n = self._squad_len(my)
        tags = {struct.unpack_from('<I', self.d, my + self.PAIR_OFF + 8 * k + 4)[0]: struct.unpack_from('<I', self.d, my + self.PAIR_OFF + 8 * k)[0] for k in range(n)}
        if pid not in tags:
            raise ValueError('player is not in your squad')
        tag = tags[pid]
        plan = self._slot_plan(tag, pid, fee, self.game_date_code())
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        if big[r + 64] >= 100 or big[r + 64] == 0x4f:
            big[r + 64] = 17 if big[r + 64] in (0x4f,) or big[r + 64] >= 100 else big[r + 64]
        big[r + 68] = 23
        big[r + 116] = 0
        big[r + 136:r + 140] = bytes.fromhex('6a01fa01')
        new, pos = [], 0
        for c in chunks:
            new.append(bytes(big[pos:pos + len(c)]))
            pos += len(c)
        self._rebuild(new, end_)
        for o, bts in plan:
            self.d[o:o + len(bts)] = bts
        return 'fixed row for %d' % pid

    def direct_sign(self, pid, fee, salary, end, pos=None, loan=False, rec116=None, mycode=None, posv=None):
        """EKSPERIMENT: igrac dolazi u tvoj klub BEZ zamjene slota: izvorni klub ga gubi (postava + brojevi, kao ai_move),
        tvoj klub ga dobiva na kraj sastava (broj dresa, kraj postave), zapis igraca (placa, ugovor, datum) i transfer budzet."""
        self.pid_guard(pid)   # pc250
        if self.ext:
            if loan:
                raise ValueError('loans from the app are not supported yet on the extended format')
            return self.sign_outside_x(pid, fee, salary, end & 0xffff, pos=pos)
        my = self.club_offset()
        if pid in self.my_squad_tags():
            raise ValueError('player is already in your club')
        n = self._squad_len(my)
        if n >= 40:
            raise ValueError('squad is full')
        src = self.find_club_of(pid)
        if not src:
            raise ValueError('player is not in any club')
        so, si = src
        if so == my:
            raise ValueError('player is already in your club')
        sn = self._squad_len(so)
        if sn <= 18:
            raise ValueError('source club would be too small')
        pos = pos or {}
        sidx = self.club_idx_of_offset(so)
        lo = self.TAC0 + 600 * sidx + 484
        L = [int(x) for x in self.d[lo:lo + sn]]
        ids = [struct.unpack_from('<I', self.d, so + self.PAIR_OFF + 8 * k + 4)[0] for k in range(sn)]
        sshape, snv = self._lineup_shape(L, sn)
        if sshape is None:
            raise ValueError('source club lineup is not in the expected form')
        tag = self.player_tag(pid)
        L = L[:snv]
        if si in L:   # pc209: igrac izvan kraceg popisa: popis ostaje isti
            j = L.index(si)
            if j < 11:
                gk_out = pos.get(pid, 5) == 0
                cand = [k for k in range(11, len(L)) if k != j and L[k] != si]
                best = [k for k in cand if (pos.get(ids[L[k]], 5) == 0) == gk_out]
                if not best:
                    raise ValueError('no replacement in the source club lineup')
                k = best[0]
                L[j] = L[k]
                del L[k]
            else:
                del L[j]
            L = [x - 1 if x > si else x for x in L]
        L += [0xff] * (sn - len(L))
        # zapis igraca + budzet (bez diranja sastava, to radimo ovdje)
        msg = self.sign_player(pid, fee, salary, end=end, _old=False, _my=False, _num=False, _game=True)
        # izvorni klub: pomak ulijevo
        for k in range(si, sn - 1):
            a = so + self.PAIR_OFF + 8 * k
            self.d[a:a + 8] = self.d[a + 8:a + 16]
            a = so + self.NUM_OFF + 2 * k
            self.d[a:a + 2] = self.d[a + 2:a + 4]
        struct.pack_into('<II', self.d, so + self.PAIR_OFF + 8 * (sn - 1), 0xffff, 0)
        struct.pack_into('<H', self.d, so + self.NUM_OFF + 2 * (sn - 1), 0)
        self.d[lo:lo + sn] = bytes(L)
        self.d[so + 1058] = sn - 1
        # moj klub: na kraj sastava, slobodan broj, kraj postave (ako je postava valjana permutacija)
        struct.pack_into('<II', self.d, my + self.PAIR_OFF + 8 * n, tag, pid)
        used = {struct.unpack_from('<H', self.d, my + self.NUM_OFF + 2 * k)[0] for k in range(n)}
        num = next(x for x in range(2, 100) if x not in used)
        struct.pack_into('<H', self.d, my + self.NUM_OFF + 2 * n, num)
        midx = self.club_idx_of_offset(my)
        blo = self.TAC0 + 600 * midx + 484
        BL = [int(x) for x in self.d[blo:blo + n]]
        if sorted(BL) == list(range(n)):
            self.d[blo + n] = n
        plan = self._slot_plan(tag, pid, fee, self.game_date_code(), loan=loan, rec116=rec116, mycode=mycode, posv=posv)
        for o, bts in plan:
            self.d[o:o + len(bts)] = bts
        self.d[my + 1058] = n + 1
        if not loan:
            self._join_tail(tag, pid, None, None)   # pc206b: red ugovora + popis igraca u repu (kao igra)
        return 'direktno potpisan %d (broj %d), %s' % (pid, num, msg)

    def _into_xi(self, bidx, bo, bn, BL, pid, pos, ovr_of):
        """Novi igrac kupca ulazi u prvih 11 ako je bolji od najslabijeg igraca iste pozicije (uloga u formaciji) za >= 2 OVR.
        Zamijeni mjesta u postavi (permutacija ostaje valjana). Vraca True ako je usao."""
        newpos = (pos or {}).get(pid)
        if newpos is None:
            return False
        ids = [struct.unpack_from('<I', self.d, bo + self.PAIR_OFF + 8 * k + 4)[0] for k in range(bn + 1)]
        blo = self.TAC0 + 600 * bidx + 484
        roles = [int(x) for x in self.d[self.PLAN0 + 600 * bidx:self.PLAN0 + 600 * bidx + 10]]
        if any(r < 1 or r > 12 for r in roles):
            return False
        new_ovr = ovr_of(pid)
        if not new_ovr:
            return False
        if newpos == 0:
            slots = [0]
        else:
            slots = [i + 1 for i, r in enumerate(roles) if r == newpos]
        best = None
        for sl in slots:
            occ = ids[BL[sl]]
            o = ovr_of(occ) or 0
            if new_ovr >= o + 2 and (best is None or o < best[0]):
                best = (o, sl)
        if best is None and newpos != 0:
            # nema uloge iste pozicije u formaciji kluba: susjedna uloga, ali uz vecu prednost (igra izvan prirodne pozicije)
            ADJ = {8: (5, 11, 6, 7), 5: (4, 8), 4: (5,), 6: (9, 5), 7: (10, 5), 9: (6, 11, 12), 10: (7, 11, 12), 11: (8, 12, 9, 10), 12: (11, 9, 10)}
            near = ADJ.get(newpos, ())
            for sl in [i + 1 for i, r in enumerate(roles) if r in near]:
                occ = ids[BL[sl]]
                o = ovr_of(occ) or 0
                if new_ovr >= o + 3 and (best is None or o < best[0]):
                    best = (o, sl)
        if best is None:
            return False
        sl = best[1]
        j_new = bn
        a, b = self.d[blo + sl], self.d[blo + j_new]
        self.d[blo + sl], self.d[blo + j_new] = b, a
        return True

    XF_END = 296848          # zadnji red (36 B) tablice transfera u repu: FIFO od 100 redova, najnoviji na kraju

    def _xfer_append(self, e2, tag, pid, to_code, from_code, fee100, date):
        """Doda red u tablicu transfera u repu (FIFO, 100 redova x 36 B ending na rep+XF_END): redovi se pomaknu za jedan prema gore, najstariji ispada."""
        d = self.d
        base = e2

        def valid(o):
            return d[base + o + 24] >= 0xe9 and d[base + o + 25] == 7 and d[base + o + 8] != 0xff
        first = self.XF_END
        while valid(first - 36):
            first -= 36
        n = (self.XF_END - first) // 36 + 1
        if n < 50 or not valid(self.XF_END):
            return False
        self._allow = list(getattr(self, '_allow', [])) + [(base + first, base + self.XF_END + 36)]
        rows = [bytearray(d[base + first + 36 * k:base + first + 36 * k + 36]) for k in range(n)]
        old_last = rows[-1]
        struct.pack_into('<II', old_last, 28, 0, 0xffff)
        new = bytearray(36)
        struct.pack_into('<IIIIIIIII', new, 0, tag, pid, to_code, from_code, 0, fee100, date, 0xffff, 0xffffffff)
        rows = rows[1:] + [new]
        for k, r in enumerate(rows):
            d[base + first + 36 * k:base + first + 36 * k + 36] = r
        return True

    LOG0 = 55300            # tablica 60 B redova transfera u repu (uzorak: Dowman @55312)
    OPT0 = 151052           # opcija otkupa: 3 reda po 12 B u repu (uzorak: Dowman)

    def loan_in(self, pid, fee, end_code, option=None, pos=None, opt_row=True):
        """EKSPERIMENT: posudba IGRACA U MOJ KLUB (uzorci Dowman s opcijom, Valdimarsson bez). Igrac ostaje ugovorom kod vlasnika
        (zapis: samo +136 = kod vlasnika, +152 = kraj posudbe), dolazi na kraj mog sastava, naknada = fee u budzet/po-slotne tablice,
        red u tablici transfera u repu; s opcijom jos red u tablici ugovora (placa otkupa, release, kraj) i red opcije (cijena otkupa).
        option = dict(buy, wage, release, end) u EUR / kod datuma ili None."""
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        orig = bytes(big[r:r + 156])
        owner = struct.unpack_from('<I', orig, 140)[0]
        if owner == 0xffffffff or owner == 0:
            raise ValueError('player has no owning club')
        if struct.unpack_from('<I', orig, 136)[0] != 0xffffffff:
            raise ValueError('player is already on loan')
        sal = struct.unpack_from('<I', orig, 128)[0] * 100
        endc = struct.unpack_from('<I', orig, 144)[0]
        tag = struct.unpack_from('<I', orig, 44)[0]
        from collections import Counter
        cc = Counter()
        my = self.club_offset()
        for k in range(self._squad_len(my)):
            q = struct.unpack_from('<I', self.d, my + self.PAIR_OFF + 8 * k + 4)[0]
            ri = self._bf(big, struct.pack('<I', q))
            while ri >= 0 and not (ri >= 192 and (ri - 192) % 156 == 0):
                ri = self._bf(big, struct.pack('<I', q), ri + 1)
            if ri >= 0 and struct.unpack_from('<I', big, ri - 48 + 136)[0] == 0xffffffff:
                cc[struct.unpack_from('<I', big, ri - 48 + 140)[0]] += 1
        mycode = cc.most_common(1)[0][0] if cc else 0x198006
        pv = (pos or {}).get(pid)
        posv = 6 if pv == 0 else 10
        if self.ext:
            msg = self.sign_outside_x(pid, fee, sal, endc, pos=pos, loan_end=end_code)
        else:
            msg = self.direct_sign(pid, fee, sal, endc, pos=pos, loan=True, rec116=bytes(orig[116:124]), mycode=mycode, posv=posv)
        # zapis igraca: vrati original, samo posudba
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        big[r:r + 156] = orig
        # oblik kao kod posudbi iz baze igre (npr. Satpaev): +136 = klub vlasnik, +140 = klub u kojem igra (moj)
        big[r + 136:r + 140] = orig[140:144]
        # nativna posudba izvrsena u igri (Dowman): +136 = +140 = klub vlasnik (igra ga prikazuje u Other Teams)
        big[r + 140:r + 144] = orig[140:144]
        struct.pack_into('<I', big, r + 152, end_code)
        # oznake statusa igraca (parovi u16 id + u16 oznaka od +52): posudba = id 3 / 0x02c0 u prvi slobodni slot (uzorak Valdimarsson)
        ents = [struct.unpack_from('<H', big, r + 52 + 4 * k)[0] for k in range(13)]
        if 3 not in ents and 0xffff in ents:
            k = ents.index(0xffff)
            struct.pack_into('<HH', big, r + 52 + 4 * k, 3, 0x02c0)
        new, pos_ = [], 0
        for c in chunks:
            new.append(bytes(big[pos_:pos_ + len(c)]))
            pos_ += len(c)
        self._rebuild(new, end_)
        _, e2 = self._chunks()
        d = self.d
        done = ['zapis']
        # red u tablici transfera (60 B)
        last = None
        for k in range(-60, 61):
            o = e2 + self.LOG0 + 60 * k
            if bytes(d[o + 4:o + 8]) != b'\xff\xff\xff\xff':
                last = k
        k = 0 if last is None else last + 1
        o = e2 + self.LOG0 + 60 * k
        if k <= 60 and bytes(d[o + 4:o + 8]) == b'\xff\xff\xff\xff':
            struct.pack_into('<IIIIII', d, o + 4, owner, tag, pid, fee // 100, fee // 100, end_code)
            done.append('tablica transfera')
        if self._xfer_append(e2, tag, pid, mycode, owner, fee // 100, self.game_date_code()):
            done.append('povijest transfera')
        # popisi igraca vezanih uz klub (kljuc = donja 2 bajta oznake igraca): tablica P (12 B, novi red na vrh) i tablica Q (40 B, prvi slobodni red)
        tagl = tag & 0xffff
        PB = Y(12586632)
        if bytes(d[PB - 12:PB - 8]) == b'\xff\xff\x00\x00':
            f = None
            for j in range(0, 40):
                o = PB + 12 * j
                if struct.unpack_from('<II', d, o) == (0xffff, 0xffffffff):
                    f = j
                    break
            if f is not None:
                d[PB + 12:PB + 12 * (f + 1)] = bytes(d[PB:PB + 12 * f])
                struct.pack_into('<III', d, PB, tagl, 0x03f9c002, 0)
                done.append('popis P')
        QB = None
        for o in range(Y(13287000), Y(13291000), 4):
            if bytes(d[o:o + 12]) == b'\xff\xff\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff' and not any(d[o + 12:o + 40]):
                QB = o
                break
        if QB is not None:
            struct.pack_into('<10I', d, QB, tagl, 0x03f9c002, mycode, 0, 2, 0, 0, 2, 0, 0)
            done.append('popis Q')
        # brojaci posudbi u bloku mog kluba (uzorak Dowman: +746,+747,+749 +1; +752,+756,+760 +2 s opcijom otkupa)
        my2 = self.club_offset()
        for off_, inc_ in ():   # pc202: NE dirati. +746..+760 su bodovi/odigrano/W/D/L/GF/GA u tablici lige (u starim uzorcima je izmedu saveova odigrana utakmica); igra ih pri posudbi ne mijenja (Moonan P0/P2, Arsenal 60 MB)
            if d[my2 + off_] < 250:
                d[my2 + off_] += inc_
        done.append('club counters')
        # tablica ugovora: nativna posudba BEZ opcije otkupa nema red (uzorak Allen), samo posudba S opcijom ima red (uzorak Dowman)
        crow = option if option else dict(wage=sal, release=fee * 12, end=endc)
        if option:
            kk = None
            for k in range(0, 60):
                o = e2 + 44 + 48 * k
                if (struct.unpack_from('<I', d, o)[0] >> 24) != 0x90:
                    kk = k
                    break
            if kk is not None:
                o = e2 + 44 + 48 * kk
                struct.pack_into('<IIIII', d, o, tag, pid, crow['wage'] // 100, crow['release'] // 100, crow['end'])
                done.append('buy option contract row')
            if option and opt_row:
                o = e2 + self.OPT0
                empty = all(bytes(d[o + 12 * j:o + 12 * j + 2]) == b'\xff\xff' and bytes(d[o + 12 * j + 4:o + 12 * j + 6]) == b'\xff\xff' for j in range(3))
                if empty:
                    struct.pack_into('<IIIIIIIII', d, o, 0xffff, 0, 0x1409, 0x30, 1, option['buy'] // 100, 0x32, 0xffff, 0)
                    done.append('red opcije otkupa')
        return 'posuden %d do %s (%s); %s' % (pid, hex(end_code), ', '.join(done), msg)


    # ---- posudba U MOJ klub kao NATIVNI "dogovoreni" posao (uzorci Doak/Kroupi/Gavi, Man City 2026-10-12): igra posudbu dovrsi sama na dan prijelaza
    @staticmethod
    def _next_day_code(code):
        import datetime as _dt
        d_, mo, y = code >> 24, (code >> 16) & 0xff, code & 0xffff
        n = _dt.date(y, mo, d_) + _dt.timedelta(days=1)
        return (n.day << 24) | (n.month << 16) | n.year

    S16CNT = 12509828        # brojac zapisa S16 (256 + broj redaka koje je upisala igra)
    SERLIST = 292656         # rep + SERLIST: lista (u16, 0xffff = slobodno) serijskih brojeva dogovora koje igra treba izvrsiti; igra ju puni pri dogovoru

    def _serial_list_add(self, e2, ser):
        d = self.d
        for k in range(0, 40):
            o = e2 + self.SERLIST + 2 * k
            v = struct.unpack_from('<H', d, o)[0]
            if v == ser:
                return
            if v == 0xffff:
                struct.pack_into('<H', d, o, ser)
                return
        raise ValueError('deal execution list is full')

    def club_code_of(self, off):
        """Kod kluba (owner kod u zapisima igraca iz njegovog sastava, najcesci)."""
        chunks, _e = self._chunks()
        big = b''.join(chunks)
        from collections import Counter
        cc = Counter()
        for k in range(self._squad_len(off)):
            q = struct.unpack_from('<I', self.d, off + self.PAIR_OFF + 8 * k + 4)[0]
            ri = self._bf(big, struct.pack('<I', q))
            while ri >= 0 and not (ri >= 192 and (ri - 192) % 156 == 0):
                ri = self._bf(big, struct.pack('<I', q), ri + 1)
            if ri >= 0 and struct.unpack_from('<I', big, ri - 48 + 136)[0] == 0xffffffff:
                cc[struct.unpack_from('<I', big, ri - 48 + 140)[0]] += 1
        return cc.most_common(1)[0][0] if cc else None


    def recently_joined(self, pid):
        """Igrac doveden u ovom roku (zapis igraca na +136 i +140 jos nosi kod bivseg kluba)."""
        try:
            chunks, _e = self._chunks()
            big = b''.join(chunks)
            pat = struct.pack('<I', pid)
            i = self._bf(big, pat)
            while i >= 0 and not (i >= 192 and (i - 192) % 156 == 0):
                i = self._bf(big, pat, i + 1)
            if i < 0:
                return False
            r = i - 48
            a_, b_ = struct.unpack_from('<II', big, r + 136)
            return a_ != 0xffffffff and a_ == b_
        except Exception:
            return False

    # ---- ugovorni uvjeti iz repa savea (izmjereno 27.10.: Kevin 20 %, Gustavo Sa 10 %, bonusi i klauzule)
    def player_terms(self, pid, tag=None):
        """Uvjeti ugovora koje je dogovorila igra (rep savea iza zlib dijelova; iznosi su /100):
        placa, odstetna klauzula, kraj ugovora, bonusi (nastup, gol, pobjeda) i sell-on (postotak bivsem klubu).
        -> dict ili None ako se igrac ne nade."""
        d = self.d
        if tag is None:
            tag = self.my_squad_tags().get(pid)
            if tag is None:
                tag = self.player_tag(pid)
        pb = struct.pack('<II', tag, pid)
        try:
            _ch, start = self._chunks()
        except Exception:
            start = len(d) - 600000
        mv = bytes(d[start:])
        out = dict(pid=pid)
        bon = []
        mc = getattr(self, '_mcc', None)
        if mc is None:
            mc = self._mcc = self.my_club_code()
        i = mv.find(pb)
        while i >= 0:
            o = start + i
            nxt = struct.unpack_from('<IIII', d, o + 8) if o + 24 <= len(d) else (0, 0, 0, 0)
            prev = struct.unpack_from('<HHI', d, o - 8) if o >= 8 else (0, 0, 0)
            y, m_, dd = nxt[2] & 0xffff, (nxt[2] >> 16) & 0xff, nxt[2] >> 24
            if 'release' not in out and 0 < nxt[0] < 2000000 and 0 <= nxt[1] < 50000000 and 2000 < y < 2100 and 1 <= m_ <= 12 and 1 <= dd <= 31:
                out.update(salary=nxt[0] * 100, release=nxt[1] * 100, until='%d/%d/%d' % (dd, m_, y))
            elif 'sell_on' not in out and 1 <= (nxt[0] & 0xff) <= 100 and nxt[1] == mc and nxt[2] not in (0, 0xffffffff) and nxt[2] != nxt[1]:
                # kod kluba >> 14 = id kluba (teamids.json)
                out.update(sell_on=nxt[0] & 0xff, sell_on_club=nxt[2], sell_on_team=nxt[2] >> 14)
            elif 0 < prev[2] < 100000 and prev[0] < 10000 and nxt[0] != mc and nxt[1] != mc:
                bon.append((o, prev[2] * 100))
            i = mv.find(pb, i + 1)
        # tri tablice bonusa (nastup, gol, pobjeda) su jedna iza druge, razmak ~22800 B
        for k in range(len(bon) - 2):
            a_, b_, c_ = bon[k:k + 3]
            if 10000 < b_[0] - a_[0] < 40000 and 10000 < c_[0] - b_[0] < 40000:
                out.update(bonus_app=a_[1], bonus_goal=b_[1], bonus_win=c_[1])
                break
        return out

    def deal_layout(self):
        """Redovi dogovora u repu: FL26 ima kod kupca (moj klub) na +4 i prodavatelja na +28; vanilla PES 2021 obrnuto
        (prodavatelj/vlasnik na +4, moj klub na +28). -> 'buyer_first' | 'seller_first' | 'unknown'."""
        try:
            my = self.my_club_code()
            _ch, e2 = self._chunks()
            mb = e2 + self.META0
            a = b = 0
            for j in range(-60, 60):
                o = mb + 60 * j
                if o < 0 or o + 60 > len(self.d) or self.d[o:o + 2] == b'\xff\xff':
                    continue
                p4, p28 = struct.unpack_from('<I', self.d, o + 4)[0], struct.unpack_from('<I', self.d, o + 28)[0]
                if p28 == my and p4 != my:
                    a += 1
                elif p4 == my and p28 != my:
                    b += 1
            return 'seller_first' if a > b else 'buyer_first' if b else 'unknown'
        except Exception:
            return 'unknown'

    def my_club_code(self):
        """Kod mog kluba (owner kod u zapisima igraca iz mog sastava, najcesci)."""
        chunks, _e = self._chunks()
        big = b''.join(chunks)
        from collections import Counter
        cc = Counter()
        my = self.club_offset()
        for k in range(self._squad_len(my)):
            q = struct.unpack_from('<I', self.d, my + self.PAIR_OFF + 8 * k + 4)[0]
            ri = self._bf(big, struct.pack('<I', q))
            while ri >= 0 and not (ri >= 192 and (ri - 192) % 156 == 0):
                ri = self._bf(big, struct.pack('<I', q), ri + 1)
            if ri >= 0 and struct.unpack_from('<I', big, ri - 48 + 136)[0] == 0xffffffff:
                cc[struct.unpack_from('<I', big, ri - 48 + 140)[0]] += 1
        return cc.most_common(1)[0][0] if cc else None

    META0 = 55156            # tablica dogovora u repu: zapisi od 60 B = meta (24 B: serijski, 0c402b00, status, datum, ff*8) + podaci (36 B)

    def player_loan_state(self, pid):
        """(ima_zapis, vec_na_posudbi, ima_vlasnika) za igraca bilo kojeg kluba."""
        chunks, _e = self._chunks()
        big = b''.join(chunks)
        pk = struct.pack('<I', pid)
        ri = self._bf(big, pk)
        while ri >= 0 and not (ri >= 192 and (ri - 192) % 156 == 0):
            ri = self._bf(big, pk, ri + 1)
        if ri < 0:
            return (False, False, False)
        r = ri - 48
        own = struct.unpack_from('<I', big, r + 140)[0]
        return (True, struct.unpack_from('<I', big, r + 136)[0] != 0xffffffff, own not in (0, 0xffffffff))

    def on_loan_pids(self):
        """Svi igraci u igri koji su trenutno na posudbi (zapis +136 != ffffffff), jednim prolazom kroz zapise igraca."""
        chunks, _e = self._chunks()
        big = b''.join(chunks)
        res = set()
        i = 0
        n = len(big)
        while 144 + 156 * i + 156 <= n:
            r = 144 + 156 * i
            tag, pid = struct.unpack_from('<II', big, r + 44)
            if (tag >> 16) == 0x49aa and 0 < pid < 400000 and struct.unpack_from('<I', big, r + 136)[0] != 0xffffffff:
                res.add(pid)
            i += 1
        return res

    def option_terms(self, pid):
        """Uvjeti opcije otkupa za igraca (tablice uvjeta i cijene u repu) ili None: dict(buy, wage, release, end)."""
        _c, e2 = self._chunks()
        d = self.d
        best = None
        for k in range(0, 80):
            o = e2 + 16 + 48 * k
            if bytes(d[o + 4:o + 8]) == b'\xff\xff\xff\xff':
                continue
            if struct.unpack_from('<I', d, o + 32)[0] != pid:
                continue
            ser = struct.unpack_from('<H', d, o)[0]
            wage, rel, end = struct.unpack_from('<III', d, o + 36)
            for m in range(0, 40):
                w0, price, w2 = struct.unpack_from('<III', d, e2 + 151056 + 12 * m)
                if (w2 & 0xffff) == ser and (w0 & 0xffff) != 0xffff:
                    best = dict(buy=price * 100, wage=wage * 100, release=rel * 100, end=end)
        return best

    def loan_end_code(self, pid):
        """Kod datuma kraja posudbe iz zapisa igraca (+152) ili None."""
        chunks, _e = self._chunks()
        big = b''.join(chunks)
        pk = struct.pack('<I', pid)
        ri = self._bf(big, pk)
        while ri >= 0 and not (ri >= 192 and (ri - 192) % 156 == 0):
            ri = self._bf(big, pk, ri + 1)
        if ri < 0:
            return None
        v = struct.unpack_from('<I', big, ri - 48 + 152)[0]
        return v if (v & 0xffff) > 2000 else None

    def loaned_in_pids(self):
        """Igraci u mom sastavu koji su POSUDENI (zapis igraca +136 != ffffffff = vlasnik je drugi klub)."""
        chunks, _e = self._chunks()
        big = b''.join(chunks)
        res = set()
        for pid in self.my_squad_tags():
            pk = struct.pack('<I', pid)
            ri = self._bf(big, pk)
            while ri >= 0 and not (ri >= 192 and (ri - 192) % 156 == 0):
                ri = self._bf(big, pk, ri + 1)
            if ri >= 0 and struct.unpack_from('<I', big, ri - 48 + 136)[0] != 0xffffffff and struct.unpack_from('<I', big, ri - 48 + 140)[0] != 0xffffffff:
                e = struct.unpack_from('<I', big, ri - 48 + 152)[0]
                # prava posudba ima datum kraja na +152; bez njega (npr. 0000ffff) +136 je samo trag proslog kluba nakon transfera
                if 1 <= (e >> 24) <= 31 and 1 <= ((e >> 16) & 0xff) <= 12 and 2000 < (e & 0xffff) < 2100:
                    res.add(pid)  # (136 = klub, 140 = ffffffff: promovirani omladinac, nije posudba)
        return res

    def pending_loan_wage(self):
        """Zbroj godisnjih placa posudbi koje su dogovorene (D red, zastavica 2), a igraca jos nema u mom sastavu."""
        d = self.d
        squad = {p for p in self.squad_ids() if p}
        w = self.player_wages()
        tot = 0
        for k in range(-30, 400):
            q = self.D0 + 52 * k
            tag, pid = struct.unpack_from('<II', d, q + 12)
            if tag != 0xffff and (tag >> 16) == 0x023d and struct.unpack_from('<I', d, q + 48)[0] == 2 and pid not in squad:
                tot += w.get(pid, 0)
        return tot

    def _s16_slot(self):
        """Sljedeci red tablice odgovora klubova (S16, 80 B) -> (baza reda 0, adresa brojaca, k).
        Tablica ima 128 redaka (k = -16..111) i puni se kruzno. Brojac: nizi bajt = indeks sljedeceg reda (0..127), gornji bajtovi su zastavice.
        Isto vrijedi za klasicni i prosireni format (provjereno 28.10. na 6 prosirenih i ~30 klasicnih saveova; stari nacin
        'iza najnovijeg datuma u redovima 0..111' je na prosirenom formatu pisao u krivi red na pocetku sezone i nakon kruga)."""
        d = self.d
        if self.ext and not self.game27:   # pc273: FL27 ima klasicni S16 (izmjereno: Alvaro Rodriguez, red k=-10 uz brojac 262)
            B, C = X(0x2454890), X(0x2459a94)   # pc202: prednji dio (DXA); na 60 MB je self.dx pisao 120 redova dalje
        else:
            B, C = Y(12488832), self.S16CNT
        cnt = struct.unpack_from('<I', d, C)[0]
        idx = (cnt & 0xff) % 128
        k = -16 + idx
        occ = lambda kk: struct.unpack_from('<I', d, B + 80 * kk + 4)[0] != 0xff
        prev = -16 + (idx - 1) % 128
        if not occ(k) or occ(prev):
            # igra pise u red koji pokazuje brojac (i preko starog reda kad je tablica puna ili je tamo stari krivi upis appa);
            # sumnjivo je samo ako je red ispred pokazivaca prazan, a tablica nije prazna
            return B, C, k
        if not any(occ(kk) for kk in range(-16, 112)):
            return B, C, k
        raise ValueError('Nothing was written: the club-response table in this save does not look as expected (counter %d, row %d is taken). '
                         'Workaround: send the loan offer in the game, save, then use "Finish offer sent in game" here (or do the loan in the game). '
                         'Please send this save file to the app author so it can be supported.' % (cnt, idx))

    def _s16_next(self):
        """Klasicni format: sljedeci red S16 (k, red 0 na 12488832)."""
        return self._s16_slot()[2]

    def loan_in_pending(self, pid, fee, end_code, today=None, s16=True, option=None, native=False, multi=False):
        """Upisuje SAMO stanje 'dogovoreno, igrac dolazi sutra' (status 4) kao da je klub prihvatio ponudu za posudbu; zapis igraca se ne dira,
        igra posudbu sama izvrsi pri sljedecem danu (pa je nativna: Other Teams, bez Renew Contract). Bez opcije otkupa."""
        self.pid_guard(pid)   # pc250
        if self.ext and self.game27:
            if option:
                if not self.FL27_OPTION_OK:
                    raise ValueError('A loan with an option to buy is not unlocked yet on Football Life 2027 saves; do it in the game. The save was not touched.')
                return self._loan_opt_fl27(pid, fee, end_code, option)
            return self._loan_in_fl27(pid, fee, end_code)
        if self.ext and not native:
            return self._pending_x(pid, fee, end_code, option, today, multi=multi)
        if False:
            ch0, _e0 = self._chunks()
            big0 = b''.join(ch0)
            r0 = None
            i0 = self._bf(big0, struct.pack('<I', pid))
            while i0 >= 0:
                if i0 >= 192 and (i0 - 192) % 156 == 0:
                    r0 = i0 - 48
                    break
                i0 = self._bf(big0, struct.pack('<I', pid), i0 + 1)
            if r0 is None:
                raise ValueError('player record not found')
            if struct.unpack_from('<I', big0, r0 + 140)[0] in (0, 0xffffffff):
                raise ValueError('player has no owning club')
            if struct.unpack_from('<I', big0, r0 + 136)[0] != 0xffffffff:
                raise ValueError('player is already on loan')
            return self.sign_outside_x(pid, fee, 0, 0, loan_end=end_code)
        chunks, e2 = self._chunks()
        big = b''.join(chunks)
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        rec = big[r:r + 156]
        owner = struct.unpack_from('<I', rec, 140)[0]
        if owner in (0, 0xffffffff) or struct.unpack_from('<I', rec, 136)[0] != 0xffffffff:
            raise ValueError('player has no owning club or is already on loan')
        tag = struct.unpack_from('<I', rec, 44)[0]
        f = fee // 100
        d = self.d
        today = self.game_date_code() if today is None else today
        move = self._next_day_code(today)
        done = []
        # 1) budzet (pada odmah pri dogovoru)
        b = struct.unpack_from('<I', d, self.BUDGET)[0]
        if f > b:
            raise ValueError('not enough money in the transfer budget')
        struct.pack_into('<I', d, self.BUDGET, b - f)
        done.append('budzet')
        # 2) dnevnik dogovora (52 B redovi, prvi slobodan: u32 na +12 == 0xffff), kraj [.., -naknada, 2]
        o = None
        for k in range(-30, 400):
            q = self.D0 + 52 * k
            if struct.unpack_from('<I', d, q + 12)[0] == 0xffff:
                o = q
                break
        if o is None:
            raise ValueError('deal log: no room')
        struct.pack_into('<13I', d, o, 0, 0, 0xffff, tag, pid, 0, 0, 0, 0, 0, 0, struct.unpack('<I', struct.pack('<i', -f))[0], 2)
        done.append('dnevnik')
        # 3) red u redu dogadjaja (56 B slotovi od 12464992; prazan slot: u32 na +0 == 0xff): (0x6e, tag, pid), datum slota (zadnja rijec) = danas
        QB = Y(12464992)
        for k in range(0, 200):
            q = QB + 56 * k
            if struct.unpack_from('<I', d, q)[0] == 0xff:
                struct.pack_into('<III', d, q, 0x6e, tag, pid)
                struct.pack_into('<I', d, q + 52, today)
                done.append('red dogadjaja')
                break
        else:
            raise ValueError('The game\'s event list in this save is full right now (this happens around the start of the transfer window). Simulate a day or two in the game, save, and try again. Nothing was written.')
        # 4) S16 (80 B): prvi red iza zadnjeg zauzetog ([4:8] != 0xff), + 'ostatak' 09414100 na pocetku sljedeceg reda
        # (nativni dogovor NE pise S16 red; igra ga napise tek pri dolasku; zato je ovo isključeno)
        if s16:
            S16, _C16, k = self._s16_slot()   # brojac igre odredjuje red (oba formata)
            o = S16 + 80 * k
            row = struct.pack('<IIIIIIIII', 0x1b, today, 3, 0xff, 1, 0, 0xffffffff, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
                bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
            assert len(row) == 76
            d[o + 4:o + 80] = row
            if o + 80 < S16 + 80 * 112:   # zadnji red tablice: iza njega je druga struktura
                d[o + 80:o + 84] = bytes.fromhex('09414100')
            # brojac zapisa u S16 (igra ga povecava za 1 po dodanom redu; bez toga igra red ne racuna i idući dogadjaj ga prepise)
            struct.pack_into('<I', d, _C16, struct.unpack_from('<I', d, _C16)[0] + 1)
            done.append('S16')
        # 5) rep: zapis dogovora (meta + podaci), sortirano po serijskom broju, serijski = najmanji slobodan >= 0x2b
        base = e2 + self.META0
        recs = []
        for j in range(-7, 60):   # pc205: tablica pocinje na -7
            o2 = base + 60 * j
            if bytes(d[o2 + 28:o2 + 32]) != b'\xff\xff\xff\xff':
                recs.append((struct.unpack_from('<H', d, o2)[0], j, bytes(d[o2:o2 + 60])))
        j0 = recs[0][1] if recs else -7   # pc205: tablica dogovora uvijek pocinje na j = -7 (svi formati); nova karijera nema redova
        used = {x[0] for x in recs}
        if True:   # pc249: i bez opcije broje se serijski iz tablice ugovora (igra: novi = max obje tablice + 1; app od pc207 tamo pise retke potpisa)
            for k in range(0, 80):
                oa = e2 + 16 + 48 * k
                if bytes(d[oa + 4:oa + 8]) != b'\xff\xff\xff\xff':
                    used.add(struct.unpack_from('<H', d, oa)[0])
        # igra svakom dogovoru rezervira par serijskih (uvjeti/ponuda + dogovor): novi dogovor = max + 2 (nativno u vanilli i FL26 s opcijom).
        # s max + 1 dogovor dobije "par" prethodnog dogovora i igra izvrsi TAJ dogovor (vanilla 28.10.: Caicedo -> vratio se Baba)
        ser = max(used) + 2 if used else 0x2b
        ser_a = None
        if option:
            ser_a = ser - 1
        mc = self.my_club_code()
        std = struct.pack('<I', mc) if mc else next((x[2][4:8] for x in recs if x[2][4:8] == bytes.fromhex('0c402b00')), bytes.fromhex('0c402b00'))
        meta = struct.pack('<HH', ser, 0) + std + struct.pack('<II', 4, move) + b'\xff' * 8
        data = struct.pack('<I', 0xffff) + struct.pack('<IIIIII', owner, tag, pid, f, f, end_code) + struct.pack('<II', 0xffff, 0)
        assert len(meta) == 24 and len(data) == 36
        new = (ser, 0, meta + data)
        allr = sorted([(x[0], x[2]) for x in recs] + [(ser, meta + data)], key=lambda t: t[0])
        if j0 + len(allr) > 58:
            raise ValueError('deal table in the tail is full')
        for n_, (_, rb) in enumerate(allr):
            o2 = base + 60 * (j0 + n_)
            d[o2:o2 + 60] = rb
        self._serial_list_add(e2, ser)
        done.append('rep serijski %d' % ser)
        if option:
            # uvjeti ugovora (red 48 B: serijski, klub, status 4, ffff0000, ff, ff, ffff, tag, pid, placa/100, release/100, kraj) + red cijene otkupa (prazan: ffff, 0, ffff -> 0, cijena/100, serijski)
            ka = None
            for k in range(0, 80):
                oa = e2 + 16 + 48 * k
                if bytes(d[oa + 4:oa + 8]) == b'\xff\xff\xff\xff':
                    ka = k
                    break
            if ka is None:
                raise ValueError('contract terms table is full')
            oa = e2 + 16 + 48 * ka
            struct.pack_into('<HH', d, oa, ser_a, 0)
            d[oa + 4:oa + 8] = std
            struct.pack_into('<IIIIII', d, oa + 8, 4, 0xffff, 0xffffffff, 0xffffffff, 0xffff, tag)
            struct.pack_into('<I', d, oa + 32, pid)
            struct.pack_into('<III', d, oa + 36, option['wage'] // 100, option['release'] // 100, option['end'])
            kb = None
            for m in range(0, 30):
                ob = e2 + 151056 + 12 * m
                w0, w1 = struct.unpack_from('<II', d, ob)
                if (w0 & 0xffff) == 0xffff and w1 == 0:
                    kb = m
                    break
            if kb is None:
                raise ValueError('buy option price table is full')
            oid = 0
            for m in range(0, 30):
                w0m = struct.unpack_from('<H', d, e2 + 151056 + 12 * m)[0]
                if w0m != 0xffff and m != kb:
                    oid = max(oid, w0m + 1)
            struct.pack_into('<III', d, e2 + 151056 + 12 * kb, oid, option['buy'] // 100, ser_a)
            # u16 na +16 retka dogovora = indeks reda u tablici cijena otkupa (0 = prvi); bez njega igra opciju ne prepozna, s krivim indeksom prikaze tudje brojke
            for j in range(-7, 60):   # pc205: tablica pocinje na -7
                oj = base + 60 * j
                if bytes(d[oj + 28:oj + 32]) != b'\xff\xff\xff\xff' and struct.unpack_from('<H', d, oj)[0] == ser and struct.unpack_from('<I', d, oj + 36)[0] == pid:
                    struct.pack_into('<H', d, oj + 16, oid)
                    break
            done.append('opcija otkupa (uvjeti %d, indeks %d)' % (ser_a, kb))
        return 'dogovoreno %d: dolazi %s do %s (%s)' % (pid, hex(move), hex(end_code), ', '.join(done))


    def loans_waiting(self):
        """pc153: dolazne posudbe koje cekaju da ih igra izvrsi (red dogadjaja 0x6e) -> [pid]. Klasicni format: [] (tamo se ne broji)."""
        # pc179: i klasicni (19,9 MB) format: red dogadjaja na Y(12464992) (tester Palermo: Cardozo 0x6e u redu 8)
        if self.ext and self.game27:
            # pc281: FL27 - svaki dogovor u listi izvrsenja (kupnja, prodaja, posudba, slobodni) blokira sljedeci; app posudbu stavi u red
            d = self.d
            _ch, e = self._chunks()
            sers = {struct.unpack_from('<H', d, e + self.SERLIST + 2 * j)[0] for j in range(40)} - {0xffff}
            out = []
            for j in range(110):
                o2 = e + 54736 + 60 * j
                if struct.unpack_from('<H', d, o2)[0] in sers:
                    out.append(struct.unpack_from('<I', d, o2 + 36)[0])
            k = 0
            while bytes(d[e + 16 + 48 * k + 4:e + 16 + 48 * k + 8]) != b'\xff\xff\xff\xff' and k < 200:
                o = e + 16 + 48 * k
                if struct.unpack_from('<H', d, o)[0] in sers:
                    out.append(struct.unpack_from('<I', d, o + 32)[0])
                k += 1
            return out or ([0] if sers else [])
        QB = X(0x244eb70) if self.ext else Y(12464992)
        out = []
        for k in range(0, 200):
            q = QB + 56 * k
            if struct.unpack_from('<I', self.d, q)[0] == 0x6e:
                out.append(struct.unpack_from('<I', self.d, q + 8)[0])
        return out

    def _pending_x(self, pid, fee, end_code, option, today=None, multi=False):
        """Prosireni (45 MB) format: stanje 'dogovoreno' za posudbu S opcijom otkupa, izmjereno na pravom dogovoru u igri (Moonan P0->P2).
        Igra posudbu sama dovrsi pri sljedecem danu simulacije."""
        d = self.d
        if self.fmt60 and option:
            # pc247: modul testera 60 MB (Report 04), beta; ukljucuje se samo uz config.json "loan_opt60_beta": true (odvojeno od free60_beta)
            if not getattr(self, '_opt60_ok', False):
                raise ValueError('On the 60 MB save format a loan with an option to buy is still a beta (a plain loan works). Turn it on in config.json ("loan_opt60_beta": true) or do this one in the game. The save was not touched.')
            if multi:
                raise ValueError('On the 60 MB save format only one option loan at a time is supported (beta). The save was not touched.')
            import fl26_optionloan60 as _option60
            info = _option60.queue_new_option(self, sys.modules[__name__], pid, fee, end_code, option)
            self._allow = list(getattr(self, '_allow', [])) + info['ranges']
            self._beta_write = True
            return 'dogovoreno %d: posudba s opcijom otkupa (60 MB beta), dolazi %s do %s (dogovor %d, uvjeti %d, opcija %d)' % (
                pid, hex(info['arrival_date']), hex(end_code), info['deal_serial'], info['term_serial'], info['option_id'])
        chunks, e2 = self._chunks()
        big = b''.join(chunks)
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        rec = big[r:r + 156]
        owner = struct.unpack_from('<I', rec, 140)[0]
        if owner in (0, 0xffffffff) or struct.unpack_from('<I', rec, 136)[0] != 0xffffffff:
            raise ValueError('player has no owning club or is already on loan')
        tag = struct.unpack_from('<I', rec, 44)[0]
        f = fee // 100
        today = self.game_date_code() if today is None else today
        move = self._next_day_code(today)
        if ((today >> 16) & 0xff, today >> 24) in ((8, 31), (1, 31)):
            # zadnji dan prijelaznog roka: dolazak 'sutra' je izvan roka i igra dogovor ponisti (Iacobellis 31.8.);
            # igra sama na zadnji dan izvrsi dogovor isti dan (Stojkovic: datum dolaska 31.8.)
            move = today
        mc = self.my_club_code()
        if not mc:
            raise ValueError('my club code not found')
        std = struct.pack('<I', mc)
        b = struct.unpack_from('<I', d, self.BUDGET)[0]
        if f > b:
            raise ValueError('not enough money in the transfer budget')
        # --- priprema (sve provjere prije prvog upisa)
        QB = X(0x244eb70)
        n_wait = 0
        for k in range(0, 200):
            q = QB + 56 * k
            if struct.unpack_from('<I', d, q)[0] == 0x6e:
                if struct.unpack_from('<I', d, q + 8)[0] == pid:
                    raise ValueError('loan for this player is already agreed (he arrives after the next day in the game)')
                # igra ponekad ponisti posudbu kad ih ceka vise odjednom (Sa; Hoever i Everton uz Vasqueza i Pobegu 14.10.; uzrok nepoznat): siguran nacin = jedna po jedna
                if multi:
                    n_wait += 1   # test (samo vlasnik): vise posudbi odjednom, svaka na svoj dan dolaska
                    continue
                raise ValueError('you already have one agreed loan waiting for arrival. When several are waiting the game cancels some (the fee is lost), so the app allows one at a time: simulate a day in the game, then bring in the next one.')
        if n_wait:
            # pc152: igra u jednom danu izvrsi samo jedan dolazak posudbe, ostale dogovore s istim datumom obrise (Saibari/Mendy uz Vanhouttea 28.10.)
            # -> svaka sljedeca posudba dolazi dan kasnije; mora stati u prijelazni rok
            for _ in range(n_wait):
                move = self._next_day_code(move)
            if ((move >> 16) & 0xff) in (9, 2) and ((today >> 16) & 0xff) in (8, 1):
                raise ValueError('not enough days left in the transfer window for another loan')
        qo = None
        for k in range(0, 200):  # prvi prazan red (igra puni od pocetka; nova karijera ima ~4 reda)
            q = QB + 56 * k
            if struct.unpack_from('<I', d, q)[0] == 0xff:
                qo = q
                break
        if qo is None:
            raise ValueError('The game\'s event list in this save is full right now (this happens around the start of the transfer window). Simulate a day or two in the game, save, and try again. Nothing was written.')
        S16, CNT, k16 = self._s16_slot()   # brojac igre (kao klasicni format): red k = -16 + nizi bajt brojaca, kruzno 128 redaka
        o13 = X(0x24ef0dc)
        for _k in range(60):
            o13 += 52
            if d[o13] == 0xff and d[o13 + 1] == 0xff:
                break
        else:
            raise ValueError('S13: no empty row')
        # tablica ugovornih uvjeta (48 B, sortirano po serijskom) i meta tablica (60 B)
        cbase = e2 + 16
        crows = []
        k = 0
        while bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff':
            crows.append(bytes(d[cbase + 48 * k:cbase + 48 * k + 48]))
            k += 1
            if k > 120:
                raise ValueError('terms table: no end')
        if bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff':
            raise ValueError('terms table is full')
        mbase = e2 + self.META0
        mrows = []
        j0 = None
        for j in range(-60, 60):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv not in (0, 0xffff):
                if j0 is None:
                    j0 = j
                mrows.append((sv, bytes(d[o2:o2 + 60])))
        if j0 is None:
            j0 = -7   # pc205: nova karijera bez ijednog dogovora; tablica pocinje na j = -7 (svi formati)
        if j0 + len(mrows) + 1 > 58:
            raise ValueError('deal table in the tail is full')
        used = {x[0] for x in mrows} | {struct.unpack_from('<H', x, 0)[0] for x in crows}
        lo = min(struct.unpack_from('<H', x, 0)[0] for x in crows)
        free = [s_ for s_ in range(lo, 0x400) if s_ not in used]
        if option:
            ser_a, ser_m = free[0], free[1]
        else:
            ser_a, ser_m = None, free[0]
        pb = e2 + 0x24e10
        kb = None
        oid = 0
        for m_ in range(0, 30 if option else 0):
            w0, w1 = struct.unpack_from('<II', d, pb + 12 * m_)
            if (w0 & 0xffff) == 0xffff and w1 == 0:
                if kb is None:
                    kb = m_
            else:
                oid = max(oid, (w0 & 0xffff) + 1)
        if option and kb is None:
            raise ValueError('buy option price table is full')
        oid = max(oid, 1) if option else 0xffff
        # --- upisi
        struct.pack_into('<I', d, self.BUDGET, b - f)
        struct.pack_into('<III', d, qo, 0x6e, tag, pid)
        struct.pack_into('<I', d, qo + 52, today)
        o = S16 + 80 * k16
        row = struct.pack('<IIIIIIIII', 0x1b, today, 3, 0xff, 1, 0, 0xffffffff, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
            bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
        assert len(row) == 76
        d[o + 4:o + 80] = row
        if o + 80 < S16 + 80 * 112:   # zadnji red tablice: iza njega je druga struktura
            d[o + 80:o + 84] = bytes.fromhex('09414100')
        struct.pack_into('<I', d, CNT, struct.unpack_from('<I', d, CNT)[0] + 1)
        d[o13:o13 + 8] = struct.pack('<II', tag, pid)
        d[o13 + 32:o13 + 40] = struct.pack('<i', -f) + b'\x02\0\0\0'
        # uvjeti ugovora (samo uz opciju otkupa)
        allc = list(crows)
        if option:
            nr = bytearray(48)
            struct.pack_into('<HH', nr, 0, ser_a, 0)
            nr[4:8] = std
            struct.pack_into('<IIIIII', nr, 8, 4, 0xffff, 0xffffffff, 0xffffffff, 0xffff, tag)
            struct.pack_into('<I', nr, 32, pid)
            struct.pack_into('<III', nr, 36, option['wage'] // 100, option['release'] // 100, option['end'])
            allc = sorted(crows + [bytes(nr)], key=lambda x: struct.unpack_from('<H', x, 0)[0])
            for n_, rb in enumerate(allc):
                d[cbase + 48 * n_:cbase + 48 * n_ + 48] = rb
            # cijena otkupa
            struct.pack_into('<III', d, pb + 12 * kb, oid, option['buy'] // 100, ser_a)
        # meta red
        meta = struct.pack('<HH', ser_m, 0) + std + struct.pack('<II', 4, move) + b'\xff' * 8
        data = struct.pack('<I', 0xffff) + struct.pack('<IIIIII', owner, tag, pid, f, f, end_code) + struct.pack('<II', 0xffff, 0)
        mrow = bytearray(meta + data)
        if option:
            struct.pack_into('<H', mrow, 16, oid)
        allm = sorted(mrows + [(ser_m, bytes(mrow))], key=lambda t: t[0])
        for n_, (_, rb) in enumerate(allm):
            d[mbase + 60 * (j0 + n_):mbase + 60 * (j0 + n_) + 60] = rb
        self._serial_list_add(e2, ser_m)
        # brojaci kluba
        my2 = self.club_offset()
        if self.fmt60:
            # pc202: nativni uzorak na 60 MB (Arsenal, Danilo Dine, spremljeno odmah nakon prihvacanja): igra ne mijenja te bajtove
            # (+747 odigrano, +750 L, +752 GF, +756 GA u tablici lige); ostatak upisa = igra (budzet, S13, red 0x6e, dogovor status 4)
            self._beta_write = True
        else:
          for off_, inc_ in ():   # pc202: NE dirati. +746..+760 su bodovi/odigrano/W/D/L/GF/GA u tablici lige (u starim uzorcima je izmedu saveova odigrana utakmica); igra ih pri posudbi ne mijenja (Moonan P0/P2, Arsenal 60 MB)
            if d[my2 + off_] < 250:
                d[my2 + off_] += inc_
        self._allow = list(getattr(self, '_allow', [])) + [
            (qo, qo + 56), (o, o + 84), (CNT, CNT + 4), (o13, o13 + 52), (cbase, cbase + 48 * (len(allc) + 1)),
            (pb + 12 * (kb or 0), pb + 12 * (kb or 0) + (12 if option else 0)), (mbase + 60 * j0, mbase + 60 * (j0 + len(allm))),
            (e2 + self.SERLIST, e2 + self.SERLIST + 256), (my2 + 740, my2 + 770)]
        return 'dogovoreno %d: dolazi %s do %s (dogovor %d%s)' % (pid, hex(move), hex(end_code), ser_m, ', opcija otkupa' if option else '')

    def option_record(self, pid):
        """Ima li igrac zapis dogovora u repu (status 4/5) -> (serijski, status, oid) ili None."""
        d = self.d
        _ch, e2 = self._chunks()
        mbase = e2 + self.META0
        for j in range(-60, 60):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv in (0, 0xffff):
                continue
            if struct.unpack_from('<I', d, o2 + 36)[0] == pid and d[o2 + 8] in (4, 5):
                return sv, d[o2 + 8], struct.unpack_from('<H', d, o2 + 16)[0]
        return None

    def restore_option_loan(self, pid, fee, buy, wage, release, opt_end, loan_end, arrived):
        """Vrati zapis posudbe S opcijom otkupa kakav igra drzi nakon dolaska (Madueke, Moonan, Lunin, Skelly):
        red dogovora status 5 (datum dolaska, oid), red uvjeta ugovora status 4 i red cijene otkupa.
        Po tom zapisu igra igraca prikazuje u Other Teams ('On loan', 'Option-to-buy On').
        Igra je kod Cubarsija (28.10.) izvela posudbu iz appa, ali je zapis obrisala; igrac i zapis igraca se ovdje ne diraju."""
        self.pid_guard(pid)   # pc250
        d = self.d
        if self.option_record(pid):
            raise ValueError('the loan record already exists')
        chunks, e2 = self._chunks()
        big = b''.join(chunks)
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        rec = big[r:r + 156]
        owner = struct.unpack_from('<I', rec, 140)[0]
        if struct.unpack_from('<I', rec, 136)[0] != owner or owner in (0, 0xffffffff):
            raise ValueError('player is not on loan in your club')
        tag = struct.unpack_from('<I', rec, 44)[0]
        mc = self.my_club_code()
        if not mc:
            raise ValueError('my club code not found')
        std = struct.pack('<I', mc)
        cbase = e2 + 16
        crows = []
        k = 0
        while bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff':
            crows.append(bytes(d[cbase + 48 * k:cbase + 48 * k + 48]))
            k += 1
            if k > 118:
                raise ValueError('terms table is full')
        mbase = e2 + self.META0
        mrows = []
        j0 = None
        for j in range(-60, 60):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv not in (0, 0xffff):
                if j0 is None:
                    j0 = j
                mrows.append((sv, bytes(d[o2:o2 + 60])))
        if j0 is None or j0 + len(mrows) + 1 > 58:
            raise ValueError('deal table in the tail is full')
        used = {x[0] for x in mrows} | {struct.unpack_from('<H', x, 0)[0] for x in crows}
        lo = min(struct.unpack_from('<H', x, 0)[0] for x in crows)
        free = [s_ for s_ in range(lo, 0x400) if s_ not in used]
        ser_a, ser_m = free[0], free[1]
        pb = e2 + 0x24e10
        kb, oid = None, 0
        for m_ in range(30):
            w0, w1 = struct.unpack_from('<II', d, pb + 12 * m_)
            if (w0 & 0xffff) == 0xffff and w1 == 0:
                if kb is None:
                    kb = m_
            else:
                oid = max(oid, (w0 & 0xffff) + 1)
        if kb is None:
            raise ValueError('buy option price table is full')
        oid = max(oid, 1)
        f = int(fee) // 100
        nr = bytearray(48)
        struct.pack_into('<HH', nr, 0, ser_a, 0)
        nr[4:8] = std
        struct.pack_into('<IIIIII', nr, 8, 4, 0xffff, 0xffffffff, 0xffffffff, 0xffff, tag)
        struct.pack_into('<I', nr, 32, pid)
        struct.pack_into('<III', nr, 36, int(wage) // 100, int(release) // 100, opt_end)
        allc = sorted(crows + [bytes(nr)], key=lambda x: struct.unpack_from('<H', x, 0)[0])
        for n_, rb in enumerate(allc):
            d[cbase + 48 * n_:cbase + 48 * n_ + 48] = rb
        struct.pack_into('<III', d, pb + 12 * kb, oid, int(buy) // 100, ser_a)
        meta = struct.pack('<HH', ser_m, 0) + std + struct.pack('<II', 5, arrived) + b'\xff' * 8
        data = struct.pack('<I', 0xffff) + struct.pack('<IIIIII', owner, tag, pid, f, f, loan_end) + struct.pack('<II', 0xffff, 0)
        mrow = bytearray(meta + data)
        struct.pack_into('<H', mrow, 16, oid)
        allm = sorted(mrows + [(ser_m, bytes(mrow))], key=lambda t: t[0])
        for n_, (_, rb) in enumerate(allm):
            d[mbase + 60 * (j0 + n_):mbase + 60 * (j0 + n_) + 60] = rb
        self._allow = list(getattr(self, '_allow', [])) + [
            (cbase, cbase + 48 * (len(allc) + 1)), (pb + 12 * kb, pb + 12 * kb + 12), (mbase + 60 * j0, mbase + 60 * (j0 + len(allm)))]
        return 'loan record restored for %d (deal %d, terms %d, option %d)' % (pid, ser_m, ser_a, oid)

    def loan_out_pending(self, pid, club_offset, fee, end_code, today=None):
        """45 MB format: posudba MOG igraca van u stanju 'dogovoreno' (kao nakon prihvacene ponude u igri); izvrsenje (odlazak,
        S15, S2, S14, zapis igraca, S16 0x21) radi igra sama sljedeci dan.
        Izmjereno 25.10. na pravoj posudbi u igri (Zehnter, Wolfsburg -> Valencia, 1,2 M, do 30.6.2026; saveovi 16.8./27.8./30.8.):
        u dogovorenom stanju postoje S13 red (+naknada, tip 2), budzet +naknada, S16 red 0x1b (kod kluba posudbe, ceka=1),
        red u tablici dogovora (status 4, datum odlaska), serijski u listi izvrsenja i red dogadjaja 0x6f."""
        self.pid_guard(pid)   # pc250
        if self.ext and self.game27:
            if not self.FL27_LOANOUT_OK:
                raise ValueError('Loaning your player out is not unlocked yet on Football Life 2027 saves; do it in the game. The save was not touched.')
            return self._loan_out_fl27(pid, club_offset, fee, end_code)
        if not self.ext:
            return self._loan_out_pending_classic(pid, club_offset, fee, end_code, today)
        d = self.d
        sq = self.my_squad_tags()
        if pid not in sq:
            raise ValueError('player is not in your squad')
        tag = sq[pid]
        my = self.club_offset()
        if self._squad_len(my) <= 12:   # pc190: igra dopusta i manje (Arsenal 2027: 17 -> 16 -> 15)
            raise ValueError('your squad would be too small (the game needs at least 12 players)')
        if club_offset == my or self._squad_len(club_offset) >= 40:
            raise ValueError('loan club not possible (full or your club)')
        mycode = self.my_club_code()
        code = self.club_code_of(club_offset)
        if not mycode or not code:
            raise ValueError('club code not found')
        chunks, e2 = self._chunks()
        big = b''.join(chunks)
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        if struct.unpack_from('<I', big, r + 136)[0] != 0xffffffff:
            if struct.unpack_from('<I', big, r + 136)[0] == struct.unpack_from('<I', big, r + 140)[0] and pid in self.my_squad_tags():
                # igrac doveden u ovom roku: zapis jos nosi bivsi klub (izmjereno 27.10. na Kevinu i Gustavu Sa)
                raise ValueError('he joined your club in this transfer window, so he cannot be loaned out yet')
            raise ValueError('player is on loan (not yours) or already loaned out')
        f = fee // 100
        today = self.game_date_code() if today is None else today
        move = self._next_day_code(today)
        if ((today >> 16) & 0xff, today >> 24) in ((8, 31), (1, 31)):
            move = today   # zadnji dan roka: igra izvrsava isti dan
        # red dogadjaja: posudbe koje cekaju (0x6e dolazne, 0x6f odlazne) - jedna po jedna (igra ponekad ponisti kad ih ceka vise)
        QB = X(0x244eb70)
        qo = None
        for k in range(0, 200):
            q = QB + 56 * k
            t = struct.unpack_from('<I', d, q)[0]
            if t in (0x6e, 0x6f):
                if struct.unpack_from('<I', d, q + 8)[0] == pid:
                    raise ValueError('loan for this player is already agreed (he leaves after the next day in the game)')
                raise ValueError('there is already an agreed loan waiting to be executed. Simulate a day in the game, then agree the next one.')
        for k in range(0, 200):
            q = QB + 56 * k
            if struct.unpack_from('<I', d, q)[0] == 0xff:
                qo = q
                break
        if self.fmt60:
            qo = None   # pc202: 60 MB nativno (Arsenal, Konsa -> Inter, spremljeno odmah): igra pri prihvacanju NE pise red 0x6f
        elif qo is None:
            raise ValueError('The game\'s event list in this save is full right now (this happens around the start of the transfer window). Simulate a day or two in the game, save, and try again. Nothing was written.')
        # S16: sljedeci red iza najnovijeg (kruzni red od 112)
        S16, CNT, k16 = self._s16_slot()   # brojac igre (kao klasicni format): red k = -16 + nizi bajt brojaca, kruzno 128 redaka
        o13 = X(0x24ef0dc)
        for _k in range(60):
            o13 += 52
            if d[o13] == 0xff and d[o13 + 1] == 0xff:
                break
        else:
            raise ValueError('S13: no empty row')
        # tablica dogovora u repu
        mbase = e2 + self.META0
        mrows, j0 = [], None
        for j in range(-60, 60):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv in (0, 0xffff):
                continue
            if j0 is None:
                j0 = j
            row = bytes(d[o2:o2 + 60])
            if struct.unpack_from('<I', row, 36)[0] == pid and (struct.unpack_from('<I', row, 8)[0] & 0xff) == 4:
                raise ValueError('there is already a deal for this player waiting to be executed')
            mrows.append((sv, row))
        if j0 is None:
            j0 = -7   # pc205: nova karijera bez ijednog dogovora; tablica pocinje na j = -7 (svi formati)
        if j0 + len(mrows) + 1 > 58:
            raise ValueError('deal table in the tail is full')
        cbase = e2 + 16
        crows, k = [], 0
        while bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff' and k < 120:
            crows.append(struct.unpack_from('<H', d, cbase + 48 * k)[0])
            k += 1
        used = {x[0] for x in mrows} | set(crows)
        ser = max(used) + 1 if used else 0x2b   # igra daje rastuce serijske (Zehnter 0x24 iza 0x22)
        if ser >= 0x400:
            raise ValueError('serijski broj dogovora izvan raspona')
        # --- upisi
        b = struct.unpack_from('<I', d, self.BUDGET)[0]
        struct.pack_into('<I', d, self.BUDGET, b + f)
        if qo is not None:
          d[qo:qo + 56] = struct.pack('<III', 0x6f, tag, pid) + bytes.fromhex(
            'ffff000000000000ffff000000000000ffffffffffff0000ffffffff00001800ffff000080ff0000') + struct.pack('<I', today)
        o = S16 + 80 * k16
        row = struct.pack('<IIIIIIIII', 0x1b, today, 3, 0xff, 1, 0, code, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
            bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
        d[o + 4:o + 80] = row
        if o + 80 < S16 + 80 * 112:   # zadnji red tablice: iza njega je druga struktura
            d[o + 80:o + 84] = bytes.fromhex('09414100')
        struct.pack_into('<I', d, CNT, struct.unpack_from('<I', d, CNT)[0] + 1)
        d[o13:o13 + 8] = struct.pack('<II', tag, pid)
        d[o13 + 32:o13 + 40] = struct.pack('<i', f) + b'\x02\0\0\0'
        meta = struct.pack('<HH', ser, 0) + struct.pack('<III', code, 4, move) + b'\xff' * 8
        data = struct.pack('<IIIIIIIII', 0xffff, mycode, tag, pid, f, f, end_code, 0xffff, 0)
        allm = sorted(mrows + [(ser, meta + data)], key=lambda t: t[0])
        for n_, (_, rb) in enumerate(allm):
            d[mbase + 60 * (j0 + n_):mbase + 60 * (j0 + n_) + 60] = rb
        self._serial_list_add(e2, ser)
        if self.fmt60:
            self._beta_write = True   # pc202: 60 MB nativno: budzet, S13 (+naknada, 2), dogovor status 4 (klub posudbe, sutra), serijski; bez 0x6f i brojaca
        else:
          for off_, inc_ in ():   # pc202: NE dirati. +746..+760 su bodovi/odigrano/W/D/L/GF/GA u tablici lige (u starim uzorcima je izmedu saveova odigrana utakmica); igra ih pri posudbi ne mijenja (Moonan P0/P2, Arsenal 60 MB)
            if d[my + off_] < 250:
                d[my + off_] += inc_
        self._allow = list(getattr(self, '_allow', [])) + [
            (qo or o, (qo or o) + 56), (o, o + 84), (CNT, CNT + 4), (o13, o13 + 52), (mbase + 60 * j0, mbase + 60 * (j0 + len(allm))),
            (e2 + self.SERLIST, e2 + self.SERLIST + 256), (my + 740, my + 770)]
        return 'loan agreed %d: leaves %s, until %s (deal %d)' % (pid, hex(move), hex(end_code), ser)

    def _loan_out_pending_classic(self, pid, club_offset, fee, end_code, today=None):
        """Klasicni (19,9 MB) format: posudba MOG igraca van u stanju 'dogovoreno', isti recept kao izmjereni 45 MB
        (Zehnter -> Valencia), preslikan na tablice klasicnog formata koje vec koristi dolazna posudba (loan_in_pending):
        dnevnik dogovora D0 (+naknada, tip 2), budzet +naknada, red dogadjaja 0x6f, S16 red 0x1b s kodom kluba posudbe,
        red u tablici dogovora u repu (klub posudbe, status 4, datum odlaska; podaci: moj kod, tag, pid, naknada, kraj posudbe)
        i serijski u listi izvrsenja. Odlazak izvrsi igra pri sljedecem danu. NIJE jos potvrdeno u igri na ovom formatu."""
        d = self.d
        sq = self.my_squad_tags()
        if pid not in sq:
            raise ValueError('player is not in your squad')
        tag = sq[pid]
        my = self.club_offset()
        if self._squad_len(my) <= 12:   # pc190: igra dopusta i manje (Arsenal 2027: 17 -> 16 -> 15)
            raise ValueError('your squad would be too small (the game needs at least 12 players)')
        if club_offset == my or self._squad_len(club_offset) >= 40:
            raise ValueError('loan club not possible (full or your club)')
        mycode = self.my_club_code()
        code = self.club_code_of(club_offset)
        if not mycode or not code:
            raise ValueError('club code not found')
        chunks, e2 = self._chunks()
        big = b''.join(chunks)
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        if struct.unpack_from('<I', big, r + 136)[0] != 0xffffffff:
            if struct.unpack_from('<I', big, r + 136)[0] == struct.unpack_from('<I', big, r + 140)[0] and pid in self.my_squad_tags():
                # igrac doveden u ovom roku: zapis jos nosi bivsi klub (izmjereno 27.10. na Kevinu i Gustavu Sa)
                raise ValueError('he joined your club in this transfer window, so he cannot be loaned out yet')
            raise ValueError('player is on loan (not yours) or already loaned out')
        f = fee // 100
        today = self.game_date_code() if today is None else today
        move = self._next_day_code(today)
        if ((today >> 16) & 0xff, today >> 24) in ((8, 31), (1, 31)):
            move = today
        QB = Y(12464992)
        qo = None
        for k in range(0, 200):
            q = QB + 56 * k
            t = struct.unpack_from('<I', d, q)[0]
            if t in (0x6e, 0x6f):
                if struct.unpack_from('<I', d, q + 8)[0] == pid:
                    raise ValueError('loan for this player is already agreed (he leaves after the next day in the game)')
                raise ValueError('there is already an agreed loan waiting to be executed. Simulate a day in the game, then agree the next one.')
        for k in range(0, 200):
            q = QB + 56 * k
            if struct.unpack_from('<I', d, q)[0] == 0xff:
                qo = q
                break
        if qo is None:
            raise ValueError('The game\'s event list in this save is full right now (this happens around the start of the transfer window). Simulate a day or two in the game, save, and try again. Nothing was written.')
        o13 = None
        for k in range(-30, 400):
            q = self.D0 + 52 * k
            if struct.unpack_from('<I', d, q + 12)[0] == 0xffff:
                o13 = q
                break
        if o13 is None:
            raise ValueError('deal log: no room')
        base = e2 + self.META0
        recs = []
        for j in range(-7, 60):   # pc205: tablica pocinje na -7
            o2 = base + 60 * j
            if bytes(d[o2 + 28:o2 + 32]) != b'\xff\xff\xff\xff':
                row = bytes(d[o2:o2 + 60])
                if struct.unpack_from('<I', row, 36)[0] == pid and (struct.unpack_from('<I', row, 8)[0] & 0xff) == 4:
                    raise ValueError('there is already a deal for this player waiting to be executed')
                recs.append((struct.unpack_from('<H', d, o2)[0], j, row))
        j0 = recs[0][1] if recs else -7   # pc205: tablica dogovora uvijek pocinje na j = -7 (svi formati); nova karijera nema redova
        used = {x[0] for x in recs}
        for k in range(0, 80):
            oa = e2 + 16 + 48 * k
            if bytes(d[oa + 4:oa + 8]) != b'\xff\xff\xff\xff':
                used.add(struct.unpack_from('<H', d, oa)[0])
        ser = max(used) + 2 if used else 0x2b   # par serijskih po dogovoru (kao loan_in, vanilla)
        if ser >= 0x400:
            raise ValueError('serijski broj dogovora izvan raspona')
        if j0 + len(recs) + 1 > 58:
            raise ValueError('deal table in the tail is full')
        b = struct.unpack_from('<I', d, self.BUDGET)[0]
        struct.pack_into('<I', d, self.BUDGET, b + f)
        struct.pack_into('<13I', d, o13, 0, 0, 0xffff, tag, pid, 0, 0, 0, 0, 0, 0, f, 2)
        d[qo:qo + 56] = struct.pack('<III', 0x6f, tag, pid) + bytes.fromhex(
            'ffff000000000000ffff000000000000ffffffffffff0000ffffffff00001800ffff000080ff0000') + struct.pack('<I', today)
        S16, _C16, k16 = self._s16_slot()
        o = S16 + 80 * k16
        row = struct.pack('<IIIIIIIII', 0x1b, today, 3, 0xff, 1, 0, code, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
            bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
        d[o + 4:o + 80] = row
        if o + 80 < S16 + 80 * 112:   # zadnji red tablice: iza njega je druga struktura
            d[o + 80:o + 84] = bytes.fromhex('09414100')
        struct.pack_into('<I', d, _C16, struct.unpack_from('<I', d, _C16)[0] + 1)
        meta = struct.pack('<HH', ser, 0) + struct.pack('<III', code, 4, move) + b'\xff' * 8
        data = struct.pack('<IIIIIIIII', 0xffff, mycode, tag, pid, f, f, end_code, 0xffff, 0)
        allr = sorted([(x[0], x[2]) for x in recs] + [(ser, meta + data)], key=lambda t: t[0])
        for n_, (_, rb) in enumerate(allr):
            d[base + 60 * (j0 + n_):base + 60 * (j0 + n_) + 60] = rb
        self._serial_list_add(e2, ser)
        for off_, inc_ in ():   # pc202: NE dirati. +746..+760 su bodovi/odigrano/W/D/L/GF/GA u tablici lige (u starim uzorcima je izmedu saveova odigrana utakmica); igra ih pri posudbi ne mijenja (Moonan P0/P2, Arsenal 60 MB)
            if d[my + off_] < 250:
                d[my + off_] += inc_
        return 'loan agreed %d: leaves %s, until %s (deal %d, classic format)' % (pid, hex(move), hex(end_code), ser)

    def stale_pending(self, fix=False):
        """Dolazne posudbe dogovorene na zadnji dan roka s datumom dolaska 'sutra' (izvan roka -> igra ih ponisti): [pid].
        fix=True: datum dolaska postavi na danas (kao igra na zadnji dan)."""
        if not self.ext:
            return []
        today = self.game_date_code()
        if ((today >> 16) & 0xff, today >> 24) not in ((8, 31), (1, 31)):
            return []
        d = self.d
        _ch, e2 = self._chunks()
        mbase = e2 + self.META0
        out = []
        for j in range(-60, 60):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv in (0, 0xffff) or (struct.unpack_from('<I', d, o2 + 8)[0] & 0xff) != 4:
                continue
            mv = struct.unpack_from('<I', d, o2 + 12)[0]
            if (mv & 0xffff, (mv >> 16) & 0xff, mv >> 24) > (today & 0xffff, (today >> 16) & 0xff, today >> 24):
                out.append(struct.unpack_from('<I', d, o2 + 36)[0])
                if fix:
                    struct.pack_into('<I', d, o2 + 12, today)
                    self._allow = list(getattr(self, '_allow', [])) + [(o2 + 12, o2 + 16)]
        return out

    def cancelled_loans(self):
        """45 MB format: posudbe koje je igra ponistila (naknada placena, igrac nije dosao): [(pid, naknada EUR)].
        Red u S13 (sezonski popis transfera, 52 B od X(0x24ef0dc)) tipa 2 s negativnom naknadom, igrac nije u mom klubu,
        nema dogadjaja 0x6e (ceka dolazak) ni reda dogovora sa statusom 4/5 u repu."""
        if not self.ext:
            return []
        d = self.d
        sq = self.my_squad_tags()
        pend = set()
        QB = X(0x244eb70)
        for k in range(0, 200):
            q = QB + 56 * k
            if struct.unpack_from('<I', d, q)[0] == 0x6e:
                pend.add(struct.unpack_from('<I', d, q + 8)[0])
        try:
            _ch, e2 = self._chunks()
            mbase = e2 + self.META0
            for j in range(-60, 60):
                o2 = mbase + 60 * j
                sv = struct.unpack_from('<H', d, o2)[0]
                if sv in (0, 0xffff):
                    continue
                if struct.unpack_from('<I', d, o2 + 8)[0] in (4, 5):
                    pend.add(struct.unpack_from('<I', d, o2 + 36)[0])
        except Exception:
            return []
        out = []
        for k in range(1, 80):
            o = X(0x24ef0dc) + 52 * k
            if d[o] == 0xff and d[o + 1] == 0xff:
                break
            pid = struct.unpack_from('<I', d, o + 4)[0]
            fee, typ = struct.unpack_from('<iI', d, o + 32)
            if typ == 2 and fee < 0 and pid not in sq and pid not in pend:
                out.append((pid, -fee * 100))
        return out

    def loan_in_finish(self, pid, today=None, s16=False):
        if self.ext:
            raise ValueError('offer sent from the game: on the extended format the game completes it itself (simulate a day)')
        """Igrac je ponudu za posudbu poslao NATIVNO u igri (u repu postoji red dogovora sa statusom 1 ili 3). Ovdje se ponuda samo
        'prihvati': status -> 4, datum -> sutra, budzet, dnevnik (D), red dogadjaja, S16 red; red ponude (5e) se isprazni kao u igri."""
        chunks, e2 = self._chunks()
        big = b''.join(chunks)
        pat = struct.pack('<I', pid)
        d = self.d
        base = e2 + self.META0
        jr = None
        for j in range(-7, 60):   # pc205: tablica pocinje na -7
            o2 = base + 60 * j
            if bytes(d[o2 + 28:o2 + 32]) == b'\xff\xff\xff\xff':
                continue
            if struct.unpack_from('<I', d, o2 + 36)[0] == pid and d[o2 + 8] in (1, 3):
                jr = j   # zadnji red za igraca = trenutna ponuda (kod protuponude postoji i stariji red)
        if jr is None:
            raise ValueError('there is no offer sent in the game for that player (send an offer in the game, save, then open the slot)')
        o2 = base + 60 * jr
        owner, tag, _pid, f1, f2, end_code = struct.unpack_from('<6I', d, o2 + 28)
        f = f1
        today = self.game_date_code() if today is None else today
        move = self._next_day_code(today)
        b = struct.unpack_from('<I', d, self.BUDGET)[0]
        if f > b:
            raise ValueError('not enough money in the transfer budget')
        struct.pack_into('<I', d, self.BUDGET, b - f)
        o = None
        for k in range(-30, 400):
            q = self.D0 + 52 * k
            if struct.unpack_from('<I', d, q + 12)[0] == 0xffff:
                o = q
                break
        if o is None:
            raise ValueError('deal log: no room')
        struct.pack_into('<13I', d, o, 0, 0, 0xffff, tag, pid, 0, 0, 0, 0, 0, 0, struct.unpack('<I', struct.pack('<i', -f))[0], 2)
        QB = Y(12464992)
        for k in range(0, 200):
            q = QB + 56 * k
            if struct.unpack_from('<I', d, q)[0] == 0xff:
                struct.pack_into('<III', d, q, 0x6e, tag, pid)
                struct.pack_into('<I', d, q + 52, today)
                break
        else:
            raise ValueError('The game\'s event list in this save is full right now (this happens around the start of the transfer window). Simulate a day or two in the game, save, and try again. Nothing was written.')
        if s16:
            S16, _C16, k = self._s16_slot()   # brojac igre odredjuje red (oba formata)
            o = S16 + 80 * k
            row = struct.pack('<IIIIIIIII', 0x1b, today, 3, 0xff, 1, 0, 0xffffffff, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
                bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
            d[o + 4:o + 80] = row
            if o + 80 < S16 + 80 * 112:   # zadnji red tablice: iza njega je druga struktura
                d[o + 80:o + 84] = bytes.fromhex('09414100')
            # brojac zapisa u S16 (igra ga povecava za 1 po dodanom redu; bez toga igra red ne racuna i idući dogadjaj ga prepise)
            struct.pack_into('<I', d, _C16, struct.unpack_from('<I', d, _C16)[0] + 1)
        # rep: status 4 + datum dolaska (sutra); serijski ostaje
        struct.pack_into('<II', d, o2 + 8, 4, move)
        self._serial_list_add(e2, struct.unpack_from('<H', d, o2)[0])
        # stariji redovi istog igraca (prethodna ponuda prije protuponude) igra ukloni, a ostali se pomaknu gore
        rows = []
        for j in range(-7, 60):   # pc205: tablica pocinje na -7
            o3 = base + 60 * j
            r = bytes(d[o3:o3 + 60])
            if r[28:32] == b'\xff\xff\xff\xff':
                continue
            if struct.unpack_from('<I', r, 36)[0] == pid and o3 != o2:
                continue
            rows.append(r)
        empty = bytes.fromhex('ffffff00ffffffff00ffff00ffff0000ffffffffffffffffffffff00ffffffffffff0000000000000000000000000000ffff0000ffff000000000000')
        for n, j in enumerate(range(-7, 60)):
            d[base + 60 * j:base + 60 * j + 60] = rows[n] if n < len(rows) else empty
        # red ponude (tag, pid, release/100, 0) pri dogovoru se isprazni
        tp = struct.pack('<II', tag, pid)
        i = bytes(d).find(tp, e2 + 400000)
        cleared = 0
        while i >= 0:
            if bytes(d[i - 1:i]) == b'\x5e':
                struct.pack_into('<IIII', d, i, 0xffff, 0, 0, 0)
                cleared += 1
            i = bytes(d).find(tp, i + 1)
        return 'completed %d (offer from game): %s arrives, fee %d (offer row cleared: %d)' % (pid, hex(move), f * 100, cleared)

    def lab_offsets(self, pid):
        """Laboratorij: pozicije para (oznaka+pid) igraca u tablicama glave (>=12M) i repa; zapis i baza ostaju netaknuti."""
        chunks, e = self._chunks()
        d = bytes(self.d)
        pat = struct.pack('<I', pid)
        out = []
        i = d.find(pat)
        while i >= 0:
            if (i >= Y(12000000) and i < self.CH0) or i >= e:
                out.append(i)
            i = d.find(pat, i + 1)
        return out


    def lab_rec(self, pid, bits):
        """Laboratorij: 1 = +136 -> ffffffff, 2 = +152 -> ffff0000, 4 = makni oznaku statusa 3, 8 = vrati brojace kluba (-Dowman), 16 = +140 -> moj klub."""
        chunks, e = self._chunks()
        big = bytearray(b''.join(chunks))
        pat = struct.pack('<I', pid)
        i = self._bf(big, pat)
        while i >= 0 and not (i >= 192 and (i - 192) % 156 == 0):
            i = self._bf(big, pat, i + 1)
        if i < 0:
            raise ValueError('record not found')
        r = i - 48
        if bits & 1:
            big[r + 136:r + 140] = b'\xff\xff\xff\xff'
        if bits & 2:
            big[r + 152:r + 156] = b'\xff\xff\x00\x00'
        if bits & 4:
            for k in range(13):
                if struct.unpack_from('<H', big, r + 52 + 4 * k)[0] == 3:
                    struct.pack_into('<HH', big, r + 52 + 4 * k, 0xffff, 0)
        if bits & 16:
            big[r + 140:r + 144] = struct.pack('<I', 0x198006)
        if bits & 32:
            for k in range(13):
                if struct.unpack_from('<H', big, r + 52 + 4 * k)[0] == 0x69:
                    struct.pack_into('<HH', big, r + 52 + 4 * k, 0xffff, 0)
        new, pos_ = [], 0
        for c in chunks:
            new.append(bytes(big[pos_:pos_ + len(c)]))
            pos_ += len(c)
        self._rebuild(new, e)
        if bits & 8:
            my = self.club_offset()
            for off_, inc_ in ((746, 1), (747, 1), (749, 1), (752, 2), (756, 2), (760, 2)):
                self.d[my + off_] -= inc_
        return bits

    def lab_blank(self, pid, mask):
        """Laboratorij: prazni (ffff0000 00000000) parove igraca u tablicama cije su bit-pozicije u mask-u."""
        offs = self.lab_offsets(pid)
        done = []
        for k, o in enumerate(offs):
            if mask >> k & 1:
                self.d[o - 4:o + 4] = b'\xff\xff\x00\x00\x00\x00\x00\x00'
                done.append(o)
        return offs, done

    def loaned_pids(self):
        """Igraci na posudbi (zapis: +136 kod kluba vlasnika, +152 datum kraja posudbe)."""
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        out = set()
        for k in range((len(big) - 144) // 156):
            r = 144 + 156 * k
            e = struct.unpack_from('<I', big, r + 152)[0]
            if struct.unpack_from('<I', big, r + 136)[0] != 0xffffffff and 1 <= (e >> 24) <= 31 and 1 <= ((e >> 16) & 0xff) <= 12 and 2000 < (e & 0xffff) < 2100:
                out.add(struct.unpack_from('<I', big, r + 48)[0])
        return out

    def _set_loan(self, pid, end_code):
        """Posudba (uzorak iz igre): zapis igraca +136 = kod kluba vlasnika (kopija +140), +152 = datum kraja posudbe."""
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        pat = struct.pack('<I', pid)
        i = self._bf(big, pat)
        r = None
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        big[r + 136:r + 140] = big[r + 140:r + 144]
        struct.pack_into('<I', big, r + 152, end_code)
        new, pos = [], 0
        for c in chunks:
            new.append(bytes(big[pos:pos + len(c)]))
            pos += len(c)
        self._rebuild(new, end_)

    S2_R = 12056764

    def _s2_stale(self, extra_gone=()):
        """Indeksi S2 redova (flag 192) cijeg igraca vise nema u mom sastavu (prodani) + eksplicitno uklonjeni."""
        d = self.d
        squad = {p for p in self.squad_ids() if p}
        gone = set(extra_gone)
        out = []
        for k in range(40):
            r = self._s2_list() + 16 * k
            if d[r:r + 2] == b'\xff\xff':
                continue
            pid = struct.unpack_from('<I', d, r + 4)[0]
            fl = d[r + 12]
            if pid in gone or (fl in (192, 193) and pid not in squad):
                out.append(k)
        return out

    def _s2_drop(self, idxs):
        """Izbaci S2 redove, ostale pomakni gore, rep dopuni praznim redovima (ffff...)."""
        d = self.d
        R = self._s2_list()
        rows = [bytes(d[R + 16 * k:R + 16 * k + 16]) for k in range(40)]
        pad = next((r for r in rows if r[:2] == b'\xff\xff'), b'\xff\xff\0\0\0\0\0\0\0\0\0\0\xc7\0\0\0')
        keep = [r for k, r in enumerate(rows) if k not in set(idxs)]
        keep += [pad] * (40 - len(keep))
        d[R:R + 640] = b''.join(keep)
        return len(idxs)

    def sell_outside_x(self, pid, fee, buyer_offset, pos=None, loan_end=None):
        """Prodaja igraca iz tvog kluba drugom klubu na prosirenom 45 MB formatu (zavrsno stanje, kao nakon dolaska u igri).
        Mjereno na pravoj prodaji (Dalot -> Fulham): slot redovi se prazne na mjestu, nizovi (S14, S2) se pomicu, S13 dobiva red prihoda."""
        if not self.ext:
            raise ValueError('only works on the verified (45 MB) format')
        d = self.d
        my = self.club_offset()
        n = self._squad_len(my)
        if buyer_offset == my:
            raise ValueError('buying club not possible')
        bn = self._squad_len(buyer_offset)
        if bn >= 40:
            raise ValueError('buying club is full')
        if n <= 12:   # pc190: igra dopusta i manje (Arsenal 2027: 17 -> 16 -> 15)
            raise ValueError('your squad would be too small (the game needs at least 12 players)')
        idx = next((k for k in range(n) if struct.unpack_from('<I', d, my + self.PAIR_OFF + 8 * k + 4)[0] == pid), None)
        if idx is None:
            raise ValueError('player is not in your squad')
        tag = struct.unpack_from('<I', d, my + self.PAIR_OFF + 8 * idx)[0]
        pair = struct.pack('<II', tag, pid)
        f = fee // 100
        date = self.game_date_code()
        mycode = self.my_club_code()
        W = []

        def empty(o):
            return (d[o] == 0xff and d[o + 1] == 0xff) or not any(d[o:o + 8])
        # ---- po-slotne tablice: red igraca se prazni na mjestu (sablona = prvi prazan red iste tablice)
        # posudba van (izmjereno 15.10., Bedja -> Lorient u igri): redovi OSTAJU (igrac se vraca; Squad List ga po njima prikazuje 'On loan')
        found = 0
        for nm, base, st in () if loan_end else (('S8', self._X_S8B, 44), ('S1', X(0x24517d8), 24), ('S12', X(0x24ee690), 52), ('S10', X(0x24bf54c), 368),
                             ('S11', X(0x24e8c84), 192), ('S15', X(0x28b886c), 5628)):
            row = next((k for k in range(0, 60) if bytes(d[base + st * k:base + st * k + 8]) == pair), None)
            if row is None:
                continue
            tmpl = next((k for k in range(0, 60) if d[base + st * k] == 0xff and d[base + st * k + 1] == 0xff), None)
            if tmpl is not None:
                tb = bytes(d[base + st * tmpl:base + st * tmpl + st])
            elif nm == 'S15':
                raise ValueError('table %s: no empty row for the template' % nm)
            else:
                # puna tablica (39/39): predlozak praznog reda izmjeren na savu s praznim redovima
                tb = b'\xff\xff\0\0' + bytes(st - 4)
                if nm == 'S1':
                    tb = b'\xff\xff\0\0' + bytes(12) + b'\xff\xff\0\0' + bytes(4)
                elif nm == 'S12':
                    tb = b'\xff\xff\0\0' + bytes(44) + b'\xff\xff\0\0'
            W.append((base + st * row, tb))
            found += 1
        if not found and not loan_end:
            raise ValueError('player has no rows in the slot tables (promoted/loaned players are not supported)')
        # ---- S7 (24 B): rupa na mjestu
        F = Y(12607428)
        F = F - 24 * ((F - X(0x2474a00)) // 24)
        for k in range(0, 0 if loan_end else 200):
            o = F + 24 * k
            if bytes(d[o:o + 8]) == pair:
                W.append((o, b'\xff\xff\0\0\0\0\0\0\0\0'))
                break
        # ---- S13: red prihoda (prvi prazan)
        o13 = X(0x24ef0dc)
        for _k in range(60):
            o13 += 52
            if d[o13] == 0xff and d[o13 + 1] == 0xff:
                break
        else:
            raise ValueError('S13: no empty row')
        W.append((o13, pair))
        W.append((o13 + 32, struct.pack('<i', f) + struct.pack('<I', 2 if loan_end else 5)))

        # ---- nizovi: S14a/b/c (108 B), S9 (8 B): red se izbacuje, ostali se pomicu gore
        def compact(ref, st, lo=-40, hi=140):
            for k in range(lo, hi):
                o = ref + st * k
                if o > 0 and bytes(d[o:o + 8]) == pair:
                    e = o
                    while not empty(e + st):
                        e += st
                    blk = bytes(d[o + st:e + st]) + b'\xff\xff' + bytes(st - 2)
                    W.append((o, blk))
                    return True
            return False
        compact(X(0x251c434), 108)
        compact(self._PR_S14B, 108)
        compact(X(0x251da10), 108)
        compact(self._PR_REF['S9'][0], 8)
        if loan_end:
            # S15 (5628 B): red igraca ostaje, bajt +18 dobiva 0x04 (oznaka 'na posudbi', izmjereno na Bedji)
            bcode = self.club_code_of(buyer_offset) or 0
            for k in range(0, 60):
                o = X(0x28b886c) + 5628 * k
                if bytes(d[o:o + 8]) == pair:
                    W.append((o + 18, bytes([d[o + 18] | 0x04])))
                    # podaci posudbe u istom redu (Bedja: +0x88 datum, +0x98 kod kluba posudbe, +0x9c 2, +0xac 3)
                    W.append((o + 0x88, struct.pack('<I', date)))
                    W.append((o + 0x98, struct.pack('<II', bcode, 2)))
                    W.append((o + 0xac, struct.pack('<I', 3)))
                    break
            # S16 (80 B, kruzni red od 112): red posudbe s klubom (Bedja: 0x1b, datum, 3, 0xff, 0, 0, kod kluba, ffff, ffffffff, tag, pid, ...).
            # Po njemu Team Negotiations pokazuje 'On loan.' (Galesic bez njega: status '-')
            S16, CNT, k16 = self._s16_slot()   # brojac igre: red k = -16 + nizi bajt brojaca, kruzno 128 redaka
            row16 = struct.pack('<IIIIIIIII', 0x1b, date, 3, 0xff, 0, 0, bcode, 0xffff, 0xffffffff) + pair + \
                bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
            W.append((S16 + 80 * k16 + 4, row16))
            W.append((CNT, struct.pack('<I', struct.unpack_from('<I', d, CNT)[0] + 1)))
            # L4 (12 B): red igraca izlazi, ostali se pomicu gore, zadnji postaje prazan predlozak ffff0000 0 15000000 (kao igra)
            for k in range(-80, 80):
                o = X(0x246c13c) + 12 * k
                if bytes(d[o:o + 8]) == pair:
                    e = o
                    while not (d[e + 12] == 0xff and d[e + 13] == 0xff):
                        e += 12
                    W.append((o, bytes(d[o + 12:e + 12]) + bytes.fromhex('ffff00000000000015000000')))
                    break
        # ---- S2: red izlazi iz grupe c0, ubacuje se na pocetak grupe c3 (prodani)
        R = self._s2_list()
        rr = [bytes(d[R + 16 * k:R + 16 * k + 16]) for k in range(48)]
        ix = None if loan_end else next((i for i, r in enumerate(rr) if r[:8] == pair), None)  # posudba van: S2 se ne mijenja
        if ix is not None:
            del rr[ix]
            c3 = next((i for i, r in enumerate(rr) if r[12] == 0xc3), None)
            ins = pair + b'\0\0\0\0' + (b'\xc4' if loan_end else b'\xc3') + b'\0\0\0'
            if loan_end:
                c3 = next((i for i, r in enumerate(rr) if r[12] == 0xc4), None)
            if c3 is None:
                c3 = next((i for i, r in enumerate(rr) if r[12] > 0xc3 or r[:2] == b'\xff\xff'), len(rr))
            rr.insert(c3, ins)
            W.append((R, b''.join(rr[:48])))
        # ---- zapis igraca
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        big[r + 72:r + 80] = bytes.fromhex('ffff0000ffff0000' if loan_end else '0500c002ffff0000')
        big[r + 136:r + 140] = big[r + 140:r + 144]
        if not loan_end:
            struct.pack_into('<I', big, r + 148, date)  # posudba van: datum dolaska u moj klub ostaje
        if loan_end:
            struct.pack_into('<I', big, r + 152, loan_end)
        new, p0 = [], 0
        for c in chunks:
            new.append(bytes(big[p0:p0 + len(c)]))
            p0 += len(c)
        # ---- postava i sastav moje momcadi
        lo = F0 + LINEUP_OFF
        L = [int(x) for x in d[lo:lo + 35]]
        ids_after = [x for x in self.squad_ids()]
        ids_after = ids_after[:idx] + ids_after[idx + 1:] + [None]
        pos = pos or {}
        for i2, v in enumerate(L):
            if v == idx:
                L[i2] = -1
            elif v != 0xff and v > idx:
                L[i2] = v - 1
        for i2 in range(11):
            if L[i2] == -1:
                cand = [j for j in range(11, 23) if L[j] not in (-1, 0xff)]
                if not cand:
                    raise ValueError('no replacement in the lineup')
                gk_out = pos.get(pid, 5) == 0
                best = [j for j in cand if (pos.get(ids_after[L[j]], 5) == 0) == gk_out] or cand
                j = best[0]
                L[i2] = L[j]
                del L[j]
                L.append(0xff)
        L = [x for x in L if x != -1]
        L = L + [0xff] * (35 - len(L))
        bi = (buyer_offset - REC0) // STRIDE
        _blo = self.TAC0 + 600 * bi + 484
        bBL = [int(x) for x in d[_blo:_blo + bn]]
        used = {struct.unpack_from('<H', d, buyer_offset + self.NUM_OFF + 2 * k)[0] for k in range(bn)}
        num = next(x for x in range(2, 100) if x not in used)
        b = struct.unpack_from('<I', d, self.BUDGET)[0]
        self._allow = [(self.CH0 - 4, end_), (self.BUDGET, self.BUDGET + 4)] + [(o, o + len(bb)) for o, bb in W]
        for o, bb in W:
            d[o:o + len(bb)] = bb
        self._rebuild(new, end_)
        try:
            self._xfer_append(end_, tag, pid, self.club_code_of(buyer_offset) or 0, mycode, f, date)
        except Exception:
            pass
        d[lo:lo + 35] = bytes(L)
        for k in range(idx, n - 1):
            a = my + self.PAIR_OFF + 8 * k
            d[a:a + 8] = d[a + 8:a + 16]
            a = my + self.NUM_OFF + 2 * k
            d[a:a + 2] = d[a + 2:a + 4]
        struct.pack_into('<II', d, my + self.PAIR_OFF + 8 * (n - 1), 0xffff, 0)
        struct.pack_into('<H', d, my + self.NUM_OFF + 2 * (n - 1), 0)
        d[my + 1058] = n - 1
        struct.pack_into('<II', d, buyer_offset + self.PAIR_OFF + 8 * bn, tag, pid)
        struct.pack_into('<H', d, buyer_offset + self.NUM_OFF + 2 * bn, num)
        if sorted(bBL) == list(range(bn)):
            d[_blo + bn] = bn
        d[buyer_offset + 1058] = bn + 1
        struct.pack_into('<I', d, self.BUDGET, b + f)
        name = bytes(d[buyer_offset:buyer_offset + 48]).split(b'\0')[0].decode('utf-8', 'replace')
        if loan_end:
            self._meta_loanout(self.club_code_of(buyer_offset) or 0, mycode, tag, pid, f, loan_end, date)
            return 'loaned %d to %s for %d EUR (until %d/%d/%d)' % (pid, name, fee, loan_end >> 24, (loan_end >> 16) & 0xff, loan_end & 0xffff)
        self._beta_write = self.beta_ok   # pc190: prodaja na 60 MB (Arsenal Zubimendi: 65/66 redova kao igra)
        return 'sold %d to %s for %d EUR' % (pid, name, fee)

    def _meta_loanout(self, buyer_code, mycode, tag, pid, f, end_code, today):
        """Posudba van: red u tablici dogovora u repu sa statusom 5 (izvrseno), kao igra (Bedja -> Lorient 15.10.; Mayk, Kacavenda, Mmaee).
        Po tom redu igra igraca u Squad Listi prikazuje 'On loan'. Ponuda kluba posudbe za tog igraca (status 1-3) pretvara se u 5;
        ostale otvorene ponude za tog igraca se brisu (inace igra pokaze njih, npr. Zajc: 'Waiting for response: Full Transfer')."""
        d = self.d
        _ch, e2 = self._chunks()
        mbase = e2 + self.META0
        EMPTY = bytes.fromhex('ffff0000ffffffff00000000ffff0000ffffffffffffffffffff0000ffffffffffff0000000000000000000000000000ffff0000ffff000000000000')
        mrows, j0, hit = [], None, None
        for j in range(-60, 60):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv in (0, 0xffff):
                continue
            if j0 is None:
                j0 = j
            row = bytes(d[o2:o2 + 60])
            mine = struct.unpack_from('<I', row, 36)[0] == pid and struct.unpack_from('<I', row, 28)[0] == mycode
            st = struct.unpack_from('<I', row, 8)[0] & 0xff
            if mine and st in (1, 2, 3):
                if hit is None and struct.unpack_from('<I', row, 4)[0] == buyer_code:
                    hit = len(mrows)
                    mrows.append((sv, row))
                continue  # druga otvorena ponuda za ovog igraca: brise se
            mrows.append((sv, row))
        if j0 is None:
            j0 = -7   # pc205: nova karijera bez ijednog dogovora; tablica pocinje na j = -7 (svi formati)
        nold = sum(1 for j in range(-60, 60) if struct.unpack_from('<H', d, mbase + 60 * j)[0] not in (0, 0xffff))
        data = struct.pack('<IIIIIIIII', 0xffff, mycode, tag, pid, f, f, end_code, 0xffff, 0)
        if hit is not None:
            sv, row = mrows[hit]
            row = bytearray(row)
            struct.pack_into('<III', row, 4, buyer_code, 5, today)
            row[28:60] = data[4:]  # +24..27 (ffff + vrsta ponude) ostaje kao kod igre
            row[27] = 1             # vrsta dogovora: 1 = posudba (Bedja: ffff0001; ponude za transfer imaju 0)
            mrows[hit] = (sv, bytes(row))
        else:
            if j0 + len(mrows) + 1 > 58:
                raise ValueError('deal table in the tail is full')
            cbase = e2 + 16
            crows, k = [], 0
            while bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff' and k < 120:
                crows.append(struct.unpack_from('<H', d, cbase + 48 * k)[0])
                k += 1
            used = {x[0] for x in mrows} | set(crows) | {struct.unpack_from('<H', d, mbase + 60 * j)[0] for j in range(-60, 60)}
            lo = min(crows) if crows else min(x[0] for x in mrows)
            ser = next(s_ for s_ in range(lo, 0x400) if s_ not in used)
            # +24..27 = ffff 00 01: vrsta dogovora posudba (kao Bedjin red iz igre)
            mrows.append((ser, struct.pack('<HH', ser, 0) + struct.pack('<III', buyer_code, 5, today) + b'\xff' * 8 + b'\xff\xff\x00\x01' + data[4:]))
        allm = sorted(mrows, key=lambda t: t[0])
        tot = max(nold, len(allm))
        for n_ in range(tot):
            rb = allm[n_][1] if n_ < len(allm) else EMPTY
            d[mbase + 60 * (j0 + n_):mbase + 60 * (j0 + n_) + 60] = rb
        self._allow = list(getattr(self, '_allow', [])) + [(mbase + 60 * j0, mbase + 60 * (j0 + tot))]

    def inject_loan_offer(self, pid, club_offset, fee, end_code):
        """45 MB format: upisuje PONUDU kluba za posudbu mog igraca, kao da ju je klub poslao u igri (uzorak: Lorient -> Bedja 14.8.).
        Igrac u igri prihvati ponudu u Team Negotiations, a posudbu izvrsi sama igra.
        Upisuje: red u tablici dogovora (status 1, vrsta 1 = posudba), S16 red (0x1b, ceka odgovor), vijest u redu dogadjaja (0x2e)."""
        if self.ext and self.game27:
            raise ValueError('Loaning your player out is not unlocked yet on Football Life 2027 saves; do it in the game. The save was not touched.')
        self.pid_guard(pid)   # pc250
        if not self.ext:
            raise ValueError('only works on the verified (45 MB) format')
        d = self.d
        sq = self.my_squad_tags()
        if pid not in sq:
            raise ValueError('player is not in your squad')
        tag = sq[pid]
        mycode = self.my_club_code()
        code = self.club_code_of(club_offset)
        if not code:
            raise ValueError('club code not found')
        today = self.game_date_code()
        f = fee // 100
        _ch, e2 = self._chunks()
        mbase = e2 + self.META0
        mrows, j0 = [], None
        for j in range(-60, 60):
            o2 = mbase + 60 * j
            sv = struct.unpack_from('<H', d, o2)[0]
            if sv in (0, 0xffff):
                continue
            if j0 is None:
                j0 = j
            row = bytes(d[o2:o2 + 60])
            if struct.unpack_from('<I', row, 36)[0] == pid and (struct.unpack_from('<I', row, 8)[0] & 0xff) in (1, 2, 3, 4) \
                    and struct.unpack_from('<I', row, 4)[0] == code:
                raise ValueError('that club already has an open offer for this player (see Team Negotiations in the game)')
            mrows.append((sv, row))
        if j0 is None:
            j0 = -7   # pc205: nova karijera bez ijednog dogovora; tablica pocinje na j = -7 (svi formati)
        if j0 + len(mrows) + 1 > 58:
            raise ValueError('deal table in the tail is full')
        cbase = e2 + 16
        crows, k = [], 0
        while bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff' and k < 120:
            crows.append(struct.unpack_from('<H', d, cbase + 48 * k)[0])
            k += 1
        used = {x[0] for x in mrows} | set(crows)
        lo = min(crows) if crows else min(x[0] for x in mrows)
        ser = next(s_ for s_ in range(lo, 0x400) if s_ not in used)
        # red dogovora (kao Bedjin pri ponudi): serijski, kod kluba, status 1, datum ffff, ff*8, ffff 00 01 (posudba), podaci
        data = struct.pack('<IIIIIIII', mycode, tag, pid, f, f, end_code, 0xffff, 0)
        row = struct.pack('<HH', ser, 0) + struct.pack('<III', code, 1, 0xffff) + b'\xff' * 8 + b'\xff\xff\x00\x01' + data
        assert len(row) == 60
        allm = sorted(mrows + [(ser, row)], key=lambda t: t[0])
        # red dogadjaja: prvi prazan
        QB = X(0x244eb70)
        qo = None
        for k in range(0, 200):
            q = QB + 56 * k
            if struct.unpack_from('<I', d, q)[0] == 0xff:
                qo = q
                break
        if qo is None:
            raise ValueError('The game\'s event list in this save is full right now (this happens around the start of the transfer window). Simulate a day or two in the game, save, and try again. Nothing was written.')
        # S16: sljedeci red iza najnovijeg (kruzni, 112)
        S16, CNT, k16 = self._s16_slot()   # brojac igre: red k = -16 + nizi bajt brojaca, kruzno 128 redaka
        # --- upisi
        for n_, (_, rb) in enumerate(allm):
            d[mbase + 60 * (j0 + n_):mbase + 60 * (j0 + n_) + 60] = rb
        row16 = struct.pack('<IIIIIIIII', 0x1b, today, 3, 0xff, 1, 0, code, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
            bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
        d[S16 + 80 * k16 + 4:S16 + 80 * k16 + 80] = row16
        struct.pack_into('<I', d, CNT, struct.unpack_from('<I', d, CNT)[0] + 1)
        ev = struct.pack('<IIIIIIIIIIIIII', 0x2e, tag, pid, 0xffff, 0, 0xffff, 0, code, 0xffff, 0xffffffff, 0, 0xffff, 0xffff, today)
        d[qo:qo + 56] = ev
        self._allow = list(getattr(self, '_allow', [])) + [
            (mbase + 60 * j0, mbase + 60 * (j0 + len(allm))), (S16 + 80 * k16, S16 + 80 * k16 + 84), (CNT, CNT + 4), (qo, qo + 56)]
        return 'offer sent to the game (deal %d)' % ser

    def sell_player(self, pid, fee, buyer_offset, pos=None, loan_end=None):
        self.pid_guard(pid)   # pc250
        if self.ext and self.game27:
            if loan_end:
                raise ValueError('Loaning your player out is not unlocked yet on Football Life 2027 saves; do it in the game. The save was not touched.')
            return self.sell_pending_fl27(pid, fee, buyer_offset)   # pc274: provjereno u igri (Danns -> Bournemouth)
        if self.ext:
            if loan_end:
                # 15.10.: i uz sve dijelove Bedjinog zapisa (redovi, S15, dogovor status 5 + vrsta 1, S16, L4, S13) igra igraca vidi kao transfer.
                # Ceka mjerenje: save prije i odmah poslije prihvacanja ponude za posudbu u igri (pa 'nativni' upis kao kod dolaznih posudbi).
                raise ValueError('Loaning your player out from the app is temporarily disabled on this save format: the game still sees it as a transfer. Loan him out in the game until this is fixed.')
            return self.sell_outside_x(pid, fee, buyer_offset, pos, loan_end=loan_end)
        """Prodaja (ili posudba bez opcije otkupa kad je zadan loan_end = datum kraja kao kod ugovora): igrac odlazi u klub kupca, novac u transfer budzet, sastav i postava se poravnaju."""
        if pid in self.moved_this_window():
            raise ValueError('player has already changed clubs in this transfer window')
        my = self.club_offset()
        n = self._squad_len(my)
        idx = next((k for k in range(n) if struct.unpack_from('<I', self.d, my + self.PAIR_OFF + 8 * k + 4)[0] == pid), None)
        if idx is None:
            raise ValueError('player is not in your squad')
        if n <= 12:   # pc190: igra dopusta i manje (Arsenal 2027: 17 -> 16 -> 15)
            raise ValueError('your squad would be too small (the game needs at least 12 players)')
        bn = self._squad_len(buyer_offset)
        if bn >= 40 or buyer_offset == my:
            raise ValueError('buying club not possible')
        tag = struct.unpack_from('<I', self.d, my + self.PAIR_OFF + 8 * idx)[0]
        # postava: izbaci, pomakni indekse
        lo = F0 + LINEUP_OFF
        L = [int(x) for x in self.d[lo:lo + 35]]
        hole = None
        for i, v in enumerate(L):
            if v == idx:
                L[i] = -1
            elif v != 0xff and v > idx:
                L[i] = v - 1
        ids_after = [x for x in self.squad_ids()]
        ids_after = ids_after[:idx] + ids_after[idx + 1:] + [None]
        pos = pos or {}
        for i in range(11):
            if L[i] == -1:
                grp = lambda p: 0 if pos.get(p, 5) == 0 else 1
                want = None
                cand = [j for j in range(11, 23) if L[j] not in (-1, 0xff)]
                if cand:
                    # preferiraj istu "vrstu": golman s golmanom, ostali redom
                    gk_out = pos.get(pid, 5) == 0
                    best = [j for j in cand if (pos.get(ids_after[L[j]], 5) == 0) == gk_out] or cand
                    j = best[0]
                    L[i] = L[j]
                    del L[j]
                    L.append(0xff)
                else:
                    raise ValueError('no replacement in the lineup')
        L = [x for x in L if x != -1] + [0xff] * (35 - len([x for x in L if x != -1]))
        self.d[lo:lo + 35] = bytes(L)
        # sastav kluba: pomak ulijevo
        for k in range(idx, n - 1):
            a = my + self.PAIR_OFF + 8 * k
            self.d[a:a + 8] = self.d[a + 8:a + 16]
            a = my + self.NUM_OFF + 2 * k
            self.d[a:a + 2] = self.d[a + 2:a + 4]
        struct.pack_into('<II', self.d, my + self.PAIR_OFF + 8 * (n - 1), 0xffff, 0)
        struct.pack_into('<H', self.d, my + self.NUM_OFF + 2 * (n - 1), 0)
        # kupac
        struct.pack_into('<II', self.d, buyer_offset + self.PAIR_OFF + 8 * bn, tag, pid)
        used = {struct.unpack_from('<H', self.d, buyer_offset + self.NUM_OFF + 2 * k)[0] for k in range(bn)}
        num = next(x for x in range(2, 100) if x not in used)
        struct.pack_into('<H', self.d, buyer_offset + self.NUM_OFF + 2 * bn, num)
        # postava kluba kupca: novi igrac na kraj (rezerva), inace ga igra ne vidi u klubu (kao u ai_move)
        _bi = (buyer_offset - REC0) // STRIDE
        _blo = self.TAC0 + 600 * _bi + 484
        if sorted(int(x) for x in self.d[_blo:_blo + bn]) == list(range(bn)):
            self.d[_blo + bn] = bn
        b = struct.unpack_from('<I', self.d, self.BUDGET)[0]
        struct.pack_into('<I', self.d, self.BUDGET, b + fee // 100)
        name = bytes(self.d[buyer_offset:buyer_offset + 48]).split(b'\0')[0].decode('utf-8', 'replace')
        if loan_end:
            self._set_loan(pid, loan_end)       # vlasnik ostaje isti, ugovor se ne dira
        else:
            self.set_contract_start(pid, self.game_date_code())
        try:
            self._s2_drop(self._s2_stale([pid]))
        except Exception:
            pass
        self.fix_squad_counts()
        if loan_end:
            return 'loaned %d to %s for %d EUR (until %d/%d/%d)' % (pid, name, fee, loan_end >> 24, (loan_end >> 16) & 0xff, loan_end & 0xffff)
        return 'sold %d to %s for %d EUR' % (pid, name, fee)

    def player_wages(self):
        """{pid: godisnja placa u EUR} iz zapisa igraca."""
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        out = {}
        for k in range((len(big) - 144) // 156):
            r = 144 + 156 * k
            out[struct.unpack_from('<I', big, r + 48)[0]] = struct.unpack_from('<I', big, r + 128)[0] * 100
        return out

    def wage_commitment(self):
        """Zbroj godisnjih placa tvoje momcadi (zapisi igraca) + placa prihvacenih dogovora, u EUR.
        Salary budget u igri = (nepoznata baza) - ovaj zbroj; baza se kalibrira iz broja koji igra prikazuje."""
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        # pc235 (izvjestaj testera 03): isti PID moze imati vise igraca (npr. igrac u klubu i generirani slobodni igrac),
        # pa se zapis trazi po punom kljucu (tag, PID) iz sastava. Ako neki kljuc ne nadjemo, za njega vrijedi stari nacin (po PID-u).
        club = self.club_offset()
        keys = {struct.unpack_from('<II', self.d, club + self.PAIR_OFF + 8 * k) for k in range(self._squad_len(club))}
        keys = {k for k in keys if k[1] and (k[0] & 0xffff) != 0xffff}
        found = set()
        bypid = {}
        tot = 0
        for k in range((len(big) - 144) // 156):
            r = 144 + 156 * k
            key = struct.unpack_from('<II', big, r + 44)
            sal = struct.unpack_from('<I', big, r + 128)[0] * 100
            if key in keys and key not in found:
                found.add(key)
                tot += sal
            elif key[1] not in bypid:
                bypid[key[1]] = sal
        for t, p in keys - found:
            tot += bypid.get(p, 0)
        return tot + sum(x['salary'] for x in self.list_deals())

    def budget(self):
        return struct.unpack_from('<I', self.d, self.BUDGET)[0] * 100

    def player_values(self, pids=None):
        """{pid: vrijednost u jedinicama 100 EUR} iz zapisa igraca (+132, donjih 21 bit)."""
        chunks, _ = self._chunks()
        big = b''.join(chunks)
        out = {}
        for k in range((len(big) - 144) // 156):
            r = 144 + 156 * k
            pid = struct.unpack_from('<I', big, r + 48)[0]
            if pids is None or pid in pids:
                out[pid] = struct.unpack_from('<I', big, r + 132)[0] & 0x1FFFFF
        return out

    def set_values(self, vals):
        """pc197: tržišna vrijednost igraca (jedinice 100 EUR) u zapis igraca +132; gornjih 11 bitova ostaje."""
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        done = 0
        for k in range((len(big) - 144) // 156):
            r = 144 + 156 * k
            pid = struct.unpack_from('<I', big, r + 48)[0]
            if pid in vals:
                old = struct.unpack_from('<I', big, r + 132)[0]
                v = max(1, min(0x1FFFFF, int(vals[pid])))
                struct.pack_into('<I', big, r + 132, (old & ~0x1FFFFF) | v)
                done += 1
        new, p0 = [], 0
        for c in chunks:
            new.append(bytes(big[p0:p0 + len(c)]))
            p0 += len(c)
        self._allow = list(getattr(self, '_allow', [])) + [(self.CH0 - 4, end_)]
        self._rebuild(new, end_)
        if self.beta_ok:
            self._beta_write = True   # zapis igraca (zlib) na 60 MB je izmjeren (ugovori, juniori)
        return done

    def club_account(self):
        """pc341: sezonski racun kluba kako ga igra pokazuje (Club Account Balance): odmah iza transfer budzeta, EUR/100.
        Izmjereno 1.11.2026 na Liverpoolu (klasicni save) i provjereno na 45 MB, 60 MB i FL27 (isti raspored)."""
        B = self.BUDGET
        g = lambda k: struct.unpack_from('<i', self.d, B + k)[0] * 100
        return dict(broadcast=g(0x2c), sponsorship=g(0x30), fan_club=g(0x34))

    BUDGET_SETTINGS = ('gate', 'merch', 'prize', 'objective', 'options_in', 'fan_fav', 'options_pay')
    BSET_OFF = 0x3b38   # pc342: Budget Settings u igri, 7 x u32 iza transfer budzeta; 1 = Salary Budget, 0 = Transfer Budget
                        # (potvrdjeno 1.11.2026: Gate Receipts Bonus prebacen u igri na Transfer -> 1 postao 0; isto mjesto na svim formatima)

    def budget_settings(self):
        o = self.BUDGET + self.BSET_OFF
        v = [struct.unpack_from('<I', self.d, o + 4 * i)[0] for i in range(7)]
        if any(x not in (0, 1) for x in v):
            return None
        return {k: ('salary' if x else 'transfer') for k, x in zip(self.BUDGET_SETTINGS, v)}

    def set_budget_settings(self, vals):
        if self.budget_settings() is None:
            raise ValueError('Budget settings were not found in this save.')
        o = self.BUDGET + self.BSET_OFF
        for i, k in enumerate(self.BUDGET_SETTINGS):
            if k in vals:
                struct.pack_into('<I', self.d, o + 4 * i, 1 if vals[k] == 'salary' else 0)
        self._allow = list(getattr(self, '_allow', [])) + [(o, o + 28)]
        if not self.known_format and self.changed_outside(self._allow) is None:
            self._beta_write = True

    def adjust_budget(self, delta):
        """Transfer budzet += delta (EUR, moze biti negativan; ne ide ispod 0)."""
        b = struct.unpack_from('<I', self.d, self.BUDGET)[0]
        nb = max(0, b + int(delta) // 100)
        struct.pack_into('<I', self.d, self.BUDGET, nb)
        if self.beta_ok:
            self._beta_write = True   # pc195: budzet na 60 MB je izmjeren (citanje = igra na svim uzorcima)
        elif self.ext and self.game27:
            # pc276: FL27 budzet je na izmjerenoj adresi (kupnje/prodaje/posudbe provjerene u igri); bonusi, sell-on, osoblje, skauting, ulaznice
            self._fl27_layout_check()
            self._allow = list(getattr(self, '_allow', [])) + [(self.BUDGET, self.BUDGET + 4)]
            self._beta_write = True
        return nb * 100

    def _set_flag80(self, edits):
        """edits: {pid: True/False} -> postavi/spusti bit 0x80 na +8 zapisa igraca."""
        chunks, end = self._chunks()
        big = bytearray(b''.join(chunks))
        for pid, on in edits.items():
            pat = struct.pack('<I', pid)
            i = self._bf(big, pat)
            while i >= 0:
                if i >= 192 and (i - 192) % 156 == 0:
                    r = i - 48
                    if on:
                        big[r + 8] |= 0x80
                    else:
                        big[r + 8] &= 0x7f
                    break
                i = big.find(pat, i + 1)
            else:
                raise ValueError('player record %d not found' % pid)
        new, p = [], 0
        for c in chunks:
            new.append(bytes(big[p:p + len(c)]))
            p += len(c)
        self._rebuild(new, end)

    def swap_deal(self, old_pid, new_pid, fee, salary, release=None, end_year=2027):
        """Prenamijeni postojeci prihvaceni dogovor na drugog igraca i druge iznose (EUR).
        Budzet se ispravlja: stari iznos se vraca, novi skida."""
        deals = {x['pid']: x for x in self.list_deals()}
        if old_pid not in deals:
            raise ValueError('taj dogovor ne postoji u savu')
        if new_pid in deals and new_pid != old_pid:
            raise ValueError('taj igrac vec ima dogovor')
        if new_pid in self.my_squad_tags():
            raise ValueError('player is already in your club')
        if fee < 0 or salary <= 0:
            raise ValueError('neispravni iznosi')
        if not (2026 <= end_year <= 2032):
            raise ValueError('invalid contract year')
        old = deals[old_pid]
        new_tag = self.player_tag(new_pid)
        f, sal = fee // 100, salary // 100
        rel = (release if release is not None else fee) // 100
        b = struct.unpack_from('<I', self.d, self.BUDGET)[0]
        nb = b + old['fee'] // 100 - f
        if nb < 0:
            raise ValueError('not enough money in the transfer budget (%d EUR short)' % (-nb * 100))
        OT, OP = old['tag'], old_pid
        d = self.d
        P = lambda o, fmt, *v: struct.pack_into(fmt, d, o, *v)
        G = lambda o, fmt: struct.unpack_from(fmt, d, o)
        o = self.D0 + old['k'] * self.DS
        assert G(o + 12, '<2I') == (OT, OP)
        P(o + 12, '<2I', new_tag, new_pid)
        P(o + 44, '<i', -f)
        oc = self.C0 + old['k'] * self.CS
        assert G(oc, '<2I') == (OT, OP)
        P(oc, '<3I', new_tag, new_pid, sal)
        for k in range(60):
            oe = self.ENT0 + 56 * k + 4
            if G(oe, '<2I') == (OT, OP):
                P(oe, '<2I', new_tag, new_pid)
            op = self.POOL0 + 80 * k + 8
            if G(op, '<2I') == (OT, OP):
                P(op, '<2I', new_tag, new_pid)
        end = self._tail()
        for i in range(120):
            oa = end + 140 + 48 * i
            if G(oa, '<2I') == (OT, OP):
                P(oa, '<2I', new_tag, new_pid)
                P(oa + 8, '<2I', sal, rel)
                P(oa + 16, '<I', (31 << 24) | (8 << 16) | end_year)
                break
        for i in range(120):
            ob = end + 54752 + 60 * i
            if G(ob + 16, '<2I') == (OT, OP):
                P(ob + 16, '<2I', new_tag, new_pid)
                P(ob + 24, '<2I', f, f)
                break
        P(self.BUDGET, '<I', nb)
        # kao u provjerenom testu: samo novom igracu se spusta bit 0x80 (stari ostaje kako jest)
        self._set_flag80({new_pid: False})
        return 'deal reassigned: %d -> %d, fee %d, wage %d, budget %d' % (old_pid, new_pid, fee, salary, nb * 100)

    # ---- potpisivanje igraca (izravan dolazak, kao sto igra zapise na dan dolaska)
    PAIR_OFF = 328
    NUM_OFF = 662  # u16 brojevi dresova, paralelno sa sastavom (club+662+2*i)

    def find_club_of(self, pid):
        """(offset kluba, indeks u sastavu) kluba cija momcad sadrzi pid; None ako nijedan."""
        n = 0
        while REC0 + n * STRIDE + STRIDE <= 6000000:
            o = REC0 + n * STRIDE
            for i in range(40):
                tag, p = struct.unpack_from('<II', self.d, o + self.PAIR_OFF + 8 * i)
                if tag & 0xffff == 0xffff:
                    break
                if p == pid:
                    return o, i
            n += 1
        return None

    def _squad_len(self, o):
        n = 0
        for i in range(40):
            if struct.unpack_from('<I', self.d, o + self.PAIR_OFF + 8 * i)[0] & 0xffff == 0xffff:
                break
            n += 1
        return n

    def squad_numbers(self):
        """Brojevi dresova mog kluba: {indeks u sastavu: broj}."""
        o = self.club_offset()
        n = self._squad_len(o)
        return {i: struct.unpack_from('<H', self.d, o + self.NUM_OFF + 2 * i)[0] for i in range(n)}

    def set_squad_numbers(self, nums):
        """nums: {indeks: broj}. Brojevi 1-99, bez duplikata u klubu."""
        o = self.club_offset()
        n = self._squad_len(o)
        cur = self.squad_numbers()
        new = dict(cur)
        for k, v in nums.items():
            k, v = int(k), int(v)
            if v == 0:
                continue
            if not 0 <= k < n:
                raise ValueError('neispravan indeks igraca')
            if not 1 <= v <= 99:
                raise ValueError('broj dresa mora biti 1-99')
            new[k] = v
        vals = [v for v in new.values() if v]
        if len(vals) != len(set(vals)):
            raise ValueError('dva igraca imaju isti broj dresa')
        for k, v in new.items():
            if v != cur.get(k):
                struct.pack_into('<H', self.d, o + self.NUM_OFF + 2 * k, v)

    # ---- promocija omladinca u prvu momcad (prosireni 45 MB format; pomaci izmjereni na pravom potpisu u igri) ----
    @property
    def _PR_REF(self):
        return dict(S2=(X(0x23ebb00), 16), S1=(X(0x2451ad8), 24), L5=(X(0x24542c4), 12), L4=(X(0x246c13c), 12), S8=(X(0x2475514), 44),
                   S9=(X(0x2475b70), 8), S12=(X(0x24eed10), 52), S14a=(X(0x251c434), 108), S14c=(X(0x251da10), 108), S15=(X(0x28e47ec), 5628))
    @property
    def _PR_S14B(self):
        return X(0x2519ebc)
    @property
    def _PR_S10(self):
        if not self.ext:
            return (Y(self._CJ['S10']), 368)   # pc201: klasicni format (izmjereno)
        return (X(0x24bf54c), 368)
    _PR_S15 = bytes.fromhex('0d0019000000000054050400ffff0000ea07070effff000000000000000000000d0019000100000000000000000000000000000003')

    # ---- pc201: klasicni (19,9 MB) format: slobodan igrac i junior u prvu momcad ----
    # Izmjereno 29.10.2026 na pravim potezima u igri (Palermo, tester): slobodan igrac pid 55245 (A->B) i junior pid 55304 (B->C).
    # Tablice imaju stalne adrese u klasicnom formatu; novi red ide u PRVI prazan (ffff) red od pocetka tablice (provjereno
    # na svim tablicama na oba poteza), S1 iza zadnjeg zauzetog, S2 se umece iza zadnjeg igraca momcadi, S7 u prazan red iznad bloka.
    _CJ = dict(S2=0xb7f8bc, S1=0xbe5fc8, L5=0xbe8a48, L4=0xc008e4, S7=0xc05fac, S8=0xc06264, S10=0xc5098c, S11=0xc7a014, S13=0xc7f960,
               S14a=0xcab1f8, S14b=0xcab1f8 + 0x15dc, S14c=0xcab1f8 + 0x2bb8, S15=0x104b138, ARR=0xc01564)
    _CJ_S10 = bytes.fromhex('1d1d1d1d1d1d1d1d1d1d1d1d1d1d000000000000000000000000000000000000000010270000000000006a0c292200007902a100c720c206c616030ea612121e261ee8210c1400000000000000003a258122fe1fb60bf0149f15340a8015d20050200000')
    _CJ_S11 = bytes.fromhex('1c282828292a2b2c2d2d2e2f303031323233343536373838393a3a3b3b3b3c3e3f3f3f3f3f3f3e')
    _CJ_S15 = bytes.fromhex('ffffffff0000000014000400ffff0000e907081fffff000000000000000000003a813b000100000000000000000000000000000003000000ffff0000000000000500000000000000')

    def classic_join(self, pid, kind, salary, end_year, number=None):
        """kind 'fa' = slobodan igrac, 'youth' = junior iz omladinske skole. Upisuje isto sto igra upise kad potpis napravi sama."""
        g27 = bool(self.ext and self.game27)
        if self.ext and not g27:
            raise ValueError('classic_join is for the classic 19.9 MB format only')
        if g27:
            if kind != 'youth':
                raise ValueError('internal: on FL27 free agents go through the game deal (sign_outside_x)')
            if not self.FL27_YOUTH_OK:
                raise ValueError('Signing youth players is not unlocked yet on Football Life 2027 saves; do it in the game. The save was not touched.')
            self._fl27_layout_check()
        d = self.d
        C = {k: Y(v) for k, v in self._CJ.items()}
        my = self.club_offset()
        n = self._squad_len(my)
        if n >= 40:
            raise ValueError('squad is full (40)')
        if pid in self.my_squad_tags():
            raise ValueError('player is already in your club')
        if not (2000 < end_year < 2100) or salary <= 0:
            raise ValueError('invalid contract terms')
        if number is not None and not (1 <= number < 100):
            raise ValueError('invalid shirt number')
        youth = kind == 'youth'
        o10y = None
        if youth:
            for k in range(160):
                o = C['S10'] + 368 * k
                if struct.unpack_from('<I', d, o + 4)[0] == pid:
                    o10y = o
                    break
            if o10y is None:
                raise ValueError('player is not in the youth table')
        elif self._free_code(pid) != 0xffffffff:
            raise ValueError('player is not a free agent (has a club)')
        tag = self.player_tag(pid)
        pair = struct.pack('<II', tag, pid)
        date = self.game_date_code()
        ds = struct.pack('<I', date)
        mycode = self.my_club_code()
        sq = {bytes(d[my + self.PAIR_OFF + 8 * k:my + self.PAIR_OFF + 8 * k + 8]) for k in range(n)}

        def ep(o):
            return d[o] == 0xff and d[o + 1] == 0xff

        def check_table(nm, base, st, lim=120):
            # zastita: tablica mora biti tamo gdje je izmjerena (barem jedan igrac momcadi medju prvih redova)
            if any(bytes(d[base + st * k:base + st * k + 8]) in sq for k in range(lim)):
                return
            if st == 12:
                # pc205: L5/L4 su popisi dolazaka; u saveu mogu biti samo igraci koji su vec otisli (Chelsea G1). Provjera oblika:
                # redovi su (tag, pid, vrsta < 32) ili prazni ffff 0000 0000 xx, a praznih ima puno
                rows = [bytes(d[base + 12 * k:base + 12 * k + 12]) for k in range(60)]
                emp = sum(1 for r_ in rows if r_[:2] == b'\xff\xff' and not any(r_[2:8]))
                okr = all(r_[:2] == b'\xff\xff' or (0 < struct.unpack_from('<I', r_, 4)[0] < 400000 and struct.unpack_from('<I', r_, 8)[0] < 32) for r_ in rows[:20])
                if emp >= 15 and okr:
                    return
            if nm.startswith('S14'):
                # pc205: S14a moze biti potpuno prazna u novoj karijeri (Man City 2025): prvih 20 redova pocinje s ffff
                if all(d[base + st * k] == 0xff and d[base + st * k + 1] == 0xff for k in range(20)):
                    return
            raise ValueError('table %s is not where expected in this save; nothing was written' % nm)

        def first_ff(nm, base, st, lim=200):
            check_table(nm, base, st)
            for k in range(lim):
                o = base + st * k
                if ep(o):
                    return o
            raise ValueError('table %s: no empty row' % nm)
        W = []
        # S2 (16 B): umetni iza zadnjeg igraca momcadi, tip c1
        R2 = C['S2']
        check_table('S2', R2, 16, 50)
        rows = [bytes(d[R2 + 16 * k:R2 + 16 * k + 16]) for k in range(48)]
        ip = next((i for i, r_ in enumerate(rows) if r_[:2] == b'\xff\xff' or r_[:8] not in sq), None)
        if ip is None or rows[-1][:2] != b'\xff\xff':
            raise ValueError('S2: no room')
        rows.insert(ip, pair + b'\0\0\0\0\xc1\0\0\0')
        W.append((R2, b''.join(rows[:48])))
        # S1 (24 B): iza zadnjeg zauzetog; 8 B iz zapisa igraca (+116) za slobodnog igraca, nule za juniora
        check_table('S1', C['S1'], 24, 60)
        last = None
        for k in range(80):
            o = C['S1'] + 24 * k
            if not ep(o) and any(d[o:o + 8]):
                last = k
        o1 = C['S1'] + 24 * (0 if last is None else last + 1)
        if any(d[o1:o1 + 8]) and not ep(o1):
            raise ValueError('S1: no empty row')
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        recs = self._player_recs([pid])[3]
        r = recs.get(pid)
        if r is None:
            raise ValueError('player record not found')
        s1mid = bytes(big[r + 116:r + 124]) if not youth else b'\0' * 8
        W.append((o1, pair + s1mid + ds + b'\0\0\0\0'))
        # L5 / L4 (12 B): vrsta dolaska (izmjereno: kupnja 7/6, junior 6/5, slobodan igrac 5/4)
        W.append((first_ff('L5', C['L5'], 12), pair + struct.pack('<I', 6 if youth else 5)))
        W.append((first_ff('L4', C['L4'], 12), pair + struct.pack('<I', 5 if youth else 4)))
        # S7 (24 B): prazan red neposredno iznad bloka igraca. pc205 (Man City 19.9 MB, nativno 4.->5.8.2025): tablica raste PREMA GORE
        # i iznad svog pocetka (redovi -1, -2 ... su ffff) -> zadnji (najnizi) prazan red ciji je sljedeci red igrac moje momcadi
        # (Palermo: red 2 iznad bloka od reda 3; Man City: red -1 iznad bloka od reda 0, junior zatim -2)
        check_table('S7', C['S7'], 24, 60)
        o7 = None
        for k in range(-40, 60):
            o = C['S7'] + 24 * k
            if ep(o) and bytes(d[o + 24:o + 32]) in sq:
                o7 = o
        if o7 is None:
            raise ValueError('This save has no free row in one of the game\'s squad tables (S7), so the app cannot add this player safely yet. Sign him in the game this time. Nothing was written.')
        # pc208: drugi u16 retka = kao u retku 0 bloka (Man City 0x90fe, Palermo 0); igra je tako upisala Novicica i Palermo juniora
        hi7 = struct.unpack_from('<H', d, C['S7'] + 10)[0] if bytes(d[C['S7']:C['S7'] + 8]) in sq else 0
        if g27:
            hi7 = 0   # pc278: FL27 junior (izmjereno 31.8.2026): S7 vrijednost 0x28, drugi u16 0
        W.append((o7, pair + struct.pack('<HH', (0x28 if g27 else 0x3c) if youth else 0x1e, hi7) + b'\0' * 12))
        # S8 (44 B), S13 (52 B), S14a/b/c (108 B), S15 (5628 B): prvi prazan red
        W.append((first_ff('S8', C['S8'], 44), pair + b'\0' * 36))
        o13 = first_ff('S13', C['S13'], 52)
        W.append((o13, pair + struct.pack('<I', (5 if g27 else 15) if youth else 9) + b'\0' * 36))
        for nm in ('S14a', 'S14b', 'S14c'):
            W.append((first_ff(nm, C[nm], 108), pair))
        s15 = bytearray(self._CJ_S15)
        s15[16:20] = ds
        s15[32:36] = struct.pack('<I', mycode)
        if g27:
            s15[64] = 0   # pc278: FL27 junior: igra ostavlja 0 (klasicni 5)
        W.append((first_ff('S15', C['S15'], 5628), pair + bytes(s15)))
        if youth:
            # S10: red juniora ostaje, mijenja se status (izmjereno 0b -> 03, isto kao na 45 MB)
            W.append((o10y + 316, b'\x03'))
            # pc208: igra pri potpisu juniora digne bajtove +8..+21 za 9 (Palermo 0x32->0x3b, 0x14->0x1d; Man City 0x14->0x1d, 0x45 ostaje)
            W.append((o10y + 8, bytes(v if v >= 0x45 else min(v + 9, 0x45) for v in d[o10y + 8:o10y + 22])))
        else:
            o10 = first_ff('S10', C['S10'], 368)
            W.append((o10, pair + self._CJ_S10))
            W.append((o10 + 248, bytes.fromhex('0f000000000000000000000505')))
            W.append((o10 + 344, bytes.fromhex('0e00000028')))
            o11 = first_ff('S11', C['S11'], 192)
            W.append((o11, pair + self._CJ_S11))
            # lista dolazaka (20 B, najnoviji prvi): datum, 0, tip 1
            A0 = C['ARR']
            ar = [bytes(d[A0 + 20 * k:A0 + 20 * k + 20]) for k in range(10)]
            if ar[-1][:2] == b'\xff\xff' and (ar[0][:2] == b'\xff\xff' or ar[0][:8] in sq or any(x[:8] in sq for x in ar[:4])):
                ar.insert(0, pair + ds + b'\0\0\0\0' + b'\1\0\0\0')
                W.append((A0, b''.join(ar[:10])))
        # zapis igraca: natjecanja kao suigraci (bez dodatnog unosa), placa, ugovor, datum; junior dobije kod kluba na +136
        sqids = set(self.squad_ids())
        ent = {}
        for k in range((len(big) - 144) // 156):
            rr = 144 + 156 * k
            if struct.unpack_from('<I', big, rr + 48)[0] in sqids:
                for j in range(6):
                    cid, code = struct.unpack_from('<HH', big, rr + 64 + 4 * j)
                    if cid < 0x1000 and code and cid != 0xffff:
                        ent.setdefault(cid, code)
        items = sorted(ent.items())[:6]
        if items:
            big[r + 64:r + 88] = b''.join(struct.pack('<HH', c, v) for c, v in items) + b'\xff\xff\0\0' * (6 - len(items))
        struct.pack_into('<I', big, r + 128, salary // 100)
        if youth:
            struct.pack_into('<I', big, r + 136, mycode)
        end = (31 << 24) | (8 << 16) | end_year
        struct.pack_into('<I', big, r + 144, end)
        struct.pack_into('<I', big, r + 148, date)
        new, p0 = [], 0
        for c in chunks:
            new.append(bytes(big[p0:p0 + len(c)]))
            p0 += len(c)
        used = {struct.unpack_from('<H', d, my + self.NUM_OFF + 2 * k)[0] for k in range(n)}
        if number is None:
            number = next(x for x in range(2, 100) if x not in used)
        elif number in used:
            raise ValueError('shirt number is taken')
        sidx = self.club_idx_of_offset(my)
        blo = self.TAC0 + 600 * sidx + 484
        BL = [int(x) for x in d[blo:blo + n]]
        for o, b in W:
            d[o:o + len(b)] = b
        self._rebuild(new, end_)
        struct.pack_into('<II', d, my + self.PAIR_OFF + 8 * n, tag, pid)
        struct.pack_into('<H', d, my + self.NUM_OFF + 2 * n, number)
        if sorted(BL) == list(range(n)) and d[blo + n] != n:
            d[blo + n] = n
        if g27:
            # pc279: FL27 igra novog igraca doda i u moj popis postave (F0+480, prvo ff mjesto); bez toga igra pokaze prazno mjesto 'GK 0'
            lo = F0 + LINEUP_OFF
            L = list(d[lo:lo + 40])
            if n not in L and 0xff in L:
                d[lo + L.index(0xff)] = n
        d[my + 1058] = n + 1
        self._join_tail(tag, pid, salary // 100, end, 0 if not youth else None, date)
        try:
            self._sync_tail([pid], {pid: (salary // 100, end)})
        except Exception:
            pass
        if g27:
            # pc278: FL27 junior: isti zapisi kao igra (osim izbora broja i serijskog), provjereno na usporedbi; dopusteni samo ovi dijelovi
            self._allow = list(getattr(self, '_allow', [])) + [(o, o + len(b)) for o, b in W]
            self._beta_write = True
        return '%s %d joined (no. %d)' % ('youth player' if youth else 'free agent', pid, number)

    def _join_tail(self, tag, pid, sal100, end_code, val100=None, date=None):
        """pc206b: igra za SVAKOG igraca u vlasnistvu drzi (1) red ugovora u repu (48 B na e2+16: serijski, klub, status 5,
        datum dolaska, ff*10, par, placa/100, vrijednost/100, kraj) i (2) red u popisu igraca u repu (16 B: par + 7 nula + 1 bajt).
        Posudjeni igraci ih nemaju. Bez njih igra padne kad se igrac oznaci u Team Management (Attigah, Man City 29.10.).
        Serijski = najveci u ugovorima i dogovorima + 1 (izmjereno: Ogiwara 0x2b, Novicic 0x2c; Palermo 0x31, 0x36)."""
        d = self.d
        e2 = self._chunks()[1]
        pr = struct.pack('<II', tag, pid)
        if date is None:
            date = self.game_date_code()
        # 1) red ugovora
        used, ka, have = set(), None, False
        for k in range(80):
            oa = e2 + 16 + 48 * k
            if bytes(d[oa + 4:oa + 8]) == b'\xff\xff\xff\xff':
                if ka is None and struct.unpack_from('<I', d, oa + 28)[0] == 0xffff:
                    ka = k
                continue
            used.add(struct.unpack_from('<H', d, oa)[0])
            if bytes(d[oa + 28:oa + 36]) == pr:
                have = True
        mb = e2 + self.META0
        for j in range(-7, 60):
            o2 = mb + 60 * j
            if bytes(d[o2 + 28:o2 + 32]) != b'\xff\xff\xff\xff':
                used.add(struct.unpack_from('<H', d, o2)[0])
        used.discard(0xffff)
        if not have and ka is None:
            raise ValueError('the contract table in the save is full; sign him in the game this time. Nothing was written.')
        # 2) popis igraca (20 B): mjesto se trazi preko igraca momcadi
        my = self.club_offset()
        n = self._squad_len(my)
        reg = bytes(d[e2 + 0x60000:e2 + 0x90000])
        pos = []
        for k in range(n):
            q = bytes(d[my + self.PAIR_OFF + 8 * k:my + self.PAIR_OFF + 8 * k + 8])
            if q == pr:
                continue
            i = reg.find(q + b'\0' * 7)
            if i >= 0:
                pos.append(i)
        t_have = reg.find(pr + b'\0' * 7) >= 0
        t_new = None
        if not t_have:
            if not pos:
                raise ValueError('the squad list in the save was not found; sign him in the game this time. Nothing was written.')
            b0 = min(pos)
            if any((x - b0) % 16 for x in pos):
                raise ValueError('the squad list in the save has an unknown shape; sign him in the game this time. Nothing was written.')
            for k in range(200):
                o = b0 + 16 * k
                if o + 16 > len(reg):
                    break
                # pc409: slobodan red = 0xffff + 9 nula; zadnja 3 bajta igra zna ostaviti (Arsenal, klasicni save: 'ffff0000 ... 00d6a2cb'),
                # pa su prije svi slobodni redovi izgledali zauzeto ("squad list is full" s 26 igraca). Bajt +12 mora biti 0: red
                # 'ffff... 0d000000' iza popisa je pocetak druge tablice.
                if struct.unpack_from('<I', reg, o)[0] == 0xffff and not any(reg[o + 4:o + 13]):
                    t_new = e2 + 0x60000 + o
                    break
            if t_new is None:
                raise ValueError('the squad list in the save is full; sign him in the game this time. Nothing was written.')
        if val100 is None or sal100 is None or end_code is None:
            big, _c, _e, recs = self._player_recs([pid])
            if pid not in recs:
                raise ValueError('player record not found; nothing was written')
            r_ = recs[pid]
            if val100 is None:
                v = struct.unpack_from('<I', big, r_ + 132)[0]
                val100 = 0 if v == 0xffffffff else v
            if sal100 is None:
                sal100 = struct.unpack_from('<I', big, r_ + 128)[0]
            if end_code is None:
                end_code = struct.unpack_from('<I', big, r_ + 144)[0]
        al = []
        if not have:
            oa = e2 + 16 + 48 * ka
            al.append((oa, oa + 48))
            ser = (max(used) + 1) if used else 0x2b
            mc = self.my_club_code() or 0x2b400c
            struct.pack_into('<HH', d, oa, ser, 0)
            struct.pack_into('<II', d, oa + 4, mc, 5)
            struct.pack_into('<I', d, oa + 12, date)
            d[oa + 16:oa + 26] = b'\xff' * 10
            d[oa + 28:oa + 36] = pr
            struct.pack_into('<III', d, oa + 36, sal100, val100, end_code)
        if t_new is not None:
            d[t_new:t_new + 15] = pr + b'\0' * 7
            al.append((t_new, t_new + 16))
        self._allow = list(getattr(self, '_allow', [])) + al
        return True

    def join_tail_missing(self):
        """pc206b: igraci u vlasnistvu (ne posudjeni) kojima fali red ugovora ili red popisa u repu (stare verzije appa:
        potpis slobodnog igraca / juniora / izravna kupnja). Igra na takvom igracu padne u Team Management."""
        d = self.d
        e2 = self._chunks()[1]
        my = self.club_offset()
        n = self._squad_len(my)
        mc = self.my_club_code()
        have = set()
        for k in range(80):
            oa = e2 + 16 + 48 * k
            if bytes(d[oa + 4:oa + 8]) != b'\xff\xff\xff\xff':
                have.add(bytes(d[oa + 28:oa + 36]))
        reg = bytes(d[e2 + 0x60000:e2 + 0x90000])
        prs = [bytes(d[my + self.PAIR_OFF + 8 * k:my + self.PAIR_OFF + 8 * k + 8]) for k in range(n)]
        # A list row is a full (tag, PID) key plus metadata, not necessarily
        # seven zero bytes. Native rows with metadata 1/2 are still present.
        # Establish the 16-byte alignment from >=11 existing zero-metadata
        # squad rows; accept nonzero metadata only with an owned contract.
        anchors = [reg.find(q + b'\0' * 7) for q in prs]
        anchors = [a for a in anchors if a >= 0]
        align = anchors[0] % 16 if self.ext and len(anchors) >= 11 and len({a % 16 for a in anchors}) == 1 else None   # pc317: i 45 MB
        owned = {bytes(d[e2 + 16 + 48*k + 28:e2 + 16 + 48*k + 36])
                 for k in range(80)
                 if struct.unpack_from('<I', d, e2 + 16 + 48*k + 4)[0] == mc
                 and d[e2 + 16 + 48*k + 8] == 5}
        def listed_with_metadata(q):
            if align is None or q not in owned:
                return False
            for flag in (1, 2):
                # 60 MB: oznaka odmah iza kljuca; 45 MB (pc317, Ayden Heaven u Man Utd saveu): oznaka na 7. bajtu iza kljuca
                for pat in ((q + bytes([flag]) + b'\0' * 6,) if self.fmt60 else (q + b'\0' * 6 + bytes([flag]),)):
                    at = reg.find(pat)
                    while at >= 0:
                        if at % 16 == align:
                            return True
                        at = reg.find(pat, at + 1)
            return False
        big, _c, _e, recs = self._player_recs([struct.unpack_from('<I', q, 4)[0] for q in prs])
        out = []
        for q in prs:
            pid = struct.unpack_from('<I', q, 4)[0]
            if q in have and (reg.find(q + b'\0' * 7) >= 0 or listed_with_metadata(q)):
                continue
            r_ = recs.get(pid)
            if r_ is None:
                continue
            a, b = struct.unpack_from('<II', big, r_ + 136)
            F = 0xffffffff
            if (a, b) in ((F, mc), (mc, F), (F, F)):
                out.append(pid)
        return out

    def fix_join_tail(self):
        miss = self.join_tail_missing()
        for pid in miss:
            self._join_tail(self.player_tag(pid), pid, None, None)
        self._beta_write = self.beta_ok
        return 'added the missing contract rows for %d player(s)' % len(miss)

    def can_promote(self):
        return True   # pc201: klasicni format preko classic_join

    def youth_in_table(self, pid):
        """Offset retka omladinca u tablici 368 B (par tag,pid) ili None."""
        base, st = self._PR_S10
        d = self.d
        for k in range(0, 400):
            o = base + st * k
            if struct.unpack_from('<I', d, o + 4)[0] == pid:
                return o
        return None

    def promote_youth(self, pid, salary, end_year, number=None):
        """Omladinac -> prva momcad, kao 'Potpisi' u igri (ugovor, broj, sve po-slotne tablice). salary u EUR/god."""
        if not self.ext or self.game27:   # pc278: FL27 junior = klasicni recept (izmjeren na pravom potpisu u igri)
            return self.classic_join(pid, 'youth', salary, end_year, number)
        if not self.can_promote():
            raise ValueError('Signing youth players only works on the verified (45 MB) save format')
        d = self.d
        my = self.club_offset()
        n = self._squad_len(my)
        if n >= 40:
            raise ValueError('squad is full (40)')
        if pid in self.my_squad_tags():
            raise ValueError('player is already in the first team')
        if not (2000 < end_year < 2100) or salary <= 0:
            raise ValueError('invalid contract terms')
        o10 = self.youth_in_table(pid)
        if o10 is None:
            raise ValueError('player is not in the youth table')
        tag = struct.unpack_from('<I', d, o10)[0]
        pair = struct.pack('<II', tag, pid)
        date = self.game_date_code()
        ds = struct.pack('<I', date)
        mycode = self.my_club_code()
        sq = {bytes(d[my + self.PAIR_OFF + 8 * k:my + self.PAIR_OFF + 8 * k + 8]) for k in range(n)}
        W = []

        def empty(o):
            return (d[o] == 0xff and d[o + 1] == 0xff) or not any(d[o:o + 8])

        def nxt(name, ref, st):
            last = None
            for k in sorted(range(-70, 70), key=abs):
                o = ref + st * k
                if o > 0 and bytes(d[o:o + 8]) in sq:
                    last = o
                    break
            if last is None:
                raise ValueError('table %s: your players are not where expected' % name)
            while bytes(d[last + st:last + st + 8]) in sq:
                last += st
            o = last + st
            for _k in range(80):
                if empty(o):
                    return o
                o += st  # redovi otpustenih/odlazecih igraca ostaju u tablici: novi ide u prvi prazan red iza njih
            raise ValueError('table %s: no empty row after the last player' % name)
        pos = {}
        for nm, (ref, st) in self._PR_REF.items():
            if nm == 'S9' or (self.fmt60 and nm in ('S2', 'S1', 'S8', 'S12', 'S15')):
                continue
            pos[nm] = nxt(nm, ref, st)
        if self.fmt60:
            # pc191 (60 MB, izmjereno: Arsenal Samuel Kal 07->08): S1/S8/S12/S15 = prvi prazan red od pocetka tablice,
            # S2 = treca lista, red iza zadnjeg igraca koji je jos u momcadi (otisli ostaju na kraju)
            def first_ff(base, st, name, lim=200):
                for k in range(lim):
                    o = base + st * k
                    if d[o] == 0xff and d[o + 1] == 0xff:
                        return o
                raise ValueError('table %s: no empty row' % name)
            _k1 = self._s1_free60()
            if _k1 is None:
                raise ValueError('table S1: no empty row')
            pos['S1'] = X(0x24517d8) + 24 * _k1
            pos['S8'] = first_ff(self._X_S8B, 44, 'S8', 60)
            pos['S12'] = first_ff(X(0x24ee690), 52, 'S12', 60)
            pos['S15'] = first_ff(X(0x28b886c), 5628, 'S15', 60)
            R2 = self._s2_list()
            rr2 = [bytes(d[R2 + 16 * k:R2 + 16 * k + 16]) for k in range(48)]
            ip = next((i for i, r_ in enumerate(rr2) if r_[:2] == b'\xff\xff' or r_[:8] not in sq), None)
            if ip is None:
                raise ValueError('S2: no room')
            rr2.insert(ip, pair + b'\0\0\0\0\xc1\0\0\0')
            W.append((R2, b''.join(rr2[:48])))
        else:
            W.append((pos['S2'], pair + b'\0\0\0\0\xc1\0\0\0'))
        W.append((pos['S1'], pair + b'\0' * 8 + ds + b'\0\0\0\0'))
        W.append((pos['L5'], pair + struct.pack('<I', 6)))
        W.append((pos['L4'], pair + struct.pack('<I', 5)))
        W.append((pos['S8'], pair + b'\0' * 36))
        o9 = self._PR_REF['S9'][0]  # S9 (8 B): kratka lista, ne mora sadrzavati igrace sastava (npr. nakon otpustanja): prvi prazan red od izmjerenog pocetka
        for _k in range(80):
            if empty(o9):
                break
            o9 += 8
        else:
            raise ValueError('table S9: no empty row')
        W.append((o9, pair))
        W.append((pos['S12'], pair + struct.pack('<I', 0x04 if self.fmt60 else 0x18)))   # 60 MB (Kal): 0x04
        W.append((pos['S12'] + 40, b'\0'))
        W.append((pos['S14a'], pair))
        W.append((pos['S14c'], pair))
        o14 = self._PR_S14B
        for _k in range(80):
            if empty(o14):
                break
            o14 += 108
        else:
            raise ValueError('table S14b: no empty row')
        W.append((o14, pair))
        s15 = self._PR_S15.replace(bytes.fromhex('ea07070e'), ds).replace(bytes.fromhex('0d001900'), struct.pack('<I', mycode))
        if self.fmt60:
            # 60 MB (Kal, izmjereno): bez kluba odakle dolazi (+8 ffffffff), +16 = 0x0014, +72 = 2
            b15 = bytearray(pair + s15)
            b15[8:12] = b'\xff\xff\xff\xff'
            b15[16:18] = b'\x14\x00'
            W.append((pos['S15'], bytes(b15)))
            W.append((pos['S15'] + 72, b'\x02'))
        else:
            W.append((pos['S15'], pair + s15))
        # S10: red omladinca ostaje, samo se mijenja status
        W.append((o10 + 316, b'\x03'))
        # S7: poredano silazno po oznaci, prazni redovi na vrhu
        F = Y(12607428)
        def ep(o):
            return d[o] == 0xff and d[o + 1] == 0xff
        s7_has = self.fmt60 and bytes(d[X(0x2474a00):X(0x2474a00) + 24 * 400]).find(pair) >= 0   # 60 MB: junior vec ima red u S7, igra ne dodaje novi
        while not ep(F - 24) and F > Y(12606000):
            F -= 24
        rows, k = [], 0
        while True:
            o = F + 24 * k
            if ep(o) or not any(d[o:o + 8]) or k > 80:
                break
            rows.append(bytes(d[o:o + 24]))
            k += 1
        ins = pair + struct.pack('<H', 0x28) + bytes.fromhex('3d91') + b'\0' * 12
        p = 0
        while p < len(rows) and struct.unpack_from('<I', rows[p], 0)[0] > tag:
            p += 1
        newrows = rows[:p] + [ins] + rows[p:]
        top = F - 24
        if s7_has:
            pass
        elif not ep(top):
            raise ValueError('S7: no empty row')
        else:
            W.append((top, b''.join(newrows)))
        # zapis igraca (zlib dio)
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        if self.fmt60:
            # 60 MB (Kal, izmjereno): natjecanja kluba u +64..+88 (kao suigraci), +140 ostaje
            cb = self._comp_block(big)
            if cb:
                big[r + 64:r + 88] = cb
            struct.pack_into('<I', big, r + 128, salary // 100)
            struct.pack_into('<I', big, r + 136, mycode)
        else:
            # pc191: natjecanja iz suigraca (prije fiksno 05/11/17 iz jedne starije karijere; u novijim svjetovima id-jevi su drugi)
            cb = self._comp_block(big)
            big[r + 64:r + 88] = cb if cb else bytes.fromhex('0500c0021100400317008002') + b'\xff\xff\0\0' * 3
            struct.pack_into('<I', big, r + 128, salary // 100)
            struct.pack_into('<I', big, r + 136, mycode)
            struct.pack_into('<I', big, r + 140, 0xffffffff)
        end = (31 << 24) | (8 << 16) | end_year
        struct.pack_into('<I', big, r + 144, end)
        struct.pack_into('<I', big, r + 148, date)
        new, p0 = [], 0
        for c in chunks:
            new.append(bytes(big[p0:p0 + len(c)]))
            p0 += len(c)
        # sve ostalo
        used = {struct.unpack_from('<H', d, my + self.NUM_OFF + 2 * k)[0] for k in range(n)}
        if number is None:
            number = next(x for x in range(2, 100) if x not in used)
        elif number in used or not (1 <= number < 100):
            raise ValueError('shirt number is taken')
        blo = self.TAC0 + 600 * self.MY_TIDX + 484
        BL = [int(x) for x in d[blo:blo + n]]
        self._allow = [(self.CH0 - 4, end_)]
        for o, b in W:
            d[o:o + len(b)] = b
            self._allow.append((o, o + len(b)))
        self._rebuild(new, end_)
        struct.pack_into('<II', d, my + self.PAIR_OFF + 8 * n, tag, pid)
        struct.pack_into('<H', d, my + self.NUM_OFF + 2 * n, number)
        if sorted(BL) == list(range(n)):
            d[blo + n] = n
        d[my + 1058] = n + 1
        self._join_tail(tag, pid, salary // 100, end, None)   # pc207: red ugovora + popis igraca u repu (kao igra)
        try:
            self._sync_tail([pid], {pid: (salary // 100, end)})
        except Exception:
            pass
        self._beta_write = self.beta_ok   # pc191: junior na 60 MB izmjeren (Arsenal Samuel Kal)
        return 'youth player %d signed for the first team (no. %d, until %d., wage %d EUR)' % (pid, number, end_year, salary)

    def sign_player(self, pid, fee, salary, end=0x1f0807eb, date=None, number=None, _old=True, _my=True, _num=True, _rec=True, _pm=True, _game=False):
        """Igrac odmah dolazi u tvoj klub: sastav obaju klubova, broj dresa, ugovor, transfer budzet.
        fee, salary u EUR. Vraca poruku."""
        my = self.club_offset()
        if pid in self.my_squad_tags():
            raise ValueError('player is already in your club')
        n = self._squad_len(my)
        if n >= 40:
            raise ValueError('squad is full')
        f = fee // 100
        b = struct.unpack_from('<I', self.d, self.BUDGET)[0]
        if f > b:
            raise ValueError('not enough money in the transfer budget')
        tag = self.player_tag(pid)
        src = self.find_club_of(pid)
        if date is None:
            date = self.game_date_code()
        # igracev zapis (zlib dio), zapis pocinje 48 B prije id-a
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        pat = struct.pack('<I', pid)
        r = None
        i = self._bf(big, pat)
        while i >= 0:
            if i >= 192 and (i - 192) % 156 == 0:
                r = i - 48
                break
            i = self._bf(big, pat, i + 1)
        if r is None:
            raise ValueError('player record not found')
        if _rec:
            if _game:
                if big[r + 64] >= 100:
                    big[r + 64] -= 100
                big[r + 68] = 23
                big[r + 116] = 0
                big[r + 136:r + 140] = bytes.fromhex('6a01fa01')
            elif _pm:
                big[r + 64] = 0x4f
                big[r + 68] = 0x17
            struct.pack_into('<I', big, r + 128, salary // 100)
            struct.pack_into('<I', big, r + 144, end)
            struct.pack_into('<I', big, r + 148, date)
        new, pos = [], 0
        for c in chunks:
            new.append(bytes(big[pos:pos + len(c)]))
            pos += len(c)
        self._rebuild(new, end_)
        # stari klub: izbaci (pomak ulijevo, isto za brojeve dresova)
        srcname = 'n/a'
        if src and _old:
            so, si = src
            srcname = bytes(self.d[so:so + 40]).split(b'\0')[0].decode('utf-8', 'replace')
            sn = self._squad_len(so)
            for k in range(si, sn - 1):
                a = so + self.PAIR_OFF + 8 * k
                self.d[a:a + 8] = self.d[a + 8:a + 16]
                a = so + self.NUM_OFF + 2 * k
                self.d[a:a + 2] = self.d[a + 2:a + 4]
            struct.pack_into('<II', self.d, so + self.PAIR_OFF + 8 * (sn - 1), 0xffff, 0)
            struct.pack_into('<H', self.d, so + self.NUM_OFF + 2 * (sn - 1), 0)
        # moj klub: dodaj na kraj
        if _my:
            struct.pack_into('<II', self.d, my + self.PAIR_OFF + 8 * n, tag, pid)
        used = {struct.unpack_from('<H', self.d, my + self.NUM_OFF + 2 * k)[0] for k in range(n)}
        if number is None:
            number = next(x for x in range(2, 100) if x not in used)
        if _my and _num:
            struct.pack_into('<H', self.d, my + self.NUM_OFF + 2 * n, number)
        struct.pack_into('<I', self.d, self.BUDGET, b - f)
        return 'signed %d (no. %d, from club %s)' % (pid, number, srcname)

    def _player_recs(self, pids):
        """pid -> offset zapisa igraca u spojenim chunkovima (zapis pocinje 48 B prije id-a)."""
        chunks, end_ = self._chunks()
        big = bytearray(b''.join(chunks))
        out = {}
        pids = list(pids)
        if len(pids) > 8:
            # pc371: jedan prolaz kroz tablicu od 156 B umjesto big.find za svakog igraca (isti rezultat: prvi poravnati zapis,
            # dupli PID ide na 'pravi' zapis iz _canon_map); prije je ovo trajalo i do 8 s po pozivu na velikom savu
            want = set(pids)
            cm = self._canon_map() or {}
            first = {}
            n = (len(big) - 144) // 156 if len(big) >= 300 else 0
            if n > 0:
                for k, (p,) in enumerate(struct.iter_unpack('<48xI104x', bytes(big[144:144 + n * 156]))):
                    if p in want and p not in first:
                        first[p] = 144 + k * 156
                tail = 144 + n * 156
                if tail + 52 <= len(big):
                    p = struct.unpack_from('<I', big, tail + 48)[0]
                    if p in want and p not in first:
                        first[p] = tail
            for pid in want:
                if pid in cm and cm[pid] is not None:
                    r = cm[pid]
                    if r + 48 >= 192 and (r + 48 - 192) % 156 == 0:
                        out[pid] = r
                elif pid in first:
                    out[pid] = first[pid]
            return big, chunks, end_, out
        for pid in pids:
            pat = struct.pack('<I', pid)
            i = self._bf(big, pat)
            while i >= 0:
                if i >= 192 and (i - 192) % 156 == 0:
                    out[pid] = i - 48
                    break
                i = self._bf(big, pat, i + 1)
        return big, chunks, end_, out

    def all_contracts(self):
        """pc161: svi zapisi igraca odjednom (jedan prolaz kroz tablicu od 156 B) -> {pid: dict(sal, y, m, owner)}."""
        chunks, _e = self._chunks()
        big = b''.join(chunks)
        out = {}
        U = struct.unpack_from
        r = 144
        n = len(big) - 156
        while r < n:
            pid = U('<I', big, r + 48)[0]
            if 1000 <= pid < 400000 and pid not in out:
                e = U('<I', big, r + 144)[0]
                y = e & 0xffff
                if 2015 <= y <= 2060:
                    out[pid] = dict(sal=U('<I', big, r + 128)[0] * 100, y=y, m=(e >> 16) & 0xff, owner=U('<I', big, r + 140)[0])
            r += 156
        # pc252: za duple PID-ove prikazi 'pravi' zapis (moj sastav / klub koji app prikazuje), ne prvi u tablici
        try:
            for pid, rc in self._canon_map().items():
                if rc is None:
                    continue
                e = U('<I', big, rc + 144)[0]
                y = e & 0xffff
                if 2015 <= y <= 2060:
                    out[pid] = dict(sal=U('<I', big, rc + 128)[0] * 100, y=y, m=(e >> 16) & 0xff, owner=U('<I', big, rc + 140)[0])
        except Exception:
            pass
        return out

    def read_status(self, pids):
        """pc316 (mapa Michele & Alex, provjereno na 20/45/60 MB i FL27): pid -> dict(inj=dani ozljede (brojac pada 1 dnevno),
        cond=kondicija % (igra je prati samo za tvoje igrace), yc={natjecanje: zuti kartoni}). Samo citanje."""
        big, _, _, recs = self._player_recs(pids)
        out = {}
        for pid, r in recs.items():
            if r + 165 > len(big):
                continue
            yc = {}
            for i in range(12):
                c, st = struct.unpack_from('<HH', big, r + 52 + 4 * i)
                if c == 0xffff:
                    break
                if st & 0x3f:
                    yc[c] = st & 0x3f
            out[pid] = dict(inj=big[r + 160], cond=big[r + 164] & 0x7f, yc=yc)
        return out

    def read_contracts(self, pids):
        """pid -> dict(sal EUR godisnje, y, m, d kraja ugovora) iz zapisa igraca u save-u."""
        big, _, _, recs = self._player_recs(pids)
        out = {}
        for pid, r in recs.items():
            sal = struct.unpack_from('<I', big, r + 128)[0] * 100
            e = struct.unpack_from('<I', big, r + 144)[0]
            b = struct.unpack_from('<I', big, r + 148)[0]
            out[pid] = dict(sal=sal, y=e & 0xffff, m=(e >> 16) & 0xff, d=(e >> 24) & 0xff, sy=b & 0xffff, sm=(b >> 16) & 0xff)
        return out

    def extend_contract(self, pid, salary, end_year, end_month=8, end_day=31):
        """Produljenje ugovora igraca iz tvoje momcadi: nova placa (EUR/god) i datum isteka. Ne dira datum pocetka (nije transfer)."""
        self.pid_guard(pid)   # pc250
        if pid not in self.my_squad_tags():
            raise ValueError('player is not in your squad')
        if salary <= 0 or not (2000 < end_year < 2100):
            raise ValueError('invalid contract terms')
        if self.ext and self.game27:
            if not self.FL27_EXTEND_OK:
                raise ValueError('Contract renewals are not unlocked yet on Football Life 2027 saves (still being checked in the game); renew him in the game. The save was not touched.')
            self._fl27_layout_check()
        big, chunks, end_, recs = self._player_recs([pid])
        r = recs.get(pid)
        if r is None:
            raise ValueError('player record not found')
        struct.pack_into('<I', big, r + 128, salary // 100)
        struct.pack_into('<I', big, r + 144, (end_day << 24) | (end_month << 16) | end_year)
        new, pos = [], 0
        for c in chunks:
            new.append(bytes(big[pos:pos + len(c)]))
            pos += len(c)
        self._allow = list(getattr(self, '_allow', [])) + [(self.CH0 - 4, end_)]
        self._rebuild(new, end_)
        if self.ext and self.game27:
            return self._extend_fl27_inplace(pid, salary // 100, (end_day << 24) | (end_month << 16) | end_year, end_month, end_year, salary)
        tail = self._sync_tail([pid], {pid: (salary // 100, (end_day << 24) | (end_month << 16) | end_year)})
        self._beta_write = self.beta_ok   # pc190: produljenje na 60 MB izmjereno (Arsenal Merino: placa, kraj ugovora, kopija u repu)
        return 'contract extended: %d until %d/%d, wage %d EUR%s' % (pid, end_month, end_year, salary, '' if tail else ' (contract copy at the end of the save not found)')

    def _extend_fl27_inplace(self, pid, sal, endc, end_month, end_year, salary):
        """pc274: FL27 produljenje na nacin appa za ostale formate: zapis igraca (vec napravljeno) + placa i kraj u POSTOJECEM
        aktivnom ugovoru (red uvjeta T sa statusom 5). Igrin nacin (novi red status 4 + stari 7 + S16 + 0x70/0x40) igra je u tri
        testa (Bradley, slotovi 8-10) sljedeci dan obrisala, pa se ne koristi."""
        d = self.d
        _ch, e = self._chunks()
        tag = self.my_squad_tags()[pid]
        pr = struct.pack('<II', tag, pid)
        cbase = e + 16
        k, cur = 0, None
        while bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff':
            o = cbase + 48 * k
            if bytes(d[o + 28:o + 36]) == pr:
                if d[o + 8] in (1, 2, 3, 4):
                    raise ValueError('There is already a contract offer for this player in the game. Finish or cancel it in the game. The save was not touched.')
                if d[o + 8] == 5:
                    cur = o
            k += 1
            if k > 200:
                raise ValueError('terms table: no end')
        if cur is None:
            raise ValueError('current contract of this player not found in the save; extend him in the game. The save was not touched.')
        struct.pack_into('<I', d, cur + 36, sal)
        struct.pack_into('<I', d, cur + 44, endc)
        self._allow = list(getattr(self, '_allow', [])) + [(cur + 36, cur + 48)]
        self._beta_write = True
        return 'contract extended: %d until %d/%d, wage %d EUR' % (pid, end_month, end_year, salary)

    def _extend_fl27(self, pid, sal, endc, end_month, end_year, salary):
        """pc274: FL27 produljenje kao u igri (izmjereno: James McConnell, Liverpool, 25.8.2026; saveovi: ponuda poslana, igrac pristao,
        potvrdeno). Pri potvrdi igra: zapis igraca (placa, kraj; vec napravljeno u extend_contract), novi red uvjeta T
        [ser, moj klub, status 4, danas, ff*8, ffff, tag, id, placa, klauzula, kraj], stari red ugovora (status 5) -> status 7,
        red dogadjaja 0x70 (tag, id, danas). Lista za izvrsenje se ne dira."""
        d = self.d
        _ch, e = self._chunks()
        tag = self.my_squad_tags()[pid]
        pr = struct.pack('<II', tag, pid)
        cbase = e + 16
        crows, k, cur = [], 0, None
        while bytes(d[cbase + 48 * k + 4:cbase + 48 * k + 8]) != b'\xff\xff\xff\xff':
            row = bytes(d[cbase + 48 * k:cbase + 48 * k + 48])
            if row[28:36] == pr:
                if row[8] in (1, 2, 3, 4):
                    raise ValueError('There is already a contract offer for this player in the game. Finish or cancel it in the game. The save was not touched.')
                if row[8] == 5:
                    cur = len(crows)
            crows.append(row)
            k += 1
            if k > 200:
                raise ValueError('terms table: no end')
        if cur is None:
            raise ValueError('current contract of this player not found in the save; extend him in the game. The save was not touched.')
        rel = struct.unpack_from('<I', crows[cur], 40)[0]
        today = self.game_date_code()
        mbase = e + 54736
        used = {struct.unpack_from('<H', x, 0)[0] for x in crows}
        for j in range(110):
            sv = struct.unpack_from('<H', d, mbase + 60 * j)[0]
            if sv not in (0, 0xffff):
                used.add(sv)
        for j in range(40):
            v = struct.unpack_from('<H', d, e + self.SERLIST + 2 * j)[0]
            if v != 0xffff:
                used.add(v)
        # pc274: igra daje najmanji slobodni serijski (McConnell 0x08, posudba Fredrick 0x22); max+1 je na testu (Bradley) zapeo pri spremanju
        ser = next(v for v in range(0, 0x400) if v not in used)
        ent = next((self.ENT0 + 56 * j for j in range(40) if d[self.ENT0 + 56 * j] == 0xff), None)
        if ent is None:
            raise ValueError('event log is full; advance a day in the game and try again')
        old = bytearray(crows[cur])
        old[8] = 7
        crows[cur] = bytes(old)
        mycode = struct.unpack_from('<I', d, self.club_offset() - 4)[0]
        nr = struct.pack('<HHIII', ser, 0, mycode, 4, today) + b'\xff' * 8 + struct.pack('<IIIIII', 0xffff, tag, pid, sal, rel, endc)
        allc = sorted(crows + [nr], key=lambda x: struct.unpack_from('<H', x, 0)[0])
        if bytes(d[cbase + 48 * len(allc) + 4:cbase + 48 * len(allc) + 8]) != b'\xff\xff\xff\xff' and \
                struct.unpack_from('<H', d, cbase + 48 * len(allc))[0] != 0xffff:
            raise ValueError('terms table is full')
        for n_, rb in enumerate(allc):
            d[cbase + 48 * n_:cbase + 48 * n_ + 48] = rb
        d[ent:ent + 56] = struct.pack('<III', 0x70, tag, pid) + bytes.fromhex(
            'ffff000000000000ffff000000000000ffffffffffff0000ffffffff00000000ffff0000ffff0000') + struct.pack('<I', today)
        # pc274: igra pri potvrdi upise DVA dogadjaja: 0x70 i odmah iza njega 0x40 (McConnell redovi 3 i 4); bez 0x40 igra novi ugovor
        # ne potvrdi nego ga obrise (test Bradley, slot 9)
        ent2 = next((self.ENT0 + 56 * j for j in range(60) if d[self.ENT0 + 56 * j] == 0xff), None)
        if ent2 is None:
            raise ValueError('event log is full; advance a day in the game and try again')
        d[ent2:ent2 + 56] = struct.pack('<III', 0x40, tag, pid) + bytes.fromhex(
            'ffff000000000000ffff000000000000ffffffffffff0000ffffffff00000000ffff0000ffff0000') + struct.pack('<I', today)
        # pc274: kad igrac pristane, igra upise S16 red 0x1b (kao kod kupnje) i poveca brojac; bez njega igra sljedeci dan obrise
        # i novi i stari red ugovora (test Bradley, slot 8: nema reda, klauzula '-', prazan komentar direktora)
        S16, CNT, k16 = self._s16_slot()
        o16 = S16 + 80 * k16
        row = struct.pack('<IIIIIIIII', 0x1b, today, 3, 0xff, 1, 0, 0xffffffff, 0xffff, 0xffffffff) + struct.pack('<II', tag, pid) + \
            bytes.fromhex('ffff000000000000ffff0000000000000000000000000000ff00ffffffff0000')
        d[o16 + 4:o16 + 80] = row
        if o16 + 80 < S16 + 80 * 112:
            d[o16 + 80:o16 + 84] = bytes.fromhex('09414100')
        struct.pack_into('<I', d, CNT, struct.unpack_from('<I', d, CNT)[0] + 1)
        self._allow = list(getattr(self, '_allow', [])) + [(ent, ent + 56), (ent2, ent2 + 56), (cbase, cbase + 48 * (len(allc) + 1)),
                                                            (o16, o16 + 84), (CNT, CNT + 4)]
        self._beta_write = True
        return 'contract extended: %d until %d/%d, wage %d EUR' % (pid, end_month, end_year, salary)

    def _tail_rows(self, end_):
        """pid -> offset reda (48 B) u tablici ugovora iza zlib dijelova: par (tag,pid), +8 placa/100, +16 datum isteka. Igra IZ OVE tablice cita ugovor u izborniku."""
        n = self._squad_len(self.club_offset())
        base = self.club_offset() + self.PAIR_OFF
        d = self.d
        lim = min(len(d), end_ + 48 * 50 + 120)
        out = {}
        for k in range(n):
            pr = bytes(d[base + 8 * k:base + 8 * k + 8])
            pid = struct.unpack_from('<I', pr, 4)[0]
            i = bytes(d[end_:lim]).find(pr)
            if i >= 0:
                o = end_ + i
                e = struct.unpack_from('<I', d, o + 16)[0]
                if 1 <= ((e >> 16) & 255) <= 12 and 2000 < (e & 0xffff) < 2100:
                    out[pid] = o
        return out

    def _sync_tail(self, pids, want=None):
        """Upisi placu i datum isteka u tablicu ugovora na kraju save-a. want: pid -> (placa/100, datum); inace prepisi iz zapisa igraca."""
        big, chunks, end_, recs = self._player_recs(pids)
        rows = self._tail_rows(end_)
        ok = False
        for pid in pids:
            o = rows.get(pid)
            if o is None:
                continue
            if want and pid in want:
                sal, e = want[pid]
            else:
                r = recs.get(pid)
                if r is None:
                    continue
                sal, e = struct.unpack_from('<I', big, r + 128)[0], struct.unpack_from('<I', big, r + 144)[0]
            struct.pack_into('<I', self.d, o + 8, sal)
            struct.pack_into('<I', self.d, o + 16, e)
            self._allow = list(getattr(self, '_allow', [])) + [(o + 8, o + 20)]
            ok = True
        return ok

    def tail_mismatch(self):
        """Igraci mog kluba ciji se ugovor u zapisu igraca razlikuje od kopije u tablici na kraju save-a: [(pid, sal_rec, end_rec, sal_tail, end_tail)]."""
        pids = list(self.my_squad_tags())
        big, chunks, end_, recs = self._player_recs(pids)
        rows = self._tail_rows(end_)
        out = []
        for pid in pids:
            r, o = recs.get(pid), rows.get(pid)
            if r is None or o is None:
                continue
            a = (struct.unpack_from('<I', big, r + 128)[0], struct.unpack_from('<I', big, r + 144)[0])
            b = struct.unpack_from('<II', self.d, o + 8)[0], struct.unpack_from('<I', self.d, o + 16)[0]
            if a != b:
                out.append((pid,) + a + b)
        return out

    def game_date_code(self):
        import re as _re
        raw = open(os.path.join(self.folder, 'description.dat'), 'rb').read()
        # pc413: neke igre/jezici pisu datum s tockama ili crticama (22.8.2026, 22-8-2026) ili kao 2026-08-22; prije je to rusilo
        # svaki upis s "'NoneType' object has no attribute 'groups'" (Reddit 3.11.: transfer lista, trener, mediji)
        m = _re.search(rb'(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})', raw)
        if m:
            d_, mo, y = (int(x) for x in m.groups())
        else:
            m = _re.search(rb'(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})', raw)
            if not m:
                raise ValueError('Could not read the game date from this save (description.dat). Please send a support file.')
            y, mo, d_ = (int(x) for x in m.groups())
        try:
            import mlsave as _ms
            if _ms.date_order(self.folder, d_, mo, y, X(0x244eb70) if self.ext else Y(12464992)) == 'mdy':
                d_, mo = mo, d_
        except Exception:
            if mo > 12:
                d_, mo = mo, d_
        return (d_ << 24) | (mo << 16) | y

    # ---------------------------------------------------------------- pc332: ML kalendar (365 dana) i "zaustavi igru na dan"
    CAL_EMPTY = struct.pack('<HHHBB', 0x3f, 0xffff, 0xffff, 0, 0)
    CAL_STOP = (0x20, 0xffeb)   # "Club ranking update": igra stane taj dan (Michele & Alex, 1.11.2026, 45 MB)

    def calendar_loc(self):
        """-> (pocetak zapisa 1. sijecnja, velicina zapisa 708/1732, godina sijecnja) ili None. Zapis: u32 broj utakmica,
        18 dogadjaja po 8 B (u16 vrsta, u16 param, u16 god, u8 mj, u8 dan), pa ID-jevi utakmica. Dogadjaj 1.1. (vrsta 6,
        otvaranje prijelaznog roka) moze biti u bilo kojem od 18 mjesta."""
        if getattr(self, '_cal', None) is not None:
            return self._cal or None
        import datetime
        d = self.d
        gd = self.game_date_code()
        y, m = gd & 0xffff, (gd >> 16) & 0xff
        y2 = y + 1 if m >= 7 else y

        def valid(st, rs, yy):
            if st < 0 or st + 365 * rs > len(d):
                return False
            for idx in range(0, 365, 7):
                dt = datetime.date(2001, 1, 1) + datetime.timedelta(days=idx)
                r = st + idx * rs
                for j in range(18):
                    t_, p_, y_, m_, d_ = struct.unpack_from('<HHHBB', d, r + 4 + 8 * j)
                    if (y_, m_, d_) == (0xffff, 0, 0):
                        continue
                    if (m_, d_) != (dt.month, dt.day) or not (yy - 4 <= y_ <= yy):   # stare sezone ostaju u zapisu
                        return False
            return True
        res = None
        for yy in (y2, y2 + 1, y2 - 1):
            pat = struct.pack('<HHHBB', 6, 0, yy, 1, 1)
            i = d.find(pat)
            while i >= 0 and res is None:
                for j0 in range(18):
                    for rs in (708, 1732):
                        if valid(i - 4 - 8 * j0, rs, yy):
                            res = (i - 4 - 8 * j0, rs, yy)
                            break
                    if res:
                        break
                i = d.find(pat, i + 1)
            if res:
                break
        self._cal = res or False
        return res

    def _cal_rec(self, y, m, dd):
        import datetime
        loc = self.calendar_loc()
        if not loc:
            raise ValueError('The season calendar was not found in this save.')
        st, rs, yj = loc
        if (m, dd) == (2, 29):
            raise ValueError('29 February is not in the game calendar.')
        want = yj if m <= 6 else yj - 1
        if y != want:
            raise ValueError('Only days of the current season (1 Jul %d - 30 Jun %d) can be used.' % (yj - 1, yj))
        idx = (datetime.date(2001, m, dd) - datetime.date(2001, 1, 1)).days
        return st + idx * rs

    def cal_events(self, y, m, dd):
        r = self._cal_rec(y, m, dd)
        out = []
        for j in range(18):
            t_, p_, y_, m_, d_ = struct.unpack_from('<HHHBB', self.d, r + 4 + 8 * j)
            if (y_, m_, d_) == (0xffff, 0, 0) and t_ == 0x3f:
                continue
            out.append((j, t_, p_))
        return out

    def cal_window_ends(self):
        """Zadnji dani prijelaznih rokova ove sezone (dani s dogadjajem 9 / 0xfff5 = dan roka) -> [(y, m, d)]."""
        import datetime
        loc = self.calendar_loc()
        if not loc:
            return []
        st, rs, yj = loc
        days = []
        for idx in range(365):
            dt = datetime.date(2001, 1, 1) + datetime.timedelta(days=idx)
            y = yj if dt.month <= 6 else yj - 1
            r = st + idx * rs
            for j in range(18):
                t_, p_, y_, m_, d_ = struct.unpack_from('<HHHBB', self.d, r + 4 + 8 * j)
                if t_ == 9 and p_ == 0xfff5 and y_ == y:
                    days.append(datetime.date(y, dt.month, dt.day))
                    break
        # ljetni (srpanj-rujan) i zimski (prosinac-veljaca) rok: zadnji dan s oznakom roka (dani utakmica nemaju oznaku)
        out = []
        for grp in ((7, 8, 9), (12, 1, 2)):
            g = [dd for dd in days if dd.month in grp]
            if g:
                dd = max(g)
                out.append((dd.year, dd.month, dd.day))
        return out

    def cal_matches(self, y, m, dd):
        """Broj utakmica (svih klubova) tog dana u kalendaru."""
        return struct.unpack_from('<I', self.d, self._cal_rec(y, m, dd))[0]

    def _cal_allow(self):
        st, rs, _y = self.calendar_loc()
        self._allow = list(getattr(self, '_allow', [])) + [(st, st + 365 * rs)]
        if not self.known_format and self.changed_outside(self._allow) is None:
            self._beta_write = True   # samo kalendar je promijenjen (8 B po danu, bez kompresije)

    def cal_add_stop(self, y, m, dd):
        r = self._cal_rec(y, m, dd)
        ev = self.cal_events(y, m, dd)
        if any((t_, p_) == self.CAL_STOP for _j, t_, p_ in ev):
            return 'exists'
        for j in range(18):
            o = r + 4 + 8 * j
            if bytes(self.d[o:o + 8]) == self.CAL_EMPTY:
                struct.pack_into('<HHHBB', self.d, o, self.CAL_STOP[0], self.CAL_STOP[1], y, m, dd)
                self._cal_allow()
                return 'added'
        raise ValueError('That day already has 18 calendar events; pick another day.')

    def cal_remove_stop(self, y, m, dd):
        r = self._cal_rec(y, m, dd)
        slots = [bytes(self.d[r + 4 + 8 * j:r + 12 + 8 * j]) for j in range(18)]
        stop = struct.pack('<HHHBB', self.CAL_STOP[0], self.CAL_STOP[1], y, m, dd)
        if stop not in slots:
            return 'missing'
        i = slots.index(stop)
        rest = slots[:i] + slots[i + 1:] + [self.CAL_EMPTY]   # pomak ostalih (bez rupe u popisu)
        self.d[r + 4:r + 4 + 8 * 18] = b''.join(rest)
        self._cal_allow()
        return 'removed'

    def _guard_extended(self):
        """Prosireni (45 MB) save: dopusteno je samo pisanje u dijelove cije pomake znamo (zapisi klubova, formacije/sastav,
        taktike, budzet). Sve ostalo (repne tablice: potpisi, ugovori, transferi) se odbija i save ostaje netaknut."""
        orig = self._orig
        cur = bytes(self.d)
        if len(cur) != len(orig):
            raise ValueError('Writing changes the save size: not supported yet on the extended format. The save was not touched.')
        okr = list(getattr(self, '_allow', [])) + [(REC0, REC0 + STRIDE * 2400), (F0 - 64, F0 + 1400), (self.TAC0, self.TAC0 + 600 * (self.MY_TIDX + 3)), (self.BUDGET, self.BUDGET + 4)]
        okr.sort()
        BLK = 4096
        n = len(cur)
        bad = None
        for p in range(0, n, BLK):
            if cur[p:p + BLK] == orig[p:p + BLK]:
                continue
            for i in range(p, min(p + BLK, n)):
                if cur[i] != orig[i] and not any(lo <= i < hi for lo, hi in okr):
                    bad = i
                    break
            if bad is not None:
                break
        if bad is not None:
            raise ValueError('This change touches parts of the extended save whose layout is not confirmed yet (e.g. signings, contracts, transfers); ' 'the save was not touched. Tactics, lineup, formations and budget work.')

    KNOWN_SHIFTS = (0, 1428000)   # stari (19,9 MB) i prosireni fl26caps (45 MB) format; za ostale app samo cita

    @property
    def known_format(self):
        # poznat raspored: stari (19,9 MB) ili prosireni kojem su sva sidra pronadjena na istom pomaku (i nova verzija exea koja samo pomakne tablice)
        return self.sh == 0 or self.layout_ok

    def _tac60_ranges(self):
        """pc247: dijelovi savea za taktiku na 60 MB (citanje izmjereno na uzorcima testera 60 MB: formacije, upute, brojevi, AI planovi):
        formacije + niz sastava, planovi/taktike svih klubova i mog kluba, brojevi dresova mog kluba."""
        my = self.club_offset()
        return [(F0 - 64, F0 + 1400), (self.TAC0, self.TAC0 + 600 * (self.MY_TIDX + 3)), (my + self.NUM_OFF, my + self.NUM_OFF + 2 * 40)]

    def save(self, out_folder=None):
        self.write_guard()
        out = out_folder or self.folder
        if out != self.folder:
            os.makedirs(out, exist_ok=True)
            for f in os.listdir(self.folder):
                if f != 'data.dat':
                    open(os.path.join(out, f), 'wb').write(open(os.path.join(self.folder, f), 'rb').read())
        open(os.path.join(out, 'data.dat'), 'wb').write(self.d)

    FL27_TACTICS_OK = True   # pc281: formacija provjerena u igri (3-5-2, slot 14); svih 586 AI zapisa taktike valjano

    def write_guard(self):
        """pc277: sve provjere prije spremanja (iste kao save), bez pisanja; koristi i provjera savea u Setupu."""
        if getattr(self, 'ro', False):
            raise RuntimeError('internal: read-only save view cannot be written')
        if (self.ext and self.game27 and self.FL27_TACTICS_OK and not getattr(self, '_beta_write', False)
                and self.changed_outside(self._tac60_ranges() + [(self.TAC0, self.TAC0 + 600 * 760)] + list(getattr(self, '_allow', []))) is None):
            # pc278: FL27 formacije, postava, upute i taktike (moja i AI klubova): isti dijelovi savea kao klasicni (izmjereno 31.8.2026,
            # promjena formacije u igri mijenja samo F0 blok)
            self._fl27_layout_check()
            self._allow = list(getattr(self, '_allow', [])) + [(self.TAC0, self.TAC0 + 600 * 760)]
            self._beta_write = True
        if (not self.known_format and not getattr(self, '_beta_write', False) and self.fmt60 and BETA_FLAG('tactics60_beta')
                and bytes(self.d) != self._orig   # pc301: samo stvarna promjena taktike (prazan upis i dalje odbijen)
                and self.changed_outside(self._tac60_ranges() + list(getattr(self, '_allow', []))) is None):
            self._beta_write = True
        if (not self.known_format and not getattr(self, '_beta_write', False) and not self.fmt60 and self.beta_ok
                and BETA_FLAG('tactics45_beta') and bytes(self.d) != self._orig
                and self.changed_outside(self._tac60_ranges() + list(getattr(self, '_allow', []))) is None):
            # pc381: 45 MB 'new save layout' (Michele, UML): formacija + upute + postava (izmjereno u igri)
            # pc385: + brojevi dresova (Michele, Genoa: jedini promijenjeni u16 na club+662+2*indeks, isto kao klasicni)
            # pc247: 60 MB taktika/formacija/brojevi/AI taktike (beta, config.json "tactics60_beta": true); sve izvan tih dijelova se i dalje odbija
            self._beta_write = True
        if not self.known_format and not getattr(self, '_beta_write', False) and self.fmt60:
            raise ValueError('On this save format (60 MB, FL Mod Studio 0.2.2+) this action (for example a loan offer sent to the game) is not unlocked yet; do it in the game. '
                             'Transfers, sales, renewals, youth, lists, loans, free agents, option loans and tactics work (test version). The save was not touched.')
        if not self.known_format and not getattr(self, '_beta_write', False) and self.beta_ok:
            raise ValueError('On this save layout (%s) the app can so far buy and sell players, renew contracts, sign youth players and use the transfer/loan lists (beta). '
                             'This action is not unlocked yet on this layout; do it in the game. The save was not touched.' % (self.layout_note.split(':')[0] if self.layout_note else 'new layout'))
        if not self.known_format and not getattr(self, '_beta_write', False):
            raise ValueError('The app does not recognise this save version (%s). It only reads it; the save was not touched. Send a save from the new game version so it can be added.' % (self.layout_note or 'club table offset %d B' % self.sh))
        if self.sh:
            self._guard_extended()


def load_positions(path):
    if path and os.path.exists(path):
        return {int(k): v for k, v in json.load(open(path)).items()}
    return {}


def load_names(path):
    if path and os.path.exists(path):
        return {p[0]: (p[1] or (p[2] if len(p) > 2 else '') or '') for p in json.load(open(path, encoding='utf-8'))}
    return {}


def show(s, names):
    ids = s.squad_ids()
    print('Klub:', s.club_name(), '| menadzer:', s.manager())
    for k, lab in enumerate(('kick-off', 'u posjedu', 'bez posjeda')):
        print(' ', lab, ' '.join(p for p, _, _ in s.formation(k)))
    lu = s.lineup()
    for i, ix in enumerate(lu[:23]):
        if ix == 0xff:
            continue
        pid = ids[ix] if ix < len(ids) else None
        tag = 'XI   ' if i < 11 else ('klupa' if i < 23 else '     ')
        print('  %s %2d idx%02d %s' % (tag, i, ix, names.get(pid, pid)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('folder')
    ap.add_argument('--players', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'players.json'))
    ap.add_argument('--positions', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'positions.json'))
    ap.add_argument('--spec', help='JSON: {"formations":{"kickoff":"4-3-3","in":"4-3-3","out":"4-4-2"},"xi":[11 id],"bench":[id...]}')
    ap.add_argument('--out', help='mapa za rezultat (obavezno uz --spec)')
    a = ap.parse_args()
    s = Save(a.folder)
    names = load_names(a.players)
    if not a.spec:
        show(s, names); return
    if not a.out:
        sys.exit('uz --spec treba --out (ne pisemo preko originala)')
    spec = json.load(open(a.spec, encoding='utf-8'))
    fm = spec.get('formations', {})
    for key, k in (('kickoff', 0), ('in', 1), ('out', 2)):
        if key in fm:
            s.set_formation(k, fm[key])
    if spec.get('auto'):
        pos = load_positions(a.positions)
        xi, bench = s.auto_lineup(fm.get('kickoff', '4-3-3'), pos, spec.get('pool'))
        s.set_lineup_by_ids(xi, bench)
    elif 'xi' in spec:
        s.set_lineup_by_ids(spec['xi'], spec.get('bench', []))
    s.save(a.out)
    show(Save(a.out), names)


if __name__ == '__main__':
    main()
