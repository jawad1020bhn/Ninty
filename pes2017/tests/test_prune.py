"""Tests for the r8 safe cleanup of FL26/FL27/Sider-only files."""
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'pes2017'))

import prune  # noqa: E402


class PruneRulesTests(unittest.TestCase):
    def test_rules_are_curated_and_do_not_touch_the_keep_set(self):
        self.assertGreaterEqual(len(prune.RULES), 10)
        self.assertGreaterEqual(len(prune.KEEP), 30)
        for rel, isdir, why in prune.RULES:
            self.assertTrue(why)
            for k in prune.KEEP:
                self.assertFalse(k == rel or k.startswith(rel + '/'),
                                 'rule %s would remove kept path %s' % (rel, k))
        # A FL26 database that PES 2017 does NOT regenerate must stay.
        self.assertIn('data/teamids.json', prune.KEEP)
        self.assertIn('static/index.html', prune.KEEP)
        self.assertIn('python/python.exe', prune.KEEP)
        self.assertIn('lib/pes17_write.py', prune.KEEP)

    def test_rules_target_only_fl26_fl27_sider_or_shadowed_databases(self):
        rels = {r[0] for r in prune.RULES}
        self.assertIn('addons/regenfix', rels)
        self.assertIn('addons/michele', rels)
        self.assertIn('lua', rels)
        self.assertIn('FL_key.bin', rels)
        for f in ('players.json', 'positions.json', 'playpos.json',
                  'ratings.json', 'realmoves.json'):
            self.assertIn('data/' + f, rels)
        # Art, scenes, strings and the classic UI are NOT removed.
        for f in ('static/index.html', 'data/art/banner.jpg',
                  'data/myscenes/office.jpg', 'data/stadiums/168c2dd70223be0d.jpg',
                  'data/i18n/strings_en.json', 'data/fm_text.json',
                  'data/venue_metadata.json'):
            self.assertNotIn(f, rels)

    def test_prune_module_is_offline(self):
        with open(prune.__file__, encoding='utf-8') as f:
            src = f.read()
        for bad in ('urllib', 'requests', 'socket.', 'https://', 'http://'):
            self.assertNotIn(bad, src)

    def test_build_calls_the_pruner(self):
        with open(os.path.join(ROOT, 'pes2017', 'build.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('import prune', src)
        self.assertIn('prune.apply(program)', src)

    def test_offline_guard_replaces_the_removed_transfer_cache(self):
        # Removing data/realmoves.json would otherwise make real_moves() spawn
        # a Wikipedia fetch in the background on first use. patch.py guards it.
        with open(os.path.join(ROOT, 'pes2017', 'patch.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn("if not _wiki_web():", src)
        self.assertIn('r8: offline by default; the FL26 Wikipedia transfer cache', src)


class PruneApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        # Minimal tree that satisfies KEEP + a few prunable paths.
        self.paths = list(prune.KEEP) + [
            'addons/regenfix/modules/fl26regen.dll',
            'addons/regenfix/livecpk/FL26 Regen Faces/common/render/symbol/player/regen/0.dds',
            'addons/michele/modules/injuries_for_all.lua',
            'lua/PlayerDump.lua',
            'FL_key.bin', 'FL_key_README.txt',
            'data/players.json', 'data/ratings.json', 'data/realmoves.json',
            'data/art/lg-pl.jpg',
        ]
        for rel in self.paths:
            p = os.path.join(self.root, *rel.split('/'))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'wb') as f:
                f.write(b'x' * 32)

    def test_apply_removes_only_the_curated_files(self):
        before = sorted(os.path.relpath(os.path.join(d, f), self.root).replace(os.sep, '/')
                        for d, _, fs in os.walk(self.root) for f in fs)
        r = prune.apply(self.root)
        after = sorted(os.path.relpath(os.path.join(d, f), self.root).replace(os.sep, '/')
                       for d, _, fs in os.walk(self.root) for f in fs)
        self.assertTrue(r['removed'] > 0)
        self.assertEqual(set(before) - set(after), set(r['files']))
        self.assertIn('CLEANUP_MANIFEST.txt', after)
        self.assertIn('data/art/lg-pl.jpg', after)   # ID-independent art stays
        self.assertIn('static/index.html', after)
        self.assertIn('python/python.exe', after)
        for rel in ('addons/regenfix/modules/fl26regen.dll',
                    'lua/PlayerDump.lua', 'FL_key.bin',
                    'data/players.json', 'data/realmoves.json'):
            self.assertNotIn(rel, after)
        self.assertFalse(os.path.isdir(os.path.join(self.root, 'addons')))
        self.assertFalse(os.path.isdir(os.path.join(self.root, 'lua')))
        with open(os.path.join(self.root, 'CLEANUP_MANIFEST.txt'), encoding='utf-8') as f:
            manifest = f.read()
        self.assertIn('SAFE CLEANUP MANIFEST', manifest)
        self.assertIn('FL26', manifest)

    def test_apply_refuses_to_ship_without_a_required_file(self):
        os.remove(os.path.join(self.root, 'static', 'index.html'))
        with self.assertRaisesRegex(RuntimeError, 'must be kept'):
            prune.apply(self.root)

    def test_plan_is_deterministic_and_does_not_include_kept_paths(self):
        a = prune.plan(self.root)
        b = prune.plan(self.root)
        self.assertEqual(a, b)
        kept = set(prune.KEEP)
        self.assertFalse(kept & {r[0] for r in a})


class ShippedZipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zp = os.path.join(ROOT, 'pes2017', 'dist', 'TheGaffer_pes2017_pc414.zip')
        if os.path.isfile(cls.zp):
            with zipfile.ZipFile(cls.zp) as z:
                cls.names = set(z.namelist())
                cls.version = z.read('TheGaffer/VERSION.txt').decode().strip()
                cls.manifest = z.read('TheGaffer/CLEANUP_MANIFEST.txt').decode('utf-8', 'replace') \
                    if 'TheGaffer/CLEANUP_MANIFEST.txt' in z.namelist() else ''
                cls.server = z.read('TheGaffer/server.py').decode('utf-8', 'replace')
        else:
            cls.names, cls.version, cls.manifest, cls.server = set(), '', '', ''

    def test_pruned_paths_are_absent_from_the_shipped_zip(self):
        if not self.names:
            self.skipTest('dist zip not built yet')
        bad = [n for n in self.names if n.startswith(('TheGaffer/addons/', 'TheGaffer/lua/'))]
        self.assertEqual(bad, [])
        for rel in ('FL_key.bin', 'FL_key_README.txt', 'players.json',
                    'positions.json', 'playpos.json', 'ratings.json', 'realmoves.json'):
            self.assertNotIn('TheGaffer/data/' + rel, self.names)
        self.assertNotIn('TheGaffer/FL_key.bin', self.names)

    def test_every_kept_path_and_the_manifest_are_shipped(self):
        if not self.names:
            self.skipTest('dist zip not built yet')
        for rel in prune.KEEP:
            self.assertIn('TheGaffer/' + rel, self.names)
        self.assertIn('TheGaffer/CLEANUP_MANIFEST.txt', self.names)
        self.assertIn('TheGaffer/CLEANUP_REPORT.md', self.names)
        self.assertIn('SAFE CLEANUP MANIFEST', self.manifest)

    def test_version_is_r9(self):
        if not self.version:
            self.skipTest('dist zip not built yet')
        self.assertEqual(self.version, 'pc414-pes17-clean-r9 (2026-11-04)')

    def test_shipped_server_has_the_offline_guard(self):
        if not self.version:
            self.skipTest('dist zip not built yet')
        self.assertIn("if not _wiki_web():", self.server)
        self.assertIn('never refetch it', self.server)

    def test_no_pycache_or_config_in_zip(self):
        if not self.names:
            self.skipTest('dist zip not built yet')
        self.assertFalse(any('__pycache__' in n or n.endswith('.pyc') for n in self.names))
        self.assertFalse(any(n.endswith('config.json') for n in self.names))


if __name__ == '__main__':
    unittest.main()
