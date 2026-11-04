# Real PES 2017 save report — t99p17v20

**Input (supplied by the user in `Needed files/`, on `main`)**

| file | bytes | SHA-256 (first 16) |
|---|---:|---|
| `ML00000011` | 13,342,176 | `41202a9196d84116` |
| `EDIT00000000` | 5,303,749 | — |
| `info.txt` | 87 | `patch name: t99p17v20`, `game folder path: D:\jawedfolder\Games\Pro Evolution Soccer 2017` |

No `PES2017.exe`, no Windows runtime, no before/after save pairs and no second
save slot were provided. Everything below was measured from these two files.

## 1. Container (the bug that broke the first build)

| | value |
|---|---|
| encryption header | 320 B |
| **file header** | **176 B** (PES 2021/FL26 uses 208 B) |
| master key | `MasterKeyPes17` (pesXdecrypter, public domain) |
| header type string | `ML` / `EDIT` at `+144` |
| ML `data.dat` | 13,304,607 B |
| EDIT `data.dat` | 5,266,180 B |
| `version.txt` | 90 B, UTF-16LE serial `S-1-5-21-...` |
| `description.dat` | 384 B |

`decrypt_bytes()` originally assumed 208 B and therefore **failed on both real
files**. It now tries 208 then 176; `encrypt_parts()` derives the header size
from `header.dat`. Decrypt → re-encrypt is byte-identical for both files
(tested).

## 2. What the real save contains

| field | value | source |
|---|---|---|
| save slot label | `Master League 18` | description.dat |
| club | Birmingham City FC | description.dat / club table |
| league (description) | Premier League | description.dat |
| league (live table) | Sky Bet Championship | EDIT competition name + standings |
| date | `10/01/2029` → `10/1/2029` D/M/YYYY | description.dat |
| next competition | Emirates FA Cup | description.dat |
| clubs in ML table | 624 | club table at 80, stride 1312 |
| EDIT players | 20,018 | player count at `0x5C` |
| squad | 26 players | club +248 |
| shirt numbers | 32 B at club +512 | measured on 3 clubs |
| league table rows | 20 | standings block located via EDIT arrays |
| active negotiations | 0 (16 garbage hits filtered out) | negotiation table |

The description says Premier League but the live standings/EDIT structures put
Birmingham in the Sky Bet Championship (patch quirk — both are reported).

## 3. Measured offsets (all confirmed on `ML00000011`)

| structure | offset | notes |
|---|---:|---|
| club table | `80` | 1312 B records, 64 B name at `+4` |
| club id | `+0` | bit-packed: `(stable team id << 14) \| ML record index` |
| squad slots | `+248` | 32 × 8 B `(roster pointer u32, player id u32)` |
| shirt numbers | `+512` | 32 × 1 B, squad-slot order |
| EDIT competition names | `4333942` | 124 B records, 64 B name |
| EDIT league member arrays | `4782840` | 18 × 80 B (20 × u32) |
| standings root | `8617528` | patch moves the blocks; located dynamically by matching EDIT member arrays |
| negotiation table | `9591148` … `9829596` | 280 B blocks, 852 total, 499 with a real club id |
| negotiation slot | `block + 4 + i*16` | 16 slots × 16 B |
| empty slot | `(6488064, 65535, 0, 1664)` | measured |
| active slot | `(0, source roster ptr, player id, 4210816)` | MLTE published layout |

**Team id mapping:** `cid >> 14` gives the stable PES Team ID used by
standings, EDIT league arrays and club lookup. Arsenal `1654784 >> 14 = 101`,
Birmingham `3293420 >> 14 = 201`. The buyer field in a negotiation block is
the **raw** `cid`, not the shifted id.

## 4. What now writes (and how it is proven)

`lib/pes17_write.py` implements:

1. `offer_add` / `offer_clear` — MLTE-verified 16-byte slot layout.
2. `shirt` — one byte at club+512.
3. `squad` — experimental, `experimental=true` required.
4. `raw` — u32 escape hatch for user-measured offsets.

Safety chain: decrypt → bytearray edit → **every changed byte must lie inside
a measured table** → re-encrypt with the PES 2017 key → decrypt again →
compare all six parts → `.tmp` + `os.replace` → reload from disk → compare →
timestamped backup in `work/backup`. A dry-run mode proves ops without
writing. Bad ops (unknown club, out-of-range offset) write nothing.

End-to-end result on a copy of the real save: `offer_add` for Arsenal (tid
101) + `shirt` for Birmingham changed **9 bytes**, `offers` went 0 → 1,
shirt 2 → 9, the file re-encrypted to exactly 13,342,176 B, and the original
`Needed files/ML00000011` SHA-256 stayed `41202a9196d84116`.

The human-controlled club (Birmingham) has **no** AI negotiation block;
`claim=true` writes its raw id into one of the 353 unused `0xFFFFFFFF`
blocks. That step is a structural inference, **not** in-game validated, and is
flagged `experimental` in the API result.

## 4b. Cheat Engine table (`Needed files/cheat engine variations.CT`)

The user also supplied a 38,029 B Cheat Engine table. Assessment:

* It is a **live process memory** table, not a save-file map: one Auto
  Assembler script (`aobscanmodule(data,PES2017.exe,0F B6 01 8B 4D 0C)`),
  a `data_ptr` symbol, 98 entries with addresses like `+3`, `+b0`, `+c4`
  relative to the selected player's RAM struct, plus absolute symbols
  (`funds=01324B3E`, `data=038278C6`, `data_ptr=08960011`). It contains **no**
  `data.dat` / `ML00000000` / formation / tactics / budget / standings /
  transfer keywords and no file offsets at all (checked).
* What it does give: exact bit positions and meanings for one player's
  attributes, skills, playable positions, COM styles, contract year/month/day,
  affection, form, stamina, team role and nickname, plus a `Comments` section
  with the team-role / nickname value tables. It only works with a matching
  `PES2017.exe` build while the game is running.
* Concrete gain: using its field semantics we located a **232 B-stride ML
  player-record table** in the real `data.dat` at `2,221,628` (Birmingham's
  26 players): `pid u32` at `+0`, `pid` again at `+4`, 46 B name at `+8`.
  With a shift of `-0x30`, the CT contract offsets line up across all 26
  records: year `2029..2032`, month `8`, day `31` — plausible PES contract
  expiries. Reproduce with `pes2017/tools/ct_player_table.py`.
* Limits: other CT fields do **not** align with that shift (affection 149,
  form 96, stamina 228, team role 128 are implausible). So the CT is a
  semantic hint + a way to find the table, not a 1:1 file layout. RAM layout
  is not the encrypted save layout; writing CT offsets straight into the file
  would corrupt it. One before/after pair is still needed to confirm that a
  contract write actually takes effect in-game.
* It does **not** help with club-level tables: formation, XI, tactics,
  budget, forced transfers, loans, standings points. Those still need pairs.

## 5. Still impossible with the supplied files

No before/after pairs ⇒ these cannot be mapped and remain blocked / zero:

* formations, lineup/XI, tactics, club instructions;
* wages, budgets, transfer fees;
* forced transfers, loans, youth players, training/growth;
* points / played / wins / goals in the league table;
* the human club's own inbox negotiations (a separate table).

**Partially mapped by the CT:** contracts / renewals — the player-record table
and its year/month/day fields are located (section 4b), but one before/after
pair is still needed to confirm that writing them changes the game.

All FL26-style write endpoints still raise the read-only message, so the app
cannot corrupt the save with PES 2021 offsets.

## 6. Validation status (honest)

| claim | status |
|---|---|
| PES 2017 master key opens the user's real files | **proven** |
| 176-byte header / byte-identical re-encryption | **proven** |
| club, date, squad, EDIT names, shirt numbers, standings parsing | **proven on real files** |
| negotiation block + slot layout on the real file | **proven structurally + published in-game checklist** |
| CT file = live RAM table, not save-file offsets | **proven** (98 entries, AOB hook, no file offsets) |
| 232 B ML player-record table + contract year/month/day | **located on real files via CT; needs 1 pair to confirm writes** |
| injected offer appears in the user's PES 2017 inbox | **NOT validated** (no Windows/game run) |
| claimed block for the human club | **experimental, NOT validated** |
| all other write features | **blocked** |

To finish: supply one before/after `ML00000011` pair per in-game action (one
change per pair), plus `EDIT00000000`, and (optionally) the game path/exe and
patch version. `lib/pes17_layout.py diff before after` maps the tables.

Upload folders are already prepared at `Needed files/pairs/<name>_before` and
`<name>_after` (11 pairs: formation, xi, tactics, contract, budget, my_offer,
forced_transfer, loan, youth, training, points). `pes2017/tools/prepare_pairs.bat`
creates the same structure locally on Windows; it only makes folders/notes and
never touches a save.

## 7. Sources

* `the4chancup/pesXdecrypter` — `src/masterkey.c`, `src/crypt.c` (`struct FileHeader` = 176 B for PES 2016–2017).
* `irvantaufik28/PES2017-Master-League-Transfer-Engine` — `docs/TEAM_ID_MAPPING.md`, `TRANSFER_OFFER_OFFSETS.md`, `TRANSFER_OFFER_BINARY.md`, `ROUND_TRIP_VALIDATION.md`, `INGAME_VALIDATION.md`, `GEMINI.md`, `src/MLTE.Parser/**`.
* Rigged Wiki — PES 2017 Edit file bitfields.
* The user's own `Needed files/*` — every measurement in sections 1–4.
