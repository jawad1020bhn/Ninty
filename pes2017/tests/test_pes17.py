"""Unit tests for the PES 2017 compatibility layer.

Run:  cd /home/user/Ninty && python3 -m unittest discover -s pes2017/tests -v
(or)  python3 pes2017/tests/test_pes17.py
"""
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pes17          # noqa: E402
import pescrypt       # noqa: E402
import mlwrite        # noqa: E402
import sample         # noqa: E402


class Pes17Crypto(unittest.TestCase):
    def test_master_key_is_the_published_pes17_key(self):
        self.assertEqual(len(pescrypt.KEY_PES17), 64)
        self.assertEqual(pescrypt.KEY_PES17[:8],
                         bytes([0x9B, 0xC7, 0x13, 0x28, 0x2D, 0xE8, 0x47, 0x75]))
        self.assertNotEqual(pescrypt.KEY_PES17, pescrypt.KEY_PES21)

    def test_encrypt_decrypt_roundtrip_and_wrong_key_rejected(self):
        parts = sample.make_parts(sample.make_ml_data(), sample.DESC)
        raw = pescrypt.encrypt_parts(parts, pescrypt.KEY_PES17)
        got = pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES17)
        self.assertEqual(got['data.dat'], parts['data.dat'])
        self.assertEqual(got['description.dat'], parts['description.dat'])
        with self.assertRaises(ValueError):
            pescrypt.decrypt_bytes(raw, pescrypt.KEY_PES21)

    def test_key_candidates_find_pes17(self):
        raw = pescrypt.encrypt_parts(
            sample.make_parts(sample.make_ml_data(), sample.DESC), pescrypt.KEY_PES17)
        found = None
        for name, key in pescrypt.key_candidates(None):
            if key is None:
                continue
            try:
                pescrypt.decrypt_bytes(raw, key)
                found = name
                break
            except ValueError:
                continue
        self.assertEqual(found, 'pes17')
        self.assertEqual(pescrypt.key_for('pes17'), pescrypt.KEY_PES17)


class Pes17Reading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pes17test_')
        self.dec = sample.write_dec(os.path.join(self.tmp, 'dec'))
        self.dec_nomark = sample.write_dec(os.path.join(self.tmp, 'dec_nomark'), marker=False)
        self.edit = sample.write_enc(os.path.join(self.tmp, 'save'), ml=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detect_by_marker_and_by_signature(self):
        self.assertTrue(pes17.is_pes17(self.dec))
        self.assertTrue(pes17.is_pes17(self.dec_nomark))

    def test_not_detected_on_pes2021_like_save(self):
        d = bytearray(20000000)
        d[84:84 + 12] = b'Arsenal FC\0\0'
        d[84 + 1680:84 + 1680 + 12] = b'Chelsea FC\0\0'
        fake = os.path.join(self.tmp, 'fake21')
        os.makedirs(fake)
        with open(os.path.join(fake, 'data.dat'), 'wb') as f:
            f.write(d)
        self.assertFalse(pes17.is_pes17(fake))

    def test_description(self):
        i = pes17.read_description(self.dec)
        self.assertEqual(i['slot'], 'ML00000000')
        self.assertEqual(i['league'], 'Premier League')
        self.assertEqual(i['date'], '7/1/2038')     # D/M/YYYY stays D/M/YYYY
        self.assertEqual(i['next_competition'], 'Premier League')
        self.assertEqual(pes17.game_date_code(self.dec), (7 << 24) | (1 << 16) | 2038)

    def test_mdy_config(self):
        i = pes17.read_description(self.dec, 'mdy')
        self.assertEqual(i['date'], '1/7/2038')

    def test_team_table_and_squad(self):
        with open(os.path.join(self.dec, 'data.dat'), 'rb') as f:
            d = f.read()
        teams = pes17.team_records(d)
        self.assertEqual(len(teams), len(sample.CLUBS))
        self.assertEqual(teams[0]['name'], 'Arsenal FC')
        self.assertEqual(teams[1]['off'] - teams[0]['off'], 1312)
        sq = pes17.squad(d, teams[0])
        self.assertEqual(len(sq), 32)
        self.assertEqual(sq[0]['id'], sample.PLAYERS[0][0])

    def test_read_save_shape_matches_mlsave(self):
        r = pes17.read_save(self.dec)
        self.assertEqual(set(('info', 'clubs', 'squad', 'league_table')) - set(r), set())
        self.assertEqual(r['clubs'], len(sample.CLUBS))
        self.assertEqual(len(r['league_table']), len(sample.CLUBS))
        self.assertEqual(r['league_table'][0]['club'], 'Arsenal FC')
        self.assertEqual(len(r['squad']), 32)

    def test_edit_import_builds_app_database(self):
        out = os.path.join(self.tmp, 'db')
        st = pes17.import_edit(self.edit, out)
        self.assertEqual(st['players'], len(sample.PLAYERS))
        players = json.load(open(os.path.join(out, 'players.json'), encoding='utf-8'))
        pos = json.load(open(os.path.join(out, 'positions.json'), encoding='utf-8'))
        pp = json.load(open(os.path.join(out, 'playpos.json'), encoding='utf-8'))
        rat = json.load(open(os.path.join(out, 'ratings.json'), encoding='utf-8'))
        self.assertEqual(players[0][1], 'P. Check')
        self.assertEqual(pos[str(sample.PLAYERS[0][0])], 0)
        self.assertEqual(pp[str(sample.PLAYERS[0][0])][0], '2')
        self.assertEqual(len(rat['ab']), 25)
        self.assertTrue(40 <= rat['p'][str(sample.PLAYERS[0][0])][0] <= 99)
        self.assertEqual(len(rat['p'][str(sample.PLAYERS[0][0])][10]), 25)

    def test_import_teams(self):
        out = os.path.join(self.tmp, 'db2')
        st = pes17.import_teams(self.dec, out)
        self.assertEqual(st['teams'], len(sample.CLUBS))
        ids = json.load(open(os.path.join(out, 'teamids.json'), encoding='utf-8'))
        self.assertEqual(ids['100'], 'Arsenal FC')


class Pes17SaveAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='pes17save_')
        self.dec = sample.write_dec(os.path.join(self.tmp, 'dec'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_factory_returns_adapter(self):
        s = mlwrite.Save(self.dec)
        self.assertIsInstance(s, pes17.Pes17Save)
        self.assertTrue(s.pes17)
        self.assertEqual(type(s.d), bytes)

    def test_read_api(self):
        s = mlwrite.Save(self.dec, ro=True)
        self.assertEqual(s.club_name(), 'Arsenal FC')
        self.assertEqual(s.squad_ids()[:3],
                         [sample.PLAYERS[0][0], sample.PLAYERS[1][0], sample.PLAYERS[2][0]])
        self.assertEqual(len(s.lineup()), 35)
        self.assertEqual(len(s.formation_rows(0)), 11)
        self.assertEqual(s.game_date_code(), (7 << 24) | (1 << 16) | 2038)
        self.assertEqual(s.budget(), 0)
        self.assertEqual(s.my_tactics(), None)

    def test_every_write_is_refused(self):
        s = mlwrite.Save(self.dec)
        with self.assertRaisesRegex(ValueError, 'read-only'):
            s.save()
        with self.assertRaisesRegex(ValueError, 'read-only'):
            s.write_guard()
        with self.assertRaisesRegex(ValueError, 'read-only'):
            s.set_formation(0, '4-4-2')
        with self.assertRaises(TypeError):
            s.d[0] = 1          # immutable: no in-place editing either

    def test_unknown_read_methods_do_not_crash(self):
        s = mlwrite.Save(self.dec)
        self.assertEqual(len(s.some_unmapped_table()), 0)
        self.assertEqual(s.BUDGET, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
