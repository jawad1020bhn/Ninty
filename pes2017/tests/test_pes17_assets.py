"""Tests for the offline CPK asset inventory / harvester (r7)."""
import base64
import json
import os
import struct
import sys
import tempfile
import types
import unittest
import zipfile
import zlib
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'overlay', 'lib'))
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'tools'))

import pes17_assets as assets  # noqa: E402
import harvest_cpk  # noqa: E402

PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==')


def make_dds(w=2, h=2):
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<I', hdr, 4, 124)
    struct.pack_into('<II', hdr, 12, h, w)
    struct.pack_into('<I', hdr, 76, 32)
    struct.pack_into('<I', hdr, 88, 32)
    struct.pack_into('<IIII', hdr, 92, 0xff, 0xff00, 0xff0000, 0xff000000)
    return bytes(hdr) + bytes((255, 0, 0, 255)) * (w * h)


class FakeCpk(object):
    DATA = {}

    def __init__(self, path):
        self.path = path
        self.files = {n: dict(FileName=n, FileSize=len(v))
                      for n, v in FakeCpk.DATA.get(path, {}).items()}

    def read(self, name):
        return FakeCpk.DATA[self.path][name]


class AssetHarvestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.src = os.path.join(self.root, 'patch')
        os.makedirs(os.path.join(self.src, 'common', 'render', 'symbol', 'flag'))
        assets.clear()
        FakeCpk.DATA = {}
        mods = {}
        zp = os.path.join(ROOT, 'pes2017', 'dist', 'TheGaffer_pes2017_pc414.zip')
        if os.path.isfile(zp):
            with zipfile.ZipFile(zp) as z:
                m = types.ModuleType('dds')
                exec(compile(z.read('TheGaffer/lib/dds.py'), 'dds.py', 'exec'), m.__dict__)
            mods['dds'] = m
        mods['cpkread'] = types.SimpleNamespace(Cpk=FakeCpk)
        self.p = mock.patch.dict(sys.modules, mods)
        self.p.start()
        self.addCleanup(self.p.stop)

    def put(self, rel, data):
        p = os.path.join(self.src, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data)
        return p

    def arc(self, name, entries):
        p = os.path.join(self.src, 'download', name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(b'CPK ')
        FakeCpk.DATA[p] = entries
        return p

    # ------------------------------------------------------------ classify
    def test_classify_all_cpk_asset_classes(self):
        cases = [
            ('common/render/symbol/flag/e_201_r.png', 'crest', 201, 'MAP'),
            ('common/render/symbol/emblemLc/emb_0017_lc.png', 'emblem', 17, 'MAP'),
            ('Asset/model/character/uniform/texture/#windx11/u0103p1.ftex', 'kit', 103, 'MAP'),
            ('common/render/symbol/player/55246.dds', 'face', 55246, 'MAP'),
            ('common/render/symbol/player/55246.ftex', 'face', 55246, 'MAP'),
            ('common/render/symbol/coach/coach_12.png', 'coach', 12, 'MAP'),
            ('common/etc/pesdb/Competition.bin', 'pesdb', None, 'NO'),
            ('data/art/banner.jpg', 'art', None, 'YES'),
            ('unknown/file.bin', 'other', None, 'MAYBE'),
        ]
        for path, cls, aid, usable in cases:
            with self.subTest(path=path):
                got = assets.classify(path)
                self.assertEqual(got[0], cls)
                self.assertEqual(got[1], aid)
                self.assertEqual(got[4], usable)

    # -------------------------------------------------------------- scan
    def test_scan_inventory_from_cpk_toc_only(self):
        self.arc('T99_v20.cpk', {
            'common/render/symbol/flag/e_201_r.png': PNG,
            'common/render/symbol/emblemLc/emb_0017_lc.png': PNG,
            'common/render/symbol/player/55246.dds': make_dds(),
            'common/etc/pesdb/Competition.bin': b'\0' * 32,
        })
        rows, s = assets.scan(self.src, force=True)
        self.assertEqual(s['archives'], 1)
        self.assertEqual(s['cpk_entries'], 4)
        self.assertEqual(s['counts']['crest'], 1)
        self.assertEqual(s['counts']['emblem'], 1)
        self.assertEqual(s['counts']['face'], 1)
        self.assertEqual(s['counts']['pesdb'], 1)
        self.assertEqual(s['usable']['NO'], 1)
        self.assertTrue(all(r['in_cpk'] for r in rows))

    def test_loose_art_and_manifest_shape(self):
        self.put('art/banner.jpg', b'\xff\xd8' + b'x' * 40)
        m = assets.manifest({'pes17_patch_dir': self.src})
        self.assertTrue(m['ok'])
        self.assertFalse(m['auto'])
        self.assertEqual(m['counts']['art'], 1)
        self.assertEqual(m['sample'][0]['usable'], 'YES')
        self.assertIn('pes17_patch_dir', m['hint'])
        self.assertEqual(m['classes'], list(assets.CLASSES))

    def test_auto_detect_from_pes_exe(self):
        game = os.path.join(self.root, 'game')
        os.makedirs(os.path.join(game, 'download'))
        with open(os.path.join(game, 'download', 'kit.png'), 'wb') as f:
            f.write(PNG)
        with open(os.path.join(game, 'PES2017.exe'), 'wb') as f:
            f.write(b'MZ')
        m = assets.manifest({'pes_exe': os.path.join(game, 'PES2017.exe')}, True)
        self.assertTrue(m['auto'])
        self.assertTrue(any('download' in r for r in m['candidate_roots']))
        self.assertGreaterEqual(m['files'], 1)

    # ------------------------------------------------------------ extract
    def test_harvest_converts_dds_and_never_writes_source(self):
        self.put('common/render/symbol/flag/e_201_r.dds', make_dds())
        before = {}
        for d, _, fs in os.walk(self.src):
            for f in fs:
                p = os.path.join(d, f)
                with open(p, 'rb') as fh:
                    before[p] = (os.path.getsize(p), fh.read())
        out = os.path.join(self.root, 'appdata', 'harvest')
        r = assets.harvest(self.src, out, classes=('crest',), limit=10)
        self.assertEqual(r['written'], 1)
        self.assertTrue(r['source_read_only'])
        got = [p for p in os.listdir(os.path.join(out, 'crest')) if p.endswith('.png')]
        self.assertEqual(len(got), 1)
        with open(os.path.join(out, 'crest', got[0]), 'rb') as f:
            self.assertTrue(f.read(8).startswith(b'\x89PNG\r\n\x1a\n'))
        after = {}
        for d, _, fs in os.walk(self.src):
            for f in fs:
                p = os.path.join(d, f)
                with open(p, 'rb') as fh:
                    after[p] = (os.path.getsize(p), fh.read())
        self.assertEqual(before, after)

    def test_harvest_unwraps_wesys_from_cpk(self):
        head = bytearray(16)
        head[0:5] = b'WESYS'
        wrapped = bytes(head) + zlib.compress(PNG)
        self.arc('a.cpk', {'common/render/symbol/flag/e_201_r.png': wrapped})
        out = os.path.join(self.root, 'appdata', 'harvest2')
        r = assets.harvest(self.src, out, classes=('crest',), limit=10)
        self.assertEqual(r['written'], 1)
        p = os.path.join(out, 'crest', os.listdir(os.path.join(out, 'crest'))[0])
        with open(p, 'rb') as f:
            self.assertEqual(f.read(), PNG)

    def test_pesdb_and_unselected_classes_are_not_extracted(self):
        self.arc('a.cpk', {
            'common/etc/pesdb/Competition.bin': b'\0' * 16,
            'common/render/symbol/player/1.png': PNG,
        })
        out = os.path.join(self.root, 'appdata', 'harvest3')
        r = assets.harvest(self.src, out, classes=('crest', 'emblem', 'art'), limit=10)
        self.assertEqual(r['written'], 0)

    def test_refuses_to_extract_into_source_folder(self):
        self.put('art/banner.jpg', b'\xff\xd8' + b'x')
        with self.assertRaisesRegex(ValueError, 'Refusing'):
            assets.harvest(self.src, os.path.join(self.src, 'harvest'), classes=('art',))

    # ---------------------------------------------------------------- CLI
    def test_cli_writes_manifest(self):
        self.put('art/banner.jpg', b'\xff\xd8' + b'x')
        mpath = os.path.join(self.root, 'manifest.json')
        rc = harvest_cpk.main([self.src, '-o', mpath, '--rescan'])
        self.assertEqual(rc, 0)
        with open(mpath, encoding='utf-8') as f:
            j = json.load(f)
        self.assertTrue(j['ok'])
        self.assertEqual(j['counts']['art'], 1)
        self.assertIn('rows', j)

    def test_module_has_no_network_calls(self):
        with open(assets.__file__, encoding='utf-8') as f:
            src = f.read()
        for bad in ('urllib', 'requests', 'socket.', 'http.client', 'https://', 'http://'):
            self.assertNotIn(bad, src)


if __name__ == '__main__':
    unittest.main()
