# What can still be extracted from the PES 2021 / FL2x CPK files

**Answering "what else can you extract and fetch from these CPK PES 2021 files
before cleaning them and making it 100% PES 2017".**

## 0. Hard fact first

There is **no `.cpk` archive anywhere in this repository** (`find . -iname
'*.cpk'` → 0). What we have is:

* the original `TheGaffer_pc414_20261103.zip` (280 files, 31 MB) — the FL26 /
  PES 2021 / FL27 companion app, including the CPK **readers** and the FL26
  databases that were extracted from those games;
* `Needed files/` — two real PES 2017 saves, `info.txt`, a Cheat Engine table;
* four game-generated after saves at the repo root.

So nothing can be *actually fetched* from a real PES 2021 CPK in this sandbox.
What follows is (a) the exact list of asset classes the shipped readers can
reach, (b) which of them survive a PES 2017 cleanup, and (c) a working,
offline harvester you can run against **your** patch folder on Windows before
you delete the PES 2021 files.

## 1. Every asset class the shipped readers can pull out of a CPK

`server.py` + `lib/cpkread.py`, `lib/dds.py`, `lib/ftex.py`, `lib/bc7.py`
already implement all of this. `cpkread.Cpk` reads only the TOC (works on
multi-GB archives); `_unwesys()` unwraps the WESYS/zlib wrapper; `dds.py`
decodes DXT1/3/5 and uncompressed 32-bit DDS; `ftex.py` + `bc7.py` decode
Fox FTEX kit textures.

| Class | Internal CPK path (case-insensitive) | Shipped consumer | PES 2017 reusable? | Why |
|---|---|---|---|---|
| **Club crests** | `common/render/symbol/flag/e_<id>_<variant>.(png\|dds)` | `_game_logo_index()`, `game_logo()`, `/api/crest` | **MAP** | Already done in r6 (`pes17_crests`), but PES 2021 team IDs ≠ PES 2017 team IDs; needs the real-save `teamids.json` map. |
| **Competition logos** | `common/render/symbol/emblem*/emb_<id>_<variant>.(png\|dds)` | `_emblem_index()`, `/api/comp/logo`, `/api/complogo` | **MAP** | Images are generic PNG/DDS, but competition IDs differ. Worth harvesting before deletion. |
| **Kit textures** | `Asset/model/character/uniform/texture/#windx11/u<tid>p<k>.ftex` | `kit_img()`, `/api/kitimg`, kit-sponsor pipeline | **MAP** | Fox FTEX/BC7 format is shared with PES 2017, but `u<tid>` IDs differ. Would need a team-ID map + per-club verification. |
| **Player portraits** | `common/render/symbol/player/<pid>.(dds\|png)` | `game_face()`, `/api/gface` | **MAP** | PES 2017 player IDs are a different ID space (`EDIT00000000` has 20,018 players). Only usable with an explicit PID map. |
| **Coach portraits** | `common/render/symbol/coach/coach_<id>.(png\|dds)` | `coach_img()`, `/api/coach/img` | **MAP** | Same ID problem. |
| **Competition DB** | `common/etc/pesdb/Competition.bin`, `CompetitionEntry.bin`, `CompetitionRegulation.bin`, `Coach.bin`, `Team.bin` | `_game_db_file()`, league names, UEFA phases | **NO** | Version-specific binary layouts. PES 2017 reads its own league/competition names from the ML + EDIT save; r1 already does that. |
| **Generic art** | any other `.png/.jpg/.dds` (backgrounds, stadium photos, UI textures) | `data/art/*`, `data/myscenes/*`, `data/stadiums/*` | **YES** | ID-independent. Safe to keep as decoration in a PES 2017-only UI. |
| **Anything else** | unknown binaries, text, `.bin`, `.lua`, `.ini` | — | **MAYBE** | Catalogued, never extracted by default. |

**Beyond crests, the genuinely harvestable items are therefore: competition
emblems, kit textures, player/coach portraits, generic art, and (as a
reference only) the pesdb binaries.** All ID-based classes need a mapping
table; only generic art is directly reusable.

## 2. What the shipped `data/` folder actually is (FL26, not CPK)

The 49 files in `TheGaffer/data/` are **extracted FL26 databases**, not CPK
archives. For a pure PES 2017 build:

| File(s) | Size | Content | Cleanup decision |
|---|---|---|---|
| `players.json`, `playpos.json`, `positions.json`, `ratings.json`, `realmoves.json` | ~6.6 MB | FL26 player IDs, ratings, positions, preferred moves | **DROP** — r1 `pes17_auto_db()` builds `data/pes17/*.json` from the user's real `EDIT00000000` instead. FL26 IDs would show wrong names. |
| `teamids.json`, `club_identity.json`, `fl26_installed_league_counts.json`, `venue_metadata.json`, `owners.json` | ~0.6 MB | FL26 club IDs, identities, league counts, venue metadata | **DROP** — all keyed to FL26 IDs. |
| `i18n/strings_en.json`, `i18n/it.json`, `fm_text.json`, `scenes.json` | ~0.5 MB | UI strings, FM-style flavour text, scene names | **KEEP** — language/text only, no IDs. |
| `art/*.jpg`, `myscenes/*`, `stadiums/*.jpg` | ~7 MB | backgrounds, press-conference scenes, stadium photos | **KEEP** — ID-independent generic art. |

`lib/cpkread.py`, `lib/dds.py`, `lib/bc7.py`, `lib/ftex.py` are pure readers
with no game-version assumptions: **KEEP**, and r7 reuses them in the harvester.

## 3. What r7 implements (harvest before cleanup)

* `pes2017/tools/harvest_cpk.py` — offline CLI. Point it at a patch folder,
  a `livecpk` folder, or a single `.cpk`; it writes a full JSON manifest
  (`CLASS / id / size / PES 2017 usability / reason` for every entry) and can
  copy selected classes into the **app's** folder, converting DDS/FTEX/WESYS
  to PNG. It refuses to extract into the source folder and never modifies it.
* `lib/pes17_assets.py` — the same engine used by the app:
  `GET /api/pes17/assets` (diagnostic), `POST /api/pes17/assets/extract`
  (owner-only, writes to `data/pes17/harvest/`), `source_for(cfg)` auto-detects
  `download/`, `Data/`, `patch/`, `content/`, `livecpk/` next to `pes_exe`.
* `GET /api/pes17/mode` — reports PES 2017 / offline / dashboard mode.
* Card **3d** on `/pes17.html` and the new **PES 2017 dashboard** show the
  inventory and can trigger a harvest.

## 4. PES 2017-only cleanup performed in r7

| FL26/FL27 leftover | r7 action |
|---|---|
| `/` served the 20,074-line FL26 `index.html` | `/` now serves `static/pes17-dashboard.html` (dedicated PES 2017 dashboard) when `pes17_only` is true; classic app still at `/index.html`, tools at `/pes17.html`. |
| 7 Google Fonts `<link>` tags fetched on every load | removed at build time by asserted regex patches; system fonts used. |
| `flagcdn.com` in `index.html` (4 sites) | removed at build time; flag `<img>` tags resolve locally and hide on error. |
| `flag_img()` server-side `urllib` download from `flagcdn.com/w160/` | short-circuited to `None` when `pes17_only`; cached local flags still served. |
| `_wiki_web()` defaulted to `True` → Wikipedia GETs | default changed to `False`; set `wiki_web:true` to opt back in. |
| Wikipedia crest prefetch | already skipped in r6 when patch crests exist. |
| FL26 write endpoints | still blocked by `pes17_readonly()` / `write_guard()` from r1. |
| FL26 player/club databases | r8 removes the five shadowed FL26 databases (`players/positions/playpos/ratings/realmoves.json`); the PES 2017 build regenerates the first four into `data/pes17/` from the real `EDIT00000000`. Small metadata JSONs and `teamids.json` stay for `/index.html`. |

`config_pes2017.example.json` documents `pes17_only` (default `true`) and
`wiki_web` (default `false`).

### 4b. r8 conservative cleanup (the user said NO to a full rewrite)

`pes2017/prune.py` runs inside `build.py` and removes **111 files / 10.01 MB**
from the shipped build only: `addons/regenfix/` (94), `addons/michele/` (8),
`lua/` (2), `FL_key.bin` + `FL_key_README.txt` (2), and the five FL26
databases above (5). All are FL26 / FL27 / Sider-only, or shadowed by
`data/pes17/*`. `CLEANUP_MANIFEST.txt` in the program folder lists every
deletion; `pes2017/CLEANUP_REPORT.md` explains the keep list. Kept on purpose:
the classic FL26 UI (`/index.html`), its `static/art`, `static/leagues`,
`data/art`, `data/myscenes`, `data/stadiums`, `data/i18n`, `fm_text.json`,
`scenes.json`, `teamids.json`, `venue_metadata.json`, `club_identity.json`,
`owners.json`, `fl26_installed_league_counts.json`, all `lib/*.py` and
`python/*`. Because the FL26 `realmoves.json` cache is gone, `patch.py` now
guards `realmoves_fetch_bg()` with `_wiki_web()` so no Wikipedia GET is
attempted by default. **This is cleanup, not deletion of the FL26 UI.**

## 5. What "100% PES 2017" still needs (not claimed)

1. **Delete or replace the FL26 UI.** The 2.9 MB `index.html` and its 29
   `p-*` pages still exist and are reachable at `/index.html`; r7 makes them
   opt-in, not gone. A full rewrite is a separate, large UI project — and the
   user explicitly rejected the r3–r5 skin ("ui is still shit").
2. **Block FL26-only API endpoints server-side** in PES 2017 mode (many
   app-side career endpoints still work against app-side data). Not done:
   it would break `/index.html` for users who opt back in.
3. **A real ID mapping** from PES 2021 team/player/competition IDs to the
   `t99p17v20` ID space. Without the user's actual patch folder this cannot be
   produced here; the harvester labels those classes `MAP` rather than
   pretending they work.
4. **Real CPK archives** to verify the TOC paths, WESYS wrapping and DDS/FTEX
   decoders. CPK reading is covered by a mocked `cpkread.Cpk` API plus the
   shipped decoder on synthetic DDS/WESYS, not by a real PES 2021 CPK.

## 6. Verification status

* **142 unit tests OK** (10 for the harvester + 5 r7 wiring + 13 r8 cleanup
  + 15 r9 first-run checks), `verify_pairs.py` **PASS**, `node --check` clean for both HTML
  inline scripts, and **76/76 HTTP checks** against a live server built from
  the pruned zip with the real `ML00000011` and a synthetic patch folder
  (r7 checks above, cleanup/manifest checks, regenerated `data/pes17/` player
  database, classic-app endpoint guards, save SHA unchanged). A differential
  sweep of all **132 GET endpoints** against the unpruned r7 build produced
  132 identical status pairs — zero new 5xx, zero timeouts.
* No real CPK archive, no Windows execution, no in-game save load. **Nothing
  here proves a written save is accepted by PES 2017**; the header-hash and
  budget-scale checks from `REAL_SAVE_REPORT.md` §6f remain outstanding.
