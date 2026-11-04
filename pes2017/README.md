# The Gaffer — PES 2017 compatibility pack (measured-pairs build)

Source of the PES 2017 port of `TheGaffer_pc414_20261103.zip` (a Football
Manager style companion for Football Life 26 / PES 2021 / FL27 Master League).

**This build was rebuilt twice after the user supplied real files.** First
`Needed files/`: `ML00000011`, `EDIT00000000`, `info.txt` (patch `t99p17v20`,
game folder `D:\jawedfolder\Games\Pro Evolution Soccer 2017`) and the Cheat
Engine `.CT` table. Then four game-generated after saves on `main`:
`formation/after`, `tactics/after`, `xi/after`, `budget/after` — one in-game
change each, with the original `ML00000011` as the common before file.
The real files exposed a blocking crypto bug; the pairs mapped four more write
tables. Full measurements and honest validation status:
[`REAL_SAVE_REPORT.md`](REAL_SAVE_REPORT.md).

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
| formation / tactics / XI / budget (measured tables) | written | **read + measured writes** (`pair` op reproduces PES 2017 exactly) |
| transfers, loans, contracts, training, arbitrary tactic values | written | **blocked** (needs more save pairs) |
| app-side career (inbox, board, press, scouting, awards…) | works | **works** |

Real result: Birmingham City FC, `10/1/2029`, 26-player squad with real names,
Sky Bet Championship table (20 rows), 0 active negotiations.

## Files

```
pes2017/
  overlay/lib/pes17.py               keys, ML/EDIT readers, measured write tables, read-only Save adapter
  overlay/lib/pes17_layout.py        diagnostic CLI: info / diff / edit (maps before/after save pairs)
  overlay/lib/pes17_write.py         real-save container I/O + whitelisted, round-trip-verified writes
  overlay/lib/pes17_pairs.py         four tables measured from real before/after save pairs
  tools/diff_saves.py                diff two encrypted saves directly (future pairs)
  tools/verify_pairs.py              prove the four measured patches against the after files
  tools/fetch_after_pairs.py         stage the 4 after saves from main into build/pairs (gitignored)
  tools/ct_player_table.py           cross-check the Cheat Engine table against the ML player records
  tools/prepare_pairs.bat            Windows CMD script that prepares pair folders
  overlay/static/pes17.html          PES 2017 tools page (read + write UI)
  overlay/README_PES2017.txt         user docs, shipped in the zip
  overlay/config_pes2017.example.json
  patch.py                           40 asserted text patches for pc414 sources
  build.py                           extract original zip -> patch -> dist/TheGaffer_pes2017_pc414.zip
  tests/sample.py                    synthetic but structurally faithful PES 2017 saves
  tests/test_pes17.py                15 unit tests (crypto, detection, parsing, EDIT DB, write guard)
  tests/test_pes17_write.py          10 tests: 176 B header, container round-trip, real-file reads/writes
  tests/test_pes17_pairs.py          15 tests: measured pairs, custom ops, engine integration, real after files
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
  New ops: `pair`, `formation`, `tactics`, `xi`, `budget`.
* `lib/pes17_pairs.py` — the 17/13/30/21 bytes PES 2017 changed in the four
  real pairs, plus validated builders for custom values.
* `static/index.html` — PES 2017 banner links to the tools page.
* `static/pes17.html` — tools UI: slot picker, real-save info, squad/table/
  offers, queued ops, dry-run, backups.

## Safety model

* All FL26-style write endpoints still raise `pes17.READ_ONLY_MSG` — PES 2021
  offsets cannot be written into a PES 2017 save.
* PES 2017 writes are limited to measured tables: negotiation slots, shirt
  numbers, (experimental) squad slots, the four tables from the real pairs
  (formation/tactics/XI/budget), and a u32 `raw` escape hatch that is still
  range-checked. `pair` checks the before-state before writing.
* Every write: decrypt → mutate bytearray → assert changed bytes are inside
  measured ranges → re-encrypt → decrypt again → compare all six parts →
  `.tmp` + `os.replace` → reload from disk → compare → timestamped backup.
* Dry-run proves the ops without touching the save. Bad ops write nothing.

## Verified

* **53 unit tests pass**, including tests that decrypt, read, modify and
  re-encrypt the user's real `ML00000011` / `EDIT00000000` (on copies only),
  tests proving all four measured pair patches against the game-generated
  after files, r2 regression tests for the budget read side
  (`Pes17Save.budget()` / `/api/pes17/info`), and r3 static checks for the
  game-HUD skin and its SVG icon pack.
* **r3: GAME UI.** `static/game-skin.css` + `static/game-skin.js` turn the
  website look into a console-style HUD (dark grid backdrop, angled mission
  panels, glowing stats, HUD strip, boot intro) on both `index.html` and
  `/pes17.html`. A 64-icon hand-drawn SVG sprite replaces ~97% of the app's
  colorful emoji at runtime, including dynamically rendered content. The
  bottom-right **GAME UI / CLASSIC UI** chip reverts to the original look.
  Pure CSS/JS/DOM: no save code, endpoint or app logic changed, no external
  assets added.
* r2: `Pes17Save.budget()` no longer returns a hardcoded `0`. It reads the
  measured u32 at `data.dat[8812904]` (2,535,240 on the supplied save), so the
  app's transfer-budget tile and `/api/deals`, `/api/finance` show a real
  number. `/api/pes17/info` also reports both budget words and their offsets.
  These are **raw save units**; PES 2017's currency scale is unverified, so
  no ×100 conversion (used by FL26) is applied.
* `tools/fetch_after_pairs.py` staged all four after saves from `main`;
  `tools/verify_pairs.py`: **PASS** for formation/tactics/xi/budget —
  `offsets_match`, `bytes_reproduced`, `no_extra_changes` all true.
* End-to-end HTTP smoke on the real files: `/api/state?slot=ML00000011`,
  `/api/pes17/info`, `/pes17.html` all 200; the info endpoint reports all four
  `measured_pairs`. A dry `pair` write changed nothing; a real `formation`
  `pair` write changed 17 bytes and produced a backup. Unknown pairs and
  unmeasured `raw` offsets were refused with 400; `/api/apply` is still
  refused.
* `READ_ONLY_MSG` guards and `sha256sum` checks confirm FL26 endpoints never
  touch the save.

## NOT verified / still needed

* **Game-side confirmation that a written save loads and shows the change**
  (no Windows/game run in this sandbox). Apply a `pair` op, e.g. `formation`,
  and load the save in PES 2017. The game's 64-byte header hash is left
  unchanged (same approach as MLTE); if the game rejects the save, that hash is
  the most likely cause.
* Game-side confirmation that an injected offer appears in PES 2017's inbox.
* The `claim` path for the human club (no AI negotiation block).
* Contracts/renewals, arbitrary tactic/formation values outside the measured
  tables, loans, youth, training, points/goals, forced transfers — need
  **more before/after save pairs** (one in-game change per pair). Use
  `pes2017/tools/diff_saves.py BEFORE AFTER`.

See `REAL_SAVE_REPORT.md` for the exact offsets, the honest validation table,
and the sources.

## Sources

* [the4chancup/pesXdecrypter](https://github.com/the4chancup/pesXdecrypter) — public-domain container algorithm + per-version keys.
* [Rigged Wiki: PES 2017 Edit file](https://implyingrigged.info/wiki/Pro_Evolution_Soccer_2017/Edit_file) — player bitfields.
* [PES2017-Master-League-Transfer-Engine](https://github.com/irvantaufik28/PES2017-Master-League-Transfer-Engine) — club/squad/standings/offer offsets, team-id shift, in-game checklist.
* The user's real `Needed files/*`, `cheat engine variations.CT`, and the four
  `*/after/ML00000011` game-generated saves on `main`.

The Gaffer is free fan-made software; see `README.txt` in the program folder
for its FREE TO USE terms. This modified build is for personal use — do not
reupload it or present it as the original work.
