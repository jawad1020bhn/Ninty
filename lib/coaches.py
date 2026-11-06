"""AI treneri: pritisak uprave, otkazi i novi treneri.

U saveu (oba formata) trener kluba stoji na dva mjesta:
  - zapis kluba +652: u32 id trenera (moj klub = 0xfffffff5),
  - blok od 56 B neposredno prije zapisa taktike kluba (TAC0 - 56 + 600 * idx):
    u32 id, ime (UTF-8, 46 B s nulama), u16 oznaka (ista kao u EDIT zapisu na +4), 4 B (obicno 50 d4 ff ff).
Imena i oznake slobodnih trenera su u EDIT datoteci (zapisi 88 B: u32 id, u16 oznaka, ffff, 0x60, ime od +9).
Sve odluke su deterministicne za (seed, klub, dan).
"""
import random
import struct

BLOCK = 56
NAME_LEN = 46


def block_off(save, idx):
    return save.TAC0 - 56 + 600 * idx


def club_coach(save, idx):
    v = struct.unpack_from('<I', save.d, 84 + 1680 * idx + 652)[0]
    return v if 0 < v < (1 << 24) else None


def read_block(save, idx):
    o = block_off(save, idx)
    return bytes(save.d[o:o + BLOCK])


def block_name(b):
    return b[4:4 + NAME_LEN].split(b'\0')[0].decode('utf-8', 'replace')


def make_block(cid, name, flag=b'\xec\x00', tail=b'\x50\xd4\xff\xff'):
    nm = name.encode('utf-8')[:NAME_LEN - 1]
    return struct.pack('<I', cid) + nm + b'\0' * (NAME_LEN - len(nm)) + flag[:2] + tail[:4]


def write_coach(save, idx, block):
    """Postavi trenera kluba: id na +652 i blok trenera. Vraca staro (id, blok)."""
    o = block_off(save, idx)
    old = (club_coach(save, idx), bytes(save.d[o:o + BLOCK]))
    cid = struct.unpack_from('<I', block, 0)[0]
    struct.pack_into('<I', save.d, 84 + 1680 * idx + 652, cid)
    save.d[o:o + BLOCK] = block
    save._allow = list(getattr(save, '_allow', [])) + [(o, o + BLOCK), (84 + 1680 * idx + 652, 84 + 1680 * idx + 656)]
    return old


def edit_coaches(edit, anchor_ids):
    """{id: dict(name, flag)} iz EDIT datoteke; sidro su id-evi trenera iz savea (ili sa slikama)."""
    d = edit

    def okrec(o):
        if o < 0 or o + 88 > len(d):
            return False
        cid = struct.unpack_from('<I', d, o)[0]
        nm = d[o + 9:o + 57].split(b'\0')[0]
        return 0 < cid < (1 << 24) and len(nm) >= 3 and all(b_ >= 32 for b_ in nm)
    best = None
    ids = set(anchor_ids)
    for pid_ in sorted(ids, reverse=True)[:400]:
        pat = struct.pack('<I', pid_)
        i = d.find(pat)
        while i >= 0:
            if okrec(i) and okrec(i + 88) and okrec(i - 88) and (struct.unpack_from('<I', d, i + 88)[0] in ids or struct.unpack_from('<I', d, i - 88)[0] in ids):
                best = i
                break
            i = d.find(pat, i + 1)
        if best is not None:
            break
    out = {}
    if best is None:
        return out
    st = best
    while okrec(st - 88):
        st -= 88
    o = st
    while okrec(o):
        cid = struct.unpack_from('<I', d, o)[0]
        out[cid] = dict(name=d[o + 9:o + 57].split(b'\0')[0].decode('utf-8', 'replace'), flag=bytes(d[o + 4:o + 6]))
        o += 88
    return out


def real_name(n):
    """Pravo ime (ne genericko PES ime velikim slovima, npr. 'ESPIMAS')."""
    return bool(n) and not n.isupper() and len(n) >= 4


# ---------------------------------------------------------------- pritisak
TIER_MULT = {'big': 1.35, 'mid': 1.0, 'small': 0.8}


def expected_positions(rows, strength):
    """rows: tablica lige; strength: {idx: snaga}. -> {idx: ocekivano mjesto}"""
    ids = [r['idx'] for r in rows if r.get('idx') is not None]
    ids.sort(key=lambda i: -strength.get(i, 60))
    return {i: k + 1 for k, i in enumerate(ids)}


def pressure(row, exp, n, form, tier, days_in_job):
    """Pritisak uprave (0 = miran posao, 1+ = otkaz moguc)."""
    pl = row.get('pl') or 0
    if pl < 5 or n < 6:
        return 0.0
    pos = row.get('pos') or n
    gap = (pos - exp) / float(n)
    ppg = row['pts'] / float(pl)
    ppg_exp = 2.3 - 1.5 * (exp - 1) / float(max(1, n - 1))
    p = 1.8 * gap + 0.7 * (ppg_exp - ppg)
    if form:
        if form.get('streak_l', 0) >= 3:
            p += 0.25
        if form.get('n', 0) >= 4 and form.get('pts', 0) <= 2:
            p += 0.2
    if pos > n - 3 and exp <= n - 5:
        p += 0.35
    p *= TIER_MULT.get(tier, 1.0)
    if pl < 8:
        p *= 0.8   # pc398: prije 0.6
    if days_in_job is not None and days_in_job < 30:
        p -= 0.3   # pc398: 'medeni mjesec' kraci i slabiji (prije 45 dana i -0.6: s 2 pobjede u 10 kola povjerenje je bilo 82)
    return round(p, 3)


def sack_chance(p):
    if p < 0.9:
        return 0.0
    return min(0.45, 0.12 + 0.15 * (p - 0.9))   # po tjednoj ocjeni: los niz od nekoliko tjedana obicno zavrsi otkazom


def end_of_season_sack(row, exp, n, tier, relegated):
    gap = ((row.get('pos') or n) - exp) / float(n)
    if relegated and exp < n - 3:
        return 0.85
    if gap >= 0.25:
        return 0.8 if tier == 'big' else 0.6
    if gap >= 0.15 and tier == 'big':
        return 0.4
    return 0.0


# ---------------------------------------------------------------- novi trener
TARGET_REP = {'big': 0.75, 'mid': 0.5, 'small': 0.3}


def pick_coach(rnd, club, candidates):
    """candidates: [dict(cid, name, rep, kind 'free'|'poach', from_idx, over)] -> izabrani ili None."""
    if not candidates:
        return None
    t = TARGET_REP.get(club.get('tier'), 0.5)
    w = []
    for c in candidates:
        x = 1.0 / (0.08 + abs(c['rep'] - t))
        if c['kind'] == 'poach':
            x *= (1.4 if c.get('over') else 0.5) * (2.0 if c.get('same_league') else 1.0)
        if not real_name(c['name']):
            x *= 0.05
        w.append(x)
    return rnd.choices(candidates, w)[0]


def seeded_rep(cid):
    return round(random.Random('rep|%s' % cid).uniform(0.35, 0.65), 3)
