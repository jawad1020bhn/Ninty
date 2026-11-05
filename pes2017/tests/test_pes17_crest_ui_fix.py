"""Regression tests for PES 2017 club-logo discovery, priority, and UI rendering."""
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
import urllib.parse
import urllib.request
import zipfile
import zlib
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'overlay', 'lib'))
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'tests'))

import pes17  # noqa: E402
import pes17_assets as assets  # noqa: E402
import pes17_crests as crests  # noqa: E402
import pes17_setup as setup  # noqa: E402

PNG_VANILLA = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
PNG_PATCH_OLD = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==')
PNG_PATCH_NEW = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR42mP8z8AARIQBEwMDAwMoAF/gBv81R1MAAAAASUVORK5CYII=')


def make_dds(w=2, h=2, rgba=(0, 80, 220, 255)):
    hdr = bytearray(128)
    hdr[0:4] = b'DDS '
    struct.pack_into('<I', hdr, 4, 124)
    struct.pack_into('<II', hdr, 12, h, w)
    struct.pack_into('<I', hdr, 76, 32)
    struct.pack_into('<I', hdr, 88, 32)
    struct.pack_into('<IIII', hdr, 92, 0xff, 0xff00, 0xff0000, 0xff000000)
    return bytes(hdr) + bytes(rgba) * (w * h)


def make_dpfilelist(cpk_names):
    buf = bytearray(16 + 48 * len(cpk_names))
    buf[0:4] = b'DpFl'
    struct.pack_into('<I', buf, 4, len(cpk_names))
    for i, nm in enumerate(cpk_names):
        raw = nm.encode('utf-8')[:31] + b'\x00'
        off = 16 + i * 48 + 16
        buf[off:off + len(raw)] = raw
    return bytes(buf)


def build_real_cpk(path, entries):
    """Write a minimal uncompressed CRI CPK with a valid `TOC ` table that `cpkread.Cpk` reads."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(_encode_cpk_bytes(entries))
    return path


def _encode_cpk_bytes(entries):
    """Build a valid uncompressed CPK binary readable by `lib/cpkread.py`."""
    def make_utf_Body(table_name, cols, rows):
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

        # cpkread._utf(buf):
        # rows_off, str_off, data_off = >III at 8..20 (relative to +8)
        # tname_off = >I at 20..24; ncols, rlen = >HH at 24..28; nrows = >I at 28..32; schema at 32
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
    cpk_utf = make_utf_Body(
        'CpkHeader',
        [('TocOffset', 6), ('ContentOffset', 6)],
        [(toc_pos, content_pos)],
    )
    toc_rows = []
    payloads = bytearray()
    cur_off = content_pos
    for full_name, data in entries.items():
        norm = full_name.strip('/')
        dname, fname = (norm.rsplit('/', 1) if '/' in norm else ('', norm))
        toc_rows.append((dname, fname, len(data), len(data), cur_off - toc_pos))
        payloads.extend(data)
        cur_off += len(data)

    toc_utf = make_utf_Body(
        'CpkTocInfo',
        [('DirName', 0xA), ('FileName', 0xA), ('FileSize', 4),
         ('ExtractSize', 4), ('FileOffset', 6)],
        toc_rows,
    )
    assert toc_pos + 16 + len(toc_utf) <= content_pos
    out = bytearray(content_pos)
    out[0:16] = b'CPK ' + struct.pack('<III', 0xFF, len(cpk_utf), 0)
    out[16:16 + len(cpk_utf)] = cpk_utf
    out[toc_pos:toc_pos + 16] = b'TOC ' + struct.pack('<III', 0xFF, len(toc_utf), 0)
    out[toc_pos + 16:toc_pos + 16 + len(toc_utf)] = toc_utf
    out.extend(payloads)
    return bytes(out)


class FakeCpk(object):
    DATA = {}

    def __init__(self, path):
        self.path = path
        self.files = {n: dict(FileName=n, FileSize=len(v))
                      for n, v in FakeCpk.DATA.get(path, {}).items()}

    def read(self, name):
        return FakeCpk.DATA[self.path][name]


class CrestBackendFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.db = os.path.join(self.root, 'app')
        os.makedirs(os.path.join(self.db, 'data', 'pes17'))
        with open(os.path.join(self.db, 'data', 'pes17', 'teamids.json'), 'w',
                  encoding='utf-8') as f:
            json.dump({
                '101': 'Arsenal FC',
                '201': 'Birmingham City FC',
                '390': 'Sunderland \u0391FC',
                '8': 'France',
            }, f)
        self.old_here = crests.HERE
        crests.HERE = self.db
        self.addCleanup(setattr, crests, 'HERE', self.old_here)
        crests.clear()
        zp = os.path.join(ROOT, 'pes2017', 'dist', 'TheGaffer_pes2017_pc414.zip')
        if os.path.isfile(zp):
            with zipfile.ZipFile(zp) as z:
                m = types.ModuleType('dds')
                exec(compile(z.read('TheGaffer/lib/dds.py'), 'dds.py', 'exec'), m.__dict__)
            sys.modules['dds'] = m
            self.addCleanup(sys.modules.pop, 'dds', None)
        FakeCpk.DATA = {}
        self.cpk_mock = mock.patch.dict(sys.modules, {'cpkread': types.SimpleNamespace(Cpk=FakeCpk)})
        self.cpk_mock.start()
        self.addCleanup(self.cpk_mock.stop)

    def _put_cpk(self, path, entries):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(b'CPK ')
        FakeCpk.DATA[path] = entries
        return path

    def test_pes17_emblem_naming_and_variant_ranking(self):
        patch = os.path.join(self.root, 'patch')
        self._put_cpk(os.path.join(patch, 'download', 't99_emblem.cpk'), {
            'common/render/symbol/flag/emblem_0201_b.png': PNG_VANILLA,
            'common/render/symbol/flag/emblem_0201_r_l.png': PNG_PATCH_OLD,
            'common/render/symbol/flag/emblem_0201_r.png': PNG_PATCH_NEW,
            'common/render/symbol/flag/flag_0008.png': PNG_PATCH_OLD,
        })
        cfg = {'pes17_patch_dir': patch}
        self.assertEqual(crests.crest_img('Birmingham City FC', cfg), PNG_PATCH_NEW)
        self.assertEqual(crests.crest_img('France', cfg), PNG_PATCH_OLD)
        cls, aid, var, _, usable, _ = assets.classify('common/render/symbol/flag/emblem_0201_r.png')
        self.assertEqual((cls, aid, var, usable), ('crest', 201, 'r', 'MAP'))

    def test_dpfilelist_override_order_and_download_beats_vanilla_data(self):
        game = os.path.join(self.root, 'Pro Evolution Soccer 2017')
        os.makedirs(os.path.join(game, 'Data'), exist_ok=True)
        os.makedirs(os.path.join(game, 'download'), exist_ok=True)
        with open(os.path.join(game, 'PES2017.exe'), 'wb') as f:
            f.write(b'MZ')
        self._put_cpk(os.path.join(game, 'Data', 'dt36_win.cpk'), {
            'common/render/symbol/flag/emblem_0201_r.png': PNG_VANILLA,
            'common/render/symbol/flag/emblem_0101_r.png': PNG_VANILLA,
        })
        self._put_cpk(os.path.join(game, 'download', 'z_base_emblems.cpk'), {
            'common/render/symbol/flag/emblem_0201_r.png': PNG_PATCH_OLD,
        })
        self._put_cpk(os.path.join(game, 'download', 'a_update_v20.cpk'), {
            'common/render/symbol/flag/emblem_0201_r_l.png': PNG_PATCH_NEW,
        })
        # Even though `a_update_v20.cpk` sorts alphabetically BEFORE `z_base_emblems.cpk`,
        # DpFileList.bin mounts `a_update_v20.cpk` LAST, so it must win!
        with open(os.path.join(game, 'download', 'DpFileList.bin'), 'wb') as f:
            f.write(make_dpfilelist(['z_base_emblems.cpk', 'a_update_v20.cpk']))

        cfg = {'pes_exe': os.path.join(game, 'PES2017.exe')}
        rep = crests.report(cfg, True)
        self.assertEqual(rep['cpk_archives'], 3)   # never double-walks download/ or Data/
        self.assertEqual(crests.crest_img('Birmingham City FC', cfg), PNG_PATCH_NEW)
        # Vanilla Data/dt36_win.cpk still serves clubs not overridden in download/
        self.assertEqual(crests.crest_img('Arsenal FC', cfg), PNG_VANILLA)

    def test_magic_bytes_and_loose_wesys_decoding(self):
        patch = os.path.join(self.root, 'sider_patch')
        flag_dir = os.path.join(patch, 'livecpk', 'logos', 'common', 'render', 'symbol', 'flag')
        os.makedirs(flag_dir, exist_ok=True)
        # 1) Loose WESYS-wrapped PNG named .dds
        hdr = bytearray(16)
        hdr[0:5] = b'WESYS'
        with open(os.path.join(flag_dir, 'emblem_0201_r.dds'), 'wb') as f:
            f.write(bytes(hdr) + zlib.compress(PNG_PATCH_NEW))
        # 2) Raw DDS texture stored inside a .png filename
        with open(os.path.join(flag_dir, 'emblem_0101_r.png'), 'wb') as f:
            f.write(make_dds())
        cfg = {'pes17_patch_dir': patch}
        self.assertEqual(crests.crest_img('Birmingham City FC', cfg), PNG_PATCH_NEW)
        ars = crests.crest_img('Arsenal FC', cfg)
        self.assertTrue(ars and ars.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_homoglyph_club_names_and_teamids_cache_invalidation(self):
        patch = os.path.join(self.root, 'homoglyph_patch')
        self._put_cpk(os.path.join(patch, 'download', 't99.cpk'), {
            'common/render/symbol/flag/emblem_0390_r.png': PNG_PATCH_NEW,
            'common/render/symbol/flag/emblem_0777_r.png': PNG_PATCH_OLD,
        })
        cfg = {'pes17_patch_dir': patch}
        # Matches both Greek-Alpha `'Sunderland ΑFC'` and plain ASCII `'Sunderland AFC'`
        self.assertEqual(crests.crest_img('Sunderland \u0391FC', cfg), PNG_PATCH_NEW)
        self.assertEqual(crests.crest_img('Sunderland AFC', cfg), PNG_PATCH_NEW)
        self.assertIsNone(crests.crest_img('New Patched Club FC', cfg))

        # Updating teamids.json must automatically refresh scan() without manual clear()
        tp = os.path.join(self.db, 'data', 'pes17', 'teamids.json')
        time.sleep(0.01)
        with open(tp, 'w', encoding='utf-8') as f:
            json.dump({'777': 'New Patched Club FC'}, f)
        self.assertEqual(crests.crest_img('New Patched Club FC', cfg), PNG_PATCH_OLD)


class SetupAndEditTeamIdTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_game_folder_autodetect_and_fl26_exe_rejection(self):
        self.assertTrue(setup.is_fl26_exe(''))
        self.assertTrue(setup.is_fl26_exe(r'D:\FL 26\FL 2026 start.exe'))
        fake_drive = os.path.join(self.root, 'drive_d')
        nested_game = os.path.join(fake_drive, 'jawedfolder', 'Games', 'Pro Evolution Soccer 2017')
        os.makedirs(os.path.join(nested_game, 'download'), exist_ok=True)
        exe = os.path.join(nested_game, 'PES2017.exe')
        with open(exe, 'wb') as f:
            f.write(b'MZ')
        with open(os.path.join(nested_game, 'download', 'DpFileList.bin'), 'wb') as f:
            f.write(make_dpfilelist(['t99.cpk']))

        cands = setup.game_candidates(drives=[fake_drive])
        self.assertIn(nested_game, cands)
        self.assertEqual(setup.autodetect_exe(drives=[fake_drive]), exe)
        self.assertFalse(setup.is_fl26_exe(exe))
        # Quoted .exe path pasted from Windows "Copy as path" normalises to game folder
        self.assertEqual(setup.validate_patch_dir('  "' + exe + '"  '), nested_game)

    def test_edit_teams_and_ensure_teamids(self):
        # Synthetic EDIT buffer with two 480-byte team records at EDIT_TEAM0
        buf = bytearray(pes17.EDIT_TEAM0 + 3 * pes17.EDIT_TEAM_STRIDE)
        for i, (tid, nm, ab) in enumerate([(201, 'Birmingham City FC', 'BIR'),
                                           (390, 'Sunderland \u0391FC', 'SUN')]):
            off = pes17.EDIT_TEAM0 + i * pes17.EDIT_TEAM_STRIDE
            struct.pack_into('<I', buf, off, tid)
            buf[off + pes17.EDIT_TEAM_NAME_OFF:off + pes17.EDIT_TEAM_NAME_OFF + len(nm.encode())] = nm.encode()
            buf[off + pes17.EDIT_TEAM_ABBR_OFF:off + pes17.EDIT_TEAM_ABBR_OFF + len(ab.encode())] = ab.encode()
        parsed = pes17.edit_teams(bytes(buf))
        self.assertEqual([(t['tid'], t['abbr']) for t in parsed], [(201, 'BIR'), (390, 'SUN')])

        real_dir = os.environ.get('PES17_REAL_SAVES') or ''
        zp = os.path.join(ROOT, 'pes2017', 'dist', 'TheGaffer_pes2017_pc414.zip')
        if os.path.isfile(os.path.join(real_dir, 'EDIT00000000')) and os.path.isfile(zp):
            with zipfile.ZipFile(zp) as z:
                pc = types.ModuleType('pescrypt')
                exec(compile(z.read('TheGaffer/lib/pescrypt.py'), 'pescrypt.py', 'exec'), pc.__dict__)
            with mock.patch.dict(sys.modules, {'pescrypt': pc}):
                out_dir = os.path.join(self.root, 'pes17_db')
                ok = pes17.ensure_teamids({'save_dir': real_dir}, out_dir, force=True)
                self.assertTrue(ok)
                with open(os.path.join(out_dir, 'teamids.json'), encoding='utf-8') as f:
                    tids = json.load(f)
                self.assertIn('Birmingham City FC', tids.values())
                self.assertGreater(len(tids), 620)


class UiAndLiveServerIntegrationTests(unittest.TestCase):
    def test_classic_and_tools_ui_have_crest_badges_and_valid_js(self):
        tools_path = os.path.join(ROOT, 'pes2017', 'overlay', 'static', 'pes17.html')
        with open(tools_path, encoding='utf-8') as f:
            tools = f.read()

        self.assertFalse(os.path.exists(
            os.path.join(ROOT, 'pes2017', 'overlay', 'static', 'pes17-dashboard.html')))
        for needle in ('function crestBadge(', '/api/clubcolors', 'renderInfoViews'):
            self.assertIn(needle, tools)
        self.assertNotIn('http://', tools)
        self.assertNotIn('https://', tools)
        self.assertNotIn('game-skin', tools)
        ids = re.findall(r'\bid="([^"]+)"', tools)
        self.assertEqual(len(ids), len(set(ids)), 'duplicate id in pes17.html')

        node = shutil.which('node')
        if node:
            scripts = re.findall(r'<script>(.*?)</script>', tools, re.S)
            self.assertTrue(scripts, 'pes17.html')
            with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as tf:
                tf.write(scripts[0])
                js_file = tf.name
            try:
                proc = subprocess.run([node, '--check', js_file],
                                      capture_output=True, text=True, timeout=15)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            finally:
                os.unlink(js_file)

    def test_live_built_server_serves_patch_crests_on_first_request(self):
        zp = os.path.join(ROOT, 'pes2017', 'dist', 'TheGaffer_pes2017_pc414.zip')
        if not os.path.isfile(zp):
            self.skipTest('dist zip not built')

        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(zp) as z:
                z.extractall(tmp)
            app_dir = os.path.join(tmp, 'TheGaffer')

            # Prepare a real-CPK PES 2017 install dir (tested via real cpkread.Cpk!)
            game_dir = os.path.join(tmp, 'Pro Evolution Soccer 2017')
            os.makedirs(os.path.join(game_dir, 'Data'), exist_ok=True)
            os.makedirs(os.path.join(game_dir, 'download'), exist_ok=True)
            exe_path = os.path.join(game_dir, 'PES2017.exe')
            with open(exe_path, 'wb') as f:
                f.write(b'MZ')

            build_real_cpk(os.path.join(game_dir, 'Data', 'dt36_win.cpk'), {
                'common/render/symbol/flag/emblem_0100_r.png': PNG_VANILLA,
                'common/render/symbol/flag/emblem_0201_r.png': PNG_VANILLA,
                'common/render/symbol/flag/emblem_0396_r.png': PNG_VANILLA,
            })
            build_real_cpk(os.path.join(game_dir, 'download', 't99p17_emblem.cpk'), {
                'common/render/symbol/flag/emblem_0100_r.png': PNG_PATCH_NEW,
                'common/render/symbol/flag/emblem_0201_r.png': PNG_PATCH_NEW,
                'common/render/symbol/flag/emblem_0396_r.png': PNG_PATCH_OLD,
            })
            with open(os.path.join(game_dir, 'download', 'DpFileList.bin'), 'wb') as f:
                f.write(make_dpfilelist(['t99p17_emblem.cpk']))

            # Save folder: use real ML00000011 + EDIT00000000 if available, else encrypted sample
            save_dir = os.path.join(tmp, 'save')
            os.makedirs(save_dir, exist_ok=True)
            real_saves = os.environ.get('PES17_REAL_SAVES') or ''
            has_real = os.path.isfile(os.path.join(real_saves, 'ML00000011'))
            if has_real:
                for fn in ('ML00000011', 'EDIT00000000'):
                    src = os.path.join(real_saves, fn)
                    if os.path.isfile(src):
                        shutil.copy2(src, os.path.join(save_dir, fn))
                target_club = 'Birmingham City FC'
            else:
                sys.path.insert(0, os.path.join(app_dir, 'lib'))
                try:
                    import pescrypt
                    import sample
                    dec_dir = os.path.join(tmp, 'dec_sample')
                    sample.write_dec(dec_dir)
                    parts = {}
                    for k in ('encryptHeader.dat', 'header.dat', 'description.dat',
                              'logo.png', 'data.dat', 'version.txt'):
                        p = os.path.join(dec_dir, k)
                        if os.path.isfile(p):
                            with open(p, 'rb') as fh:
                                parts[k] = fh.read()
                        else:
                            parts[k] = b''
                    if not parts['encryptHeader.dat']:
                        parts['encryptHeader.dat'] = b'\x00' * 320
                    if len(parts['header.dat']) not in (176, 208):
                        parts['header.dat'] = b'\x00' * 176
                    if not parts['version.txt']:
                        parts['version.txt'] = '1.00'.encode('utf-16le')
                    enc = pescrypt.encrypt_parts(parts, pescrypt.KEY_PES17)
                    with open(os.path.join(save_dir, 'ML00000000'), 'wb') as f:
                        f.write(enc)
                finally:
                    sys.path.pop(0)
                target_club = 'Arsenal FC'

            # Pick a free localhost port
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]

            # Notice: `pes17_patch_dir` is NOT set — only `pes_exe` + `save_dir`!
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
                            mode = json.loads(resp.read().decode('utf-8'))
                            if mode.get('pes17'):
                                ready = True
                                break
                    except Exception:
                        time.sleep(0.1)
                self.assertTrue(ready, 'server did not enter pes17 mode on startup')

                # 1) Landing page `/` serves the pure Classic UI (`index.html`),
                #    with no `pes17-dashboard.html` or `game-skin` overlay
                with urllib.request.urlopen(base + '/', timeout=3) as resp:
                    html = resp.read().decode('utf-8')
                self.assertIn('function crestSvg(', html)
                self.assertIn('/api/crest?club=', html)
                self.assertIn('id="pes17ToolsBtn"', html)
                self.assertNotIn('game-skin.js', html)
                self.assertNotIn('game-skin.css', html)

                # 2) `/api/crest?club=...` works BEFORE `/api/state` is ever called,
                #    and `download/t99p17_emblem.cpk` beats `Data/dt36_win.cpk`!
                url = base + '/api/crest?club=' + urllib.parse.quote(target_club)
                with urllib.request.urlopen(url, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(resp.headers.get_content_type(), 'image/png')
                    body = resp.read()
                self.assertEqual(body, PNG_PATCH_NEW)

                if has_real:
                    for sun_name in ('Sunderland \u0391FC', 'Sunderland AFC'):
                        surl = base + '/api/crest?club=' + urllib.parse.quote(sun_name)
                        with urllib.request.urlopen(surl, timeout=5) as resp:
                            self.assertEqual(resp.read(), PNG_PATCH_OLD)

                # 3) `/api/pes17/crests/dir` accepts a quoted exe path
                req = urllib.request.Request(
                    base + '/api/pes17/crests/dir',
                    data=json.dumps({'dir': '"' + exe_path + '"'}).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    rep = json.loads(resp.read().decode('utf-8'))
                self.assertTrue(rep['available'])
                self.assertGreaterEqual(rep['logos_found'], 1)
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
