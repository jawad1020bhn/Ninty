#!/usr/bin/env python3
"""Build the PES 2017 edition of The Gaffer from the original pc414 zip.

    python pes2017/build.py
    GAFFER_ORIGINAL_ZIP=/path/to/TheGaffer_pc414_20261103.zip python pes2017/build.py

The original upstream zip was removed from the repository by the r8/r9 repo
cleanup (only the pes2017/ folder is kept). It is still recoverable from git
history, e.g.:

    git show e89a9a1:TheGaffer_pc414_20261103.zip > /tmp/pc414.zip
    GAFFER_ORIGINAL_ZIP=/tmp/pc414.zip python3 pes2017/build.py

Set GAFFER_ORIGINAL_ZIP (or pass --source) to build without re-adding the
31 MB upstream zip to the repo. Writes dist/TheGaffer_pes2017_pc414.zip (the
folder inside is still called "TheGaffer", so unzipping over an existing
install works as an update).
"""
import argparse
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get('GAFFER_ORIGINAL_ZIP') or os.path.join(ROOT, 'TheGaffer_pc414_20261103.zip')
BUILD = os.environ.get('GAFFER_BUILD_DIR') or os.path.join(ROOT, 'build', 'TheGaffer')
OUT = os.path.join(HERE, 'dist', 'TheGaffer_pes2017_pc414.zip')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', help='path to the original pc414 zip (overrides GAFFER_ORIGINAL_ZIP)')
    a = ap.parse_args()
    src = a.source or SRC
    builddir = os.environ.get('GAFFER_BUILD_DIR') or BUILD
    if not os.path.isfile(src):
        sys.exit('Original zip not found: %s\nRecover it with: '
                 'git show e89a9a1:TheGaffer_pc414_20261103.zip > /tmp/pc414.zip '
                 'then set GAFFER_ORIGINAL_ZIP=/tmp/pc414.zip' % src)
    if os.path.isdir(builddir):
        shutil.rmtree(builddir)
    os.makedirs(builddir, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        z.extractall(builddir)
    program = os.path.join(builddir, 'TheGaffer')
    if not os.path.isfile(os.path.join(program, 'server.py')):
        sys.exit('Unexpected zip layout: TheGaffer/server.py missing')

    sys.path.insert(0, HERE)
    import patch
    import prune
    patch.apply(program)
    clean = prune.apply(program)
    print('Safe cleanup: removed %d FL26/FL27/Sider-only files (%.2f MB), kept %d required paths' %
          (clean['removed'], clean['bytes'] / 1e6, clean['kept']))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for folder, dirs, files in os.walk(builddir):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in sorted(files):
                if f.endswith('.pyc'):
                    continue
                p = os.path.join(folder, f)
                z.write(p, os.path.relpath(p, builddir).replace(os.sep, '/'))
    print('Built', OUT, '(%.1f MB)' % (os.path.getsize(OUT) / 1e6))


if __name__ == '__main__':
    main()
