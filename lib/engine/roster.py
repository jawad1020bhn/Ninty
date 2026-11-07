"""Save-aware player facts.

A career contains two kinds of player: real ones from the FC 27 database, and
generated ones (youth intake, regens) whose ids live far above the real id space
and exist only in the save. Calling fc27.positions()/name()/ratings() directly
silently returns a default for the generated ones - which is how a goalkeeper
created by the youth intake became invisible to the "does this club have a
keeper?" test and span a loop forever.

Every engine module resolves player facts through HERE, so a generated player is
a first-class citizen. The database is still the source of truth for real ones;
this layer only adds the save's own players and its attribute overlay.

The EA->25-attribute projection below mirrors tools/import_fc27.mjs exactly, including the
TightPossession blend, so a generated player's 25-attribute row is computed the
same way as a real one's.
"""

import fc27

from . import store as S

# Same order and sources as the importer's AB / AB_SRC.
AB25 = ['OffensiveAwareness', 'BallControl', 'Dribbling', 'TightPossession', 'LowPass',
          'LoftedPass', 'Finishing', 'Heading', 'PlaceKicking', 'Curl', 'Speed',
          'Acceleration', 'KickingPower', 'Jump', 'PhysicalContact', 'Balance',
          'Stamina', 'DefensiveAwareness', 'BallWinning', 'Aggression', 'GKAwareness',
          'GKCatching', 'GKClearing', 'GKReflexes', 'GKReach']
AB_SRC = ['positioning', 'ballcontrol', 'dribbling', '@tight', 'shortpassing',
          'longpassing', 'finishing', 'headingaccuracy', 'freekickaccuracy', 'curve',
          'sprintspeed', 'acceleration', 'shotpower', 'jumping', 'strength', 'balance',
          'stamina', 'defensiveawareness', 'standingtackle', 'aggression',
          'gkpositioning', 'gkhandling', 'gkkicking', 'gkreflexes', 'gkdiving']


def _clamp(v, lo=1, hi=99):
    return max(lo, min(hi, int(round(v))))


def project_ab25(ea):
    """EA attribute dict -> the 25 legacy values, exactly as the importer does."""
    out = []
    for k in AB_SRC:
        if k == '@tight':
            out.append(_clamp((_clamp(ea.get('ballcontrol', 0)) * 2 +
                               _clamp(ea.get('dribbling', 0)) +
                               _clamp(ea.get('agility', 0))) / 4.0))
        else:
            out.append(_clamp(ea.get(k, 0)))
    return out


# --- compact save codecs -------------------------------------------------
# A career develops ~19,000 players a season. Storing each one's progress as a
# dict of 25 legacy attribute NAMES cost 5.92 MB after one season and 7.12 MB after
# three. The names are identical for every player and already fixed by AB25,
# so the save stores a positional list instead: 2.49 MB for the same data.
# Decoders accept both shapes, so an older save still loads.

def decode_named(stored, names):
    """Positional list (or legacy name->value dict) -> name->value dict."""
    if not stored:
        return {}
    if isinstance(stored, dict):
        return dict(stored)
    return {n: stored[i] for i, n in enumerate(names)
            if i < len(stored) and stored[i]}


def encode_named(d, names, ndigits=None):
    """name->value dict -> positional list. Returns None if nothing to store."""
    out = []
    for n in names:
        v = d.get(n, 0) or 0
        out.append(round(float(v), ndigits) if ndigits is not None else int(v))
    return out if any(out) else None


def prog_of(st, pid):
    """A player's carried sub-point growth progress, as attr->float."""
    return decode_named((st.get('growthProg') or {}).get(str(int(pid))), AB25)


def set_prog(st, pid, prog):
    """Store growth progress compactly; drop the row entirely when empty."""
    tbl = st.setdefault('growthProg', {})
    enc = encode_named(prog, AB25, ndigits=3)
    if enc is None:
        tbl.pop(str(int(pid)), None)
    else:
        tbl[str(int(pid))] = enc


def overlay_of(st, pid):
    """A player's accumulated attribute deltas, as legacy attr->int."""
    return decode_named((st.get('attrOverlay') or {}).get(str(int(pid))), AB25)


def set_overlay(st, pid, ov):
    tbl = st.setdefault('attrOverlay', {})
    enc = encode_named({k: v for k, v in ov.items() if v}, AB25)
    if enc is None:
        tbl.pop(str(int(pid)), None)
    else:
        tbl[str(int(pid))] = enc


def ea_of(st, pid):
    """A generated player's 34 base EA attributes as name->value.

    Stored positionally in fc27.ea_ab() order for the same reason as above:
    1.25 MB -> 0.24 MB for one intake.
    """
    g = generated(st, pid)
    if not g:
        return {}
    return decode_named(g.get('ea'), fc27.ea_ab())


def generated(st, pid):
    return (st.get('generated') or {}).get(str(int(pid)))


def is_generated(st, pid):
    return generated(st, pid) is not None


def exists(st, pid):
    return S.pstate(st, pid) is not None


def name(st, pid):
    g = generated(st, pid)
    if g:
        return g['name']
    return fc27.name(int(pid))


def pos(st, pid):
    """POSN role 0..12. Generated players carry their role in the save."""
    g = generated(st, pid)
    if g:
        return int(g['role'])
    return int(fc27.positions().get(str(int(pid)), 5))


def born(st, pid):
    g = generated(st, pid)
    if g:
        return g.get('born', '')
    return fc27.birthdays().get(str(int(pid)), '')


def age(st, pid, date=None):
    """Age at an in-game date (defaults to the career's current date)."""
    bd = born(st, pid)
    date = str(date or st.get('date') or '')[:10]
    if not bd or not date:
        g = generated(st, pid)
        if g:
            return int(g.get('age', 18))
        r = fc27.ratings().get(str(int(pid)))
        return r[1] if r else 25
    try:
        y, m, d = (int(x) for x in bd.split('-'))
        ry, rm, rd = (int(x) for x in date.split('-'))
    except (ValueError, AttributeError):
        return 25
    n = ry - y
    if (rm, rd) < (m, d):
        n -= 1
    return max(15, n)


def ovr(st, pid):
    r = S.pstate(st, pid)
    return int(r[S.P_OVR]) if r else 0


def potential(st, pid):
    g = generated(st, pid)
    if g:
        return int((st.get('potentials') or {}).get(str(int(pid))) or g.get('potential', 80))
    return int(fc27.potential().get(str(int(pid))) or ovr(st, pid))


def ea_attrs(st, pid):
    """EA's 34 raw attributes as a name->value dict, including career growth.

    For real players the base is the database; the save's overlay is expressed
    in legacy attribute names (that is what lib/growth produces), so it is mapped
    back onto the EA fields that project to them.
    """
    g = generated(st, pid)
    base = ea_of(st, pid) if g else dict(fc27.ea_attrs(int(pid)))
    if not base:
        base = {k: 50 for k in fc27.ea_ab()}
    ov = overlay_of(st, pid)
    if ov:
        for i, pes_name in enumerate(AB25):
            d = int(ov.get(pes_name, 0))
            if not d:
                continue
            src = AB_SRC[i]
            if src == '@tight':
                for k in ('ballcontrol', 'dribbling', 'agility'):
                    base[k] = _clamp(base.get(k, 50) + d)
            else:
                base[src] = _clamp(base.get(src, 50) + d)
    return base


def ab25_attrs(st, pid):
    """The legacy 25 attributes as name->value, with career growth applied."""
    g = generated(st, pid)
    if g:
        vals = project_ab25(ea_of(st, pid))
    else:
        row = fc27.ratings().get(str(int(pid)))
        vals = list(row[10]) if row else [50] * 25
    ov = overlay_of(st, pid)
    return {n: max(1, min(99, vals[i] + int(ov.get(n, 0))))
            for i, n in enumerate(AB25)}


def base_ovr(st, pid):
    """The player's database OVR, for measuring career development against."""
    g = generated(st, pid)
    if g:
        return int(g.get('startOvr', ovr(st, pid)))
    r = fc27.ratings().get(str(int(pid)))
    return int(r[0]) if r else ovr(st, pid)
