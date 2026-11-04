"""Regression checks for the MATCHDAY skin and its vector icon pack (r10).

The skin ships as two extra static files (game-skin.css / game-skin.js) that
are hooked into index.html by patch.py and directly into pes17.html.  These
tests are deliberately static: they do not need a browser, but they do check
that the icon map is internally consistent and that EVERY pictographic /
dingbat / arrow glyph in the original app is covered by a vector icon.

r10: there is no generic "unknown -> badge" fallback any more.  A glyph we
do not know is hidden visually but kept as text in the DOM, so a formation
icon can never silently turn into a star or a badge.
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
DASH = os.path.join(OVERLAY, 'pes17-dashboard.html')
PATCH = os.path.join(ROOT, 'pes2017', 'patch.py')
# The pc414 zip and the built index.html were removed from the repo root by
# the "keep only pes2017/" cleanup.  Point the coverage checks at real files
# with these overrides (build.py accepts the same two overrides).
ORIGINAL_ZIP = os.environ.get('GAFFER_ORIGINAL_ZIP',
                              os.path.join(ROOT, 'TheGaffer_pc414_20261103.zip'))
BUILT_HTML = os.environ.get('GAFFER_BUILT_HTML',
                            os.path.join(ROOT, 'build', 'TheGaffer', 'TheGaffer', 'static', 'index.html'))

# The same Unicode blocks the JS catch-all covers (plus arrows).
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
        self.assertGreaterEqual(len(ids), 100)
        missing = sorted(set(base_map(self.js).values()) - ids)
        self.assertEqual(missing, [], 'icon ids without a <symbol>: %s' % missing)

    def test_dedicated_football_icons_exist(self):
        """r10: formation / transfers / contracts / tactics / training /
        injuries / finance / competitions / news each get their own symbol."""
        ids = sprite_ids(self.js)
        wanted = ['formation', 'tactics', 'training', 'contract', 'transfer',
                  'injury', 'finance', 'competition', 'news', 'scout', 'youth',
                  'bench', 'substitute', 'medal', 'crown', 'manager', 'player',
                  'staff', 'press', 'stats', 'whistle', 'pace', 'status',
                  'rating', 'menu', 'bell', 'undo', 'refresh', 'weather',
                  'defence', 'match', 'table', 'form', 'quick', 'book']
        self.assertEqual(sorted(set(wanted) - ids), [], 'missing dedicated icons')
        keys = base_map(self.js)
        self.assertEqual(keys.get('⬡'), 'formation')
        self.assertEqual(keys.get('🧩'), 'tactics')
        self.assertEqual(keys.get('📰'), 'news')
        self.assertEqual(keys.get('⚖'), 'contract')
        self.assertEqual(keys.get('🧬'), 'youth')
        self.assertEqual(keys.get('🥇'), 'medal')
        self.assertEqual(keys.get('👑'), 'crown')
        self.assertEqual(keys.get('🩹'), 'injury')
        self.assertEqual(keys.get('💶'), 'finance')

    def test_no_generic_badge_fallback(self):
        """Different symbols must not collapse into one generic badge/star."""
        self.assertIn('return null;', self.js)
        self.assertNotIn("return 'badge';", self.js)
        self.assertIn('gi-unknown', self.js)
        self.assertIn('gi-sr', self.js)
        vals = collections.Counter(base_map(self.js).values())
        self.assertLess(vals['badge'], 3, 'badge is still overused: %d' % vals['badge'])
        self.assertLess(vals['star'], 9, 'star is still overused: %d' % vals['star'])

    def test_every_symbolic_glyph_is_explicitly_mapped(self):
        """100% explicit coverage: no emoji, dingbat, arrow or squared badge
        in pc414 is left to the catch-all."""
        if not os.path.isfile(ORIGINAL_ZIP):
            self.skipTest('original pc414 zip missing (set GAFFER_ORIGINAL_ZIP)')
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
        self.assertIn('✕', keys)     # close button X is an icon too
        self.assertIn('✗', keys)
        self.assertIn('→', keys)     # plain arrows are covered too

    def test_exhaustive_catch_all_is_present(self):
        """Unknown / future emoji are caught but hidden, never faked."""
        self.assertIn("'gu'", self.js)
        self.assertIn('var CATCH =', self.js)
        self.assertIn('\\u{1F000}', self.js)
        self.assertIn('function iconId(', self.js)

    def test_zwj_sequences_are_single_icons(self):
        keys = base_map(self.js)
        self.assertEqual(keys.get('😮\u200d💨'), 'mood')
        self.assertEqual(keys.get('🧑\u200d💼'), 'briefcase')
        self.assertEqual(keys.get('👨\u200d👩\u200d👧'), 'squad')

    def test_icon_library_is_a_single_consistent_sprite(self):
        """All symbols share the same 24x24 grid, stroke weight and sizing."""
        symbols = re.findall(r'<symbol id="gi-[a-z-]+"[^>]*>', self.js)
        self.assertEqual(len(symbols), len(sprite_ids(self.js)))
        for s in symbols:
            self.assertIn('viewBox="0 0 24 24"', s)
        self.assertIn('stroke-width: 1.65', self.css)
        self.assertIn('width: 1.08em', self.css)

    def test_stadium_dark_palette_and_no_scanlines_or_glow(self):
        self.assertIn('--bg: #070d16', self.css)
        self.assertIn('--club:', self.css)
        self.assertIn('--accent: var(--club)', self.css)
        self.assertNotIn('repeating-linear-gradient', self.css)
        self.assertNotIn('scanline', self.css.lower())
        self.assertNotIn('mix-blend-mode', self.css)
        for glow in ('0 0 22px rgba(', 'text-shadow: 0 0', '0 0 18px rgba('):
            self.assertNotIn(glow, self.css)

    def test_console_navigation_and_quick_switcher(self):
        for frag in ('gi-console', 'gi-tabs', 'gi-subbar', 'data-gi-sec',
                     'data-gi-go', 'SECTIONS', 'openSwitcher', 'tbFind',
                     'Alt+', 'ArrowRight', 'role="tablist"'):
            self.assertIn(frag, self.js)
        self.assertIn('.gi-tab', self.css)
        self.assertIn('.gi-subbar', self.css)
        self.assertIn('.gi-mobilenav', self.css)
        self.assertIn('position: fixed', self.css)

    def test_game_feel_focus_and_reduced_motion(self):
        for frag in ('gafferToast', 'AudioContext', 'SOUND_KEY', 'gi-enter',
                     'gi-press', 'beep(', 'toast('):
            self.assertIn(frag, self.js)
        self.assertIn(':focus-visible', self.css)
        self.assertIn('button:disabled', self.css)
        self.assertIn('prefers-reduced-motion', self.css)
        self.assertIn('gi-page-in', self.css)

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

    def test_dashboard_shares_the_identity(self):
        dash = read(DASH)
        self.assertIn('--club:', dash)
        self.assertIn('MATCHDAY', dash.upper())
        self.assertIn('id="setupCard"', dash)
        self.assertIn('gi-hero', dash)
        self.assertIn('bottom', dash)
        for frag in ('id="squadCards"', 'id="squadTable"', 'id="faceHome"',
                     'id="tilePosition"', 'function playerCards(',
                     'function standingsHtml(', 'gi-players', 'gi-bottom',
                     'gi-pill', 'gi-mission'):
            self.assertIn(frag, dash, 'home screen missing %s' % frag)
        # r10: no duplicate ids. A duplicate "squad" id once made the table
        # render wipe the whole squad hub section on load.
        ids = re.findall(r'\bid="([^"]+)"', dash)
        dupes = sorted(k for k in collections.Counter(ids) if collections.Counter(ids)[k] > 1)
        self.assertEqual(dupes, [], 'duplicate element ids: %s' % dupes)


if __name__ == '__main__':
    unittest.main()
