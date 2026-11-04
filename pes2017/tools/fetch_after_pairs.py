#!/usr/bin/env python3
"""Stage the four game-generated after saves for tools/verify_pairs.py.

The after files live on ``main`` (``formation/after/ML00000011`` etc.).  They
are 13 MB each, so we do NOT duplicate them on the working branch / in Git.
This script copies them into the gitignored ``build/pairs/<name>/`` folder:

    git fetch origin main
    python3 pes2017/tools/fetch_after_pairs.py
    python3 pes2017/tools/verify_pairs.py

It first looks for the files on disk (e.g. if you unzipped them next to the
repo), then falls back to ``git show origin/main:<path>``.  Nothing is
committed and no save is modified.
"""
import os
import subprocess
import sys
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEST = os.path.join(ROOT, 'build', 'pairs')
NAMES = ('formation', 'tactics', 'xi', 'budget')
EXPECTED_SIZE = 13342176


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    ok = 0
    for n in NAMES:
        out = os.path.join(DEST, n, 'ML00000011')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        local = os.path.join(ROOT, n, 'after', 'ML00000011')
        if os.path.isfile(local) and os.path.getsize(local) == EXPECTED_SIZE:
            with open(local, 'rb') as src, open(out, 'wb') as dst:
                dst.write(src.read())
            src_desc = local
        else:
            spec = 'origin/main:%s/after/ML00000011' % n
            try:
                raw = subprocess.check_output(['git', 'show', spec], cwd=ROOT,
                                             stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                print('SKIP', n, '- cannot read', spec,
                      e.stderr.decode('utf8', 'replace').strip()[:120])
                continue
            if len(raw) != EXPECTED_SIZE:
                print('SKIP', n, '- unexpected size', len(raw))
                continue
            with open(out, 'wb') as dst:
                dst.write(raw)
            src_desc = spec
        print('OK  ', n, EXPECTED_SIZE, 'B', sha256(out)[:16], '<-', src_desc)
        ok += 1
    print('\n%d/4 after saves staged in %s' % (ok, DEST))
    return 0 if ok == 4 else 1


if __name__ == '__main__':
    sys.exit(main())
