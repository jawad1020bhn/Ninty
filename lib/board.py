"""Uprava kluba (u appu): cilj sezone, povjerenje uprave, upozorenja i reputacija menadzera.

Igra ima svoj sustav otkaza (neovisan). Ovo je uprava u appu: prati isto sto i igra (tablica prema ocekivanju, forma),
upozorava, pamti otkaze i vodi reputaciju menadzera kroz karijeru (za ponude klubova kasnije).
"""
import math

GOALS = (
    ('title', 'Win the league'),
    ('challenge', 'Challenge for the title (top 3)'),
    ('europe', 'Qualify for Europe'),
    ('upper', 'Finish in the top half'),
    ('mid', 'A safe mid-table season'),
    ('survive', 'Avoid relegation'),
)
GOAL_TXT = dict(GOALS)


def goal_for(exp, n):
    """Cilj iz ocekivanog mjesta (po snazi momcadi u ligi)."""
    if n < 4:
        return 'mid', n
    f = (exp - 1) / float(max(1, n - 1))
    if exp == 1:
        return 'title', 1
    if exp <= 3 and n >= 12:
        return 'challenge', 3   # pc315: drugi ili treci po snazi (npr. Liverpool, prvak) ne igra samo za Europu
    if f <= 0.22:
        return 'europe', max(2, int(math.ceil(0.22 * n)))
    if f <= 0.45:
        return 'upper', int(math.ceil(0.5 * n))
    if f <= 0.75:
        return 'mid', int(math.ceil(0.75 * n))
    return 'survive', n - 3


def target_pos(goal, n):
    return {'title': 1, 'challenge': 3, 'europe': max(2, int(math.ceil(0.22 * n))), 'upper': int(math.ceil(0.5 * n)),
            'mid': int(math.ceil(0.75 * n)), 'survive': n - 3}.get(goal, n - 3)


def week_delta(p):
    """Promjena povjerenja za jedan tjedan iz pritiska (coaches.pressure, 0 = sve po planu)."""
    if p > 0.3:
        return -min(18.0, 12.0 * (p - 0.3))
    return min(5.0, 4.0 * (0.3 - p) + 1.0)


LEVELS = ((75, 'delighted'), (55, 'satisfied'), (40, 'concerned'), (25, 'worried'), (12, 'final_warning'), (0, 'lost_faith'))


def level(trust):
    for t, k in LEVELS:
        if trust >= t:
            return k
    return 'lost_faith'


def start_rep(tier):
    return {'big': 62, 'mid': 45, 'small': 32}.get(tier, 45)


def season_rep(pos, target, n, champion=False):
    """Promjena reputacije na kraju sezone: koliko si bio iznad/ispod cilja (mjesta), naslov +8."""
    d = (target - pos) / float(max(1, n)) * 40
    d = max(-10.0, min(10.0, d))
    if champion:
        d += 8
    return round(d, 1)


def rep_label(r):
    return 'world class' if r >= 85 else 'elite' if r >= 72 else 'respected' if r >= 58 else 'established' if r >= 44 else 'rising' if r >= 30 else 'unproven'
