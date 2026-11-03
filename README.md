# Ninty

Contents:

* `TheGaffer_pc414_20261103.zip` — original Windows program (The Gaffer pc414,
  a Football Manager style companion for Football Life 26 / PES 2021 / FL27
  Master League).
* `pes2017/dist/TheGaffer_pes2017_pc414.zip` — **rebuilt program with PES 2017
  support (read-only)**. Unzip on Windows and run `The Gaffer.vbs`.
* `pes2017/` — source of the compatibility pack, patcher, build script, tests
  and documentation. Start with [`pes2017/README.md`](pes2017/README.md).

Quick summary: PES 2017 uses the same encrypted save *container* but a
different 64-byte master key, and its decrypted Master League `data.dat` has a
completely different table layout. This build adds the PES 2017 key, reads
your club/squad/players/standings from the PES 2017 save and `EDIT00000000`,
and blocks all writes (which would otherwise corrupt the save because they use
PES 2021 offsets). See `pes2017/overlay/README_PES2017.txt` for setup and the
roadmap to unlock writing.

Build / test:

```bash
python3 pes2017/build.py
python3 -m unittest discover -s pes2017/tests -p 'test_*.py' -v
```
