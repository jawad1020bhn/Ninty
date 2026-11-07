"""posGroup: the enum used by regen_templates.json and career_createplayerattributes.

Upstream does not name these groups, so the mapping below was INFERRED from the
attribute profiles of the shipped templates. The signal is strong and unambiguous
at the ends (mean over the 6 age rows in each group of the regen templates):

  group  GK attrs  finishing  defAwareness  sprint
    0      62.4       10.0         12.3       33.5   <- only group with GK attrs
    1      10.0       28.2         62.3       60.8   <- slow, defensive: centre-back
    2      10.5       36.0         60.0       71.3   <- defensive AND fast: full-back
    3      10.0       56.0         34.7       73.5
    4       9.9       40.7         58.8       62.0   <- defensive mid
    5      10.0       48.0         50.5       64.0   <- central mid
    6      10.0       52.7         38.2       66.8
    7      10.0       54.7         34.0       72.0   <- wide/attacking mid
    8      10.2       58.0         27.8       73.7
    9       9.6       65.5         36.0       70.7
   10      10.8       63.7         24.7       69.0   <- highest finishing: striker

The goalkeeper group and the two defensive groups are certain. The exact split
between the midfield and forward groups (3, 6, 7, 8) is a judgement call, so this
is used only to CHOOSE A TEMPLATE for a generated player, never to reinterpret an
existing database player. A wrong guess there costs a slightly off-centre youth
profile, not corrupt data.
"""

# POSN role (0..12, lib/fc27.POSN) -> template posGroup
ROLE_TO_GROUP = {
    0: 0,    # GK
    1: 1,    # CB
    2: 2,    # LB
    3: 2,    # RB
    4: 4,    # DMF
    5: 5,    # CMF
    6: 7,    # LMF
    7: 7,    # RMF
    8: 6,    # AMF
    9: 8,    # LWF
    10: 8,   # RWF
    11: 9,   # SS
    12: 10,  # CF
}

GROUP_ROLE = {0: 0, 1: 1, 2: 3, 3: 8, 4: 4, 5: 5, 6: 8, 7: 7, 8: 10, 9: 11, 10: 12}


def group_for(role):
    return ROLE_TO_GROUP.get(int(role), 5)


def role_for(group):
    return GROUP_ROLE.get(int(group), 5)
