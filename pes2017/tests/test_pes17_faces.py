"""Tests for PES 2017 player mini-faces (backend scanner/decoder, live server, and UI)."""
import base64
import json
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

PNG_VANILLA = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
PNG_PATCH_BASE = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==')
PNG_PATCH_TOP = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEklEQVR42mNk+M9QzwAEjDAGACCcAv8c8L6AAAAAAElFTkSuQmCC')
PNG_LOOSE = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


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
        # 4) Corrupt DDS fails gracefully
        with open(os.path.join(pdir, '99999.dds'), 'wb') as f:
            f.write(b'DDS broken')

        cfg = {'pes17_patch_dir': patch_dir}
        for pid in (55246, 55255, 169457):
            got = faces.face_img(pid, cfg)
            self.assertIsNotNone(got, 'failed to decode pid %d' % pid)
            self.assertEqual(got[:8], b'\x89PNG\r\n\x1a\n')
        self.assertIsNone(faces.face_img(99999, cfg))


class UiAndLiveServerMinifaceTests(unittest.TestCase):
    def test_classic_and_tools_ui_have_face_badges_and_valid_js(self):
        tools_p = os.path.join(ROOT, 'pes2017', 'overlay', 'static', 'pes17.html')
        with open(tools_p, encoding='utf-8') as f:
            tools = f.read()

        for removed in ('pes17-dashboard.html', 'game-skin.css', 'game-skin.js'):
            self.assertFalse(os.path.exists(
                os.path.join(ROOT, 'pes2017', 'overlay', 'static', removed)), removed)

        self.assertIn('function faceBadge(', tools)
        self.assertIn('/api/wiki/img?pid=', tools)
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

            save_dir = os.path.join(tmp, 'save')
            os.makedirs(save_dir, exist_ok=True)
            real_saves = os.environ.get('PES17_REAL_SAVES') or ''
            has_real = (real_saves
                        and os.path.isfile(os.path.join(real_saves, 'ML00000011'))
                        and os.path.isfile(os.path.join(real_saves, 'EDIT00000000')))
            if has_real:
                shutil.copy2(os.path.join(real_saves, 'ML00000011'),
                             os.path.join(save_dir, 'ML00000011'))
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
                    self.assertEqual(resp.read(), PNG_PATCH_TOP)

                # 2) `/api/wiki/img?pid=970` decodes WESYS-wrapped DDS from Data/dt14_win.cpk into valid PNG
                with urllib.request.urlopen(base + '/api/wiki/img?pid=970', timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(resp.headers.get_content_type(), 'image/png')
                    self.assertEqual(resp.read()[:8], b'\x89PNG\r\n\x1a\n')

                # 3) `/api/pes17/face?pid=147337` serves Jobe Bellingham's portrait
                with urllib.request.urlopen(base + '/api/pes17/face?pid=147337', timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(resp.read(), PNG_PATCH_BASE)

                # 4) `/api/pes17/faces` returns diagnostic report with squad match counts
                with urllib.request.urlopen(base + '/api/pes17/faces', timeout=5) as resp:
                    rep = json.loads(resp.read().decode('utf-8'))
                self.assertTrue(rep['available'])
                self.assertEqual(rep['faces_found'], 3)
                if has_real:
                    self.assertEqual(rep['squad_total'], 26)
                    self.assertEqual(rep['squad_matched'], 3)
                    self.assertEqual(rep['players_matched'], 3)

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
