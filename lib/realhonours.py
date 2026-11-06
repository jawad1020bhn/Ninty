"""pc358: stvarni trofeji klubova prije pocetka savea (Wikipedia, skupljeno jednom i spremljeno u lib/honours_real.json).

Vitrina tada ne krece od nule: Arsenal ima svojih 13 naslova, a tvoji se trofeji iz karijere zbrajaju na to.
Sezona = pocetna godina (2024-25 = 2024). Broje se samo pobjede PRIJE pocetka svijeta igre (cutoff), jer od tada
naslove osvajaju klubovi u tvojoj karijeri."""
import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'honours_real.json')

STOP = {'fc', 'cf', 'afc', 'sc', 'ac', 'as', 'ssc', 'club', 'de', 'the', 'cd', 'ud', 'sd', 'rc', 'rcd', 'ca', 'sv', 'vfl', 'vfb',
        'tsg', 'fk', 'sk', 'if', 'bk', 'calcio', 'football', 'futbol', 'futebol', 'clube', 'and', 'of', 'e', 'y', 'del', 'da', 'do',
        'balompie', 'bc', 'nk', 'hnk', 'gnk', 'kv', 'rsc', 'osc', 'ogc', 'sl', 'ss', 'us', 'acf', 'bv', 'hsv', 'pfc', 'sco'}
# ime iz igre -> ime kakvo pise u Wikipedia tablicama (normalizirano)
ALIAS = {
    'internazionale milano': 'inter milan', 'internazionale': 'inter milan', 'inter': 'inter milan',
    'bayern munchen': 'bayern munich', 'bayern': 'bayern munich',
    'athletic': 'athletic bilbao',
    'atletico madrid': 'atletico madrid',
    'sporting portugal': 'sporting cp', 'sporting lisbon': 'sporting cp', 'sporting cp': 'sporting cp',
    'benfica': 'benfica', 'lisboa benfica': 'benfica', 'sport lisboa benfica': 'benfica',
    'porto': 'porto',
    'paris saint germain': 'paris saint germain', 'psg': 'paris saint germain',
    'olympique marseille': 'marseille', 'olympique lyonnais': 'lyon', 'lyonnais': 'lyon',
    'nice cote azur': 'nice', 'lille': 'lille',
    'feyenoord rotterdam': 'feyenoord', 'psv eindhoven': 'psv eindhoven', 'psv': 'psv eindhoven', 'ajax': 'ajax',
    'borussia monchengladbach': 'borussia monchengladbach', 'gladbach': 'borussia monchengladbach',
    'werder bremen': 'werder bremen', 'hamburger': 'hamburger sv', 'az alkmaar': 'az', 'inker zapresic': 'inter zapresic', 'croatia zagreb': 'dinamo zagreb', 'strasbourg alsace': 'strasbourg',
    'real sociedad futbol': 'real sociedad', 'real betis': 'real betis', 'betis': 'real betis',
    'brighton hove albion': 'brighton hove albion', 'tottenham hotspur': 'tottenham hotspur', 'spurs': 'tottenham hotspur',
    'wolverhampton wanderers': 'wolverhampton wanderers', 'wolves': 'wolverhampton wanderers',
    'nottingham forest': 'nottingham forest', 'west ham united': 'west ham united',
    'heart midlothian': 'heart of midlothian', 'hearts': 'heart of midlothian',
    'juventus': 'juventus', 'napoli': 'napoli', 'roma': 'roma', 'lazio': 'lazio', 'milan': 'milan',
}
COUNTRY = (('eng', r'premier league|england|english|championship|efl'), ('esp', r'la ?liga|spain|spanish|espa'),
           ('ita', r'serie a|serie b|italy|italian|italia'), ('ger', r'bundesliga|germany|german'),
           ('fra', r'ligue 1|ligue 2|france|french'), ('ned', r'eredivisie|netherlands|dutch'),
           ('por', r'liga portugal|primeira|portugal|portuguese'), ('sco', r'scotland|scottish|scottish premiership'), ('hrv', r'hnl|croatia|hrvat'))

_D = None


def norm(s):
    s = unicodedata.normalize('NFKD', str(s or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace('ø', 'o').replace('ı', 'i').replace('ß', 'ss').replace('ł', 'l').replace('æ', 'ae').replace('&', ' ')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', s).split())


def key_of(name):
    t = [w for w in norm(name).split() if w not in STOP and not w.isdigit()]
    k = ' '.join(t)
    return ALIAS.get(k, k)


def load():
    global _D
    if _D is None:
        try:
            _D = json.load(open(DATA, encoding='utf-8'))
        except Exception:
            _D = {}
    return _D


def _find(clubs, name):
    """Klub iz tablice: prvo isto ime (nakon normalizacije i aliasa), onda jedini klub ciji su svi tokeni u imenu (ili obrnuto)."""
    k = key_of(name)
    if not k:
        return None
    idx = {}
    for cn in clubs:
        idx.setdefault(key_of(cn), cn)
    if k in idx:
        return idx[k]
    tk = set(k.split())
    # samo za imena od 2+ rijeci: 'Milan' ne smije pasti na 'Inter Milan'
    cand = [cn for ck, cn in idx.items() if ck and min(len(tk), len(ck.split())) >= 2 and (set(ck.split()) <= tk or tk <= set(ck.split()))]
    return cand[0] if len(cand) == 1 else None


def country_of(league):
    for c, rx in COUNTRY:
        if re.search(rx, league or '', re.I):
            return c
    return None


def for_club(name, cutoff):
    """{kljuc natjecanja: {n, last, first, wiki}} za klub, samo pobjede u sezonama < cutoff."""
    out = {}
    for comp, v in load().items():
        if comp.startswith('_') or not isinstance(v, dict):
            continue
        clubs = v.get('clubs') or {}
        cn = _find(clubs, name)
        if not cn:
            continue
        r = clubs[cn]
        ss = sorted(int(x) for x in (r.get('seasons') or []))
        n = int(r.get('n') or len(ss)) - sum(1 for x in ss if x >= cutoff)
        if n <= 0:
            continue
        before = [x for x in ss if x < cutoff]
        out[comp] = dict(n=n, last=before[-1] if before else None, first=before[0] if before and len(ss) >= int(r.get('n') or 0) else None, wiki=cn)
    return out


def home_country(real):
    """Zemlja kluba po tome gdje ima domace trofeje (za klub u ligi koju app ne prepoznaje, npr. Championship)."""
    cnt = {}
    for k, v in real.items():
        c = k.split('_')[0]
        if c not in ('ucl', 'uel', 'uecl'):
            cnt[c] = cnt.get(c, 0) + v['n']
    return max(cnt, key=cnt.get) if cnt else None
