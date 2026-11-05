"""Game Shell asset, inventory and build integration regressions.

The interactive browser checks are in game_shell_browser.cjs; these tests need
only Python and the normal built ZIP, not a browser or runtime dependencies.
"""
import re
import shutil
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

PES = Path(__file__).resolve().parents[1]
STATIC = PES / 'overlay' / 'static'
DIST = PES / 'dist' / 'TheGaffer_pes2017_pc414.zip'
sys.path.insert(0, str(PES))
import prune  # noqa: E402


class GameShellSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (STATIC / 'game-shell.js').read_text(encoding='utf-8')
        cls.css = (STATIC / 'game-shell.css').read_text(encoding='utf-8')
        cls.tools = (STATIC / 'pes17.html').read_text(encoding='utf-8')

    def test_section_map_includes_every_real_panel_once(self):
        expected = {
            'home', 'inbox', 'assistant', 'growth', 'youth', 'calendar',
            'squad', 'league', 'stats', 'kit', 'players', 'signings',
            'shortlist', 'board', 'talks', 'sales', 'transfers', 'loans',
            'aimoves', 'press', 'story', 'journal', 'fans', 'clubs',
            'honours', 'awards', 'review', 'stories', 'records', 'history',
            'deadline', 'news', 'rumours',
        }
        definitions = self.js.split('const DEFINITIONS = [', 1)[1].split('];', 1)[0]
        groups = re.findall(r"\{id:'([^']+)'[^\n]+pages:\[([^\]]+)\]", definitions)
        self.assertEqual([g[0] for g in groups],
                         ['home', 'squad', 'transfers', 'competitions', 'media', 'office'])
        pages = [p for _, content in groups for p in re.findall(r"'([^']+)'", content)]
        self.assertEqual(set(pages), expected)
        self.assertEqual(len(pages), len(expected), 'no duplicate pages')
        self.assertIn("const aliases = {transfers:'signings', story:'news'}", self.js)

    def test_sections_use_bundled_real_sprite_symbols(self):
        definitions = self.js.split('const DEFINITIONS = [', 1)[1].split('];', 1)[0]
        icons = set(re.findall(r"icon:'([^']+)'", definitions))
        root = ET.parse(STATIC / 'hud-icons.svg').getroot()
        symbols = {child.get('id') for child in root if child.tag.endswith('symbol')}
        self.assertEqual(len(icons), 6)
        self.assertFalse({'hud-' + icon for icon in icons} - symbols)
        self.assertIn("'/hud-icons.svg#hud-'", self.js)

    def test_shell_styles_are_opt_in_and_have_viewport_fallback(self):
        source = re.sub(r'/\*.*?\*/', '', self.css, flags=re.S)
        for block in source.split('{')[:-1]:
            selector = block.rsplit('}', 1)[-1].strip()
            if selector.startswith('@'):
                continue
            # Commas inside :is(...) are not selector-list separators.
            selector = re.sub(r':is\([^)]*\)', ':is(*)', selector)
            for item in selector.split(','):
                self.assertIn('body.game-shell', item.strip(), item)
        self.assertIn('height:100vh; height:100dvh', source)
        self.assertIn('(min-width: 1025px)', source)
        self.assertIn('(min-height: 560px)', source)
        self.assertIn('overflow:auto!important', source)

    def test_assets_are_local_optional_and_preserve_original_router(self):
        self.assertIn("body.dataset.hud !== 'classic'", self.js)
        self.assertIn("localStorage.getItem(KEY) !== '0'", self.js)
        self.assertIn("const KEY = 'gaffer_shell'", self.js)
        self.assertIn('source.click()', self.js)
        self.assertNotRegex(self.js, r'\bshow\s*=\s*function|\bfunction\s+show\s*\(')
        self.assertNotRegex(self.js, r'\bfetch\s*\(|https://|\brequire\s*\(')
        self.assertIn('href="/game-shell.css"', self.tools)
        self.assertIn('src="/game-shell.js"', self.tools)
        self.assertIn('data-hud="tools"', self.tools)
        for name in ('game-shell.css', 'game-shell.js'):
            self.assertIn('static/' + name, prune.KEEP)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for syntax validation')
    def test_javascript_syntax(self):
        subprocess.run(['node', '--check', str(STATIC / 'game-shell.js')], check=True,
                       capture_output=True, text=True)


@unittest.skipUnless(DIST.is_file(), 'PES 2017 dist zip not built')
class ShippedGameShellTests(unittest.TestCase):
    def test_distribution_matches_the_sources(self):
        with zipfile.ZipFile(DIST) as z:
            for name in ('game-shell.css', 'game-shell.js'):
                self.assertEqual(z.read('TheGaffer/static/' + name), (STATIC / name).read_bytes())
            for name in ('index.html', 'pes17.html'):
                html = z.read('TheGaffer/static/' + name).decode('utf-8')
                self.assertIn('href="/game-shell.css"', html)
                self.assertIn('src="/game-shell.js"', html)


if __name__ == '__main__':
    unittest.main()
