"""dbimport.py - alat "Uvoz baze": iz zivog dumpa igraca (F7), save-a i EDIT datoteke slozi staticke podatke appa
(players.json, ratings.json, positions.json, playpos.json, teamids.json, comps.json) za novu bazu igraca.

Polja bloka igraca (0x17C = 380 B) potvrdjena na FL26 bazi (usporedba s postojecim datotekama, 25k igraca):
  +0x00 visina (8 b), +0x01 tezina (8 b), +0x03 bit 7 noga (1 = lijeva), +0x07 bitovi 4-7 glavna pozicija,
  +0x17 bitovi 4-6 forma (stat 1-8, +1), +0x1C & 63 dob, +0x1D bitovi 3-7 stil igre, +0x22 bitovi 4-5 preciznost slabije noge (+1),
  +0x22 bitovi 6-7 otpornost na ozljede (+1), +0x23 bitovi 0-1 koristenje slabije noge (+1), +0x30 id, +0x38 ime, +0x75 ime na dresu,
  +0x144 & 0x1ff nacionalnost, bitovi 249-274 igrive pozicije (0/1/2), atributi po growth.FIELDS.
OVR: linearni model po glavnoj poziciji (25 atributa + forma) naucen na FL26 bazi (lib/ovr_weights.json): ~68% tocno, ~99.6% unutar +-1.
"""
import json
import os
import re
import struct

import growth

BLOCK = 380
AB = ['OffensiveAwareness', 'BallControl', 'Dribbling', 'TightPossession', 'LowPass', 'LoftedPass', 'Finishing', 'Heading', 'PlaceKicking', 'Curl',
      'Speed', 'Acceleration', 'KickingPower', 'Jump', 'PhysicalContact', 'Balance', 'Stamina', 'DefensiveAwareness', 'BallWinning', 'Aggression',
      'GKAwareness', 'GKCatching', 'GKClearing', 'GKReflexes', 'GKReach']
PP_BITS = (274, 268, 270, 272, 260, 262, 264, 266, 258, 253, 256, 251, 249)
HERE = os.path.dirname(os.path.abspath(__file__))
_W = None


def _weights():
    global _W
    if _W is None:
        try:
            _W = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'ovr_weights.json'))).items()}
        except Exception:
            _W = {}
    return _W


def _bits(b, byte, bit, n):
    return (int.from_bytes(b[byte:byte + 2], 'little') >> bit) & ((1 << n) - 1)


def ovr_of(att, pos, form):
    w = _weights().get(pos)
    if not w:
        return min(99, round(sum(att) / len(att)))
    x = att + [1.0 if i == form else 0.0 for i in range(9)] + [1.0]
    return max(1, min(99, int(round(sum(a * b for a, b in zip(x, w))))))   # pc380: najvise 99 (FL Mod Studio baza davala 100-102)


# pc268: Football Life 2027 ima atribute po eFootball skali (Haaland 89 u igri, iz atributa bi bilo 101): uzmi OVR koji
# racuna sama igra (+0x179 zivog zapisa). Server ukljucuje za FL27; FL26 ostaje izracun iz atributa (kao do sada).
USE_GAME_OVR = False


# pc289: FL27 drzi spremljeni OVR (+0x179) iz baze i NE mijenja ga kad igracu narastu atributi (rast u igri ili iz appa),
# a igra prikazuje novi OVR. Zivi OVR = spremljeni + promjena procjene iz atributa (sada naspram baze igre).
# Baza = players_base.bin (PlayerDump 2.1 zapise osnovnu kopiju tablice igraca). Tezine: linearni fit na FL27 (lib/ovr_weights_fl27.json).
BASE_PATH = None
_B27 = dict(mt=None, attrs={}, w=None)


def _base27():
    p = BASE_PATH
    if not p or not os.path.exists(p):
        return {}
    mt = os.path.getmtime(p)
    if _B27['mt'] != mt:
        raw = open(p, 'rb').read()
        att = {}
        for i in range(len(raw) // BLOCK):
            blk = raw[i * BLOCK:(i + 1) * BLOCK]
            pid = struct.unpack_from('<I', blk, 0x30)[0]
            if pid and pid not in att:
                a = growth.attrs_from_block(blk)
                att[pid] = [a[k] for k in AB]
        _B27.update(mt=mt, attrs=att)
    return _B27['attrs']


def _w27():
    if _B27['w'] is None:
        try:
            _B27['w'] = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'ovr_weights_fl27.json'))).items()}
        except Exception:
            _B27['w'] = {}
    return _B27['w']


def game_ovr(b):
    """OVR iz igre za blok dumpa (0 ako ga nema). Na FL27 s osnovnom tablicom: spremljeni + promjena iz atributa (prema nuli)."""
    go = b[0x179]
    if not (40 <= go <= 99) or not USE_GAME_OVR:
        return go
    try:
        base = _base27()
        if not base:
            return go
        pid = struct.unpack_from('<I', b, 0x30)[0]
        a0 = base.get(pid)
        pos = min(12, (b[7] >> 4) & 15)
        w = _w27().get(pos)
        if not a0 or not w:
            return go
        a = growth.attrs_from_block(b)
        a1 = [a[k] for k in AB]
        if a1 == a0:
            return go
        dl = sum((x - y) * k for x, y, k in zip(a1, a0, w))
        return max(40, min(99, go + int(dl)))
    except Exception:
        return go


def player_from_block(b):
    pid = struct.unpack_from('<I', b, 0x30)[0]
    if not pid:
        return None
    nm = b[0x38:0x75].split(b'\0')[0].decode('utf-8', 'replace').strip()
    if not nm:
        return None
    a = growth.attrs_from_block(b)
    att = [a[k] for k in AB]
    pos = (b[7] >> 4) & 15
    if pos > 12:
        pos = 12
    form = _bits(b, 0x17, 4, 3) + 1
    v = int.from_bytes(b[30:40], 'little')
    return dict(id=pid, name=nm, shirt=b[0x75:0xB2].split(b'\0')[0].decode('utf-8', 'replace').strip(), nat=struct.unpack_from('<H', b, 0x144)[0] & 0x1ff,
                age=b[0x1C] & 63, h=b[0], w=b[1], foot=bool(b[3] >> 7), style=_bits(b, 0x1D, 3, 5), wfu=_bits(b, 0x23, 0, 2) + 1, wfa=_bits(b, 0x22, 4, 2) + 1,
                form=form, inj=_bits(b, 0x22, 6, 2) + 1, pos=pos, pp=''.join(str((v >> (l - 240)) & 3) for l in PP_BITS), attrs=att,
                ovr=(game_ovr(b) if 40 <= b[0x179] <= 99 else ovr_of(att, pos, form)))   # pc380: i na FL26 OVR koji prikazuje igra (baze s drugacijim atributima, npr. FL Mod Studio, davale su 100+)


def players_from_dump(raw):
    out = {}
    for i in range(len(raw) // BLOCK):
        p = player_from_block(raw[i * BLOCK:(i + 1) * BLOCK])
        if p and p['id'] not in out:
            out[p['id']] = p
    return out


def teams_from_edit(d):
    """{team_id: ime} iz dekriptirane EDIT datoteke: niz zapisa od 0x24C B, u32 id na +0, ime na +0x68."""
    ST, NO = 0x24C, 0x68

    def ok(o):
        if o < 0 or o + NO + 4 > len(d):
            return False
        tid = struct.unpack_from('<I', d, o)[0]
        if not (1 <= tid < 300000):
            return False
        s = d[o + NO:o + NO + 0x46].split(b'\0')[0]
        if len(s) < 2:
            return False
        try:
            t = s.decode('utf-8')
        except UnicodeDecodeError:
            return False
        return t.isprintable()
    best = (0, 0)
    for m in re.finditer(rb'[A-Z][\x20-\x7e\xc0-\xff]{2,40}\x00', d):
        o = m.start() - NO
        if o % 4 or not ok(o) or not ok(o + ST):
            continue
        s0 = o
        while ok(s0 - ST):
            s0 -= ST
        n, e = 0, s0
        while ok(e):
            n += 1
            e += ST
        if n > best[1]:
            best = (s0, n)
        if n > 300:
            break
    out = {}
    s0, n = best
    for k in range(n):
        o = s0 + k * ST
        out[struct.unpack_from('<I', d, o)[0]] = d[o + NO:o + NO + 0x46].split(b'\0')[0].decode('utf-8')
    return out


def leagues_from_matches(matches, club_name):
    """Natjecanja koja izgledaju kao liga (dvokruzno, >= 8 klubova) iz utakmica save-a: {tid: dict(clubs=[...], n=broj klubova, played)}."""
    by = {}
    for m in matches:
        t = by.setdefault(m['tid'], dict(cnt={}, ms=0, pl=0))
        t['ms'] += 1
        t['pl'] += 1 if m.get('played') else 0
        for c in (m['home'], m['away']):
            t['cnt'][c] = t['cnt'].get(c, 0) + 1
    out = {}
    for tid, t in by.items():
        if not t['cnt']:
            continue
        mx = max(t['cnt'].values())
        clubs = [c for c, n in t['cnt'].items() if n >= max(2, mx * 0.5) and c < 4000]
        n = len(clubs)
        if n >= 8 and t['ms'] >= n * (n - 1) * 0.6:
            out[tid] = dict(clubs=sorted(club_name(c) for c in clubs), n=n, played=t['pl'], kind='league', maxg=mx)
        elif n >= 16 and mx <= 8:
            out[tid] = dict(clubs=sorted(club_name(c) for c in clubs), n=n, played=t['pl'], kind='groups', maxg=mx)
    return out


def build(raw_dump, edit_data=None, old_players=None, old_ratings=None):
    """-> dict datoteka (players, ratings, positions, playpos, teamids) i statistika."""
    P = players_from_dump(raw_dump)
    full = {}
    for p in (old_players or []):
        full[p[0]] = (p[1], p[2])
    players, ratings, positions, playpos, nats = [], {}, {}, {}, {}
    regens = 0
    for pid, p in sorted(P.items()):
        o = (old_ratings or {}).get(str(pid))
        if o and p['age'] <= 17 and o[1] >= p['age'] + 3:
            regens += 1                 # regen (umirovljeni igrac na istom ID-u): ne dira se, app ga vodi iz dumpa
            continue
        f = full.get(pid)
        # puno ime: iz stare baze ako je isti igrac (isto kratko ime), inace ime iz igre
        fn = f[0] if f and f[1] == p['name'] else p['name']
        players.append([pid, fn, p['name']])
        ratings[str(pid)] = [p['ovr'], p['age'], p['h'], p['w'], 'True' if p['foot'] else 'False', p['style'], p['wfu'], p['wfa'], p['form'], p['inj'], p['attrs']]
        positions[str(pid)] = p['pos']
        playpos[str(pid)] = p['pp']
        nats[pid] = p['nat']
    teams = teams_from_edit(edit_data) if edit_data else {}
    return dict(players=players, ratings=dict(ab=AB, f='o,age,h,w,foot,style,wfu,wfa,form,inj,stats', p=ratings), positions=positions, playpos=playpos,
                teamids={str(k): v for k, v in sorted(teams.items())}, n_players=len(players), n_teams=len(teams), regens=regens, nats=nats)
