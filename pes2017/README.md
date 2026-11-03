# The Gaffer — PES 2017 compatibility pack (real-save build)

Source of the PES 2017 port of `TheGaffer_pc414_20261103.zip` (a Football
Manager style companion for Football Life 26 / PES 2021 / FL27 Master League).

**This build was rebuilt after the user supplied real files** in
`Needed files/`: `ML00000011`, `EDIT00000000` and `info.txt`
(patch `t99p17v20`, game folder `D:\jawedfolder\Games\Pro Evolution Soccer 2017`).
The first build was synthetic-only; the real files exposed a blocking crypto bug
and let us measure the actual tables. Full measurements and honest validation
status: [`REAL_SAVE_REPORT.md`](REAL_SAVE_REPORT.md).

## TL;DR

| | original FL26/PES2021 | this build on real PES 2017 |
|---|---|---|
| container key | PES 2021 / FL27 | **PES 2017 key, auto-detected** |
| file header | 208 B | **176 B (fixed)** |
| club, date, league, next competition | read | **read** |
| squad + names/attributes | save + Sider dump | **save + `EDIT00000000` (20,018 players)** |
| shirt numbers | read | **read + write** |
| league table | full | **20 rows, positions only** (points not mapped) |
| transfer negotiations | app-side | **read + write (measured slots)** |
| transfers, loans, contracts, tactics, formation, budgets, training | written | **blocked** (needs save pairs) |
| app-side career (inbox, board, press, scouting, awards…) | works | **works** |

Real result: Birmingham City FC, `10/1/2029`, 26-player squad with real names,
Sky Bet Championship table (20 rows), 0 active negotiations.

## Files

```
pes2017/
  overlay/lib/pes17.py               keys, ML/EDIT readers, measured write tables, read-only Save adapter
  overlay/lib/pes17_layout.py        diagnostic CLI: info / diff / edit (maps before/after save pairs)
  overlay/lib/pes17_write.py         real-save container I/O + whitelisted, round-trip-verified writes
  overlay/static/pes17.html          PES 2017 tools page (read + write UI)
  overlay/README_PES2017.txt         user docs, shipped in the zip
  overlay/config_pes2017.example.json
  patch.py                           40 asserted text patches for pc414 sources
  build.py                           extract original zip -> patch -> dist/TheGaffer_pes2017_pc414.zip
  tests/sample.py                    synthetic but structurally faithful PES 2017 saves
  tests/test_pes17.py                15 unit tests (crypto, detection, parsing, EDIT DB, write guard)
  tests/test_pes17_write.py          10 tests: 176 B header, container round-trip, real-file reads/writes
  REAL_SAVE_REPORT.md                measurements + validation status
  dist/TheGaffer_pes2017_pc414.zip   the ready-to-unzip Windows build
```

Rebuild / test:

```bash
python3 pes2017/build.py
python3 -m unittest discover -s pes2017/tests -p 'test_*.py' -v
```

`patch.py` fails loudly if upstream pc414 drifts. The build is syntax-checked
in memory and contains no `__pycache__` / `.pyc`.

## What changed in the original program

* `lib/pescrypt.py` — `KEY_PES17`, `key_candidates()`, `key_for()`; **dual
  header sizes** (208 B for PES 2021/FL, 176 B for PES 2017) in
  `decrypt_bytes()` / `encrypt_parts()`. Decrypt → re-encrypt of both real user
  files is byte-identical.
* `server.py` — decryption tries all keys, remembers the winner in
  `gaffer_key.txt`; `_game_of()` recognises `pes17`; `data/pes17/*.json` is
  built automatically from `EDIT00000000`; Setup finds PES 2017 paths; state
  reads real club/squad/standings (with EDIT-derived competition names); new
  `/api/pes17/info`, `/api/pes17/offers`, `/api/pes17/write` endpoints;
  `--host` for LAN/preview.
* `lib/mlwrite.py` — `Save.__new__` returns `pes17.Pes17Save` for PES 2017
  folders (redirects all 169 constructions); `flag_map()` returns `{}`.
* `lib/pes17.py` — team table (80 / 1312 / `tid = cid >> 14`), squad (+248),
  shirt numbers (+512), standings located dynamically from EDIT league arrays,
  EDIT player DB (188 B records from 120, count from `0x5C`), competition
  names from EDIT, negotiation blocks (9,591,148), read-only `Save` adapter.
* `lib/pes17_write.py` — `Pes17Container`, `info()`, `apply_ops()`,
  `save_with_backup()`; every changed byte must be inside a measured table.
* `static/index.html` — PES 2017 banner links to the tools page.
* `static/pes17.html` — tools UI: slot picker, real-save info, squad/table/
  offers, queued ops, dry-run, backups.

## Safety model

* All FL26-style write endpoints still raise `pes17.READ_ONLY_MSG` — PES 2021
  offsets cannot be written into a PES 2017 save.
* PES 2017 writes are limited to measured tables: negotiation slots, shirt
  numbers, (experimental) squad slots, and a u32 `raw` escape hatch that is
  still range-checked.
* Every write: decrypt → mutate bytearray → assert changed bytes are inside
  measured ranges → re-encrypt → decrypt again → compare all six parts →
  `.tmp` + `os.replace` → reload from disk → compare → timestamped backup.
* Dry-run proves the ops without touching the save. Bad ops write nothing.

## Verified

* **25 unit tests pass**, including tests that decrypt, read, modify and
  re-encrypt the user's real `ML00000011` / `EDIT00000000` (on copies only).
* End-to-end HTTP smoke on the real files: `/api/state`, `/api/pes17/info`,
  `/api/pes17/offers`, 14 other GET endpoints all 200. Dry write left the
  SHA-256 unchanged; real write changed 9 bytes, offers 0 → 1, shirt 2 → 9,
  and produced a backup. `/api/apply` and friends were still refused.
* `READ_ONLY_MSG` guards and `sha256sum` checks confirm FL26 endpoints never
  touch the save.

## NOT verified / still needed

* Game-side confirmation that an injected offer appears in PES 2017's inbox
  (no Windows/game run in this sandbox).
* The `claim` path for the human club (no AI negotiation block).
* Formations, lineup, tactics, contracts, budgets, transfers, loans, youth,
  training, points/goals — need **before/after save pairs** (one in-game change
  per pair). Use `lib/pes17_layout.py diff before after`.

See `REAL_SAVE_REPORT.md` for the exact offsets, the honest validation table,
and the sources.

## Sources

* [the4chancup/pesXdecrypter](https://github.com/the4chancup/pesXdecrypter) — public-domain container algorithm + per-version keys.
* [Rigged Wiki: PES 2017 Edit file](https://implyingrigged.info/wiki/Pro_Evolution_Soccer_2017/Edit_file) — player bitfields.
* [PES2017-Master-League-Transfer-Engine](https://github.com/irvantaufik28/PES2017-Master-League-Transfer-Engine) — club/squad/standings/offer offsets, team-id shift, in-game checklist.
* The user's real `Needed files/*`.

The Gaffer is free fan-made software; see `README.txt` in the program folder
for its FREE TO USE terms. This modified build is for personal use — do not
reupload it or present it as the original work.
