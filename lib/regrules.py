"""Pravila registracije igraca po ligama (pc195).

Pravila i popis EU drzava: Michele & Claude, "Regole di tesseramento" (FL26 Master League Realism Mods), uz njihovo dopustenje.
  Serie A           lista 25 igraca starijih od 21; najvise 2 nova igraca izvan EU iz inozemstva po prijelaznom roku
  Serie B           lista 25; najvise 1 novi igrac izvan EU iz inozemstva
  Serie C           lista 25; nijedan novi igrac izvan EU iz inozemstva
  LaLiga, LaLiga 2  lista 25; najvise 3 igraca izvan EU u momcadi
  Ligue 1, Ligue 2  najvise 4 igraca izvan EU u momcadi
  Premier League    lista 25
Igraci do 21 godine su uvijek slobodni; prodaja je uvijek dopustena. EU = Europska unija + Svicarska, Norveska, Island,
Lihtenstajn; Englezi, Skoti i Velsani su izvan EU. Igra zna samo jednu nacionalnost po igracu (nema dvojnog drzavljanstva).
Nacionalnost = u16 na +0x144 zivog zapisa igraca (PlayerDump), id drzave kao u igri.
"""

EU = {194, 197, 199, 200, 201, 202, 203, 205, 207, 208, 210, 211, 212, 214, 215, 217, 219, 220, 222, 224, 227, 228, 229, 234, 235,
      236, 237, 213, 218, 226, 238}
FREE_AGE = 21
RULES = {
    18: dict(name='Serie A', lista=25, new_extra=2),
    82: dict(name='Serie B', lista=25, new_extra=1),
    74: dict(name='Serie C', lista=25, new_extra=0),
    19: dict(name='LaLiga', lista=25, extra=3),
    80: dict(name='LaLiga 2', lista=25, extra=3),
    116: dict(name='Ligue 1', extra=4),
    62: dict(name='Ligue 2', extra=4),
    17: dict(name='Premier League', lista=25),
}
DOMESTIC = {18: 'IT', 82: 'IT', 74: 'IT', 19: 'ES', 80: 'ES', 116: 'FR', 62: 'FR', 17: 'EN', 79: 'EN'}
# pc264: Football Life 2027 (drugi brojevi liga: Ligue 1 = 20, Ligue 2 = 81; Serie C u FL27 rasporedu jos nije nadjena)
RULES_FL27 = {
    18: dict(name='Serie A', lista=25, new_extra=2),
    82: dict(name='Serie B', lista=25, new_extra=1),
    19: dict(name='LaLiga', lista=25, extra=3),
    80: dict(name='LaLiga 2', lista=25, extra=3),
    20: dict(name='Ligue 1', extra=4),
    81: dict(name='Ligue 2', extra=4),
    17: dict(name='Premier League', lista=25),
}
DOMESTIC_FL27 = {18: 'IT', 82: 'IT', 19: 'ES', 80: 'ES', 20: 'FR', 81: 'FR', 17: 'EN', 79: 'EN'}

# --- EA SPORTS FC 27 -------------------------------------------------------
# FC 27 reuses small league ids that mean DIFFERENT competitions in PES:
# 17 is Ligue 2 here but Premier League in FL26, 19 is 1. Bundesliga, etc.
# These ids were read out of data/fc27/leagues.json, never guessed.
# The real-world rules are the ones documented at the top of this file.
RULES_FC27 = {
    31: dict(name='Serie A', lista=25, new_extra=2),
    32: dict(name='Serie B', lista=25, new_extra=1),
    53: dict(name='LaLiga', lista=25, extra=3),
    54: dict(name='LaLiga 2', lista=25, extra=3),
    16: dict(name='Ligue 1', extra=4),
    17: dict(name='Ligue 2', extra=4),
    13: dict(name='Premier League', lista=25),
}
DOMESTIC_FC27 = {31: 'IT', 32: 'IT', 53: 'ES', 54: 'ES', 16: 'FR', 17: 'FR',
                 13: 'EN', 14: 'EN', 60: 'EN', 61: 'EN', 19: 'DE', 20: 'DE', 2076: 'DE'}

# FC 27 nationality ids are EA's, not PES's (PES uses 194-238 for Europe;
# FC 27 uses 4 Austria / 18 France / 21 Germany / 27 Italy / 45 Spain).
# Same membership as EU above: EU + Switzerland, Norway, Iceland and
# Liechtenstein; England, Scotland and Wales are outside it.
# Derived from data/fc27/nations.json by ISO code, not hand-copied.
EU_FC27 = {4, 7, 9, 10, 11, 12, 13, 17, 18, 21, 22, 23, 24, 25, 27, 28, 29,
           30, 31, 32, 34, 36, 37, 38, 39, 43, 44, 45, 46, 47, 208}
EU_PES = set(EU)   # kept so a game switch can restore the PES set


def non_eu(nat):
    # FC 27 ids are all < 512, so the mask is identity there; PES packs flag
    # bits above bit 8, which is why the mask exists at all.
    return nat is not None and (nat & 0x1ff) not in EU


def check(tid, squad, inc, from_tid=None):
    """tid: liga kupca; squad: [dict(pid, age, nat, new)] trenutna momcad (new = dosao u ovom roku);
    inc: dict(pid, age, nat) igrac koji dolazi; from_tid: liga kluba iz kojeg dolazi (None = nepoznato ili slobodan).
    -> None ako je dopusteno, inace razlog (engleski tekst za korisnika)."""
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
        return None   # nacionalnost nepoznata (nema dumpa): ostala pravila se ne mogu provjeriti
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
