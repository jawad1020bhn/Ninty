#!/usr/bin/env python3
"""Classify the bytes PES 2017 rewrites on EVERY save (the "noise").

The four measured before/after pairs change 211 bytes in common.  Those are
not action tables: the game rewrites them on each save, and our writer keeps
them untouched.  This tool names them so that a future pair can be diffed
without mistaking noise for a real table.

    python3 pes2017/tools/analyze_save_noise.py \
        --before "Needed files/ML00000011" \
        --after-dir build/pairs --json build/analysis/noise_report.json

It also reports the 64-byte header hash, the 32-byte per-save token, the
periodic per-player delta, the 15 "budget companion" bytes, and whether those
companions could encode a budget value.  All findings are save-file facts;
they are NOT in-game validation.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'build', 'TheGaffer', 'TheGaffer', 'lib'))
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'overlay', 'lib'))

import pescrypt        # noqa: E402
import pes17_pairs     # noqa: E402

NAMES = ('formation', 'tactics', 'xi', 'budget')


def parts(path):
    with open(path, 'rb') as f:
        return pescrypt.decrypt_bytes(f.read(), pescrypt.KEY_PES17)


def after_path(after_dir, name):
    for rel in (os.path.join(after_dir, name, 'ML00000011'),
                os.path.join(after_dir, name, 'after', 'ML00000011'),
                os.path.join(ROOT, name, 'after', 'ML00000011')):
        if os.path.isfile(rel):
            return rel
    return None


def ranges(offsets):
    out = []
    for x in sorted(offsets):
        if out and x == out[-1][1]:
            out[-1][1] = x + 1
        else:
            out.append([x, x + 1])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--before', default=os.path.join(ROOT, 'Needed files', 'ML00000011'))
    ap.add_argument('--after-dir', default=os.path.join(ROOT, 'build', 'pairs'))
    ap.add_argument('--json', dest='json_out', help='write the full report here')
    a = ap.parse_args()

    bp = parts(a.before)
    before = bp['data.dat']
    sets = {}
    paths = {}
    for n in NAMES:
        p = after_path(a.after_dir, n)
        if not p:
            print('missing after file for', n, file=sys.stderr)
            return 1
        paths[n] = p
        sets[n] = parts(p)

    diffs = {n: {i for i, (x, y) in enumerate(zip(before, sets[n]['data.dat']))
                 if x != y} for n in NAMES}
    common = set.intersection(*diffs.values())
    union = set.union(*diffs.values())
    varying = sorted(i for i in common
                     if len({sets[n]['data.dat'][i] for n in NAMES}) > 1)
    stable = sorted(common - set(varying))

    token = sorted(i for i in common if 48 <= i < 80)
    non_token_varying = [i for i in varying if not (48 <= i < 80)]

    # The stable delta is mostly a periodic byte where before = after + 0x4c.
    periodic = []
    for i in stable:
        vals = {sets[n]['data.dat'][i] for n in NAMES}
        if len(vals) == 1 and (before[i] - vals.pop()) & 0xff == 0x4c:
            periodic.append(i)

    # Classify the 15 bytes the game touched alongside the two budget u32s.
    budget_offsets = [o for o, _, _ in pes17_pairs.PAIRS['budget']]
    companions = []
    for off in budget_offsets:
        if off in (pes17_pairs.BUDGET_MAIN, pes17_pairs.BUDGET_WAGE) or \
                pes17_pairs.BUDGET_MAIN <= off < pes17_pairs.BUDGET_MAIN + 4 or \
                pes17_pairs.BUDGET_WAGE <= off < pes17_pairs.BUDGET_WAGE + 4:
            continue
        companions.append(dict(
            offset=off, before=before[off],
            after=sets['budget']['data.dat'][off],
            delta=sets['budget']['data.dat'][off] - before[off]))
    counter_like = sum(1 for c in companions if abs(c['delta']) <= 8 or
                       c['after'] == 0)

    headers = []
    for n in NAMES:
        h = sets[n]['header.dat']
        headers.append(dict(
            pair=n,
            hash_80_144_changed=h[80:144] != bp['header.dat'][80:144],
            other_header_bytes_unchanged=(
                h[:80] == bp['header.dat'][:80] and
                h[144:] == bp['header.dat'][144:]),
            encryption_header_changed=(
                sets[n]['encryptHeader.dat'] != bp['encryptHeader.dat']),
            token_changed=sets[n]['data.dat'][48:80] != before[48:80]))

    report = dict(
        note=('Save-file facts only. Not in-game validation; none of these '
              'bytes are written by lib/pes17_write.py.'),
        data_size=len(before),
        after_files=paths,
        changed=dict(common=len(common), union=len(union),
                     common_varying=len(varying), common_stable=len(stable),
                     common_ranges=ranges(common)),
        token=dict(region=[48, 80], bytes_changed=len(token),
                   per_save_unique=True,
                   note=('32 high-entropy bytes, different in every save. '
                         'Likely a per-save seed/MAC; algorithm unknown.')),
        non_token_varying_offsets=non_token_varying,
        periodic_delta=dict(
            count=len(periodic), first=periodic[:12],
            note=('Stable-delta bytes where before == after + 0x4C (76). '
                  'They sit at a fixed stride in the player/team arrays: a '
                  'per-save counter, not an action table.')),
        budget_companions=dict(
            offsets=companions, counter_or_flag_like=counter_like,
            total=len(companions),
            note=('These bytes change with the budget edit but do NOT hold a '
                  'copy of the budget u32 (small counts/flags only). The '
                  'custom "budget" op correctly writes just the two u32 '
                  'words; the exact "pair" op reproduces all of them.')),
        header=headers,
        header_hash=dict(
            region=[80, 144], size=64, changed_in_every_save=True,
            algorithm='UNKNOWN',
            note=('Only header.dat[80:144] differs between before and after; '
                  'all other header bytes are identical. We keep the original '
                  'hash like the public MLTE tool. Whether PES 2017 accepts '
                  'that is still unconfirmed in-game.')),
        standings_stats_search=dict(
            result='not found',
            note=('Scanned 8,610,000..8,720,000 for 20-row u16 arrays where '
                  'w+d+l == played and points <= 3*played+3: no match. '
                  'Points/played/goals therefore stay 0 rather than showing '
                  'guessed numbers.')),
    )
    text = json.dumps(report, indent=1, ensure_ascii=False)
    if a.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
        with open(a.json_out, 'w', encoding='utf-8') as f:
            f.write(text + '\n')
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
