THE GAFFER pc414 - PES 2017 COMPATIBILITY PACK (PES 2017 CLEAN BUILD r8)
===================================================================

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
3. Measured-pairs build: you supplied four game-generated "after" saves, one
   per in-game change (formation, tactics, XI, budget), with the same common
   "before" file ML00000011.  Those pairs mapped four more tables exactly.
4. r2: the main app showed "Budget EUR 0" because the PES 2017 read adapter
   had a hardcoded 0 stub.  The two measured budget u32 words are now read
   from your save and shown in the app and on the tools page.  The wage word
   in the docs was also corrected to the exact measured value.
5. r3: GAME UI.  A dark "game HUD" skin replaces the website look on both
   the main app and /pes17.html, and colorful emoji are swapped at runtime
   for a hand-drawn SVG vector pack.  A short boot intro, a HUD strip and a
   GAME UI / CLASSIC UI toggle were added.
6. r4: EXHAUSTIVE ICONS.  All 926 symbolic glyph occurrences
   (170 distinct characters) in pc414 are now explicitly mapped to SVG
   icons: the X close buttons, plain arrows, squared A / NEW / joker badges
   and ZWJ family sequences were the last gaps.  A Unicode catch-all with
   the 'u' flag also converts any unknown / future emoji to a neutral
   vector badge.  NO app logic, save code or endpoint was changed.
7. r6: PATCH-FOLDER CLUB CRESTS.  The app can now read club logos straight
   from the local PES 2017 patch folder, offline, instead of downloading
   crests from Wikipedia.  Loose PNG/JPG/DDS/FTEX logos and
   common/render/symbol/flag/e_<id>_r.dds entries inside *.cpk archives are
   decoded with the readers already shipped with the program.  See the
   CLUB CRESTS FROM THE PATCH FOLDER section below.
8. r7: CPK HARVEST + PES 2017-ONLY MODE.  An offline inventory of everything
   the shipped CPK readers can reach (competition emblems, kit textures,
   player/coach portraits, pesdb tables, generic art), a harvester that can
   copy them before you delete the PES 2021 files, a dedicated PES 2017
   dashboard at /, and no external CDNs by default.  See the CPK ASSET
   INVENTORY / HARVEST and PES 2017-ONLY MODE sections below and the shipped
   CPK_ASSET_INVENTORY.md.
9. r8: SAFE CLEANUP (not a rewrite).  111 FL26/FL27/Sider-only files
   (10.01 MB) are removed from this shipped build only: addons/regenfix,
   addons/michele, lua, FL_key.bin + its readme, and the five FL26 player
   databases that PES 2017 regenerates into data/pes17/ from your real
   EDIT00000000.  CLEANUP_MANIFEST.txt lists every deletion and
   CLEANUP_REPORT.md explains what was kept and why.  The classic FL26 page
   at /index.html, its art/scenes/stadiums and all lib/*.py are KEPT because
   they are still referenced.  realmoves_fetch_bg() is now blocked offline so
   removing the FL26 transfer cache does not trigger a Wikipedia fetch.

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
Points / played / goals are still shown as 0: not mapped yet.  r5 scanned
8,610,000..8,720,000 for a 20-row stats array (w+d+l == played, plausible
points) and found none, so zeros are kept instead of guessed values.
Real shirt numbers and the starting XI order are now read (r5).

BUDGET DISPLAY (r2)
-------------------
Earlier builds showed "Budget EUR 0": the PES 2017 read adapter had a
hardcoded 0 stub, even though the budget words were measured for writing.
r2 reads them from YOUR save.  The app's "Transfer budget" tile now shows the
raw u32 word at data.dat offset 8,812,904:

  before (the file you gave me)      2,535,240
  after  (game-generated budget)     3,088,641
  second word at 8,812,936           9,692,344 -> 10,245,745

These are RAW save units, NOT confirmed EUR amounts.  FL26 stores its budget
in 100-EUR units and the original app multiplies by 100; PES 2017's currency
scale has NOT been checked in game, so no conversion is applied.  Compare the
number with what PES 2017 shows on screen.  If the game shows a multiple
(e.g. 10x or 100x), report the figure and the scale can be added.  The
PES 2017 tools page ("Load info") shows both words and their offsets.

BUDGET LABELLING (r5)
---------------------
The tools page now shows a RAW / NOT CONFIRMED EUR badge instead of a bare
currency amount, and /api/pes17/info reports currency_verified=false plus
unit="raw u32 save units".  A "Display scale (view only)" selector (x1, x10,
x100, x1000) lets you compare the raw word with the number PES 2017 shows on
screen; it is display-only and NEVER writes to the save.  The blue banner in
the main app says the same.  Report the in-game figure and the correct scale
can be applied -- until then the EUR sign in the original FL26 UI is only
presentation.

LAYOUT GUARD (r5)
-----------------
The four custom ops (formation, tactics, xi, budget) used to write arbitrary
values without checking the save layout.  apply_ops() now calls
pes17_pairs.verify_layout() first:

  * data.dat must be exactly 13,304,607 B (the measured save);
  * formation record markers, the 26-slot XI permutation, two invariant
    tactics bytes and plausible budget u32 words must all be present;
  * 50 stable anchor bytes sampled around the tables and across the file
    (identical in BEFORE and all four AFTERs, outside every writable range)
    must match at least 60%.

A save from another season/patch is REFUSED before a single byte changes;
the response includes the layout report.  The tools page has a checked
"verify save layout" box -- unchecking it disables the guard with a loud
warning, for advanced users only.  `layout_check='report'` runs the checks
without refusing.  Synthetic test buffers (<10 MB) are reported, never
written to a user's save.  This is a save-file comparison, NOT in-game
validation.

GAME UI (r3)
------------
The app now opens with a console-style HUD instead of a plain website:

  * dark navy grid backdrop, angled "mission panel" cards with corner
    ticks and a thin cyan accent edge, uppercase condensed headings,
    glowing numeric stats, beveled buttons and HUD-style tables;
  * a top status strip: THE GAFFER // PES 2017 - MASTER LEAGUE, with a
    green "SAVE LINK LOCAL" LED;
  * r5: a HUD accent picker (ICE / AMBER / PITCH, remembered locally)
    and an INTRO: ON/OFF chip.  The boot intro is now OFF by default;
    turning it on plays it once per tab, and "SKIP & DON'T SHOW AGAIN"
    disables it again;
  * a 69-icon vector pack (static/game-skin.js) replaces EVERY one of the
    926 symbolic glyph occurrences (170 distinct characters) in pc414 with
    crisp SVG icons: colorful emoji, dingbats, stars, arrows, X close
    buttons, squared A/NEW badges and ZWJ family sequences.  A Unicode
    catch-all also converts any unknown / future emoji to a neutral badge.
    Icons apply to content the app renders later (MutationObserver).
    Arrows and X's are drawn in a muted colour so they read as typography.

  Files:  static/game-skin.css   (theme, scoped to body.game-skin)
          static/game-skin.js    (SVG sprite, emoji swap, HUD, toggle)

  TOGGLE: the "GAME UI" chip at the bottom-right switches to the original
  "CLASSIC UI" look and restores the original emoji.  The choice is saved
  in the browser.  Nothing in the skin touches the save file, the API or
  any app logic.  It is fully offline: no external fonts, images or CDNs
  were added (the original Google Fonts links are unchanged).

  If the skin ever looks wrong on your display, click the chip once; the
  classic layout is byte-for-byte the original pc414 UI.

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
  wage budget u32       8,812,936 (9,692,344 -> 10,245,745)
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

CLUB CRESTS FROM THE PATCH FOLDER (r6)
--------------------------------------
Set "pes17_patch_dir" in config.json to the folder that holds your patch's
logos, e.g.

    "pes17_patch_dir": "D:\jawedfolder\Games\Pro Evolution Soccer 2017\download"

or leave it blank ("") and the app auto-detects download/, Data/, patch/,
content/ and livecpk/ next to "pes_exe".  On the PES 2017 tools page, card
"3c. Club logos from your PES 2017 patch folder" can also set/clear the folder
without editing JSON by hand; press "Set folder & scan".

Recognised crest files (case-insensitive, read-only):

    common/render/symbol/flag/e_201_r.png       game emblem, team id 201
    common/render/symbol/flag/e_201_r_l.dds     DDS emblem (converted to PNG)
    logos/201.png  logos/logo_201.png  logos/flag_201.png
    logos/Birmingham City FC.png                named after the club
    map.txt / teams.txt with lines like "201=Birmingham City FC"
    <patch>/download/T99_v20.cpk                CPK archive containing
       common/render/symbol/flag/e_201_r.dds    (CPK TOC read only)

Preferred emblem variants are r, r_l, r_w, r_b, ... (same order the game
uses).  Club names are matched against data/pes17/teamids.json, which the app
builds from YOUR real ML/EDIT files; the stable team id wins over the raw
bit-packed id.  When patch crests are found they are served FIRST by the
existing /api/crest?club=... endpoint and the Wikipedia crest prefetch is
skipped, so no network request is made for club logos.

GET  /api/pes17/crests           diagnostic: folders scanned, files, CPK
                                archives, logos found, clubs matched, sample
POST /api/pes17/crests/dir       set/clear the folder (PC only, saves
                                config.json). {"dir": ""} clears it.

Nothing is ever written into the game or patch folder.  No CDN, font, API or
external library is added.  If the report says "Logos found: 0", point the
folder at the place where your patch keeps emblems (often download/*.cpk) and
press Rescan.  Kit textures, player faces and stadium images are ignored.

LIMIT: the user's real patch folder was not available in this sandbox.  Loose
files, DDS/WESYS decoding, ID/name mapping and the HTTP endpoints were tested
against a synthetic patch folder and the REAL save; CPK reading was tested
with the shipped cpkread.Cpk API via a mocked archive.  Try it on your patch
and read the diagnostic card -- that is the confirmation step for your layout.

CPK ASSET INVENTORY / HARVEST (r7)
----------------------------------
There is NO .cpk archive in this repository -- only the CPK readers shipped
with pc414 and the FL26 databases extracted from those games.  The harvester
must be pointed at YOUR patch folder on Windows.  It reads the CPK table of
contents only, never modifies the source, and has no network access.

  python tools\harvest_cpk.py "D:\...\Pro Evolution Soccer 2017\download" ^
      -o manifest.json --extract "data\pes17\harvest" ^
      --classes crest,emblem,art

Or use /pes17.html card "3d. CPK assets in the patch folder" (Scan assets /
Harvest crests / logos / art), or the dashboard card.  Manifest fields:
CLASS, id, size, PES 2017 usability (YES / MAP / NO) and the reason.

  crest   common/render/symbol/flag/e_<id>_r.png|dds        MAP (team ids)
  emblem  common/render/symbol/emblem*/emb_<id>_*.png|dds   MAP (comp ids)
  kit     .../uniform/texture/.../u<tid>p1.ftex             MAP (team ids)
  face    common/render/symbol/player/<pid>.dds             MAP (player ids)
  coach   common/render/symbol/coach/coach_<id>.png         MAP (staff ids)
  pesdb   common/etc/pesdb/Competition.bin                  NO (version-specific)
  art     any other PNG/JPG/DDS                            YES (ID-independent)

DDS/FTEX/WESYS are converted to PNG with the shipped dds/ftex/bc7 readers.
Harvested files go into the APP folder (data\pes17\harvest), never into the
game folder.  Full keep/drop list for the FL26 data/*.json databases:
CPK_ASSET_INVENTORY.md.

GET  /api/pes17/assets             diagnostic inventory
POST /api/pes17/assets/extract     harvest selected classes (PC only)
GET  /api/pes17/mode               reports PES 2017 / offline / dashboard mode

PES 2017-ONLY MODE (r7)
-----------------------
"pes17_only": true in config.json (default) makes / serve the dedicated PES
2017 dashboard instead of the 20,074-line FL26 website.  The classic app is
still at /index.html and the write tools at /pes17.html; set pes17_only to
false to restore the old landing page.  Build-time cleanup removes the 7
Google Fonts links and 4 flagcdn references from index.html, flag_img() no
longer downloads flags, and wiki_web defaults to false -- so club crests and
all other assets come from YOUR local patch folder with no CDN, font or
Wikipedia request.  Set "wiki_web": true only if you want those lookups back.

LIMIT: the FL26 UI and its app-side endpoints still exist; this build makes
them opt-in, it does NOT delete them.  A true 100% PES 2017 rewrite, and a
real PES 2021 -> t99p17v20 team/player/competition ID map, are still needed.

SAFE CLEANUP (r8)
-----------------
CLEANUP_MANIFEST.txt in this folder lists the 111 removed files and their
sizes.  Removed: the FL26 Sider regen fix (94 files), Michele & Claude Lua
mods (8), F7 dump Lua modules (2), the FL27 save key + readme (2), and
data/players.json, positions.json, playpos.json, ratings.json and
realmoves.json (5 FL26 databases, 6.8 MB).  On a PES 2017 save the app
rebuilds data/pes17/players.json etc. from EDIT00000000 (20,018 players),
so those FL26 IDs are never used.  Nothing in your save, patch or game
folder is touched.  Kept: the classic FL26 UI (still at /index.html), its
art, scenes, stadium photos, i18n strings, teamids.json and small metadata
JSONs, all lib/*.py, and the portable python/ folder.  All 132 GET endpoints
were compared against the unpruned r7 build: 132 identical status pairs,
zero new errors.

HOW TO USE ON WINDOWS
---------------------
1. Unzip this build anywhere (not inside the zip) on Windows.
   Check VERSION.txt in that folder: it must say
   "pc414-pes17-clean-r8 (2026-11-04)".  If it says
   "pc414 (2026-11-01)" you unzipped the ORIGINAL program, which cannot
   decrypt a PES 2017 save at all.
   Both builds use port 8766, so close the old one first (or run
   "The Gaffer.bat" from the new folder, which stops the old process).
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
  {"op":"budget","value":3088641,"wage":10245745}
]

DIFF TOOLS (on the development machine)
---------------------------------------
    git fetch origin main
    python3 pes2017/tools/fetch_after_pairs.py   # stage the 4 after saves from main
    python3 pes2017/tools/diff_saves.py  BEFORE AFTER --json diff.json
    python3 pes2017/tools/verify_pairs.py --before "Needed files/ML00000011" \
        --after-dir build/pairs
    python3 pes2017/tools/analyze_save_noise.py \
        --json build/analysis/noise_report.json

TESTS
-----
    python3 -m unittest discover -s pes2017/tests -p 'test_*.py' -v
127 tests pass, including tests that decrypt, read, modify and re-encrypt
YOUR real ML00000011 / EDIT00000000 files (on copies only), tests that
prove all four measured pair patches against the game-generated after files,
r2 regression tests for the budget read side, r3/r4 checks for the game
skin / SVG icon pack (100% symbolic-glyph coverage, ZWJ sequences,
catch-all, offline, JS syntax), and r5 tests for the layout guard
(refusal on a different-size or broken-table save, all four custom ops,
report/opt-out modes, real shirt numbers / XI, RAW budget labels), and r6
tests for the offline crest reader (loose files, CPK/WESYS, DDS -> PNG,
stable-id mapping, auto-detection, read-only, no network API).  A live HTTP
smoke on the real save with a synthetic patch folder passed 32/32 checks
(r6), plus r7 tests for the CPK asset inventory / harvester (8 classes,
DDS/WESYS -> PNG, source read-only, CLI, no network) and the offline /
dashboard wiring.  A live r7 HTTP smoke passed 42/42 checks.  r8 adds 13
cleanup / shipped-zip / offline-guard tests; a live HTTP smoke of the PRUNED
build passed 76/76 checks, including all 132 GET endpoints returning exactly
the same status as the unpruned r7 build (zero new 5xx, no timeouts).

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
