THE GAFFER pc414 - FC 27 DATABASE BUILD r12
===========================================

This folder is The Gaffer pc414.  It is a private, modified build for personal
use; please respect the original FREE TO USE terms of The Gaffer (do not
reupload or publish this as your own work).

r12 begins the move from a PES save-file companion to a standalone game:
EA SPORTS FC 27 is now the only game and supplies the player database.
See FC 27 DATABASE below for what is wired and what is NOT yet done.

FC 27 DATABASE (r12)
--------------------
The game runs on 21,623 players, 717 real clubs, 41 leagues and 102 cups
extracted from the FC 27 tables bundled in eafc-db-kit (MIT, (c) 2026 ViniMacacari):

    https://github.com/ViniMacacari/eafc-db-kit

WHERE THE DATA LIVES
    data/fc27/*.json      the database (committed, ~7 MB)
    lib/fc27.py           pure-stdlib runtime reader
    tools/import_fc27.mjs BUILD-TIME ONLY generator (the only Node in the repo)

Playing needs no Node, no npm install and no network: the runtime is still
pure-stdlib Python.  To regenerate the data:

    npm pack eafc-db-kit
    mkdir -p /tmp/kit && tar xzf eafc-db-kit-*.tgz -C /tmp/kit
    node tools/import_fc27.mjs --kit /tmp/kit/package

The six files players/ratings/positions/playpos/teamids/comps.json keep the
schema the existing algorithms already read, so market.py, growth.py,
aitransfers.py, ailineup.py, aimanager.py, negotiate.py, revalue.py, board.py,
formengine.py and the ovr_weights tables are all KEPT and run on FC 27 data
unchanged.  Nothing was rebranded in the UI; the new source is wired underneath.

ENGINE REFERENCE DATA
The engine is a separate program with its own save. It needs static reference
data, not season state, so these tables are extracted too:

    stadiums.json    181 venues; name, capacity, city, pitch dimensions.
                     Linked for 717/717 clubs (teams only carried a capacity).
    managers.json    717 entries; name where licensed (452), stars, nationality.
    squad_meta.json  shirt numbers + squad role per player:
                     0 = starting XI, 1 = substitute, 2 = reserve.
                     Every club has exactly 11 designated starters.
    formations.json  717 formations; name ("4-2-3-1"), 11 slots, per-slot roles
                     and pitch offsets for the UI.
    rivals.json      1,040 derby pairs with intensity (Everton 5, Man Utd 5 for
                     Liverpool) - richer than teams.rivalteam's single id.
    loans.json       645 loans; owning club, destination, end date, option to buy.
    traits.json      trait1/trait2 as RAW bitflags, isretiring, skill-move
                     likelihood. The bit meanings are undocumented upstream, so
                     they are stored raw rather than guessed at.
    cups.json        102 named cups (FA Cup, Carabao Cup, DFB-Pokal, Copa del
                     Rey, Coppa Italia, UCL/UEL/UECL, Libertadores...).
    prev_pos.json    last season's finishing position per club, for reputation
                     and board expectations.

DELIBERATELY NOT EXTRACTED - the engine owns this
    points, fixtures, results, budgets, form, injuries, league tables.
    The template's standings are half-filled (points non-zero for only 295/870
    clubs), so importing them would seed a career with contradictory numbers.
    Cup qualification is likewise engine state: a cup is shipped whenever it
    has a name, and the template's seed list is kept only as an optional hint.
    Market value is NOT a column in FC 27 (only wage and release clause), so
    the engine must derive it - market.py/revalue.py already do this.

Read API (no save required):
    /api/fc27/status            counts + provenance
    /api/fc27/leagues?women=0   league list
    /api/fc27/league?id=13      one league + its clubs
    /api/fc27/club?id=9         club, squad, stadium, manager, formations,
                                rivals, starting XI, last season's position
    /api/fc27/player?id=203376  one player incl. shirt, role, traits, loan
    /api/fc27/search?q=mbappe   accent-insensitive search
    /api/fc27/cups?women=0      cup list
    /api/fc27/loans?club=9      loans in/out for a club

TWO ID COLLISIONS THAT HAD TO BE FIXED (not cosmetic)
    FC 27 reuses small competition ids for DIFFERENT leagues: 17 is Ligue 2
    here but Premier League in FL26, 19 is 1. Bundesliga.  Twelve FL26 ids do
    not exist in FC 27 at all, so merging the tables left stale names behind.
    COMP_LEAGUES/COMP_GROUPS are now REPLACED from data/fc27/comps.json.
    Nationality ids differ too (PES uses 194-238 for Europe, FC 27 uses
    4 Austria / 18 France / 21 Germany), so regrules.EU would have mis-checked
    every non-EU signing.  RULES_FC27 / DOMESTIC_FC27 / EU_FC27 were added,
    derived from the extracted leagues and nations, never guessed.

ALSO REMOVED IN r12
    The PES F7-dump database importer (/api/dbimport/preview, /apply, /faces).
    A PES dump has different player ids and a different attribute scale, so
    importing one would corrupt the FC 27 database.  Rebuild with the importer
    instead.  _dbf() no longer falls back to data/ root, which would silently
    serve FL26 players against FC 27 squads.

SCOPE OF THIS STEP
    This is the database step.  The separate game engine - time and season
    progression, match simulation, career state and its own save - is the next
    piece of work and is not built yet.  The existing UI still reads career
    state through the old PES save path, so those screens need the engine (or a
    save) before they show anything; the /api/fc27 routes above work standalone.
    The 25 PES attributes are MAPPED from EA's separate attribute set, so they
    are approximations.  Overall rating is EA's own value, used directly
    (dbimport.USE_GAME_OVR), not recomputed from the mapped 25.

LICENSING - IMPORTANT
    eafc-db-kit's MIT licence covers the KIT'S CODE, not EA's football data.
    The player/club/rating content is EA's copyrighted material and is
    redistributed here without an explicit licence from the rights holder,
    at the repository owner's direction.  Read data/fc27/NOTICE.txt before
    publishing or selling this.  The importer and runtime depend only on the
    JSON schema, so the data can be swapped for a set you have rights to.

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
5. MATCHDAY PRESENTATION.  The Classic app remains the default at / and
   uses an integrated football-management presentation shared with the
   PES 2017 tools page.  The former separate dashboard and game-skin toggle
   have been removed.
6. LOCAL ICONS.  Original emoji are replaced with layered SVG game emblems.
   The renderer also handles older saved messages, with a neutral fallback
   for unknown pictographs.  Regular text arrows remain text.
7. r6: PATCH-FOLDER CLUB CRESTS.  The app can now read club logos straight
   from the local PES 2017 patch folder, offline, instead of downloading
   crests from Wikipedia.  Loose PNG/JPG/DDS/FTEX logos and
   common/render/symbol/flag/e_<id>_r.dds entries inside *.cpk archives are
   decoded with the readers already shipped with the program.
   REMOVED in r11 - see LOGO IMPORTERS REMOVED below.
8. r7: CPK HARVEST + PES 2017-ONLY MODE.  An offline inventory of everything
   the shipped CPK readers can reach (competition emblems, kit textures,
   coach portraits, pesdb tables, generic art), a harvester that can
   copy them before you delete the PES 2021 files, and no external CDNs by
   default.  The Classic application remains at /.  The inventory and
   harvester were REMOVED in r11; PES 2017-only mode is unchanged.
9. r8: SAFE CLEANUP (not a rewrite).  111 FL26/FL27/Sider-only files
   (10.01 MB) are removed from this shipped build only: addons/regenfix,
   addons/michele, lua, FL_key.bin + its readme, and the five FL26 player
   databases that PES 2017 regenerates into data/pes17/ from your real
   EDIT00000000.  The classic FL26 page
   at /index.html, its art/scenes/stadiums and all lib/*.py are KEPT because
   they are still referenced.  realmoves_fetch_bg() is now blocked offline so
   removing the FL26 transfer cache does not trigger a Wikipedia fetch.
10. r9: FIRST RUN WORKS.  The original pc414 default save_dir pointed at a
   Football Life 2026 / PES 2021 folder.  On a PES 2017 PC that folder does
   not exist, so a fresh install showed raw Windows errors
   ([Errno 2] / [WinError 3]) instead of your save.  r9 removes that default,
   auto-detects KONAMI\Pro Evolution Soccer 2017\save under your profile,
   Documents and OneDrive (including Dokumenti), and adds a "Save folder"
   card on the PES 2017 tools page plus GET /api/pes17/setup and
   POST /api/pes17/setup/savefolder.  Paste the path once; it is written to
   config.json and works immediately.

11. r10: PLAYER MINI-FACE IMPORT REMOVED.  It did not work reliably, so the
   whole PES 2017 mini-face importer is gone: lib/pes17_faces.py,
   static/pes17-face-refresh.js, GET /api/pes17/faces, GET /api/pes17/face,
   the "Player mini-faces" half of tools card 3c,
   "Harvest mini-faces", and the "face" class in the CPK harvester.  The app
   no longer scans the game/patch folder for portraits.  Players show the
   initials/silhouette badge; the tools page uses a local SVG badge with no
   image request.  Portraits already cached in data/gface are still served,
   and the legacy FM-cutout / Wikipedia photo paths are untouched.

12. r11: LOGO IMPORTERS + CPK ARCHIVE READING REMOVED.  Club crests,
   competition logos/emblems, national flags and the whole CPK asset
   harvester are gone, ready for a new logo system to be built.  See
   LOGO IMPORTERS REMOVED below for exactly what was deleted and what
   was deliberately kept.
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
screen; it is display-only and NEVER writes to the save.  Report the in-game
figure and the correct scale can be applied -- until then the EUR sign in
the Classic UI is only presentation.

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

MATCHDAY PRESENTATION
---------------------
The Classic application opens directly at /.  Its matchday controls, panels
and PES 2017 tools use the same dark football-management presentation.  On
larger desktop displays, the six-section Game Shell activates after the
first-run tour; screens scroll inside the window.  To return to the original
scrolling Classic navigation, open Look & sound and switch Game shell off.
Phones and tablets retain their existing layout.  There is no separate
dashboard.  PES 2017 tools remain at /pes17.html and in the sidebar.

  * Layered local SVG emblems replace emoji in the shipped UI and in older
    saved messages.  Morale has directional indicators; unknown pictographs
    use a neutral emblem.  Normal text arrows remain text.
  * The icon renderer preserves text-only controls and translations.  No
    external icon library, font or network connection is required.
  * Files: static/hud-icons.svg, static/hud-icons.js, static/hud-ui.css.

This is a presentation update.  Save-writing restrictions, layout checks,
dry runs, backups and API behaviour remain in force.

WHAT CAN BE WRITTEN (MEASURED, ROUND-TRIP VERIFIED)
---------------------------------------------------
Open  http://localhost:8766/pes17.html  (or the "PES 2017 tools" button in
the Classic sidebar).  The page reads your real save and lets you queue ops:

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

LOGO IMPORTERS REMOVED (r11)
----------------------------
All logo importing was deleted so a new system can be built in its place.
Nothing is downloaded, scanned or decoded for logos any more, and the UI
makes ZERO image requests for crests, competition logos or flags.

Deleted files:
    lib/pes17_crests.py      offline patch/livecpk/CPK club-crest reader
    lib/pes17_assets.py      CPK asset inventory + harvester
    lib/cpkread.py           CPK archive (TOC/WESYS) reader
    tools/harvest_cpk.py     harvester CLI
    static/leagues/*.png     the two bundled Premier League logos

Deleted endpoints (they now return 404):
    GET  /api/crest                  GET  /api/crest/prefetch (POST)
    GET  /api/flag                   GET  /api/compemb
    GET  /api/complogo               GET  /api/comp/logo
    GET  /api/pes17/crests           POST /api/pes17/crests/dir
    GET  /api/pes17/assets           POST /api/pes17/assets/extract

Also gone: server-side crest/emblem/flag/game-logo indexers and the
Wikipedia crest prefetch worker, the crest thumbnail download in
lib/wiki.py, tools cards "3c. Club logos" and "3d. CPK assets", the
"pes17_patch_dir" config key, and the db-import "with an in-game crest"
counter.

What you see instead: the generated initials shield for clubs (coloured
from lib/clubcolors.py), the generated SVG league badge, and a trophy
glyph for competitions.  These are drawn locally from the club/league
name - no file and no network is involved.

DELIBERATELY KEPT (they are not logo importers):
  * lib/dds.py, lib/ftex.py, lib/bc7.py - texture codecs.  The kit-sponsor
    feature imports them, so they stay.
  * lib/kitsponsor.py and /api/kitsp/* - shirt/kit sponsor editing.
  * Loose-folder readers (_cpk_find / _cpk_roots / _game_db_file) for
    kit textures, coach portraits and pesdb competition DATA read from
    livecpk folders.  Only CPK ARCHIVE reading was removed.
  * Competition names/entries, club IDs and the Wikipedia article-title
    lookup used by kit/ground/founded-year data.
  * /api/clubcolors, /api/kit, /api/kitimg, /api/coach/img, /api/stadium.

KNOWN EFFECT: kits that existed ONLY inside FL27 CPK archives can no
longer be copied for sponsor editing (_ks_fl27_make now returns None).
Loose kit-server files and FL26 livecpk kits still work.

GET  /api/pes17/mode               reports PES 2017 and offline mode

PES 2017-ONLY MODE
------------------
The Classic application is served at / (and /index.html) regardless of the
PES 2017-only setting.  The PES 2017 read/write tools are at /pes17.html.
"pes17_only": true in config.json keeps PES 2017 defaults active.  Build-time
cleanup removes the Google Fonts links and flag CDN references from the
Classic app, the flag endpoint was removed in r11, and wiki_web defaults to
false.  Set "wiki_web": true only if you want Wikipedia text lookups back
(player descriptions, club kit/ground data).  No logo is fetched either way.

LIMIT: the FL26 UI and its app-side endpoints still exist; the PES 2017
edition is not a complete rewrite.  A real PES 2021 -> t99p17v20
team/player/competition ID map is still needed.

SAFE CLEANUP (r8)
-----------------
The r8 cleanup removed 111 files (10.01 MB): the FL26 Sider regen fix (94 files), Michele & Claude Lua
mods (8), F7 dump Lua modules (2), the FL27 save key + readme (2), and
data/players.json, positions.json, playpos.json, ratings.json and
realmoves.json (5 FL26 databases, 6.8 MB).  On a PES 2017 save the app
rebuilds data/pes17/players.json etc. from EDIT00000000 (20,018 players),
so those FL26 IDs are never used.  Nothing in your save, patch or game
folder is touched.  Kept: the classic FL26 UI (still at /index.html), its
art, scenes, stadium photos, i18n strings, teamids.json and small metadata
JSONs, and all lib/*.py.  All 132 GET endpoints
were compared against the unpruned r7 build: 132 identical status pairs,
zero new errors.

FIRST RUN - SAVE FOLDER (r9)
----------------------------
A fresh install has NO config.json and NO hard-coded FL26 save path any more.
The app looks for ...\KONAMI\Pro Evolution Soccer 2017\save in your
profile, Documents and OneDrive (including localised names like Dokumenti).
If it cannot find one, open PES 2017 tools from the Classic sidebar; the
"Save folder" card appears at the top instead of raw Windows errors.  Paste the full path that holds ML00000011 and
EDIT00000000, e.g.
    C:\Users\<you>\Documents\KONAMI\Pro Evolution Soccer 2017\save
    C:\Users\<you>\OneDrive\Dokumenti\KONAMI\Pro Evolution Soccer 2017\save
and press "Use this folder".  It is saved to config.json and takes effect at
once.  Save reads work on a fresh install with no other setup.

HOW TO USE ON WINDOWS
---------------------
1. Unzip this build anywhere (not inside the zip) on Windows.
   Check VERSION.txt in that folder: it must say
   "pc414-pes17-clean-r11 (2026-11-06)".  If it says
   "pc414 (2026-11-01)" you unzipped the ORIGINAL program, which cannot
   decrypt a PES 2017 save at all.
   Both builds use port 8766, so close the old one first (or run
   "The Gaffer.bat" from the new folder, which stops the old process).
2. Double-click "The Gaffer.vbs" (or "The Gaffer.bat").
3. In Setup > Save folder choose
      ...\Documents\KONAMI\Pro Evolution Soccer 2017\save
   (or wherever your ML00000011 / EDIT00000000 live), then Save paths.
   Keep EDIT00000000 in that folder (or set "edit_dat" in config.json).
   The Classic sidebar's "PES 2017 tools" button opens /pes17.html.
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

COMMAND LINE (needs Python 3.10+ installed)
-------------------------------------------
    python lib\pes17_write.py roundtrip ML00000011
    python lib\pes17_write.py info ML00000011 --edit EDIT00000000
    python lib\pes17_write.py offers ML00000011
    python lib\pes17_layout.py info C:\dec\ML00000011
    python lib\pes17_write.py apply ML00000011 --ops ops.json --work work

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
The suite includes tests that decrypt, read, modify and re-encrypt real
ML00000011 / EDIT00000000 files (on copies only), tests that prove the four
measured pair patches against game-generated after files, budget read-side
regressions, matchday icon / translation checks, and layout guard tests
(refusal on a different-size or broken-table save, all four custom ops,
report/opt-out modes, real shirt numbers / XI, RAW budget labels).  The
r6 crest-reader and r7 CPK-harvester tests were removed with those modules
in r11.  r8 adds 13
cleanup / shipped-zip / offline-guard tests; a live HTTP smoke of the PRUNED
build passed 76/76 checks, including all 132 GET endpoints returning exactly
the same status as the unpruned r7 build (zero new 5xx, no timeouts).  r9
adds 15 first-run / save-folder tests; a fresh-install HTTP smoke (NO
config.json) and a configured-install smoke passed 66/66 checks, and a
133-GET sweep against r8 returned 132 identical statuses (the only new
endpoint is /api/pes17/setup).

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
