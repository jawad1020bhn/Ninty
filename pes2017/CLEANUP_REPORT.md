# Safe cleanup of the PES 2017 build (r8)

Asked: *"no, clean things that can be removed safely"* — i.e. **not** the full
FL26 UI rewrite, just delete the leftovers that are provably unused.

The verification figures below record the r8 build at the time of cleanup.
The current build opens the Classic application at `/`, retains the tools at
`/pes17.html`, and no longer ships the old dashboard or `game-skin` overlay.

`pes2017/prune.py` runs inside `build.py` after `patch.apply()`. It removes a
**curated list of 111 files (10.01 MB uncompressed)** from the freshly
extracted build tree only. It never touches the repository, the original zip,
the game folder, the patch folder or any save. Every deletion is written into
`CLEANUP_MANIFEST.txt` inside the shipped program.

## Removed

| Path | Files | Why it is safe |
|---|---|---|
| `addons/regenfix/` | 94 | FL26 Sider regen fix: `fl26regen.dll`, `.lua`, `.bin` and 90 regen-face DDS files. PES 2017 here has no Sider. `_regen_src()` / `_regen_state()` / `setup_install_regen()` all guard on `os.path.isfile`, so Setup reports "not available" instead of crashing. |
| `addons/michele/` | 8 | FL26 Sider Master League Realism Lua modules (Michele & Claude). `_mich_src()` and the installer guard on `os.path.isfile`. |
| `lua/` | 2 | Sider F7 `PlayerDump.lua` / `GrowthBridge.lua`. PES 2017 has no F7 dump; `_lua_ver()` is in a try/except and `put()` skips missing files. |
| `FL_key.bin`, `FL_key_README.txt` | 2 | Football Life 2027 save key. PES 2017 uses `KEY_PES17`; `_fl_key()` returns `None` when absent and `decrypt()` still tries the PES 2017 key. |
| `data/players.json`, `positions.json`, `playpos.json`, `ratings.json`, `realmoves.json` | 5 | FL26 player databases / Wikipedia transfer cache. On a PES 2017 save, r1 writes `data/pes17/{players,positions,playpos,ratings,teamids}.json` from the real `EDIT00000000`, and `_dbf()` resolves those first once `_GAME['v'] == 'pes17'`. Startup is guarded: `mlwrite.load_names()` / `load_positions()` return `{}` for a missing file, `PLAYPOS` is in a try/except, `ratings.json` is behind `os.path.exists`, `real_moves_ready()` returns `False`. |

## The one code change this cleanup required

`real_moves()` calls `realmoves_fetch_bg()` when its cache file is missing.
With `data/realmoves.json` removed, that would have spawned a background
Wikipedia GET on first use — contradicting the `wiki_web:false` offline
default that r7 established. So `patch.py` adds an asserted one-line guard at
the top of `realmoves_fetch_bg()`:

```python
    if not _wiki_web():
        return   # r8: offline by default; the FL26 Wikipedia transfer cache was cleaned out, never refetch it
```

Verified live: after hitting all 132 GET endpoints on the pruned build,
`data/realmoves.json` is still absent — no outbound request, no recreated
cache. Set `wiki_web:true` in `config.json` if you deliberately want those
lookups back. This is the only behaviour change in r8; every other diff is a
file deletion.

## Kept on purpose (and why)

* **Classic application**: `static/index.html`, `static/art/*`,
  `static/leagues/*`, `favicon.png` and the local `hud-*` presentation assets.
  It is the default at `/` as well as `/index.html`; deleting it would break
  the application.
* **ID-independent art / text**: `data/art/*`, `data/myscenes/*`,
  `data/stadiums/*`, `data/i18n/*`, `fm_text.json`, `scenes.json`. The classic
  app serves these through `/api/art`, `/api/myscene`, `/api/scene`,
  `/api/fmtext`. r7's inventory already classified them as `YES / keep`.
* **Small FL26 metadata** (`teamids.json`, `venue_metadata.json`,
  `club_identity.json`, `owners.json`, `fl26_installed_league_counts.json`):
  `lib/fl26_venue_metadata.lookup()` reads `teamids.json` +
  `venue_metadata.json` for `/api/venue`; `_game_logo_index()` falls back to
  `teamids.json`. Removing them would produce 500s on classic-app endpoints.
  Total cost of keeping: ~0.56 MB.
* **All `lib/*.py`**: `server.py` imports most of them at startup. Total 0.98 MB.
  (`lib/realmoves.py` stays but its background fetch is now guarded offline.)
* **Bundled `python/*`**: portable Windows Python, required to run the app.
* **PES 2017 runtime**: tools page, `pes17*`, `pescrypt`,
  `cpkread/dds/ftex/bc7`, launchers, docs, `tools/harvest_cpk.py`,
  `CPK_ASSET_INVENTORY.md`.

## Verification before shipping

* `prune.apply()` asserts that **every** `KEEP` path still exists and that
  **no** planned removal remains; it raises instead of producing a broken zip.
* **13 new unit tests** cover the rules, `plan()`/`apply()` on a synthetic
  tree, the offline guard, the shipped zip contents and the manifest.
  Full suite: **127 unit tests OK (1 skipped)**, `verify_pairs.py` **PASS**,
  `node --check` clean.
* A live HTTP smoke runs against the **pruned** build (not the unpruned tree)
  with the real `ML00000011` and a synthetic patch folder: **76/76 checks
  PASS** — startup, dashboard, classic app, `/api/state`, `/api/setup/status`,
  `/api/fmtext`, `/api/venue`, `/api/scene`, `/api/art`, all `/api/pes17/*`
  endpoints, crests, assets, harvest, dry measured writes, layout guard,
  cleanup/manifest checks, regenerated `data/pes17/players.json` (20,018
  players from the real EDIT), and the unchanged real save SHA.
* **Differential sweep:** all **132 GET endpoints** were called on both the
  pruned r8 build (port 8767) and a freshly extracted unpruned r7 build (port
  8768) with identical config/save/patch. **132 identical status pairs, zero
  new 5xx, zero timeouts.** The handful of pre-existing 500s are identical in
  both builds; this cleanup introduces none.
* `CLEANUP_MANIFEST.txt` lists all 111 removals (10,013,776 bytes).
  See `REAL_SAVE_REPORT.md` §6i for the exact deliverable hash.

## Still NOT removed (needs a redesign, not a cleanup)

The 20,074-line `index.html` and its 29 `p-*` pages, the FL26 app-side career
endpoints, and the FL26 save-writing engine (already blocked by
`pes17_readonly()`). Deleting those means rewriting the whole app — the user
said **no** to that. Also still outstanding: a real PES 2021 → `t99p17v20`
team/player/competition ID map, real CPK decoding, and the Windows in-game
save-load / header-hash / budget-scale test. **None of this cleanup proves a
written save is accepted by PES 2017.**

## r9 follow-up (first run)

r8's cleanup removed `data/realmoves.json` but did not touch the hard-coded
FL26 `DEFAULT_CFG['save_dir']`. A user's first run on Windows (no
`config.json`) therefore still hit a nonexistent PES 2021 path and the
dashboard printed raw `[Errno 2]` / `[WinError 3]` errors. r9 fixes that: the
default is empty, `lib/pes17_setup.py` auto-detects a real PES 2017 save
folder, `GET /api/pes17/setup` + owner-only `POST
/api/pes17/setup/savefolder` let the user set it from the tools page, and
`/api/slots` / `/api/pes17/info` return friendly structured responses instead
of 500s. `FIRST_RUN.md` documents the one-time step. The r8 keep/removal list
is unchanged; `prune.KEEP` gained `lib/pes17_setup.py` and `FIRST_RUN.md`.
