# Study: adopting OpenFoot Manager's match engine

Upstream: https://github.com/openfootmanager/openfootmanager
Studied at commit `46b03f21b561381b19170c33328b15692dce4fa1` (develop, 2026-11-04).
Source pulled to `.cache/ofm.tar.gz` (7.0 MB, git-ignored).

**Recommendation: do not vendor or transliterate the code. Rebuild the missing
behaviours in our own engine, using OFM's published model and calibration
targets as the specification.** Two hard blockers and one softer one decide
this, and the measurements below show we need less than it first appears.

---

## 1. What OFM actually is

| | |
|---|---|
| Language | **Rust** (9.55 MB) + TypeScript (5.70 MB) frontend, Tauri shell |
| Licence | **GPL-3.0**, repo-wide; `engine` crate declares no `license` field, so it inherits |
| Engine crate | `src-tauri/crates/engine/` — **8,031 lines src + 7,232 lines tests** |
| Dependencies | **`rand` + `serde` only.** Genuinely standalone, no domain coupling |
| Activity | 5,154 commits, pushed 3 days before this study, 1,184 stars, not archived |

The engine is well built. It defines its own mirror types so it never imports
the game domain, takes an injectable RNG (`simulate_with_rng`) for deterministic
tests, and refuses an empty side up front so every player lookup is total. That
is the same discipline our `lib/engine/` follows.

There are **two** engines, which matters for any comparison:

- **instant** (`engine/`, ~3,106 lines with shared/types/report) — whole match in
  one call, no commands. Upstream now uses this only for its own bench tools.
- **live** (`live_match/` + `ai.rs`, ~4,513 lines) — minute-by-minute, accepts
  substitutions, formation/style/dial changes, set-piece takers, shootout order.
  **Every competitive fixture in OFM goes through this one**, watched or not.

So a fair comparison against our `match.simulate()` is the *live* engine, not
the 2 ms instant one quoted in their docs.

## 2. Blocker one — GPL-3.0 (decisive)

GPL-3.0 is strong copyleft. Copying the crate, or transliterating its Rust into
Python, produces a derivative work: the GPL would attach to our engine and, on
distribution, to the combined work as a whole.

That is normally a choice a project can make. Here it collides with what this
repo already ships:

- The repository is **public** and has **no LICENSE file** at root.
- `data/fc27/` is EA's copyrighted database, redistributed without a licence from
  the rights holder (recorded in `data/fc27/NOTICE.txt` and README's LICENSING
  section). We cannot place it under GPL-3.0, because we hold no rights to
  sublicense it. Asserting a licence over it would be a false claim.
- Crests are already git-ignored precisely because they are their owners'
  trademarks and this repo is public.

Adopting GPL code would therefore force a relicensing we have no authority to
perform. **This alone rules out vendoring.** It is not a style preference.

Note the distinction honestly: a Python transliteration of `resolution.rs` is
still a derivative work — changing language does not launder copyright. What is
*not* copyrightable is the underlying idea (a 5-zone action model) and the
published calibration facts (real-world card and shot rates, and the papers
cited for them). Rebuilding from the specification in `docs/MATCH_SIMULATION.md`
and the cited literature, without copying implementation expression, is the
defensible path. I am not a lawyer and this is an engineering risk assessment,
not legal advice.

## 3. Blocker two — no Rust toolchain here (practical)

`cargo` and `rustc` are absent. `static.rust-lang.org` is **not** on this
environment's allowlist (TLS connect fails), and the PyPI `rustup` package is
only a bootstrapper that downloads from that same blocked host. So OFM cannot be
compiled, run, or measured here at all.

Every OFM performance figure in this document is therefore **quoted from their
docs, not measured by me**. Our own figures are measured. Any port would be
written blind against a test suite we cannot execute — the opposite of how this
repo has been built.

## 4. Blocker three — attribute mismatch (soft, solvable)

OFM's engine reads **19** attributes. We ship EA's **34 raw** ones. I mapped all
19 against the real 21,623-player table:

| OFM | EA source | kind |
|---|---|---|
| pace | acceleration, sprintspeed | mean |
| stamina / strength / agility / vision / composure / aggression | same name | direct |
| passing | shortpassing, longpassing | mean |
| shooting | finishing, shotpower, longshots | mean |
| tackling | standingtackle, slidingtackle | mean |
| dribbling | dribbling, ballcontrol | mean |
| defending | defensiveawareness, interceptions | mean |
| positioning | positioning, defensiveawareness | mean |
| decisions | composure, reactions | **proxy** |
| handling | gkhandling | direct |
| reflexes | gkreflexes, gkdiving | mean |
| aerial | jumping, headingaccuracy, strength | mean |
| **teamwork** | — | **no source** |
| **leadership** | — | **no source** |

**17 of 19 map cleanly.** Composites land in sane ranges (medians: pace 67.5,
passing 60.5, shooting 54.3, defending 53.5). `teamwork` and `leadership` have no
EA equivalent and would have to be flat constants — which silently disables part
of OFM's midfield and passing maths.

Two more mismatches: OFM's `Position` has only 4 values (GK/Def/Mid/Fwd) against
our 28 EA slot ids, and its traits are computed names like `Sharpshooter`, while
we ship 36 EA playstyles plus raw trait bitmasks. Both need a translation layer.

This blocker is real but ordinary. It is not why I recommend against the port.

## 5. What our engine already does well (measured)

380-match Premier League season, seed 7, our current `lib/engine/match.py`:

| Metric | Ours (measured) | Real PL reference |
|---|---|---|
| goals/game | **2.65** | ~2.8 |
| home win | **46.3%** | ~46% |
| draw | **25.0%** | ~24% |
| away win | **28.7%** | ~30% |
| shots/game | **24.7** | ~25 |
| speed | **9.05 ms/match** (3.44 s per 380) | — |

Our scoreline calibration is already close to real, and it was fitted, not
guessed. Replacing the engine would put that at risk to solve problems that are
mostly *not* in the scoreline model.

## 6. What our engine genuinely lacks

These are the reasons to do work at all. The first is a proven defect.

### 6.1 Red cards are cosmetic — PROVEN

Cards and injuries are rolled **after** the minute loop finishes, so they cannot
influence play. I forced `RED_P = 1.0` across 120 fixtures:

- **2,621 red cards** issued (~21.8 per match, i.e. both XIs sent off)
- goals/game **3.02**, shots/game **25.4**
- baseline, same seeds: goals/game **3.02**, shots/game **25.4**
- **every scoreline identical**; sent-off players still recorded **90 minutes**

A team playing with nine men scores exactly as often as at full strength. OFM
models this properly and calibrates it against published red-card research
(Ridder et al. 1994; Červený et al. 2018): the eleven-man side scores ~1.9–2.2×
as often, the ten-man side ~0.53–1.0×. **This is the single most valuable thing
to take from OFM, and it is a calibration target, not code.**

### 6.2 Card rates are below the real band

Ours: **3.28 yellows, 0.100 reds** per match. OFM cites CIES Football Observatory
Monthly Report n°57 (Poli, Ravenel & Besson 2020) for the Big Five band of
**3.39–5.27 yellows and 0.12–0.27 reds**. We are under the floor on both. OFM
lands at ~4.0 and ~0.21. Fixing 6.1 will move these, so they must be re-fitted
together.

### 6.3 Possession is derived, not simulated

Ours is one line of algebra on midfield ratings, clamped to 28–72%:
`poss = hu['mid'] / (hu['mid'] + au['mid'])`, then squeezed. It is a plausible
number, not an emergent one. OFM counts possession ticks per minute.

### 6.4 No in-match management

No live phase machine, no user substitutions during play, no formation or
tactical changes, no half-time interval. Our subs are three pre-rolled events at
minutes 58–78 chosen before the match starts. This is the largest feature gap and
the one a playable UI would immediately expose.

### 6.5 No extra time or shootouts

Absent entirely. Needed before knockout cups work — and cups are already on the
"not built" list. OFM's shootout implementation is notably careful (early clinch
per the Laws, equal-attempts sudden death, reduce-to-fewer-kickers, order fixed at
the final whistle). Its *rules* are just the Laws of the Game and are free to
implement.

### 6.6 No event feed

We emit only `goal`, `yellow`, `red`, `injury`, `sub`. No passes, tackles,
interceptions, or zone movement — so there is nothing to render as commentary.
OFM has 22 event types.

## 7. Options

| Option | Verdict |
|---|---|
| **A. Vendor the Rust crate, call via subprocess/FFI** | Rejected. GPL-3.0 attaches; no toolchain to build it; adds a Rust build step to a stdlib-only Python runtime. |
| **B. Transliterate Rust → Python** | Rejected. Still a derivative work under GPL; 8,031 lines to port blind against 7,232 lines of tests we cannot run. |
| **C. Rebuild the behaviours from the published spec + cited literature** | **Recommended.** No copied expression, keeps our fitted calibration, stays stdlib-only, and each piece is independently testable. |
| **D. Do nothing** | Defensible short-term, but leaves a proven correctness bug (6.1) in place. |

## 8. Suggested order of work (option C)

Ordered by value against risk. Each step keeps our existing calibration
assertions in `tools/verify_engine.py` green, and each needs new invariants plus
mutation tests in the established style.

1. **Move discipline into the minute loop; make a red card reduce the side.**
   Fixes the proven bug. Apply an eleven-man boost and a ten-man penalty,
   re-fitted to hold goals/game near 2.7 while landing cards in the CIES band.
   Reduce the sent-off player's recorded minutes. This is self-contained and
   changes no public API.
2. **Simulate possession** rather than deriving it, so it can respond to shape
   and to being a man down.
3. **Adopt a 5-zone action model** for the event feed. This is the idea, not the
   code: ball in one of five zones, 1–3 actions resolved per minute, advance on
   success. Re-fit chance volume afterwards, since this replaces our per-minute
   chance process.
4. **Live phase machine + in-match commands.** The big feature. Worth doing only
   once a UI exists to drive it, which is still unbuilt.
5. **Extra time and shootouts**, alongside knockout cups.

Steps 1–2 are a contained fix worth doing on their own. Step 3 is the real
"new engine" and should be treated as a re-calibration project, not a refactor.

## 9. Honest limits of this study

- I could not compile or run OFM. All upstream performance and rate figures are
  quoted from `docs/MATCH_SIMULATION.md`, not verified by me.
- I read the design doc fully and sampled the Rust (`lib.rs`, `engine/mod.rs`,
  `engine/resolution.rs`, `types.rs`, crate manifest). I did **not** read all
  8,031 source lines, so the port estimate is by line count and structure, not a
  line-by-line audit.
- The attribute mapping was computed against all 21,623 real players, but it is
  my proposed mapping, not one validated by simulating with it.
- Our 380-match figures are one season at one seed. `verify_engine.py` covers
  more; a re-fit must use several seeds, as the original calibration did.
- The GPL analysis is an engineering risk assessment, not legal advice.
