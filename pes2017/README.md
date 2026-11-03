# The Gaffer — PES 2017 compatibility pack

This directory contains the source of a **read-only PES 2017 port** of
`TheGaffer_pc414_20261103.zip` (The Gaffer pc414, a Football Manager style
companion app for Football Life 26 / PES 2021 and FL27 Master League).

## TL;DR

| | PES 2021 / FL26 / FL27 (original) | PES 2017 (this build) |
|---|---|---|
| Save container decryption | PES 2021 key (+ FL27 key) | **PES 2017 key, auto-detected** |
| Club, league, date, next competition | read | **read** |
| Squad (players, names, ages, attributes, OVR) | read from save + F7 dump | **read from save + `EDIT00000000`** |
| League table | full | **positions only** (points/goals not mapped) |
| Transfers, loans, contracts, tactics, training, AI moves | written into the save | **blocked** (different save layout) |
| App-side career (inbox, negotiations, board, press, scouting, awards...) | works | **works** |

Everything that would write into a PES 2017 Master League save is refused by
three independent guards, so the save cannot be corrupted.

## Files

```
pes2017/
  overlay/lib/pes17.py               core: keys, ML save reader, EDIT importer, read-only Save adapter
  overlay/lib/pes17_layout.py        diagnostic CLI: info / diff / edit (for mapping write tables)
  overlay/README_PES2017.txt         user documentation, shipped in the zip
  overlay/config_pes2017.example.json  example config.json for PES 2017
  patch.py                           exact, asserted text patches for the pc414 sources
  build.py                           extract original zip -> patch -> dist/TheGaffer_pes2017_pc414.zip
  tests/sample.py                    synthetic but structurally faithful PES 2017 saves
  tests/test_pes17.py                15 unit tests (crypto, detection, parsing, EDIT DB, write guard)
  dist/TheGaffer_pes2017_pc414.zip   the ready-to-unzip Windows build
```

Rebuild after changing anything in `overlay/` or `patch.py`:

```bash
python3 pes2017/build.py
python3 -m unittest discover -s pes2017/tests -p 'test_*.py' -v
```

`patch.py` fails loudly if the upstream pc414 source changes, so the patch can
never be applied half-way by accident.

## What was changed in the original program

* `lib/pescrypt.py` — added `KEY_PES17` (from pesXdecrypter `src/masterkey.c`,
  public domain), `key_candidates()` and `key_for()`. The container algorithm
  (MT19937 + rolling XOR, 320 B encryption header, 208 B file header) is the
  same for PES 2016–2021; only the 64-byte master key differs.
* `server.py` — decryption tries all known keys and writes the winning key name
  into `gaffer_key.txt`; encryption uses that key and refuses PES 2017 writes;
  `_game_of()` recognises `pes17`; `data/pes17/*.json` player database is built
  automatically from `EDIT00000000`; Setup finds PES 2017 save folders and
  process names; the state endpoint reads PES 2017 club/squad/standings;
  `--host` was added for LAN/preview hosting.
* `lib/mlwrite.py` — `Save.__new__` returns `pes17.Pes17Save` for PES 2017
  folders; this single hook redirects **all 169** `mlwrite.Save(...)` calls.
  `flag_map()` returns `{}` on PES 2017 data (no FL26 zlib chain).
* `lib/pes17.py` (new) — reads the PES 2017 ML team table (offset 80,
  1312 B records, 64 B name at +4), the 32-slot squad list (+248, pairs of
  roster pointer / player id), the standing structures (8617528, 2600 B per
  league), and the EDIT player database (188 B records from offset 120:
  116 B player entry + 72 B appearance entry). It builds `players.json`,
  `ratings.json`, `positions.json`, `playpos.json` and `teamids.json` in the
  exact shapes `reload_db()` expects. Attributes are decoded from the bitfields
  documented on the Rigged Wiki PES 2017 Edit file page; OVR is estimated with
  the app's own `dbimport.ovr_of()` linear model.
* `static/index.html` — a PES 2017 read-only banner.
* `VERSION.txt`, `README_PES2017.txt`, `config_pes2017.example.json` — docs.

## Verified

* 15 unit tests pass, including a full PES 2017 encrypt → decrypt round trip,
  rejection of the PES 2021 key, detection by both marker and binary
  signature, description/date parsing, team/squad/standings parsing, EDIT
  database import, and refusal of every write path.
* End-to-end smoke test: the patched server was started against a synthetic
  encrypted PES 2017 `ML00000000` + `EDIT00000000`. `/api/state` returned the
  real club, date, 32-player squad (with names from EDIT), 20-row league table
  and `layout.pes17=true`. 124 of 127 GET endpoints returned 200; the three
  exceptions are two dev-only lab endpoints and the national-team squad view
  (which correctly reports there is no national team). Four POST write
  endpoints were refused and the save file's SHA-256 was unchanged.

## Why writing is disabled

`mlwrite.py` (~6,300 lines) writes at hard-coded PES 2021/FL26 offsets. PES
2017 uses a different database:

| structure | PES 2017 | PES 2021 / FL26 |
|---|---|---|
| club table start | 80 | 84 |
| club record size | 1312 B | 1680 B |
| squad list | +248, 32 × 8 B (roster ptr, id) | +332, 40 × 8 B (id, tag) |
| ML save size | ~9.9 MB | 19.9 / 45 / 60 MB |
| formation block (`F0`) | not mapped | 1,675,944 (+shift) |
| tactics table (`TAC0`) | not mapped | 1,260,140 (+shift) |
| EDIT player record | 188 B from 120 | different table |

Writing FL26 offsets into that file would corrupt the career. The companion
`lib/pes17_layout.py diff` command is designed to map these tables from pairs
of real saves (one in-game action per pair) so that features can be unlocked
one by one. Send a few save pairs to enable transfers/tactics/etc.

## Sources

* [the4chancup/pesXdecrypter](https://github.com/the4chancup/pesXdecrypter) — public-domain container algorithm and per-version master keys.
* [Rigged Wiki: PES 2017 Edit file](https://implyingrigged.info/wiki/Pro_Evolution_Soccer_2017/Edit_file) — player entry bitfields.
* [PES2017-Master-League-Transfer-Engine](https://github.com/irvantaufik28/PES2017-Master-League-Transfer-Engine) — ML save club table, squad list and standings offsets.

The Gaffer is free fan-made software; see `README.txt` in the program folder
for its FREE TO USE terms. This modified build is for personal use — do not
reupload it or present it as the original work.
