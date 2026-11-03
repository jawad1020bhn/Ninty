#!/usr/bin/env python3
"""PES 2017 save layout helper for The Gaffer.

Use this when you want to unlock *writing* to PES 2017 saves.  It reads a
decrypted Master League save and reports the structures that are known, and it
can diff two decrypted saves so that one in-game action can be traced to the
exact bytes that changed.

Examples
--------
  python lib/pes17_layout.py info  "C:\\dec\\ML00000000"
  python lib/pes17_layout.py diff  "C:\\dec\\before" "C:\\dec\\after"  --json diff.json
  python lib/pes17_layout.py edit  "C:\\dec\\EDIT00000000"  --json players.json

Workflow for mapping a table:
  1. In PES 2017, save your Master League to a slot.  Decrypt it to "before".
  2. Change ONE thing in the game (formation, a transfer, a contract, the
     budget ...) and save again.  Decrypt it to "after".
  3. Run diff.  The changed ranges point at the table and row that the game
     writes.  Repeat with a second value to identify the field inside the row.
  4. Add the offset to pes17.py and to a PES 2017 write profile, then remove
     the read-only guard for that operation.
"""
import argparse
import json
import os
import struct

import pes17


def _read(folder, name='data.dat'):
    with open(os.path.join(folder, name), 'rb') as f:
        return f.read()


def info(folder):
    d = _read(folder)
    r = pes17.read_save(folder)
    teams = pes17.team_records(d)
    blocks = pes17.standings(d, teams)
    out = dict(
        game='PES 2017', read_only=True,
        files={f: os.path.getsize(os.path.join(folder, f))
               for f in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, f))},
        data_size=len(d),
        description=r['info'],
        team_table=dict(offset=pes17.TEAM0, stride=pes17.TEAM_STRIDE,
                        count=len(teams), end=pes17.TEAM_END,
                        first=[t['name'] for t in teams[:5]],
                        squad_offset=pes17.SQUAD_OFF, squad_slots=pes17.SQUAD_SLOTS),
        squad=r.get('squad', []),
        standings=[dict(league=b['league'], offset=b['offset'], teams=len(b['rows']),
                        first=[x['club'] for x in b['rows'][:5]]) for b in blocks],
        known_write_tables=[],
        note=('Writing is disabled. Points/goals/played fields inside the club '
              'record, the standing structures, budget, contracts, transfers '
              'and formation/tactics blocks still need to be measured on real '
              'PES 2017 save pairs.'),
    )
    return out


def diff(a, b, block=4096, max_ranges=400):
    """Changed 4 KiB blocks and byte ranges between two decrypted saves."""
    da, db = _read(a), _read(b)
    n = min(len(da), len(db))
    out = dict(a=a, b=b, size_a=len(da), size_b=len(db), blocks=[], ranges=[])
    if len(da) != len(db):
        out['note'] = 'The two saves have different sizes: compare same-slot saves.'
    lo = None
    for p in range(0, n, block):
        if da[p:p + block] == db[p:p + block]:
            if lo is not None:
                out['blocks'].append([lo, p]); lo = None
            continue
        if lo is None:
            lo = p
    if lo is not None:
        out['blocks'].append([lo, n])
    # byte-exact ranges (coalesce changes closer than 64 bytes)
    start = None
    last = None
    for p, (x, y) in enumerate(zip(da[:n], db[:n])):
        if x != y:
            if start is None:
                start = p
            last = p
        elif start is not None and p - last > 64:
            out['ranges'].append([start, last + 1])
            start = None
        if len(out['ranges']) >= max_ranges:
            break
    if start is not None:
        out['ranges'].append([start, last + 1])
    return out


def edit(src):
    data = pes17._edit_data(src)
    players = pes17.parse_edit(data)
    return dict(count=len(players), players=players[:20],
                note='First 20 players shown; use import_edit() for the full database.')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mode', choices=('info', 'diff', 'edit'))
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--json', help='write the report to this JSON file')
    args = ap.parse_args()
    if args.mode == 'info':
        r = info(args.paths[0])
    elif args.mode == 'diff':
        if len(args.paths) < 2:
            ap.error('diff needs two folders')
        r = diff(args.paths[0], args.paths[1])
    else:
        r = edit(args.paths[0])
    text = json.dumps(r, ensure_ascii=False, indent=1)
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            f.write(text)
        print('Wrote', args.json)
    else:
        print(text)


if __name__ == '__main__':
    main()
