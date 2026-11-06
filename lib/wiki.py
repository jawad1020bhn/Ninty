"""Wikipedia podaci o igracu: portret, kratki opis i prosli klubovi. Dohvaca se s racunala korisnika (treba internet) pri prvom otvaranju kartice,
rezultat se sprema u data/wiki/<pid>.json i data/wiki/img/<pid>.jpg. Bez interneta ili bez clanka vraca ok=False i app radi dalje."""
import jsafe  # pc251: sigurno spremanje JSON-a
import json
import os
import re
import time
import urllib.parse
import urllib.request

UA = 'Karijera26/1.0 (osobna companion aplikacija; kontakt: lokalno)'
API = 'https://en.wikipedia.org'


_LAST = [0.0]
GAP = 0.6          # najmanje sekundi izmedju dva upita (Wikipedia ogranicava brze)


def _get(url, timeout=12, binary=False):
    d = GAP - (time.time() - _LAST[0])
    if d > 0:
        time.sleep(d)
    _LAST[0] = time.time()
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json' if not binary else '*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
    return b if binary else json.loads(b.decode('utf-8', 'replace'))


def _clean(t):
    t = re.sub(r'<ref[^>]*/>', '', t)
    t = re.sub(r'<ref[^>]*>.*?</ref>', '', t, flags=re.S)
    t = re.sub(r'<!--.*?-->', '', t, flags=re.S)
    t = re.sub(r'\{\{[^{}]*\}\}', '', t)
    t = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', t)
    t = t.replace("'''", '').replace("''", '')
    t = re.sub(r'<[^>]+>', '', t)
    return t.strip()


def parse_career(wt):
    """Iz wikitexta infoboxa: [{years, club, loan, apps, goals, youth}] (seniorski i mladi klubovi)."""
    out = []
    for kind, ck, yk, ak, gk in (('y', 'youthclubs', 'youthyears', None, None), ('s', 'clubs', 'years', 'caps', 'goals')):
        vals = {}
        for m in re.finditer(r'^\s*\|\s*(%s|%s|%s|%s)(\d+)\s*=\s*(.*?)\s*$' % tuple(k or 'zzz' for k in (ck, yk, ak, gk)), wt, flags=re.M):
            vals.setdefault(int(m.group(2)), {})[m.group(1)] = m.group(3)
        for n in sorted(vals):
            v = vals[n]
            raw = v.get(ck, '')
            if not raw:
                continue
            loan = bool(re.search(r'\{\{\s*(?:loan|→)|^\s*→|\(loan\)', raw, flags=re.I))
            club = _clean(raw).lstrip('→').replace('(loan)', '').strip()
            if not club:
                continue
            out.append(dict(years=_clean(v.get(yk, '')), club=club, loan=loan, apps=_clean(v.get(ak, '')) if ak else '', goals=_clean(v.get(gk, '')) if gk else '', youth=(kind == 'y')))
    return out


def _career(key):
    q = urllib.parse.quote(key.replace(' ', '_'), safe='')
    for url in ('%s/w/api.php?action=parse&page=%s&prop=wikitext&section=0&format=json&redirects=1' % (API, q),
                '%s/w/api.php?action=parse&page=%s&prop=wikitext&format=json&redirects=1' % (API, q)):
        try:
            w = _get(url)
            c = parse_career(w['parse']['wikitext']['*'])
            if c:
                return c
        except Exception:
            pass
    return []


def _by(text):
    """Godina rodenja iz opisa/uvoda ('(born 2004)', 'born 12 March 2001', '(b. 2001)'), ili None."""
    m = re.search(r'\bborn\b[^0-9]{0,25}(?:\d{1,2}\s+\w+\s+|\w+\s+\d{1,2},\s*)?((?:19|20)\d\d)', text or '') or re.search(r'\(b\.\s*(?:\d{1,2}\s+\w+\s+)?((?:19|20)\d\d)', text or '')
    return int(m.group(1)) if m else None


def _ok_by(by, age, year):
    return not (by and age and abs(by - (year - age)) > 1)


def _picks(name, age=None, year=2025):
    q = urllib.parse.quote(name + ' footballer')
    r = _get('%s/w/rest.php/v1/search/page?q=%s&limit=8' % (API, q))
    good, maybe = [], []
    for p in r.get('pages', []):
        d = (p.get('description') or '').lower()
        if 'footballer' in d or 'soccer' in d or 'goalkeeper' in d:
            by = _by(d)
            if not _ok_by(by, age, year):
                continue
            (good if by else maybe).append(p['key'])
    return good + maybe


def fetch(pid, name, folder, age=None, year=2025):
    os.makedirs(os.path.join(folder, 'img'), exist_ok=True)
    fp = os.path.join(folder, '%s.json' % pid)
    try:
        c = json.load(open(fp, encoding='utf-8'))
        if c.get('ok') and not _ok_by(_by(c.get('description')) or _by(c.get('extract')), age, year):
            raise ValueError('krivo godiste')           # stari zapis je krivi igrac istog imena: dohvati ponovno
        ag = time.time() - c.get('t', 0)
        if c.get('ok') and c.get('title') and not c.get('career') and time.time() - c.get('ct', 0) > 600:
            c['career'] = _career(c['title']) or []        # prije je zapis mogao ostati bez karijere (greska/429): pokusaj opet
            c['ct'] = int(time.time())
            jsafe.jdump(c, fp, ensure_ascii=False)
            return c
        if c.get('ok') or (not c.get('error') and ag < 30 * 86400) or (c.get('error') and ag < 300):
            return c
    except Exception:
        pass
    res = dict(ok=False, t=int(time.time()), name=name)
    try:
        for key in _picks(name, age, year)[:4]:
            s = _get('%s/api/rest_v1/page/summary/%s' % (API, urllib.parse.quote(key, safe='')))
            if not _ok_by(_by(s.get('description')) or _by(s.get('extract')), age, year):
                continue
            res.update(ok=True, title=s.get('title'), description=s.get('description'), extract=s.get('extract'), url=((s.get('content_urls') or {}).get('desktop') or {}).get('page'))
            th = (s.get('thumbnail') or {}).get('source')
            ip = os.path.join(folder, 'img', '%s.jpg' % pid)
            if th:
                try:
                    open(ip, 'wb').write(_get(th, binary=True))
                    res['img'] = True
                except Exception:
                    pass
            res['career'] = _career(key)
            res['ct'] = int(time.time())
            break
        if not res.get('ok'):
            for f in ('%s.jpg' % pid, '%s_c.jpg' % pid):
                try:
                    os.remove(os.path.join(folder, 'img', f))
                except Exception:
                    pass
    except Exception as e:
        res['error'] = str(e)[:120]
        return res            # greska (429, mreza...): ne spremaj kao 'nema clanka', pokusat ce se ponovno
    jsafe.jdump(res, fp, ensure_ascii=False)
    return res


def norm_club(name):
    """Rezervne/mladje momcadi (Sporting CP B, Bayern Munich II, X U21) koriste grb matičnog kluba."""
    n = (name or '').strip()
    n2 = re.sub(r'\s+(B|II|III|U-?\d\d|Reserves?|Youth|Juniors?|Castilla|Atletic)$', '', n, flags=re.I).strip()
    return n2 or n


def _slug(name):
    import hashlib
    return hashlib.md5(norm_club(name).lower().encode('utf-8')).hexdigest()[:16]


def crest_path(folder, name):
    return os.path.join(folder, '%s.png' % _slug(name))


CLUB_KEYS = {
    'manchester united fc': 'Manchester_United_F.C.', 'newcastle united fc': 'Newcastle_United_F.C.', 'manchester city fc': 'Manchester_City_F.C.',
    'arsenal fc': 'Arsenal_F.C.', 'chelsea fc': 'Chelsea_F.C.', 'tottenham hotspur fc': 'Tottenham_Hotspur_F.C.', 'liverpool fc': 'Liverpool_F.C.',
    'everton fc': 'Everton_F.C.', 'fulham fc': 'Fulham_F.C.', 'brentford fc': 'Brentford_F.C.', 'aston villa fc': 'Aston_Villa_F.C.',
    'crystal palace fc': 'Crystal_Palace_F.C.', 'west ham united fc': 'West_Ham_United_F.C.', 'wolverhampton wanderers fc': 'Wolverhampton_Wanderers_F.C.',
    'brighton & hove albion fc': 'Brighton_&_Hove_Albion_F.C.', 'nottingham forest fc': 'Nottingham_Forest_F.C.', 'leeds united fc': 'Leeds_United_F.C.',
    'burnley fc': 'Burnley_F.C.', 'sunderland afc': 'Sunderland_A.F.C.', 'afc bournemouth': 'AFC_Bournemouth', 'southampton fc': 'Southampton_F.C.',
    'ipswich town fc': 'Ipswich_Town_F.C.', 'ac milan': 'A.C._Milan', 'fc internazionale milano': 'Inter_Milan', 'hamburger sv': 'Hamburger_SV',
    'real madrid cf': 'Real_Madrid_CF', 'fc barcelona': 'FC_Barcelona', 'fc bayern münchen': 'FC_Bayern_Munich', 'paris saint-germain fc': 'Paris_Saint-Germain_F.C.',
    'galatasaray aş': 'Galatasaray_S.K._(football)', 'sl benfica': 'S.L._Benfica', 'fc porto': 'FC_Porto', 'sporting cp': 'Sporting_CP',
    'juventus fc': 'Juventus_FC', 'borussia dortmund': 'Borussia_Dortmund', 'atlético de madrid': 'Atlético_Madrid', 'afc ajax': 'AFC_Ajax',
}


def fetch_club(name, folder):
    """Grb kluba: glavna slika Wikipedia clanka. Sprema data/crests/<md5>.png + <md5>.json. Greske (429/mreza) se ne pamte kao 'nema'."""
    os.makedirs(folder, exist_ok=True)
    fp = os.path.join(folder, '%s.json' % _slug(name))
    try:
        c = json.load(open(fp, encoding='utf-8'))
        age = time.time() - c.get('t', 0)
        okv = (norm_club(name).lower() not in CLUB_KEYS) or c.get('ov')
        if okv and (c.get('ok') or (not c.get('error') and age < 30 * 86400) or (c.get('error') and age < 300)):
            return c
    except Exception:
        pass
    res = dict(ok=False, t=int(time.time()), name=name)
    try:
        key = CLUB_KEYS.get(norm_club(name).lower())
        if key:
            res['ov'] = 1
        r = {} if key else _get('%s/w/rest.php/v1/search/page?q=%s&limit=6' % (API, urllib.parse.quote(norm_club(name) + ' football club')))
        for p in r.get('pages', []):
            d = (p.get('description') or '').lower()
            if re.search(r'football (club|team)|soccer|association football', d):
                key = p['key']
                break
        if key:
            s = _get('%s/api/rest_v1/page/summary/%s' % (API, urllib.parse.quote(key, safe='')))
            th = (s.get('thumbnail') or {}).get('source')
            if th:
                open(crest_path(folder, name), 'wb').write(_get(th, binary=True))
                res.update(ok=True, title=s.get('title'))
    except Exception as e:
        res['error'] = str(e)[:120]
        return res
    jsafe.jdump(res, fp, ensure_ascii=False)
    return res



def fetch_photo(pid, title, folder, name=''):
    """Druga, veca fotka igraca (siroka, po mogucnosti akcijska): trazi u Wikimedia Commons po imenu + slike iz clanka.
    Sprema img/<pid>_c.jpg. Vraca bytes ili None. Greske se ne pamte, 'nema' 14 dana."""
    d = os.path.join(folder, 'img')
    os.makedirs(d, exist_ok=True)
    fp, nf = os.path.join(d, '%s_c.jpg' % pid), os.path.join(d, '%s_c2.none' % pid)
    if os.path.exists(fp):
        return open(fp, 'rb').read()
    if os.path.exists(nf) and time.time() - os.path.getmtime(nf) < 14 * 86400:
        return None
    BAD = r'flag|logo|crest|badge|icon|signature|map|kit|stadium|autograph|shirt|jersey|statue|wax|trophy|cartoon|comic|caricature'
    try:
        nm = name or title
        sur = re.sub(r'[^a-z ]', '', urllib.parse.unquote(nm).lower().replace('-', ' ')).split()
        sur = sur[-1] if sur else ''
        s = _get('%s/api/rest_v1/page/summary/%s' % (API, urllib.parse.quote(title.replace(' ', '_'), safe='')))
        main = ((s.get('originalimage') or {}).get('source') or (s.get('thumbnail') or {}).get('source') or '')
        mname = re.sub(r'^\d+px-', '', urllib.parse.unquote(main.rstrip('/').split('/')[-1]).lower()) if main else ''
        pages = []
        try:
            r = _get('https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch=%s&gsrnamespace=6&gsrlimit=30&prop=imageinfo&iiprop=url|size|mime&iiurlwidth=1100&format=json'
                     % urllib.parse.quote('%s filetype:bitmap' % nm))
            pages += list((r.get('query', {}).get('pages', {}) or {}).values())
        except Exception:
            pass
        try:
            r = _get('%s/w/api.php?action=query&generator=images&titles=%s&gimlimit=40&prop=imageinfo&iiprop=url|size|mime&iiurlwidth=1100&format=json&redirects=1'
                     % (API, urllib.parse.quote(title)))
            pages += list((r.get('query', {}).get('pages', {}) or {}).values())
        except Exception:
            pass
        cands, seen = [], set()
        for pg in pages:
            ii = (pg.get('imageinfo') or [{}])[0]
            t = (pg.get('title') or '').lower()
            u = ii.get('thumburl') or ii.get('url')
            if not u or u in seen or ii.get('mime') != 'image/jpeg' or ii.get('width', 0) < 800 or re.search(BAD, t):
                continue
            seen.add(u)
            if mname and mname in urllib.parse.unquote(ii.get('url', '')).lower():
                continue
            ratio = ii.get('width', 1) / max(1, ii.get('height', 1))
            if ratio < 1.15 or ratio > 2.2:
                continue
            named = bool(sur) and sur in re.sub(r'[^a-z ]', ' ', t)
            if not named:
                continue
            cands.append((-ii.get('width', 0) // 400, hash((pid, u)) % 1000, u))
        cands.sort()
        url = cands[0][2] if cands else None
        if not url:
            url = (s.get('originalimage') or {}).get('source') or main
        if not url:
            open(nf, 'w').write('x')
            return None
        b = _get(url, binary=True, timeout=25)
        open(fp, 'wb').write(b)
        return b
    except Exception:
        return None


_KP = ('pattern_la', 'pattern_b', 'pattern_ra', 'pattern_sh', 'pattern_so', 'leftarm', 'body', 'rightarm', 'shorts', 'socks')


def parse_kits(wt):
    """Boje dresova iz infoboxa kluba: [{name, la, b, ra, sh, so (hex), pb (naziv uzorka)}] za home/away/third."""
    out = []
    for n, label in ((1, 'Home'), (2, 'Away'), (3, 'Third')):
        v = {}
        for k in _KP:
            m = re.search(r'^\s*\|\s*%s%d\s*=\s*([^\n|]*)' % (k, n), wt, flags=re.M)
            if m:
                v[k] = _clean(m.group(1)).strip()
        if not v.get('body') and not v.get('shorts'):
            continue
        hexc = lambda x: ('#' + x.lstrip('#')) if re.fullmatch(r'#?[0-9A-Fa-f]{6}|#?[0-9A-Fa-f]{3}', x or '') else ''
        out.append(dict(name=label, la=hexc(v.get('leftarm')), b=hexc(v.get('body')), ra=hexc(v.get('rightarm')),
                        sh=hexc(v.get('shorts')), so=hexc(v.get('socks')), pb=(v.get('pattern_b') or '').lower()))
    return out


def _kit_old(old, fp):
    """pc216: osvjezavanje (godina osnutka) nije uspjelo: vrati stari zapis i ne pokusavaj ponovno tjedan dana."""
    if not old:
        return None
    old['ftry'] = int(time.time())
    try:
        jsafe.jdump(old, fp, ensure_ascii=False)
    except Exception:
        pass
    return old


def fetch_kit(name, folder):
    """Dresovi kluba (home/away/third) iz infoboxa clanka. Sprema data/crests/<md5>.kit.json."""
    fp = os.path.join(folder, '%s.kit.json' % _slug(name))
    try:
        c = json.load(open(fp, encoding='utf-8'))
        age = time.time() - c.get('t', 0)
        if 'ground' in c and (c.get('kits') or age < 7 * 86400) and ('founded' in c or time.time() - c.get('ftry', 0) < 7 * 86400):
            return c
        if 'ground' in c:
            old = c          # pc216: stari zapis bez godine osnutka; osvjezi, a ako nema mreze vrati stari
    except Exception:
        pass
    res = dict(t=int(time.time()), kits=[])
    try:
        cj = fetch_club(name, folder)
        title = cj.get('title') if cj else None
        if not title:
            return _kit_old(locals().get('old'), fp) or dict(kits=[], error='no article')
        res['kits'], res['ground'], res['cap'], res['founded'] = _kits(title)
    except Exception as e:
        return _kit_old(locals().get('old'), fp) or dict(kits=[], error=str(e)[:120])
    jsafe.jdump(res, fp, ensure_ascii=False)
    return res


def _kits(title):
    q = urllib.parse.quote(title.replace(' ', '_'), safe='')
    w = _get('%s/w/api.php?action=parse&page=%s&prop=wikitext&section=0&format=json&redirects=1' % (API, q))
    wt = w['parse']['wikitext']['*']
    gm = re.search(r'^\s*\|\s*ground\s*=\s*([^\n]*)', wt, flags=re.M)
    cm = re.search(r'^\s*\|\s*capacity\s*=\s*([^\n]*)', wt, flags=re.M)
    ground = _clean(gm.group(1)).split(',')[0].strip() if gm else ''
    cap = (re.search(r'\d{1,3}(?:,\d{3})+|\d+', _clean(cm.group(1))) or [''])[0] if cm else ''
    fm = re.search(r'^\s*\|\s*(?:founded|formed|established)\s*=\s*([^\n]*)', wt, flags=re.M | re.I)
    fy = re.search(r'1[789]\d\d|20[0-2]\d', fm.group(1)) if fm else None
    return parse_kits(wt), ground, cap, (fy.group(0) if fy else '')


# ---- stadioni (graficki dio kluba): slika stadiona s Wikipedije, sprema se u data/stadiums ----
STADIUMS = {
 'manchester united fc': 'Old_Trafford', 'arsenal fc': 'Emirates_Stadium', 'chelsea fc': 'Stamford_Bridge_(stadium)',
 'liverpool fc': 'Anfield', 'leeds united fc': 'Elland_Road', 'everton fc': 'Hill_Dickinson_Stadium', 'fulham fc': 'Craven_Cottage',
 'manchester city fc': 'City_of_Manchester_Stadium', 'newcastle united fc': "St_James'_Park", 'tottenham hotspur fc': 'Tottenham_Hotspur_Stadium',
 'west ham united fc': 'London_Stadium', 'aston villa fc': 'Villa_Park', 'afc bournemouth': 'Dean_Court', 'brighton & hove albion fc': 'Falmer_Stadium',
 'burnley fc': 'Turf_Moor', 'sunderland afc': 'Stadium_of_Light', 'wolverhampton wanderers fc': 'Molineux_Stadium', 'crystal palace fc': 'Selhurst_Park',
 'brentford fc': 'Gtech_Community_Stadium', 'nottingham forest fc': 'City_Ground', 'leicester city fc': 'King_Power_Stadium', 'southampton fc': "St_Mary's_Stadium",
 'real madrid cf': 'Santiago_Bernab%C3%A9u_Stadium', 'fc barcelona': 'Camp_Nou', 'fc bayern munchen': 'Allianz_Arena', 'juventus fc': 'Allianz_Stadium_(Turin)',
 'ac milan': 'San_Siro', 'fc internazionale milano': 'San_Siro', 'paris saint-germain fc': 'Parc_des_Princes', 'borussia dortmund': 'Signal_Iduna_Park',
 'atletico de madrid': 'Metropolitano_Stadium', 'ssc napoli': 'Stadio_Diego_Armando_Maradona', 'as roma': 'Stadio_Olimpico',
}


def stadium_path(base, name):
    import hashlib
    return os.path.join(base, hashlib.md5((name or '').lower().encode('utf-8')).hexdigest()[:16] + '.jpg')


def fetch_stadium(base, name):
    """Vraca putanju do slike stadiona (dohvaca ako treba) ili None."""
    p = stadium_path(base, name)
    if os.path.exists(p):
        return p
    key = re.sub(r'\s+', ' ', (name or '').lower().strip())
    if key == '__generic':
        for t in GENERIC_TITLES:
            r = _stadium_dl(p, base, t)
            if r:
                return r
        return None
    t = STADIUMS.get(key)
    if not t:
        return None
    return _stadium_dl(p, base, t)


GENERIC_TITLES = ['Emirates_Stadium', 'Allianz_Arena', 'Wembley_Stadium', 'Old_Trafford', 'Anfield']


def _stadium_dl(p, base, t):
    os.makedirs(base, exist_ok=True)
    try:
        j = _get(API + '/w/api.php?action=query&format=json&prop=pageimages&piprop=thumbnail&pithumbsize=1400&redirects=1&titles=' + t)
        for pg in (j.get('query', {}).get('pages', {}) or {}).values():
            u = (pg.get('thumbnail') or {}).get('source')
            if u:
                b = _get(u, timeout=25, binary=True)
                if b and len(b) > 5000:
                    open(p, 'wb').write(b)
                    return p
    except Exception:
        return None
    return None
