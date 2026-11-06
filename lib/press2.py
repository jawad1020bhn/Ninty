"""Konferencije v2: pitanja iz konteksta (uprava, sljedeci protivnik, glasine o transferima, nezadovoljni igraci,
cilj sezone, prekrsena obecanja) i posljedice svakog odgovora.

Odgovor nosi listu ucinaka (fx):
  ('aff', pid | 'squad', delta)      moral igraca (Affection u igri, preko mosta)
  ('board', delta)                   povjerenje uprave u appu
  ('fans', delta)                    raspolozenje navijaca (app)
  ('promise', dict)                  obecanje koje se kasnije provjerava
  ('war', klub)                      verbalni rat s trenerom protivnika (vijest)
Sve je deterministicno za (slot, konferencija).
"""
import hashlib
import random


def rng(*p):
    return random.Random(int(hashlib.md5('|'.join(str(x) for x in p).encode()).hexdigest()[:12], 16))


def _q(key, topic, q, opts, pid=None, pname=''):
    return dict(key=key, topic=topic, q=q, pid=pid, pname=pname,
                opts=[dict(id=i, tone=t, t=txt, fx=fx) for i, (t, txt, fx) in enumerate(opts)])


def q_board(ctx, r):
    """Uprava nezadovoljna: novinari pitaju za posao."""
    lv = ctx.get('board_level')
    if lv not in ('concerned', 'worried', 'final_warning', 'lost_faith'):
        return None
    pos, tgt = ctx.get('pos'), ctx.get('target')
    q = r.choice(['You are %s and the board expected a top-%s finish. Is your job under threat?' % (ctx.get('pos_s'), tgt),
                  'There are reports the board is losing patience. How secure do you feel?',
                  'Results are below expectations. Have you spoken to the board this week?'])
    return _q('board', 'board', q, [
        ('pos', 'I have the full backing of the board and I believe in this group. We will turn it around.', [('board', 2), ('aff', 'squad', 3)]),
        ('neu', 'I understand the pressure. That is football. I only focus on the next game.', [('board', 1)]),
        ('neg', 'Some players are not giving me what I need. That has to change, starting now.', [('aff', 'squad', -6), ('board', -1), ('fans', 1)]),
    ])


def q_next(ctx, r):
    """Sljedeci protivnik: obecanje pobjede ili psiholoski rat."""
    nx = ctx.get('next')
    if not nx:
        return None
    opp = nx['opp']
    stronger = nx.get('opp_str', 0) > ctx.get('my_str', 0) + 1
    q = r.choice(['Next up is %s. What is your prediction?' % opp,
                  '%s are %s. How do you approach that game?' % (opp, 'favourites' if stronger else 'up next'),
                  'The %s manager said this week his team will win. Your response?' % opp])
    return _q('next', 'next', q, [
        ('pos', 'We will beat %s. I am sure of it.' % opp, [('promise', dict(kind='win', opp=opp, n=nx.get('n'))), ('aff', 'squad', 3), ('fans', 2)]),
        ('neu', 'Respect to %s. It will be a hard game and we will prepare well.' % opp, [('board', 1)]),
        ('neg', 'I do not care what %s say. They should worry about their own problems.' % opp, [('war', opp), ('fans', 2), ('aff', 'squad', 2)]),
    ])


def q_rumour(ctx, r):
    """Glasine o odlasku tvog igraca (interes vecih klubova ili ponude)."""
    ru = ctx.get('rumour')
    if not ru:
        return None
    pid, pn, club = ru['pid'], ru['name'], ru.get('club') or 'a bigger club'
    q = r.choice(['%s are reportedly interested in %s. Is he for sale?' % (club, pn),
                  'Will %s still be here after the window closes? %s are said to be watching.' % (pn, club)])
    return _q('rumour', 'rumour', q, [
        ('pos', '%s is not for sale. End of story.' % pn, [('promise', dict(kind='keep', pid=pid, name=pn)), ('aff', pid, 9), ('fans', 2)]),
        ('neu', 'Every player has a price, but we are not looking to sell.', [('aff', pid, -3)]),
        ('neg', 'If the right offer comes, we will listen. Nobody is bigger than the club.', [('aff', pid, -9), ('board', 2), ('fans', -2)]),
    ], pid=pid, pname=pn)


def q_unhappy(ctx, r):
    """Nezadovoljan igrac (zahtjevi)."""
    u = ctx.get('unhappy')
    if not u:
        return None
    pid, pn = u['pid'], u['name']
    why = u.get('why')
    q = ('%s is said to be unhappy with his playing time. Will he get more chances?' % pn) if why in ('bench', 'minutes') else \
        ('Reports say %s wants a move. What is your message to him?' % pn)
    if why not in ('bench', 'minutes'):
        return _q('unhappy', 'unhappy', q, [
            ('pos', '%s is a key player for us and he knows how much I value him. I am not worried.' % pn, [('aff', pid, 9)]),
            ('neu', 'That is an internal matter. I speak to my players in private.', [('aff', pid, 2)]),
            ('neg', 'Nobody is bigger than this club. If he wants to go, he can tell me to my face.', [('aff', pid, -9), ('aff', 'squad', 2), ('fans', 1)]),
        ], pid=pid, pname=pn)
    return _q('unhappy', 'unhappy', q, [
        ('pos', '%s is an important player for us. His chance will come, I have told him that.' % pn, [('aff', pid, 9), ('aff', 'squad', -1)]),
        ('neu', 'That is an internal matter. I speak to my players in private.', [('aff', pid, 2)]),
        ('neg', 'Nobody is guaranteed a place. %s has to earn it in training, like everyone else.' % pn, [('aff', pid, -9), ('aff', 'squad', 2)]),
    ], pid=pid, pname=pn)


def q_goal(ctx, r):
    """Cilj sezone: obecati vise, biti realan ili spustiti ocekivanja."""
    g = ctx.get('goal_txt')
    if not g:
        return None
    q = r.choice(['The board wants you to %s. Is that realistic?' % g.lower(),
                  'What is the target for this season? Fans want to know.'])
    higher = dict(kind='goal_up', goal=ctx.get('goal'))
    return _q('goal', 'goal', q, [
        ('pos', 'We can do more than that. This team can surprise everybody.', [('promise', higher), ('board', 3), ('fans', 3), ('aff', 'squad', 2)]),
        ('neu', 'The target is clear and we work for it every day.', [('board', 1)]),
        ('neg', 'We have to be realistic. This squad has limits.', [('board', -3), ('fans', -2), ('aff', 'squad', -3)]),
    ])


def q_broken(ctx, r):
    """Novinar podsjeca na prekrseno obecanje."""
    b = ctx.get('broken')
    if not b:
        return None
    if b['kind'] == 'win':
        q = 'Last time you said you would beat %s. You did not. What went wrong?' % b.get('opp')
    elif b['kind'] == 'keep':
        q = 'You said %s was not for sale. Now he is gone. Did you mislead the fans?' % b.get('name')
    else:
        q = 'You promised more than the board asked for this season. That has not happened. Your thoughts?'
    return _q('broken', 'broken', q, [
        ('pos', 'I take full responsibility. I said it and I did not deliver. We will learn from it.', [('board', 2), ('fans', 2)]),
        ('neu', 'Things change in football. I will not apologise for believing in my team.', [('fans', -1)]),
        ('neg', 'That is not a fair question. Let us talk about the future.', [('fans', -3), ('board', -1)]),
    ])


def q_story(ctx, r):
    """Prica sezone vezana uz sljedeceg protivnika: povratak u bivsi klub ili osveta."""
    st = ctx.get('story')
    nx = ctx.get('next')
    if not st or not nx:
        return None
    opp = nx['opp']
    if st['kind'] == 'revenge':
        q = 'Last season %s %s. Is this game about revenge?' % (opp, st.get('why') or 'had the better of you')
    elif st.get('who') == 'player':
        q = '%s faces you for the first time since you sold him to %s. Do you regret letting him go?' % (st.get('name') or 'He', opp)
    else:
        q = 'You go back to %s, your former club. What does this game mean to you?' % opp
    return _q('story', 'story', q, [
        ('pos', 'It is special for me and I respect them, but we will go there to win.', [('promise', dict(kind='win', opp=opp, n=nx.get('n'))), ('fans', 2), ('aff', 'squad', 2)]),
        ('neu', 'It is just another game. Three points, nothing more.', [('board', 1)]),
        ('neg', 'I have nothing to prove to them. They will see on the pitch.', [('war', opp), ('fans', 3), ('aff', 'squad', 2)]),
    ])


BUILDERS = (q_broken, q_story, q_board, q_rumour, q_unhappy, q_next, q_goal)


def context_questions(slot, cid, ctx, limit=3):
    r = rng('pc2', slot, cid)
    out = []
    for b in BUILDERS:
        q = b(ctx, r)
        if q:
            out.append(q)
        if len(out) >= limit:
            break
    return out


def apply_fx(picks_fx):
    """Zbroji ucinke odabranih odgovora. -> dict(aff={pid|'squad': d}, board=d, fans=d, promises=[], wars=[])"""
    out = dict(aff={}, board=0, fans=0, promises=[], wars=[])
    for fx in picks_fx:
        for e in fx or []:
            k = e[0]
            if k == 'aff':
                out['aff'][e[1]] = out['aff'].get(e[1], 0) + e[2]
            elif k == 'board':
                out['board'] += e[1]
            elif k == 'fans':
                out['fans'] += e[1]
            elif k == 'promise':
                out['promises'].append(e[1])
            elif k == 'war':
                out['wars'].append(e[1])
    return out
