#!/usr/bin/env python3
"""Diff two encrypted PES 2017 saves (one in-game action) without manual decrypt.

    python3 pes2017/tools/diff_saves.py "Needed files/ML00000011" \
        "formation/after/ML00000011" --json build/formation_diff.json

Decrypts both with the PES 2017 key / 176 B header, writes the six parts to
temporary folders and calls lib/pes17_layout.py diff.  Only data.dat is
compared; header hashes / encryption salts are reported separately.
"""
import argparse
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'build', 'TheGaffer', 'TheGaffer', 'lib'))
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'overlay', 'lib'))

import pescrypt  # noqa: E402
import pes17_layout  # noqa: E402


def decrypt_to_folder(path, folder):
    with open(path, 'rb') as f:
        parts = pescrypt.decrypt_bytes(f.read(), pescrypt.KEY_PES17)
    os.makedirs(folder, exist_ok=True)
    for k, v in parts.items():
        with open(os.path.join(folder, k), 'wb') as f:
            f.write(v)
    return parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('before')
    ap.add_argument('after')
    ap.add_argument('--json', help='write the report here')
    ap.add_argument('--block', type=int, default=4096)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='pes17diff_') as tmp:
        p1 = decrypt_to_folder(a.before, os.path.join(tmp, 'before'))
        p2 = decrypt_to_folder(a.after, os.path.join(tmp, 'after'))
        rep = pes17_layout.diff(os.path.join(tmp, 'before'),
                                os.path.join(tmp, 'after'), a.block)
        rep['header'] = dict(
            file_header=len(p1['header.dat']),
            hash_changed=p1['header.dat'][80:144] != p2['header.dat'][80:144],
            encryption_header_changed=(p1['encryptHeader.dat'] !=
                                       p2['encryptHeader.dat']),
            description_changed=p1['description.dat'] != p2['description.dat'],
            token_changed=p1['data.dat'][48:80] != p2['data.dat'][48:80],
            before_sha256=hashlib.sha256(open(a.before, 'rb').read()).hexdigest(),
            after_sha256=hashlib.sha256(open(a.after, 'rb').read()).hexdigest())
    text = json.dumps(rep, indent=1, ensure_ascii=False)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, 'w', encoding='utf-8') as f:
            f.write(text + '\n')
        print('wrote', a.json)
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
