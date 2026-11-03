THE GAFFER pc414 - PES 2017 COMPATIBILITY PACK (REAL-SAVE BUILD)
=================================================================

This folder is The Gaffer pc414 with PES 2017 support added.  It is a private,
modified build for personal use; please respect the original FREE TO USE
terms in README.txt (do not reupload or publish this as your own work).

WHAT CHANGED SINCE THE FIRST (SYNTHETIC-ONLY) BUILD
--------------------------------------------------
The first build was tested only on self-generated saves.  You then supplied
real files in "Needed files":  ML00000011 (13,342,176 B), EDIT00000000
(5,303,749 B) and info.txt (patch t99p17v20, game folder
D:\jawedfolder\Games\Pro Evolution Soccer 2017).  Those files exposed a
critical bug and allowed real measurements:

* CRYPTO FIX: real PES 2017 saves use a 176-byte file header, not the
  208-byte PES 2021 header.  The old build could not open your save at all.
  decrypt_bytes() now tries both header sizes; encrypt_parts() detects the
  header length.  Decrypt -> re-encrypt of BOTH of your real files is now
  byte-for-byte identical to the originals (proved in tests).
* READ FIXES: patched club ids are bit-packed (stable PES Team ID << 14 |
  ML record index); standings/EDIT league arrays use the stable ID.  Standings
  blocks are located dynamically from the EDIT league arrays because the
  patch moved them.  Competition names are read from your EDIT file.  EDIT
  player import now uses the header count instead of a vanilla 21,000 cap.
* REAL WRITE ENGINE: a small, explicitly whitelisted set of writes, each
  round-trip verified and backed up.  See below.

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
place Birmingham in the Sky Bet Championship.  Both values are shown (the
description is authoritative for the save slot label; the table is the live
league structure).  Points / played / goals are still shown as 0: those
columns are not mapped yet.

WHAT CAN BE WRITTEN (MEASURED, ROUND-TRIP VERIFIED)
---------------------------------------------------
Open  http://localhost:8766/pes17.html  (or the "PES 2017 tools" link in the
main app banner).  The page reads your real save and lets you queue ops:

  offer_add     inject an active transfer negotiation into a club's block
  offer_clear   restore an empty negotiation slot
  shirt         set one of the 32 shirt numbers of a club
  squad         experimental, requires experimental=true (NOT in-game tested)
  raw           u32 escape hatch for offsets you measured yourself

Measured offsets (all confirmed on ML00000011):

  club table            80, 1312 B records, name at +4
  shirt numbers         club + 512, 32 x 1 byte
  squad slots           club + 248, 32 x 8 B (roster pointer, player id)
  negotiation table     9,591,148 .. 9,829,596, 280 B blocks
  negotiation slots     block + 4, 16 x 16 B
  empty slot            (6488064, 65535, 0, 1664)
  active slot           (0, source roster ptr, player id, 4210816)
  buyer field           raw bit-packed club id (NOT team id >> 14)
  unused blocks         buyer id = 0xFFFFFFFF (353 of them)

The negotiation slot layout is the one published and in-game validated by the
PES2017-Master-League-Transfer-Engine project.  The switch from 208 to 176
byte headers, all read-side offsets, the shirt-number table, and the
empty/active slot values were verified directly on YOUR files in this repo.

SAFETY MODEL
------------
* Every write goes through lib/pes17_write.py: decrypt -> edit a bytearray ->
  re-encrypt with the PES 2017 key -> decrypt again -> compare ALL SIX parts
  byte-for-byte -> write to a .tmp file -> os.replace -> load the file from
  disk again and compare.  A timestamped backup of the original is kept in
  work\backup.
* Every changed byte is checked to be inside a measured table.  A bad op
  (unknown club, offset outside the tables) raises and NOTHING is written.
* All FL26-style write endpoints (transfers, loans, contracts, tactics,
  formations, budgets, training, AI moves) are STILL REFUSED.  They would
  write PES 2021 offsets into a PES 2017 save.  Do those in the game.
* The dry-run checkbox proves the operation without touching the save.

WHAT IS STILL NOT POSSIBLE
--------------------------
No "before/after" save pairs were supplied.  Without them these tables cannot
be mapped, so they remain blocked (or show 0 / app-side data):

  formations, lineup/XI, tactics, contracts + renewals, wages and budgets,
  forced transfers, loans, youth players, training/growth, points/goals in
  the league table, and the human club's own inbox negotiations.

Human-controlled clubs normally have NO AI negotiation block in the save.
The tools page has a "claim an unused block for my club" checkbox: it writes
your club's id into an unused 0xFFFFFFFF block.  That is a structural
inference, NOT in-game validated, and is flagged experimental in the result.
Prefer an AI club (e.g. Arsenal, tid 101) for a fully published write.

To map the remaining features, make ONE change in PES 2017, save again, and
keep the before/after ML00000011 pair (plus EDIT00000000).  Then:

    python\python.exe lib\pes17_layout.py diff before after --json diff.json
    python\python.exe lib\pes17_write.py info ML00000011 --edit EDIT00000000
    python\python.exe lib\pes17_layout.py info C:\dec\ML00000011

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

config.json keys (see config_pes2017.example.json):
    "save_dir": "...\\save"
    "edit_dat": "...\\save\\EDIT00000000"   (optional override)
    "pes17_date_order": "dmy"              (default; "mdy" for US saves)
    "pes_process": "PES2017"
    "pes17_allow_writes": false             keep false: it only gates the
                                            old FL26 write engine.  The
                                            /pes17.html tools are separate.

COMMAND LINE (portable Python included)
--------------------------------------
    python\python.exe lib\pes17_write.py roundtrip ML00000011
    python\python.exe lib\pes17_write.py info ML00000011 --edit EDIT00000000
    python\python.exe lib\pes17_write.py offers ML00000011
    python\python.exe lib\pes17_write.py apply ML00000011 --ops ops.json --work work

ops.json example:
[
  {"op":"offer_add","buyer":101,"slot":0,"pid":55246},
  {"op":"shirt","club":201,"slot":0,"number":9},
  {"op":"offer_clear","buyer":101,"slot":3}
]

TESTS
-----
    python3 -m unittest discover -s pes2017/tests -p 'test_*.py' -v
25 tests pass, including tests that decrypt, read, modify and re-encrypt
YOUR real ML00000011 / EDIT00000000 files (on copies only).

TECHNICAL SOURCES
-----------------
* the4chancup/pesXdecrypter (public domain): container algorithm, PES 2017
  master key (src/masterkey.c), 176 B FileHeader in crypt.h.
* Rigged Wiki "Pro Evolution Soccer 2017/Edit file": player entry bitfields.
* irvantaufik28/PES2017-Master-League-Transfer-Engine: club/squad/standings
  offsets, negotiation layout, team-id bit shift, in-game validation checklist
  (docs/TEAM_ID_MAPPING.md, TRANSFER_OFFER_*.md, ROUND_TRIP_VALIDATION.md).
* Your own files in "Needed files" (t99p17v20) for every measurement above.
