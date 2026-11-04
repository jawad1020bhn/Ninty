# First run on Windows — choose your PES 2017 save folder

**Build `pc414-pes17-clean-r9`.** Unzip this program anywhere (not inside the
zip), then run `The Gaffer.vbs`. Open `http://localhost:8766/` — the PES 2017
dashboard is the landing page.

## The one thing you must do

The original pc414 program shipped a hard-coded save path for *Football Life
2026 / PES 2021*:

```
%USERPROFILE%\OneDrive\Dokumenti\KONAMI\eFootball PES 2021 SEASON UPDATE\2026\save
```

If that folder is missing (it is, on a PES 2017 PC), older builds printed raw
errors like `[Errno 2] No such file or directory` or
`[WinError 3] Le chemin d'accès spécifié est introuvable` in the dashboard.
**r9 removes that default.** On first run the app now:

1. looks for a real `KONAMI\Pro Evolution Soccer 2017\save` folder under your
   profile, `Documents` and OneDrive (including localised names such as
   `Dokumenti`), and uses it automatically if it contains `ML*` saves;
2. otherwise shows a **Save folder** card at the top of the dashboard instead
   of raw Windows errors.

Paste the full path into that card and press **Save folder**. It is written to
`config.json` next to the program and takes effect immediately — no restart
needed. Typical paths:

```
C:\Users\<you>\Documents\KONAMI\Pro Evolution Soccer 2017\save
C:\Users\<you>\OneDrive\Dokumenti\KONAMI\Pro Evolution Soccer 2017\save
D:\...\KONAMI\Pro Evolution Soccer 2017\save
```

The folder must contain your Master League file (`ML00000011` or similar) and,
for real player names, `EDIT00000000`. The app **reads** these files; it never
changes the game or patch folder.

You can also use the classic Setup (`Classic app ↗` → Setup → Save folder). Both
write the same `config.json` key. `config_pes2017.example.json` shows every
option; rename it to `config.json` only if you want to set things by hand.

## What the other cards mean on a fresh install

| Card | Expected before setup | Meaning |
|---|---|---|
| Save slot / budget / squad / league table | "Save folder not set" | Fix the path above; all four then read from your real save. |
| Club crests from your patch folder | `0 logos / 0 clubs` | **Optional.** Only needed if you have loose logos or a `livecpk`/CPK patch. Set `pes17_patch_dir` in Tools → card 3c. |
| CPK asset inventory | `0 entries / 0 archives` | **Optional.** Point `pes17_patch_dir` at a folder holding PES 2021 CPK files, then Refresh. No real `.cpk` ships with this build. |

Nothing here needs internet. Wikipedia, Google Fonts and flag CDNs are off by
default. `pes17_patch_dir` and `pes_exe` are only for artwork/auto-detection.

## Safety, unchanged

* Budget is shown as a **RAW u32 save value**, not confirmed EUR.
* FL26-style writes stay blocked; only measured PES 2017 writes (formation,
  tactics, XI, budget, shirts, offers) are available, dry-run first, with a
  layout guard and timestamped backups.
* `pes17_allow_writes` stays `false`, `auto_menu` `false`, LAN off, `sider` empty.
* **Still not proven:** loading a written save in PES 2017 on Windows, the
  in-game currency scale, and the save header hash. Keep a backup and report
  what the game shows.
