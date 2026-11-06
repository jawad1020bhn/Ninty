"""Dijagnostika rasporeda savea za nove verzije exea (FL27 i dalje).

Trazi poznate tablice srednjeg dijela savea po igracima tvoje momcadi: par (oznaka, id igraca) se u svakoj od tih tablica
pojavljuje jednom po redu, pa razmak izmedju pogodaka daje velicinu reda, a polozaj daje pomak tablice.
Rezultat je izvjestaj (za datoteku podrske i Setup), ne mijenja save i ne ukljucuje pisanje.
"""
import math
import re
import struct

# (ime, adresa u referentnom prosirenom 45 MB saveu, velicina reda, opis)
TABLES = (
    ('S8', 0x2474f94, 44, 'squad slots (44 B)'),
    ('S10', 0x24bf54c, 368, 'player season data (368 B)'),
    ('S11', 0x24e8c84, 192, 'player data (192 B)'),
    ('S12', 0x24ee690, 52, 'squad register (52 B)'),
    ('S15', 0x28b886c, 5628, 'player records (5628 B)'),
)
# provjereno na 8 prosirenih saveova (razlicite karijere i baze): ovih 5 tablica je uvijek na istom mjestu.
# S1, S2, S9, S13, S14, L4, L5 su kratke liste kojima se pocetak mijenja od savea do savea, pa nisu pouzdane za ovu provjeru.


def _hits(d, pairs):
    out = []
    for pid, pb in pairs.items():
        for m in re.finditer(re.escape(pb), d):
            out.append(m.start())
    out.sort()
    return out


def _chains(hs, st, max_rows=45):
    """Nizovi pogodaka ciji su razmaci visekratnici velicine reda st (rupe do max_rows redova)."""
    res, cur = [], []
    for h in hs:
        if cur and (h - cur[-1]) % st == 0 and 0 < h - cur[-1] <= st * max_rows:
            cur.append(h)
        else:
            if len(cur) >= 3:
                res.append(cur)
            cur = [h]
    if len(cur) >= 3:
        res.append(cur)
    return res


def _clusters(hs, gap=8000):
    res, cur = [], []
    for h in hs:
        if cur and h - cur[-1] > gap:
            res.append(cur)
            cur = []
        cur.append(h)
    if cur:
        res.append(cur)
    return res


def scan(d, squad_tags, dx=0, window=1500000):
    """d: bytes savea; squad_tags: {pid: tag}; dx: pomak srednjeg dijela iz sidara (0 ako nije poznat).
    -> dict(tables=[...], summary)"""
    d = bytes(d)
    pairs = {pid: struct.pack('<II', tag, pid) for pid, tag in squad_tags.items() if pid}
    hs = _hits(d, pairs)
    out = []
    for name, ref, st, desc in TABLES:
        exp = ref + dx
        near = [h for h in hs if exp - window <= h <= exp + window]
        best = None
        for ch in _chains(near, st):
            dl = ch[0] - exp
            aligned = dl % st == 0 and abs(dl) <= st * 45
            score = (aligned, len(ch) >= 5, -abs(dl), len(ch))
            if best is None or score > best[0]:
                best = (score, ch)
        row = dict(name=name, desc=desc, expected=exp, row_size=st)
        if best and len(best[1]) >= 5:
            ch = best[1]
            delta = ch[0] - exp
            row.update(found=ch[0], hits=len(ch), found_row=st)
            if delta % st == 0 and abs(delta) <= st * 45:
                row['status'] = 'ok'
            else:
                row.update(status='moved', moved_by=delta)
        else:
            # velicina reda se mozda promijenila: probaj druge velicine reda i trazi niz pogodaka blizu ocekivanog pocetka
            loc = [h for h in near if exp - 200000 <= h <= exp + 400000]
            cand = None
            for g in range(8, 8192, 4):
                if g == st:
                    continue
                for ch in _chains(loc, g):
                    if len(ch) < 8 or abs(ch[0] - exp) > max(4096, 3 * g):
                        continue
                    # niz mora imati pogotke u vecini redova (ne samo visekratnik vece tablice)
                    rows = (ch[-1] - ch[0]) // g + 1
                    if len(ch) < rows * 0.5:
                        continue
                    sc = (len(ch), g, -abs(ch[0] - exp))   # isti pogoci: veci red (manji je samo njegov djelitelj)
                    if cand is None or sc > cand[0]:
                        cand = (sc, ch, g)
            if cand:
                _, ch, g = cand
                row.update(status='row_size_changed', found=ch[0], hits=len(ch), found_row=g, moved_by=ch[0] - exp)
            else:
                row['status'] = 'not_found'
        out.append(row)
    n_ok = sum(1 for r in out if r['status'] == 'ok')
    moved = sorted({r.get('moved_by') for r in out if r['status'] == 'moved'})
    changed = [r['name'] for r in out if r['status'] == 'row_size_changed']
    missing = [r['name'] for r in out if r['status'] == 'not_found']
    if n_ok == len(out):
        summ = 'All %d tables found where expected.' % len(out)
    else:
        parts = ['%d of %d tables in place' % (n_ok, len(out))]
        if moved:
            parts.append('moved: %s' % ', '.join('%s (%+d B)' % (r['name'], r['moved_by']) for r in out if r['status'] == 'moved'))
        if changed:
            parts.append('row size changed: %s' % ', '.join('%s %d→%d B' % (r['name'], r['row_size'], r['found_row']) for r in out if r['status'] == 'row_size_changed'))
        if missing:
            parts.append('not found: %s' % ', '.join(missing))
        summ = '; '.join(parts) + '.'
    return dict(tables=out, summary=summ, hits=len(hs), players=len(pairs))


if __name__ == '__main__':
    # za autora: python lib/layoutscan.py <mapa dekriptiranog savea>
    import json, os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mlwrite
    s = mlwrite.Save(sys.argv[1])
    print('shift', s.sh, 'dx', s.dx, 'layout ok', s.layout_ok, s.layout_note)
    r = scan(s.d, s.my_squad_tags(), s.dx if s.ext else 0)
    print(r['summary'])
    print(json.dumps(r['tables'], indent=1))
