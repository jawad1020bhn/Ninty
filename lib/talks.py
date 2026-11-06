"""Razgovori menadzera i igraca ("svlacionica").

Igrac sam trazi razgovor (minute, ambicija, prekrseno obecanje, ugovor) ili ga menadzer pozove (pohvala, ohrabrenje,
upozorenje, obecanje uloge). Ishod ovisi o osobnosti igraca (persona: ego, ambicija, odanost, novac), o tome sto mu nudis
i o malo slucajnosti (deterministicno po igracu i danu). Ucinci: moral (Affection), forma, obecanja, zahtjevi za odlazak.
"""
import hashlib
import random

OUTCOMES = ((0.6, 'delighted'), (0.2, 'content'), (-0.2, 'unconvinced'), (-9, 'angry'))
AFF = {'delighted': 9, 'content': 4, 'unconvinced': -3, 'angry': -9}


def rng(*p):
    return random.Random(int(hashlib.md5('|'.join(str(x) for x in p).encode()).hexdigest()[:12], 16))


def outcome(score):
    for t, k in OUTCOMES:
        if score >= t:
            return k
    return 'angry'


# ---------------------------------------------------------------- teme
# svaka opcija: (id, tekst menadzera, osnova, funkcija modifikatora(tr, ctx), radnja)
def _opts(topic, ctx):
    n = ctx.get('first') or 'mate'
    if topic == 'minutes':
        return [
            ('promise', 'You will get more minutes in the coming games. You have my word.', 0.7, lambda tr, c: -0.2 * (1 - tr['loyalty']) * c.get('broken', 0), 'req_promise'),
            ('earn', 'Keep working hard in training. Your chance will come.', 0.1, lambda tr, c: 0.3 * tr['loyalty'] - 0.35 * tr['ego'], None),
            ('honest', 'Right now others are ahead of you. I will not lie to you.', -0.05, lambda tr, c: 0.45 * tr['loyalty'] - 0.25 * tr['ego'], None),
            ('door', 'If you want to leave, I will not stop you.', 0.25, lambda tr, c: 0.5 * tr['ambition'] - 0.6 * tr['loyalty'], 'req_release'),
        ]
    if topic in ('ambition', 'interest'):
        return [
            ('project', 'You are the heart of this project. I want to build the team around you.', 0.3, lambda tr, c: 0.5 * tr['loyalty'] - 0.35 * tr['ambition'], None),
            ('door', 'If a big club comes with the right offer, I will not stand in your way.', 0.55, lambda tr, c: 0.2 * tr['ambition'], 'req_release'),
            ('contract', 'You have a contract. You are not going anywhere.', -0.35, lambda tr, c: 0.55 * tr['loyalty'] - 0.2 * tr['ego'], 'req_refuse'),
        ]
    if topic == 'broken':
        return [
            ('sorry', 'You are right, I let you down. You will start the next match.', 0.5, lambda tr, c: -0.2 * tr['ego'], 'promise_reset'),
            ('explain', 'The team needed a different set-up. Your time will come, trust me.', -0.05, lambda tr, c: 0.35 * tr['loyalty'] - 0.3 * tr['ego'], None),
            ('tough', 'I pick the team on merit, not on promises.', -0.55, lambda tr, c: 0.3 * tr['loyalty'], 'promise_angry'),
        ]
    if topic == 'contract':
        return [
            ('renew', 'We want you to stay. Let us sit down and talk about a new contract.', 0.55, lambda tr, c: -0.35 * tr['ambition'] * c.get('step_down', 0), 'go_contract'),
            ('later', 'We will talk about it at the end of the season.', 0.1, lambda tr, c: 0.35 * tr['loyalty'] - 0.25 * tr['money'], None),
            ('no', 'To be honest, we do not plan to extend it.', -0.45, lambda tr, c: 0.15 * tr['loyalty'], None),
        ]
    if topic == 'praise':
        return [
            ('praise', 'You have been excellent lately. Keep it up, %s.' % n, 0.6, lambda tr, c: 0.1 * (c.get('form', 4) - 4), 'form_up'),
            ('more', 'Good, but I know you can give me even more.', 0.15, lambda tr, c: 0.35 * (1 - tr['ego']) - 0.1, 'form_up_maybe'),
        ]
    if topic == 'encourage':
        return [
            ('belief', 'I believe in you. Do not lose your head, the goals and the good games will come.', 0.45, lambda tr, c: 0.2 * tr['loyalty'], None),
            ('rest', 'Take a breather. A few games on the bench will do you good.', -0.1, lambda tr, c: 0.4 * (1 - tr['ego']) - 0.2 * tr['ambition'], None),
        ]
    if topic == 'warn':
        return [
            ('warn', 'Your level is not good enough right now. I need much more from you.', -0.15, lambda tr, c: 0.55 * tr['loyalty'] - 0.45 * tr['ego'], 'form_up_if_ok'),
            ('public', 'One more performance like that and you are out of the team.', -0.35, lambda tr, c: 0.4 * tr['loyalty'] - 0.5 * tr['ego'] + 0.2 * tr['ambition'], 'form_up_if_ok'),
        ]
    if topic == 'role':
        return [
            ('key', 'I want you to be a key player for us. The team will be built around you.', 0.6, lambda tr, c: 0, 'promise_key'),
            ('starter', 'You will be a regular starter from now on.', 0.4, lambda tr, c: 0.2 * c.get('role_gap', 0), 'promise_starter'),
            ('rotation', 'You will play a part in rotation, game by game.', 0.0, lambda tr, c: 0.3 * c.get('role_gap', 0) + 0.2 * tr['loyalty'] - 0.2 * tr['ego'], None),
        ]
    return []


OPEN = {
    'minutes': ['Boss, can we talk? I have not been playing and I do not understand why.',
                'I need to play. Sitting on the bench every week is killing me.',
                'I came here to play football, not to watch it. What is the plan for me?'],
    'ambition': ['I have to be honest with you: I want to play at the highest level. I think it is time for a step up.',
                 'I love this club, but I feel I am ready for something bigger.'],
    'interest': ['You must have seen the news. {club} want me. I would like to talk about it.',
                 'My agent tells me {club} are interested. That is a big chance for me.'],
    'broken': ['You promised me a role in this team. That has not happened.',
               'I trusted you. You told me I would play, and I am still on the bench.'],
    'contract': ['My contract runs out soon and nobody has said a word to me. What is going on?',
                 'I want to know my future here. My contract is ending.'],
    'praise': ['Boss, you wanted to see me?'],
    'encourage': ['Boss, you wanted to see me?'],
    'warn': ['Boss, you wanted to see me?'],
    'role': ['Boss, you wanted to see me?'],
}

REPLY = {
    'delighted': ['Thank you, boss. That means a lot. You will not regret it.', 'That is all I needed to hear. I am all in.',
                  'Great. I will give you everything on the pitch.'],
    'content': ['OK. I trust you. Let us see how it goes.', 'Fair enough. I will keep working.', 'Understood, boss.'],
    'unconvinced': ['I hear you, but I am not sure I believe it.', 'We will see. Words are cheap.', 'I expected more from this conversation.'],
    'angry': ['That is not acceptable. I will speak to my agent.', 'Then we have a problem, boss.', 'I did not come here to be treated like this.'],
}


def opening(topic, ctx, seed):
    r = rng('open', seed, topic)
    return r.choice(OPEN.get(topic) or ['Boss?']).replace('{club}', ctx.get('club_int') or 'a bigger club')


def options(topic, ctx):
    return [dict(id=o[0], t=o[1]) for o in _opts(topic, ctx)]


# odgovori vezani uz ono sto je menadzer rekao (dobar ishod / los ishod)
REPLY_OPT = {
    'promise': (['I will hold you to that, boss. I will be ready.', 'OK. I just want to play. Thank you.'],
                ['You said that before. I need to see it on the pitch.', 'Words. Show me on Saturday.']),
    'earn': (['Fair enough. I will make it hard for you to leave me out.', 'Then I will work twice as hard.'],
             ['I already work hard. That is not the problem.', 'I have been training well for weeks.']),
    'honest': (['At least you are honest with me. I respect that.', 'OK. I know where I stand.'],
               ['So I am not part of your plans.', 'Honest? It sounds like you have given up on me.']),
    'door': (['Thank you. I will tell my agent to look for options.', 'I appreciate that, boss. It is the right moment for me.'],
             ['So you want to get rid of me. Fine.', 'Wow. I thought I mattered here.']),
    'project': (['If you really build around me, I am in.', 'That means a lot. I want to win things here.'],
                ['Every manager says that. I want to see ambition.', 'A project is not a trophy.']),
    'contract': (['OK, I understand. I will keep my head down.', 'I know. I just wanted you to hear me.'],
                 ['A contract does not make me happy.', 'So I am a prisoner here?']),
    'sorry': (['I appreciate you saying that. Let us move on.', 'Thank you for being straight with me.'],
              ['Sorry is not enough this time.', 'We will see if anything changes.']),
    'explain': (['OK, I can accept that.', 'I understand. I will be ready.'],
                ['There is always a reason, is there not?', 'Your time will come... I have heard that before.']),
    'tough': (['Then I will earn it.', 'Fine. I will prove it in training.'],
              ['Then why make the promise?', 'Merit? I have done everything right.']),
    'renew': (['Great. I want to stay. Let us talk.', 'That is what I wanted to hear.'],
              ['It will have to be a very good offer.', 'Let us see what you put on the table.']),
    'later': (['OK, I can wait until the summer.', 'Fine. As long as we talk.'],
              ['I do not want to wait. Other clubs are calling.', 'Later is too late for me.']),
    'no': (['I understand. Thank you for telling me.', 'OK. At least I can plan my future.'],
           ['After everything I gave this club?', 'Then I will play out my contract and leave.']),
    'praise': (['Thanks, boss. I feel great right now.', 'Thank you. The lads make it easy.'],
               ['Thanks.', 'OK.']),
    'more': (['I know. I will give you more.', 'Message received. I am not done yet.'],
             ['More? I am giving everything.', 'Nothing is ever enough, is it?']),
    'belief': (['Thanks, boss. That helps a lot.', 'I needed to hear that.'],
               ['Belief does not change my minutes.', 'OK... thanks, I guess.']),
    'rest': (['Maybe you are right. I will recharge.', 'OK, a short break might help.'],
             ['I do not need a rest. I need to play.', 'The bench? That is the last thing I need.']),
    'warn': (['You are right. I will step up.', 'I know. It will not happen again.'],
             ['I do not agree, but OK.', 'You are blaming me for the team.']),
    'public': (['Understood. You will see a reaction.', 'Message received loud and clear.'],
               ['You cannot threaten me like that.', 'Then drop me. See what happens.']),
    'key': (['That means everything to me. I will not let you down.', 'Then let us win something together.'],
            ['I will believe it when I see it.', 'Key player? We will see.']),
    'starter': (['Thank you. I will repay your trust.', 'Great. I am ready every week.'],
                ['We will see if that lasts.', 'I have heard that before.']),
    'rotation': (['OK. I will be ready when you need me.', 'Fair enough, I will take my chances.'],
                 ['Rotation? I expected more.', 'I did not come here to rotate.']),
}
CONFUSED = 'Sorry boss, I am not sure what you mean.'


def resolve(topic, choice, tr, ctx, seed, adj=0.0):
    """-> dict(outcome, aff, form, action, reply). adj: ton slobodnog teksta (uvrede -, toplina +)."""
    op = next((o for o in _opts(topic, ctx) if o[0] == choice), None)
    if not op:
        raise ValueError('unknown answer')
    _, _, base, mod, action = op
    r = rng('talk', seed, topic, choice)
    score = base + mod(tr, ctx) + r.uniform(-0.15, 0.15) - 0.25 * ctx.get('low_mood', 0) + max(-0.6, min(0.15, adj or 0))
    oc = outcome(score)
    form = 0
    if action == 'form_up' and oc in ('delighted', 'content'):
        form = 1
    if action in ('form_up_maybe', 'form_up_if_ok') and oc in ('delighted', 'content'):
        form = 1
    if action == 'form_up_if_ok' and oc == 'angry':
        form = -1
    ro = REPLY_OPT.get(choice)
    rep = r.choice(ro[0] if oc in ('delighted', 'content') else ro[1]) if ro and r.random() < 0.75 else r.choice(REPLY[oc])
    if oc == 'angry' and (adj or 0) <= -0.3:
        rep = r.choice(['Do not talk to me like that.', 'You do not speak to me like that, boss.', 'Watch your words.']) + ' ' + rep
    return dict(outcome=oc, aff=AFF[oc], form=form, action=action, reply=rep, score=round(score, 2))
