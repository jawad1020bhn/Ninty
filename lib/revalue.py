"""Revalorizacija tvojih igraca na kraju sezone (pc197).

Formula i konstante: Michele & Claude, "Economia Lunga - rivalutazione" (FL26 Master League Realism Mods), uz dopustenje.
  regularnost = nastupi / utakmice momcadi (najvise 1)
  zasluga = 1 + (prosjecna ocjena - 6,00) x 0,80 x regularnost
              + bodovi / 17 (najvise +1,50)          bodovi = golovi + 0,5 x asistencije
              + 0,20 x regularnost
              - malus klupe (do 22 god. 0, 23-27: 0,15, 28+: 0,30) x (1 - regularnost)
  zasluga je izmedju 0,65 i 2,50
  nova vrijednost = trenutna x zasluga
  pojas: ne smije se udaljiti iznad fer vrijednosti x 4 (ako je vec bio iznad, ne raste dalje); dolje nema pojasa,
         pod je 12.000 EUR; strop polja u saveu je 21 bit (209,7 M EUR).
Vrijednost u saveu: zapis igraca +132, u jedinicama 100 EUR (donjih 21 bit).
"""
VOTO_NEUTRO = 6.00
PESO_VOTO = 0.80
PUNTI_RADDOPPIO = 17.0
PREMIO_GOL_MAX = 1.50
BONUS_REGOLARE = 0.20
MERITO_MIN, MERITO_MAX = 0.65, 2.50
SCARTO_MAX = 4.00
MURO = 120            # 12.000 EUR (jedinice 100 EUR)
TETTO = 0x1FFFFF      # 21 bit
PARTITE_MINIME = 20

# Micheleova krivulja (jedinice 100 EUR) kad nemamo bazu iz igre (bez F7 dumpa)
BASE = {40: 9, 41: 11, 42: 13, 43: 17, 44: 21, 45: 26, 46: 33, 47: 41, 48: 51, 49: 64, 50: 80, 51: 100, 52: 125, 53: 156, 54: 195,
        55: 244, 56: 305, 57: 381, 58: 476, 59: 595, 60: 744, 61: 930, 62: 1162, 63: 1453, 64: 1816, 65: 2270, 66: 2838, 67: 3547,
        68: 4434, 69: 5543, 70: 6928, 71: 8110, 72: 11012, 73: 15544, 74: 22785, 75: 34020, 76: 51440, 77: 77951, 78: 112331,
        79: 156004, 80: 202873, 81: 253425, 82: 317960, 83: 400010, 84: 517900, 85: 627064, 86: 763193, 87: 924445, 88: 1004686,
        89: 1291327, 90: 1699406}
ETA = {20: 2.33, 21: 2.33, 22: 2.00, 23: 1.60, 24: 1.20, 25: 1.00, 26: 0.89, 27: 0.78, 28: 0.72, 29: 0.67, 30: 0.56, 31: 0.45,
       32: 0.36, 33: 0.32, 34: 0.26, 35: 0.20, 36: 0.20, 37: 0.20, 38: 0.16, 39: 0.11, 40: 0.13}


def bench_malus(age):
    if not age or age <= 22:
        return 0.0
    return 0.15 if age <= 27 else 0.30


def fair_units(ovr, age, fair_eur=None):
    if fair_eur:
        return max(MURO, min(TETTO, int(round(fair_eur / 100.0))))
    b = BASE.get(max(40, min(90, ovr or 50)), TETTO)
    e = ETA.get(age, 2.33 if (age or 25) < 20 else 0.10)
    return max(MURO, min(TETTO, int(round(b * e))))


def merit(app, team_matches, rating_sum, goals, assists, age):
    reg = min(1.0, app / float(team_matches)) if team_matches else 0.0
    vote = rating_sum / app if app else None
    pv = (vote - VOTO_NEUTRO) * PESO_VOTO * reg if vote is not None else 0.0
    pg = min(PREMIO_GOL_MAX, (goals + 0.5 * assists) / PUNTI_RADDOPPIO)
    m = 1 + pv + pg + BONUS_REGOLARE * reg - bench_malus(age) * (1 - reg)
    return max(MERITO_MIN, min(MERITO_MAX, m)), vote, reg


def new_value(cur, mer, fair):
    """cur, fair u jedinicama 100 EUR."""
    nv = cur * mer
    cap = fair * SCARTO_MAX
    if cur > cap:
        cap = cur            # vec je bio iznad pojasa: ne spustamo ga, samo ne raste dalje
    nv = min(nv, cap)
    step = 1000 if nv >= 10000 else 100 if nv >= 1000 else 10   # okrugli iznosi kao u igri (100.000 / 10.000 / 1.000 EUR)
    nv = round(nv / float(step)) * step
    return int(max(MURO, min(TETTO, nv)))
