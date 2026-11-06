THE GAFFER
Companion app for Football Life 26 / PES 2021 and Football Life 2027 Master League
=============================================================

IN SHORT
--------
Football Manager style career on top of your Master League save:
- Real negotiations: transfers, loans, sales, renewals, agents.
- A living world: AI transfers, managers, tactics, sackings.
- Board, press, dressing room, fans, newspaper, awards.
- Training, youth, scouting, sponsors on your real kit.
Everything the game needs is written into your save (with a backup if you
want one).

PUBLIC TEST: thank you for testing! Back up your saves, and send problems
with "Report a problem" (left column). What's new and known limits are at
the end.

The Gaffer is FREE. Download it only from the official Evoweb thread.
Please do not reupload it or put it in other packs (see FREE TO USE at the
end).


WHAT YOU NEED
-------------
- Windows 10 or 11.
- PES 2021 with Football Life 26 (or Football Life 2027) and Sider.
  Sider comes with Football Life; you do not need to install it separately.
- About 200 MB of free disk space (more if you keep many save backups).
- Internet is optional. Crests, kits, faces and logos come from your
  game. Only extras (stadium photos, real player careers, photos of
  players who have no face in the game) come from Wikipedia. Without
  internet the app works the same, just with fewer extras.
- Nothing else. The folder already contains a portable Python, and save
  encryption is built into the app (no extra tools needed).


BEFORE YOU START: BACK UP YOUR SAVES
------------------------------------
The app writes into your Master League save. Before the first start, copy
your whole save folder somewhere safe, for example to your Desktop:
  FL26 / PES 2021:  Documents\KONAMI\eFootball PES 2021 SEASON UPDATE\<number>\save
  FL27:             Documents\SPGAME\Football Life\2027\save
If anything ever goes wrong, close the game and copy this folder back.


INSTALL (about 5 minutes)
-------------------------
1. Unzip the zip. You get a folder called "TheGaffer". Put it anywhere,
   for example in Documents. Do not run the app from inside the zip.

2. Double-click "The Gaffer.vbs".
   - The app opens in its own window.
   - The first start creates a "The Gaffer" shortcut on your Desktop.
     From then on, start the app with that shortcut.
   - If Windows says "Windows protected your PC": click "More info",
     then "Run anyway". The app is not signed, that is all.
   - If nothing opens after 30 seconds, double-click "The Gaffer.bat".
     A black window shows what went wrong, or offers to install Python.

3. The Setup window opens on its own the first time. Go from top to bottom:
   a) Paths. The app looks for your save folder, Sider and the game by
      itself. Check that the three paths are right and click "Save paths".
   b) Sider modules. Click "Install modules", then restart the game.
      These two small modules let the game send your players' data to the
      app (PlayerDump) and let the app's training reach the game
      (GrowthBridge). PlayerDump only reads; GrowthBridge only adds the
      training progress the app calculated.
   c) Regen fix (optional, recommended). Click "Install regen fix" and
      restart the game. Regens then become real new players (new name,
      potential and face) instead of copies of retired players.
   d) Backups. Choose how many copies of each save the app keeps before it
      writes (Off, 1, 3 or 15). 3 is a good choice.
   You can open Setup again at any time (left column, "Setup").

4. In the left column, pick your career (Career / slot) and you are ready.
   The Home page shows a "Getting started" checklist until everything is
   connected.


EVERYDAY USE - THE ONE RULE TO REMEMBER
--------------------------------------
The app READS your save whenever the game saves. That is always safe.

When the app WRITES to your save (signings, sales, loans, contracts,
line-up, tactics, sponsors, AI transfers), the game must not be inside
Master League, otherwise the game overwrites the app's change. So:
  1. Save in the game.
  2. Go back to the game's MAIN MENU (leave Master League).
  3. In the app, click "I am on the main menu" (or close the game).
  4. Do what you want in the app. It writes and tells you when it is done.
  5. In the game, choose "Load" and load your Master League again.
If you forget, the app shows a red banner and waits; nothing is lost.

Good to know:
- Switching between the game and the app: press Ctrl+F8 on the keyboard,
  or hold Back + Start on the controller for half a second (Xbox: View +
  Menu, PlayStation: Share + Options). Do the same in the app to jump back
  to the game. Works best with the game in Borderless or Windowed mode.
- Transfers and loans arrive in the game after you play or simulate ONE
  day.
- The first time you sign a player, the app asks for your Salary Budget:
  type the number the game shows at the top of the Master League screens.
- Player data (attributes, OVR, morale, form, youth) refreshes by itself
  before every match. Want fresh data without a match? In the game press
  Space, press 1 until "PlayerDump" appears, then press F7.
- Training runs by itself: every 30 game days the app processes a month
  of training and sends it to the game before your next match. Save after
  that match so the progress stays.
- If the app says the Sider modules are out of date, click "Update
  modules" on the Home page and restart the game.


PHONE AND TABLET
----------------
You can use The Gaffer on your phone or tablet while the game runs on the
PC, for example from the couch with the controller in your hand.
  1. On the PC, open Setup, go to "Phone & tablet" and click
     "Turn on phone access".
  2. Connect the phone to the same Wi-Fi as the PC.
  3. Scan the QR code with the phone camera (or type the address shown).
  4. Enter the 6-digit PIN from Setup. The phone remembers it.
Everything works like on the PC: writes still go into the save on the PC,
and the same main-menu rule applies. Setup, the package and closing the
app can only be done on the PC. "New PIN" signs out every device.
If the page does not open, Windows has probably asked whether Python may
use the network: allow it on Private networks.

SAFETY
------
- The app keeps a copy of your save before every write if Backups is not
  "Off" (folder work\backup inside the app folder). Only the newest
  copies are kept; older ones are deleted on their own.
- The app only writes to save formats it knows. With an unknown save it
  only reads.
- The Sider modules never touch your save files.


IF SOMETHING GOES WRONG
-----------------------
- Click "Report a problem" (left column), write what happened and click
  "Create report". A folder opens with a zip file: send that zip to the
  person who gave you the app. It contains your save, a check of the save
  and the app's settings and logs (no passwords).
- To undo the app's last write: close the game, open work\backup inside
  the app folder, take the newest copy of your save (its name starts
  with your slot, for example ML00000003_...), rename it to the slot name
  (for example ML00000003) and copy it over the one in your save folder.
- The app does not open: start "The Gaffer.bat" to see the error.
- The game crashes after the app wrote something: restore your save as
  above and send a report.


UPDATING AND UNINSTALLING
-------------------------
- Update: unzip the new version over the old "TheGaffer" folder and
  allow Windows to replace the files. Your careers and settings stay.
- Uninstall: delete the "TheGaffer" folder and the Desktop shortcut. Your
  saves stay as they are. The Sider modules can stay in the game; without
  the app they have nothing to do.


FEATURES
--------
The Gaffer turns Master League into a Football Manager style career. The
things marked [writes] are saved into your Master League save, so you see
them in the game. Everything else lives in the app next to your career.

Your club
- Home: next match, league table, form, transfer window, notifications
  and a short "today" summary of what is happening at your club.
- Inbox: messages from players, agents, the board and other clubs:
  expiring contracts, offers, requests, injuries, news about your club.
- Assistant manager: advice on your squad, what is missing (positions,
  depth, quality, age) and what to do next.
- Squad & tactics [writes]: starting XI, bench, shirt numbers, formations
  (kick-off, in possession, out of possession) and team instructions.
- Player profiles: attributes, positions, form, contract, value, season
  and career stats, similar players, and a radar of his strengths.
- Training [writes, live]: individual training focus. With the
  GrowthBridge Sider module, training is applied to the game while you play.
- Youth academy: your youth players and regens with estimated OVR and
  potential, and new regens since your last save.

Transfers
- Search the whole world database with filters (league, club, position,
  age, OVR, value, attributes), plus a shortlist.
- Transfer negotiations [writes]: talk to the club (fee, add-ons such as
  appearance bonus and sell-on clause), then the player (wage, years, role,
  release clause, appearance/goal/win bonuses), then the agent fee and the
  medical. Clubs and players have moods, can counter, stall, walk away or
  pick a rival offer, and replies take game days. The deal is written on
  a "paper contract" with both club crests and signatures.
- Loans in [writes]: plain loans and loans with an option to buy (buy
  price and future wage are written into the game's own loan contract).
- Selling players [writes]: clubs send offers for your players. Haggle
  over the fee, let them wait, claim a rival bid or leak it to the press,
  agree the player's bonus, add your own sell-on, then confirm the sale.
- Loans out [writes]: send players out on loan.
- Contract renewals [writes]: negotiate new wage and length with your
  own players. Unhappy players and agents put pressure on you.
- Free agents and scouting: hire scouts (paid from the transfer budget),
  send them to leagues or countries, get scouting reports and free agents.
- Deadline day: the last days of the window with late offers, the
  latest deals and the biggest spenders.
- Salary Budget check, so the game never cancels a deal on arrival day.

A living football world
- AI transfers [writes]: other clubs buy, sell and loan players between
  themselves during the transfer windows, so the world changes every season.
- AI managers and tactics [writes]: every club gets its own playing style
  and line-ups. A new manager brings his own formation, and the club then
  buys players who fit it. Clubs short of players switch formation for
  one match. Managers get sacked and hired. If you are sacked or move
  to a new club, the app follows you and keeps your career history.
- Player history: no quick return to the club a player just left; older
  players sometimes go home to the club where they grew up.
- End-of-season revaluation for the whole world: players who score and
  play well become more expensive.
- Other clubs: squads, managers and transfer activity of every club.
- Competitions: league tables, cup groups and the new Champions League /
  Europa League format, with results, fixtures, top scorers and assists.
- Calendar: fixtures, transfer windows and club events.
- Match debrief and opponent analysis before and after each match.

Board, media and dressing room
- Board: season objective, board confidence over time, your reputation
  and your career history. Miss the target and your job is at risk.
- Press conferences and interviews: answer questions in your own words.
  Your answers affect players, fans and the board.
- Dressing room: talk to your players (praise, warn, promise minutes),
  handle transfer requests and unhappy players.
- Fans & atmosphere: how the fans feel about results, signings and sales.
- News, rumours and the club journal: stories about your season,
  transfer rumours and newspaper pages.
- Awards and records: Team of the Week, monthly awards, Ballon d'Or,
  honours and club records.

Finances and sponsors
- Board & finances: monthly report, club account and Budget Settings
  (which budget receives gate, prize money, etc.) [writes].
- Kit sponsors on chest, sleeve and back with real contracts, exit fees
  and a relegation clause. Add your own sponsors with a logo. The logo is
  drawn on your real kit in the game (needs the Sider kit-server).

Tools
- Several careers and save folders: switch between Master League slots
  (and between Football Life and PES 2021 save folders). Each career keeps
  its own app data.
- Import database: match the app to your game's player database (new
  patch, new leagues) from the F7 dump.
- Regen fix (by mataodzanata): regens become real new players.
- Club colours and a retro PES theme for the whole app.


WHAT'S NEW IN THIS UPDATE (since pc378)
---------------------------------------
You can keep your career: unzip this version over your old TheGaffer
folder and allow Windows to replace the files. Careers and settings stay,
no new career needed. Then click "Update modules" on the Home screen
(or Setup > Install modules) and restart the game once.

No more "I'm on the main menu" click
- The app now knows by itself whether the game is in Master League or on
  the main menu. Saving from the app unlocks a few seconds after you leave
  Master League and locks again as soon as you load your career. The bar
  at the top says which one it is. It only reads (nothing is written to
  the game). It needs the updated GrowthBridge module ("Update modules").
  If the app can't tell (another game version), the old button works as
  before. Turn it off in config.json with "auto_menu": false.
  Idea and memory address found by a tester.

Football Life 2027
- More save layouts can be written to: saves with the Carabao Cup mod and
  saves with Classic Teams on (thanks to the FL27 testers for the layout
  work). Reading always worked; writing is now unlocked too.
- Long careers: writing was refused after many club responses (a safety
  check on a counter was too strict). Fixed.
- Player faces come from the game files (FL27 keeps them inside its own
  archives).
- Sponsors on your kit work on FL27 (see Kits below).

Kits and sponsors
- Sponsors on your kit no longer need a Sider kit-server. If your club
  has no kit-server entry (all FL27 clubs, and FL26 clubs whose kits come
  from the game or a kit pack), the app copies your real kits, puts the
  sponsor on the copies and the game loads them through livecpk. Only the
  kit texture changes: the cut, collar, numbers and colours stay exactly
  as in the game, and your original files are never touched ("Restore
  original kits" removes the copies). On FL26 the app adds its own folder
  (livecpk\TheGaffer_kits) at the top of sider.ini the first time, so
  restart the game once. A kit-server setup is still the better option if
  you have one: the app then uses your kit-server kits directly.
- The old sponsor is removed more cleanly: the app patches it with a part
  of the shirt where the pattern lines up, or smooths it over (no more
  half-circles or dark patches on patterned kits). The logo also sits a
  little lower so it never shows inside a deep V-neck.
- Fixed "bytes must be in range" when putting a sponsor on some kits.
- The app no longer mistakes other Sider folders (like SleeveBadge) for
  the kit-server.

Transfer market
- AI transfers: new "Activity" setting (Normal / Low, about half the
  moves) and "Skip the first transfer window" for databases already
  updated to the end of the real September window.
- Clubs no longer pay more for one player than fits their class (no more
  mid-table clubs spending 45 million on one signing).
- Real transfers from Wikipedia: players who actually joined their club
  this summer don't get sold on or flooded with offers right away. The
  list now comes with the download (no internet needed at first start)
  and covers more leagues and the 2026 windows.
- Offers for your players: "Reject" on every offer, and "Not for sale"
  (no more offers for that player until you put him on the list).
- Offers now also arrive in the two weeks before a window opens (from
  mid-December and mid-June); the deal itself is done once the window is
  open, as in real life.

Board, leagues and competitions
- Board confidence: the new-manager honeymoon is shorter, and confidence
  no longer goes up while your results are poor.
- South American, Asian and North American leagues: the table and the
  season objective use their own competitions (Copa Libertadores and
  Sudamericana, AFC Champions League, CONCACAF Champions Cup) instead of
  "Europe".
- Expanded databases (FL Mod Studio): the league names you set in
  "Import database" now also decide the country a league is listed under
  (Austrian Premier League no longer under Albania, and so on).
- Stadium attendance uses the real stadium capacity.

Squad and tactics
- 45 MB "new save layout" (Michele's UML): lineup, formation, team
  instructions and shirt numbers can be changed in the app (measured in
  the game by Michele).
- OVR from FL Mod Studio databases above 99 is shown as the game shows it.
- A negative Salary Budget (as the game sometimes shows) can be entered.

Fixes and small things
- PlayerDump (F7) now shows the real result in the Sider overlay: "DONE:
  ... players written" or "FAILED: ..." with the reason (before, a
  technical line "step C: ok=true" hid it).
- Lite mode for slower PCs and handhelds (ROG Ally and similar): fewer
  effects, smoother pages. Switches on by itself when the device is slow.
- If an old copy of The Gaffer got stuck in the background ("Failed to
  fetch"), starting the app again closes it by itself.
- The page is no longer auto-translated by the browser (that broke
  numbers and names).
- Linux (Wine/Proton): the app detects when the game is running.
- Dates written with dots or dashes are read correctly.
- No more false "contract rows" warnings after a transfer.


KNOWN LIMITS (PUBLIC TEST)
--------------------------
- "Stop the game on a day" is switched off for now (it crashed the game
  when the stop fell on a match day).

CREDITS
-------
- Regen fix: mataodzanata (FL Mod Studio), included with his permission.
- Michele & Claude: Economia Lunga revaluation, Injuries For All and
  many ideas and tests, included with their permission.
- Main menu detection (no more "I'm on the main menu" click): idea, memory
  address and timing rules from our FL27 tester on Linux, thank you!
- FL27 save layouts (1600-slot table, Carabao Cup, Classic Teams): the
  FL27 testers' layout work and saves.
- Save encryption: built in, based on pesXdecrypter (public domain).
- Football Life 26 belongs to its authors. The Gaffer is a free fan-made
  companion and is not affiliated with Konami.


FREE TO USE
-----------
The Gaffer is free, and it will stay free.
- Use it as much as you like for your own Master League careers.
- The only official download is the official The Gaffer thread on Evoweb.
  Copies from anywhere else may be old, changed or unsafe.
- Please do not reupload The Gaffer, sell it, or include it in other packs,
  patches or tools without the author's permission.
- Please do not publish changed versions of it as your own work.
- Screenshots, videos and streams are welcome. A link to the official
  thread is appreciated.
- The included Sider modules (the regen fix and Michele's modules) belong
  to their authors and follow their rules.
- The Gaffer is provided as it is, without any warranty. Keep backups of
  your saves.
Want to share it, build on it or include it somewhere? Just ask in the
official thread.
