"""pitch.py - pure position geometry and assignment maths.

Extracted VERBATIM from the project's original assignment code so the engine
imports a 6,109-line save-file writer to use two pure functions. Nothing here
reads a file, knows a save format, or touches any game but its own: it is plain
arithmetic over the 13-role position enum.

    POS         role name -> index (GK 0 .. CF 12)
    DIST        13x13 all-pairs cost of playing a role out of position
    hungarian   min-cost assignment (n x m, n <= m) -> column per row
    plan_label  role codes -> a formation label like "4-2-3-1"

The role order is shared with lib/fc27.py POSN and lib/ailineup.py, so these
helpers run on FC 27 data unchanged. The extraction is covered by
tools/verify_engine.py, which asserts the engine imports no save machinery.
"""

POS = dict(GK=0, CB=1, LB=2, RB=3, DMF=4, CMF=5, LMF=6, RMF=7, AMF=8, LWF=9, RWF=10, SS=11, CF=12)


def _dist():
    n = 13
    INF = 99
    D = [[INF] * n for _ in range(n)]
    for i in range(n):
        D[i][i] = 0
    E = [('CB','LB',2),('CB','RB',2),('LB','RB',3),('CB','DMF',3),('LB','LMF',2),('RB','RMF',2),
         ('DMF','CMF',1),('CMF','AMF',1),('CMF','LMF',2),('CMF','RMF',2),('LMF','RMF',3),
         ('LMF','LWF',1),('RMF','RWF',1),('AMF','SS',1),('AMF','LWF',2),('AMF','RWF',2),
         ('SS','CF',1),('CF','LWF',2),('CF','RWF',2),('LWF','RWF',3),('DMF','LB',4),('DMF','RB',4)]
    for a, b, w in E:
        D[POS[a]][POS[b]] = D[POS[b]][POS[a]] = w
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if D[i][k] + D[k][j] < D[i][j]:
                    D[i][j] = D[i][k] + D[k][j]
    for i in range(1, n):
        D[0][i] = D[i][0] = 60   # golman samo na gol
    return D

DIST = _dist()


def hungarian(cost):
    """min-cost assignment, cost: n x m (n<=m). Vraca listu stupaca po retku."""
    n, m = len(cost), len(cost[0])
    INF = float('inf')
    u = [0] * (n + 1); v = [0] * (m + 1); p = [0] * (m + 1); way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i; j0 = 0
        minv = [INF] * (m + 1); used = [False] * (m + 1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = INF; j1 = 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur; way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]; j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta; v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0:
                break
    res = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            res[p[j] - 1] = j - 1
    return res


def plan_label(roles):
    """Oznaka formacije kao u igri (npr. 4-2-1-3, 4-2-3-1, 4-4-2) iz kodova uloga:
    1 CB, 2 LB, 3 RB, 4 DMF, 5 CMF, 6 LMF, 7 RMF, 8 AMF, 9 LWF, 10 RWF, 11 SS, 12 CF."""
    c = lambda *rs: sum(1 for r in roles if r in rs)
    df, dm, cm, wm, am, ss, fw = c(1, 2, 3), c(4), c(5), c(6, 7), c(8), c(11), c(9, 10, 12)
    parts = [df]
    if am:
        parts += [dm + cm, am + wm]
    elif dm == 1 and cm + wm == 4:
        parts += [1, 4]
    else:
        parts += [dm + cm + wm]
    parts += [ss, fw]
    return '-'.join(str(x) for x in parts if x)
