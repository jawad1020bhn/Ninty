# Real PES 2017 save report — t99p17v20 (four measured save pairs)

**Input (supplied by the user on `main`)**

| file | bytes | SHA-256 (first 16) |
|---|---:|---|
| `Needed files/ML00000011` | 13,342,176 | `41202a9196d84116` |
| `Needed files/EDIT00000000` | 5,303,749 | — |
| `Needed files/info.txt` | 87 | `patch name: t99p17v20`, `game folder path: D:\jawedfolder\Games\Pro Evolution Soccer 2017` |
| `Needed files/cheat engine variations.CT` | 38,029 | Cheat Engine live-RAM player table |
| `formation/after/ML00000011` | 13,342,176 | `61a26eaa293fe57d0` |
| `tactics/after/ML00000011` | 13,342,176 | `7a0455b2446f4d8c5` |
| `xi/after/ML00000011` | 13,342,176 | `680d23b30488eea31` |
| `budget/after/ML00000011` | 13,342,176 | `237f51a3ed8916448` |

The four after files were generated in-game with ONE change each; the common
`before` is the original `ML00000011`. No `PES2017.exe`, no Windows runtime and
no in-game load test were provided. Everything below was measured from these
files. Sections 1–4b predate the pairs; section 4c uses them.

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
| formation records | `1256248` | 33 B records × 3; 17 bytes changed by the formation pair |
| tactics block | `1256348` | 15 B; 13 bytes changed by the tactics pair |
| XI / squad order | `1256728` | 26 B permutation of squad slots 0..25 (+ 42 B order block) |
| XI float sliders | `2230192` | 24 B (6 × f32), changed by the XI pair |
| budget u32 | `8812904` | `2535240 → 3088641` in the budget pair |
| wage budget u32 | `8812936` | `9689272 → 10247281` in the budget pair |
| budget companion bytes | `9836708 … 9845147` | 15 more bytes changed by the budget pair |

**Team id mapping:** `cid >> 14` gives the stable PES Team ID used by
standings, EDIT league arrays and club lookup. Arsenal `1654784 >> 14 = 101`,
Birmingham `3293420 >> 14 = 201`. The buyer field in a negotiation block is
the **raw** `cid`, not the shifted id.

## 4. What now writes (and how it is proven)

`lib/pes17_write.py` implements:

1. `offer_add` / `offer_clear` — MLTE-verified 16-byte slot layout.
2. `shirt` — one byte at club+512.
3. `squad` — experimental, `experimental=true` required.
4. `pair` / `formation` / `tactics` / `xi` / `budget` — four tables measured
   from the user's real before/after save pairs (section 4c).
5. `raw` — u32 escape hatch for user-measured offsets.

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

## 4c. Four real before/after save pairs (formation, tactics, XI, budget)

The user uploaded four game-generated `after` saves on `main`
(`formation/after/ML00000011`, `tactics/after/ML00000011`,
`xi/after/ML00000011`, `budget/after/ML00000011`, 13,342,176 B each) and said
the common `before` is the original `Needed files/ML00000011`.

Method: decrypt each with `KEY_PES17` / 176 B header, byte-diff `data.dat`
(13,304,607 B) against the common before file, then subtract the bytes that
changed in ALL FOUR saves.

* **211 bytes changed in every save:** a 32-byte per-save token at
  `data.dat[48:80]` (different in each after file), a stable 170-byte
  save-state delta, and two UI-state u32 words (`2210056`, `8361492`).
  These are NOT action tables and are never written.
* **Action-specific bytes** (only one pair each): formation 17, tactics 13,
  XI 30, budget 21.  These are the tables PES 2017 itself writes for that
  action; they are now allow-listed in `lib/pes17_pairs.py`.
* Every other part (`description.dat`, `logo.png`, `version.txt`) is identical.
  `header.dat[80:144]` (64-byte hash) and `encryptHeader.dat[128:256]` change
  on every save; the hash algorithm is unknown (SHA-512/MD5/HMAC attempts on
  all part combinations failed).  We keep the original hash, exactly as MLTE's
  `SaveDecryptor.Encrypt` does.

`pes2017/tools/verify_pairs.py` proves the patches: applied to the common
before file, each `pair` op reproduces every action-specific byte exactly and
changes no other byte. Result: **PASS** for all four
(`offsets_match: true`, `bytes_reproduced: true`, `no_extra_changes: true`).
`pes2017/tools/diff_saves.py` diffs two encrypted saves directly for future
pairs.

Interpretation of the tables:

* Formation record 0 at `1256248` is 33 B: fixed prefix `00 01 01 01`,
  then role/position bytes and 11 (x,y) coordinate pairs. The pair moved those
  coordinates (e.g. `1a 44 1a 24` → `15 34 1b 44`).
* Tactics at `1256348`: six flag bytes + seven style bytes changed
  (`07 13 00 00 ff 87 02` → `03 3c 40 03 00 77 00`).
* XI at `1256728` is a **permutation of 0..25** (26 squad slots). The before
  order `09 0f 04 0c 0d 16 13 11 05 03 06 19 10 12 0a 15 08 18 0b 02 07 17
  14 0e 00 01` became `00 0f 04 0c 17 15 08 12 05 01 19 06 10 11 0a 16 13
  18 0b 02 07 0d 14 0e 09 03`. The XI edit also reset six formation-slider
  floats at `2230192` (1.0/1.75/1.25/4.0/5.0 → 2.0/0.5/0.0…).
* Budget: u32 at `8812904` `2535240 → 3088641`, u32 at `8812936`
  `9689272 → 10247281`, plus 15 companion bytes in four finance records
  (`+3` in three `0x16 → 0x19` bytes, clearing three `01 01` flags). We only
  expose the two u32 words as a value op; the companions are available through
  the exact `pair` op.

**Limits of this measurement:** absolute offsets belong to THIS save; they are
checked against the observed before-bytes before any write, so a different
save is refused. One pair per action means we can reproduce that exact change
and write inside those tables, but we do not have a semantic map of every
possible formation/tactic value. The game's header hash is unchanged; whether
it validates on load is unconfirmed — an in-game test is still required.

## 5. Still impossible with the supplied files

Four before/after pairs were supplied, so formation, tactics, XI and the two
budget u32 words are now measured (section 4c). Still unmapped / blocked:

* arbitrary formation and tactic values outside the four measured tables;
* club instructions, transfer fees, wages (only the measured u32 is writable);
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
| 4 measured pairs reproduce the game's own changed bytes | **proven** (`tools/verify_pairs.py`: PASS × 4) |
| formation / tactics / XI / budget writes re-encrypt cleanly | **proven** (40 tests + HTTP write, 17 B changed) |
| written save loads in PES 2017 and shows the change | **NOT validated** (no Windows/game run) |
| injected offer appears in the user's PES 2017 inbox | **NOT validated** (no Windows/game run) |
| claimed block for the human club | **experimental, NOT validated** |
| all other write features | **blocked** |

To finish: **load a written save in PES 2017 on Windows** and confirm the
change (the `pair` op for `formation` is the easiest test). If the game rejects
it, the unchanged 64-byte header hash is the most likely cause. For the
remaining features supply one before/after `ML00000011` pair per in-game action
(one change per pair). `pes2017/tools/diff_saves.py BEFORE AFTER` maps them.

Upload folders are already prepared at `Needed files/pairs/<name>_before` and
`<name>_after` (11 pairs: formation, xi, tactics, contract, budget, my_offer,
forced_transfer, loan, youth, training, points). `pes2017/tools/prepare_pairs.bat`
creates the same structure locally on Windows; it only makes folders/notes and
never touches a save.

## 6b. Final deliverable (this build)

* `pes2017/dist/TheGaffer_pes2017_pc414.zip` — 30,856,008 B, SHA-256
  `78f08e0bd517f1ca181416e8618fea2618e2aa5ba9c05dfeec27460ee277b7de`,
  287 entries, 0 `__pycache__`, `VERSION.txt`
  `pc414-pes17-measuredpairs (2026-11-04)`.
* New in the zip: `lib/pes17_pairs.py`, updated `lib/pes17_write.py`,
  `lib/pes17.py`, `lib/pes17_layout.py`, `static/pes17.html` (section 3b),
  `README_PES2017.txt`.
* 40 unit tests OK. `tools/verify_pairs.py` PASS × 4. Non-dry HTTP
  `/api/pes17/write` with `{"op":"pair","name":"formation"}` returned 200,
  17 bytes changed, backup created. Final restarted server on port 8767 was
  swept with GETs (200) and dry writes only, so the smoke save is pristine
  (`41202a9196d84116`).
* The four 13 MB after saves are left on `main`; `tools/fetch_after_pairs.py`
  stages them into the gitignored `build/pairs/` for verification.

## 7. Sources

* `the4chancup/pesXdecrypter` — `src/masterkey.c`, `src/crypt.c` (`struct FileHeader` = 176 B for PES 2016–2017).
* `irvantaufik28/PES2017-Master-League-Transfer-Engine` — `docs/TEAM_ID_MAPPING.md`, `TRANSFER_OFFER_OFFSETS.md`, `TRANSFER_OFFER_BINARY.md`, `ROUND_TRIP_VALIDATION.md`, `INGAME_VALIDATION.md`, `GEMINI.md`, `src/MLTE.Parser/**`.
* Rigged Wiki — PES 2017 Edit file bitfields.
* The user's own `Needed files/*` — every measurement in sections 1–4b.
* The user's four game-generated after saves on `main` (`formation/after`,
  `tactics/after`, `xi/after`, `budget/after`) — section 4c, `lib/pes17_pairs.py`.
* `Needed files/cheat engine variations.CT` — section 4b, `pes2017/tools/ct_player_table.py`.
