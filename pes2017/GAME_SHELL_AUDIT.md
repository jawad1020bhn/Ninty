# Game Shell V2 — screen and integration audit

This is the initial audit and shell/navigation milestone. The later player/club
redesign, board/focus model and full tools-page shell are deliberately deferred
until the requested screenshot review.

## Existing application

- `/` serves the Classic `static/index.html`; `/pes17.html` is the existing
  PES 2017 tools page. The shell is an additive layer on the Classic app, not
  a new landing page or a replacement for its router.
- The actual pc414 build contains **33** `section.panel` screens and matching
  `#nav button[data-p]` targets, not the 27 in the proposal. Several entries
  are intentionally hidden in the old navigation. `transfers` is an existing
  alias for the transfer-list tab of `signings`; `story` redirects to the
  dressing-room section of `news`. Neither is a separate replacement page.
- `show()` and its existing wrappers perform page loads, select the current
  panel and update the hash. The shell uses the original `data-p` buttons and
  listens for navigation changes; it does not replace or wrap `show()`.
- Native dialogs are already present for setup, player details, news, search
  and other workflows. They remain the app's dialogs, not automatically
  converted cards. Search and notifications already live in `#tbar`.
- The existing sprite is `/hud-icons.svg#hud-<name>`. `__gi_...__` are text
  tokens, not sprite IDs; there is no `ric` sprite in this build.
- At 1366×768 with the real test career, the baseline Signings screen had
  `document.scrollingElement.scrollHeight = 1084` versus `innerHeight = 768`.
  Inbox and League also exceeded the viewport. The app's left rail already
  has its own scroll area, and some lists have separate internal scrollers.

## Complete section map

Only real `data-p` targets and real panels are included; labels come from the
existing navigation. Hidden entries remain reachable through the shell.

| Section | Existing screens |
|---|---|
| Home | home |
| Squad | squad, kit, growth, youth, players |
| Transfers | signings, transfers (existing alias), shortlist, sales, loans, aimoves, deadline |
| Competitions | league, clubs, honours, records, history, stats, awards |
| Media | news, press, rumours, journal, story, fans, stories |
| Office / Board | board, inbox, assistant, talks, calendar, review |

The league selector in the original league sub-navigation is a real control,
not just navigation, and must stay available. The Signings screen already has
its own Scouting tab. The original save bar, dirty indicator, career selector,
settings and tools link are retained rather than recreated.

## Guardrails for the first milestone

- Desktop uses a locked window with an independently scrolling screen pane;
  long content must remain reachable rather than being clipped. Existing
  list-level scrollers are not blindly rewritten.
- Full shell above 1024 CSS pixels with a compact-height variant; small
  screens fall back to the existing mobile layout. `100vh` precedes `100dvh`.
- A persistent Look & sound switch removes `body.game-shell`; the original
  app layout and navigation remain in place when it is off. The first-run
  tour temporarily uses Classic, because it anchors to the original nav;
  the shell activates after the tour is finished or skipped. If the native
  tour never starts and its own retry window expires, the shell can activate
  without waiting forever.
- Primary and secondary navigation use existing labels and route through the
  app's buttons. Only the shell's own navigation handles arrow keys; inputs,
  selects, the pitch, native dialogs and existing shortcuts are left alone.
- The tools page receives the local asset links but retains its existing
  layout and dry-run/guard behavior until its dedicated phase.

## Repeatable verification

Build normally, run `python3 -m unittest discover -s pes2017/tests`, and serve
an extracted build configured against **copies** of the save files. The
optional `tests/game_shell_browser.cjs` exercises all 33 navigation targets,
internal scrolling, the real League picker, keyboard/search, dirty/revert,
the persistent switch, mobile fallback and tools-page isolation. It requires
an externally installed Playwright Core and Chromium for tests only; neither
is a runtime dependency. For example:

```sh
GAME_SHELL_URL=http://127.0.0.1:7861/ \
CHROMIUM_PATH=/path/to/chromium \
NODE_PATH=/path/to/test/node_modules \
node pes2017/tests/game_shell_browser.cjs
```

The preview used for review blocks owner-only operations and reads copied
sample saves; production LAN protections and save-writing code are unchanged.
