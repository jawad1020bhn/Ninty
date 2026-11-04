THE GAFFER pc414 - PES 2017 COMPATIBILITY PACK (MEASURED-PAIRS BUILD)
======================================================================

This folder is The Gaffer pc414 with PES 2017 support added.  It is a private,
modified build for personal use; please respect the original FREE TO USE
terms in README.txt (do not reupload or publish this as your own work).

BUILD HISTORY
-------------
1. First build: synthetic saves only.  It could NOT open a real PES 2017 save.
2. Real-save build: you supplied ML00000011, EDIT00000000 and info.txt in
   "Needed files".  Real PES 2017 saves use a 176-byte file header (not the
   208-byte PES 2021 header).  That was fixed; decryption and byte-identical
   re-encryption of BOTH real files is proven in tests.  Reads + a small set
   of writes (offers, shirts) were measured on your files.
3. This build: you supplied four game-generated "after" saves, one per
   in-game change (formation, tactics, XI, budget), with the same common
   "before" file ML00000011.  Those pairs mapped four more tables exactly.

WHAT THE APP READS FROM YOUR REAL SAVE
--------------------------------------
  club                Birmingham City FC
  in-game date        10/01/2029  (D/M/YYYY)
  next competition    Emirates FA Cup
  clubs               624
  your squad          26 players, with real EDIT names and shirt numbers
  league table        20 rows, Sky Bet Championship (from your EDIT file)
  player database     20,018 players from your EDIT00000000
  negotiations        0 active (after filtering garbage blocks)

Note: description.dat says "Premier League" while the standings/EDIT tables
place Birmingham in the Sky Bet Championship.  Both values are shown.
Points / played / goals are still shown as 0: not mapped yet.

WHAT CAN BE WRITTEN (MEASURED, ROUND-TRIP VERIFIED)
---------------------------------------------------
Open  http://localhost:8766/pes17.html  (or the "PES 2017 tools" link in the
main app banner).  The page reads your real save and lets you queue ops:

  offer_add     inject an active transfer negotiation into a club's block
  offer_clear   restore an empty negotiation slot
  shirt         set one of the 32 shirt numbers of a club
  squad         experimental, requires experimental=true (NOT in-game tested)
  pair          reproduce EXACTLY one of your four measured changes
  formation     write a 33-byte formation record (hex)
  tactics       write one measured byte in the tactics block
  xi            write the 26-slot XI / squad order
  budget        write the two measured budget u32 words
  raw           u32 escape hatch for offsets you measured yourself

Measured offsets, all confirmed on ML00000011 (decrypted data.dat,
13,304,607 B):

  club table            80, 1312 B records, name at +4
  shirt numbers         club + 512, 32 x 1 byte
  squad slots           club + 248, 32 x 8 B (roster pointer, player id)
  negotiation table     9,591,148 .. 9,829,596, 280 B blocks
  negotiation slots     block + 4, 16 x 16 B
  empty slot            (6488064, 65535, 0, 1664)
  active slot           (0, source roster ptr, player id, 4210816)

Four tables measured from YOUR before/after save pairs (lib/pes17_pairs.py):

  formation records     1,256,248, 33 B records, 3 records
                        formation pair changed 17 bytes in record 0
  tactics block         1,256,348, 15 B; 13 bytes changed by the tactics pair
  XI / squad order      1,256,728, 26 B permutation of squad slots 0..25
                        + 42 B order block, 24 B float sliders at 2,230,192
  budget u32            8,812,904 (2,535,240 -> 3,088,641)
  wage budget u32       8,812,936 (9,689,272 -> 10,247,281)
                        budget pair also touched 15 companion bytes
                        (9,836,708 .. 9,845,147)

Each "pair" op is verified by tools/verify_pairs.py: applied to the common
before file it reproduces every byte the game itself changed for that action,
and changes no other byte.  Per-save bytes (the 32-byte token at data.dat
[48:80], the 64-byte header hash, the encryption-header salt and two UI-state
words) are NOT written: the game rewrites those on every save.  The 64-byte
header hash algorithm is unknown; we keep the original hash, exactly as the
public MLTE tool does.  IN-GAME LOAD VALIDATION IS STILL REQUIRED.

SAFETY MODEL
------------
* Every write goes through lib/pes17_write.py: decrypt -> edit a bytearray ->
  re-encrypt with the PES 2017 key -> decrypt again -> compare ALL SIX parts
  byte-for-byte -> write to a .tmp file -> os.replace -> load the file from
  disk again and compare.  A timestamped backup is kept in work\backup.
* Every changed byte is checked to be inside a measured table.  A bad op
  (unknown club, unknown pair, offset outside the tables) raises and NOTHING
  is written.  The "pair" op additionally checks that the current save still
  matches the measured before-state before writing.
* All FL26-style write endpoints (transfers, loans, contracts, tactics,
  formations, budgets, training, AI moves, revalues) are STILL REFUSED in the
  main app.  Use the PES 2017 tools page for the measured writes.  Do the rest
  in the game.
* The dry-run checkbox proves the operation without touching the save.

WHAT IS STILL NOT POSSIBLE
--------------------------
Contracts/renewals (the player-record table was located via the Cheat Engine
table but not confirmed by a pair), loans, youth players, training/growth,
points/goals in the league table, forced transfers, AI transfers, the human
club's own inbox negotiations, and any arbitrary formation/tactic value that
is not inside the measured table layout.  More before/after pairs (one change
per pair) are needed for those.  See REAL_SAVE_REPORT.md.

Human-controlled clubs normally have NO AI negotiation block in the save.
The "claim an unused block for my club" checkbox is a structural inference,
NOT in-game validated, and is flagged experimental.  Prefer an AI club
(e.g. Arsenal, tid 101) for a fully published write.

HOW TO USE ON WINDOWS
---------------------
1. Unzip this build anywhere (not inside the zip) on Windows.
2. Double-click "The Gaffer.vbs" (or "The Gaffer.bat").
3. In Setup > Save folder choose
      ...\Documents\KONAMI\Pro Evolution Soccer 2017\save
   (or wherever your ML00000011 / EDIT00000000 live), then Save paths.
   Keep EDIT00000000 in that folder (or set "edit_dat" in config.json).
   A blue banner confirms PES 2017 mode; it links to /pes17.html.
4. Back up your save folder anyway.  Close PES 2017 before writing.
5. TEST IN GAME: apply a "pair" op (e.g. formation), load the written save in
   PES 2017 and confirm the change appears.  That is the only remaining
   validation step.  If the game rejects the save, restore from work\backup
   and tell us: the header hash is the most likely cause.

config.json keys (see config_pes2017.example.json):
    "save_dir": "...\\save"
    "edit_dat": "...\\save\\EDIT00000000"   (optional override)
    "pes17_date_order": "dmy"              (default; "mdy" for US saves)
    "pes_process": "PES2017"
    "pes17_allow_writes": false             keep false: it only gates the
                                            old FL26 write engine.

COMMAND LINE (portable Python included)
--------------------------------------
    python\python.exe lib\pes17_write.py roundtrip ML00000011
    python\python.exe lib\pes17_write.py info ML00000011 --edit EDIT00000000
    python\python.exe lib\pes17_write.py offers ML00000011
    python\python.exe lib\pes17_layout.py info C:\dec\ML00000011
    python\python.exe lib\pes17_write.py apply ML00000011 --ops ops.json --work work

ops.json example:
[
  {"op":"offer_add","buyer":101,"slot":0,"pid":55246},
  {"op":"shirt","club":201,"slot":0,"number":9},
  {"op":"pair","name":"formation"},
  {"op":"tactics","values":{"1256356":3}},
  {"op":"xi","order":[9,15,4,12,13,22,19,17,5,3,6,25,16,18,10,21,8,24,11,2,7,23,20,14,0,1]},
  {"op":"budget","value":3088641,"wage":10247281}
]

DIFF TOOLS (on the development machine)
---------------------------------------
    git fetch origin main
    python3 pes2017/tools/fetch_after_pairs.py   # stage the 4 after saves from main
    python3 pes2017/tools/diff_saves.py  BEFORE AFTER --json diff.json
    python3 pes2017/tools/verify_pairs.py --before "Needed files/ML00000011" \
        --after-dir build/pairs

TESTS
-----
    python3 -m unittest discover -s pes2017/tests -p 'test_*.py' -v
40 tests pass, including tests that decrypt, read, modify and re-encrypt
YOUR real ML00000011 / EDIT00000000 files (on copies only) and tests that
prove all four measured pair patches against the game-generated after files.

TECHNICAL SOURCES
-----------------
* the4chancup/pesXdecrypter (public domain): container algorithm, PES 2017
  master key (src/masterkey.c), 176 B FileHeader in crypt.h.
* Rigged Wiki "Pro Evolution Soccer 2017/Edit file": player entry bitfields.
* irvantaufik28/PES2017-Master-League-Transfer-Engine: club/squad/standings
  offsets, negotiation layout, team-id bit shift, in-game validation checklist.
* "Needed files/cheat engine variations.CT": live-RAM player field semantics,
  used to locate the 232 B ML player-record / contract table.
* Your own files in "Needed files" (t99p17v20) and the four after saves
  (formation/after, tactics/after, xi/after, budget/after) for every offset
  and value above.
