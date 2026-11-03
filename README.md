# Ninty

Contents:

* `TheGaffer_pc414_20261103.zip` — original Windows program (The Gaffer pc414,
  a Football Manager style companion for Football Life 26 / PES 2021 / FL27
  Master League).
* `Needed files/` — the user's real PES 2017 saves (`ML00000011`,
  `EDIT00000000`) and `info.txt` (patch `t99p17v20`, game folder path).
* `pes2017/dist/TheGaffer_pes2017_pc414.zip` — **rebuilt program with PES 2017
  read support + measured, round-trip-verified writes**. Unzip on Windows and
  run `The Gaffer.vbs`, then open `/pes17.html`.
* `pes2017/` — source of the compatibility pack, patcher, build script, tests
  and documentation. Start with [`pes2017/README.md`](pes2017/README.md) and
  [`pes2017/REAL_SAVE_REPORT.md`](pes2017/REAL_SAVE_REPORT.md).

Quick summary: PES 2017 uses the same encrypted save *container* but a
different master key **and a 176-byte file header** (the first, synthetic-only
build wrongly assumed 208 B and could not open the real saves). It also has a
completely different `data.dat` layout. This build fixes both, reads the real
club / squad / EDIT player database / standings / shirt numbers, and writes
only the tables measured on the supplied files: transfer negotiations and
shirt numbers. All FL26-style writes (transfers, tactics, contracts...) remain
blocked until before/after save pairs are supplied.

Build / test:

```bash
python3 pes2017/build.py
python3 -m unittest discover -s pes2017/tests -p 'test_*.py' -v
```
