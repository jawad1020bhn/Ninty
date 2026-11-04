"""Tests for the measured PES 2017 write engine (no Windows / game needed)."""
import hashlib
import json
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
import pescrypt       # noqa: E402
import pes17_write    # noqa: E402
import sample         # noqa: E402


class Pes17Header176(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pes17write_')
        self.parts = sample.make_parts17()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_176_header_roundtrip_and_208_is_rejected(self):
        raw = pescrypt.encrypt_parts(self.parts, pescrypt.KEY_PES17)
        got = pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES17)
        self.assertEqual(len(got['header.dat']), 176)
        self.assertEqual(got['data.dat'], self.parts['data.dat'])
        self.assertEqual(got['description.dat'], self.parts['description.dat'])
        self.assertEqual(raw, pescrypt.encrypt_parts(got, pescrypt.KEY_PES17))
        with self.assertRaises(ValueError):
            pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES21)

    def test_208_header_still_works_for_pes2021(self):
        p = sample.make_parts(sample.make_ml_data(), sample.DESC)
        raw = pescrypt.encrypt_parts(p, pescrypt.KEY_PES21)
        got = pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES21)
        self.assertEqual(len(got['header.dat']), 208)
        self.assertEqual(got['data.dat'], p['data.dat'])

    def test_container_load_save_roundtrip(self):
        p = dict(self.parts)
        p['header.dat'] = bytes(176)
        p['header.dat'] = p['header.dat'][:144] + b'ML' + bytes(30)
        raw = pescrypt.encrypt_parts(p, pescrypt.KEY_PES17)
        path = os.path.join(self.tmp, 'ML00000000')
        with open(path, 'wb') as f:
            f.write(raw)
        c = pes17_write.Pes17Container.load(path)
        self.assertEqual(len(c.parts['header.dat']), 176)
        self.assertEqual(c.encrypt(), raw)
        n = c.save(path)
        self.assertEqual(n, len(raw))
        with open(path, 'rb') as f:
            self.assertEqual(hashlib.sha256(f.read()).digest(),
                             hashlib.sha256(raw).digest())

    def test_shirt_write_and_safety_range(self):
        p = dict(self.parts)
        p['header.dat'] = bytes(144) + b'ML' + bytes(30)
        raw = pescrypt.encrypt_parts(p, pescrypt.KEY_PES17)
        path = os.path.join(self.tmp, 'ML00000000')
        with open(path, 'wb') as f:
            f.write(raw)
        c = pes17_write.Pes17Container.load(path)
        before = bytes(c.data)
        res, changed = pes17_write.apply_ops(c, [
            dict(op='shirt', club=100, slot=0, number=9)])
        self.assertEqual(changed, 1)
        self.assertEqual(res[0]['new'], 9)
        self.assertNotEqual(c.data, before)
        raw2 = c.encrypt()                     # proves re-encryption
        self.assertEqual(pescrypt.decrypt_bytes(raw2, pescrypt.KEY_PES17)['data.dat'], c.data)
        work = os.path.join(self.tmp, 'work')
        r = pes17_write.save_with_backup(path, c, work)
        self.assertTrue(r['ok'])
        self.assertTrue(os.path.isfile(r['backup']))
        self.assertEqual(pes17_write.Pes17Container.load(path).data, c.data)

    def test_out_of_range_write_is_refused(self):
        p = dict(self.parts)
        p['header.dat'] = bytes(144) + b'ML' + bytes(30)
        raw = pescrypt.encrypt_parts(p, pescrypt.KEY_PES17)
        path = os.path.join(self.tmp, 'ML00000000')
        with open(path, 'wb') as f:
            f.write(raw)
        c = pes17_write.Pes17Container.load(path)
        with self.assertRaisesRegex(ValueError, 'outside every measured'):
            # The raw escape hatch is still bound by the measured ranges.
            pes17_write.apply_ops(c, [dict(op='raw', offset=4000000, values=[1])])


class Pes17RealSave(unittest.TestCase):
    """Only runs when the user's real files are present in the repo."""
    ML = os.path.join(ROOT, 'Needed files', 'ML00000011')
    EDIT = os.path.join(ROOT, 'Needed files', 'EDIT00000000')

    @classmethod
    def setUpClass(cls):
        if not (os.path.isfile(cls.ML) and os.path.isfile(cls.EDIT)):
            raise unittest.SkipTest('real t99p17v20 saves not in the workspace')

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pes17real_')
        self.ml = os.path.join(self.tmp, 'ML00000011')
        shutil.copy2(self.ML, self.ml)
        with open(self.ML, 'rb') as f:
            self.orig_sha = hashlib.sha256(f.read()).digest()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_real_files_decrypt_and_re_encrypt_byte_identically(self):
        for src in (self.ML, self.EDIT):
            with open(src, 'rb') as f:
                raw = f.read()
            parts = pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES17)
            self.assertEqual(len(parts['header.dat']), 176)
            self.assertEqual(pescrypt.encrypt_parts(parts, pescrypt.KEY_PES17), raw)

    def test_real_career_is_read_correctly(self):
        c = pes17_write.Pes17Container.load(self.ML)
        e = pes17_write.Pes17Container.load(self.EDIT)
        i = pes17_write.info(c, e)
        self.assertEqual(i['info']['club'], 'Birmingham City FC')
        self.assertEqual(i['info']['date'], '10/1/2029')
        self.assertEqual(len(i['squad']), 26)
        self.assertEqual(i['squad'][0]['name'], 'K. Vasilj')
        self.assertEqual(i['squad'][0]['shirt'], 2)
        self.assertEqual(i['league_name'], 'Sky Bet Championship')
        self.assertEqual(len(i['league_table']), 20)
        self.assertEqual(i['league_table'][0]['club'], 'Birmingham City FC')
        self.assertEqual(len(i['offers']), 0)

    def test_verified_writes_on_real_save(self):
        c = pes17_write.Pes17Container.load(self.ml)
        e = pes17_write.Pes17Container.load(self.EDIT)
        ops = [dict(op='offer_add', buyer=101, slot=0, pid=55246),
               dict(op='shirt', club=201, slot=0, number=9)]
        res, changed = pes17_write.apply_ops(c, ops, e.data)
        self.assertEqual(changed, 9)
        self.assertEqual(res[0]['buyer'], 'Arsenal FC')
        self.assertEqual(res[0]['source_club'], 'Birmingham City FC')
        self.assertEqual(res[1]['new'], 9)
        i = pes17_write.info(c, e)
        self.assertEqual(len(i['offers']), 1)
        self.assertEqual(i['offers'][0]['pid'], 55246)
        self.assertEqual(i['squad'][0]['shirt'], 9)
        r = pes17_write.save_with_backup(self.ml, c, self.tmp)
        self.assertTrue(r['ok'])
        back = pes17_write.Pes17Container.load(self.ml)
        self.assertEqual(back.data, c.data)
        # original in the repo was never touched
        with open(self.ML, 'rb') as f:
            self.assertEqual(hashlib.sha256(f.read()).digest(), self.orig_sha)
        with open(self.ml, 'rb') as f:
            self.assertNotEqual(hashlib.sha256(f.read()).digest(), self.orig_sha)

    def test_bad_op_does_not_change_the_save(self):
        c = pes17_write.Pes17Container.load(self.ml)
        before = bytes(c.data)
        with self.assertRaisesRegex(ValueError, 'unknown buyer club'):
            pes17_write.apply_ops(c, [dict(op='offer_add', buyer=999999,
                                           slot=0, pid=1)])
        self.assertEqual(c.data, before)

    def test_human_club_has_no_ai_block_and_claim_is_explicit(self):
        c = pes17_write.Pes17Container.load(self.ml)
        teams = pes17.team_records(c.data)
        with self.assertRaisesRegex(ValueError, 'human-controlled club'):
            pes17.find_offer_block(bytearray(c.data), teams, 201)
        d = bytearray(c.data)
        off, club, claimed = pes17.find_offer_block(d, teams, 201, claim=True)
        self.assertTrue(claimed)
        self.assertEqual(struct.unpack_from('<I', d, off)[0], club['id'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
