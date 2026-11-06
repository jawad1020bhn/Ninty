"""Uvod u novi klub: velika vijest + prica zasto te nova uprava htjela (izmisljeni, ali vezani uz povijest u appu).

Sve je deterministicno po kljucu (karijera + klub + datum), pa se isti uvod ne mijenja pri ponovnom otvaranju.
"""
import random

HEAD = [
    'OFFICIAL: {mgr} is the new {new} manager',
    '{new} turn to {mgr}',
    '{mgr} takes charge at {new}',
    'From {old} to {new}: {mgr} gets a second chance',
    '{new} appoint {mgr} after a week of talks',
    'Surprise in {city}: {mgr} named {new} head coach',
    '{mgr} back in the dugout, this time at {new}',
    'New era at {new}: {mgr} signs on',
]
HEAD_FIRST = [   # nema prethodnog kluba u appu
    'OFFICIAL: {mgr} is the new {new} manager',
    '{new} hand the keys to {mgr}',
    'A new name on the {new} bench: {mgr}',
]

# zasto je otisao iz staroga kluba
LEFT_SACKED = [
    '{old} lost patience{posx}, and {mgr} was shown the door on {until}.',
    'The end at {old} came quickly: a board meeting, a short statement, and {mgr} was out{posx}.',
    'At {old} the results never followed the ideas{posx}. The club pulled the plug on {until}.',
    '{old} decided a change was needed{posx}. {mgr} cleared the office the same afternoon.',
    'It was not supposed to end like this at {old}{posx}, but football rarely waits.',
]
LEFT_LEFT = [
    '{mgr} left {old} by mutual agreement at the end of the season{posx}.',
    'After {old}{posx}, {mgr} felt the project had gone as far as it could.',
    '{mgr} turned down a new deal at {old} to look for a bigger challenge.',
]

# zasto ga je nova uprava izabrala
WHY = [
    'The {new} board liked the way your sides play: brave, on the front foot, with the ball.',
    'The sporting director watched three {old} matches in person and came back with one name.',
    'The president is an old admirer and pushed for the appointment from day one.',
    '{new} wanted a coach who develops young players, and your work at {old} did not go unnoticed.',
    'The first-choice candidate turned {new} down. You were plan B, and you have a point to prove.',
    'Your interview lasted six hours. The board say it was the dossier on pressing that won them over.',
    'The dressing room asked for a coach with clear ideas. The captain was consulted, and he said yes.',
    'With no compensation to pay, you were the quickest and cheapest solution, and the board liked your plan.',
    'Your possession numbers at {old} impressed the analysts more than the results worried them.',
    'The board see you as the man to stabilise the club after a rough spell under {prev}.',
    'A former {new} player now on the board put your name forward over dinner.',
    'The fans wanted a fresh face with energy. The board agreed.',
    'Your press conferences at {old} made an impression: calm, honest, never hiding behind excuses.',
    'The owners want a long-term project, and you were the only candidate with a three-year plan on paper.',
    'The scouts were tired of watching your {old} side give their teams trouble. Better to hire you.',
]
WHY_FIRST = [
    'The {new} board liked the way your sides play: brave, on the front foot, with the ball.',
    'The owners want a long-term project, and you were the only candidate with a three-year plan on paper.',
    'The president is an old admirer and pushed for the appointment from day one.',
    'The fans wanted a fresh face with energy. The board agreed.',
]

# situacija u novom klubu
SITUATION = [
    '{new} sit {pos} in the {league}{gapx}. {prev} is gone, and the squad needs a reaction.',
    'You inherit a side {pos} in the {league}{gapx}. {prev} left behind talent but little confidence.',
    'The table says {pos}{gapx}. The mood around the club says the same: it is time for something new.',
]
SITUATION_NO = [
    'A new squad, a new league, a new city. Everything starts from zero.',
]

# prvi dani: male izmisljene scene
FIRST_DAYS = [
    ('__gi_1f399__', 'The unveiling press conference is packed: three TV crews and every local paper.'),
    ('__gi_1f9e3__', 'A few hundred fans waited outside the training ground to see you arrive.'),
    ('__gi_1f4cb__', 'The sporting director left a folder on your desk: "Players we can sell".'),
    ('__gi_1f91d__', 'The captain asked for a one-to-one meeting before your first training session.'),
    ('__gi_1f4de__', 'Two agents called before lunch, each with a client who is "perfect for your system".'),
    ('__gi_2615__', 'The kit man already knew how you take your coffee. Somebody did their homework.'),
    ('__gi_1f4fa__', 'Pundits are split: half call it a bold choice, half call it a gamble.'),
    ('__gi_1f3df__', 'You walked the empty stadium alone on the first evening. It felt bigger than on TV.'),
    ('__gi_1f4f0__', 'The local paper ran your face on the front page with one word: "Ready?"'),
    ('__gi_1f5c2__', 'The analysts handed you 40 pages on the previous coach\'s tactics.'),
    ('__gi_1f9d1_200d_1f91d_200d_1f9d1__', 'One of the senior players skipped the welcome meeting. Nobody wants to say why.'),
    ('__gi_1f4c8__', 'The club shop sold out of training tops the day your name was announced.'),
    ('__gi_1f6eb__', '{old} fans sent a mixed message on social media: thanks, and good riddance.'),
    ('__gi_2709_fe0f__', 'A handwritten note from the club president: "Make them proud."'),
]
FIRST_DAYS_FIRST = [x for x in FIRST_DAYS if '{old}' not in x[1]]

# sto uprava ocekuje (iz board.goal)
GOAL_LINE = {
    'title': 'The board want the title. Nothing less.',
    'europe': 'The board expect a European place.',
    'upper': 'The board want a top-half finish.',
    'mid': 'A calm season in mid-table is the minimum.',
    'survive': 'The only target: keep the club in the league.',
}

TAG = ['Breaking news', 'Official', 'Done deal', 'Exclusive']


def _ord(n):
    try:
        n = int(n)
    except Exception:
        return str(n)
    return '%d%s' % (n, 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th'))


def build(key, mgr, new, old=None, until=None, reason=None, old_pos=None, prev=None, league=None, pos=None, n=None,
          gap_safe=None, gap_top=None, goal=None, target=None, city=None):
    """-> dict(tag, head, lead, paras[], days[[ic, txt]], goal, sub)"""
    rnd = random.Random(str(key))
    first = not old
    f = dict(mgr=mgr or 'The new manager', new=new, old=old or '', until=until or 'that day', prev=prev or 'the previous coach',
             league=league or 'league', pos=_ord(pos) if pos else '', city=city or new.split(' ')[-1])
    f['posx'] = (' with the team %s in the table' % _ord(old_pos)) if old_pos else ''
    gx = ''
    if pos and n:
        if gap_safe is not None and pos >= n - 4 and gap_safe <= 4:
            gx = ', only %d point%s above the drop zone' % (gap_safe, '' if gap_safe == 1 else 's') if gap_safe > 0 else ', inside the relegation zone' if gap_safe < 0 else ', level on points with the drop zone'
        elif gap_safe is not None and pos >= n - 4 and gap_safe <= 8:
            gx = ', just %d points clear of the drop zone' % gap_safe
        elif gap_top is not None and pos <= 4:
            gx = ', %d point%s off the top' % (gap_top, '' if gap_top == 1 else 's') if gap_top > 0 else ', top of the table'
    f['gapx'] = gx
    head = rnd.choice(HEAD_FIRST if first else HEAD).format(**f)
    paras = []
    if not first:
        pool = LEFT_SACKED if reason == 'sacked' else LEFT_LEFT
        paras.append(rnd.choice(pool).format(**f))
    why = rnd.sample(WHY_FIRST if first else WHY, 2)
    if prev is None:
        why = [w for w in why if '{prev}' not in w] or [WHY[0]]
    paras.append(' '.join(w.format(**f) for w in why))
    if pos:
        paras.append(rnd.choice(SITUATION).format(**f))
    else:
        paras.append(rnd.choice(SITUATION_NO).format(**f))
    days = [[ic, t.format(**f)] for ic, t in rnd.sample(FIRST_DAYS_FIRST if first else FIRST_DAYS, 3)]
    g = GOAL_LINE.get(goal or '', '')
    if target and not g:
        g = 'The board expect a finish in the top %d.' % target
    lead = ('%s leaves %s behind and starts again at %s.' % (f['mgr'], old, new)) if not first else ('%s starts a new chapter at %s.' % (f['mgr'], new))
    cap = lambda t: '. '.join(x[:1].upper() + x[1:] for x in t.split('. '))
    paras = [cap(p) for p in paras]
    return dict(tag=rnd.choice(TAG), head=head, lead=lead, paras=paras, days=days, goal=g, target=target)
