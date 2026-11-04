#!/usr/bin/env python3
"""Build the PES 2017 edition of The Gaffer from the original pc414 zip.

    python pes2017/build.py

Writes dist/TheGaffer_pes2017_pc414.zip (the folder inside is still called
"TheGaffer", so unzipping over an existing install works as an update).
"""
import os
import shutil
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'TheGaffer_pc414_20261103.zip')
BUILD = os.path.join(ROOT, 'build', 'TheGaffer')
OUT = os.path.join(HERE, 'dist', 'TheGaffer_pes2017_pc414.zip')


def main():
    if not os.path.isfile(SRC):
        sys.exit('Original zip not found: ' + SRC)
    if os.path.isdir(BUILD):
        shutil.rmtree(BUILD)
    os.makedirs(BUILD, exist_ok=True)
    with zipfile.ZipFile(SRC) as z:
        z.extractall(BUILD)
    program = os.path.join(BUILD, 'TheGaffer')
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
        for folder, dirs, files in os.walk(BUILD):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in sorted(files):
                if f.endswith('.pyc'):
                    continue
                p = os.path.join(folder, f)
                z.write(p, os.path.relpath(p, BUILD).replace(os.sep, '/'))
    print('Built', OUT, '(%.1f MB)' % (os.path.getsize(OUT) / 1e6))


if __name__ == '__main__':
    main()
