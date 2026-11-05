"""Offline matchday HUD and emoji-removal regressions for the classic UI."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PES = ROOT / 'pes2017'
OVERLAY = PES / 'overlay' / 'static'
DIST = PES / 'dist' / 'TheGaffer_pes2017_pc414.zip'
sys.path.insert(0, str(PES))
import pro_ui  # noqa: E402


class IconMappingTests(unittest.TestCase):
    def test_tokens_preserve_distinct_values_and_graphemes(self):
        glyphs = ['⚽', '🏆', '✍', '✍️', '🧑\u200d🤝\u200d🧑', '😮\u200d💨']
        tokens = [pro_ui.tokenize(glyph) for glyph in glyphs]
        self.assertEqual(len(tokens), len(set(tokens)))
        self.assertTrue(all(re.fullmatch(r'__gi_[0-9a-f]+(?:_[0-9a-f]+)*__', t)
                            for t in tokens))
        self.assertEqual(pro_ui.tokenize('⚽⚽'), tokens[0] * 2)
        self.assertEqual(pro_ui.tokenize('✍️'), '__gi_270d_fe0f__')
        # Ordinary arrows remain readable prose; the emoji-style form is an icon.
        self.assertEqual(pro_ui.tokenize('↗'), '↗')
        self.assertEqual(pro_ui.tokenize('↗️'), '__gi_2197_fe0f__')

    def test_morale_uses_directional_game_indicators(self):
        self.assertEqual(pro_ui.GLYPHS['😄'], 'form-up')
        self.assertEqual(pro_ui.GLYPHS['🙂'], 'form-good')
        self.assertEqual(pro_ui.GLYPHS['😐'], 'form-neutral')
        self.assertEqual(pro_ui.GLYPHS['🙁'], 'form-low')
        self.assertEqual(pro_ui.GLYPHS['😡'], 'form-down')

    def test_all_mapped_icons_exist_as_local_svg_symbols(self):
        root = ET.parse(OVERLAY / 'hud-icons.svg').getroot()
        ids = {child.get('id') for child in root if child.tag.endswith('symbol')}
        self.assertGreaterEqual(len(ids), 80)
        self.assertFalse({'hud-' + name for name in pro_ui.GLYPHS.values()} - ids)
        # Symbols are solid/layered emblems, not a font or remote image library.
        source = (OVERLAY / 'hud-icons.svg').read_text(encoding='utf-8')
        self.assertIn('fill="currentColor"', source)
        self.assertIn('opacity=".45"', source)
        self.assertNotIn('<image', source)

    def test_translation_aliases_preserve_original_and_existing_keys(self):
        key = pro_ui.tokenize('🖥 Digital')
        value = pro_ui.tokenize('🖥 Digitale')
        alias = pro_ui._translation_aliases({key: value, 'The board': 'Dirigenza',
                    pro_ui.tokenize('⚠️ The board'): pro_ui.tokenize('⚠️ La Dirigenza'),
                    pro_ui.tokenize('>🤫 Let them wait'): pro_ui.tokenize('>🤫 Lasciarli aspettare')})
        self.assertEqual(alias[key], value)
        self.assertEqual(alias['Digital'], 'Digitale')
        self.assertEqual(alias['The board'], 'Dirigenza')  # never overwrite
        self.assertEqual(alias['Let them wait'], 'Lasciarli aspettare')


class TransformFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for d in ('static', 'lib', 'data/i18n'):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        for fn in ('hud-icons.svg', 'hud-icons.js', 'hud-ui.css', 'pes17.html'):
            shutil.copyfile(OVERLAY / fn, self.root / 'static' / fn)
        css = '''.pc-tr .tr-chip.cm::before{content:"⚡";margin-right:7px;font-size:12px;color:var(--g)}
html body #p-journal .jn-main h3::before{content:"⚽ ";text-decoration:none;display:inline-block}
.stx-rs li::before{content:"✔";color:#f0575c;margin-right:8px}'''
        script = """const lab=q=>{let t=q;const n=1;t='★ '+t+(n?' · '+n:'');return t};
const scope='[translate=no]:not(thead):not(.lgt-h):not(.hm2-th)';
const ball='⚽'.repeat(3), same='🏆'==='🏆'; let text='✍️ Extend contract';"""
        (self.root / 'static/index.html').write_text(
            '<html><head><style>' + css + '</style></head><body><script>' + script +
            '</script><span>⚙</span></body></html>', encoding='utf-8')
        (self.root / 'lib/jobintro.py').write_text("DAYS = [('🎙', 'Welcome')]\n", encoding='utf-8')
        (self.root / 'data/i18n/it.json').write_text(json.dumps(
            {'🖥 Digital': '🖥 Digitale', '✍️ Extend contract': '✍️ Rinnova contratto'},
            ensure_ascii=False), encoding='utf-8')
        (self.root / 'data/i18n/strings_en.json').write_text(json.dumps(
            {'🖥 Digital': '', '✍️ Extend contract': ''}, ensure_ascii=False), encoding='utf-8')

    def test_transform_preserves_logic_and_adds_assets_and_i18n_aliases(self):
        pro_ui.apply(str(self.root))
        index = (self.root / 'static/index.html').read_text(encoding='utf-8')
        self.assertIn('<body data-hud="classic">', index)
        self.assertIn('/hud-ui.css', index)
        self.assertIn('/hud-icons.js', index)
        self.assertIn("'__gi_26bd__'.repeat(3)", index)
        self.assertIn("'__gi_1f3c6__'==='__gi_1f3c6__'", index)
        self.assertIn("t=t+(n?' · '+n:'')", index)
        self.assertIn('[translate=no]:not(html)', index)
        self.assertNotRegex(index, pro_ui._STRICT_LEFTOVER)
        style = re.search(r'<style>(.*?)</style>', index, re.S).group(1)
        self.assertNotIn('__gi_', style)
        it = json.loads((self.root / 'data/i18n/it.json').read_text(encoding='utf-8'))
        self.assertEqual(it['__gi_1f5a5__ Digital'], '__gi_1f5a5__ Digitale')
        self.assertEqual(it['Digital'], 'Digitale')
        self.assertEqual(it['Extend contract'], 'Rinnova contratto')
        job = (self.root / 'lib/jobintro.py').read_text(encoding='utf-8')
        self.assertIn('__gi_1f399__', job)
        compile(job, 'jobintro.py', 'exec')
        generated = (self.root / 'static/hud-icons.js').read_text(encoding='utf-8')
        self.assertNotIn('__HUD_ICON_MAP__', generated)
        self.assertIn('"26bd":"ball"', generated)

    def test_unknown_upstream_emoji_fails_the_build(self):
        path = self.root / 'lib/jobintro.py'
        path.write_text("DAYS = [('🎙', 'known'), ('🫨', 'unknown')]\n", encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'unmapped pictograph'):
            pro_ui.apply(str(self.root))

    def test_unknown_default_presentation_bmp_emoji_fails_the_build(self):
        path = self.root / 'lib/jobintro.py'
        path.write_text("DAYS = [('🎙', 'known'), ('⛄', 'unknown')]\n", encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'unmapped pictograph'):
            pro_ui.apply(str(self.root))

    def test_tools_page_cannot_ship_default_presentation_emoji(self):
        path = self.root / 'static/pes17.html'
        path.write_text(path.read_text(encoding='utf-8') + '<span>⛄</span>', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'tools page contains an unmapped pictograph'):
            pro_ui.apply(str(self.root))

    def test_changed_css_fails_loudly(self):
        path = self.root / 'static/index.html'
        path.write_text(path.read_text(encoding='utf-8').replace('content:"⚡"', 'content:"new"'),
                        encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'lightning CSS'):
            pro_ui.apply(str(self.root))


class ShippedHudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DIST.is_file():
            raise unittest.SkipTest('PES 2017 dist zip not built')
        with zipfile.ZipFile(DIST) as z:
            cls.names = set(z.namelist())
            cls.index = z.read('TheGaffer/static/index.html').decode('utf-8')
            cls.tools = z.read('TheGaffer/static/pes17.html').decode('utf-8')
            cls.js = z.read('TheGaffer/static/hud-icons.js').decode('utf-8')
            cls.css = z.read('TheGaffer/static/hud-ui.css').decode('utf-8')
            cls.it = json.loads(z.read('TheGaffer/data/i18n/it.json'))
            cls.text_files = {}
            for name in cls.names:
                if not name.lower().endswith(('.html', '.py', '.json', '.txt', '.md', '.js', '.css', '.svg')):
                    continue
                try:
                    cls.text_files[name] = z.read(name).decode('utf-8')
                except UnicodeDecodeError:
                    pass

    def test_ships_the_classic_app_and_local_hud_not_the_removed_skin(self):
        for name in ('hud-icons.svg', 'hud-icons.js', 'hud-ui.css'):
            self.assertIn('TheGaffer/static/' + name, self.names)
        for name in ('game-skin.css', 'game-skin.js', 'pes17-dashboard.html'):
            self.assertNotIn('TheGaffer/static/' + name, self.names)
        self.assertIn('<body data-hud="classic">', self.index)
        self.assertIn('<body data-hud="tools">', self.tools)
        self.assertRegex(self.tools, r'<h2[^>]*data-hud-icon="player"[^>]*>Player mini-faces')
        for source in (self.index, self.tools):
            self.assertIn('href="/hud-ui.css"', source)
            self.assertIn('src="/hud-icons.js"', source)
        self.assertNotIn('fonts.googleapis', self.css)
        self.assertIn("const SPRITE = '/hud-icons.svg#hud-'", self.js)

    def test_packaged_instructions_match_the_classic_landing_page(self):
        readme = self.text_files['TheGaffer/README_PES2017.txt']
        first_run = self.text_files['TheGaffer/FIRST_RUN.md']
        self.assertIn('Classic application opens directly at /', readme)
        self.assertIn('sidebar', readme)
        self.assertIn('/pes17.html', first_run)
        self.assertIn('Use this folder', first_run)
        self.assertNotIn('static/game-skin.js', readme)
        self.assertNotIn('A blue banner confirms PES 2017 mode', readme)
        self.assertNotIn('Classic app ↗', first_run)

    def test_shipped_text_contains_no_emoji_presentation(self):
        for name, text in self.text_files.items():
            match = pro_ui._STRICT_LEFTOVER.search(text)
            self.assertIsNone(match, '%s contains an emoji at %s' %
                              (name, match.start() if match else ''))
        for glyph in pro_ui.BASE:
            self.assertNotIn(glyph, self.index, 'classic UI still contains %r' % glyph)

    def test_italian_full_and_split_icon_keys_are_available(self):
        self.assertEqual(self.it['__gi_1f5a5__ Digital'], '__gi_1f5a5__ Digitale')
        self.assertEqual(self.it['Digital'], 'Digitale')
        self.assertEqual(self.it['__gi_1f512__ moved club this window'],
                         '__gi_1f512__ ha già cambiato club in questa sessione')
        self.assertIn('[translate=no]:not(html)', self.index)

    def test_renderer_handles_repeated_and_legacy_icons(self):
        if not shutil.which('node'):
            self.skipTest('node not installed')
        # Exercise the generated pure parser without requiring a browser or
        # npm dependency. The document stub prevents the DOM bootstrap.
        js = self.js.replace("  if (document.readyState === 'loading')",
                             "  globalThis.__hudTest = {parts, plain, renderText, renderTree};\n"
                             "  if (document.readyState === 'loading')", 1)
        runner = r'''
const vm = require('vm');
const fs = require('fs');
const element=()=>({dataset:{},children:[],attributes:{},className:'',
  setAttribute(k,v){this.attributes[k]=v},appendChild(n){this.children.push(n)}});
const doc={readyState:'loading',addEventListener(){},createElement:element,
  createElementNS:element,createDocumentFragment:element,
  createTextNode(value){return {nodeValue:value}},createTreeWalker(){return {nextNode(){return false}}}};
const ctx = {document:doc,NodeFilter:{SHOW_TEXT:4}};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'),ctx);
const p=ctx.__hudTest.parts;
function check(ok,msg){if(!ok)throw new Error(msg)}
let a=p('__gi_26bd____gi_26bd____gi_26bd__');
check(a.length===3 && a.every(x=>x.code==='26bd' && x.name==='ball'),'adjacent goals');
a=p('__gi_1f9d1_200d_1f91d_200d_1f9d1__');
check(a.length===1 && a[0].name==='squad','joined grapheme');
a=p(String.fromCodePoint(0x26bd)+String.fromCodePoint(0x1f3c6));
check(a.length===2 && a[0].name==='ball' && a[1].name==='trophy','old save icons');
a=p(String.fromCodePoint(0x1fae8));
check(a.length===1 && a[0].name==='info','unknown emoji fallback');
a=p('⛄');
check(a.length===1 && a[0].name==='info','unknown BMP emoji fallback');
a=p('⚽️⚽️');
check(a.length===2 && a.every(x=>x.name==='ball'),'known icons with variation selectors');
check(p('↗').length===0,'ordinary arrows remain text');
check(p('🇩🇿').length===1 && p('1️⃣').length===1,'flags and keycaps remain whole');
check(p('👩‍⚕️').length===1,'unknown joined emoji remains whole');
check(ctx.__hudTest.plain('__gi_1f3c6__ Winner')==='Trophy Winner','plain text controls');
const parent={closest(){return null},replaceChild(fragment){this.fragment=fragment}};
let text={nodeValue:'__gi_26bd____gi_26bd__ & <',parentElement:parent,parentNode:parent};
ctx.__hudTest.renderText(text);
check(parent.fragment.children.filter(x=>x.className==='hud-icon hud-icon--ball').length===2,'two DOM icons');
check(parent.fragment.children.at(-1).nodeValue===' & <','text is not interpreted as HTML');
const option={value:'__gi_1f3c6__ Winner',attributes:{},hasAttribute(){return false},
  setAttribute(k,v){this.attributes[k]=v}};
const selectParent={closest(s){return s==='option'?option:null}};
text={nodeValue:option.value,parentElement:selectParent,parentNode:selectParent};
ctx.__hudTest.renderText(text);
check(text.nodeValue==='Trophy Winner' && option.attributes.value==='__gi_1f3c6__ Winner',
  'option labels must not change their submitted value');
const child={nodeType:1,classList:{contains(){return false}},attrs:{title:'⛄ Winter'},
  hasAttribute(k){return k in this.attrs},getAttribute(k){return this.attrs[k]},
  setAttribute(k,v){this.attrs[k]=v}};
const root={nodeType:1,classList:{contains(){return false}},closest(){return null},
  hasAttribute(){return false},querySelectorAll(selector){
    check(selector.includes('[title]'),'nested attribute selector');return [child]}};
ctx.__hudTest.renderTree(root);
check(child.attrs.title==='Information Winter','native emoji in inserted descendant attributes');
'''
        with tempfile.TemporaryDirectory() as d:
            renderer, script = Path(d) / 'renderer.js', Path(d) / 'test.js'
            renderer.write_text(js, encoding='utf-8')
            script.write_text(runner, encoding='utf-8')
            r = subprocess.run(['node', str(script), str(renderer)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_all_inline_scripts_and_renderer_parse(self):
        if not shutil.which('node'):
            self.skipTest('node not installed')
        scripts = []
        for source in (self.index, self.tools):
            scripts.extend(re.findall(r'<script(?![^>]*src)[^>]*>([\s\S]*?)</script>', source, re.I))
        scripts.append(self.js)
        with tempfile.TemporaryDirectory() as d:
            for i, source in enumerate(scripts):
                p = Path(d) / ('script%d.js' % i)
                p.write_text(source, encoding='utf-8')
                r = subprocess.run(['node', '--check', str(p)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, 'script %d: %s' % (i, r.stderr))


if __name__ == '__main__':
    unittest.main(verbosity=2)
