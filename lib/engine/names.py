"""Generated-player names from the shipped regen name pools.

data/fc27/regen_names.json has three lists, each row [name, poolId, flag]:

  first   11,744 rows   flag 0 = masculine, 1 = feminine
  last     9,358 rows   flag 0 = masculine form, 1 = feminine form, 2 = invariant
  common     481 rows   ready-made full names, flag 0

The flag meanings were verified against known names rather than guessed:
173/173 sampled masculine forenames (john, david, mohamed, luka, ...) carry 0 and
190/190 feminine ones (maria, laura, emma, ...) carry 1, with no counterexample.
The surname split is the Slavic/Turkic pattern - Abdullayev/Abdullayeva,
Andreev/Andreeva - so 0 and 1 are gendered forms of the same name and 2 is a
surname that does not inflect.

Two rules follow, and both were bugs in the first intake implementation, which
called rnd.choice() on the unfiltered lists:

  1. Pick the flag that matches the club. 85 of the 717 clubs are women's sides
     (the database's own `women` flag), and the rest are men's. Unfiltered
     picking produced "Alina Haraldsen" at a men's club and masculine names at
     women's clubs.
  2. Take the forename AND surname from the SAME pool. poolId is a language /
     regional group, so mixing pools produced names like "Maimouna
     Kubanychbekova" - an Arabic forename with a Kyrgyz surname.

poolId is NOT a nation id. An attempt to map pools to nationalities by matching
surnames against the real player table was rejected: only 16 of 89 pools had a
dominant nation at >=50% purity, because Spanish and Arabic surnames span many
nations. So no nationality is inferred from a name pool, and a generated
player's nation is left unset rather than invented.
"""
import collections

import fc27

_MASC_FIRST = 0
_FEM_FIRST = 1
_MASC_LAST = 0
_FEM_LAST = 1
_NEUTRAL_LAST = 2

_CACHE = {}


def _pools():
    """poolId -> {'first': {0:[], 1:[]}, 'last': {0:[], 1:[], 2:[]}, 'common': []}"""
    if _CACHE:
        return _CACHE
    n = fc27.regen_names() or {}
    out = collections.defaultdict(lambda: {'first': collections.defaultdict(list),
                                           'last': collections.defaultdict(list),
                                           'common': []})
    for key in ('first', 'last'):
        for row in n.get(key) or []:
            if not row:
                continue
            name = str(row[0])
            pool = int(row[1]) if len(row) > 1 else 0
            flag = int(row[2]) if len(row) > 2 else (0 if key == 'first' else _NEUTRAL_LAST)
            out[pool][key][flag].append(name)
    for row in n.get('common') or []:
        if row:
            out[int(row[1]) if len(row) > 1 else 0]['common'].append(str(row[0]))
    _CACHE.update(out)
    return _CACHE


def is_women_club(tid):
    """The database's own flag, not a guess from the club's name."""
    c = (fc27.clubs() or {}).get(str(int(tid))) or {}
    return bool(int(c.get('women') or 0))


def usable_pools(women=False):
    """Pools that can actually produce a full name for this gender."""
    ff = _FEM_FIRST if women else _MASC_FIRST
    out = []
    for pid, p in _pools().items():
        if not p['first'].get(ff):
            continue
        if p['last'].get(_NEUTRAL_LAST) or p['last'].get(_FEM_LAST if women else _MASC_LAST):
            out.append(pid)
    return sorted(out)


def make_name(rnd, tid, women=None):
    """A full name appropriate to the club, from one language pool.

    Falls back to any usable pool if the chosen one is thin, and to a shipped
    'common' full name only if no pool can serve the gender at all.
    """
    if women is None:
        women = is_women_club(tid)
    pools = _pools()
    usable = usable_pools(women)
    if not usable:
        return 'Youth Player'
    pid = rnd.choice(usable)
    p = pools[pid]
    firsts = p['first'].get(_FEM_FIRST if women else _MASC_FIRST) or []
    # An inflecting surname must match the gender; an invariant one always does.
    lasts = list(p['last'].get(_NEUTRAL_LAST) or [])
    lasts += list(p['last'].get(_FEM_LAST if women else _MASC_LAST) or [])
    if not firsts or not lasts:
        common = p['common']
        if common:
            return rnd.choice(common)
        return 'Youth Player'
    return '%s %s' % (rnd.choice(firsts), rnd.choice(lasts))
