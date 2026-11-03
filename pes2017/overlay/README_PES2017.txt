THE GAFFER pc414 - PES 2017 COMPATIBILITY PACK (READ-ONLY)
==========================================================

This folder is The Gaffer pc414 with PES 2017 support added. It is a private,
modified build for personal use; please respect the original FREE TO USE
terms in README.txt (do not reupload or publish this as your own work).


WHAT WORKS ON PES 2017
----------------------
* The app finds your PES 2017 save folder:
    Documents\KONAMI\Pro Evolution Soccer 2017\save
  (also numeric Steam subfolders). Setup > Save folder lists it as "PES 2017".
* PES 2017 saves are decrypted and re-encrypted with their own master key.
  The container format is the same as PES 2021, but the 64-byte key is not;
  the app now tries the PES 2021, FL27 and PES 2017 keys and remembers the
  one that opened each save.
* Your career is read from the PES 2017 Master League save:
    club, league, in-game date, next competition,
    all clubs (651 records x 1312 B at offset 80),
    your 32-player squad (offset +248 in the club record),
    league standings membership/order (structures at 8617528).
* Player names, ages, positions and attributes come from EDIT00000000.
  On the first load the app builds data/pes17/players.json, ratings.json,
  positions.json, playpos.json and teamids.json from your own edit file, so
  the squad shows YOUR PES 2017 players (with any patch you installed).
* The app-side career still runs: inbox, negotiations, board, press,
  scouting, awards, calendar, newspaper, journal, finances in the app, etc.
* Everything that would write into the save is refused with a clear message.
  There are several independent guards (Save adapter, write endpoints and
  the encryption step), so a PES 2017 save cannot be damaged by this build.


WHAT DOES NOT WORK YET (AND WHY)
--------------------------------
PES 2017 and PES 2021/FL26 store Master League data in completely different
tables. Examples measured on real PES 2017 saves:

    club record start     80       (PES 2021: 84)
    club record size      1312 B   (PES 2021: 1680 B)
    squad list            +248, 32 slots, (roster ptr, player id)
                                   (PES 2021: +332, 40 slots, (id, tag))
    ML save size          ~9.9 MB  (PES 2021: 19.9 / 45 / 60 MB)
    EDIT player record    188 B from offset 120
                                   (PES 2021: different table entirely)

The app's write engine (mlwrite.py, ~6,000 lines) writes at hard-coded PES
2021 offsets for transfers, loans, contracts, wages, budgets, formations,
tactics, shirt numbers, youth players, AI transfers, etc. Those offsets are
meaningless on a PES 2017 save. Writing them would corrupt the career, so
writing is disabled until each PES 2017 table has been measured on real save
pairs and verified in-game.

Consequences: do transfers, renewals, loans, tactics, formations, training
and shirt numbers inside PES 2017 itself. The app will still show your squad
and career; it just will not push changes back into the save. The FL26 Sider
modules (PlayerDump / GrowthBridge / regen fix) are PES 2021-only and are not
used for PES 2017.

League table note: the standing structures give the member clubs and their
order; points/goals/played fields are not mapped yet, so those columns show 0.


HOW TO USE
----------
1. Unzip this build anywhere (not inside the zip) on Windows.
2. Double-click "The Gaffer.vbs" (or "The Gaffer.bat").
3. In Setup > Save folder pick
      ...\Documents\KONAMI\Pro Evolution Soccer 2017\save
   and click Save paths. The game process is detected as PES2017.exe.
4. Pick your career slot (ML00000000, ...). A blue banner confirms PES 2017
   read-only mode. Keep EDIT00000000 in the save folder (it always is) so the
   player database can be imported. Back up your save folder anyway.

Optional config.json keys:
    "pes17_date_order": "dmy"   default (day/month/year). Set "mdy" if
                                your PES 2017 writes month/day/year dates.
    "edit_dat": "C:\\...\\EDIT00000000"   override where the EDIT file is.
    "pes17_allow_writes": false  DO NOT SET TO TRUE with this build. It only
                                exists for a future version with mapped
                                write tables.


HELP MAP THE WRITE TABLES
-------------------------
From the app folder (Windows, portable Python included):

    python\python.exe lib\pes17_layout.py info "C:\dec\ML00000000"
    python\python.exe lib\pes17_layout.py diff "C:\dec\before" "C:\dec\after" --json diff.json
    python\python.exe lib\pes17_layout.py edit "C:\path\EDIT00000000"

Workflow: decrypt a save, change ONE thing in PES 2017 (e.g. formation), save
again, decrypt that too, then run diff. The changed byte ranges identify the
table and row. Two or three such pairs per feature are enough to add a PES
2017 write profile for that feature. Send the diffs (and the two saves) to
whoever is doing the port.

To decrypt a save by hand:

    python\python.exe lib\pescrypt.py dec ML00000000 C:\dec
    python\python.exe lib\pescrypt.py enc C:\dec ML_new

(pescrypt.py now auto-detects the key on decryption; pass the PES 2017 key
file only if you need to force it.)


TECHNICAL SOURCES
-----------------
* the4chancup/pesXdecrypter (public domain): container algorithm and the
  PES 2017 master key (src/masterkey.c).
* Rigged Wiki "Pro Evolution Soccer 2017/Edit file": 116 B player entry,
  bit-packed attributes, 72 B appearance entry, 188 B pair.
* irvantaufik28/PES2017-Master-League-Transfer-Engine: ML save club table
  (80 / 1312 / +248), standings structures (8617528), EDIT offsets.
