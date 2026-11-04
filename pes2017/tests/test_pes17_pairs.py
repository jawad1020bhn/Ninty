"""Tests for the four tables measured from real before/after PES 2017 saves."""
import hashlib
import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.environ.get('GAFFER_LIB', os.path.join(ROOT, 'build', 'TheGaffer', 'TheGaffer', 'lib'))
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'overlay', 'lib'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pes17          # noqa: E402
import pes17_pairs    # noqa: E402
import pes17_write    # noqa: E402
import pescrypt       # noqa: E402

REAL_ML = os.path.join(ROOT, 'Needed files', 'ML00000011')


def sha256_file(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def seeded_data(name):
    """A data.dat-sized buffer holding only the measured before-bytes."""
    d = bytearray(pes17_pairs.DATA_SIZE)
    for off, bef, _ in pes17_pairs.PAIRS[name]:
        d[off] = bef
    return d


class PairTableTests(unittest.TestCase):
    def test_every_measured_offset_is_in_range(self):
        for name, rows in pes17_pairs.PAIRS.items():
            for off, bef, aft in rows:
                self.assertTrue(0 <= off < pes17_pairs.DATA_SIZE, (name, off))
                self.assertTrue(0 <= bef <= 255 and 0 <= aft <= 255)
                self.assertNotEqual(bef, aft, (name, off))

    def test_each_pair_reproduces_its_after_bytes_only(self):
        for name, rows in pes17_pairs.PAIRS.items():
            d = seeded_data(name)
            seeded = bytes(d)
            res = pes17_pairs.apply_pair(d, name)
            self.assertEqual(res['op'], 'pair')
            self.assertEqual(res['offsets'], len(rows))
            self.assertEqual(res['changed_bytes'], len(rows))
            changed = {i for i, (x, y) in enumerate(zip(seeded, d)) if x != y}
            self.assertEqual(changed, {o for o, _, _ in rows})
            for off, _, aft in rows:
                self.assertEqual(d[off], aft, (name, off))

    def test_strict_mode_refuses_a_different_save(self):
        d = seeded_data('formation')
        d[1256252] = 0xff
        with self.assertRaises(ValueError):
            pes17_pairs.apply_pair(d, 'formation')
        res = pes17_pairs.apply_pair(d, 'formation', strict=False)
        self.assertEqual(res['offsets'], len(pes17_pairs.PAIRS['formation']))

    def test_unknown_pair_is_refused(self):
        with self.assertRaises(ValueError):
            pes17_pairs.apply_pair(seeded_data('xi'), 'contract')

    def test_writable_ranges_cover_every_measured_offset(self):
        ranges = pes17_pairs.writable_ranges()
        for off in pes17_pairs.all_offsets():
            self.assertTrue(any(lo <= off < hi for lo, hi in ranges), off)


class CustomOpTests(unittest.TestCase):
    def test_formation_record_validation_and_write(self):
        d = bytearray(pes17_pairs.DATA_SIZE)
        good = b'\x00\x01\x01\x01' + bytes(range(29))
        r = pes17_pairs.set_formation_record(d, good)
        self.assertEqual(r['offset'], pes17_pairs.FORMATION0)
        self.assertEqual(d[pes17_pairs.FORMATION0:
                           pes17_pairs.FORMATION0 + 33], good)
        with self.assertRaises(ValueError):
            pes17_pairs.set_formation_record(d, b'\x01' * 33)
        with self.assertRaises(ValueError):
            pes17_pairs.set_formation_record(d, b'\x00\x01\x01\x01' + b'\xff' * 29)
        with self.assertRaises(ValueError):
            pes17_pairs.set_formation_record(d, good, index=99)
        with self.assertRaises(ValueError):
            pes17_pairs.set_formation_record(d, good[:32])

    def test_tactics_only_allows_measured_offsets(self):
        d = bytearray(pes17_pairs.DATA_SIZE)
        r = pes17_pairs.set_tactic_bytes(d, {'1256356': 3, '1256357': 60})
        self.assertEqual(r['changed_bytes'], 2)
        self.assertEqual(d[1256356], 3)
        self.assertEqual(d[1256357], 60)
        with self.assertRaises(ValueError):
            pes17_pairs.set_tactic_bytes(d, {'1256355': 1})
        with self.assertRaises(ValueError):
            pes17_pairs.set_tactic_bytes(d, {'1256356': 999})

    def test_xi_order_must_be_a_permutation(self):
        d = bytearray(pes17_pairs.DATA_SIZE)
        order = list(range(26))
        r = pes17_pairs.set_xi_order(d, order)
        self.assertEqual(r['new'], order)
        self.assertEqual(bytes(d[pes17_pairs.XI_ORDER:
                                  pes17_pairs.XI_ORDER + 26]), bytes(order))
        with self.assertRaises(ValueError):
            pes17_pairs.set_xi_order(d, [0] * 26)
        with self.assertRaises(ValueError):
            pes17_pairs.set_xi_order(d, list(range(25)))

    def test_budget_u32_and_wage(self):
        d = bytearray(pes17_pairs.DATA_SIZE)
        r = pes17_pairs.set_budget(d, 3088641, wage=10247281)
        self.assertEqual(struct.unpack_from('<I', d, pes17_pairs.BUDGET_MAIN)[0],
                         3088641)
        self.assertEqual(struct.unpack_from('<I', d, pes17_pairs.BUDGET_WAGE)[0],
                         10247281)
        self.assertEqual(r['op'], 'budget')
        with self.assertRaises(ValueError):
            pes17_pairs.set_budget(d, -1)


class EngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pes17pairs_')
        self.path = os.path.join(self.tmp, 'ML00000011')
        shutil.copy2(REAL_ML, self.path)
        self.orig_sha = sha256_file(REAL_ML)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_apply_ops_pair_on_the_real_save(self):
        c = pes17_write.Pes17Container.load(self.path)
        before = bytes(c.data)
        orig_hash = c.parts['header.dat'][80:144]
        res, changed = pes17_write.apply_ops(c, [dict(op='pair', name='xi')])
        self.assertEqual(res[0]['name'], 'xi')
        self.assertEqual(changed, len(pes17_pairs.PAIRS['xi']))
        self.assertEqual(len(c.data), len(before))
        raw = c.encrypt()          # proves re-encryption
        back = pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES17)
        self.assertEqual(back['data.dat'], c.data)
        self.assertEqual(back['header.dat'][80:144], orig_hash)  # hash preserved
        # the repository original is never touched
        self.assertEqual(sha256_file(REAL_ML), self.orig_sha)

    def test_all_four_pairs_roundtrip(self):
        for name in pes17_pairs.PAIRS:
            c = pes17_write.Pes17Container.load(self.path)
            res, changed = pes17_write.apply_ops(c, [dict(op='pair', name=name)])
            self.assertEqual(changed, len(pes17_pairs.PAIRS[name]), name)
            raw = c.encrypt()
            self.assertEqual(
                pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES17)['data.dat'],
                c.data, name)

    def test_safety_net_still_blocks_unmeasured_raw_writes(self):
        c = pes17_write.Pes17Container.load(self.path)
        with self.assertRaises(ValueError):
            pes17_write.apply_ops(c, [dict(op='raw', offset=7000000,
                                           values=[1])])

    def test_formation_tactics_xi_budget_ops_roundtrip(self):
        ops = [
            dict(op='formation', index=0,
                 record=(b'\x00\x01\x01\x01' + bytes(range(29))).hex()),
            dict(op='tactics', values={'1256356': 3}),
            dict(op='xi', order=list(range(26))),
            dict(op='budget', value=3088641, wage=10247281),
        ]
        c = pes17_write.Pes17Container.load(self.path)
        res, changed = pes17_write.apply_ops(c, ops)
        self.assertEqual(len(res), 4)
        self.assertGreater(changed, 0)
        raw = c.encrypt()
        self.assertEqual(
            pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES17)['data.dat'], c.data)

    def test_save_with_backup_then_reload(self):
        c = pes17_write.Pes17Container.load(self.path)
        pes17_write.apply_ops(c, [dict(op='pair', name='budget')])
        r = pes17_write.save_with_backup(self.path, c, self.tmp)
        self.assertTrue(r['ok'])
        self.assertTrue(os.path.isfile(r['backup']))
        again = pes17_write.Pes17Container.load(self.path)
        self.assertEqual(again.data, c.data)
        self.assertEqual(sha256_file(REAL_ML), self.orig_sha)


class RealPairVerificationTests(unittest.TestCase):
    """Optional: prove the patches against the uploaded after files."""

    def test_measured_bytes_equal_the_game_generated_after_files(self):
        after_dir = os.path.join(ROOT, 'build', 'pairs')
        if not os.path.isfile(REAL_ML) or not os.path.isdir(after_dir):
            self.skipTest('after saves not present in this checkout')
        before = pes17_write.Pes17Container.load(REAL_ML).data
        found = 0
        for name in pes17_pairs.PAIRS:
            p = os.path.join(after_dir, name, 'ML00000011')
            if not os.path.isfile(p):
                continue
            with open(p, 'rb') as f:
                after = pescrypt.decrypt_bytes(f.read(), pescrypt.KEY_PES17)['data.dat']
            d = bytearray(before)
            pes17_pairs.apply_pair(d, name)
            for off, _, aft in pes17_pairs.PAIRS[name]:
                self.assertEqual(d[off], after[off], (name, off))
            found += 1
        self.assertGreater(found, 0)


if __name__ == '__main__':
    unittest.main()
