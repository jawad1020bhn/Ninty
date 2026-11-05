# The Gaffer — PES 2017 compatibility pack (r9: first-run save-folder fix)

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

## Classic UI by default

The shipped `VERSION.txt` is `pc414-pes17-clean-r9 (2026-11-04)`. Opening `/`
loads the original **Classic UI** (`static/index.html`) directly, with the
dedicated PES 2017 read/write & asset tools reachable at `/pes17.html` via the
sidebar **PES 2017 tools** button. The separate dashboard and the previous
`game-skin` overlay have been removed; the PES 2017 banner and F7 connection
message are suppressed on the main screen.

The classic interface now has a matchday command-deck presentation shared
with the tools page. Its locally bundled, layered SVG emblems replace the
original emoji, including directional morale indicators. The icon renderer
also handles older saved messages and preserves translation lookups, text-only
controls and existing navigation. No online icon library or font is required.
The r9 first-run save-folder flow, measured-only writes, dry-run/backups,
layout guard, offline defaults, club crests and player mini-faces remain active.

## Files

```
pes2017/
  overlay/lib/pes17.py               keys, ML/EDIT readers, measured write tables, read-only Save adapter
  overlay/lib/pes17_layout.py        diagnostic CLI: info / diff / edit (maps before/after save pairs)
  overlay/lib/pes17_write.py         real-save container I/O + whitelisted, round-trip-verified writes
  overlay/lib/pes17_pairs.py         four tables measured from real before/after save pairs
  overlay/lib/pes17_crests.py       offline club-crest reader for the local patch folder
  overlay/lib/pes17_faces.py        offline player mini-face scanner & decoder for CPK / loose files
  overlay/lib/pes17_assets.py       offline CPK asset inventory + harvester
  overlay/lib/pes17_setup.py        r9 first-run save-folder detection + friendly status
  FIRST_RUN.md                      Windows first-run guide (shipped in the build)
  prune.py                          curated r8 cleanup of FL26/FL27/Sider leftovers
  CLEANUP_REPORT.md                 what r8 removed, what it kept and why
  tools/harvest_cpk.py              standalone offline CLI for the harvester
  CPK_ASSET_INVENTORY.md            what can be extracted from PES 2021 CPK files
  tools/diff_saves.py                diff two encrypted saves directly (future pairs)
  tools/verify_pairs.py              prove the four measured patches against the after files
  tools/analyze_save_noise.py        classify the 211 bytes the game rewrites on every save
  tools/fetch_after_pairs.py         stage the 4 after saves from main into build/pairs (gitignored)
  tools/ct_player_table.py           cross-check the Cheat Engine table against the ML player records
  tools/prepare_pairs.bat            Windows CMD script that prepares pair folders
  overlay/static/pes17.html          PES 2017 tools page (read + write UI)
  overlay/static/hud-icons.svg       local layered matchday icon sprite
  overlay/static/hud-icons.js        safe DOM renderer for icon tokens
  overlay/static/hud-ui.css          classic and tools matchday presentation
  pro_ui.py                          asserted build-time icon/i18n transformation
  overlay/README_PES2017.txt         user docs, shipped in the zip
  overlay/config_pes2017.example.json
  patch.py                           asserted compatibility and offline patches
  build.py                           extract original zip -> patch -> prune -> dist/TheGaffer_pes2017_pc414.zip
                                      (GAFFER_ORIGINAL_ZIP=... since the original zip
                                       was removed from the repo by the r8 cleanup)
  tests/test_prune.py                13 r8 cleanup / shipped-zip / offline-guard tests
  tests/test_pes17_setup.py          15 r9 detection / status / wiring tests
  tests/sample.py                    synthetic but structurally faithful PES 2017 saves
  tests/test_pes17.py                15 unit tests (crypto, detection, parsing, EDIT DB, write guard)
  tests/test_pes17_write.py          10 tests: 176 B header, container round-trip, real-file reads/writes
  tests/test_pes17_pairs.py          15 tests: measured pairs, custom ops, engine integration, real after files
  tests/test_pro_ui.py               icon, translation and shipped-HUD regressions
  REAL_SAVE_REPORT.md                measurements + validation status
  dist/TheGaffer_pes2017_pc414.zip   the ready-to-unzip Windows build
```

Rebuild / test:

```bash
python3 pes2017/build.py --source /path/to/TheGaffer_pc414_20261103.zip
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
* `static/index.html` — Classic remains the default; a sidebar button opens the
  PES 2017 tools, and the obsolete PES 2017/F7 banners are suppressed.
* `static/pes17.html` — tools UI: slot picker, real-save info, squad/table/
  offers, queued ops, dry-run, backups, RAW budget badge + display-only
  scale, layout verification checkbox, Arabic toggle.

## Safety model

* All FL26-style write endpoints still raise `pes17.READ_ONLY_MSG` — PES 2021
  offsets cannot be written into a PES 2017 save.
* PES 2017 writes are limited to measured tables: negotiation slots, shirt
  numbers, (experimental) squad slots, the four tables from the real pairs
  (formation/tactics/XI/budget), and a u32 `raw` escape hatch that is still
  range-checked. `pair` checks the before-state before writing; r5 adds a
  layout guard that runs BEFORE every op, for all ops.
* Every write: decrypt → mutate bytearray → assert changed bytes are inside
  measured ranges → re-encrypt → decrypt again → compare all six parts →
  `.tmp` + `os.replace` → reload from disk → compare → timestamped backup.
* Dry-run proves the ops without touching the save. Bad ops write nothing.

## Verified

* The automated suite includes tests that decrypt, read, modify and
  re-encrypt the user's real `ML00000011` / `EDIT00000000` (on copies only),
  tests proving all four measured pair patches against the game-generated
  after files, r2 regression tests for the budget read side
  (`Pes17Save.budget()` / `/api/pes17/info`), matchday HUD/icon and i18n
  regressions, r5
  tests for the layout guard, real shirt numbers / XI and RAW budget labels,
  r6 tests for offline patch-folder crests (loose files, CPK/WESYS, DDS
  decoding, stable-id mapping, read-only behaviour), and r7 tests for the CPK
  asset inventory/harvester (all 8 classes, DDS/WESYS conversion, source
  read-only, CLI, no network) plus the PES 2017-only offline wiring, and r8
  tests for the curated cleanup rules, the shipped zip contents/manifest and
  the offline guard that replaces the removed FL26 transfer cache, and r9
  tests for PES 2017 save-folder detection, friendly first-run status, the
  `/api/pes17/setup` endpoints and the tools-page setup card.
* **Matchday presentation.** The Classic application and tools page use one
  local HUD and a layered football icon sprite. Build-time tokenization keeps
  emoji-bearing comparison strings and translation keys intact; the DOM
  renderer displays SVGs instead of emoji and handles legacy saved messages.
  Unsupported incoming emoji fall back to a neutral information emblem. Normal
  text arrows remain text, and implicit option values are preserved.
* **r7: harvest before cleanup + PES 2017-only mode.** There is no real
  `.cpk` archive in this workspace, so `pes17/CPK_ASSET_INVENTORY.md` lists
  everything the shipped `cpkread`/`dds`/`ftex`/`bc7` readers can pull from a
  PES 2021 / FL2x CPK (crests, competition emblems, kit textures, player and
  coach portraits, pesdb tables, generic art) and marks each class
  `YES` / `MAP` / `NO` for PES 2017. `lib/pes17_assets.py` +
  `tools/harvest_cpk.py` produce a read-only manifest and can copy selected
  assets into the app folder, converting DDS/FTEX/WESYS to PNG; the app also
  exposes `GET /api/pes17/assets` and owner-only
  `POST /api/pes17/assets/extract`. Cleanup strips the 7 Google Fonts links
  and 4 flagcdn references at build time, `flag_img()` no longer downloads,
  and `_wiki_web()` defaults to false. `/` serves the Classic application.
  **Not a full rewrite** — the FL26 UI and its endpoints still exist.
  42/42 HTTP checks with the real save + synthetic patch folder.
* **r9: first run actually works.** pc414 shipped a hard-coded FL26 save path
  (`%USERPROFILE%\OneDrive\Dokumenti\KONAMI\eFootball PES 2021 SEASON
  UPDATE\2026\save`), so on a PES 2017 PC with no `config.json` the dashboard
  printed raw `[Errno 2]` / `[WinError 3]` exceptions and no save data. r9 sets
  that default to empty, auto-detects a real
  `KONAMI\Pro Evolution Soccer 2017\save` folder (profile, Documents,
  OneDrive, localised names like `Dokumenti`), and adds `GET
  /api/pes17/setup` plus owner-only `POST /api/pes17/setup/savefolder`. The
  tools page shows a **Save folder** card with clickable detected paths,
  friendly messages instead of OS errors, a dynamic build label, and clearer
  "optional" wording for the crest/CPK cards. `list_slots()` and
  `/api/pes17/info` no longer raise on a missing folder. Shipped
  [`FIRST_RUN.md`](FIRST_RUN.md) explains the one-time step. **66/66 live HTTP
  checks** (fresh install + configured install) and a **133-GET differential
  sweep** against r8 (132 identical, the 1 difference being the new setup
  endpoint) pass. `verify_pairs.py` still PASSes.
* **r8: conservative cleanup, not a rewrite.** `prune.py` removes 111
  FL26/FL27/Sider-only files (10.01 MB) from the shipped build:
  `addons/regenfix/`, `addons/michele/`, `lua/`, `FL_key.bin`,
  `FL_key_README.txt`, and the five FL26 databases that PES 2017 regenerates
  into `data/pes17/` from the real `EDIT00000000`. Every deletion is listed in
  `CLEANUP_MANIFEST.txt`; `prune.apply()` asserts that all required paths
  survive. Kept on purpose: the classic FL26 UI at `/index.html` and the
  art/scenes/stadiums/i18n/small metadata it serves, all `lib/*.py` and the
  portable `python/*`. Because the FL26 `data/realmoves.json` cache is gone,
  `patch.py` also guards `realmoves_fetch_bg()` with `_wiki_web()` so the
  build stays offline by default. **Verification:** 76/76 HTTP checks on a
  live server built from the pruned zip, plus a differential sweep of all 132
  GET endpoints against the unpruned r7 build — 132 identical status pairs,
  zero new 5xx, no timeouts. The PES 2017 player database is regenerated from
  `EDIT00000000` (20,018 players) despite the FL26 databases being absent.
  See [`CLEANUP_REPORT.md`](CLEANUP_REPORT.md).
* **r6: patch-folder club crests.** `overlay/lib/pes17_crests.py` walks a
  configurable local folder (`pes17_patch_dir`; blank = auto-detect folders
  next to `pes_exe`) for crest-like PNG/JPG/DDS/FTEX files and for
  `common/render/symbol/flag/e_<id>_<variant>.(png|dds)` entries inside `*.cpk`
  archives, using the shipped `cpkread` / `dds` / `ftex` / `bc7` readers.
  Club names are resolved with `data/pes17/teamids.json`, preferring the stable
  team ID over the raw bit-packed ID (the FL26 `_save_team_ids()` stride is
  wrong for PES 2017). `crest_img()` tries this source first on a PES 2017
  save; `crest_prefetch()` skips Wikipedia when patch crests exist. New
  `/api/pes17/crests` (diagnostic) and `/api/pes17/crests/dir` (owner-only
  config setter) endpoints and a card on `/pes17.html` show the result.
  Read-only, offline, no external dependency; nothing is written to the game
  folder. Verified with 32/32 HTTP checks on the real save plus a synthetic
  patch folder. Real patch CPK archives were not available in this sandbox, so
  CPK reading is covered by a mocked reader and the shipped `cpkread.Cpk` API.
* **r5: layout guard.** `apply_ops()` calls `pes17_pairs.verify_layout()`
  before any op: exact 13,304,607 B data size, four structural table markers
  (formation record prefixes, XI permutation, tactics invariant bytes,
  plausible budget u32s) and 50 stable anchors (≥60% match). A different-sized
  or structurally different save is refused before a byte changes; the
  `layout` report is returned by `/api/pes17/write` and shown on the tools
  page with a checked "verify save layout" box. `layout_check=False` opts out
  with a loud warning; `'report'` runs checks without refusing.
* **r5: honest budget + more reads.** `/api/pes17/info` reports
  `currency_verified=false` and `unit='raw u32 save units'`; the tools page
  shows a RAW / NOT CONFIRMED EUR badge and a display-only x1/x10/x100/x1000
  scale selector (never written). `Pes17Save.squad_numbers()` now returns the
  real shirt numbers and `lineup()` the measured 26-slot XI order + 0xFF pad.
  The tools page has an Arabic toggle (RTL), and the HUD has ICE/AMBER/PITCH
  accents with the boot intro off by default. `tools/analyze_save_noise.py`
  classified the 211 common bytes; `tools/diff_saves.py` was executed on all
  four pairs.
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
