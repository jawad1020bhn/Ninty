"""r2 regression: the PES 2017 read adapter must expose the measured budget.

Before r2, ``Pes17Save.budget()`` returned a hardcoded 0, so every "Transfer
budget" tile in the app showed EUR 0 even though the real save contains the
two u32 words measured from the budget before/after pair.  These tests pin
the read side, and prove /api/pes17/info reports the same words.
"""
import os
import struct
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.environ.get('GAFFER_LIB', os.path.join(ROOT, 'build', 'TheGaffer', 'TheGaffer', 'lib'))
sys.path.insert(0, LIB)
sys.path.insert(0, os.path.join(ROOT, 'pes2017', 'overlay', 'lib'))

import pes17          # noqa: E402
import pes17_pairs    # noqa: E402
import pes17_write    # noqa: E402

REAL_ML = os.path.join(ROOT, 'Needed files', 'ML00000011')


def adapter(d):
    """Pes17Save without __init__ (which needs a full decrypted folder).

    measured_budget()/budget() only use self.d, so this is enough for a unit
    test and keeps the test independent of description.dat parsing.
    """
    s = object.__new__(pes17.Pes17Save)
    s.d = bytes(d)
    return s


class BudgetReadTests(unittest.TestCase):
    def test_constants_match_the_measured_pairs_table(self):
        self.assertEqual(pes17.BUDGET_MAIN, pes17_pairs.BUDGET_MAIN)
        self.assertEqual(pes17.BUDGET_WAGE, pes17_pairs.BUDGET_WAGE)

    def test_budget_reads_the_before_words_not_zero(self):
        d = bytearray(pes17_pairs.DATA_SIZE)
        struct.pack_into('<I', d, pes17_pairs.BUDGET_MAIN, 2535240)
        struct.pack_into('<I', d, pes17_pairs.BUDGET_WAGE, 9692344)
        s = adapter(d)
        self.assertEqual(s.budget(), 2535240)
        m = s.measured_budget()
        self.assertEqual(m['transfer'], 2535240)
        self.assertEqual(m['salary'], 9692344)
        self.assertTrue(m['raw'])
        self.assertEqual(m['offsets'], dict(transfer=8812904, salary=8812936))

    def test_budget_reads_the_after_words(self):
        d = bytearray(pes17_pairs.DATA_SIZE)
        struct.pack_into('<I', d, pes17_pairs.BUDGET_MAIN, 3088641)
        struct.pack_into('<I', d, pes17_pairs.BUDGET_WAGE, 10245745)
        s = adapter(d)
        self.assertEqual(s.budget(), 3088641)
        self.assertEqual(s.measured_budget()['salary'], 10245745)

    def test_short_or_empty_data_returns_zero_instead_of_raising(self):
        s = adapter(b'\x00' * 16)
        self.assertEqual(s.budget(), 0)
        self.assertEqual(s.measured_budget()['salary'], 0)

    def test_wage_commitment_is_still_zero(self):
        # FL26's sum-of-salaries is not mapped for PES 2017.  The measured
        # salary word must NOT be mislabelled as a wage total.
        d = bytearray(pes17_pairs.DATA_SIZE)
        struct.pack_into('<I', d, pes17_pairs.BUDGET_WAGE, 9692344)
        self.assertEqual(adapter(d).wage_commitment(), 0)


class RealSaveInfoTests(unittest.TestCase):
    @unittest.skipUnless(os.path.isfile(REAL_ML), 'real ML00000011 not present')
    def test_info_reports_the_real_before_values(self):
        c = pes17_write.Pes17Container.load(REAL_ML)
        b = pes17_write.info(c, None)['budget']
        self.assertEqual(b['transfer_raw'], 2535240)
        self.assertEqual(b['salary_raw'], 9692344)
        self.assertEqual(b['transfer_offset'], 8812904)
        self.assertEqual(b['salary_offset'], 8812936)
        self.assertTrue(b['raw'])

    @unittest.skipUnless(os.path.isfile(REAL_ML), 'real ML00000011 not present')
    def test_info_reflects_the_budget_pair_write(self):
        c = pes17_write.Pes17Container.load(REAL_ML)
        _, changed = pes17_write.apply_ops(c, [dict(op='pair', name='budget')])
        self.assertEqual(changed, len(pes17_pairs.PAIRS['budget']))
        b = pes17_write.info(c, None)['budget']
        self.assertEqual(b['transfer_raw'], 3088641)
        self.assertEqual(b['salary_raw'], 10245745)


if __name__ == '__main__':
    unittest.main()
