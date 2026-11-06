#!/usr/bin/env python3
"""mlsave.py - citac dekriptiranog Master League save-a (Football Life 26 v1.3).

Cita SAMO. Ulaz: mapa koju je napravio decrypter21 (data.dat, description.dat, ...).
Izlaz: klub, liga, datum, tablica lige kluba i sastav kluba.

Poznato (izmjereno usporedbom save-ova, v1.3):
  description.dat : naziv slota\0 ... "Klub / Liga\nd/m/yyyy\nSljedece natjecanje"
  data.dat        : zapisi klubova od offseta 84, korak 1680, ime kluba u prvih ~64 B
    +332 ..       : sastav, parovi (u32 id igraca, u32 oznaka) korak 8
    +746 bodovi, +747 odigrano, +748 W, +749 D, +750 L, +752 GF, +756 GA
Nepoznato/nepotvrdeno: +751, +760, prvih 32 B (48..79) na pocetku data.dat.
"""
import argparse, json, os, struct, sys

REC0, STRIDE = 84, 1680
OFF = dict(pts=746, pl=747, w=748, d=749, l=750, gf=752, ga=756)
SQUAD_OFF, SQUAD_SLOTS = 332, 40


_DORD = {}


def _queue_base(p):
    """Pocetak reda dogadjaja (56 B redovi) za svaki format: klasicni 12464992, prosireni po mlwrite rasporedu."""
    try:
        sz = os.path.getsize(p)
        if sz < 30000000:
            return 12464992
        import mlwrite as _mw
        s = _mw.Save(os.path.dirname(p))
        return _mw.X(0x244eb70)
    except Exception:
        return 12464992


def date_order(d, a, b, y, qb=None):
    """Redoslijed datuma u description.dat: FL26 pise D/M/Y, vanilla PES 2021 (engleski) M/D/Y. -> 'dmy' ili 'mdy'.
    Kad su oba broja <= 12, odluci po datumima u redu dogadjaja savea (56 B redovi, kod datuma d<<24|m<<16|y na +52)."""
    if b > 12:
        return 'mdy'
    if a > 12:
        return 'dmy'
    p = os.path.join(d, 'data.dat')
    try:
        k = (p, os.path.getmtime(p), qb)
    except Exception:
        k = None
    if k and k in _DORD:
        return _DORD[k]
    res = 'dmy'
    try:
        import struct
        with open(p, 'rb') as f:
            f.seek(qb if qb else _queue_base(p))
            q = f.read(56 * 200)
        best = None
        for i in range(0, len(q) - 55, 56):
            c = struct.unpack_from('<I', q, i + 52)[0]
            cy, cm, cd = c & 0xffff, (c >> 16) & 0xff, c >> 24
            if cy == y and 1 <= cm <= 12 and 1 <= cd <= 31:
                if best is None or (cm, cd) > best:
                    best = (cm, cd)
        if best:
            # najnoviji dogadjaj je oko danasnjeg datuma: koji redoslijed daje datum blize njemu
            dmy, mdy = (b, a), (a, b)
            dist = lambda md: abs((md[0] - best[0]) * 31 + (md[1] - best[1]))
            res = 'mdy' if dist(mdy) < dist(dmy) else 'dmy'
    except Exception:
        pass
    if k:
        _DORD[k] = res
    return res


def norm_date(d, txt):
    """'8/18/2020' iz vanille -> '18/8/2020' (app svugdje racuna D/M/Y)."""
    import re
    # pc380: neke igre pisu datum s tockama ili crticama (22.8.2026) - tester na Linuxu; app svugdje ocekuje D/M/Y
    txt = re.sub(r'^(\s*\d{1,2})[.\-](\d{1,2})[.\-](\d{4})', r'\1/\2/\3', txt or '')
    m = re.match(r'\s*(\d{1,2})/(\d{1,2})/(\d{4})', txt or '')
    if not m:
        return txt
    a, b, y = (int(x) for x in m.groups())
    if date_order(d, a, b, y) == 'mdy':
        return '%d/%d/%d' % (b, a, y)
    return txt


def read_description(d):
    raw = open(os.path.join(d, 'description.dat'), 'rb').read()
    parts = [p for p in raw.split(b'\0') if p]
    slot = parts[0].decode('utf-8', 'replace') if parts else ''
    club = league = date = comp = ''
    if len(parts) > 1:
        lines = parts[1].decode('utf-8', 'replace').split('\n')
        head = lines[0].split(' / ')
        club = head[0]
        league = head[1] if len(head) > 1 else ''
        date = norm_date(d, lines[1]) if len(lines) > 1 else ''
        comp = lines[2] if len(lines) > 2 else ''
    return dict(slot=slot, club=club, league=league, date=date, next_competition=comp)


def team_records(data):
    out = []
    n = 0
    while True:
        o = REC0 + n * STRIDE
        if o + STRIDE > len(data):
            break
        name = data[o:o + 48].split(b'\0')[0]
        try:
            s = name.decode('utf-8')
        except UnicodeDecodeError:
            break
        if len(s) < 3 or not s.replace(' ', '').replace('.', '').replace("'", '').replace('&', '').replace('-', '').isalnum():
            break
        r = data[o:o + STRIDE]
        t = dict(idx=n, off=o, name=s)
        for k, v in OFF.items():
            t[k] = r[v] if k != 'gf' and k != 'ga' else r[v]
        out.append(t)
        n += 1
    return out


def league_blocks(teams):
    """Dijeli popis klubova u lige. Unutar lige vrijedi sum(GF)==sum(GA) i sum(W)==sum(L)."""
    blocks, i = [], 0
    while i < len(teams):
        sw = sl = sgf = sga = 0
        j = i
        ok = None
        while j < len(teams):
            t = teams[j]
            sw += t['w']; sl += t['l']; sgf += t['gf']; sga += t['ga']
            j += 1
            if j - i >= 8 and sw == sl and sgf == sga:
                ok = j
                if j - i >= 16:
                    break
        end = ok if ok else len(teams)
        blocks.append(teams[i:end])
        i = end
    return blocks


def results_of(matches):
    """[(home, away, gh, ga)] odigranih utakmica (zapisi rasporeda iz seasonstats: gol = zbroj golova igraca)."""
    out = []
    for m in matches or []:
        if not m.get('played'):
            continue
        gh = (m['sc'][0] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] == m['home']))
        ga = (m['sc'][1] if m.get('sc') else sum(r[2] for r in m['rows'] if r[1] != m['home']))
        out.append((m['home'], m['away'], gh, ga))
    return out


def game_ranks(rows, results, key='idx'):
    """pc316: poredak kao u igri (Michele & Alex, 1.11.2026): bodovi, pa medjusobni susreti klubova s istim brojem bodova,
    inace dijeljeno mjesto (gol-razlika NE odlucuje; Padova i Spezia oboje 16.). rows trebaju pts, gf, ga i kljuc kluba.
    Redoslijed prikaza unutar dijeljenog mjesta: gol-razlika, golovi. Vraca sortirane redove s 'pos'."""
    for t in rows:
        t['gd'] = t['gf'] - t['ga']
    rows = sorted(rows, key=lambda t: (-t['pts'], -t['gd'], -t['gf']))
    out, i = [], 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j]['pts'] == rows[i]['pts']:
            j += 1
        grp = rows[i:j]
        if len(grp) == 1:
            grp[0]['pos'] = i + 1
        else:
            mem = {t[key] for t in grp}
            h2h = {c: 0 for c in mem}
            for h, a, gh, ga in results:
                if h in mem and a in mem:
                    h2h[h] += 3 if gh > ga else 1 if gh == ga else 0
                    h2h[a] += 3 if ga > gh else 1 if gh == ga else 0
            grp.sort(key=lambda t: (-h2h[t[key]], -t['gd'], -t['gf']))
            for t in grp:
                t['pos'] = i + 1 + sum(1 for u in grp if h2h[u[key]] > h2h[t[key]])
        out += grp
        i = j
    return out


def table(block, results=None):
    for t in block:
        t['pts'] = 3 * t['w'] + t['d']
    if results is not None:
        return game_ranks(block, results, 'idx')
    rows = sorted(block, key=lambda t: (-t['pts'], -(t['gf'] - t['ga']), -t['gf']))
    for p, t in enumerate(rows, 1):
        t['pos'] = p
        t['gd'] = t['gf'] - t['ga']
    return rows


def load_players(path):
    if not path or not os.path.exists(path):
        return {}
    return {p[0]: p[1] for p in json.load(open(path, encoding='utf-8'))}


def squad(data, team, names):
    o = team['off'] + SQUAD_OFF
    out = []
    for i in range(SQUAD_SLOTS):
        pid, tag = struct.unpack_from('<II', data, o + i * 8)
        if pid == 0 or pid == 0xFFFFFFFF or pid > 400000:
            if out:
                break
            continue
        out.append(dict(slot=i, id=pid, tag=hex(tag), name=names.get(pid, '?')))
    return out


def read_save(d, players_json=None):
    desc = read_description(d)
    data = open(os.path.join(d, 'data.dat'), 'rb').read()
    teams = team_records(data)
    blocks = league_blocks(teams)
    mine = next((t for t in teams if t['name'] == desc['club']), None)
    res = dict(info=desc, clubs=len(teams))
    if mine:
        blk = next(b for b in blocks if mine in b)
        res['league_table'] = [dict(pos=t['pos'], club=t['name'], pl=t['pl'], w=t['w'], d=t['d'], l=t['l'],
                                    gf=t['gf'], ga=t['ga'], gd=t['gd'], pts=t['pts'], idx=t['idx'])
                               for t in table(blk)]
        res['squad'] = squad(data, mine, load_players(players_json))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', help='mapa s dekriptiranim ML save-om')
    ap.add_argument('--players', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'players.json'))
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    r = read_save(a.folder, a.players)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    i = r['info']
    print(f"{i['slot']}: {i['club']} | {i['league']} | {i['date']} | {i['next_competition']}  (klubova u save-u: {r['clubs']})")
    for t in r.get('league_table', []):
        print(f"{t['pos']:>2} {t['club']:<28} {t['pl']:>2} {t['w']:>2} {t['d']:>2} {t['l']:>2} {t['gf']:>3}:{t['ga']:<3} {t['gd']:>+4} {t['pts']:>3}")
    sq = r.get('squad', [])
    print(f"Sastav ({len(sq)}):")
    for p in sq:
        print(f"  {p['slot']:>2} {p['id']:>7} {p['name']}")


if __name__ == '__main__':
    main()


# ---------- svi igraci i transfer lista ----------
FIRST_NATIONAL = 580   # indeks 'Albania'; iza toga su reprezentacije (izmjereno, v1.3)


def team_names(data, limit=693):
    out = []
    for k in range(limit):
        o = REC0 + k * STRIDE
        if o + STRIDE > len(data):
            break
        out.append(data[o:o + 48].split(b'\0')[0].decode('utf-8', 'replace'))
    return out


_CL_CACHE = {}


def club_layout(data):
    """pc186: koliko ima klubova i koji su reprezentacije. Klasicni / 45 MB: 'Albania' je na 580 i iza su reprezentacije (kao prije).
    Prosirena baza (tester PAOK, 2.400 mjesta): klubovi idu i iznad 580, a reprezentacije se prepoznaju po tome sto su
    gotovo svi njihovi igraci i u nekom klubu. -> (limit, set(indeksa reprezentacija))"""
    key = (len(data), bytes(data[REC0:REC0 + 48]), bytes(data[REC0 + 600 * STRIDE:REC0 + 600 * STRIDE + 48]) if len(data) > REC0 + 601 * STRIDE else b'')
    if key in _CL_CACHE:
        return _CL_CACHE[key]
    nm = lambda k: bytes(data[REC0 + k * STRIDE:REC0 + k * STRIDE + 48]).split(b'\0')[0]
    if REC0 + 581 * STRIDE <= len(data) and nm(FIRST_NATIONAL) == b'Albania':
        res = (FIRST_NATIONAL, frozenset())
    else:
        lim, empty = 0, 0
        for k in range(2400):
            o = REC0 + k * STRIDE
            if o + STRIDE > len(data):
                break
            # pc264: kraj tablice klubova = prvi zapis ciji kljuc (u32 na 80 + 1680*k = teamID<<14 | k) ne odgovara indeksu
            # (FL27: tablica od 750 mjesta, iza nje su drugi podaci koji izgledaju kao imena; 45 MB: 1600; 60 MB: 2400)
            _kk = struct.unpack_from('<I', data, 80 + k * STRIDE)[0]
            if _kk != 0xffffffff and (_kk & 0x3fff) != k:
                break
            n = data[o + 1058]
            s = nm(k)
            ok = len(s) >= 2 and n <= 40
            try:
                s.decode('utf-8')
            except Exception:
                ok = False
            if ok and n:
                lim, empty = k + 1, 0
            else:
                empty += 1
                if empty >= 30:
                    break
        owners = {}
        for k in range(lim):
            o = REC0 + k * STRIDE + SQUAD_OFF
            for i in range(min(SQUAD_SLOTS, data[REC0 + k * STRIDE + 1058])):
                pid = struct.unpack_from('<I', data, o + i * 8)[0]
                if 0 < pid < 400000:
                    owners.setdefault(pid, []).append(k)
        nat = set()
        for k in range(lim):
            o = REC0 + k * STRIDE + SQUAD_OFF
            n = min(SQUAD_SLOTS, data[REC0 + k * STRIDE + 1058])
            pids = [struct.unpack_from('<I', data, o + i * 8)[0] for i in range(n)]
            pids = [x for x in pids if 0 < x < 400000]
            if len(pids) >= 11 and sum(1 for x in pids if len(owners.get(x, ())) > 1) >= 0.7 * len(pids):
                nat.add(k)
        # pc261: velik klub s malim sastavom gotovo samih reprezentativaca (Arsenal 1.7., 17 igraca, 13 u reprezentacijama)
        # izgleda isto kao reprezentacija. Razlika: igraci reprezentacije su drugdje u KLUBOVIMA, a igraci tog kluba drugdje u
        # REPREZENTACIJAMA. Kandidat ciji su dijeljeni igraci vecinom u drugim kandidatima je klub.
        drop = set()
        for k in nat:
            o = REC0 + k * STRIDE + SQUAD_OFF
            n = min(SQUAD_SLOTS, data[REC0 + k * STRIDE + 1058])
            sh = [x for x in (struct.unpack_from('<I', data, o + i * 8)[0] for i in range(n)) if 0 < x < 400000 and len(owners.get(x, ())) > 1]
            inn = sum(1 for x in sh if any(k2 != k and k2 in nat for k2 in owners[x]))
            if sh and inn > 0.5 * len(sh):
                drop.add(k)
        nat -= drop
        # reprezentacije su jedan neprekinut blok na kraju tablice (60 MB: od 1723 do kraja, ukljucujuci slabe reprezentacije cijih
        # igraca nema u klubovima, npr. Andora, i 'World Selection'): blok pocinje na prvom kandidatu iza kojeg je gusto kandidata
        cs = sorted(nat)
        start = next((c for c in cs if sum(1 for x in cs if c <= x < c + 60) >= 15), None)
        if start is not None:
            nat = set(range(start, lim))
        res = (lim or FIRST_NATIONAL, frozenset(nat))
    _CL_CACHE[key] = res
    return res


def all_players(data):
    """{id: (indeks_kluba, naziv_kluba, tag)} iz sastava klubova (ne reprezentacija)."""
    lim, nat = club_layout(data)
    names = team_names(data, max(693, lim))
    out = {}
    for k in range(min(lim, len(names))):
        if k in nat:
            continue
        o = REC0 + k * STRIDE + SQUAD_OFF
        for i in range(SQUAD_SLOTS):
            pid, tag = struct.unpack_from('<II', data, o + i * 8)
            if 0 < pid < 400000 and pid not in out:
                out[pid] = (k, names[k], tag)
    return out


def transfer_list(data):
    """Zapisi s transfer liste (112 B): [u32 oznaka][u32 tag][u32 id][u32 0xffff] ... +52 datum (u16 god, mj, dan).
    Izmjereno testom: igrac stavljen na listu upisuje se u prvo slobodno mjesto."""
    import re
    pl = all_players(data)
    out = []
    for m in re.finditer(b'\x9f\x48', data):
        p = m.start()
        o = p - 6            # pocetak zapisa (tag je na +4)
        if o < 0 or o % 4 or o + 112 > len(data):
            continue
        v, tag, pid, w = struct.unpack_from('<IIII', data, o)
        if v >= 0x400 or w != 0xffff or not (0 < pid < 400000) or struct.unpack_from('<I', data, o + 48)[0] != 0xffff:
            continue
        y, mo, d = struct.unpack_from('<HBB', data, o + 52)
        if not (2000 < y < 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            y = mo = d = 0
        c = pl.get(pid)
        out.append(dict(offset=o, id=pid, club=c[1] if c else '', club_idx=c[0] if c else -1,
                        date='%d/%d/%d' % (d, mo, y) if y else '', code=v))
    return out
