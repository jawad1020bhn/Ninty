"""Bridge between EA's 28-id position enum and the app's 13-role POSN space.

The existing algorithms (ailineup, pitch.DIST, formengine) all speak the
13-role POSN space: GK CB LB RB DMF CMF LMF RMF AMF LWF RWF SS CF.  The FC 27
data speaks EA's 28-id enum, which is finer (RCB/LCB, RDM/CDM/LDM, RS/ST/LS).

Two different collapses are needed and they are NOT the same map:

  slot_role()  formation slot -> tactical role.  A slot is a place on the pitch,
               so side matters: 4 RCB and 6 LCB are both CB, but 2 RWB is a
               right-back and 8 LWB a left-back.
  player_role() is NOT needed: fc27.positions() already gives the coarse POSN
               index per player, produced by the importer.

Formation slots also need fc27.slot_compat() when compared against a player's
EA ids - see lib/fc27.py.  This module deals only with the POSN bridge.
"""

# EA enum -> POSN index.  Total over all 28 ids, including the ones no club
# formation currently uses (1 SW, 20 RF, 21 CF, 22 LF), so a custom formation
# cannot fall off the end.
EA_TO_POSN = {
    0: 0,    # GK   -> GK
    1: 1,    # SW   -> CB
    2: 3,    # RWB  -> RB
    3: 3,    # RB   -> RB
    4: 1,    # RCB  -> CB
    5: 1,    # CB   -> CB
    6: 1,    # LCB  -> CB
    7: 2,    # LB   -> LB
    8: 2,    # LWB  -> LB
    9: 4,    # RDM  -> DMF
    10: 4,   # CDM  -> DMF
    11: 4,   # LDM  -> DMF
    12: 7,   # RM   -> RMF
    13: 5,   # RCM  -> CMF
    14: 5,   # CM   -> CMF
    15: 5,   # LCM  -> CMF
    16: 6,   # LM   -> LMF
    17: 8,   # RAM  -> AMF
    18: 8,   # CAM  -> AMF
    19: 8,   # LAM  -> AMF
    20: 11,  # RF   -> SS
    21: 12,  # CF   -> CF
    22: 11,  # LF   -> SS
    23: 10,  # RW   -> RWF
    24: 12,  # RS   -> CF
    25: 12,  # ST   -> CF
    26: 12,  # LS   -> CF
    27: 9,   # LW   -> LWF
}


def slot_role(slot):
    """Formation slot id -> POSN role index. Unknown ids fall back to CMF."""
    return EA_TO_POSN.get(int(slot), 5)


def formation_roles(pos):
    """A formation's 11 EA slot ids -> 11 POSN roles, order preserved.

    ailineup.pick_xi expects roles[0] to be the goalkeeper; every shipped club
    formation starts at slot 0, and this asserts that rather than silently
    producing a lineup with an outfielder in goal.
    """
    roles = [slot_role(s) for s in pos]
    if roles and roles[0] != 0:
        raise ValueError('formation does not start with a goalkeeper: %r' % (pos,))
    return roles


def line_of(role):
    """POSN role -> 0 GK, 1 defence, 2 midfield, 3 attack.

    Same grouping lib/formengine.grp uses, expressed as a number so the match
    engine can weight units without importing that module's string codes.
    """
    r = int(role)
    if r == 0:
        return 0
    if r in (1, 2, 3):
        return 1
    if r in (4, 5, 6, 7, 8):
        return 2
    return 3
