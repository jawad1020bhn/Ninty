"""press.py - press konferencije (FM tekstovi) i njihov ucinak na formu/moral (Affection) igraca."""
import json, os, re, random, hashlib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FM = None


def fm():
    global _FM
    if _FM is None:
        _FM = json.load(open(os.path.join(HERE, 'data', 'fm_text.json'), encoding='utf-8'))
    return _FM


def rng(*parts):
    return random.Random(int(hashlib.md5('|'.join(str(p) for p in parts).encode()).hexdigest()[:12], 16))


def fill(t, p2=None, club='', ctx='pc'):
    """Zamjena FM oznaka. pc: person#1 = trener, person#2 = igrac. fan: person#1 = igrac."""
    name = p2 or 'the player'
    parts = name.strip().split()
    first, sur = (parts[0], ' '.join(parts[1:])) if len(parts) > 1 else (name, name)
    m = {'he': 'he', 'He': 'He', 'him': 'him', 'his': 'his', 'His': 'His', 'himself': 'himself', '': name, 'first': first, 'surname': sur, 'hidden': ''}

    def rep(mo):
        k = mo.group(1)
        who, _, form = k.partition('-')
        if who in ('person#author', ) or (ctx == 'pc' and who == 'person#1'):
            if who == 'person#author':
                return {'I': 'I', 'hidden': ''}.get(form, 'I')
            return {'I': 'I', 'you': 'you', 'my': 'my', 'My': 'My', 'me': 'me', 'surname': 'boss'}.get(form, 'I')
        if who in ('person#2', 'person#1'):
            return m.get(form, name)
        if who.startswith('team'):
            return club if form == 'short' else ''
        if who.startswith('cash'):
            return 'a big fee'
        return ''
    out = re.sub(r'\[%([^\]]+)\]', rep, t)
    return re.sub(r'\s+([.,!?;:])', r'\1', re.sub(r'\s{2,}', ' ', out)).strip()


# tema pitanja -> kome mijenja moral
TOPIC = {
    'NEW_SIGNING_IS_MANAGER_PLEASED_WITH_SIGNING': 'player', 'NEW_SIGNING_HIGH_FEE_PRESSURE_TO_SUCCEED': 'pressure',
    'NEW_SIGNING_WHAT_IMPACT_ON_REST_OF_SQUAD': 'squad', 'NEW_SIGNING_IS_PLAYER_A_DIFFERENCE_MAKER': 'player',
    'NEW_SIGNING_WILL_PLAYER_BE_KEY_TO_SUCCESS': 'player', 'NEW_SIGNING_POSITION_CHOSEN_ASK_MANAGER_TO_EXPLAIN_REASONING': 'player',
    'BIG_SIGNING_MADE_HOW_DOES_THAT_IMPACT_SHORT_AND_LONG_TERM_PLANS': 'squad', 'HOW_WILL_MANAGER_GET_BEST_OUT_OF_NEW_SIGNING': 'player',
    'WILL_NEW_EXPENSIVE_SIGNING_JUSTIFY_PRICE_TAG': 'pressure', 'HOW_DOES_NEW_SIGNING_LINK_WITH_CLUB_VISION_OBJECTIVES': 'squad',
    'CAN_NEW_YOUNG_FRINGE_SIGNING_BREAK_INTO_FIRST_TEAM_IN_NEAR_FUTURE': 'player',
}

# pitanja nakon utakmice (vlastiti tekst, HR/EN); ton: pos / neu / neg
MATCH_Q = {
    'team': dict(topic='team', q=('Kako ocjenjujete današnju igru momčadi?', 'How would you rate the team\'s performance today?'), a=[
        ('pos', 'Ponosan sam na dečke. Dali su sve što su imali.', 'I am proud of the lads. They gave everything.'),
        ('neu', 'Ima dobrih i loših dijelova. Idemo analizirati i ići dalje.', 'There were good and bad parts. We will analyse it and move on.'),
        ('neg', 'Ovo nije razina koju tražim. Očekujem puno više.', 'This is not the level I demand. I expect much more.')]),
    'star': dict(topic='star', q=('{p} je bio najbolji na terenu. Što kažete o njemu?', '{p} was the best on the pitch. What do you say about him?'), a=[
        ('pos', '{p} je izvanredan. Takve nastupe želim vidjeti svaki tjedan.', '{p} is outstanding. I want to see performances like that every week.'),
        ('neu', 'Dobro je odigrao, ali ovo je timski uspjeh.', 'He played well, but this is a team effort.'),
        ('neg', 'Dobro je, ali neću ga previše hvaliti. Mora ostati gladan.', 'He was good, but I will not praise him too much. He has to stay hungry.')]),
    'weak': dict(topic='weak', q=('{p} je imao težak dan. Jeste li razočarani?', '{p} had a tough day. Are you disappointed?'), a=[
        ('pos', 'Svatko ima loš dan. Imam potpuno povjerenje u {p}.', 'Everyone has a bad day. I have complete faith in {p}.'),
        ('neu', 'Nije bio na svojoj razini, razgovarat ćemo nasamo.', 'He was not at his level, we will talk in private.'),
        ('neg', 'Da, {p} mora puno bolje. Ovo nije prihvatljivo.', 'Yes, {p} has to do much better. This is not acceptable.')]),
    'next': dict(topic='team', q=('Što očekujete u sljedećoj utakmici?', 'What do you expect in the next match?'), a=[
        ('pos', 'Idemo po pobjedu. Vjerujem u ovu momčad.', 'We go for the win. I believe in this team.'),
        ('neu', 'Utakmicu po utakmicu, bez velikih riječi.', 'One game at a time, no big words.'),
        ('neg', 'Ako se ovako igra, bit će nam jako teško.', 'If we play like this, it will be very hard for us.')]),
}


def build_signing(slot, pid, name, club, seed):
    pc = fm()['pc']
    keys = [k for k, v in pc.items() if v['q'] and k in TOPIC]
    r = rng('presser', slot, pid, seed)
    r.shuffle(keys)
    qs = []
    for k in keys[:4]:
        v = pc[k]
        q = fill(r.choice(v['q']), name, club)
        by = {'pos': [], 'neu': [], 'neg': []}
        for i, a in enumerate(v['a']):
            by.setdefault(a.get('tone', 'neu'), []).append((i, a))
        opts, used = [], set()
        for tone in ('pos', 'neu', 'neg'):
            if by.get(tone):
                i, a = r.choice(by[tone])
                opts.append(dict(id=i, tone=tone, t=fill(a['t'], name, club)))
                used.add(i)
        rest = [(i, a) for i, a in enumerate(v['a']) if i not in used]
        r.shuffle(rest)
        while len(opts) < 3 and rest:
            i, a = rest.pop()
            opts.append(dict(id=i, tone=a.get('tone', 'neu'), t=fill(a['t'], name, club)))
        r.shuffle(opts)
        qs.append(dict(key=k, topic=TOPIC[k], q=q, opts=opts))
    return qs


def build_match(slot, mid, res, star, weak, lang_pair=0):
    qs = []
    keys = ['team', 'star' if star else None, 'weak' if weak and res != 'W' else None, 'next']
    for k in keys:
        if not k:
            continue
        d = MATCH_Q[k]
        who = (star if k == 'star' else weak) if k in ('star', 'weak') else None
        pn = who['name'] if who else ''
        qs.append(dict(key=k, topic=d['topic'], pid=(who['id'] if who else None), pname=pn,
                       q=[d['q'][0].replace('{p}', pn), d['q'][1].replace('{p}', pn)],
                       opts=[dict(id=i, tone=t, t=[h.replace('{p}', pn), e.replace('{p}', pn)]) for i, (t, h, e) in enumerate(d['a'])]))
    return qs


def effects(kind, picks, signed_pid, squad, rivals, res=None):
    """picks: [{topic, tone, pid}] -> rows [(pid, polje, delta, razlog)]. Affection koraka po +-3 (Lua ogranicava korak)."""
    aff, form = {}, {}

    def A(p, d):
        aff[p] = aff.get(p, 0) + d

    def F(p, d):
        form[p] = form.get(p, 0) + d
    for x in picks:
        t, tone, pid = x['topic'], x['tone'], x.get('pid')
        sgn = {'pos': 1, 'neu': 0, 'neg': -1}.get(tone, 0)
        if not sgn:
            continue
        if t == 'player' and signed_pid:
            A(signed_pid, 9 * sgn if sgn > 0 else -6)
            F(signed_pid, sgn)
        elif t == 'pressure' and signed_pid:
            A(signed_pid, 6 * sgn)
            if sgn > 0:
                F(signed_pid, 1)
        elif t == 'squad':
            for p in squad:
                A(p, 3 * sgn)
            if sgn < 0:
                for p in rivals:
                    A(p, -6)
        elif t == 'team':
            for p in squad:
                A(p, 3 * sgn)
        elif t == 'star' and pid:
            A(pid, 9 * sgn if sgn > 0 else -3)
            if sgn > 0:
                F(pid, 1)
        elif t == 'weak' and pid:
            A(pid, 9 * sgn if sgn > 0 else -9)
            F(pid, 1 if sgn > 0 else -1)
    rows = []
    for p, d in aff.items():
        d = max(-24, min(24, d))
        if d:
            rows.append((p, 'Affection', d))
    for p, d in form.items():
        d = max(-1, min(1, d))
        if d:
            rows.append((p, 'Form', d))
    return rows


def chunks(rows):
    """Razbij delte na korake po +-3 (GrowthBridge MAX_STEP) -> [(pid, polje, korak, n)]."""
    out = []
    for p, f, d in rows:
        s = 1 if d > 0 else -1
        d = abs(d)
        n = 0
        while d > 0:
            st = min(3, d)
            out.append((p, f, s * st, n))
            d -= st
            n += 1
    return out


def reactions(net, name, club, seed):
    """Tweetovi i komentari navijaca iz FM teksta, prema ukupnom tonu odgovora (net: <0, 0, >0)."""
    t = fm()
    tone = 'pos' if net > 0 else 'neg' if net < 0 else 'neu'
    r = rng('react', seed, name)
    tw = r.sample(t['tweet_' + tone], min(3, len(t['tweet_' + tone])))
    fn = r.sample(t['fan_' + tone] if tone != 'neg' or True else [], min(2, len(t['fan_' + tone])))
    return dict(tone=tone, tweets=[fill(x['t'], name, club, 'fan') for x in tw], fans=[fill(x['t'], name, club, 'fan') for x in fn])


def match_reactions(net, res, club, opp, seed):
    """Kratke reakcije medija/navijaca nakon pressa o utakmici: [(hr, en)] prema tonu."""
    pos = [('Navijači: "Konačno trener koji stoji iza svojih igrača."', 'Fans: "Finally a manager who backs his players."'),
           ('Mediji pohvalili smirenost trenera nakon utakmice.', 'Media praise the manager\'s composure after the match.'),
           ('Svlačionica zadovoljna trenerovim riječima.', 'Dressing room pleased with the manager\'s words.')]
    neu = [('Mediji: trener je govorio oprezno, bez velikih izjava.', 'Media: the manager spoke carefully, no big statements.'),
           ('Navijači podijeljeni oko trenerovih riječi.', 'Fans divided over the manager\'s words.')]
    neg = [('Navijači: "Trener preoštro kritizira momčad u javnosti."', 'Fans: "The manager is too harsh on the team in public."'),
           ('Mediji pišu o napetosti u svlačionici nakon trenerovih izjava.', 'Media report tension in the dressing room after the manager\'s comments.'),
           ('Igrači nisu oduševljeni javnom kritikom.', 'Players are not happy with the public criticism.')]
    r = rng('mreact', seed, club)
    L = pos if net > 0 else neg if net < 0 else neu
    return dict(tone='pos' if net > 0 else 'neg' if net < 0 else 'neu', lines=r.sample(L, min(2, len(L))))
