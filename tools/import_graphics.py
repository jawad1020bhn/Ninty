#!/usr/bin/env python3
"""Build-time importer for club / league / national-team crests.

FC 27's database carries NO artwork. The eafc-db-kit README is explicit that
"external crests/textures ... require the game's own tooling", so crests have to
come from somewhere else. This imports them from a pinned snapshot of a public
logo collection and writes a manifest the runtime can resolve without ever
touching the network.

    python3 tools/import_graphics.py                 # download + import
    python3 tools/import_graphics.py --tarball F     # reuse a local download
    python3 tools/import_graphics.py --dry-run       # report coverage only

RUNTIME NEEDS NONE OF THIS. lib/graphics.py reads the manifest and falls back to
a generated shield when a crest is absent, so the game works before you run it.

LICENSING - READ THIS. The upstream repository is MIT, but that licence covers
its *code and curation*, not the artwork. Club, league and federation marks are
the trademarks of their respective owners and no open-source licence grants you
rights to them. The extracted crests are therefore written to a GIT-IGNORED
directory (matching the existing data/crests/ convention) and are meant for a
private, personal install. Do not commit or publish them.
"""
import argparse
import collections
import json
import os
import re
import sys
import tarfile
import time
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REPO = 'JoseArroyave/football-logos'
# Pinned so a re-import reproduces byte-identical artwork. Bump deliberately.
SHA = '5ab11fed47427b3003f4b276554491fe683387b1'
TARBALL_URL = 'https://codeload.github.com/%s/tar.gz/%s' % (REPO, SHA)
UA = 'TheGaffer-graphics-import/1.0 (personal, local build-time tool)'

OUT_DIR = os.path.join(ROOT, 'data', 'graphics')
CREST_DIR = os.path.join(OUT_DIR, 'crests')

# Characters NFKD does not decompose. Without these, "Widzew Lodz" never matches
# "Widzew Łódź" and "Bodo/Glimt" never matches "BodøGlimt".
_FOLD = str.maketrans({
    'ł': 'l', 'Ł': 'L', 'ø': 'o', 'Ø': 'O', 'đ': 'd', 'Đ': 'D',
    'ð': 'd', 'Ð': 'D', 'þ': 'th', 'Þ': 'th', 'ı': 'i', 'İ': 'I',
    'æ': 'ae', 'Æ': 'ae', 'œ': 'oe', 'Œ': 'oe', 'ß': 'ss', 'ẞ': 'ss',
})

# Dropped when comparing club names. Kept deliberately small: over-stripping
# invents collisions ("Inter" vs "Inter Escaldes") that the country guard then
# has to catch.
_STOP = {
    'fc', 'cf', 'ac', 'as', 'ssc', 'afc', 'sc', 'cd', 'ud', 'rc', 'rcd', 'ca',
    'ec', 'cr', 'se', 'sk', 'fk', 'bk', 'if', 'aif', 'kv', 'kvc', 'bsc', 'gnk',
    'calcio', 'club', 'de', 'del', 'la', 'el', 'the', 'football', 'futbol',
    'futebol', 'soccer', 'team', 'balompie', 'hotspur', 'wanderers', 'rovers',
    ' united', '04', '1899', '1900', '1', 'vfl', 'vfb', 'tsg', 'fsv', 'sv', 'rb',
}
_STOP.discard(' united')

# Hand-reviewed. Fuzzy matching proposed several WRONG answers that would have
# shipped a rival's crest, so every entry here was checked by eye:
#   Stade Rennais    -> "Stade de Reims"        REJECTED (different club)
#   Heart of Midlothian -> "Heart of Lions"     REJECTED (Ghanaian club)
#   Austria Lustenau -> "Austria Wien"          REJECTED (different club)
#   Rot-Weiss Essen  -> "Rot-Weiss Oberhausen"  REJECTED (different club)
#   Real Sociedad B  -> "Real Sociedad"         REJECTED (reserve team)
#   Al Diriyah       -> "Al Riyadh"             REJECTED (different club)
# EA ships unlicensed clubs under invented names; those can never be matched by
# similarity and must be mapped explicitly.
ALIAS = {
    'bergamo calcio': 'Atalanta',              # EA placeholder for Atalanta
    'gotham fc': 'NJNY Gotham FC',
    'losc lille': 'Lille',
    'ogc nice': 'Nice',
    'aj auxerre': 'Auxerre',
    'stade brestois 29': 'Brest',
    'estac troyes': 'Troyes',
    'en avant guingamp': 'EA Guingamp',
    'usl dunkerque': 'Dunkerque',
    'us boulogne': 'Boulogne',
    'olympique de marseille': 'Marseille',
    'stade rennais': 'Rennes',
    'borussia m\'gladbach': "Borussia Mönchengladbach",
    'anderlecht': 'RSC Anderlecht',
    'dinamo zagreb': 'GNK Dinamo Zagreb',
    'bsc young boys': 'Young Boys',
    'fk bodo/glimt': 'BodøGlimt',
    'argentinos juniors': 'Argeninos Juniors',   # upstream typo
    'ferencvarosi tc': 'Ferencváros',
    'sd eibar': 'Eibar',
    'ce sabadell': 'Sabadell',
    'ad ceuta': 'Ceuta',
    'omonia nicosia fc': 'Omonoia Nicosia',
    'tigres u.a.n.l.': 'Tigres UANL',
    'gallos blancos de queretaro': 'Queretaro',
    'd.c. united': 'DC United',
    'sint-truiden': 'Sint-Truidense VV',
    'sk beveren': 'S.K. Beveren',
    'kortrijk': 'KV Kortrijk',
    'westerlo': 'KVC Westerlo',
    'djurgardens if': 'Djurgården',
    'halmstads bk': 'Halmstad',
    'ik sirius': 'Sirius',
    'aalesunds fk': 'Aalesund',
    'wsg tirol': 'Tirol',
    'hamkam fotball': 'HamKam',
    'odense boldklub': 'OB',
    'sonderjyske fodbold': 'SonderjyskE',
    'widzew lodz': 'Widzew Lodz',
    'sudtirol': 'Suditrol',                     # upstream typo
    'liaoning tieren': 'Liaoning Tiening',       # upstream typo
    'grasshopper club zurich': 'Grasshoppers',
    'heart of midlothian': 'Hearts',
    'corendon alanyaspor': 'Alanyaspor',
    'istanbul basaksehir fk': 'Basaksehir',
    'rc deportivo': 'Deportivo La Coruna',
    'real betis balompie': 'Real Betis',
    # Verified against the upstream file list, not guessed from similarity.
    'lombardia fc': 'Inter',                   # upstream calls Inter just "Inter"
    'ol lyonnes': 'Olympique Lyonnais',        # Lyon women, rebranded 2025
    'ol lyonnais': 'Olympique Lyonnais',
    'antwerp': 'Royal Antwerp',
    'charleroi': 'Royal Charleroi S C',         # NOT "Olympic Charleroi"
    'bohemians': 'Bohemian',                   # upstream singular
    'real sporting de gijon': 'Sporting Gijon',
    'genk': 'KRC Genk',
    'gent': 'KAA Gent',
    'sporting kc': 'Sporting Kansas City',
    'fc kobenhavn': 'F C Copenhagen',
    'excelsior': 'Excelsior Rotterdam',        # NOT "Excelsior Maassluis"
    'avellino': 'US Avellino 1912',
    'oh leuven': 'Oud Heverlee Leuven',
    'real oviedo': 'Oviedo',
    'wolfsberger ac': 'Wolfsberg',
    'entella': 'Virtus Entella',
    'al diriyah': 'Diriyah',                   # NOT "Al Riyadh"
    'shenzhen peng city': 'Shenzhen Xinpengcheng',
    'pumas u.n.a.m.': 'UNAM Pumas',
    'rodez aveyron football': 'Rodez AF',
    'red bull new york': 'New York Red Bulls',
    'sporting de braga': 'SC Braga',
    'austria lustenau': 'Lustenau',            # NOT "Austria Wien"
    'aek': 'AEK Athens',
    'apoel nicosia fc': 'APOEL',
    'shakhtar donetsk': 'Shakhtar',
    'ludogorets razgrad': 'Ludogorets',
    'roma': 'AS Roma',
    'wellington phoenix': 'Wellington Phoenix FC',
    'auckland fc': 'Auckland FC',
    # Found by auditing every non-exact match, not by similarity.
    'milano fc': 'Milan',                      # EA placeholder for AC Milan.
    #   Stripping stopwords collapses "Milano FC" and "Club Milano" to the same
    #   key, and Club Milano is a small Serie D side, not AC Milan.
    'gimnasia y esgrima la plata': 'Gimnasia LP',
    'racing club de avellaneda': 'Racing Club',
    'montpellier hsc': 'Montpellier',
    'rc celta de vigo': 'Celta',
}

# Clubs that must NOT be matched at all. Each was proposed by the token/global
# matcher and checked upstream: the candidate is a DIFFERENT club, or the real
# club has no file. A wrong crest is worse than a generated shield.
BLOCK = {
    '1. fc koln',            # only Koln files are Viktoria/Fortuna/Bruu... none is 1. FC Koln
    'united tigers sc',      # proposed india/United_SC.svg, a different club
    'gimnasia y esgrima de mendoza',   # plain "Gimnasia y Esgrima" is ambiguous
    'costa adeje tenerife',  # independent women's club, NOT CD Tenerife's side
    'real sociedad b', 'tsg 1899 hoffenheim ii', 'vfb stuttgart ii',
    'rc celta fortuna',      # reserve sides must not inherit the parent crest
}

# A reserve/second team. If the FC 27 name carries one of these and the upstream
# file does not, the match is refused: it is the parent's crest, not theirs.
RESERVE_RE = re.compile(
    r'(?:\s(?:B|II|III|IV|U-?\d\d|Reserves?|Youth|Juniors?|Castilla|Fortuna))$', re.I)

# FC 27 files some clubs under "Rest of World", and puts New Zealand clubs in the
# Australian league, so the club's own country field points at the wrong folder
# (or none). These overrides were each confirmed to exist upstream.
COUNTRY_OVERRIDE = {
    'aek': 'greece', 'apoel nicosia fc': 'cyprus', 'shakhtar donetsk': 'ukraine',
    'ludogorets razgrad': 'bulgaria', 'roma': 'italy',
    'wellington phoenix': 'new-zealand', 'auckland fc': 'new-zealand',
}

# League marks, keyed by (upstream folder, FC 27 league name) so a name reused in
# two countries cannot cross over: Austria's "Bundesliga" must never resolve to
# Germany's, and Spain's "Primera Division" is La Liga, NOT "Primera Federacion"
# (which is the third tier).
LEAGUE_ALIAS = {
    ('england', 'championship'): 'EFL Championship',
    ('england', 'league one'): 'EFL League One',
    ('england', 'league two'): 'EFL League Two',
    ('spain', 'primera division'): 'La Liga',
    ('spain', 'segunda division'): 'La Liga 2',
    ('usa', 'major league soccer'): 'MLS - Major League Soccer',
    ('usa', 'nwsl'): "National Women's Soccer League",
    ('scotland', 'premiership'): 'Scottish Premiership',
    ('belgium', 'pro league'): 'Belgian Pro League',
    ('republic-of-ireland', 'premier division'): 'League of Ireland Premier Division',
    ('poland', 'ekstraklasa'): 'PKO BP Ekstraklasa',
    ('austria', 'bundesliga'): 'Austrian Bundesliga',
    ('switzerland', 'super league'): 'Swiss Super League',
    ('saudi-arabia', 'saudi pro league'): 'Saudi Professional League',
    ('china', 'china super league'): 'Chinese Super League',
    ('denmark', 'superliga'): 'Danish Superliga',
}

# FC 27 nation name -> upstream folder, where the slug differs. Every target
# here was checked against the actual folder list: an alias pointing at a
# folder that does not exist silently disables country-scoped matching for
# every club in that nation (that is how Ajax and AZ went missing).
FOLDER_ALIAS = {
    'holland': 'netherlands',                 # FC 27's name for Netherlands
    'united states': 'usa',
    'korea republic': 'south-korea', 'korea dpr': 'north-korea',
    'china pr': 'china', 'chinese taipei': 'taiwan',
    'st. lucia': 'saint-lucia',
    'st. vincent and the grenadines': 'saint-vincent-and-the-grenadines',
    'st. kitts and nevis': 'st-kitts-and-nevis',
    'cape verde islands': 'cabo-verde',
    'sao tome e principe': 'sao-tome-and-principe',
    'brunei darussalam': 'brunei',
    'turkiye': 'turkey', 'czechia': 'czech-republic',
}

# FC 27 buckets these under invented "nations" that are not countries at all.
# They get no national-team crest, and their clubs must match globally.
PSEUDO_NATIONS = {
    'international', 'international women', 'rest of world', 'free agents country',
    'created players country', 'conmebol', 'afc', 'uefa', 'caf', 'concacaf', 'ofc',
}


def fold(s):
    """ASCII-fold, preserving letter identity for characters NFKD leaves alone."""
    s = str(s).translate(_FOLD)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return s.lower()


def slug(s):
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', fold(s))).strip('-')


def key(s, stop=True):
    s = re.sub(r'\(.*?\)', ' ', fold(s)).replace('&', ' and ')
    toks = [t for t in re.sub(r'[^a-z0-9 ]', ' ', s).split()
            if t and (not stop or t not in _STOP)]
    return tuple(toks)


def load_db():
    def rd(n):
        with open(os.path.join(ROOT, 'data', 'fc27', n), encoding='utf-8') as f:
            return json.load(f)
    return rd('clubs.json'), rd('leagues.json'), rd('nations.json')


def download(dest):
    if os.path.exists(dest):
        return dest
    req = urllib.request.Request(TARBALL_URL, headers={'User-Agent': UA})
    tmp = dest + '.part'
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, 'wb') as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    os.replace(tmp, dest)
    return dest


def build_index(tf):
    """folder -> {normalized name: member}, plus a flat name index.

    The stopword-stripped key is LOSSY: "Milano FC" and "Club Milano" both
    collapse to ('milano',). Registering whichever came first in the tarball
    silently handed AC Milan's placeholder a Serie D club's crest. A stripped
    key is therefore only registered when exactly one file produces it; the
    precise (unstripped) key is always registered.
    """
    per = collections.defaultdict(dict)
    flat = collections.defaultdict(list)
    stripped = collections.defaultdict(lambda: collections.defaultdict(list))
    root = None
    for m in tf.getmembers():
        if not m.isfile() or not m.name.lower().endswith('.svg'):
            continue
        parts = m.name.split('/')
        if root is None:
            root = parts[0]
        if len(parts) < 4 or parts[1] != 'logos':
            continue
        folder, fname = parts[2], parts[-1]
        nm = fname.rsplit('.', 1)[0].replace('_', ' ')
        per[folder].setdefault(key(nm, stop=False), m)
        stripped[folder][key(nm)].append(m)
        flat[key(nm)].append(m)
    for folder, d in stripped.items():
        for ks, ms in d.items():
            if len({m.name for m in ms}) == 1:
                per[folder].setdefault(ks, ms[0])
    return per, flat, root


def nation_folders(nations, per):
    """Map FC 27 nation id -> upstream country folder."""
    out = {}
    have = set(per)
    for nid, row in nations.items():
        nm = row.get('name', '')
        if fold(nm) in PSEUDO_NATIONS:
            continue
        cand = FOLDER_ALIAS.get(fold(nm)) or slug(nm)
        if cand in have:
            out[str(nid)] = cand
            continue
        iso = slug(row.get('iso', ''))
        if iso in have:
            out[str(nid)] = iso
    return out


def match_club(row, folder, per, flat):
    """Resolve one club. Returns (member, how) or (None, reason).

    Matching is confined to the club's own country folder whenever that folder
    is known: a token-subset match is otherwise happy to pair Leverkusen with
    "Leverstock Green" or Wolfsberger with Austria's "Wolfsberg".

    Clubs FC 27 files under "Rest of World" have no real country, so they fall
    back to the global index and are only accepted when the name is unique
    across all 229 folders.
    """
    name = row.get('name', '')
    if fold(name) in BLOCK:
        return None, 'blocked'
    scope = per.get(folder) if folder else None
    k, kfull = key(name), key(name, stop=False)

    def acceptable(m, how):
        """A reserve side must not inherit its parent's crest."""
        if RESERVE_RE.search(name):
            upstream = m.name.split('/')[-1].rsplit('.', 1)[0].replace('_', ' ')
            if not RESERVE_RE.search(upstream):
                return None, 'reserve'
        return m, how

    # An explicit, hand-checked alias outranks EVERY automatic match. "Milano
    # FC" is EA's placeholder for AC Milan, but it also strips to the same key
    # as "Club Milano", a real Serie D side; consulting the exact key first
    # handed it the wrong crest even with the alias present.
    al = ALIAS.get(fold(name))
    if al:
        for kk in (key(al, stop=False), key(al)):
            if scope and kk in scope:
                return acceptable(scope[kk], 'alias')
            if kk in flat and len({m.name for m in flat[kk]}) == 1:
                return acceptable(flat[kk][0], 'alias')
    # Precise key before the lossy stripped key.
    if scope:
        for kk in (kfull, k):
            if kk in scope:
                return acceptable(scope[kk], 'exact')
    else:
        for kk in (kfull, k):
            if kk in flat and len({m.name for m in flat[kk]}) == 1:
                return acceptable(flat[kk][0], 'global')
    if scope and k:
        cand = {m.name: m for kk, m in scope.items()
                if kk and kk[0] == k[0] and (set(kk) <= set(k) or set(k) <= set(kk))}
        if len(cand) == 1:
            return acceptable(next(iter(cand.values())), 'token')
        if len(cand) > 1:
            return None, 'ambiguous'
    return None, 'miss'


def run(tarball, dry):
    clubs, leagues, nations = load_db()
    path = download(tarball)
    tf = tarfile.open(path)
    per, flat, root = build_index(tf)
    nfolder = nation_folders(nations, per)
    print('upstream folders: %d   FC27 nations mapped to a folder: %d/%d'
          % (len(per), len(nfolder), len(nations)))

    # `members` deduplicates the files we extract; `entries` keeps EVERY resolved
    # entity. They must be separate: several FC 27 clubs legitimately share one
    # crest (a women's side and its parent, or the same club listed under both a
    # real league and "Rest of World"), and keying the manifest by filename
    # silently dropped 64 of them.
    members = {}
    member_by_name = {}
    entries = []
    how_c = collections.Counter()
    unresolved = []
    for tid, row in clubs.items():
        folder = (COUNTRY_OVERRIDE.get(fold(row.get('name', '')))
                  or nfolder.get(str(row.get('country'))))
        m, how = match_club(row, folder, per, flat)
        if m is None and row.get('women'):
            base = re.sub(r'\s+(women|femeni|femenino)$', '', row['name'], flags=re.I).strip()
            if base != row['name']:
                m, how = match_club(dict(row, name=base), folder, per, flat)
                if m is not None:
                    how = 'parent'
        how_c[how] += 1
        if m is not None:
            member_by_name[m.name] = m
            entries.append(('clubs', str(tid), row['name'], how, m.name))
        else:
            unresolved.append((row['name'], how))

    # Defence in depth. Several FC 27 ids legitimately share one crest (a
    # women's side and its parent, or the same club listed twice), but two
    # DIFFERENT club names on one file means at most one can be right. Drop the
    # fuzzy claim and keep the exact/aliased one; if both are fuzzy, drop both.
    # This is what caught Gimnasia La Plata and Gimnasia de Mendoza silently
    # sharing a single crest.
    names_by_member = collections.defaultdict(set)
    for _kind, _id, _nm, _how, _mem in entries:
        names_by_member[_mem].add(_nm)
    kept = []
    for kind, ident, nm, how, mem in entries:
        if len(names_by_member[mem]) > 1 and how in ('token', 'global'):
            how_c[how] -= 1
            how_c['shared-conflict'] += 1
            unresolved.append((nm, 'shared-conflict'))
            continue
        kept.append((kind, ident, nm, how, mem))
    entries = kept
    for _kind, _ident, _nm, _how, mem in entries:
        members[mem] = member_by_name[mem]

    # National team marks are "<Country> National Team" in the country folder.
    nat_picks = {}
    for nid, row in nations.items():
        folder = nfolder.get(str(nid))
        if not folder:
            continue
        scope = per.get(folder, {})
        for kk in (key(row['name'] + ' National Team', stop=False),
                   key(row['name'] + ' National Team')):
            if kk in scope:
                m = scope[kk]
                nat_picks[str(nid)] = m.name
                members[m.name] = m
                entries.append(('nations', str(nid), row['name'], 'exact', m.name))
                break

    lg_picks = {}
    for lid, row in leagues.items():
        folder = nfolder.get(str(row.get('country')))
        scope = per.get(folder) if folder else None
        nm = row.get('name', '')
        m, how = None, 'miss'
        if scope:
            for kk in (key(nm, stop=False), key(nm)):
                if kk in scope:
                    m, how = scope[kk], 'exact'
                    break
            if m is None:
                al = LEAGUE_ALIAS.get((folder, fold(nm)))
                if al:
                    for kk in (key(al, stop=False), key(al)):
                        if kk in scope:
                            m, how = scope[kk], 'alias'
                            break
        if m is not None:
            lg_picks[str(lid)] = m.name
            members[m.name] = m
            entries.append(('leagues', str(lid), nm, how, m.name))

    print('clubs   : %s' % dict(how_c))
    print('nations : %d/%d' % (len(nat_picks), len(nations)))
    print('leagues : %d/%d' % (len(lg_picks), len(leagues)))
    total = sum(m.size for m in members.values())
    print('files   : %d   %.1f MB' % (len(members), total / 1e6))
    if dry:
        print('\n--dry-run: nothing written. Unresolved clubs:')
        for n, h in sorted(unresolved)[:40]:
            print('   %-32s %s' % (n, h))
        return 0

    os.makedirs(CREST_DIR, exist_ok=True)
    manifest = {
        'source': {
            'repo': REPO, 'sha': SHA, 'url': 'https://github.com/' + REPO,
            'imported': time.strftime('%Y-%m-%d'),
            'licence': ('Upstream repo is MIT for its code/curcation only. The '
                        'artwork is the trademark and copyright of the respective '
                        'clubs, leagues and federations. Personal use only.'),
        },
        'clubs': {}, 'leagues': {}, 'nations': {},
    }
    rels = {}
    for member, m in sorted(members.items()):
        parts = member.split('/')
        rel = os.path.join('crests', parts[2], parts[-1]).replace(os.sep, '/')
        dest = os.path.join(OUT_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with tf.extractfile(m) as src, open(dest, 'wb') as out:
            out.write(src.read())
        rels[member] = rel
    for kind, ident, name, how, member in entries:
        manifest[kind][ident] = {'file': rels[member], 'name': name, 'match': how}

    manifest['coverage'] = {
        'clubs': len(manifest['clubs']), 'clubs_total': len(clubs),
        'leagues': len(manifest['leagues']), 'leagues_total': len(leagues),
        'nations': len(manifest['nations']), 'nations_total': len(nations),
        'files': len(members), 'entities': len(entries), 'bytes': total,
    }
    with open(os.path.join(OUT_DIR, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

    lines = [
        'CREST ATTRIBUTION', '=' * 60, '',
        'Source: https://github.com/%s' % REPO, 'Commit: %s' % SHA, '',
        manifest['source']['licence'], '',
        'These files are NOT covered by this project\'s licence and are NOT',
        'committed to the repository. They are a local, personal-install cache.', '',
        '%d files, %d mapped ids. Mapping (id -> upstream file):' % (len(members), len(entries)), '',
    ]
    for kind in ('clubs', 'leagues', 'nations'):
        for ident, e in sorted(manifest[kind].items(), key=lambda x: int(x[0])):
            lines.append('  %-8s %-34s %s' % (kind[:3] + ' ' + ident, e['name'], e['file']))
    with open(os.path.join(OUT_DIR, 'ATTRIBUTION.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\nwrote %s' % os.path.relpath(OUT_DIR, ROOT))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tarball', default=os.path.join(ROOT, '.cache', 'football-logos.tar.gz'))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.tarball), exist_ok=True)
    return run(a.tarball, a.dry_run)


if __name__ == '__main__':
    sys.exit(main())
