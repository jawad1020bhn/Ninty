"""pc307: stvarni transferi iz pravog zivota (Wikipedia popisi transfera) za pocetni save.

Baza igre ne zna kad je igrac dosao u klub (u saveu svi imaju 1.1. ili 1.7. 2025.), pa bi AI transferi odmah prodali
igraca kojeg je klub tek kupio u stvarnosti. Ovdje se jednom skinu Wikipedia popisi transfera (ljeto 2025, zima 2025-26)
za glavne lige, rezultat se spremi u data/realmoves.json i dalje radi bez interneta.

Igrac se broji samo ako se IME i ODREDISNI KLUB poklapaju s klubom u saveu (pa nema laznih pogodaka; ako se ne poklopi,
igrac jednostavno nije zasticen)."""
import html.parser
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request

UA = 'Karijera26/1.0 (osobna companion aplikacija; kontakt: lokalno)'
API = 'https://en.wikipedia.org/w/api.php'

NATIONS = ('English', 'Spanish', 'Italian', 'German', 'French', 'Portuguese', 'Dutch', 'Scottish', 'Turkish', 'Belgian',
           'Saudi Arabian', 'Greek', 'Austrian', 'Swiss', 'Danish', 'Brazilian', 'Argentine', 'Mexican')
WINDOWS = ('summer 2025', 'winter 2025–26', 'summer 2026', 'winter 2026–27')   # pc379: i 2026 za Football Life 2027
PAGES = ['List of %s football transfers %s' % (n, w) for w in WINDOWS for n in NATIONS]

MONTHS = {m: i + 1 for i, m in enumerate(('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                                          'september', 'october', 'november', 'december'))}
STOP = {'fc', 'cf', 'afc', 'sc', 'ac', 'as', 'ssc', 'club', 'de', 'the', 'cd', 'ud', 'sd', 'rc', 'rcd', 'ca', 'sv', 'vfl', 'vfb',
        'tsg', 'fk', 'sk', 'if', 'bk', 'calcio', 'football', 'futbol', 'futebol', 'clube', 'and', 'of', 'deportivo', 'sporting'}


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace('ø', 'o').replace('ı', 'i').replace('ß', 'ss').replace('ł', 'l').replace('æ', 'ae')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', s).split())


def club_tokens(s):
    return {t for t in norm(s).split() if t not in STOP and len(t) >= 2}


def club_match(a, b):
    """Isti klub: sve bitne rijeci kraceg imena su u duljem ('Liverpool' ~ 'Liverpool FC', 'Bayer Leverkusen' ~ 'Bayer 04 Leverkusen')."""
    ta, tb = club_tokens(a), club_tokens(b)
    ta = {t for t in ta if not t.isdigit()}
    tb = {t for t in tb if not t.isdigit()}
    if not ta or not tb:
        return False
    s, l = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return s <= l


def parse_date(t):
    t = norm(t)
    m = re.search(r'(\d{1,2}) ([a-z]+) (20\d\d)', t)
    if m and m.group(2) in MONTHS:
        return '%s-%02d-%02d' % (m.group(3), MONTHS[m.group(2)], int(m.group(1)))
    m = re.search(r'([a-z]+) (\d{1,2}) (20\d\d)', t)
    if m and m.group(1) in MONTHS:
        return '%s-%02d-%02d' % (m.group(3), MONTHS[m.group(1)], int(m.group(2)))
    m = re.search(r'(20\d\d) (\d\d) (\d\d)', t)
    if m:
        return '%s-%s-%s' % m.groups()
    return None


PV = 4   # pc379: verzija citaca; stranice koje stari citac nije razumio (ok=False) skidaju se ponovno


class _Tables(html.parser.HTMLParser):
    """Sve tablice 'wikitable' (i ugnijezdene, npr. In/Out po klubu): redovi -> celije (tekst, rowspan, th?).
    Uz svaku tablicu pamti zadnji naslov (h2-h4) iznad nje = klub na stranicama 'po klubovima'.
    Skriveni tekst (display:none, sortkey) se preskace."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack, self.hide = [], [], []
        self.cell = None
        self.row = None
        self.head = ''
        self.htxt = None

    def handle_starttag(self, tag, a):
        a = dict(a)
        st = (a.get('style') or '').replace(' ', '').lower()
        cls = a.get('class') or ''
        hidden = 'display:none' in st or 'sortkey' in cls or 'mw-editsection' in cls or 'reference' in cls
        if tag not in ('br', 'img', 'meta', 'link', 'wbr', 'hr', 'input'):
            self.hide.append(hidden)
        if tag in ('h2', 'h3', 'h4'):
            self.htxt = ''
        elif tag == 'table':
            t = dict(wt='wikitable' in cls, rows=[], club=self.head)
            self.stack.append(t)
            if t['wt']:
                self.tables.append(t)
            self.row = None
        elif tag == 'tr' and self.stack and self.stack[-1]['wt']:
            self.row = []
            self.stack[-1]['rows'].append(self.row)
        elif tag in ('td', 'th') and self.row is not None and self.stack and self.stack[-1]['wt']:
            try:
                rs = int(re.sub(r'\D', '', a.get('rowspan') or '1') or 1)
            except ValueError:
                rs = 1
            try:
                cs = int(re.sub(r'\D', '', a.get('colspan') or '1') or 1)
            except ValueError:
                cs = 1
            self.cell = dict(t='', rs=rs, cs=cs, th=(tag == 'th'))
            self.row.append(self.cell)
        elif tag == 'br' and self.cell is not None:
            self.cell['t'] += ' '

    def handle_endtag(self, tag):
        if tag not in ('br', 'img', 'meta', 'link', 'wbr', 'hr', 'input') and self.hide:
            self.hide.pop()
        if tag in ('h2', 'h3', 'h4') and self.htxt is not None:
            self.head = ' '.join(re.sub(r'\[.*?\]', '', self.htxt).split())
            self.htxt = None
        elif tag == 'table' and self.stack:
            self.stack.pop()
            self.row = None
            self.cell = None
        elif tag in ('td', 'th'):
            self.cell = None
        elif tag == 'tr':
            self.row = None

    def handle_data(self, data):
        if any(self.hide):
            return
        if self.htxt is not None:
            self.htxt += data
        if self.cell is not None:
            self.cell['t'] += data


def _page_date(page):
    """Zadani datum kad tablica nema stupac s datumom: sredina prijelaznog roka iz naslova stranice."""
    m = re.search(r'(summer|winter) (20\d\d)', page or '')
    if not m:
        return None
    y = int(m.group(2))
    return '%d-07-15' % y if m.group(1) == 'summer' else '%d-01-15' % (y + 1)


def parse_html(text, page=None):
    """-> [(date, player, frm, to)]. Dva oblika Wikipedije: jedna tablica datum/igrac/od/do (Engleska, Italija...),
    ili po klubovima: naslov kluba + tablice 'In' (igrac, od) i 'Out' (igrac, za) (Njemacka, Francuska, Spanjolska...)."""
    p = _Tables()
    p.feed(text)
    out = []
    dflt = _page_date(page)
    for tb in p.tables:
        rows = tb['rows']
        if not rows:
            continue
        hdr = [' '.join(c['t'].split()).lower() for c in rows[0] for _ in range(c['cs'])]
        def col(*keys, exact=()):
            for i, h in enumerate(hdr):
                if h in exact or any(k in h for k in keys):
                    return i
            return None
        ci_d, ci_p = col('date'), col('player', 'name')
        ci_f = col('from')
        ci_t = col(exact=('to', 'to club', 'transferred to', 'new club'))
        if ci_t is None:
            for i, h in enumerate(hdr):
                if (h.endswith(' to') or h == 'to') and i != ci_f:
                    ci_t = i
                    break
        if ci_t is not None and ci_t == ci_f:
            ci_t = None
        club = tb.get('club') or ''
        if ci_p is None:
            continue
        inline = ci_f is None and ci_t is None
        if inline and not club:
            continue   # 'football-squad' tablica bez kluba iznad nje
        if ci_f is None or ci_t is None:
            if not club:
                continue   # tablica samo s 'od' ili 'za' bez kluba iznad nje
        carry = {}   # kolona -> [preostalo, tekst]
        for r in rows[1:]:
            vals, it = [], iter(r)
            c = 0
            while c < len(hdr):
                if c in carry and carry[c][0] > 0:
                    vals.append(carry[c][1])
                    carry[c][0] -= 1
                    c += 1
                    continue
                cell = next(it, None)
                if cell is None:
                    break
                t = ' '.join(cell['t'].split())
                for k in range(cell['cs']):
                    vals.append(t)
                    if cell['rs'] > 1:
                        carry[c + k] = [cell['rs'] - 1, t]
                c += cell['cs']
            need = [x for x in (ci_d, ci_p, ci_f, ci_t) if x is not None]
            if len(vals) <= max(need):
                continue
            dt = (parse_date(vals[ci_d]) if ci_d is not None else None) or dflt
            if inline:
                # pc379: 'Jonathan Tah (from Bayer Leverkusen)' / 'Leroy Sane (to Galatasaray)' / '(on loan from X)'
                m_ = re.match(r'\s*(.+?)\s*\((?:on\s+)?(?:loan\s+)?(?:return\s+)?(from|to)\s+(.+?)\)', re.sub(r'\[.*?\]', '', vals[ci_p]), re.I)
                if not m_ or not dt:
                    continue
                pl, d_, oc = m_.group(1).strip(), m_.group(2).lower(), m_.group(3).strip()
                out.append((dt, pl, oc, club) if d_ == 'from' else (dt, pl, club, oc))
                continue
            pl = re.sub(r'\[.*?\]', '', vals[ci_p]).strip()
            frm = vals[ci_f] if ci_f is not None else club
            to = vals[ci_t] if ci_t is not None else club
            if dt and pl and to:
                out.append((dt, pl, frm, to))
    return out


LAST_RAW = {}


def _get(page, timeout=20):
    q = urllib.parse.urlencode(dict(action='parse', page=page, prop='text', format='json', formatversion=2, redirects=1))
    req = urllib.request.Request(API + '?' + q, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode('utf-8', 'replace')
    LAST_RAW['raw'] = raw
    j = json.loads(raw)
    return (j.get('parse') or {}).get('text') or ''


def fetch_all(path, pages=PAGES, gap=2.0):
    """Skine sve popise (jednom; vec skinute stranice se preskacu) i spremi u path. -> dict"""
    st = {}
    if os.path.exists(path):
        try:
            st = json.load(open(path, encoding='utf-8'))
        except Exception:
            st = {}
    done = st.setdefault('pages', {})
    rows = st.setdefault('rows', [])
    changed = False
    for pg in pages:
        dn = done.get(pg) or {}
        if dn.get('ok') is not None and time.time() - dn.get('t', 0) < 30 * 86400 and (dn.get('ok') or dn.get('pv', 1) >= PV):
            continue
        try:
            txt = _get(pg)
            got = parse_html(txt, pg) if txt else []
            if not got:   # pc379: za dijagnozu spremi sto je Wikipedija vratila (najvise nekoliko stranica)
                try:
                    dd = os.path.join(os.path.dirname(path), 'realmoves_dbg')
                    os.makedirs(dd, exist_ok=True)
                    if len(os.listdir(dd)) < 6:
                        open(os.path.join(dd, re.sub(r'[^A-Za-z0-9]+', '_', pg)[:80] + '.json'), 'w', encoding='utf-8').write(LAST_RAW.get('raw', '')[:3000000])
                except Exception:
                    pass
            rows[:] = [r for r in rows if r[4] != pg] + [list(r) + [pg] for r in got]
            done[pg] = dict(ok=bool(got), n=len(got), t=time.time(), pv=PV)
        except Exception as ex:
            done[pg] = dict(ok=None if 'HTTP Error 404' not in str(ex) else False, err=str(ex)[:120], t=time.time())
            if '429' in str(ex):
                time.sleep(30)   # pc379: Wikipedija trazi da usporimo
        changed = True
        _nd = sum(1 for v in done.values() if v.get('t', 0) > time.time() - 3600)
        if _nd % 6 == 0:   # pc379: spremi usput (prije tek na kraju svih stranica)
            try:
                json.dump(st, open(path + '.tmp', 'w', encoding='utf-8'))
                os.replace(path + '.tmp', path)
            except Exception:
                pass
        time.sleep(gap)
    if changed:
        tmp = path + '.tmp'
        json.dump(st, open(tmp, 'w', encoding='utf-8'))
        os.replace(tmp, path)
    return st


def match(rows, players):
    """rows: [(date, ime, od, do, stranica)], players: [{id, name, club}] (klub iz savea).
    -> {pid: {date, frm, to}} samo gdje se poklapaju ime i odredisni klub (najnoviji potez)."""
    by = {}
    for p in players:
        by.setdefault(norm(p.get('name')), []).append(p)
    out = {}
    for r in rows:
        dt, nm, frm, to = r[0], r[1], r[2], r[3]
        for p in by.get(norm(nm), []):
            if p.get('club') and club_match(to, p['club']):
                o = out.get(p['id'])
                if not o or o['date'] < dt:
                    out[p['id']] = dict(date=dt, frm=frm, to=to)
    return out
