"""Razumijevanje slobodnog teksta (offline, HR + EN) za konferencije i razgovore s igracima.

Tekst -> znacajke namjere (pohvala, kritika, obecanje pobjede, "nije na prodaju", isprika...), uz negaciju
("nije los" = blaga pohvala, "necemo ga prodati" = nije na prodaju). Znacajke se usporede s namjerom svake
ponudene opcije; najbolja opcija je ono sto je menadzer "rekao". Ucinke i dalje racunaju postojeca pravila,
tekst samo bira opciju (i malo mijenja ton u razgovoru: uvrede ljute igraca, toplina malo pomaze).
"""
import re
import unicodedata

# ---------------------------------------------------------------- normalizacija
_TR = str.maketrans({'đ': 'dj', 'Đ': 'dj', 'ß': 'ss'})


def norm(t):
    t = (t or '').translate(_TR).lower()
    t = unicodedata.normalize('NFKD', t)
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = t.replace("'", '').replace('’', '')
    return [('|' if x in ',.;:!?' or x == '-' else x) for x in re.findall(r'[a-z0-9]+|[,.;:!?]| - ', t)]


NEG = {'ne', 'not', 'no', 'nije', 'nisu', 'nisam', 'nismo', 'niste', 'nisi', 'nemas', 'nemojte', 'nemate', 'nece', 'necu', 'necemo', 'neces', 'necete', 'nikad', 'nikada',
       'never', 'dont', 'doesnt', 'didnt', 'wont', 'cant', 'cannot', 'isnt', 'arent', 'wasnt', 'nemoj', 'nemam', 'nema', 'nemamo',
       'without', 'bez', 'nor', 'neither', 'nobody', 'nitko', 'nista', 'nothing', 'shouldnt', 'wouldnt', 'mustnt'}
INTENS = {'very', 'really', 'so', 'extremely', 'absolutely', 'totally', 'completely', 'jako', 'stvarno', 'vrlo', 'apsolutno', 'potpuno',
          'izuzetno', 'bas', 'uistinu', 'definitivno', 'definitely', 'zaista', 'skroz', 'super'}

# znacajka -> uzorci. Uzorak = rijeci odvojene razmakom; rijec s '=' na pocetku mora biti tocna, inace je prefiks (korijen).
LEX = {
    'praise': ['proud', 'great', 'excellent', 'brilliant', 'fantastic', 'outstanding', 'superb', 'amazing', 'top class', 'world class',
               'happy with', '=happy', 'pleased', 'delighted', 'impress', 'quality', 'talent', 'important', 'valuable', 'magnificent', 'phenomenal',
               '=good', 'well done', 'played well', 'love', '=best', 'star', 'leader', 'hero', 'deserv',
               'ponos', 'sjajn', 'odlic', 'fantasti', 'izvanred', 'vrhunsk', 'zadovolj', 'sretan', 'sretni', 'talentir', 'talent',
               'vazan', 'vazn', 'dragocj', 'kvalitet', 'impresiv', 'oduse', '=dobar', '=dobro', '=dobri', 'bravo', 'najbolj', 'genij',
               'dali su sve', 'dao je sve', 'dali sve', 'gave everything', 'gave it all', 'fenomen', 'carob', 'mocan', 'svaka cast', 'majstor', 'vodja', 'lider', 'heroj', '=top', 'volim'],
    'criticism': ['bad', 'badly', 'unhappy', 'poor', 'disappoint', 'unacceptable', 'terrible', 'awful', 'embarrass', 'lazy', 'useless', 'shameful', 'shame',
                  'not good enough', 'not acceptable', 'not at his level', 'not at the level', 'below par', 'below standard', 'mistake',
                  'error', 'careless', 'sloppy', 'weak', 'worst', 'rubbish', 'disgrace', 'pathetic', 'horrible',
                  '=los', '=losa', '=lose', '=lose', 'losi', 'losu', 'razocar', 'neprihvatljiv', 'sramot', 'katastrof', 'uzas', 'ocaj', 'lijen',
                  'slab', 'najgor', 'greska', 'greske', 'pogresk', 'bezveze', 'jadn', 'nije dovoljno dobr', 'ispod razine', 'ispod nivoa',
                  'bijed', 'nemaran'],
    'win': ['we will win', 'well win', 'we win', 'beat them', 'we will beat', 'well beat', 'three points', '3 points', 'victory',
            'take the points', 'win this', 'win the game', 'win the match', 'go for the win', 'going to win', 'gonna win', 'smash',
            'pobijed', 'pobjed', 'dobit cemo', 'dobiti cemo', 'dobicemo', 'tri boda', '3 boda', 'srusit', 'srusi', 'pomest', 'slavit cemo',
            'uzet cemo bodove', 'uzeti bodove', 'idemo po bodove', 'pregazit', 'nadigrat'],
    'respect': ['respect', 'difficult', 'tough game', 'hard game', 'tough opponent', 'strong team', 'good team', 'dangerous', 'prepare',
                'give our best', 'one game at a time', 'one match at a time', 'humble', 'credit to',
                'postov', 'postuj', 'tesk', 'jaka momcad', 'jak protivnik', 'jaki su', 'dobra momcad', 'opasn', 'pripremi', 'pripremit',
                'utakmicu po utakmicu', 'korak po korak', 'skromn', 'ozbiljn', 'cestit'],
    'hostile': ['dont care what', 'do not care what', 'dont care about them', 'worry about themselves', 'worry about their own',
                'their own problems', 'nonsense', 'talk too much', 'arrogant', 'clown', 'shut up', 'mind their own', 'disrespect', 'rubbish they',
                'empty words', 'big mouth', 'cheap talk', 'whatever they say', 'not fair', 'unfair', 'ridiculous question', 'stupid question',
                'ne zanima me', 'ne zanimaju me', 'boli me', 'briga me', 'nek se brinu', 'neka se brinu', 'neka gledaju sebe', 'nek gledaju sebe',
                'svoje probleme', 'gluposti', 'pricaju puno', 'previse pricaju', 'bahat', 'arogant', 'klaun', 'neka sute', 'nek sute',
                'prazne price', 'prazne rijeci', 'velika usta', 'jeftin', 'nije fer', 'nefer', 'nepravedn', 'glupo pitanje', 'smijesno pitanje'],
    'keep': ['not for sale', 'not leaving', 'going nowhere', 'staying', 'stays', 'he stays', 'he will stay', 'stay here', 'part of our future',
             'part of the future', 'keep him', 'we keep', 'untouchable', 'off the table',
             'nije na prodaju', 'nisu na prodaju', 'ne prodajemo', 'ne ide nikamo', 'ne ide nigdje', 'ostaje', 'ostat ce', 'ostati ce',
             'ostaje kod nas', 'zadrzat', 'zadrzava', 'nedodirljiv', 'dio buducnosti', 'dio nase buducnosti'],
    'sell': ['sell', 'price', 'right offer', 'good offer', 'the offer', 'offers', 'listen', 'money', 'business', 'nobody is bigger',
             'no one is bigger', 'everyone has a price', 'every player has a price', 'for the right',
             'prodat', 'prodaj', 'prodam', 'cijen', 'ponud', 'saslusat', 'slusat', 'novac', 'novce', 'posao', 'biznis',
             'nitko nije veci', 'nitko nije iznad', 'svatko ima cijenu', 'za pravu'],
    'deflect': ['internal', 'private', 'no comment', 'not going to discuss', 'wont discuss', 'not discuss', 'between us', 'behind closed doors',
                'focus on', 'focused on', 'not talk about', 'next question', 'not the time', 'in house',
                'intern', 'nasamo', 'bez komentar', 'necu komentir', 'ne bih komentir', 'ne zelim komentir', 'izmedju nas', 'u svlacionici',
                'fokus', 'koncentr', 'sljedece pitanje', 'nije trenutak', 'necu pricati o tome', 'ne bih o tome'],
    'sorry': ['sorry', 'apolog', 'my fault', 'my responsibility', 'my mistake', 'i was wrong', 'take responsibility', 'blame myself', 'i failed',
              'let you down', 'let him down', 'i messed', 'owe you',
              'oprost', 'isprik', 'ispricav', 'moja greska', 'moja odgovornost', 'moja krivnja', 'kriv sam', 'pogrijesio sam', 'pogrijesila sam',
              'preuzimam odgovornost', 'iznevjerio', 'iznevjerila', 'duguj', 'u pravu si', 'u pravu ste', 'you are right', 'youre right'],
    'realistic': ['realistic', 'realism', 'limits', 'limitations', 'not favourites', 'not favorites', 'underdog', 'small club', 'cant compete',
                  'step by step', 'patience', 'long term', 'rebuild', 'transition', 'expectations too high',
                  'realn', 'ogranicen', 'nismo favorit', 'autsajder', 'mali klub', 'strpljen', 'dugorocn', 'prijelazn', 'obnov',
                  'ocekivanja su previsok', 'previsoka ocekivanja', 'prezahtjevn'],
    'ambition': ['more than that', 'surprise', 'higher', 'europe', 'champions league', 'title', 'trophy', 'trophies', 'top four', 'top 4',
                 'challenge for', 'aim high', 'ambitio', 'exceed', 'better than', 'go further', 'dream', 'win the league',
                 'vise od toga', 'vise nego', 'iznenadit', 'iznenadi', 'visok', 'europ', 'liga prvaka', 'naslov', 'titul', 'trofej', 'pehar',
                 'prvak', 'prvenstv', 'ambici', 'nadmasit', 'bolje od', 'dalje od', 'san nam', 'sanjamo', 'gore na tablici'],
    'support': ['backing', 'support', 'full trust of the board', 'board trusts', 'confidence of the board', 'turn it around', 'turn this around',
                'we will come back', 'bounce back', 'together', 'united', 'calm',
                'podrsk', 'podrzav', 'uprava vjeruje', 'povjerenje uprave', 'preokren', 'okrenut cemo', 'vratit cemo se', 'zajedn', 'ujedinj',
                'mirn', 'smiren'],
    'blame': ['some players', 'certain players', 'players are not', 'not giving me', 'not giving everything', 'not doing their job', 'they let me down',
              'need more from them', 'not committed', 'no desire', 'no attitude',
              'neki igraci', 'pojedini igraci', 'igraci ne daju', 'ne daju sve', 'ne rade svoj posao', 'iznevjerili su', 'nema zelje', 'nema stava',
              'nisu dali', 'ne trude', 'nisu se trudili'],
    'leave': ['leave', 'can go', 'free to go', 'let him go', 'let you go', 'wont stand in', 'not stand in', 'stand in your way', 'stand in his way',
              'move on', 'find a new club', 'wont stop', 'not stop you', 'dont want you', 'door is open', 'next step',
              'otic', 'odlaz', 'mozes ic', 'mozes otic', 'slobodno idi', 'pustit cu', 'pusti', 'necu te zadrzavat', 'necu ga zadrzavat', 'necu stajat na putu',
              'ne stojim na putu', 'necu ti stajat', 'novi klub', 'vrata su otvorena', 'sljedeci korak', 'idi'],
    'hold': ['contract', 'not going anywhere', 'youre staying', 'you are staying', 'you stay', 'you will stay', 'under contract', 'we decide',
             'ugovor', 'ne ides nikamo', 'ne ides nigdje', 'ostajes', 'ostat ces', 'mi odlucujemo', 'pod ugovorom'],
    'minutes': ['more minutes', 'more games', 'more chances', 'you will play', 'youll play', 'you will start', 'youll start', 'play more',
                'start the next', 'start next', 'get your chance', 'your chance will', 'chance soon', 'next game you', 'in the team', 'first team',
                'igrat ces', 'igrati ces', 'igraces', 'vise minuta', 'vise prilika', 'vise utakmica', 'dobit ces priliku', 'dobiti ces priliku',
                'startat ces', 'startati ces', 'pocet ces', 'poceti ces', 'u prvih jedanaest', 'u prvoj postavi', 'u sastavu', 'tvoja prilika',
                'tvoja sansa', 'dobit ces sansu', 'sljedecu utakmicu', 'sljedecu utakmicu igras', 'igras'],
    'promise': ['promise', 'my word', 'guarantee', 'trust me', 'i swear', 'you have my',
                'obecav', 'obecaj', 'obecanj', 'dajem ti rijec', 'imas moju rijec', 'garantir', 'jamcim', 'vjeruj mi', 'kunem'],
    'work': ['work hard', 'keep working', 'train', 'training', 'earn it', 'earn your', 'prove', 'show me', 'merit', 'fight for',
             'radi', 'rad ', 'trenir', 'trening', 'zasluz', 'dokaz', 'pokazi mi', 'pokaz', 'bori se', 'izbori', 'zaradi'],
    'honest': ['honest', 'truth', 'ahead of you', 'better than you', 'others are ahead', 'currently', 'right now others', 'not lie', 'wont lie',
               'iskren', 'istin', 'ispred tebe', 'bolji od tebe', 'bolji su', 'trenutno', 'necu ti lagat', 'necu lagat', 'ne lazem'],
    'rest': ['rest', 'breather', 'break', 'recharge', 'clear your head', 'step back', 'bench for', 'fresh',
             'odmor', 'odmori', 'predah', 'pauz', 'napuni baterije', 'razbistri', 'odmakni', 'svjez'],
    'renew': ['new contract', 'new deal', 'extend', 'extension', 'renew', 'sit down and talk', 'sign again', 'future here', 'want you to stay',
              'novi ugovor', 'produz', 'produlj', 'potpisat ponovno', 'buducnost ovdje', 'zelimo da ostanes', 'zelim da ostanes', 'sjest cemo'],
    'later': ['later', 'end of the season', 'end of season', 'in the summer', 'not now', 'after the season', 'next year', 'we will see', 'wait',
              'kasnije', 'kraj sezone', 'kraju sezone', 'na ljeto', 'ljeti', 'ne sada', 'nakon sezone', 'iduce godine', 'vidjet cemo', 'pricekaj',
              'cekaj', 'strpi'],
    'noext': ['not extend', 'no new contract', 'wont renew', 'not renew', 'not offer you', 'run out', 'free transfer', 'your time here is',
              'ne produz', 'necemo produz', 'nema novog ugovora', 'necemo ti ponudit', 'istece', 'istec', 'slobodan transfer', 'tvoje vrijeme ovdje'],
    'key': ['key player', 'built around', 'build around', 'build the team around', 'heart of', 'most important', 'cornerstone', 'centre of',
            'center of', 'main man', 'leader of',
            'kljucn', 'oko tebe', 'srce momcadi', 'srce ovog', 'najvazniji', 'temelj', 'stup', 'nositelj', 'glavni igrac', 'vodja momcadi'],
    'starter': ['starter', 'regular', 'every game', 'every week', 'every match', 'first eleven', 'starting eleven', 'starting xi', 'first choice',
                'standardn', 'svaku utakmicu', 'svaki tjedan', 'prvih jedanaest', 'prva postava', 'prvi izbor', 'stalno igr', 'redovit'],
    'rotation': ['rotation', 'rotate', 'game by game', 'squad player', 'depends on', 'sometimes', 'some games', 'part to play', 'role to play',
                 'rotacij', 'rotir', 'od utakmice do utakmice', 'ovisno o', 'povremeno', 'ponekad', 'neke utakmice', 'imat ces ulogu', 'imati ces ulogu'],
    'warn': ['not good enough', 'need more', 'need much more', 'expect more', 'expect much more', 'improve', 'step up', 'wake up', 'level is not',
             'not your level', 'below your level', 'not happy with you', 'disappointed in you',
             'nisi dovoljno dobar', 'nije dovoljno dobar', 'nije dovoljno', 'nisi dovoljno', 'trebam vise', 'trebam puno vise', 'ocekujem vise', 'ocekujem puno vise', 'popravi', 'podigni', 'probudi', 'nije tvoja razina',
             'ispod tvoje razine', 'nisam zadovoljan tobom', 'razocaran sam tobom', 'moras bolje', 'mora bolje', 'moras puno bolje'],
    'threat': ['one more', 'last chance', 'final warning', 'out of the team', 'drop you', 'dropped', 'out of the squad', 'reserves', 'or else',
               'you will be out', 'train with the', 'fine you',
               'jos jednom', 'jos jedna', 'zadnja prilika', 'zadnja sansa', 'zadnje upozorenje', 'van sastava', 'izvan sastava', 'ispast ces',
               'ispasti ces', 'micem te', 'maknut cu te', 'rezerv', 'u suprotnom', 'inace', 'kazn', 'trenirat ces s'],
    'push': ['even more', 'more from you', 'can do better', 'stay hungry', 'keep pushing', 'not satisfied', 'dont relax', 'no time to relax',
             'not praise him too much', 'more to come', 'can give more',
             'jos vise', 'jos bolje', 'mozes bolje', 'mozes vise', 'ostani glad', 'ostati gladan', 'gladan', 'ne opustaj', 'nemoj se opustit',
             'nisam zadovoljan jos', 'moze vise', 'moze bolje', 'mozes dati vise'],
    'belief': ['believe in', 'faith in', 'trust in', 'trust you', 'trust him', 'confidence in', 'confident', 'back you', 'back him', 'behind you',
               'behind him', 'will come', 'dont worry', 'do not worry', 'keep your head up', 'head up', 'you will be fine', 'it will come',
               'vjerujem', 'vjeru', 'povjerenje', 'uz tebe', 'uz njega', 'iza tebe', 'iza njega', 'doci ce', 'bit ce dobro', 'ne brini', 'ne brinite',
               'glavu gore', 'samopouzdan', 'siguran sam u'],
    'team': ['team effort', 'whole team', 'collective', 'all of them', 'everyone contributed', 'the group', 'squad effort', 'team performance',
             'cijela momcad', 'cijeli tim', 'kolektiv', 'timski', 'svi su', 'cijela ekipa', 'grupa', 'zajednicki'],
    'rude': ['idiot', 'stupid', 'moron', 'useless', 'clown', 'shut up', 'fuck', 'shit', 'pathetic', 'disgrace', 'joke of a',
             'idiot', 'glup', 'kreten', 'debil', 'budal', 'sutit', 'sutite', 'jebo', 'jebe', 'jeben', 'sranje', 'govno', 'jadnik', 'nesposob', 'smece', 'klaun'],
}

# negacija mijenja znacenje (znacajka -> (nova, tezina))
NEG_MAP = {'praise': ('criticism', 0.6), 'criticism': ('praise', 0.4), 'win': ('realistic', 0.6), 'keep': ('sell', 0.9), 'sell': ('keep', 1.0),
           'leave': ('hold', 0.9), 'hold': ('leave', 0.6), 'renew': ('noext', 1.0), 'minutes': ('honest', 0.7), 'ambition': ('realistic', 0.6),
           'belief': ('criticism', 0.5), 'support': ('blame', 0.4), 'key': ('rotation', 0.6), 'starter': ('rotation', 0.8), 'respect': ('hostile', 0.6),
           'worry': ('belief', 0.6), 'later': ('renew', 0.4), 'rest': ('starter', 0.3), 'threat': ('belief', 0.3), 'warn': ('praise', 0.3),
           'hostile': ('respect', 0.4), 'sorry': ('hostile', 0.4), 'realistic': ('ambition', 0.4), 'deflect': ('honest', 0.3)}

_COMPILED = None


def _compile():
    global _COMPILED
    if _COMPILED is None:
        out = []
        for f, pats in LEX.items():
            for p in pats:
                ws = p.split()
                if ws:
                    out.append((f, ws))
        out.sort(key=lambda x: -len(x[1]))       # dulji uzorci prvi
        _COMPILED = out
    return _COMPILED


def _wmatch(tok, w):
    if w.startswith('='):
        return tok == w[1:]
    if len(w) <= 3:
        return tok == w
    return tok.startswith(w)


def features(text):
    """-> (dict znacajka->tezina, lista pogodaka [(znacajka, rijeci, negirano)])"""
    toks = norm(text)
    used = [False] * len(toks)
    found = []
    for f, ws in _compile():
        n = len(ws)
        i = 0
        while i + n <= len(toks):
            if not any(used[i:i + n]) and all(_wmatch(toks[i + k], ws[k]) for k in range(n)):
                found.append((i, n, f))
                for k in range(n):
                    used[i + k] = True
                i += n
            else:
                i += 1
    found.sort()
    feat, hits = {}, []
    for i, n, f in found:
        win = []
        for j in range(i - 1, max(-1, i - 4), -1):
            if toks[j] == '|':
                break
            if not used[j]:
                win.append(j)
        neg = any(toks[j] in NEG for j in win)
        if neg:
            last_neg = max(j for j in win if toks[j] in NEG)
            if any(toks[j] in ('but', 'ali', 'nego', 'vec', 'and', 'i') for j in range(last_neg + 1, i)):
                neg = False
        w = 1.0 + (0.3 if any(toks[j] in INTENS for j in win[:2]) else 0) + 0.15 * (n - 1)
        tgt = f
        if neg:
            m = NEG_MAP.get(f)
            if not m:
                continue
            tgt, k = m
            w *= k
        feat[tgt] = feat.get(tgt, 0) + w
        hits.append((tgt, ' '.join(toks[i:i + n]), neg))
    ex = (text or '').count('!')
    if ex:
        feat['_loud'] = min(3, ex)
    letters = [c for c in (text or '') if c.isalpha()]
    if len(letters) >= 12 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7:
        feat['_loud'] = feat.get('_loud', 0) + 2
    return feat, hits


# ---------------------------------------------------------------- namjere opcija
GEN = {
    'pos': dict(praise=1, belief=1, ambition=.6, win=.6, support=.6, keep=.3, key=.4, minutes=.3),
    'neu': dict(deflect=1, respect=.7, realistic=.4, work=.5, honest=.5, later=.3, team=.5),
    'neg': dict(criticism=1, blame=.9, warn=.8, threat=.8, hostile=.5, push=.5, rude=.6),
}
PRESS = {
    'board': {'pos': dict(support=1, belief=1, praise=.6, ambition=.4, win=.3),
              'neu': dict(deflect=1, respect=.4, work=.6, realistic=.3, honest=.3),
              'neg': dict(blame=1.2, criticism=1, warn=.8, threat=.8, rude=.5)},
    'next': {'pos': dict(win=1.4, belief=.6, praise=.3, ambition=.4),
             'neu': dict(respect=1.2, realistic=.6, work=.6, deflect=.5),
             'neg': dict(hostile=1.4, criticism=.6, threat=.4, rude=.6)},
    'rumour': {'pos': dict(keep=1.4, praise=.5, hold=.8, key=.5),
               'neu': dict(deflect=.9, realistic=.3, honest=.3),
               'neg': dict(sell=1.3, leave=1, blame=.3)},
    'unhappy': {'pos': dict(praise=1, minutes=1.2, key=.8, belief=.8, starter=.6, keep=.4),
                'neu': dict(deflect=1.2, honest=.3),
                'neg': dict(work=.8, criticism=1, leave=.8, blame=.6, threat=.6, rude=.6, warn=.6)},
    'goal': {'pos': dict(ambition=1.3, win=.8, belief=.5, praise=.3),
             'neu': dict(work=.8, deflect=.6, respect=.3),
             'neg': dict(realistic=1.3, criticism=.6, blame=.4)},
    'broken': {'pos': dict(sorry=1.4, minutes=.3),
               'neu': dict(belief=.8, deflect=.3, realistic=.5, honest=.4, respect=.2),
               'neg': dict(hostile=1, deflect=.5, criticism=.5, rude=.8)},
    'm_star': {'pos': dict(praise=1.2, belief=.5, key=.5),
               'neu': dict(team=1.6, deflect=.4, respect=.3, honest=.3, work=.3),
               'neg': dict(push=1.3, criticism=.6, warn=.5)},
    'm_weak': {'pos': dict(belief=1.2, support=.8, praise=.6),
               'neu': dict(deflect=1, honest=.6, realistic=.3),
               'neg': dict(criticism=1, warn=.8, threat=.6, blame=.4, rude=.6)},
    'm_next': {'pos': dict(win=1.3, belief=.9, ambition=.5, praise=.4),
               'neu': dict(respect=.9, work=.5, deflect=.6, realistic=.3),
               'neg': dict(realistic=.8, criticism=.9, warn=.4, blame=.4)},
}

PRESS['story'] = {'pos': dict(win=1.2, respect=.6, praise=.3, belief=.4),
                  'neu': dict(deflect=1.2, realistic=.4, work=.5),
                  'neg': dict(hostile=1.4, criticism=.5, rude=.6)}

TALK = {
    'minutes': {'promise': dict(minutes=1.3, promise=.6, starter=.5), 'earn': dict(work=1.3, belief=.4),
                'honest': dict(honest=1.2, realistic=.5, criticism=.3, rotation=.3), 'door': dict(leave=1.4, sell=.6)},
    'ambition': {'project': dict(key=1, praise=.8, keep=.8, ambition=.5, belief=.5), 'door': dict(leave=1.3, sell=.8),
                 'contract': dict(hold=1.4, keep=.5, threat=.4)},
    'broken': {'sorry': dict(sorry=1.3, minutes=.8, promise=.3, starter=.4), 'explain': dict(belief=.7, deflect=.5, realistic=.5, work=.4, honest=.4, later=.3),
               'tough': dict(criticism=.8, work=.7, threat=.5, hostile=.4, blame=.3, rude=.5)},
    'contract': {'renew': dict(renew=1.4, keep=.6, praise=.3, hold=.3), 'later': dict(later=1.3, deflect=.5), 'no': dict(noext=1.4, leave=.8, sell=.4)},
    'praise': {'praise': dict(praise=1.2, belief=.4), 'more': dict(push=1.3, work=.5, criticism=.2, warn=.3)},
    'encourage': {'belief': dict(belief=1.2, praise=.6, support=.6), 'rest': dict(rest=1.4, rotation=.5)},
    'warn': {'warn': dict(warn=1.2, criticism=.8, push=.5, work=.4), 'public': dict(threat=1.4, warn=.3, blame=.3, rude=.4)},
    'role': {'key': dict(key=1.4, praise=.3), 'starter': dict(starter=1.4, minutes=.6), 'rotation': dict(rotation=1.4, honest=.3)},
}
TALK['interest'] = TALK['ambition']

LABEL = {'praise': 'praise', 'criticism': 'criticism', 'win': 'predicting a win', 'respect': 'respect for the opponent', 'hostile': 'a dig at them',
         'keep': '"he stays"', 'sell': 'open to selling', 'deflect': 'keeping it private', 'sorry': 'an apology', 'realistic': 'realism',
         'ambition': 'ambition', 'support': 'calm and support', 'blame': 'blaming players', 'leave': 'letting him go', 'hold': '"you stay"',
         'minutes': 'more minutes', 'promise': 'a promise', 'work': 'hard work', 'honest': 'honesty', 'rest': 'a rest', 'renew': 'a new contract',
         'later': '"later"', 'noext': 'no new contract', 'key': 'a key role', 'starter': 'a starting place', 'rotation': 'rotation', 'warn': 'a warning',
         'threat': 'a threat', 'push': 'demanding more', 'belief': 'belief', 'rude': 'insults', 'team': 'the whole team'}


def _score(vec, feat):
    return sum(w * feat.get(k, 0) for k, w in vec.items() if not k.startswith('_'))


def press_kind(q):
    if any(o.get('fx') is not None for o in q.get('opts', [])):
        return q.get('key')
    k = q.get('key')
    if k in ('star', 'weak', 'next'):
        return 'm_' + k
    return 'gen'


def understand_press(q, text):
    """q: pitanje iz _press_questions. -> dict(pick, tone, conf, feats, hits, alts)"""
    feat, hits = features(text)
    kind = press_kind(q)
    table = PRESS.get(kind) or GEN
    sc = {}
    for o in q['opts']:
        vec = table.get(o['tone']) or GEN.get(o['tone'], {})
        s = _score(vec, feat)
        if kind not in PRESS:
            s = max(s, 0.6 * _score(GEN.get(o['tone'], {}), feat))
        if o['tone'] == 'neg' and feat.get('_loud'):
            s += 0.15 * feat['_loud'] if s > 0 else 0
        sc[o['id']] = s
    ranked = sorted(q['opts'], key=lambda o: -sc[o['id']])
    best = ranked[0]
    top = sc[best['id']]
    second = sc[ranked[1]['id']] if len(ranked) > 1 else 0
    if top < 0.5:
        neu = next((o for o in q['opts'] if o['tone'] == 'neu'), best)
        return dict(pick=neu['id'], tone=neu['tone'], conf=0.2, low=True, feats=_feat_out(feat), hits=hits, scores=sc)
    conf = min(1.0, 0.45 + 0.25 * top + 0.3 * (top - second) / max(top, 0.01))
    return dict(pick=best['id'], tone=best['tone'], conf=round(conf, 2), low=conf < 0.5, feats=_feat_out(feat), hits=hits, scores=sc)


def understand_talk(topic, options, text):
    feat, hits = features(text)
    table = TALK.get(topic, {})
    sc = {o['id']: _score(table.get(o['id'], {}), feat) for o in options}
    ranked = sorted(options, key=lambda o: -sc[o['id']])
    best = ranked[0]
    top = sc[best['id']]
    second = sc[ranked[1]['id']] if len(ranked) > 1 else 0
    warm = feat.get('praise', 0) + feat.get('belief', 0) + feat.get('sorry', 0) * .5
    adj = -0.3 * min(2, feat.get('rude', 0)) - 0.05 * min(3, feat.get('_loud', 0)) + 0.05 * min(2, warm)
    if top < 0.5:
        return dict(pick=None, conf=0.2, low=True, adj=round(adj, 2), feats=_feat_out(feat), hits=hits, scores=sc)
    conf = min(1.0, 0.45 + 0.25 * top + 0.3 * (top - second) / max(top, 0.01))
    return dict(pick=best['id'], conf=round(conf, 2), low=conf < 0.5, adj=round(adj, 2), feats=_feat_out(feat), hits=hits, scores=sc)


def _feat_out(feat):
    return [dict(k=k, label=LABEL.get(k, k), w=round(v, 2)) for k, v in sorted(feat.items(), key=lambda x: -x[1]) if not k.startswith('_')][:4]


# ---------------------------------------------------------------- novinar: kratka reakcija na odgovor
ECHO = {
    ('next', 'pos'): ['So that is a promise: a win. We will hold you to it.', 'Bold. You are guaranteeing the three points?'],
    ('next', 'neu'): ['A respectful answer, then.', 'Measured words before a big game.'],
    ('next', 'neg'): ['That will make the back pages tomorrow.', 'Strong words. I am sure they will hear them.'],
    ('rumour', 'pos'): ['So he is not for sale. Noted.', 'Clear enough: he stays.'],
    ('rumour', 'neu'): ['Not a no, then.', 'So the door is not completely closed?'],
    ('rumour', 'neg'): ['So he can leave for the right price.', 'That sounds like an invitation to bid.'],
    ('goal', 'pos'): ['So you are aiming higher than the board. Brave.', 'A bigger target than the board set. Noted.'],
    ('goal', 'neg'): ['Lowering expectations, then.', 'The fans will not love that answer.'],
    ('board', 'pos'): ['Calm under pressure.', 'You sound confident.'],
    ('board', 'neg'): ['So the players are to blame?', 'That is a message to the dressing room.'],
    ('broken', 'pos'): ['Credit for owning it.', 'Not many managers admit that.'],
    ('broken', 'neg'): ['Touchy subject, I see.', 'That sounds like a dodge.'],
    ('unhappy', 'pos'): ['So he has a future here.', 'Warm words for him.'],
    ('unhappy', 'neg'): ['That will not calm him down.', 'Tough love, then.'],
}
ECHO_GEN = {'pos': ['Thank you.', 'Positive words.', 'Understood.'], 'neu': ['Diplomatic.', 'Fair enough.', 'Noted.'],
            'neg': ['Harsh words.', 'That is a strong message.', 'Not happy, then.']}
LOW = ['I am not sure that answers the question, but thank you.', 'So... I will take that as a "no comment".',
       'Let us move on, then.']


def echo_press(q, tone, low, seed):
    import random
    r = random.Random(seed)
    if low:
        return r.choice(LOW)
    k = press_kind(q)
    return r.choice(ECHO.get((k, tone)) or ECHO_GEN.get(tone) or ['Noted.'])


# ---------------------------------------------------------------- prosireni rjecnik (pc95)
EXTRA = {
    'praise': ['incredible', 'unbelievable', 'class', 'top player', 'top lad', 'great lad', 'great player', 'huge player', 'massive player',
               'top drawer', 'different level', 'another level', 'special player', 'special talent', 'gem', 'machine', 'beast', 'warrior',
               'leader', 'captain material', 'proud of', 'thrilled', 'over the moon', 'excellent work', 'great job', 'good job', 'nice work',
               'magnifique', 'perfect', 'spot on', 'superb', 'world beater', 'match winner', 'game changer', 'key man', 'fan favourite',
               'playing well', 'in great form', 'in good form', 'on fire', 'flying', 'unstoppable', 'clinical', 'composed', 'brave', 'mature',
               'odigrao odlicno', 'igrao odlicno', 'igra odlicno', 'igra dobro', 'igrao dobro', 'odigrao dobro', 'bio je sjajan', 'bio si sjajan',
               'mašina', 'masina', 'zvijer', 'ratnik', 'borac', 'kapetan', 'carobnjak', 'cudo', 'dragulj', 'biser', 'klasa', 'ozbiljan igrac',
               'veliki igrac', 'igracina', 'frajer', 'legenda', 'pun pogodak', 'savrsen', 'perfekt', 'u formi', 'u odlicnoj formi', 'u top formi',
               'gori', 'leti', 'nezaustavljiv', 'precizan', 'smiren', 'zreo', 'hrabar', 'neumoran', 'motor', 'zadovoljan sam', 'sve pohvale',
               'skidam kapu', 'kapa dolje', 'respekt', 'odlicna utakmica', 'odlicna partija', 'dobra partija', 'sjajna partija', 'top partija',
               'pokazao karakter', 'pokazali karakter', 'pokazali smo karakter', 'fenomenalno', 'maestralno', 'genijalno', 'brutalno dobro'],
    'criticism': ['shocking', 'awful', 'dreadful', 'abysmal', 'woeful', 'not good', 'not great', 'not acceptable', 'nowhere near', 'off the pace',
                  'switched off', 'asleep', 'sleeping', 'no effort', 'no energy', 'no fight', 'no heart', 'gave up', 'too slow', 'too soft',
                  'naive', 'amateur', 'schoolboy', 'nightmare', 'disaster', 'mess', 'embarrassment', 'humiliat', 'let us down', 'let the fans down',
                  'not his day', 'off day', 'bad day', 'below his level', 'poor game', 'poor performance', 'bad performance', 'bad game',
                  'lose', 'losa partija', 'losa utakmica', 'losa igra', 'los dan', 'losiji', 'ocajno', 'ocajan', 'katastrofalno', 'blamaza', 'bruka',
                  'sramota', 'ponizenje', 'ponizavajuc', 'spavali', 'spavao', 'zaspali', 'bez energije', 'bez borbe', 'bez srca', 'bez zelje',
                  'predali', 'predao', 'prespor', 'premek', 'naivn', 'amaterski', 'djecje greske', 'kosmar', 'nered', 'raspad', 'nije bio svoj',
                  'nije njegov dan', 'ispod nivoa', 'nismo bili dobri', 'nije bilo dobro', 'nije dobro', 'jako lose', 'previse gresaka',
                  'nedopustivo', 'neozbiljn', 'neodgovorn', 'bezidejn', 'jalov', 'mlak', 'bljedo', 'blijed', 'podbacio', 'podbacili', 'zakazao',
                  'zakazali', 'razocarali', 'iznevjerili navijace'],
    'win': ['win it', 'win on', 'win at', 'get the win', 'get a result', 'take three points', 'all three points', 'beat them', 'we beat',
            'destroy them', 'crush them', 'thrash', 'hammer them', 'outplay', 'we are better', 'better team', 'we will score', 'score goals',
            'favourites', 'we expect to win', 'expect a win', 'clean sheet and a win', 'go there to win', 'play to win', 'only the win',
            'only three points', 'nothing but a win', 'confident we win',
            'dobit cemo ih', 'dobijemo', 'dobit cemo utakmicu', 'pobjeda je cilj', 'samo pobjeda', 'idemo po pobjedu', 'idemo po tri boda',
            'tri boda ostaju', 'uzimamo tri boda', 'uzet cemo tri', 'zabit cemo', 'zabijat cemo', 'bolji smo', 'bolja smo momcad', 'mi smo favorit',
            'favoriti smo', 'razbit cemo', 'razbiti cemo', 'rasturit', 'pomesti cemo', 'nadigrat cemo', 'slomit cemo', 'srusit cemo',
            'nema sanse da izgubimo', 'necemo izgubiti', 'ne mozemo izgubiti', 'igramo na pobjedu', 'igramo za pobjedu'],
    'respect': ['great team', 'top side', 'quality side', 'excellent team', 'excellent coach', 'great manager', 'big club', 'tough place',
                'hard place to go', 'they are strong', 'they are dangerous', 'well organised', 'well coached', 'we know their quality',
                'admire', 'huge respect', 'take it seriously', 'not underestimate', 'cant underestimate', 'will be difficult', 'fifty fifty', '50 50',
                'odlicna momcad', 'kvalitetna momcad', 'veliki klub', 'dobar trener', 'odlican trener', 'tesko gostovanje', 'tezak teren',
                'jaki su', 'opasni su', 'dobro organiziran', 'znamo njihovu kvalitetu', 'cijenim', 'velik respekt', 'shvacamo ozbiljno',
                'ne podcjenjujemo', 'ne smijemo podcijeniti', 'bit ce tesko', 'pedeset posto', '50 posto', 'izjednacen', 'otvorena utakmica',
                'svaka cast protivniku', 'priznajem'],
    'hostile': ['they talk', 'let them talk', 'not scared', 'not afraid', 'we fear no one', 'fear nobody', 'they should be scared', 'they will see',
                'see on the pitch', 'talk on the pitch', 'arrogance', 'disrespectful', 'cheap shot', 'mind games', 'whinge', 'cry baby', 'moan',
                'excuses', 'lucky last time', 'they were lucky', 'overrated', 'nothing special', 'not that good', 'who are they', 'small team',
                'neka pricaju', 'nek pricaju', 'ne bojimo se', 'ne bojim se', 'ne bojimo se nikoga', 'neka se boje', 'nek se boje', 'vidjet ce',
                'vidjet cemo na terenu', 'teren ce pokazati', 'bahatost', 'nepostovanje', 'psiholoske igre', 'kukaju', 'placu', 'izgovori',
                'imali su srece', 'sreca ih je', 'precijenjen', 'nista posebno', 'nisu nista', 'tko su oni', 'mala momcad', 'mali klub su', 'smijesno',
                'neozbiljni su', 'neka se bave sobom', 'nek se bave sobom', 'brinite za sebe', 'gledajte sebe'],
    'keep': ['not selling', 'wont sell', 'no chance he leaves', 'no way he leaves', 'he is ours', 'hes ours', 'he is going nowhere', 'stay with us',
             'remain', 'long term future', 'build around him', 'priceless', 'not available', 'no offers', 'reject any offer', 'not interested in offers',
             'ne prodajem', 'ne damo ga', 'necemo ga dati', 'ne dam ga', 'nema sanse da ode', 'nema sanse da ga prodamo', 'nas je', 'ostat ce s nama',
             'ostati kod nas', 'buducnost kluba', 'neprocjenjiv', 'nije dostupan', 'odbijamo sve ponude', 'odbit cemo', 'ne zanimaju nas ponude',
             'ni za koje novce', 'ni za kakve novce', 'nema te cijene', 'nema cijene'],
    'sell': ['sell him', 'for sale', 'accept an offer', 'bid', 'bids', 'fee', 'valuation', 'release clause', 'for the right price', 'right money',
             'business decision', 'if he wants to go', 'cash in', 'make a profit', 'big money',
             'prodaja', 'prodajemo', 'na prodaju je', 'ponudu', 'ponude su dobrodosle', 'odstetn', 'klauzul', 'za prave novce', 'pravi novac',
             'za dobar novac', 'poslovna odluka', 'ako zeli otici', 'zaradit', 'profit', 'veliki novac', 'velike novce', 'unovcit'],
    'deflect': ['just another game', 'another game', 'like any other', 'nothing special for me', 'just three points', 'samo jos jedna utakmica', 'jos jedna utakmica', 'obicna utakmica', 'kao i svaka druga', 'kao svaka druga', 'samo tri boda', 'nije nista posebno', 'speculation', 'rumours', 'rumors', 'not going to talk', 'i wont talk', 'not my concern', 'not something i comment on',
                'only care about', 'we will see', 'time will tell', 'not important now', 'next game is what matters', 'nothing to say',
                'not today', 'ask the board', 'ask the director', 'leave it there',
                'spekulacij', 'nagadjanj', 'glasine', 'necu o tome', 'ne bih o tome', 'nije moja briga', 'ne komentiram', 'ne komentiramo',
                'zanima me samo', 'vrijeme ce pokazati', 'nije bitno sada', 'bitna je sljedeca', 'nemam sto reci', 'nemam komentara',
                'pitajte upravu', 'pitajte direktora', 'ostavimo to', 'idemo dalje', 'o tome cemo drugi put', 'to ostaje medju nama'],
    'sorry': ['apologies', 'i apologise', 'i apologize', 'excuse me', 'forgive me', 'that was on me', 'on me', 'i should have', 'i shouldnt have',
              'regret', 'mea culpa', 'i got it wrong', 'got it wrong', 'my bad', 'fault is mine', 'the blame is mine',
              'ispricavam', 'ispricavam se', 'oprostite', 'oprosti mi', 'zao mi je', 'žao mi je', 'zalim', 'trebao sam', 'nisam trebao', 'krivo sam',
              'pogrijesio', 'moja je krivnja', 'krivnja je moja', 'na meni je', 'snosim odgovornost', 'preuzimam krivnju'],
    'realistic': ['realistic target', 'be realistic', 'lets be realistic', 'consolidate', 'stay up', 'survival', 'avoid relegation', 'mid table',
                  'bigger budgets', 'small budget', 'not the money', 'cant compare', 'one step at a time', 'patience needed', 'need time',
                  'ostati u ligi', 'opstanak', 'izbjeci ispadanje', 'sredina tablice', 'veci budzeti', 'mali budzet', 'nemamo novca', 'ne mozemo se usporedjivati',
                  'treba vremena', 'potrebno vrijeme', 'budimo realni', 'trebamo biti realni', 'realno gledano', 'objektivno', 'skromni ciljevi',
                  'ne smijemo letjeti', 'noge na zemlji', 'nogama na zemlji'],
    'ambition': ['go for the title', 'top half', 'top six', 'qualify', 'qualification', 'cup run', 'win the cup', 'win something', 'silverware',
                 'make history', 'history', 'the sky is the limit', 'no limits', 'nothing is impossible', 'fight for', 'push for', 'aim for the top',
                 'gornji dom', 'gornja polovica', 'prvih sest', 'prvih pet', 'prvih cetiri', 'plasman u europu', 'kvalifikacij', 'kup', 'osvojit',
                 'osvajanje', 'pisati povijest', 'povijest', 'nebo je granica', 'bez granica', 'nista nije nemoguce', 'borit cemo se za', 'ciljamo vrh',
                 'vrh tablice', 'za vrh', 'za naslov', 'za prvaka'],
    'support': ['we stick together', 'stay calm', 'keep calm', 'no panic', 'dont panic', 'trust the process', 'the process', 'good relationship',
                'talk every day', 'board is happy', 'we are aligned', 'same page',
                'drzimo se zajedno', 'ostajemo mirni', 'bez panike', 'nema panike', 'vjerujem u proces', 'proces', 'dobar odnos s upravom',
                'u kontaktu s upravom', 'uprava je zadovoljna', 'na istoj smo strani', 'svi smo zajedno'],
    'blame': ['individual errors', 'individual mistakes', 'some of them', 'a few players', 'players must', 'players have to', 'they need to wake up',
              'not good enough from', 'look at themselves', 'look in the mirror', 'attitude problem', 'lack of commitment', 'not professional',
              'individualne greske', 'pojedinci', 'neki od njih', 'par igraca', 'igraci moraju', 'moraju se probuditi', 'neka se pogledaju',
              'u ogledalo', 'problem s karakterom', 'nema predanosti', 'neprofesional', 'krivi su igraci', 'igraci su krivi'],
    'leave': ['you can leave', 'you may leave', 'go if you want', 'if you want to go', 'if you want to leave', 'your choice', 'up to you', 'no problem if you go',
              'we will find a club', 'find you a club', 'loan', 'go on loan',
              'mozes ici', 'ako hoces ici', 'ako zelis ici', 'tvoj izbor', 'na tebi je', 'nema problema ako odes', 'nadjemo ti klub', 'naci cemo ti klub',
              'posudba', 'na posudbu', 'slobodno', 'ne branim ti'],
    'hold': ['you signed', 'you are under contract', 'contract until', 'nobody leaves', 'no one leaves', 'i decide', 'the club decides', 'not for sale',
             'potpisao si', 'imas ugovor do', 'nitko ne ide', 'nitko ne odlazi', 'ja odlucujem', 'klub odlucuje', 'ostajes ovdje', 'ostajes kod nas'],
    'minutes': ['more game time', 'game time', 'playing time', 'you will get games', 'you will get minutes', 'next match you start',
                'you start next', 'your turn', 'from the start', 'in the starting', 'next week you play', 'chance in the cup', 'cup games',
                'minutaz', 'minute', 'vise igrati', 'igrat ces vise', 'dobit ces minute', 'dobit ces vise minuta', 'sljedeca je tvoja',
                'krecs od pocetka', 'od prve minute', 'u prvoj jedanaestorici', 'sljedeci tjedan igras', 'kup utakmice', 'u kupu igras',
                'pruzit cu ti priliku', 'dat cu ti priliku', 'dobit ces svoju priliku', 'dobit ces sansu'],
    'promise': ['i promise', 'promised', 'you have my word', 'i give you my word', 'guaranteed', 'for sure', 'definitely', 'hundred percent', '100 percent',
                'obecajem', 'obecao sam', 'dajem rijec', 'moja rijec', 'sigurno', 'sto posto', '100 posto', 'garantiram', 'zajamceno', 'kunem ti se'],
    'work': ['work harder', 'put the work in', 'graft', 'improve in training', 'show me in training', 'impress me', 'convince me', 'earn a place',
             'compete', 'competition for places', 'be patient', 'patience',
             'radi vise', 'radi jace', 'zapni', 'pokazi na treningu', 'uvjeri me', 'impresioniraj me', 'izbori se', 'konkurencija', 'budi strpljiv',
             'strpljenje', 'trudi se', 'trud', 'disciplin', 'fokusiraj se na trening'],
    'honest': ['to be honest', 'honestly', 'the truth is', 'straight with you', 'i will be straight', 'reality is', 'facts', 'right now he is better',
               'he is better', 'others are better', 'not first choice', 'behind in the pecking order', 'pecking order',
               'iskreno', 'da budem iskren', 'istina je', 'bit cu iskren', 'realnost je', 'cinjenice', 'on je trenutno bolji', 'drugi su bolji',
               'nisi prvi izbor', 'hijerarhij', 'redoslijed'],
    'rest': ['take a break', 'switch off', 'recover', 'recovery', 'rotate you', 'a few days off', 'days off', 'holiday', 'manage your minutes',
             'manage your load', 'load management',
             'uzmi pauzu', 'oporavi se', 'oporavak', 'par dana slobodno', 'slobodni dani', 'odmori se', 'dozirat', 'opterecenj', 'cuvat cu te',
             'cuvamo te'],
    'renew': ['new terms', 'improve your contract', 'better contract', 'pay rise', 'raise', 'more money', 'reward you', 'long term deal',
              'nove uvjete', 'bolji ugovor', 'povisic', 'vise novca', 'veca placa', 'nagradit', 'dugorocni ugovor', 'novi potpis', 'potpisi ponovno'],
    'later': ['in a few months', 'next summer', 'january', 'when the time comes', 'soon', 'let us wait', 'lets wait', 'no rush', 'no hurry',
              'za par mjeseci', 'iduce ljeto', 'sljedece ljeto', 'u sijecnju', 'u zimu', 'kad dodje vrijeme', 'uskoro', 'pricekajmo', 'nema zurbe',
              'polako', 'ima vremena'],
    'noext': ['no extension', 'not in our plans', 'not part of the plans', 'end of the road', 'time to part', 'part ways', 'move on in the summer',
              'nema produzenja', 'nisi u planovima', 'nisi dio planova', 'kraj puta', 'vrijeme je za rastanak', 'rastajemo se', 'razici cemo se',
              'ljeti odlazis'],
    'key': ['main player', 'most important player', 'franchise', 'the star', 'our star', 'focal point', 'centrepiece', 'centerpiece', 'number one',
            'first name on the team sheet', 'irreplaceable', 'vital', 'crucial', 'essential',
            'glavni', 'najvazniji igrac', 'zvijezda', 'nasa zvijezda', 'centralna figura', 'broj jedan', 'prvo ime na popisu', 'nezamjenjiv',
            'nezamjenjljiv', 'presudan', 'kljucna figura', 'oslonac'],
    'starter': ['starting place', 'starting spot', 'first team regular', 'nailed on', 'guaranteed starter', 'starts every game', 'plays every game',
                'mjesto u prvoj postavi', 'standardan', 'stalno mjesto', 'siguran u sastavu', 'svake utakmice', 'igra svaku', 'igrat ces stalno', 'starter'],
    'rotation': ['share minutes', 'share the load', 'squad role', 'impact sub', 'from the bench', 'super sub', 'when needed', 'when i need you',
                 'occasionally', 'here and there',
                 'dijelit minute', 'uloga u momcadi', 'dzoker', 'joker', 's klupe', 'kad zatreba', 'kad te trebam', 'po potrebi', 'tu i tamo',
                 'na smjenu', 'mijenjat cete se'],
    'warn': ['raise your level', 'lift your level', 'up your game', 'sharpen up', 'concentrate', 'focus more', 'more focus', 'more effort', 'more intensity',
             'more professional', 'be more professional', 'this cannot continue', 'cant continue', 'this has to change', 'has to change', 'things must change',
             'podigni razinu', 'podigni nivo', 'izostri se', 'koncentriraj se', 'vise fokusa', 'vise truda', 'vise intenziteta', 'budi profesionalniji',
             'ovo ne moze tako', 'ne moze se ovako', 'ovo se mora promijeniti', 'mora se promijeniti', 'stvari se moraju promijeniti', 'nisam zadovoljan'],
    'threat': ['bench you', 'on the bench', 'sit on the bench', 'drop to the bench', 'u23', 'b team', 'second team', 'transfer list', 'sell you',
               'get rid of you', 'no future here', 'consequences', 'punish',
               'na klupu', 'sjedit ces', 'sjediti ces', 'druga momcad', 'b momcad', 'mladja momcad', 'transfer listu', 'prodat cu te', 'rijesit cu te se',
               'nemas buducnost', 'nema buducnosti', 'posljedice', 'kaznit cu', 'globa', 'novcana kazna'],
    'push': ['more goals', 'more assists', 'keep it up and more', 'raise the bar', 'next level', 'step further', 'dont stop', 'never satisfied',
             'vise golova', 'vise asistencija', 'podigni letvicu', 'sljedeca razina', 'korak dalje', 'ne staj', 'ne stani', 'nikad zadovoljan',
             'moze jos', 'ima jos', 'jos koji gol'],
    'belief': ['i believe', 'i trust', 'confident in you', 'you will come good', 'you will bounce back', 'stay positive', 'keep going', 'chin up',
               'it happens', 'happens to everyone', 'everyone has bad days', 'you are good enough', 'youre good enough', 'support you', 'with you',
               'vjerujem ti', 'imam povjerenja', 'imam povjerenje', 'vratit ces se', 'ostani pozitivan', 'samo naprijed', 'nastavi', 'glavu gore',
               'dogodi se', 'svakome se dogodi', 'svatko ima los dan', 'dovoljno si dobar', 'podrzavam te', 'tu sam za tebe', 'uz tebe sam'],
    'rude': ['loser', 'dumb', 'trash', 'garbage', 'piece of', 'bloody', 'damn', 'wtf', 'retard',
             'luzer', 'smeće', 'glupan', 'glupane', 'idiote', 'kretenu', 'majmun', 'stoka', 'krava', 'magarac', 'tupan', 'tukac', 'koza', 'picka', 'kurac',
             'pizda', 'jebem', 'odjebi', 'mamu', 'sereš', 'seres', 'drkat', 'bezveznjak', 'nula', 'nikakav'],
    'team': ['team spirit', 'together as a team', 'as a group', 'the lads', 'the boys', 'everybody', 'all the players', 'whole squad', 'team game',
             'decki', 'dečki', 'momci', 'svi igraci', 'cijeli sastav', 'timska igra', 'zajedno kao momcad', 'kao grupa', 'zajednistvo'],
}
_seen = {f: set(v) for f, v in LEX.items()}
for _f, _pats in EXTRA.items():
    for _p in _pats:
        _p2 = ' '.join(norm(_p))
        if _p2 and _p2 not in _seen.setdefault(_f, set()):
            LEX.setdefault(_f, []).append(_p2)
            _seen[_f].add(_p2)
