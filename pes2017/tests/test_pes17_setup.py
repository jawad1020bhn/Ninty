"""r9: first-run PES 2017 save-folder detection and friendly error handling."""
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'overlay', 'lib'))
sys.path.insert(0, os.path.join(ROOT, 'pes2017'))

import pes17_setup as setup  # noqa: E402


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def folder(self, rel, with_slot=False, with_edit=False):
        p = os.path.join(self.root, *rel.split('/'))
        os.makedirs(p, exist_ok=True)
        if with_slot:
            open(os.path.join(p, 'ML00000011'), 'wb').write(b'x')
        if with_edit:
            open(os.path.join(p, 'EDIT00000000'), 'wb').write(b'x')
        return p

    def test_candidates_finds_a_pes17_save_with_ml_slots_first(self):
        a = self.folder('OneDrive/Dokumenti', with_slot=True)
        b = self.folder('Documents')
        # candidates() appends KONAMI/Pro Evolution Soccer 2017/save to each root
        good = os.path.join(a, setup.PES17_SUB)
        empty = os.path.join(b, setup.PES17_SUB)
        os.makedirs(good, exist_ok=True)
        os.makedirs(empty, exist_ok=True)
        open(os.path.join(good, 'ML00000011'), 'wb').write(b'x')
        roots = (os.path.join(self.root, 'Documents'),
                 os.path.join(self.root, 'OneDrive', 'Dokumenti'))
        self.assertEqual(setup.candidates(roots), [good, empty])
        self.assertEqual(setup.autodetect(roots), good)

    def test_autodetect_returns_empty_when_nothing_exists(self):
        self.assertEqual(setup.candidates((self.root,)), [])
        self.assertEqual(setup.autodetect((self.root,)), '')

    def test_suggested_is_a_pes17_path_even_when_missing(self):
        p = setup.suggested((self.root,))
        self.assertTrue(p.endswith(setup.PES17_SUB))
        self.assertTrue(os.path.isabs(p))

    def test_slots_in_filters_and_tolerates_missing(self):
        p = self.folder('save', with_slot=True)
        open(os.path.join(p, 'SYSTEM00000000'), 'wb').write(b'x')
        self.assertEqual(setup.slots_in(p), ['ML00000011'])
        self.assertEqual(setup.slots_in(os.path.join(self.root, 'nope')), [])

    def test_validate_save_dir(self):
        p = self.folder('save')
        self.assertEqual(setup.validate_save_dir('  "' + p + '"  '), p)
        for bad in ('', '   ', 'C:\\definitely\\missing\\save'):
            with self.assertRaisesRegex(ValueError, 'Enter the full path|Folder not found'):
                setup.validate_save_dir(bad)

    def test_home_roots_includes_onedrive_and_localised_documents(self):
        # profile + any OneDrive-like folders + localised Documents names
        fake = self.folder('profile')
        self.folder('profile/OneDrive')
        old = os.environ.get('USERPROFILE')
        os.environ['USERPROFILE'] = fake
        try:
            rs = setup.home_roots()
        finally:
            if old is None:
                del os.environ['USERPROFILE']
            else:
                os.environ['USERPROFILE'] = old
        self.assertTrue(any('OneDrive' in r for r in rs))
        self.assertTrue(any('Dokumenti' in r for r in rs))


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.here = self.tmp.name
        open(os.path.join(self.here, 'VERSION.txt'), 'w').write(
            'pc414-pes17-clean-r9 (2026-11-04)\n')

    def test_status_without_save_dir_is_friendly(self):
        s = setup.status({}, self.here)
        self.assertIs(s['ok'], False)
        self.assertEqual(s['save_dir'], '')
        self.assertIn('save folder', s['message'].lower())
        self.assertEqual(s['version'], 'pc414-pes17-clean-r9 (2026-11-04)')
        self.assertIn('Pro Evolution Soccer 2017', s['suggested'])
        self.assertNotIn('Errno', str(s))
        self.assertNotIn('WinError', str(s))

    def test_status_with_missing_configured_folder(self):
        s = setup.status({'save_dir': 'C:\\definitely\\missing\\save'}, self.here)
        self.assertIs(s['ok'], False)
        self.assertIs(s['save_dir_exists'], False)
        self.assertIn('does not exist', s['message'])

    def test_status_with_real_slot_and_edit(self):
        d = self.tmp.name
        open(os.path.join(d, 'ML00000011'), 'wb').write(b'x')
        open(os.path.join(d, 'EDIT00000000'), 'wb').write(b'x')
        s = setup.status({'save_dir': d}, self.here)
        self.assertIs(s['ok'], True)
        self.assertEqual(s['slots'], ['ML00000011'])
        self.assertIs(s['edit_exists'], True)
        self.assertEqual(s['candidates'], [])

    def test_friendly_error_and_unavailable_never_leak_raw_os_errors(self):
        ex = FileNotFoundError(2, 'No such file or directory',
                               'C:\\Users\\x\\KONAMI\\eFootball PES 2021 SEASON UPDATE\\2026\\save\\')
        msg = setup.friendly_error(ex, 'C:\\Users\\x\\save')
        self.assertIn('Save folder', msg)
        self.assertNotIn('Errno', msg)
        u = setup.unavailable({'save_dir': ''}, '', ex, self.here)
        self.assertIs(u['ok'], False)
        self.assertEqual(u['error'], 'save_unavailable')
        self.assertNotIn('Errno', str(u))
        self.assertNotIn('WinError', str(u))

    def test_module_is_offline(self):
        with open(setup.__file__, encoding='utf-8') as f:
            src = f.read()
        for bad in ('urllib', 'requests', 'socket.', 'https://', 'http://'):
            self.assertNotIn(bad, src)


class WiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patch = open(os.path.join(ROOT, 'pes2017', 'patch.py'), encoding='utf-8').read()
        cls.dash = open(os.path.join(ROOT, 'pes2017', 'overlay', 'static',
                                     'pes17-dashboard.html'), encoding='utf-8').read()
        cls.build = open(os.path.join(ROOT, 'pes2017', 'build.py'), encoding='utf-8').read()
        cls.zp = os.path.join(ROOT, 'pes2017', 'dist', 'TheGaffer_pes2017_pc414.zip')
        if os.path.isfile(cls.zp):
            with zipfile.ZipFile(cls.zp) as z:
                cls.names = set(z.namelist())
                cls.server = z.read('TheGaffer/server.py').decode('utf-8', 'replace')
                cls.version = z.read('TheGaffer/VERSION.txt').decode().strip()
        else:
            cls.names, cls.server, cls.version = set(), '', ''

    def test_no_fl26_default_path_in_patch_or_build(self):
        self.assertIn("'save_dir': '',   # r9:", self.patch)
        self.assertIn('pes17_setup.autodetect()', self.patch)
        self.assertIn("if u.path == '/api/pes17/setup'", self.patch)
        self.assertIn("if self.path == '/api/pes17/setup/savefolder'", self.patch)
        self.assertIn("'/api/pes17/setup/savefolder'", self.patch)
        self.assertIn('pes17_setup.unavailable(', self.patch)

    def test_dashboard_has_setup_card_and_no_raw_errors(self):
        for needle in ('id="setupCard"', 'id="saveDir"', 'id="saveDirBtn"',
                       'id="setupBtn"', 'id="buildVer"', 'function friendly(',
                       "'/api/pes17/setup'", "'/api/pes17/setup/savefolder'",
                       'Waiting for a save folder'):
            self.assertIn(needle, self.dash)
        self.assertNotIn('Build <b>r7</b>', self.dash)
        self.assertIn('>r9<', self.dash)
        self.assertNotIn('fonts.googleapis', self.dash)
        self.assertNotIn('flagcdn', self.dash)

    def test_build_accepts_an_external_original_zip(self):
        self.assertIn('GAFFER_ORIGINAL_ZIP', self.build)
        self.assertIn('GAFFER_BUILD_DIR', self.build)
        self.assertIn('--source', self.build)

    def test_shipped_zip_has_the_r9_files_and_no_fl26_default(self):
        if not self.names:
            self.skipTest('dist zip not built yet')
        for rel in ('TheGaffer/lib/pes17_setup.py', 'TheGaffer/FIRST_RUN.md',
                    'TheGaffer/static/pes17-dashboard.html'):
            self.assertIn(rel, self.names)
        self.assertEqual(self.version, 'pc414-pes17-clean-r9 (2026-11-04)')
        self.assertIn("'save_dir': '',   # r9:", self.server)
        self.assertNotIn("eFootball PES 2021 SEASON UPDATE\\\\2026\\\\save',", self.server)
        self.assertIn("if u.path == '/api/pes17/setup':", self.server)
        self.assertFalse(any('__pycache__' in n or n.endswith('.pyc') for n in self.names))
        self.assertFalse(any(n.endswith('config.json') for n in self.names))


if __name__ == '__main__':
    unittest.main()
