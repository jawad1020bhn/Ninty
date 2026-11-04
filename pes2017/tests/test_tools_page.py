"""r5/r6 static checks: tools page, HUD controls, budget labels, crests.

These are static/DOM-independent checks; the interactive jsdom smokes live in
the build notes (REAL_SAVE_REPORT.md).  No Windows / game is needed.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OVERLAY = os.path.join(ROOT, 'pes2017', 'overlay')
TOOLS = os.path.join(OVERLAY, 'static', 'pes17.html')
JS = os.path.join(OVERLAY, 'static', 'game-skin.js')
CSS = os.path.join(OVERLAY, 'static', 'game-skin.css')
PATCH = os.path.join(ROOT, 'pes2017', 'patch.py')
PAIRS = os.path.join(OVERLAY, 'lib', 'pes17_pairs.py')


def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


class ToolsPageR5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools, cls.js, cls.css = read(TOOLS), read(JS), read(CSS)
        cls.patch, cls.pairs = read(PATCH), read(PAIRS)

    def test_skin_hooks_still_present(self):
        self.assertIn('href="/game-skin.css"', self.tools)
        self.assertIn('src="/game-skin.js"', self.tools)

    def test_budget_is_labelled_raw_not_eur(self):
        self.assertIn('class="raw-badge"', self.tools)
        self.assertIn('NOT CONFIRMED EUR', self.tools)
        self.assertIn('currency scale has NOT been verified in game', self.tools)
        self.assertIn('Display scale (view only)', self.tools)
        self.assertIn('never writes to your save', self.tools)
        self.assertIn("currency_verified=False", read(os.path.join(
            OVERLAY, 'lib', 'pes17_write.py')))

    def test_banner_says_raw_and_mentions_layout_check(self):
        self.assertIn('RAW save word', self.patch)
        self.assertIn('checks the save layout before any write', self.patch)
        self.assertIn('not confirmed EUR', self.patch)

    def test_layout_guard_is_wired_into_the_page_and_server(self):
        self.assertIn('id="verifyLayout"', self.tools)
        self.assertIn("layout:$('verifyLayout').checked", self.tools)
        self.assertIn('layout_check', self.patch)
        self.assertIn('layout=lay', self.patch)
        self.assertIn('def verify_layout(', self.pairs)
        self.assertIn('MIN_REAL_SAVE', self.pairs)
        self.assertIn('TABLE_ANCHORS', self.pairs)

    def test_bilingual_toggle_is_present(self):
        self.assertIn('id="langBtn"', self.tools)
        self.assertIn('function setLang(', self.tools)
        self.assertIn("document.documentElement.dir=ar?'rtl':'ltr'", self.tools)
        self.assertGreaterEqual(len(re.findall(r'data-ar="', self.tools)), 30)
        # labels keep their inputs: data-ar lives on the text span, not <label>
        self.assertNotIn('<label data-ar', self.tools)

    def test_theme_picker_and_intro_default(self):
        self.assertIn("THEME_KEY = 'gaffer_game_theme'", self.js)
        self.assertIn('data-gi-theme-btn', self.js)
        self.assertIn("lsGet(INTRO_KEY) !== '1'", self.js)
        self.assertIn('data-gi-intro-btn', self.js)
        self.assertIn('data-gi-theme="amber"', self.css)
        self.assertIn('data-gi-theme="pitch"', self.css)
        self.assertIn('.gi-hud-btn {', self.css)

    def test_tools_page_inline_javascript_is_syntactically_valid(self):
        if not shutil.which('node'):
            self.skipTest('node not installed')
        scripts = re.findall(r'<script(?![^>]*src)[^>]*>([\s\S]*?)</script>',
                             self.tools)
        self.assertEqual(len(scripts), 1)
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False,
                                         encoding='utf-8') as f:
            f.write(scripts[0])
            path = f.name
        try:
            r = subprocess.run(['node', '--check', path],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.unlink(path)

    def test_read_side_now_exposes_numbers_and_xi(self):
        p17 = read(os.path.join(OVERLAY, 'lib', 'pes17.py'))
        self.assertIn('def squad_numbers(self):', p17)
        self.assertIn('shirt_numbers(self.d, self._team)', p17)
        self.assertIn('XI_ORDER = 1256728', p17)
        self.assertIn('def lineup(self):', p17)
        self.assertIn('35 - XI_ORDER_LEN', p17)


if __name__ == '__main__':
    unittest.main(verbosity=2)


class ToolsPageR6Tests(unittest.TestCase):
    """r6: club crests read from the local PES 2017 patch folder."""
    @classmethod
    def setUpClass(cls):
        cls.tools = read(TOOLS)
        cls.patch = read(PATCH)
        cls.module = read(os.path.join(OVERLAY, 'lib', 'pes17_crests.py'))
        cls.config = read(os.path.join(OVERLAY, 'config_pes2017.example.json'))

    def test_crest_card_and_controls_are_present(self):
        for needle in ('3c. Club logos from your PES 2017 patch folder',
                       'id="patchDir"', 'id="setCrestsDir"', 'id="rescanCrests"',
                       'id="clearCrestsDir"', 'id="crestReport"', 'id="crestGrid"',
                       'function renderCrests(', '/api/pes17/crests',
                       '/api/pes17/crests/dir', '/api/crest?club='):
            self.assertIn(needle, self.tools)
        self.assertIn('3c. شعارات الأندية', self.tools)

    def test_server_hooks_patch_crests_first_on_pes17(self):
        self.assertIn("if _GAME['v'] == 'pes17' or CFG.get('pes17_patch_dir'):", self.patch)
        self.assertIn('pes17_crests.crest_img(name, CFG)', self.patch)
        self.assertIn("if u.path == '/api/pes17/crests':", self.patch)
        self.assertIn("if self.path == '/api/pes17/crests/dir':", self.patch)
        self.assertIn("'/api/pes17/crests/dir'", self.patch)
        self.assertIn('_cfg_update(pes17_patch_dir=_pd)', self.patch)
        self.assertIn('pes17_crests.clear()', self.patch)
        self.assertIn('lib/pes17_crests.py', self.patch)
        self.assertIn('pc414-pes17-', self.patch)   # r6/r7 VERSION is set in patch.py

    def test_reader_is_offline_and_read_only(self):
        for bad in ('urllib', 'requests', 'socket.', 'http.client', 'https://', 'http://'):
            self.assertNotIn(bad, self.module)
        self.assertIn('def crest_img(', self.module)
        self.assertIn('def report(', self.module)
        self.assertIn('cpkread.Cpk', self.module)
        self.assertIn('dds.dds_to_png', self.module)
        self.assertIn('e_<id>_', self.module)

    def test_config_documents_the_optional_patch_folder(self):
        self.assertIn('"pes17_patch_dir": ""', self.config)
        self.assertIn('never modifies the game', self.config)


class ToolsPageR7Tests(unittest.TestCase):
    """r7: CPK harvest + PES 2017-only / offline cleanup."""
    @classmethod
    def setUpClass(cls):
        cls.patch = read(PATCH)
        cls.tools = read(TOOLS)
        cls.dash = read(os.path.join(OVERLAY, 'static', 'pes17-dashboard.html'))
        cls.module = read(os.path.join(OVERLAY, 'lib', 'pes17_assets.py'))
        cls.config = read(os.path.join(OVERLAY, 'config_pes2017.example.json'))
        cls.inv = read(os.path.join(OVERLAY, '..', 'CPK_ASSET_INVENTORY.md'))

    def test_harvest_endpoints_and_dashboard_landing_are_wired(self):
        for needle in ("if u.path == '/api/pes17/assets':",
                       "if self.path == '/api/pes17/assets/extract':",
                       "if u.path == '/api/pes17/mode':",
                       "name = 'pes17-dashboard.html'",
                       "'/api/pes17/assets/extract'",
                       'lib/pes17_assets.py', 'static/pes17-dashboard.html',
                       'tools/harvest_cpk.py', 'CPK_ASSET_INVENTORY.md',
                       'pc414-pes17-only-r7'):
            self.assertIn(needle, self.patch)

    def test_offline_cleanup_is_asserted(self):
        self.assertIn('REGEX_PATCHES', self.patch)
        self.assertIn(r"fonts\.googleapis\.com", self.patch)
        self.assertIn(r"https://flagcdn\.com", self.patch)
        self.assertIn("CFG.get('wiki_web', False)", self.patch)
        self.assertIn("CFG.get('pes17_only', True)", self.patch)
        self.assertIn('"pes17_only": true', self.config)
        self.assertIn('"wiki_web": false', self.config)

    def test_tools_page_has_asset_card(self):
        for needle in ('3d. CPK assets in the patch folder', 'id="scanAssets"',
                       'id="harvestAssets"', 'id="assetBars"',
                       '/api/pes17/assets', '/api/pes17/assets/extract'):
            self.assertIn(needle, self.tools)

    def test_dashboard_is_self_contained_and_honest(self):
        self.assertIn('/api/pes17/info', self.dash)
        self.assertIn('/api/crest?club=', self.dash)
        self.assertIn('/api/pes17/crests', self.dash)
        self.assertIn('/api/pes17/assets', self.dash)
        for bad in ('fonts.googleapis', 'flagcdn', 'https://'):
            self.assertNotIn(bad, self.dash)
        self.assertIn('NOT confirmed EUR', self.dash)
        self.assertIn('not yet loaded in PES 2017', self.dash)

    def test_asset_reader_and_inventory_are_offline(self):
        for bad in ('urllib', 'requests', 'socket.', 'https://', 'http://'):
            self.assertNotIn(bad, self.module)
        self.assertIn('def harvest(', self.module)
        self.assertIn('def classify(', self.module)
        self.assertIn('Refusing to extract into the source folder', self.module)
        self.assertIn('common/render/symbol/flag', self.inv)
        self.assertIn('common/render/symbol/emblem', self.inv)
        self.assertIn('common/etc/pesdb', self.inv)
