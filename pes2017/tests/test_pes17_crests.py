"""Tests for the PES 2017 patch-folder crest reader (offline, read-only).

Run:  python3 -m unittest discover -s pes2017/tests -v
"""
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

import pes17_crests as crests  # noqa: E402

# 1x1 transparent PNG, and a solid-colour 2x2 PNG used to tell files apart.
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==')
PNG2 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR42mP8z8AARIQBEwMDAwMoAF/gBv81R1MAAAAASUVORK5CYII=')

TEAMIDS = {
    '1': 'Arsenal FC',
    '2': 'Chelsea FC',
    '201': 'Birmingham City FC',
    # Same club name under the raw bit-packed id: the stable tid must win.
    '3293185': 'Birmingham City FC',
    '42': 'Real Madrid CF',
}


def make_dds(w=2, h=2, rgba=(255, 0, 0, 255)):
    """Uncompressed 32-bit DDS the shipped lib/dds.py can decode."""
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<I', hdr, 4, 124)
    struct.pack_into('<II', hdr, 12, h, w)
    struct.pack_into('<I', hdr, 76, 32)          # pf_flags
    struct.pack_into('<I', hdr, 88, 32)          # bits per pixel
    struct.pack_into('<IIII', hdr, 92, 0xff, 0xff00, 0xff0000, 0xff000000)
    return bytes(hdr) + bytes(rgba) * (w * h)


def wesys(raw):
    """FL27-style wrapper: 16 B header containing WESYS + zlib payload."""
    head = bytearray(16)
    head[0:5] = b'WESYS'
    return bytes(head) + zlib.compress(raw)


class FakeCpk(object):
    """In-memory stand-in for cpkread.Cpk (same .files / .read API)."""
    DATA = {}

    def __init__(self, path):
        self.path = path
        self.files = {n: dict(FileName=n, FileSize=len(v))
                      for n, v in FakeCpk.DATA.get(path, {}).items()}

    def read(self, name):
        return FakeCpk.DATA[self.path][name]


class PatchCrests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.db = os.path.join(self.root, 'appdata')
        os.makedirs(os.path.join(self.db, 'data', 'pes17'))
        with open(os.path.join(self.db, 'data', 'pes17', 'teamids.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(TEAMIDS, f)
        self.old_here = crests.HERE
        crests.HERE = self.db
        self.addCleanup(setattr, crests, 'HERE', self.old_here)
        crests.clear()
        # Load the shipped lib/dds.py out of the built zip so the real DDS
        # decoder is exercised (there is no build/ tree in a clean checkout).
        zp = os.path.join(ROOT, 'pes2017', 'dist', 'TheGaffer_pes2017_pc414.zip')
        if os.path.isfile(zp):
            with zipfile.ZipFile(zp) as z:
                m = types.ModuleType('dds')
                exec(compile(z.read('TheGaffer/lib/dds.py'), 'dds.py', 'exec'), m.__dict__)
            sys.modules['dds'] = m
            self.addCleanup(sys.modules.pop, 'dds', None)
        FakeCpk.DATA = {}
        self.cpk_patch = mock.patch.dict(sys.modules, {'cpkread': types.SimpleNamespace(Cpk=FakeCpk)})
        self.cpk_patch.start()
        self.addCleanup(self.cpk_patch.stop)

    def cfg(self, patch=None, exe=None):
        c = {'pes17_patch_dir': patch or '', 'work': self.root}
        if exe:
            c['pes_exe'] = exe
        return c

    def put(self, rel, data):
        p = os.path.join(self.patch, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data)
        return p

    @property
    def patch(self):
        p = os.path.join(self.root, 'patch')
        os.makedirs(p, exist_ok=True)
        return p

    # -------------------------------------------------------------- mapping
    def test_team_map_prefers_stable_tid_over_raw_id(self):
        ids = crests._team_map(self.cfg())
        self.assertEqual(ids[crests._norm('Birmingham City FC')], 201)
        self.assertEqual(ids[crests._norm('Birminghamcityfc')], 201)
        self.assertEqual(crests.resolve(self.cfg(), 'Birmingham City FC'), 201)
        self.assertEqual(crests.resolve(self.cfg(), '201'), 201)
        self.assertEqual(crests.resolve(self.cfg(), ' arsenalfc '), 1)

    def test_strip_fc_suffix_and_fuzzy_match(self):
        self.assertEqual(crests.resolve(self.cfg(), 'Birmingham City'), 201)
        self.assertEqual(crests.resolve(self.cfg(), 'Real Madrid'), 42)
        self.assertEqual(crests.resolve(self.cfg(), 'Arsenal'), 1)

    # ---------------------------------------------------------- loose files
    def test_loose_emblem_png_by_team_id_and_variant_ranking(self):
        self.put('common/render/symbol/flag/e_201_r_b.png', PNG2)
        self.put('common/render/symbol/flag/e_201_r.png', PNG)
        idx, rep = crests.scan(self.cfg(self.patch))
        self.assertEqual(idx[201]['kind'], 'file')
        self.assertTrue(idx[201]['path'].endswith('e_201_r.png'))
        self.assertEqual(rep['logos_found'], 1)
        self.assertEqual(rep['clubs_matched'], 1)
        self.assertEqual(crests.crest_img('Birmingham City FC', self.cfg(self.patch)), PNG)

    def test_loose_logo_named_after_club(self):
        self.put('logos/Arsenal_FC.png', PNG2)
        idx, _ = crests.scan(self.cfg(self.patch))
        self.assertIn(1, idx)
        self.assertEqual(crests.crest_img('Arsenal FC', self.cfg(self.patch)), PNG2)

    def test_plain_number_filename_in_logo_folder(self):
        self.put('crests/42.png', PNG)
        idx, _ = crests.scan(self.cfg(self.patch))
        self.assertIn(42, idx)
        self.assertEqual(crests.crest_img('Real Madrid CF', self.cfg(self.patch)), PNG)

    def test_flag_prefixed_filename_and_no_false_positive_id(self):
        self.put('logos/flag_201.png', PNG)
        self.put('logos/somefile201.png', PNG2)
        idx, rep = crests.scan(self.cfg(self.patch))
        self.assertEqual(sorted(idx), [201])
        self.assertEqual(rep['skipped'], 1)

    def test_patch_root_name_with_kit_in_it_does_not_hide_crests(self):
        # NOT_CREST_WORDS must be applied to the relative path, not the root.
        p = os.path.join(self.root, 'kitserver_patch', 'logos', 'e_201_r.png')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(PNG)
        idx, _ = crests.scan(self.cfg(os.path.join(self.root, 'kitserver_patch')))
        self.assertIn(201, idx)

    def test_map_txt_adds_club_name(self):
        self.put('map.txt', b'# patch team list\n999=Test United FC\n')
        self.put('logos/999.png', PNG)
        idx, _ = crests.scan(self.cfg(self.patch))
        self.assertIn(999, idx)
        self.assertEqual(crests.resolve(self.cfg(self.patch), 'Test United'), 999)

    def test_kit_and_face_files_are_not_treated_as_crests(self):
        self.put('logos/u0201p1.ftex', b'FTEX' + b'\0' * 64)
        self.put('kits/e_201_r.png', PNG)
        idx, _ = crests.scan(self.cfg(self.patch))
        self.assertEqual(idx, {})

    # ----------------------------------------------------------- decoding
    def test_dds_is_converted_to_png(self):
        self.put('common/render/symbol/flag/e_201_r.dds', make_dds())
        b = crests.crest_img('Birmingham City FC', self.cfg(self.patch))
        self.assertTrue(b and b[:8] == b'\x89PNG\r\n\x1a\n')

    def test_wesys_wrapped_cpk_emblem_is_decoded(self):
        arc = os.path.join(self.patch, 'download', 'T99_v20.cpk')
        os.makedirs(os.path.dirname(arc), exist_ok=True)
        with open(arc, 'wb') as f:
            f.write(b'CPK ')
        FakeCpk.DATA[arc] = {
            'common/render/symbol/flag/e_201_r.png': wesys(PNG2),
        }
        idx, rep = crests.scan(self.cfg(self.patch))
        self.assertEqual(rep['cpk_archives'], 1)
        self.assertIn(201, idx)
        self.assertEqual(idx[201]['kind'], 'cpk')
        self.assertEqual(crests.crest_img(201, self.cfg(self.patch)), PNG2)

    def test_loose_file_beats_cpk_copy(self):
        self.put('common/render/symbol/flag/e_201_r.png', PNG)
        arc = os.path.join(self.patch, 'download', 'patch.cpk')
        os.makedirs(os.path.dirname(arc), exist_ok=True)
        with open(arc, 'wb') as f:
            f.write(b'CPK ')
        FakeCpk.DATA[arc] = {'common/render/symbol/flag/e_201_r.png': PNG2}
        idx, _ = crests.scan(self.cfg(self.patch))
        self.assertEqual(idx[201]['kind'], 'file')
        self.assertEqual(crests.crest_img(201, self.cfg(self.patch)), PNG)

    def test_broken_dds_and_oversized_file_fail_gracefully(self):
        self.put('common/render/symbol/flag/e_201_r.dds', b'not a dds')
        self.assertIsNone(crests.crest_img(201, self.cfg(self.patch)))
        crests.clear()
        self.put('logos/Arsenal_FC.png', b'\x89PNG\r\n\x1a\n' + b'x' * (crests.MAX_BYTES + 8))
        self.assertIsNone(crests.crest_img('Arsenal FC', self.cfg(self.patch)))

    # -------------------------------------------------------------- report
    def test_report_is_diagnostic_and_offline(self):
        self.put('logos/Arsenal_FC.png', PNG)
        r = crests.report(self.cfg(self.patch), True)
        self.assertTrue(r['ok'])
        self.assertTrue(r['available'])
        self.assertFalse(r['auto'])
        self.assertTrue(r['explicit'])
        self.assertEqual(r['logos_found'], 1)
        self.assertEqual(r['clubs_matched'], 1)
        self.assertEqual(r['sample'][0]['id'], 1)
        self.assertIn('CPK', r['hint'])
        self.assertEqual(crests.count(self.cfg(self.patch)), 1)

    def test_auto_detect_from_pes_exe(self):
        game = os.path.join(self.root, 'game')
        os.makedirs(os.path.join(game, 'download', 'logos'))
        with open(os.path.join(game, 'PES2017.exe'), 'wb') as f:
            f.write(b'MZ')
        with open(os.path.join(game, 'download', 'logos', 'Chelsea_FC.png'), 'wb') as f:
            f.write(PNG2)
        r = crests.report(self.cfg(exe=os.path.join(game, 'PES2017.exe')), True)
        self.assertTrue(r['auto'])
        self.assertFalse(r['explicit'])
        self.assertTrue(any('download' in x for x in r['roots']))
        self.assertTrue(r['available'])
        self.assertEqual(crests.crest_img('Chelsea FC', self.cfg(
            exe=os.path.join(game, 'PES2017.exe'))), PNG2)

    def test_missing_folder_and_clear(self):
        c = self.cfg(os.path.join(self.root, 'does-not-exist'))
        self.assertEqual(crests.roots_for(c)[0], [])
        self.assertFalse(crests.report(c, True)['available'])
        self.assertEqual(crests.count(c), 0)
        self.put('logos/Arsenal_FC.png', PNG)
        self.assertEqual(crests.count(self.cfg(self.patch)), 1)
        crests.clear()
        self.assertEqual(crests._STATE['index'], {})

    def test_unknown_club_returns_none(self):
        self.put('logos/Arsenal_FC.png', PNG)
        self.assertIsNone(crests.crest_img('A Club That Does Not Exist', self.cfg(self.patch)))

    # -------------------------------------------------------------- safety
    def test_no_network_api_in_module(self):
        with open(crests.__file__, encoding='utf-8') as f:
            src = f.read()
        for bad in ('urllib', 'requests', 'socket.', 'http.client', 'https://', 'http://'):
            self.assertNotIn(bad, src)
        self.assertIn('read-only', src.lower())

    def test_nothing_is_written_into_the_patch_folder(self):
        self.put('logos/Arsenal_FC.png', PNG)
        before = sorted((os.path.relpath(os.path.join(d, f), self.patch),
                         os.path.getsize(os.path.join(d, f)))
                        for d, _, fs in os.walk(self.patch) for f in fs)
        crests.report(self.cfg(self.patch), True)
        crests.crest_img('Arsenal FC', self.cfg(self.patch))
        after = sorted((os.path.relpath(os.path.join(d, f), self.patch),
                        os.path.getsize(os.path.join(d, f)))
                       for d, _, fs in os.walk(self.patch) for f in fs)
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
