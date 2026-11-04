"""Regression checks for the game-HUD skin and its vector icon pack.

The skin ships as two extra static files (game-skin.css / game-skin.js) that
are hooked into index.html by patch.py and directly into pes17.html.  These
tests are deliberately static: they do not need a browser, but they do check
that the icon map is internally consistent and that EVERY pictographic /
dingbat / arrow glyph in the original app is covered by a vector icon.
"""
import collections
import os
import re
import shutil
import subprocess
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OVERLAY = os.path.join(ROOT, 'pes2017', 'overlay', 'static')
CSS = os.path.join(OVERLAY, 'game-skin.css')
JS = os.path.join(OVERLAY, 'game-skin.js')
TOOLS = os.path.join(OVERLAY, 'pes17.html')
PATCH = os.path.join(ROOT, 'pes2017', 'patch.py')
ORIGINAL_ZIP = os.path.join(ROOT, 'TheGaffer_pc414_20261103.zip')
BUILT_HTML = os.path.join(ROOT, 'build', 'TheGaffer', 'TheGaffer', 'static', 'index.html')

# The same four Unicode blocks the JS catch-all covers (plus arrows).
PICTO_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF),
                (0x2B00, 0x2BFF), (0x2190, 0x21FF))


def read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def is_pictographic(ch):
    o = ord(ch)
    return any(lo <= o <= hi for lo, hi in PICTO_RANGES)


def unescape_key(k):
    """JS writes ZWJ keys as '\\u200d'; compare with the real character."""
    return k.replace('\\u200d', '\u200d').replace('\\ufe0f', '\ufe0f')


def sprite_ids(js):
    return set(re.findall(r'<symbol id="gi-([a-z-]+)"', js))


def base_map(js):
    block = js.split('var BASE = {')[1].split('};')[0]
    return {unescape_key(k): v for k, v in
            re.findall(r"'([^']+)': '([a-z-]+)'", block)}


class GameSkinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css, cls.js, cls.tools = read(CSS), read(JS), read(TOOLS)
        cls.patch = read(PATCH)

    def test_files_exist_and_are_hooked_up(self):
        self.assertIn('/game-skin.css', self.tools)
        self.assertIn('/game-skin.js', self.tools)
        self.assertIn("'static/game-skin.css'", self.patch)
        self.assertIn("'static/game-skin.js'", self.patch)
        self.assertIn('href="/game-skin.css"', self.patch)
        self.assertIn('src="/game-skin.js"', self.patch)
        if os.path.isfile(BUILT_HTML):
            built = read(BUILT_HTML)
            self.assertIn('href="/game-skin.css"', built)
            self.assertIn('src="/game-skin.js"', built)

    def test_js_syntax_is_valid(self):
        if not shutil.which('node'):
            self.skipTest('node not installed')
        r = subprocess.run(['node', '--check', JS], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_mapped_icon_has_a_svg_symbol(self):
        ids = sprite_ids(self.js)
        self.assertGreaterEqual(len(ids), 60)
        missing = sorted(set(base_map(self.js).values()) - ids)
        self.assertEqual(missing, [], 'icon ids without a <symbol>: %s' % missing)

    def test_every_symbolic_glyph_is_explicitly_mapped(self):
        """100% explicit coverage: no emoji, dingbat, arrow or squared badge
        in pc414 is left to the fallback (the fallback is a safety net only)."""
        if not os.path.isfile(ORIGINAL_ZIP):
            self.skipTest('original pc414 zip missing')
        with zipfile.ZipFile(ORIGINAL_ZIP) as z:
            html = z.read('TheGaffer/static/index.html').decode('utf-8', 'replace')
        tools = self.tools
        keys = set(base_map(self.js))
        keys |= {k + '\ufe0f' for k in keys.copy()}
        for text in (html, tools):
            pict = collections.Counter(ch for ch in text if is_pictographic(ch))
            left = {k for k in pict if k not in keys}
            self.assertEqual(left, set(),
                             'unmapped glyphs: %s' % [(hex(ord(k)), k) for k in left])
        self.assertIn('✕', keys)     # close button X is now an icon too
        self.assertIn('✗', keys)
        self.assertIn('→', keys)     # plain arrows are covered too

    def test_exhaustive_catch_all_is_present(self):
        """Unknown / future emoji still become an icon, never a color glyph."""
        self.assertIn("'gu'", self.js)
        self.assertIn('var CATCH =', self.js)
        self.assertIn('\\u{1F000}', self.js)
        self.assertIn('function iconId(', self.js)
        self.assertIn("return 'badge';", self.js)

    def test_zwj_sequences_are_single_icons(self):
        keys = base_map(self.js)
        self.assertEqual(keys.get('😮\u200d💨'), 'mood')
        self.assertEqual(keys.get('🧑\u200d💼'), 'briefcase')
        self.assertEqual(keys.get('👨\u200d👩\u200d👧'), 'squad')

    def test_skin_is_offline_and_self_contained(self):
        for name, text in (('css', self.css), ('js', self.js)):
            self.assertNotIn('https://', text, name)
            self.assertNotIn('fonts.googleapis', text, name)
            self.assertNotIn('@import', text, name)
            self.assertNotIn('url(', text, name)
        self.assertEqual(self.css.count('{'), self.css.count('}'), 'unbalanced CSS braces')

    def test_skin_is_scoped_and_toggleable(self):
        self.assertIn('body.game-skin', self.css)
        self.assertIn("SKIN_KEY = 'gaffer_game_skin'", self.js)
        self.assertIn("classList.toggle('game-skin'", self.js)
        self.assertIn('MutationObserver', self.js)
        self.assertIn('data-gi-emoji', self.js)        # textContent preserved
        self.assertIn('gi-boot', self.js)              # boot intro
        self.assertIn('gi-hud', self.js)               # HUD strip


if __name__ == '__main__':
    unittest.main()
