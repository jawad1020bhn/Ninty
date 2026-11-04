#!/usr/bin/env python3
"""Prove the measured pair patches against the real before/after saves.

    python3 pes2017/tools/verify_pairs.py \
        --before "Needed files/ML00000011" \
        --after-dir build/pairs            # {formation,tactics,xi,budget}/ML00000011

For each action it decrypts both files, computes the byte diff, then applies
lib/pes17_pairs.apply_pair() to a copy of the before data and asserts that:

  * every byte the game changed ONLY for this action is reproduced exactly,
  * no other byte is changed by the patch,
  * the 211 bytes that changed in ALL four saves are left untouched.

It also reports the residual differences (per-save token at data.dat[48:80],
the 64-byte header hash, the encryption header salt and the UI-state words),
which the game rewrites on every save and which our writer deliberately keeps.
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

import pescrypt  # noqa: E402
import pes17_pairs  # noqa: E402

NAMES = ('formation', 'tactics', 'xi', 'budget')


def parts(path):
    with open(path, 'rb') as f:
        return pescrypt.decrypt_bytes(f.read(), pescrypt.KEY_PES17)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--before', default=os.path.join(ROOT, 'Needed files', 'ML00000011'))
    ap.add_argument('--after-dir', default=os.path.join(ROOT, 'build', 'pairs'),
                    help='directory containing <name>/ML00000011 (or <name>/after/ML00000011)')
    a = ap.parse_args()
    bp = parts(a.before)
    before = bp['data.dat']
    afters = {}
    for n in NAMES:
        for rel in (os.path.join(a.after_dir, n, 'ML00000011'),
                    os.path.join(a.after_dir, n, 'after', 'ML00000011'),
                    os.path.join(ROOT, n, 'after', 'ML00000011')):
            if os.path.isfile(rel):
                afters[n] = parts(rel)
                print('found', n, '->', rel)
                break
    missing = [n for n in NAMES if n not in afters]
    if missing:
        print('missing after files:', ', '.join(missing))
        return 1

    diffs = {n: {i for i, (x, y) in enumerate(zip(before, p['data.dat']))
                 if x != y} for n, p in afters.items()}
    common = set.intersection(*diffs.values())
    report = dict(before_sha256=hashlib.sha256(open(a.before, 'rb').read()).hexdigest(),
                  data_size=len(before), common_changed=len(common), pairs={})
    ok = True
    for n in NAMES:
        target = afters[n]['data.dat']
        feature = sorted(i for i in diffs[n] - common if i >= 1000 and
                         i not in (2210056, 8361492))
        measured = pes17_pairs.pair_offsets(n)
        d = bytearray(before)
        res = pes17_pairs.apply_pair(d, n)
        changed = {i for i, (x, y) in enumerate(zip(before, d)) if x != y}
        match = all(d[i] == target[i] for i in measured)
        exact = (feature == measured)
        only = changed.issubset(set(measured))
        report['pairs'][n] = dict(
            game_unique_bytes=len(feature), measured_bytes=len(measured),
            patch_changed_bytes=len(changed), offsets_match=exact,
            bytes_reproduced=match, no_extra_changes=only,
            residual_differences=len(diffs[n] - set(measured)),
            apply_result=res)
        if not (match and exact and only):
            ok = False
        # header / volatile detail
        hp = afters[n]['header.dat']
        report['pairs'][n]['header_hash_changed'] = (hp[80:144] != bp['header.dat'][80:144])
        report['pairs'][n]['token_changed'] = (target[48:80] != before[48:80])
    report['ok'] = ok
    print(json.dumps(report, indent=1))
    print('\nRESULT:', 'PASS - every measured byte reproduces the game' if ok
          else 'FAIL - see report')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
