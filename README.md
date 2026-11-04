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
  `pc414-pes17-measuredpairs-r2 (2026-11-04)`. Unzip on Windows and run
  `The Gaffer.vbs`, then open `/pes17.html`. r2 fixes the "Budget €0" display:
  the two measured budget u32 words are now read from the save (raw units,
  PES 2017 currency scale not confirmed in game).
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
