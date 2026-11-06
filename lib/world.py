"""Knjiga svijeta (world ledger): jedan dnevnik dogadjaja po karijeri.

Svaki sustav appa (AI transferi, moji transferi, prodaje, posudbe, zahtjevi igraca, konferencije, taktike AI trenera,
preuzimanja klubova, nagrade...) upisuje dogadjaj s datumom u igri i sudionicima. Iz dnevnika se grade povijest igraca,
klubova i sezona, pa vijesti, uprava, navijaci i AI odluke mogu citati isti izvor.

Datoteka: data/world/<career id>.jsonl (red = JSON dogadjaj). Svaki dogadjaj ima jedinstveni 'key' (dvostruki upis se preskace).
Polja: key, kind, d (YYYY-MM-DD datum u igri), season (pocetna godina sezone, sezona pocinje 1.7.),
       pid (igrac, opcionalno), clubs (popis imena klubova koji sudjeluju), te podaci dogadjaja.
"""
import jsafe  # pc251: sigurno spremanje JSON-a
import json
import os
import threading

_LOCK = threading.Lock()
_CACHE = {}   # path -> dict(mtime, size, events, keys)


def date_str(code):
    """Kod datuma iz save-a (d<<24 | m<<16 | y) -> 'YYYY-MM-DD'."""
    try:
        code = int(code)
        d, m, y = code >> 24, (code >> 16) & 0xff, code & 0xffff
        if 1 <= d <= 31 and 1 <= m <= 12 and 1900 < y < 2200:
            return '%04d-%02d-%02d' % (y, m, d)
    except Exception:
        pass
    return ''


def parse_when(w):
    """'27/8/2025' ili '27.8.2025' -> 'YYYY-MM-DD' (ili '' ako ne valja)."""
    import re
    m = re.match(r'\s*(\d{1,2})[./](\d{1,2})[./](\d{4})', str(w or ''))
    if not m:
        return ''
    return '%04d-%02d-%02d' % (int(m.group(3)), int(m.group(2)), int(m.group(1)))


def season_of(d):
    """Sezona (pocetna godina) za datum 'YYYY-MM-DD': srpanj..lipanj."""
    try:
        y, m = int(d[:4]), int(d[5:7])
        return y if m >= 7 else y - 1
    except Exception:
        return None


class Ledger:
    def __init__(self, folder, career_id):
        self.folder = folder
        self.id = career_id
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, '%s.jsonl' % career_id)
        self.meta_path = os.path.join(folder, '%s.meta.json' % career_id)

    # ---- citanje (keš po mtime/size)
    def _load(self):
        try:
            st = os.stat(self.path)
        except OSError:
            return dict(events=[], keys=set())
        c = _CACHE.get(self.path)
        if c and c['mtime'] == st.st_mtime and c['size'] == st.st_size:
            return c
        ev, keys = [], set()
        with open(self.path, encoding='utf-8') as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                if e.get('key') in keys:
                    continue
                keys.add(e.get('key'))
                ev.append(e)
        c = dict(mtime=st.st_mtime, size=st.st_size, events=ev, keys=keys)
        _CACHE[self.path] = c
        return c

    def events(self):
        return list(self._load()['events'])

    def has(self, key):
        return key in self._load()['keys']

    # ---- upis
    def add(self, kind, d, key, pid=None, clubs=None, **data):
        """Dodaj dogadjaj (ako kljuc vec postoji, ne radi nista). d = 'YYYY-MM-DD'."""
        if not key:
            return False
        with _LOCK:
            if self.has(key):
                return False
            e = dict(key=key, kind=kind, d=d or '', season=season_of(d or ''))
            if pid:
                e['pid'] = int(pid)
            cl = [c for c in (clubs or []) if c]
            if cl:
                e['clubs'] = sorted(set(cl))
            for k, v in data.items():
                if v is not None and v != '':
                    e[k] = v
            with open(self.path, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(e, ensure_ascii=False) + '\n')
            return True

    def add_many(self, items):
        """items: [(kind, d, key, pid, clubs, data)] u jednom upisu (backfill)."""
        n = 0
        with _LOCK:
            have = self._load()['keys']
            lines = []
            for kind, d, key, pid, clubs, data in items:
                if not key or key in have:
                    continue
                have.add(key)
                e = dict(key=key, kind=kind, d=d or '', season=season_of(d or ''))
                if pid:
                    e['pid'] = int(pid)
                cl = [c for c in (clubs or []) if c]
                if cl:
                    e['clubs'] = sorted(set(cl))
                for k, v in (data or {}).items():
                    if v is not None and v != '':
                        e[k] = v
                lines.append(json.dumps(e, ensure_ascii=False))
            if lines:
                with open(self.path, 'a', encoding='utf-8') as fh:
                    fh.write('\n'.join(lines) + '\n')
                n = len(lines)
            _CACHE.pop(self.path, None)
        return n

    def prune_after(self, d):
        """pc354: dogadjaji s datumom iza d ('YYYY-MM-DD') se maknu u <id>.future.jsonl (ucitan stariji save iste karijere
        ili nova karijera istog kluba i menadzera). -> broj maknutih"""
        with _LOCK:
            ev = self._load()['events']
            fut = [e for e in ev if e.get('d') and e['d'] > d]
            if not fut:
                return 0
            keep = [e for e in ev if not (e.get('d') and e['d'] > d)]
            with open(os.path.join(self.folder, '%s.future.jsonl' % self.id), 'a', encoding='utf-8') as fh:
                fh.write('\n'.join(json.dumps(e, ensure_ascii=False) for e in fut) + '\n')
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                fh.write(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in keep))
            os.replace(tmp, self.path)
            _CACHE.pop(self.path, None)
            return len(fut)

    # ---- meta (npr. je li backfill napravljen)
    def meta(self):
        try:
            return json.load(open(self.meta_path, encoding='utf-8'))
        except Exception:
            return {}

    def set_meta(self, **kw):
        m = self.meta()
        m.update(kw)
        jsafe.jdump(m, self.meta_path, ensure_ascii=False, indent=1)

    # ---- upiti
    def query(self, kind=None, pid=None, club=None, season=None, since=None, limit=None):
        out = []
        kinds = set(kind) if isinstance(kind, (list, tuple, set)) else ({kind} if kind else None)
        for e in self._load()['events']:
            if kinds and e.get('kind') not in kinds:
                continue
            if pid is not None and e.get('pid') != int(pid):
                continue
            if club and club not in (e.get('clubs') or []):
                continue
            if season is not None and e.get('season') != int(season):
                continue
            if since and (e.get('d') or '') < since:
                continue
            out.append(e)
        out.sort(key=lambda e: (e.get('d') or '', e.get('key')))
        return out[-limit:] if limit else out

    def player(self, pid):
        """Povijest igraca u ovom svijetu: put kroz klubove (s naknadama), nagrade, dogadjaji."""
        ev = self.query(pid=pid)
        path = [e for e in ev if e.get('kind') in ('ai_transfer', 'signed', 'sold', 'loaned', 'loan_in', 'game_transfer')]
        return dict(pid=int(pid), events=ev, moves=path,
                    awards=[e for e in ev if e.get('kind') == 'award'])

    def club(self, name):
        """Povijest kluba: dolasci/odlasci po sezonama (broj i novac), ostali dogadjaji."""
        ev = self.query(club=name)
        seasons = {}
        for e in ev:
            if e.get('kind') not in ('ai_transfer', 'signed', 'sold', 'game_transfer', 'loaned', 'loan_in'):
                continue
            s = seasons.setdefault(e.get('season'), dict(season=e.get('season'), ins=0, outs=0, spent=0, earned=0, moves=[]))
            to, frm, fee = e.get('to'), e.get('frm'), int(e.get('fee') or 0)
            if to == name:
                s['ins'] += 1
                s['spent'] += fee
            elif frm == name:
                s['outs'] += 1
                s['earned'] += fee
            s['moves'].append(e)
        other = [e for e in ev if e.get('kind') not in ('ai_transfer', 'game_transfer')]
        return dict(club=name, seasons=sorted(seasons.values(), key=lambda x: x['season'] or 0, reverse=True), events=other[-60:])

    def season_summary(self, season):
        ev = self.query(season=season)
        moves = [e for e in ev if e.get('kind') in ('ai_transfer', 'signed', 'sold', 'game_transfer')]
        top = sorted(moves, key=lambda e: -(int(e.get('fee') or 0)))[:10]
        by = {}
        for e in ev:
            by[e['kind']] = by.get(e['kind'], 0) + 1
        return dict(season=season, counts=by, top_moves=top, total_fees=sum(int(e.get('fee') or 0) for e in moves))
