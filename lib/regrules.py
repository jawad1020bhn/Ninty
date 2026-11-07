"""Squad registration rules per league, for EA SPORTS FC 27 ids.

Rules and the EU membership list: Michele & Claude, "Regole di tesseramento",
used with their permission.
  Serie A          list of 25 players over 21; at most 2 new non-EU signings from abroad per window
  Serie B          list of 25; at most 1 new non-EU signing from abroad
  LaLiga, LaLiga 2 list of 25; at most 3 non-EU players in the squad
  Ligue 1, Ligue 2 at most 4 non-EU players in the squad
  Premier League   list of 25
Players aged 21 or under are always free, and selling is always allowed.
EU = European Union + Switzerland, Norway, Iceland and Liechtenstein; England,
Scotland and Wales are outside it. The game stores one nationality per player
(no dual citizenship).

League ids come from data/fc27/leagues.json and nationality ids from
data/fc27/nations.json - both read out of the database, never guessed. They are
EA's ids and are NOT interchangeable with any other game's numbering.
"""

FREE_AGE = 21

RULES = {
    31: dict(name='Serie A', lista=25, new_extra=2),
    32: dict(name='Serie B', lista=25, new_extra=1),
    53: dict(name='LaLiga', lista=25, extra=3),
    54: dict(name='LaLiga 2', lista=25, extra=3),
    16: dict(name='Ligue 1', extra=4),
    17: dict(name='Ligue 2', extra=4),
    13: dict(name='Premier League', lista=25),
}
DOMESTIC = {31: 'IT', 32: 'IT', 53: 'ES', 54: 'ES', 16: 'FR', 17: 'FR',
            13: 'EN', 14: 'EN', 60: 'EN', 61: 'EN', 19: 'DE', 20: 'DE', 2076: 'DE'}

# EU + Switzerland, Norway, Iceland and Liechtenstein, by ISO code in
# data/fc27/nations.json: 4 Austria / 18 France / 21 Germany / 27 Italy /
# 45 Spain / 47 Switzerland / 36 Norway / 24 Iceland / 29 Liechtenstein.
EU = {4, 7, 9, 10, 11, 12, 13, 17, 18, 21, 22, 23, 24, 25, 27, 28, 29,
      30, 31, 32, 34, 36, 37, 38, 39, 43, 44, 45, 46, 47, 208}


def non_eu(nat):
    """True when the nationality is known and outside the EU set.

    FC 27 nationality ids are plain small integers (1..226), so no bit masking
    is needed.
    """
    return nat is not None and nat not in EU


def check(tid, squad, inc, from_tid=None):
    """tid: the buyer's league; squad: [dict(pid, age, nat, new)] the current squad
    (new = arrived this window); inc: dict(pid, age, nat) the incoming player;
    from_tid: the selling club's league (None = unknown or a free agent).
    -> None when allowed, otherwise the reason as user-facing text."""
    r = RULES.get(tid)
    if not r or not inc:
        return None
    young = (inc.get('age') or 99) <= FREE_AGE
    if young:
        return None
    others = [p for p in squad if p.get('pid') != inc.get('pid')]
    if r.get('lista'):
        over = sum(1 for p in others if (p.get('age') or 0) > FREE_AGE)
        if over + 1 > r['lista']:
            return ('%s registration rules: your list of %d players over %d is full (%d). Sell, loan out or release a player over %d first.'
                    % (r['name'], r['lista'], FREE_AGE, over, FREE_AGE))
    if inc.get('nat') is None:
        return None   # nationality unknown: the remaining rules cannot be checked
    if not non_eu(inc['nat']):
        return None
    if r.get('extra') is not None:
        n = sum(1 for p in others if non_eu(p.get('nat')))
        if n + 1 > r['extra']:
            return ('%s registration rules: at most %d non-EU players in the squad, you already have %d.' % (r['name'], r['extra'], n))
    if r.get('new_extra') is not None:
        abroad = from_tid is None or DOMESTIC.get(from_tid) != DOMESTIC.get(tid)
        if abroad:
            n = sum(1 for p in others if p.get('new') and non_eu(p.get('nat')) and (p.get('age') or 0) > FREE_AGE)
            if n + 1 > r['new_extra']:
                if r['new_extra'] == 0:
                    return '%s registration rules: no new non-EU players from abroad can be signed.' % r['name']
                return ('%s registration rules: at most %d new non-EU player%s from abroad per transfer window, you already signed %d.'
                        % (r['name'], r['new_extra'], '' if r['new_extra'] == 1 else 's', n))
    return None
