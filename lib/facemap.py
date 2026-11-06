"""facemap.py - automatsko povezivanje igraca iz baze (PES id) s FM licima (FM Unique ID iz Genie Scout izvoza).
Ista pravila kao faces/napravi_mapu.py: (1) tocno ime (jedinstveno ili uz istu drzavu), (2) inicijal + prezime uz istu drzavu
(drzave PES kod -> FM naziv uce se iz jedinstvenih podudaranja). Bez priblizanog podudaranja (davalo je krive igrace)."""
import collections
import csv
import io
import re
import unicodedata


def _fold(s):
    s = unicodedata.normalize('NFKD', s.lower().replace('ø', 'o').replace('đ', 'd').replace('ł', 'l').replace('ß', 'ss').replace('æ', 'ae'))
    return ''.join(c for c in s if not unicodedata.combining(c))


def norm(s):
    s = re.sub(r"[^a-z0-9 ]", " ", _fold(s).replace("'", "").replace("-", " "))
    return ' '.join(sorted(s.split()))


def rawtok(s):
    return re.sub(r"[^a-z0-9 ]", " ", _fold(s).replace("'", "").replace("-", " ")).split()


def read_fm(raw):
    """Genie Scout CSV (;, cp1252) -> lista dict(uid, name, nation[])"""
    for enc in ('cp1252', 'utf-8-sig', 'utf-8'):
        try:
            txt = raw.decode(enc)
            break
        except Exception:
            continue
    out = []
    for row in csv.DictReader(io.StringIO(txt), delimiter=';'):
        if (row.get('Gen') or 'M') != 'M' or not row.get('Unique ID'):
            continue
        n = row.get('Name') or ''
        if ', ' in n:
            last, first = n.split(', ', 1)
            n = first + ' ' + last
        out.append(dict(uid=row['Unique ID'].strip(), name=n, nation=[x.strip() for x in (row.get('Nation') or '').split('/') if x.strip()]))
    return out


def is_fm_csv(raw):
    head = raw[:400].decode('cp1252', 'ignore')
    return 'Unique ID' in head and 'Nation' in head


def _same_first(a, b):
    """Ime iz FM-a i PES-a: isto ili jedno je skraceni oblik drugog (Zac/Zachary, Sam/Samuel), ne samo ista prva slova (Brandon != Brayan)."""
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


def build(fm, players):
    """players: lista (pid, puno_ime, kratko_ime, drzava_kod, drzava2_kod) -> {pid: uid}"""
    byname = collections.defaultdict(list)
    for x in fm:
        byname[norm(x['name'])].append(x)
    out = {}
    cc = collections.defaultdict(collections.Counter)
    for pid, full, short, c1, c2 in players:
        c = byname.get(norm(full or short), [])
        if len(c) == 1:
            out[pid] = c[0]['uid']
            for n in c[0]['nation'][:1]:
                cc[str(c1)][n] += 1
    # dodatno ucenje drzava: inicijal + prezime jedinstveno u cijelom FM izvozu (za baze s kratkim imenima, npr. 'R. Santa Cruz')
    anyidx = collections.defaultdict(list)
    for x in fm:
        raw = rawtok(x['name'])
        if len(raw) >= 2:
            anyidx[(raw[0][0], ' '.join(raw[1:]))].append(x)
            anyidx[(raw[0][0], raw[-1])].append(x)
    for pid, full, short, c1, c2 in players:
        t = rawtok(short or full or '')
        if len(t) >= 2:
            c = {x['uid']: x for x in anyidx.get((t[0][0], ' '.join(t[1:])), [])}
            if len(c) == 1:
                for n in list(c.values())[0]['nation'][:1]:
                    cc[str(c1)][n] += 1
    cmap = {k: v.most_common(1)[0][0] for k, v in cc.items()}
    for pid, full, short, c1, c2 in players:
        c = byname.get(norm(full or short), [])
        if len(c) > 1:
            nats = [n for n in (cmap.get(str(c1)), cmap.get(str(c2))) if n]
            cn = [x for x in c if any(n in x['nation'] for n in nats)]
            if len(cn) == 1:
                out[pid] = cn[0]['uid']
    idx = collections.defaultdict(list)
    for x in fm:
        raw = rawtok(x['name'])
        if not raw:
            continue
        for n in x['nation']:
            for i in range(1, len(raw)):
                idx[(n, raw[0][0], ' '.join(raw[i:]))].append(x)
    for pid, full, short, c1, c2 in players:
        if pid in out or byname.get(norm(full or short)):
            continue
        nats = [n for n in (cmap.get(str(c1)), cmap.get(str(c2))) if n]
        ft = rawtok(full) if full else []
        # puno ime (s pravim imenom) ima prednost; kratko ime (inicijal) samo kad punog imena nema
        for nm in ([full] if ft and len(ft[0]) > 2 else [x for x in (full, short) if x]):
            t = rawtok(nm)
            if len(t) < 2:
                continue
            got = None
            for n in nats:
                cands = {x['uid']: x for x in idx.get((n, t[0][0], ' '.join(t[1:])), [])
                         if len(t[0]) <= 2 or _same_first(rawtok(x['name'])[0], t[0])}
                if len(cands) == 1:
                    got = list(cands)[0]
                    break
            if got:
                out[pid] = got
                break
    return out
