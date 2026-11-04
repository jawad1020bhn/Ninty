"""r5: layout guard + real shirt numbers / starting XI read-side.

No Windows or game needed: every test uses the real t99p17v20 files that are
already in the repo, decrypted in memory.  Nothing is written to those files.
"""
import os
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.environ.get('GAFFER_LIB', os.path.join(ROOT, 'build', 'TheGaffer', 'TheGaffer', 'lib'))
OVERLAY = os.path.join(ROOT, 'pes2017', 'overlay', 'lib')
sys.path.insert(0, LIB)
sys.path.insert(0, OVERLAY)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pes17          # noqa: E402
import pes17_pairs    # noqa: E402
import pes17_write    # noqa: E402
import pescrypt       # noqa: E402

REAL_ML = os.path.join(ROOT, 'Needed files', 'ML00000011')


def real_container():
    with open(REAL_ML, 'rb') as f:
        raw = f.read()
    return pes17_write.Pes17Container(
        pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES17))


class LayoutGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(REAL_ML):
            raise unittest.SkipTest('real t99p17v20 save not in the workspace')

    def test_real_save_passes_every_check(self):
        c = real_container()
        rep = pes17_pairs.verify_layout(c.data)
        self.assertEqual(rep['mode'], 'verified')
        self.assertTrue(rep['ok'], rep)
        self.assertEqual(rep['data_size'], pes17_pairs.DATA_SIZE)
        self.assertTrue(all(rep['checks'].values()), rep['checks'])
        self.assertEqual(rep['anchors_matched'], rep['anchors_total'])
        self.assertFalse(rep['problems'])

    def test_wrong_sized_save_is_refused(self):
        d = bytearray(pes17_pairs.DATA_SIZE + 512)
        with self.assertRaisesRegex(ValueError, 'layout verification FAILED'):
            pes17_pairs.verify_layout(d)
        rep = pes17_pairs.verify_layout(d, strict=False)
        self.assertEqual(rep['mode'], 'override')
        self.assertTrue(any('expected' in p for p in rep['problems']))

    def test_synthetic_buffer_is_reported_not_refused(self):
        rep = pes17_pairs.verify_layout(bytearray(4096))
        self.assertEqual(rep['mode'], 'synthetic')
        self.assertTrue(rep['ok'])

    def test_small_but_real_container_is_refused_when_check_is_forced(self):
        # An EDIT00000000 data.dat is 5,266,180 B.  The HTTP/CLI callers force
        # require_real=True, so it cannot slip through as "synthetic".
        d = bytearray(5266180)
        with self.assertRaisesRegex(ValueError, 'layout verification FAILED'):
            pes17_pairs.verify_layout(d, require_real=True)
        rep = pes17_pairs.verify_layout(d, strict=False, require_real=True)
        self.assertEqual(rep['mode'], 'override')
        self.assertIn('expected', ' '.join(rep['problems']))

    def test_broken_table_structure_blocks_any_custom_op(self):
        c = real_container()
        # Corrupt the XI permutation and the formation marker.  Those are
        # exactly the checks that must stop a save from a different layout.
        d = bytearray(c.data)
        d[pes17_pairs.XI_ORDER] = 0xff
        d[pes17_pairs.FORMATION0] = 0x7f
        c.set_data(d)
        before = bytes(c.data)
        with self.assertRaisesRegex(ValueError, 'layout verification FAILED'):
            pes17_write.apply_ops(c, [dict(op='budget', value=3088641)])
        self.assertEqual(c.data, before)

    def test_all_four_custom_ops_still_work_with_the_guard(self):
        c = real_container()
        record = bytes(c.data[pes17_pairs.FORMATION0:
                              pes17_pairs.FORMATION0 + 33])
        order = list(bytes(c.data[pes17_pairs.XI_ORDER:
                                  pes17_pairs.XI_ORDER + 26]))
        ops = [
            dict(op='formation', index=0, record=record.hex()),
            dict(op='tactics', values={'1256356': 3}),
            dict(op='xi', order=order),
            dict(op='budget', value=3088641, wage=10245745),
        ]
        res, changed = pes17_write.apply_ops(c, ops)
        self.assertEqual(len(res), 4)
        self.assertEqual(c.layout['mode'], 'verified')
        self.assertTrue(c.layout['ok'])
        self.assertGreater(changed, 0)

    def test_auto_guard_is_enabled_for_real_saves(self):
        c = real_container()
        res, changed = pes17_write.apply_ops(c, [
            dict(op='pair', name='formation')])
        self.assertEqual(changed, 17)
        self.assertEqual(c.layout['mode'], 'verified')

    def test_report_mode_runs_checks_without_refusing(self):
        c = real_container()
        d = bytearray(c.data)
        d[pes17_pairs.XI_ORDER] = 0x7f
        c.set_data(d)
        res, changed = pes17_write.apply_ops(
            c, [dict(op='pair', name='formation')], layout_check='report')
        self.assertEqual(c.layout['mode'], 'override')
        self.assertIn('warning', c.layout)

    def test_explicit_opt_out_is_loud(self):
        c = real_container()
        res, changed = pes17_write.apply_ops(
            c, [dict(op='pair', name='formation')], layout_check=False)
        self.assertEqual(c.layout['mode'], 'skipped')
        self.assertIn('DISABLED', c.layout['warning'])

    def test_unrelated_season_changes_do_not_break_the_guard(self):
        # A legitimately advanced save changes thousands of bytes, but the
        # structural markers and the sampled anchors must still pass.
        c = real_container()
        d = bytearray(c.data)
        for i in range(200000, 200400):
            d[i] ^= 0x5a
        rep = pes17_pairs.verify_layout(d)
        self.assertTrue(rep['ok'], rep)
        self.assertEqual(rep['anchors_matched'], rep['anchors_total'])


class ReadSideR5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(REAL_ML):
            raise unittest.SkipTest('real t99p17v20 save not in the workspace')

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pes17r5_')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_real_shirt_numbers_and_starting_xi_are_read(self):
        c = real_container()
        for k in ('data.dat', 'description.dat'):
            with open(os.path.join(self.tmp, k), 'wb') as f:
                f.write(c.parts[k])
        with open(os.path.join(self.tmp, pes17.KEY_MARK), 'w') as f:
            f.write(pes17.PES17_GAME)
        s = pes17.open_save(self.tmp)
        self.assertTrue(getattr(s, 'pes17', False))
        nums = s.squad_numbers()
        self.assertIn(0, nums)
        self.assertEqual(nums[0], 2)           # K. Vasilj wears 2
        self.assertTrue(all(1 <= n <= 99 for n in nums.values()))
        lu = s.lineup()
        self.assertEqual(len(lu), 35)
        self.assertEqual(lu[:26], list(bytes(c.data[pes17.XI_ORDER:
                                                     pes17.XI_ORDER + 26])))
        self.assertEqual(lu[26:], [0xff] * 9)
        # still strictly read-only
        with self.assertRaises(ValueError):
            s.write_guard()

    def test_budget_reports_currency_as_unverified(self):
        c = real_container()
        b = c  # measured_budget lives on the read-only adapter
        for k in ('data.dat', 'description.dat'):
            with open(os.path.join(self.tmp, k), 'wb') as f:
                f.write(c.parts[k])
        with open(os.path.join(self.tmp, pes17.KEY_MARK), 'w') as f:
            f.write(pes17.PES17_GAME)
        s = pes17.open_save(self.tmp)
        m = s.measured_budget()
        self.assertEqual(m['transfer'], 2535240)
        self.assertEqual(m['salary'], 9692344)
        self.assertFalse(m['currency_verified'])
        self.assertEqual(m['unit'], 'raw u32 save units')

    def test_tools_info_labels_budget_raw(self):
        c = real_container()
        i = pes17_write.info(c)
        self.assertFalse(i['budget']['currency_verified'])
        self.assertEqual(i['budget']['label'], 'RAW (not confirmed EUR)')
        self.assertIn('compare', i['budget']['scale_note'].lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
