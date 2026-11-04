"""r5 static checks: tools page, HUD controls, honest budget labelling.

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
