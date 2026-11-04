#!/usr/bin/env python3
"""Offline CPK asset inventory / harvester for the PES 2017 edition.

Read-only with respect to the source.  Uses the pc414 readers already shipped
with the app (cpkread / dds / ftex / bc7); no network, no new dependency.

Examples
--------
    # just list what a patch folder (or a single .cpk) contains
    python3 pes2017/tools/harvest_cpk.py "D:/PES2017/download" -o manifest.json

    # copy reusable crests / competition logos / generic art into the app
    python3 pes2017/tools/harvest_cpk.py "D:/PES2017/download" \
        -o manifest.json --extract "C:/TheGaffer/data/pes17/harvest" \
        --classes crest,emblem,art

    # if the shipped lib/ is not next to this script, point at the built tree
    GAFFER_LIB=/home/user/Ninty/build/TheGaffer/TheGaffer/lib \
        python3 pes2017/tools/harvest_cpk.py build/realsmoke2/patch -o /tmp/m.json

The manifest records CLASS, id, size, PES 2017 usability and the reason for
every entry.  Extraction never writes into the source folder.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.environ.get('GAFFER_LIB',
                                 os.path.join(ROOT, 'build', 'TheGaffer', 'TheGaffer', 'lib')))
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'overlay', 'lib'))

import pes17_assets  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('source', help='patch folder, livecpk folder, or a single .cpk file')
    ap.add_argument('-o', '--out', help='write the JSON manifest here')
    ap.add_argument('--extract', help='copy selected assets into this APP folder')
    ap.add_argument('--classes', default=','.join(pes17_assets.DEFAULT_EXTRACT),
                    help='comma-separated classes to extract (default: %(default)s)')
    ap.add_argument('--limit', type=int, default=200, help='max files to extract')
    ap.add_argument('--rescan', action='store_true', help='ignore the in-process cache')
    a = ap.parse_args(argv)

    rows, summary = pes17_assets.scan(a.source, force=a.rescan)
    manifest = dict(summary)
    manifest['rows'] = rows
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1, default=str)

    print('Source      :', a.source or '(none)')
    print('Archives    :', summary['archives'], ' loose files:', summary['loose_files'],
          ' total entries:', summary['files'])
    print('By class    :', ', '.join('%s=%d' % (k, v) for k, v in summary['counts'].items() if v))
    print('PES 2017    :', ', '.join('%s=%d' % (k, v) for k, v in summary['usable'].items() if v))
    for e in summary['errors'][:5]:
        print('  archive error:', e)
    if a.out:
        print('Manifest    :', a.out)

    if a.extract:
        cls = [c.strip() for c in a.classes.split(',') if c.strip()]
        try:
            r = pes17_assets.harvest(a.source, a.extract, classes=cls,
                                     limit=a.limit, rows=rows)
        except ValueError as e:
            print('REFUSED:', e)
            return 2
        print('Extracted   :', r['written'], 'files,', r['bytes'], 'bytes ->', r['out'],
              '(skipped %d, failed %d)' % (r['skipped'], r['failed']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
