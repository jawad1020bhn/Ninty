"""Tests for PES 2017 player mini-faces (backend scanner/decoder, live server, and UI)."""
import json
from concurrent.futures import ThreadPoolExecutor
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.environ.get('GAFFER_LIB', os.path.join(ROOT, 'build', 'TheGaffer', 'TheGaffer', 'lib'))
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'overlay', 'lib'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pes17_faces as faces  # noqa: E402

def make_png(rgba, width=2, height=2):
    """A valid synthetic image; colors are fixtures, not real player faces."""
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data +
                struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    pixels = b''.join(b'\x00' + bytes(rgba) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) +
            chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


PNG_VANILLA = make_png((15, 40, 90, 255))
PNG_PATCH_BASE = make_png((200, 25, 30, 255))
PNG_PATCH_TOP = make_png((30, 220, 40, 255))
PNG_LOOSE = make_png((40, 60, 225, 255))


def make_rgba_dds(w=2, h=2, rgba=(30, 140, 240, 255)):
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<I', hdr, 4, 124)
    struct.pack_into('<II', hdr, 12, h, w)
    struct.pack_into('<I', hdr, 76, 32)
    struct.pack_into('<I', hdr, 80, 0x41)
    struct.pack_into('<I', hdr, 88, 32)
    struct.pack_into('<IIII', hdr, 92, 0xff, 0xff00, 0xff0000, 0xff000000)
    return bytes(hdr) + bytes(rgba) * (w * h)


def make_rgb24_dds(w=2, h=2, rgb=(20, 180, 90)):
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<I', hdr, 4, 124)
    struct.pack_into('<II', hdr, 12, h, w)
    struct.pack_into('<I', hdr, 76, 32)
    struct.pack_into('<I', hdr, 80, 0x40)
    struct.pack_into('<I', hdr, 88, 24)
    struct.pack_into('<IIII', hdr, 92, 0xff0000, 0x00ff00, 0x0000ff, 0)
    px = bytes((rgb[2], rgb[1], rgb[0])) * (w * h)
    return bytes(hdr) + px


def make_ftex(w=2, h=2):
    # A minimal uncompressed, one-mip Fox texture (BGRA pixels).
    pixels = bytes((200, 80, 20, 255)) * (w * h)
    out = bytearray(0x68)
    out[:4] = b'FTEX'
    struct.pack_into('<HHH', out, 8, 0, w, h)
    out[0x10] = 1
    struct.pack_into('<IIIBBH', out, 0x40, 0x60, len(pixels), len(pixels), 0, 0, 1)
    struct.pack_into('<HHI', out, 0x60, len(pixels), len(pixels), 8)
    return bytes(out) + pixels


def wrap_wesys(payload):
    comp = zlib.compress(payload)
    hdr = b'WESYS\x00\x01\x00' + struct.pack('<II', len(comp), len(payload))
    return hdr + comp


def make_dpfilelist(cpk_names):
    buf = bytearray(16 + 48 * len(cpk_names))
    buf[0:4] = b'DPL\x00'
    struct.pack_into('<I', buf, 4, len(cpk_names))
    for idx, nm in enumerate(cpk_names):
        raw = nm.encode('utf-8')[:31] + b'\x00'
        off = 16 + idx * 48 + 16
        buf[off:off + len(raw)] = raw
    return bytes(buf)


def build_real_cpk(path, entries):
    """Build a minimal CRI CPK archive readable by `cpkread.Cpk`."""
    def make_utf_body(table_name, cols, rows):
        strings = bytearray(b'\x00')
        seen = {'': 0}

        def s_off(s):
            if s not in seen:
                seen[s] = len(strings)
                strings.extend(s.encode('utf-8') + b'\x00')
            return seen[s]

        tn = s_off(table_name)
        schema = bytearray()
        rlen = 0
        for cname, kind in cols:
            schema.append(0x50 | kind)
            schema.extend(struct.pack('>I', s_off(cname)))
            rlen += 8 if kind == 6 else 4

        rdata = bytearray()
        for row in rows:
            for (_, kind), val in zip(cols, row):
                if kind == 6:
                    rdata.extend(struct.pack('>Q', int(val)))
                elif kind == 4:
                    rdata.extend(struct.pack('>I', int(val)))
                else:
                    rdata.extend(struct.pack('>I', s_off(str(val))))

        rows_rel = 24 + len(schema)
        str_rel = rows_rel + len(rdata)
        dat_rel = str_rel + len(strings)
        hdr = bytearray(b'@UTF')
        hdr.extend(struct.pack('>I', dat_rel))
        hdr.extend(struct.pack('>III', rows_rel, str_rel, dat_rel))
        hdr.extend(struct.pack('>IHHI', tn, len(cols), rlen, len(rows)))
        return bytes(hdr + schema + rdata + strings)

    toc_pos = 0x800
    content_pos = 0x4000
    cpk_utf = make_utf_body(
        'CpkHeader',
        [('TocOffset', 6), ('ContentOffset', 6)],
        [(toc_pos, content_pos)],
    )
    toc_rows = []
    payloads = bytearray()
    cur_off = content_pos
    for full_name, data in entries.items():
        norm = full_name.replace('\\', '/').strip('/')
        dname, fname = (norm.rsplit('/', 1) if '/' in norm else ('', norm))
        toc_rows.append((dname, fname, len(data), len(data), cur_off - toc_pos))
        payloads.extend(data)
        cur_off += len(data)

    toc_utf = make_utf_body(
        'CpkTocInfo',
        [('DirName', 0xA), ('FileName', 0xA), ('FileSize', 4),
         ('ExtractSize', 4), ('FileOffset', 6)],
        toc_rows,
    )
    out = bytearray(content_pos)
    out[0:16] = b'CPK ' + struct.pack('<III', 0xFF, len(cpk_utf), 0)
    out[16:16 + len(cpk_utf)] = cpk_utf
    out[toc_pos:toc_pos + 16] = b'TOC ' + struct.pack('<III', 0xFF, len(toc_utf), 0)
    out[toc_pos + 16:toc_pos + 16 + len(toc_utf)] = toc_utf
    out.extend(payloads)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(out)
    return path


class FakeCpk(object):
    DATA = {}

    def __init__(self, path):
        self.path = path
        self.files = {n: dict(FileName=n, FileSize=len(v))
                      for n, v in FakeCpk.DATA.get(path, {}).items()}

    def read(self, name):
        return FakeCpk.DATA[self.path][name]


class Pes17FacesUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        faces.clear()
        FakeCpk.DATA = {}

        mods = {'cpkread': types.SimpleNamespace(Cpk=FakeCpk)}
        zp = os.path.join(ROOT, 'pes2017', 'dist', 'TheGaffer_pes2017_pc414.zip')
        if os.path.isfile(zp):
            with zipfile.ZipFile(zp) as z:
                m = types.ModuleType('dds')
                exec(compile(z.read('TheGaffer/lib/dds.py'), 'dds.py', 'exec'), m.__dict__)
                mods['dds'] = m
        self.patcher = mock.patch.dict(sys.modules, mods)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _make_fake_cpk(self, path, entries):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(b'CPK ')
        FakeCpk.DATA[path] = entries
        return path

    def test_module_is_strictly_offline_and_read_only(self):
        with open(faces.__file__, encoding='utf-8') as f:
            src = f.read()
        for bad in ('urllib', 'requests', 'socket.', 'http.client', 'https://', 'http://'):
            self.assertNotIn(bad, src)

    def test_dpfilelist_priority_and_loose_sider_override(self):
        game = os.path.join(self.root, 'Pro Evolution Soccer 2017')
        os.makedirs(os.path.join(game, 'Data'), exist_ok=True)
        os.makedirs(os.path.join(game, 'download'), exist_ok=True)
        exe = os.path.join(game, 'PES2017.exe')
        with open(exe, 'wb') as f:
            f.write(b'MZ')

        # Vanilla Data/dt14_win.cpk has 55246, 970, 7511
        self._make_fake_cpk(os.path.join(game, 'Data', 'dt14_win.cpk'), {
            'common/render/symbol/player/55246.png': PNG_VANILLA,
            'common/render/symbol/player/970.png': PNG_VANILLA,
            'common/render/symbol/player/7511.png': PNG_VANILLA,
        })
        # Patch base CPK overrides 55246 and 970
        self._make_fake_cpk(os.path.join(game, 'download', 'z_base_faces.cpk'), {
            'common/render/symbol/player/55246.png': PNG_PATCH_BASE,
            'common/render/symbol/player/970.png': PNG_PATCH_BASE,
        })
        # Later DpFileList CPK overrides 55246 (even though 'a_' sorts alphabetically first)
        self._make_fake_cpk(os.path.join(game, 'download', 'a_t99_minifaces_update.cpk'), {
            'common/render/symbol/player/55246.png': PNG_PATCH_TOP,
        })
        with open(os.path.join(game, 'download', 'DpFileList.bin'), 'wb') as f:
            f.write(make_dpfilelist(['z_base_faces.cpk', 'a_t99_minifaces_update.cpk']))

        # Sider livecpk overrides 970
        sider_dir = os.path.join(game, 'SiderAddons', 'Minifaces', 'common', 'render', 'symbol', 'player')
        os.makedirs(sider_dir, exist_ok=True)
        with open(os.path.join(game, 'sider.ini'), 'w', encoding='utf-8') as f:
            f.write('cpk.root = ".\\SiderAddons\\Minifaces"\n')
        with open(os.path.join(sider_dir, '000970.png'), 'wb') as f:
            f.write(PNG_LOOSE)

        cfg = {'pes_exe': exe}
        # 55246 -> later DpFileList CPK
        self.assertEqual(faces.face_img(55246, cfg), PNG_PATCH_TOP)
        # 970 -> Sider livecpk loose file (zero-padded 000970.png!)
        self.assertEqual(faces.face_img(970, cfg), PNG_LOOSE)
        # 7511 -> Vanilla Data/dt14_win.cpk fallback
        self.assertEqual(faces.face_img(7511, cfg), PNG_VANILLA)
        # High-bit ML player ID fallback (bit 20 set -> base pid 55246)
        self.assertEqual(faces.face_img((1 << 20) | 55246, cfg), PNG_PATCH_TOP)

    def test_excludes_3d_face_meshes_crests_kits_and_regens(self):
        patch_dir = os.path.join(self.root, 'patch')
        self._make_fake_cpk(os.path.join(patch_dir, 'download', 'mixed.cpk'), {
            # 3D head UV mesh textures -- MUST NOT be treated as 2D portraits!
            'common/character0/model/character/face/real/55246/face_bsm.dds': PNG_VANILLA,
            'Asset/model/character/face/real/55246/55246.png': PNG_VANILLA,
            # Club crests, kits, staff coaches, FL26 generic regens -- MUST NOT match!
            'common/render/symbol/flag/emblem_0201_r.png': PNG_VANILLA,
            'Asset/model/character/uniform/texture/#windx11/u0201p1.ftex': PNG_VANILLA,
            'common/render/symbol/coach/coach_201.png': PNG_VANILLA,
            'common/render/symbol/player/regen/89.dds': PNG_VANILLA,
            # Valid 2D player portrait & coachML fallback:
            'common/render/symbol/player/player_147337.png': PNG_PATCH_TOP,
            'common/render/symbol/coachML/4073.png': PNG_PATCH_BASE,
        })
        logos_dir = os.path.join(patch_dir, 'logos')
        os.makedirs(logos_dir, exist_ok=True)
        with open(os.path.join(logos_dir, '201.png'), 'wb') as f:
            f.write(PNG_LOOSE)

        cfg = {'pes17_patch_dir': patch_dir}
        self.assertIsNone(faces.face_img(55246, cfg))
        self.assertIsNone(faces.face_img(201, cfg))
        self.assertIsNone(faces.face_img(89, cfg))
        self.assertEqual(faces.face_img(147337, cfg), PNG_PATCH_TOP)
        self.assertEqual(faces.face_img(4073, cfg), PNG_PATCH_BASE)

    def test_wesys_dds_rgb24_and_mismatched_extensions_decode_to_png(self):
        patch_dir = os.path.join(self.root, 'patch_tex')
        pdir = os.path.join(patch_dir, 'livecpk', 'faces', 'common', 'render', 'symbol', 'player')
        os.makedirs(pdir, exist_ok=True)
        # 1) Loose WESYS-wrapped RGBA DDS
        with open(os.path.join(pdir, '55246.dds'), 'wb') as f:
            f.write(wrap_wesys(make_rgba_dds(2, 2)))
        # 2) `.dds` file actually containing PNG bytes
        with open(os.path.join(pdir, '55255.dds'), 'wb') as f:
            f.write(PNG_PATCH_TOP)
        # 3) `.png` file actually containing 24-bit RGB DDS bytes
        with open(os.path.join(pdir, '169457.png'), 'wb') as f:
            f.write(make_rgb24_dds(2, 2))
        # 4) WESYS-wrapped FTEX is decoded by the shipped Fox reader.
        with open(os.path.join(pdir, '147337.ftex'), 'wb') as f:
            f.write(wrap_wesys(make_ftex()))
        # 5) Corrupt DDS fails gracefully
        with open(os.path.join(pdir, '99999.dds'), 'wb') as f:
            f.write(b'DDS broken')

        cfg = {'pes17_patch_dir': patch_dir}
        for pid in (55246, 55255, 169457, 147337):
            got = faces.face_img(pid, cfg)
            self.assertIsNotNone(got, 'failed to decode pid %d' % pid)
            self.assertEqual(got[:8], b'\x89PNG\r\n\x1a\n')
        self.assertIsNone(faces.face_img(99999, cfg))

    def test_download_selection_includes_sibling_data_and_sider_roots(self):
        game = os.path.join(self.root, 'game')
        dl = os.path.join(game, 'download')
        data = os.path.join(game, 'Data')
        os.makedirs(dl)
        os.makedirs(data)
        exe = os.path.join(game, 'PES2017.exe')
        with open(exe, 'wb') as f:
            f.write(b'MZ')
        self._make_fake_cpk(os.path.join(data, 'vanilla.cpk'), {
            'common/render/symbol/player/55246.png': PNG_VANILLA,
        })
        self._make_fake_cpk(os.path.join(dl, 'patch.cpk'), {
            'common/render/symbol/player/970.png': PNG_PATCH_BASE,
        })
        loose = os.path.join(game, 'SiderAddons', 'livecpk', 'mini',
                             'common', 'render', 'symbol', 'player')
        os.makedirs(loose)
        with open(os.path.join(loose, '147337.png'), 'wb') as f:
            f.write(PNG_LOOSE)
        for cfg in ({'pes17_patch_dir': dl}, {'pes17_patch_dir': dl, 'pes_exe': exe}):
            with self.subTest(cfg=cfg):
                faces.clear()
                roots, auto = faces.roots_for(cfg)
                self.assertFalse(auto)
                self.assertIn(data, roots)
                self.assertIn(os.path.join(game, 'SiderAddons'), roots)
                self.assertEqual(faces.face_img(55246, cfg), PNG_VANILLA)
                self.assertEqual(faces.face_img(970, cfg), PNG_PATCH_BASE)
                self.assertEqual(faces.face_img(147337, cfg), PNG_LOOSE)

    def test_separate_explicit_patch_precedes_game_fallback(self):
        patch = os.path.join(self.root, 'custom-pack')
        game = os.path.join(self.root, 'game')
        dl = os.path.join(game, 'download')
        os.makedirs(dl)
        exe = os.path.join(game, 'PES2017.exe')
        with open(exe, 'wb') as f:
            f.write(b'MZ')
        self._make_fake_cpk(os.path.join(patch, 'pack.cpk'), {
            'common/render/symbol/player/55246.png': PNG_PATCH_TOP,
        })
        self._make_fake_cpk(os.path.join(dl, 'mounted.cpk'), {
            'common/render/symbol/player/55246.png': PNG_VANILLA,
            'common/render/symbol/player/970.png': PNG_PATCH_BASE,
        })
        with open(os.path.join(dl, 'DpFileList.bin'), 'wb') as f:
            f.write(make_dpfilelist(['mounted.cpk']))
        cfg = {'pes17_patch_dir': patch, 'pes_exe': exe}
        self.assertEqual(faces.face_img(55246, cfg), PNG_PATCH_TOP)
        self.assertEqual(faces.face_img(970, cfg), PNG_PATCH_BASE)
        # A missing explicit folder must not suppress a valid configured game.
        cfg['pes17_patch_dir'] = os.path.join(self.root, 'missing')
        self.assertEqual(faces.face_img(970, cfg), PNG_PATCH_BASE)
        self.assertFalse(faces.report(cfg)['explicit_valid'])

    def test_unreadable_top_asset_falls_back_and_report_tests_decode(self):
        game = os.path.join(self.root, 'game')
        dl = os.path.join(game, 'download')
        data = os.path.join(game, 'Data')
        os.makedirs(dl)
        os.makedirs(data)
        self._make_fake_cpk(os.path.join(dl, 'patch.cpk'), {
            'common/render/symbol/player/55246.png': PNG_PATCH_TOP[:-7],
            'common/render/symbol/player/970.png': b'DDS broken',
        })
        self._make_fake_cpk(os.path.join(data, 'vanilla.cpk'), {
            'common/render/symbol/player/55246.png': PNG_VANILLA,
        })
        cfg = {'pes17_patch_dir': game}
        self.assertEqual(faces.face_img(55246, cfg), PNG_VANILLA)
        self.assertIsNone(faces.face_img(970, cfg))
        high_bit = (1 << 20) | 55246
        with mock.patch.object(faces, '_player_names', return_value={}), \
             mock.patch.object(faces, '_squad_file', return_value='/save/ML00000012'), \
             mock.patch.object(faces, '_active_squad', return_value=[
                 (high_bit, 4, 'Example A'), (970, 10, 'Example B'), (999, 1, 'Example C')]) as squad:
            rep = faces.report(cfg, slot='ML00000012')
        squad.assert_called_once_with(cfg, {}, 'ML00000012')
        self.assertEqual(rep['squad_slot'], 'ML00000012')
        self.assertEqual((rep['squad_total'], rep['squad_matched'], rep['squad_decoded']), (3, 2, 1))
        self.assertEqual((rep['faces_found'], rep['sample_tested'], rep['sample_decoded']), (2, 2, 1))
        self.assertTrue(rep['available'])
        self.assertTrue(next(r for r in rep['sample'] if r['id'] == high_bit)['fallback_used'])
        self.assertFalse(next(r for r in rep['sample'] if r['id'] == 970)['decoded'])
        self.assertGreaterEqual(len(rep['decode_errors']), 2)
        self.assertFalse(faces.report(cfg, slot='../ML00000012')['ok'])

    def test_rejects_impossible_texture_dimensions_before_decoding(self):
        dds = bytearray(make_rgba_dds())
        struct.pack_into('<II', dds, 12, 100000, 100000)
        fox = bytearray(make_ftex())
        struct.pack_into('<HH', fox, 10, 65000, 65000)
        with mock.patch.dict(sys.modules, {
            'dds': types.SimpleNamespace(dds_to_png=mock.Mock(side_effect=AssertionError('unsafe DDS'))),
            'ftex': types.SimpleNamespace(decode=mock.Mock(side_effect=AssertionError('unsafe FTEX'))),
        }):
            self.assertIsNone(faces._to_png(bytes(dds), 'dds'))
            self.assertIsNone(faces._to_png(bytes(fox), 'ftex'))

    def test_indexed_but_corrupt_png_is_not_advertised_as_available(self):
        patch = os.path.join(self.root, 'minifaces')
        os.makedirs(patch)
        with open(os.path.join(patch, '55246.png'), 'wb') as f:
            f.write(PNG_PATCH_TOP[:-3])
        r = faces.report({'pes17_patch_dir': patch})
        self.assertEqual(r['faces_found'], 1)
        self.assertEqual((r['sample_tested'], r['sample_decoded']), (1, 0))
        self.assertFalse(r['available'])
        self.assertIn('Corrupt', r['decode_errors'][0]['error'])

    def test_parallel_requests_build_one_index_and_reuse_cpk_toc(self):
        patch = os.path.join(self.root, 'pack')
        archive = self._make_fake_cpk(os.path.join(patch, 'faces.cpk'), {
            'common/render/symbol/player/%d.png' % (50000 + i): PNG_VANILLA
            for i in range(20)
        })
        calls = []
        class CountingCpk(FakeCpk):
            def __init__(self, path):
                calls.append(path)
                time.sleep(0.025)
                super().__init__(path)
        cfg = {'pes17_patch_dir': patch}
        with mock.patch.dict(sys.modules, {'cpkread': types.SimpleNamespace(Cpk=CountingCpk)}), \
             mock.patch.object(faces, '_scan_cpk', wraps=faces._scan_cpk) as scan_cpk, \
             mock.patch.object(faces, '_signature', wraps=faces._signature) as signature:
            with ThreadPoolExecutor(max_workers=20) as pool:
                got = list(pool.map(lambda i: faces.face_img(50000 + i, cfg), range(20)))
            self.assertEqual(got, [PNG_VANILLA] * 20)
            self.assertEqual(calls, [archive])
            self.assertEqual(scan_cpk.call_count, 1)
            self.assertEqual(signature.call_count, 1)
            # Same archive signature and ID, changed contents: only a forced
            # scan should evict both TOC and previously decoded portrait.
            FakeCpk.DATA[archive]['common/render/symbol/player/50000.png'] = PNG_PATCH_TOP
            self.assertEqual(faces.face_img(50000, cfg), PNG_VANILLA)
            faces.report(cfg, force=True)
            self.assertEqual(faces.face_img(50000, cfg), PNG_PATCH_TOP)
            self.assertEqual(calls, [archive, archive])
        self.assertLessEqual(len(faces._CPK), faces.MAX_CACHED_CPKS)

    def test_archive_errors_and_bounded_toc_cache_are_reported(self):
        patch = os.path.join(self.root, 'pack')
        for i in range(faces.MAX_CACHED_CPKS + 3):
            self._make_fake_cpk(os.path.join(patch, '%02d.cpk' % i), {})
        bad = self._make_fake_cpk(os.path.join(patch, 'broken.cpk'), {})
        class SomeBroken(FakeCpk):
            def __init__(self, path):
                if path == bad:
                    raise ValueError('unsupported CPK index')
                super().__init__(path)
        with mock.patch.dict(sys.modules, {'cpkread': types.SimpleNamespace(Cpk=SomeBroken)}):
            rep = faces.report({'pes17_patch_dir': patch})
        self.assertTrue(any('unsupported CPK index' in e for e in rep['errors']))
        self.assertLessEqual(len(faces._CPK), faces.MAX_CACHED_CPKS)

    def test_configured_edit_names_take_priority_over_stale_app_database(self):
        app = os.path.join(self.root, 'app')
        db = os.path.join(app, 'data', 'pes17')
        os.makedirs(db)
        with open(os.path.join(db, 'players.json'), 'w', encoding='utf-8') as f:
            json.dump([[55246, 'Old unrelated player']], f)
        sd = os.path.join(self.root, 'save')
        os.makedirs(sd)
        edit = os.path.join(sd, 'EDIT00000000')
        with open(edit, 'wb') as f:
            f.write(b'edit fixture')
        fake = types.SimpleNamespace(_edit_data=lambda path: b'parsed',
                                     parse_edit=lambda data: [{'id': 55246, 'name': 'Current EDIT player'}])
        with mock.patch.object(faces, 'HERE', app), mock.patch.dict(sys.modules, {'pes17': fake}):
            self.assertEqual(faces._player_names({'save_dir': sd})[55246], 'Current EDIT player')


class UiAndLiveServerMinifaceTests(unittest.TestCase):
    def test_classic_and_tools_ui_have_face_badges_and_valid_js(self):
        tools_p = os.path.join(ROOT, 'pes2017', 'overlay', 'static', 'pes17.html')
        with open(tools_p, encoding='utf-8') as f:
            tools = f.read()

        for removed in ('pes17-dashboard.html', 'game-skin.css', 'game-skin.js'):
            self.assertFalse(os.path.exists(
                os.path.join(ROOT, 'pes2017', 'overlay', 'static', removed)), removed)

        self.assertIn('function faceBadge(', tools)
        self.assertIn('/api/pes17/face?pid=', tools)
        self.assertIn('/api/pes17/faces', tools)
        self.assertIn('pf-wrap', tools)
        self.assertNotIn('https://', tools)
        self.assertNotIn('game-skin', tools)

        # Ensure zero duplicate IDs in pes17.html
        ids = re.findall(r'\bid="([^"]+)"', tools)
        dupes = [k for k in set(ids) if ids.count(k) > 1]
        self.assertEqual(dupes, [])

        # Syntax check inline JavaScript of tools page if node is installed
        if shutil.which('node'):
            scripts = re.findall(r'<script(?![^>]*src)[^>]*>([\s\S]*?)</script>', tools)
            self.assertEqual(len(scripts), 1)
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as tf:
                tf.write(scripts[0])
                js_path = tf.name
            try:
                res = subprocess.run(['node', '--check', js_path], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, 'tools JS syntax error: %s' % res.stderr)
            finally:
                os.unlink(js_path)

    def test_live_built_server_serves_pes17_minifaces_end_to_end(self):
        zp = os.path.join(ROOT, 'pes2017', 'dist', 'TheGaffer_pes2017_pc414.zip')
        if not os.path.isfile(zp):
            self.skipTest('dist zip not built yet')

        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(zp) as z:
                z.extractall(tmp)
            app_dir = os.path.join(tmp, 'TheGaffer')
            # A broken old on-disk cache must not be re-served by the legacy
            # game-face path after the PES 2017 reader rejects it.
            stale = os.path.join(app_dir, 'data', 'gface')
            os.makedirs(stale, exist_ok=True)
            with open(os.path.join(stale, '999991.png'), 'wb') as f:
                f.write(PNG_PATCH_TOP[:-5])

            save_dir = os.path.join(tmp, 'save')
            os.makedirs(save_dir, exist_ok=True)
            real_saves = os.environ.get('PES17_REAL_SAVES') or ''
            has_real = (real_saves
                        and os.path.isfile(os.path.join(real_saves, 'ML00000011'))
                        and os.path.isfile(os.path.join(real_saves, 'EDIT00000000')))
            if has_real:
                shutil.copy2(os.path.join(real_saves, 'ML00000011'),
                             os.path.join(save_dir, 'ML00000011'))
                # A newer slot must not override the one selected in the report.
                other = os.path.join(save_dir, 'ML00000012')
                shutil.copy2(os.path.join(real_saves, 'ML00000011'), other)
                os.utime(other, (time.time() + 5, time.time() + 5))
                shutil.copy2(os.path.join(real_saves, 'EDIT00000000'),
                             os.path.join(save_dir, 'EDIT00000000'))
            else:
                import sample
                import pescrypt
                parts = sample.make_parts17()
                with open(os.path.join(save_dir, 'ML00000011'), 'wb') as f:
                    f.write(pescrypt.encrypt_parts(parts, pescrypt.KEY_PES17))

            game_dir = os.path.join(tmp, 'Pro Evolution Soccer 2017')
            os.makedirs(os.path.join(game_dir, 'Data'), exist_ok=True)
            os.makedirs(os.path.join(game_dir, 'download'), exist_ok=True)
            exe_path = os.path.join(game_dir, 'PES2017.exe')
            with open(exe_path, 'wb') as f:
                f.write(b'MZ')

            # Vanilla Data CPK + Patch DpFileList CPKs with real CRI @UTF TOC
            build_real_cpk(os.path.join(game_dir, 'Data', 'dt14_win.cpk'), {
                'common/render/symbol/player/55246.dds': wrap_wesys(PNG_VANILLA),
                'common/render/symbol/player/970.dds': wrap_wesys(make_rgba_dds(2, 2)),
            })
            build_real_cpk(os.path.join(game_dir, 'download', 't99p17_miniface.cpk'), {
                'common/render/symbol/player/55246.png': wrap_wesys(PNG_PATCH_TOP),
                'common/render/symbol/player/147337.png': PNG_PATCH_BASE,
            })
            with open(os.path.join(game_dir, 'download', 'DpFileList.bin'), 'wb') as f:
                f.write(make_dpfilelist(['t99p17_miniface.cpk']))

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]

            with open(os.path.join(app_dir, 'config.json'), 'w', encoding='utf-8') as f:
                json.dump({
                    'save_dir': save_dir,
                    'pes_exe': exe_path,
                    'pes17_patch_dir': os.path.join(game_dir, 'download'),
                    'pes17_only': True,
                    'wiki_web': False,
                    'port': port,
                }, f)

            proc = subprocess.Popen(
                [sys.executable, 'server.py', '--no-browser', '--host', '127.0.0.1', '--port', str(port)],
                cwd=app_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            try:
                base = 'http://127.0.0.1:%d' % port
                ready = False
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(base + '/api/pes17/mode', timeout=1) as resp:
                            if json.loads(resp.read().decode('utf-8')).get('pes17'):
                                ready = True
                                break
                    except Exception:
                        time.sleep(0.1)
                self.assertTrue(ready, 'server did not enter pes17 mode on startup')

                # 0) `/` serves pure Classic UI (`static/index.html`) with `/api/wiki/img?pid=`
                #    portraits, and `pes17-dashboard.html` / `game-skin` are gone (404)
                with urllib.request.urlopen(base + '/', timeout=5) as resp:
                    classic_html = resp.read().decode('utf-8')
                self.assertIn('function av(pid,sz)', classic_html)
                self.assertIn('/api/wiki/img?pid=', classic_html)
                self.assertIn('/pes17-face-refresh.js', classic_html)
                self.assertIn('id="pes17ToolsBtn"', classic_html)
                self.assertNotIn('game-skin', classic_html)
                for removed_url in ('/pes17-dashboard.html', '/game-skin.css', '/game-skin.js'):
                    try:
                        urllib.request.urlopen(base + removed_url, timeout=3)
                        self.fail('expected 404 for ' + removed_url)
                    except urllib.error.HTTPError as he:
                        self.assertEqual(he.code, 404, removed_url)

                # 1) `/api/wiki/img?pid=55246` serves the patched T99 miniface (overriding Data/dt14_win.cpk)
                with urllib.request.urlopen(base + '/api/wiki/img?pid=55246', timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(resp.headers.get_content_type(), 'image/png')
                    self.assertEqual(resp.headers.get('Cache-Control'), 'no-store')
                    self.assertEqual(resp.read(), PNG_PATCH_TOP)

                # 2) `/api/wiki/img?pid=970` decodes WESYS-wrapped DDS from Data/dt14_win.cpk into valid PNG
                with urllib.request.urlopen(base + '/api/wiki/img?pid=970', timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(resp.headers.get_content_type(), 'image/png')
                    self.assertEqual(resp.read()[:8], b'\x89PNG\r\n\x1a\n')

                # 3) `/api/pes17/face?pid=147337` serves a synthetic image for that real save ID.
                with urllib.request.urlopen(base + '/api/pes17/face?pid=147337', timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(resp.headers.get('Cache-Control'), 'no-store')
                    self.assertEqual(resp.read(), PNG_PATCH_BASE)

                # A corrupt legacy cache is never sent as if it were a portrait.
                with self.assertRaises(urllib.error.HTTPError) as bad_image:
                    urllib.request.urlopen(base + '/api/wiki/img?pid=999991', timeout=5)
                self.assertEqual(bad_image.exception.code, 404)

                # 4) Diagnose the explicitly selected slot, not the newest one.
                with urllib.request.urlopen(base + '/api/pes17/faces?slot=ML00000011', timeout=5) as resp:
                    rep = json.loads(resp.read().decode('utf-8'))
                self.assertTrue(rep['available'])
                self.assertEqual(rep['faces_found'], 4)
                self.assertEqual((rep['sample_tested'], rep['sample_decoded']), (4, 3))
                self.assertTrue(any(x['id'] == 999991 for x in rep['decode_errors']))
                self.assertEqual(rep['squad_slot'], 'ML00000011')
                self.assertTrue(any(r.endswith(os.path.join(game_dir, 'Data')) for r in rep['roots']))
                if has_real:
                    self.assertEqual(rep['squad_total'], 26)
                    self.assertEqual(rep['squad_matched'], 3)
                    self.assertEqual(rep['squad_decoded'], 3)
                    self.assertEqual(rep['players_matched'], 3)
                    with urllib.request.urlopen(base + '/api/pes17/faces', timeout=5) as resp:
                        newest = json.loads(resp.read().decode('utf-8'))
                    self.assertEqual(newest['squad_slot'], 'ML00000012')

                # 5) `/api/pes17/info` includes EDIT positions on squad players
                if has_real:
                    with urllib.request.urlopen(base + '/api/pes17/info?slot=ML00000011', timeout=8) as resp:
                        inf = json.loads(resp.read().decode('utf-8'))
                    self.assertTrue(inf['ok'])
                    self.assertEqual(inf['squad'][0]['id'], 55246)
                    self.assertEqual(inf['squad'][0]['pos'], 'CB')
                    fabio = next(p for p in inf['squad'] if p['id'] == 4039)
                    self.assertEqual(fabio['pos'], 'GK')

                # 6) Harvesting `['face']` copies decoded PNGs into `data/pes17/harvest/face`
                req = urllib.request.Request(
                    base + '/api/pes17/assets/extract',
                    data=json.dumps({'classes': ['face'], 'limit': 50}).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    hr = json.loads(resp.read().decode('utf-8'))
                self.assertTrue(hr['ok'])
                self.assertGreaterEqual(hr['written'], 2)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                if proc.stdout:
                    proc.stdout.close()


if __name__ == '__main__':
    unittest.main()
