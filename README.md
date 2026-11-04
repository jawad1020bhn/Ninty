# Ninty

Contents:

* `TheGaffer_pc414_20261103.zip` — original Windows program (The Gaffer pc414,
  a Football Manager style companion for Football Life 26 / PES 2021 / FL27
  Master League).
* `Needed files/` — the user's real PES 2017 saves (`ML00000011`,
  `EDIT00000000`), `info.txt` (patch `t99p17v20`, game folder path), the
  Cheat Engine table and the prepared before/after pair folders.
* `formation/`, `tactics/`, `xi/`, `budget/` (on `main`) — four game-generated
  `after/ML00000011` files, one per in-game change.
* `pes2017/dist/TheGaffer_pes2017_pc414.zip` — **rebuilt program with PES 2017
  reads + measured, round-trip-verified writes**. `VERSION.txt` says
  `pc414-pes17-only-r7 (2026-11-04)`. Unzip on Windows and run
  `The Gaffer.vbs`, then open `/pes17.html`. r2 fixed the "Budget €0" display
  (the two measured budget u32 words are read from the save, in raw units;
  PES 2017 currency scale not confirmed in game). r3 adds a **game-style HUD
  skin** and an SVG icon pack; r4 makes that icon replacement exhaustive
  (all 926 symbolic glyphs in pc414, plus a catch-all for unknown emoji).
  r5 adds a **layout guard before every write**, labels the budget figure as
  RAW (not confirmed EUR), reads real shirt numbers / the starting XI, and
  adds an Arabic toggle on the tools page plus a HUD accent picker. The
  bottom-right chip toggles back to the original website look. r6 reads
  **club crests from the local PES 2017 patch folder** offline: loose
  PNG/JPG/DDS/FTEX logos and `flag/e_<teamid>_r.dds` entries inside CPK
  archives are decoded with the shipped readers and served by the existing
  `/api/crest` endpoint. A diagnostic card on `/pes17.html` shows how many
  logos were found; no Wikipedia/CDN crest fetch is needed. r7 adds an
  **offline CPK asset harvester** (`pes2017/tools/harvest_cpk.py`,
  `/api/pes17/assets`, card 3d) that inventories club crests, competition
  emblems, kit textures, player/coach portraits, pesdb tables and generic
  art, and a **dedicated PES 2017 dashboard** at `/`. Google Fonts, flagcdn,
  Wikipedia and the FL26 landing page are removed/disabled by default
  (`pes17_only`); see [`pes2017/CPK_ASSET_INVENTORY.md`](pes2017/CPK_ASSET_INVENTORY.md)
  for what can be salvaged from the PES 2021 CPK files before cleaning them.
* `pes2017/` — source of the compatibility pack, patcher, build script, tests
  and documentation. Start with [`pes2017/README.md`](pes2017/README.md) and
  [`pes2017/REAL_SAVE_REPORT.md`](pes2017/REAL_SAVE_REPORT.md).

Quick summary: PES 2017 uses the same encrypted save *container* but a
different master key **and a 176-byte file header** (the first, synthetic-only
build wrongly assumed 208 B and could not open the real saves). It also has a
completely different `data.dat` layout. This build fixes both, reads the real
club / squad / EDIT player database / standings / shirt numbers, and writes
only the tables measured on the supplied files: transfer negotiations, shirt
numbers, and — from four real before/after save pairs — formation records,
tactics bytes, XI/squad order and the two budget u32 words. All FL26-style
write endpoints remain blocked. A Windows in-game load test is the last
outstanding validation step (the game's 64-byte header hash is left unchanged,
as the public MLTE tool does).

Build / test / verify:

```bash
python3 pes2017/build.py
python3 -m unittest discover -s pes2017/tests -p 'test_*.py' -v
git fetch origin main
python3 pes2017/tools/fetch_after_pairs.py
python3 pes2017/tools/verify_pairs.py --before "Needed files/ML00000011" --after-dir build/pairs
```

r6 adds 23 tests (19 for the crest reader + 4 static wiring checks); r7 adds
15 more (10 harvester + 5 wiring). 114 unit tests total, plus 42/42 HTTP
checks against the real save with a synthetic patch folder. Note: this repo
contains **no real `.cpk` archives** — only the shipped readers and FL26
databases — so the harvester must be pointed at your patch folder on Windows
to get a true inventory. Set `pes17_patch_dir` in `config.json` (or leave it blank to
auto-detect `download/`, `Data/`, `livecpk/`, `content/` next to `pes_exe`).
