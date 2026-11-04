# MATCHDAY UI — r10 UI refresh (on top of the r9 build)

The PES 2017 adaptation build is still `pc414-pes17-clean-r9 (2026-11-04)`.
This is a **visual/navigation overlay revision** of the shipped static files;
no save format, write path, endpoint or safety rule changed. The HUD strip
reads `MATCHDAY · R10` so the UI revision is visible in the running app.

## What changed

### 1. Icon system — no emoji, no generic Badge
- `overlay/static/game-skin.js` now ships **108 dedicated SVG symbols** on one
  24×24 grid with one stroke weight (1.65) and one size (1.08em).
- Added purpose-specific icons: `formation`, `tactics`, `training`, `contract`,
  `transfer`, `injury`, `finance`, `competition`, `news`, `scout`, `youth`,
  `player`, `staff`, `manager`, `bench`, `substitute`, `medal`, `crown`, `pace`,
  `status`, `rating`, `menu`, `bell`, `undo`, `refresh`, `weather`, `defence`,
  `press`, `match`, `table`, `form`, `quick`, `stats`, `whistle`, `book`,
  `happy`, `sad`, `angry`, `calm`.
- The old `badge` catch-all is **gone**. Previously dozens of unrelated glyphs
  (`🧩`, `🧬`, `⚖`, `🅰`, `🧾`, `🪑`, …) all became the same badge/star. Each
  now has its own icon. `USE` of `badge` in the map dropped from many entries
  to **0**, `star` to 5 genuinely star-shaped glyphs.
- **Unknown glyph → `null`**: `iconId()` no longer invents an icon. The glyph
  is kept as text inside an accessible `.gi-sr` span (so `textContent`, search,
  screen readers and the CLASSIC UI toggle are unchanged) but nothing false is
  drawn. All 177 keys needed by the original `index.html` and `pes17.html` are
  still explicitly mapped — 100% glyph coverage is enforced by
  `tests/test_game_skin.py`.
- Text labels stay next to icons everywhere; the skin never deletes copy.

### 2. Visual identity
- `overlay/static/game-skin.css` is now **Stadium Dark / Deep Navy**
  (`--bg:#070d16`), with a single `--club` accent. The cyan `#38d9ff` glow,
  CRT scanline overlay, grid background, corner decorations and neon button
  gradients are removed.
- `CLUB` theme reads the user's club colour from the local `/api/clubcolors`
  endpoint (offline; falls back to gold). `GOLD` and `PITCH` are fixed
  fallbacks. No external fonts, images or CDN — the font stack is system-only.
- The stadium/pitch artwork is pure CSS (gradients), no bundled assets.

### 3. Navigation / console feel
- New sticky **console top bar**: brand, six sections (HOME / SQUAD /
  TRANSFERS / COMPETITIONS / MEDIA / OFFICE), each with a subsection bar.
  Active section and active page are both clearly marked.
- The long sidebar `#nav` is hidden on desktop (the app's own grouped subtabs
  are restyled as quiet chips and the Scouting action is kept in the
  TRANSFERS subbar). Slot/setup/look controls stay reachable in the slim
  sidebar.
- **Quick Switcher**: visible `CTRL K` button hooks into the app's existing
  Ctrl+K command palette; `/` also opens it.
- Keyboard: `Alt+1…6` jump to sections, `←/→` move between tabs, `↑/↓` rove
  the squad list with an explicit Selected state, `Esc` closes the drawer.
- Clicking a section uses the app's own `#nav` button handler, so every
  per-page loader still runs. `pes17_only` / FL26 pages are untouched.

### 4. Home screen
- `overlay/static/pes17-dashboard.html` is rebuilt as a **MATCHDAY home**:
  full-width hero with club crest, league, in-game date, derived season,
  face-off panel, four tactical tiles (league position, squad size, RAW
  budget, next fixture), a visual standings rail, player cards, manager
  decisions, club news and club info.
- **Honest data**: league position and club/league/date come from the real
  PES 2017 save. `next_competition` comes from `description.dat`. Fixture,
  recent results, news, stadium, manager name, OVR/Form/Fitness/Morale and
  player photos are **not** in the measured PES 2017 read layer, so the UI
  labels them as unavailable instead of inventing values.
- All r9 first-run controls are preserved verbatim: `setupCard`, `saveDir`,
  `saveDirBtn`, `setupBtn`, `buildVer`, `/api/pes17/setup`,
  `/api/pes17/setup/savefolder`, `friendly()`, Arabic toggle, crest/CPK
  cards and harvest action.

### 5. Squad & Tactics / cards
- Bigger tactical pitch column (620px), framed pitch with a soft stadium
  vignette, animated spot transitions, horizontal **bench strip**, roster rows
  restyled as compact player cards with a rating chip, clear hover / focus /
  Selected / Disabled states.
- Player/transfer dialogs get a game-profile frame. `.squad` rows and bench
  items get roving selection and press animation.

### 6. Game feel
- Screen-transition animation on panels, selection pulse, press feedback,
  football-style toast notifications, boot intro (restyled, no glow),
  **optional** WebAudio menu blips (OFF by default, toggle in the HUD strip),
  loading shimmer on the home screen, `prefers-reduced-motion` support.
- `window.gafferToast(msg)` is exposed for other UI code.

### 7. Mobile
- Bottom 5-tab navigation, off-canvas sidebar drawer via the `☰` button,
  per-screen responsive layout, larger touch targets (≥36px), compact
  tile/player grids, and dense tables collapsed into a `<details>` "full
  squad list" on the home screen.

## Not implemented (and why)

- **Real player photos / cinematic backgrounds**: no real CPK, player-face,
  stadium or club image assets exist in this workspace, and the build is
  offline by default with no CDN. The app's optional crest/asset harvester can
  supply crests from the user's patch folder, but there are no bundled photos.
- **Fixture, results, news feeds, OVR/Form/Fitness/Morale**: not measured in
  the PES 2017 save read layer. Showing numbers would be fabricated.
- **Gamepad polling**: only keyboard/arrow roving focus is implemented.
- **Real in-game sound assets**: the optional blips are synthesised with
  WebAudio; no audio files ship.
- **In-game validation**: unchanged from r9. No Windows run, no written save
  loaded in PES 2017, no budget-scale or header-hash confirmation. Passing
  unit tests / HTTP sweeps is not game acceptance.
- No FL26 UI or endpoint was deleted; `pes17_only:false` still restores the
  classic app. Measured-only writes, dry-run/backups, layout guard and the
  offline defaults are unchanged.

## Verification

- `python3 -m unittest discover -s pes2017/tests` with
  `GAFFER_ORIGINAL_ZIP` / `GAFFER_BUILT_HTML` pointing at the recovered pc414
  zip and built tree (glyph-coverage and hook checks no longer skip).
- `node --check` on `game-skin.js` and on the dashboard's inline script.
- `tools/verify_pairs.py` unchanged (no save-writing code touched).
- Full HTTP smoke on a fresh unzip of the rebuilt zip, plus the 133-GET
  differential sweep against the r8 baseline.
