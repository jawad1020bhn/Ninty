THE GAFFER pc414 - FC 27 STANDALONE CAREER BUILD r23
===========================================

This folder is The Gaffer pc414.  It is a private, modified build for personal
use; please respect the original FREE TO USE terms of The Gaffer (do not
reupload or publish this as your own work).

EA SPORTS FC 27 is the only game.  r23 removed the old PES/FL26 save-file
backend entirely: this is now a standalone career simulation with its own
save.  See REMOVING THE PES BACKEND below for what changed and what the old
UI's status is.

r22 makes it a CAREER rather than a single season: the season now closes and
the next one opens, with aging, development, retirement, revaluation, youth
intake at every club and a release valve that keeps the world from inflating.
See SEASON ROLLOVER below.  r21 added the engine itself; r20 the database
checker; r18 the table-coverage audit (268/268 tables accounted for).

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
unchanged.  Those algorithms are now save-format independent (see r23 below).

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
    ea_attrs.json    EA's 34 attributes per player, RAW and lossless.
    ea_positions.json  EA position ids per player, best first, plus the
                     slotCompat map (see POSITIONS below).
    national_teams.json  69 national teams (51 men, 18 women) with 1,740
                     capped players.  Kept separate from clubs.json so club
                     competitions never pick up a national side.

CAREER LOGIC TABLES
Found by sweeping all 268 upstream tables for non-empty ones the importer was
not reading.  215 are non-empty; most are presentation-only (skins, crowds,
kits, vanity, audio) and stay out.  These twelve carry career logic:

    teamsheets.json  captain + 7 set-piece takers for all 717 clubs.  Every
                     taker verified to be in that club's own squad.
    coefficients.json  175 clubs / 27 nations, 5 yearly scores + total, for
                     European seeding and reputation.
    calendar.json    transfer windows as month/day (1 Jul-31 Aug, 1-31 Jan).
                     Year-less on purpose: the engine's save owns the season.
    ownership.json   93 clubs in 33 multi-club groups - blocks transfers
                     between siblings (e.g. Arsenal / Colorado Rapids).
    league_groups.json  MLS conference split (30 clubs).
    comp_venues.json neutral and cup-final venues per competition.
    prev_stats.json  last season's real per-competition stats for 3,929
                     players (apps, goals, assists, cards, clean sheets).
    referees.json    363 officials with card/foul strictness, linked to 53
                     leagues - feeds discipline rates in match simulation.
    regen_names.json 11,744 first / 9,358 last / 481 common names for youth
                     and regen generation, in 105 language/region pools.
    regen_templates.json  attribute templates by position group and age
                     (72 youth, 66 regen).  Youth ages are MONTHS, regen YEARS.
    ovr_weights.json EA's per-position rating weights + the 0..5 star bands.
                     See the warning below about the attribute ids.
    playstyles.json  36 PlayStyle unlock thresholds (26 named).

THE FC 27 ENGINE (separate game, own save)
-----------------------------------------
lib/engine/ is the game the database was prepared for.  It is self-contained:
it reads the FC 27 database for static facts and keeps its own JSON careers
under data/saves/ (git-ignored, about 1.2 MB each).  No other game's save
format or install is involved.

    lib/engine/store.py     save format, atomic writes, squad moves
    lib/engine/world.py     build a career world from the database
    lib/engine/fixtures.py  seeded double round-robin schedule
    lib/engine/lineup.py    team selection (drives the existing AI)
    lib/engine/match.py     match simulation on EA's 34 raw attributes
    lib/engine/season.py    play fixtures, tables, form, injuries, bans
    lib/engine/positions.py EA's 28-id enum -> the app's 13 POSN roles
    lib/engine/roster.py    save-aware player facts + compact save codecs
    lib/engine/rollover.py  end-of-season aging, growth, retirement, intake
    lib/engine/names.py     regen names by language pool and club gender
    lib/engine/posgroup.py  the inferred position-group enum for templates

The division of responsibility is deliberate: the DATABASE owns static facts
(names, attributes, birthdays, stadiums, formation shapes) and the SAVE owns
only what a career changes.  So a database refresh is not destructive, and no
fact has two sources of truth.

Existing, credited algorithms are REUSED, not reimplemented:
    lib/ailineup    how many changes to make for a big/normal/low match
    lib/pitch       position-distance matrix + Hungarian assignment (pure)
    lib/formengine  the 0-7 Form level from real match ratings
    lib/revalue     the valuation curve that seeds market values
These are pure helpers with no save-format coupling.  verify_engine.py and
verify_backend.py assert that by walking the actual import statements through
the whole transitive closure, not just the engine's own files.

WHAT WORKS NOW
    * create a career at any of the 717 clubs, in any of the 41 leagues
    * a full 38-round double round-robin season, played in date order
    * match simulation with scorers, assists, cards, injuries, substitutions,
      possession, shots, referee and crowd
    * league table, form guide, top scorers, per-player season stats
    * injuries heal and bans are served as the clock advances
    * deterministic: the same seed replays a season identically, and a
      reloaded save continues exactly as an uninterrupted one would
    * MULTI-SEASON: close a season and the next one opens.  Players age,
      develop or decline, retire, get revalued; every club gets a youth
      intake, surplus players are released, and free agents age out

CALIBRATION IS MEASURED, NOT GUESSED
Three full 380-match seasons (seeds 7, 19, 31) were simulated over a grid of
chance/conversion/home-edge values.  The shipped setting produces

    goals/game 2.74   home 45.7%   draw 24.8%   away 29.5%   shots/game 25.0

against real Premier League references of roughly 2.8 / 46 / 24 / 30 / 25.
Shots were already right, so conversion was the lever for goals and the
home/away pair sets the result split.  A full season simulates in ~2.4s.

Two data traps found while building this, both recorded in the code:
  * match_tuning.attendance is a 0-10 EMOTION band, not a stadium fill
    fraction.  Reading it as a fill gave 100% capacity at every ground.
    Attendance is now an explicit engine choice from capacity + reputation.
  * EA's bigmatchups list is curated and omits Manchester United-Liverpool,
    which rivals.json rates intensity 5.  The engine treats a fixture as big
    if EITHER source says so; fc27.is_big_match() still reports only upstream.

SEASON ROLLOVER
    close_season() ages and develops every player, retires the old, revalues
    the market, brings through an academy group at all 717 clubs, releases the
    surplus to free agency, and opens the next fixture list.  It reuses two
    more credited modules rather than inventing curves:

        lib/growth   month_plan() - development, decline, destiny, late bloomers
        lib/revalue  merit()/new_value() - end-of-season revaluation

    Attribute deltas live in the SAVE as an overlay; the database is never
    mutated.  Retirement and intake are engine rules, not database facts:
    upstream ships isretiring = 0 for all 21,623 players and no intake rules.

    Six defects found by running FIVE seasons, all recorded in the code and
    covered by the verifier:
      * the keeper-restock loop asked the DATABASE whether a club had two
        keepers.  A generated keeper is invisible there, so the test never
        became true and the loop span forever.  Player facts now resolve
        through lib/engine/roster.py, and the loop is bounded.
      * the keeper age allowance was ADDED, retiring 30-year-old keepers as if
        they were 33.  Keepers get three years SUBTRACTED.
      * only 20 of 717 clubs are simulated, so 19,081 players had no minutes.
        Scoring absent evidence as bad form retired 1,224 of them in one
        close.  Unsimulated players now get a neutral regular season.
      * intake ran BEFORE trimming, so a club already at the squad limit got
        no academy at all - including the big clubs a manager is most likely
        to run.  Squads are trimmed first, with slots reserved for the intake.
      * nothing ever left the world except retirees: population climbed
        21,623 -> 24,355 in three seasons while mean OVR fell.  Clubs now carry
        a 26-man list, the surplus is released, and unsigned free agents age
        out.  Population settles near 19,000 and elite quality holds steady
        (Premier League best-XI mean 80.28 -> 80.02 over six seasons).
      * unfiltered name picking gave men's clubs feminine forenames and mixed
        language pools ("Maimouna Kubanychbekova").  Names now come from ONE
        pool and match the club's own `women` flag (85 of 717 are women's
        sides).  The flag meanings were verified against 363 known names.

    A youth player who is not selected still trains: without an academy floor
    his playing share was 0 and he could never close the gap to the seniors
    ahead of him.  Generated players now reach first-team minutes.

    Saves stay small: per-player progress is stored positionally instead of
    as 25 repeated attribute names, and archived history keeps the headline
    movers.  A five-season career is about 7 MB instead of 15 MB at three.

NOT BUILT YET (honest scope)
    cups and continental competition, the transfer market and contract
    negotiations, budgets spent, morale effects, and the UI screens.  The
    data for these is already shipped and verified; the engine increment that
    consumes it is still to come.  Rollover auto-renews expiring contracts
    until negotiation exists.  The engine is reachable by API only: there is
    no UI yet, and static/index.html is an inert design reference.

ENGINE API
    GET  /api/engine/careers                 list careers
    GET  /api/engine/state?id=               summary, table, next fixtures
    GET  /api/engine/squad?id=&club=         squad with career state
    GET  /api/engine/table?id=&league=       table + top scorers
    GET  /api/engine/select?id=&club=&opp=   proposed XI and why
    POST /api/engine/new                     {club, manager, seed, leagues}
    POST /api/engine/play                    {id} play the next fixture
    POST /api/engine/advance                 {id, days} run the clock (1..400)
    POST /api/engine/transfer                {id, pid, to}
    POST /api/engine/finish                  {id} play out the whole season
    POST /api/engine/close_season            {id} roll into the next season
    GET  /api/engine/history?id=&limit=      archived season reports
    POST /api/engine/save                    {id}
    POST /api/engine/delete                  {id}

    play only advances the MANAGED club's fixtures, so finish exists to play
    the rest of the league; close_season refuses (400) until every fixture is
    played, rather than half-applying a rollover.

VERIFYING THE ENGINE
    python3 tools/verify_engine.py            # 131 checks, about 60 seconds
    python3 tools/verify_engine.py --quick    # 119 checks, skips calibration

Careers are written to a temporary directory, so the verifier can never touch
a real career.  It asserts BEHAVIOUR, not just consistency: reproducibility,
exact save/reload, resume-after-reload, table arithmetic closing, scorer rows
summing to the scoreline, injuries and bans actually affecting selection, and
the stored Form equalling what formengine computes.

Home advantage is tested in ISOLATION by putting the SAME XI on both sides,
so team quality cannot mask a broken venue multiplier.

The verifier was mutation-tested against 26 deliberately broken engines: 12
for the single-season core and 14 for rollover (database-only keeper lookup,
inverted keeper allowance, absent minutes scored as bad form, intake after
trimming, no release valve, immortal free agents, a retiree left in his squad,
names ignoring club gender, names mixing language pools, no academy floor,
unchecked season completion, uncapped history, a roster blind to generated
players, and a codec dropping negative deltas).  All 26 were caught.  The
rollover pass caught only 9 of 14 at first: five checks were too weak - two
passed the gender explicitly instead of exercising the club-flag lookup, one
could not reach a 20-season history cap in two rollovers, and two asserted an
outcome the mutant did not actually change.  Those were fixed and re-run.

The original 12 were
(neutralised home edge, ignored injuries, ignored suspensions, stubbed-out
form, career id leaking into the seed, int keys breaking reload, wrong win
points, injuries never healing, duplicate squads, single round-robin, arcade
conversion).  All 12 were caught.  The first pass caught only 7 - three checks
were passing vacuously because they injured or banned a player who was not in
the XI anyway, and the home-advantage cutoff was too loose.  Those were fixed
before the engine was committed.

VERIFYING THE DATABASE
    There is no test suite in this repo, so the database ships with its own
    checker.  Run it after any regeneration:

        python3 tools/verify_fc27.py            # 64 checks, about half a second
        python3 tools/verify_fc27.py --verbose   # list every check

    Stdlib only; no server, no save, no Node.  It exits non-zero on any failure
    and checks five things: identity (every per-player table covers exactly the
    roster), coordinates (all 7,887 designated starters fit their club's
    formation through slotCompat), references (zero dangling team/stadium/
    referee ids across all 730 referenced team ids), raw id spaces (the
    undecodable tables still carry their warnings, so a false alignment claim
    cannot be quietly reintroduced), and readiness.

    Readiness is the one that matters: for EVERY club it builds a matchday squad
    - 11 starters, subs, captain, set-piece takers inside the squad, stadium,
    manager, formation - using nothing but this database.  That is the
    difference between "the files parse" and "a career can actually start".

    The checker was mutation-tested: 10 deliberately corrupted copies (dangling
    national-team id, broken slotCompat, captain outside the squad, missing
    attribute row, reintroduced ab-alignment claim, out-of-range attribute,
    invalid join date, bad stadium id, club without an XI, asymmetric rivalry)
    were all caught.  A checker that cannot fail proves nothing.

COVERAGE - EVERY UPSTREAM TABLE IS ACCOUNTED FOR
    data/fc27/COVERAGE.txt lists all 268 tables in the FC 27 template and says
    what happened to each one:

        43  read and extracted (+ the localization bundle)
        53  empty upstream - nothing to extract
        78  inspected individually and excluded, each with its reason
        94  triaged by family AND field-scanned (appearance, audio, other modes)

    The last group is labelled honestly: those were judged by name and by a
    scan of their FIELDS for football logic, not row by row.  r16 had called
    that whole remainder "presentation" and r17 proved that wrong, so the
    distinction is kept visible.  The field scan now reports 0 tables with an
    unexplained logic field.

    Regenerate it with:
        node tools/audit_fc27_coverage.mjs --kit /tmp/kit/package

    The "read" list is parsed out of import_fc27.mjs, so it cannot drift from
    what the importer does.  The tool exits non-zero if a table is unaccounted
    for or unclassified - a new upstream table fails the audit instead of being
    silently ignored.

    The same field scan was pointed at the players table itself and found three
    career fields that had never been read, now extracted:
      joinedClub      date the player joined his current club (same 1582 epoch
                      as birthdate).  van Dijk 2018-01-01, Messi 2023-07-16,
                      Mbappe 2024-07-01.  fc27.years_at_club(pid) gives tenure
                      against the database snapshot, for homegrown/loyalty rules.
      growthProfile   raw 1..6 career-stage id.  Upstream does not name the
                      curves, so no label is invented; observed: profile 6 is
                      young with headroom (mean age 24.4, +9.4 potential),
                      profile 4 is a near-peak veteran (30.0, +1.4).
      icon1/icon2     Icon/Hero bitflags in traits.json (327 / 30 players), raw
                      like trait1/trait2.

SECOND PASS - "presentation-only" WAS TOO SWEEPING
    r16 dismissed the remaining non-empty tables as presentation.  Checking
    them one by one showed several carry career logic, now extracted too:

    affinities.json  216 players' emotional ties to clubs, strongest first.
                     Iniesta -> Barcelona 7, -> Athletic Club 1.  The scale is
                     NOT documented upstream; low=grudge/high=affection is an
                     inference and is labelled as such in the metadata.
    former_clubs.json  200 players' previous club (verified none is still there).
    counterparts.json  128 clubs paired men's <-> women's (64 pairs, symmetric).
    big_matches.json 33 marquee fixtures; only 7 of 38 upstream rows overlapped
                     rivals.json, so this is genuinely extra signal.
    match_tuning.json  intensity by score difference (-4..4) x minute bucket
                     (15/30/45/60/75/90/120), plus attendance emotion bands.
    external_teams.json  8 CONMEBOL clubs (Flamengo, Corinthians, Penarol...)
                     referenced by the data but outside the 717-club universe.
    regen_templates.json  also gained 149 create-player templates by position
                     group, age range and OVR band.

    A sweep of EVERY team id referenced anywhere in the shipped data (730
    distinct) found 8 that resolved to nothing.  external_teams.json ships
    their names, and fc27.team_name(tid) resolves clubs, national teams and
    these externals alike.  There are now zero dangling team references.

    Still excluded, each verified rather than assumed:
      agents (29)         every row is "Agent Test N" - no real names.
      sponsors (392)      names are texture asset keys (dynamic_01,
                          Tottenham_Hotelscom); no contract or value fields.
      competitionmatchups (450)  a partial UEFA pot draw, not a fixture list;
                          drawing the schedule is engine season state.
      cm_* / level_caps   Pro Clubs archetype XP, not manager career.
      height_weight_impact, createplayerpositiontemplates, turfattributesmap
                          further unresolved attribute id spaces (the second
                          uses ids 75..111, outside the 34-field range).
      positionbonus, rankweight   every value is 0.

ATTRIBUTE IDS THAT ARE NOT WHAT THEY LOOK LIKE
    ovr_weights.json and playstyles.json reference EA's INTERNAL attribute
    enum, which is NOT the field order in ea_attrs.json.  Treating them as the
    same space puts only 29% of players top in their own position (van Dijk
    rated higher at ST than at CB).  An unconstrained fit reached just 48% and
    still produced impossible assignments - a keeper formula weighting
    freekickaccuracy while gkkicking sat outside it - and attributecategorymap
    contradicts it.  Five ids appear in no formula at all.  So the ids ship RAW
    and UNMAPPED, and no rating_in_pos() helper is offered: do not index
    ea_attrs.json with them.  The star bands are rating-based and safe
    (fc27.stars(ovr)).  regen_templates.json is keyed by FIELD NAME, so it is
    unaffected.
    traits.json is likewise still raw: every trait bit was tested against every
    PlayStyle requirement set and the best F1 was 0.32, so no decode is invented.

TWO ATTRIBUTE SETS - USE THE RAW ONE FOR SIMULATION
    ratings.json carries the legacy 25 attributes the growth algorithm reads.
    That is a LOSSY projection of EA's data: it has no slot for crossing,
    volleys, reactions, longshots, interceptions, vision, penalties, composure
    or slidingtackle, and it blends agility into TightPossession.
    Those are match-deciding values. Van Dijk's interceptions 88 and sliding
    tackle 85 versus Messi's 40 and 24 simply do not exist in the legacy 25, so a
    simulator reading only those cannot tell an interceptor from a slider.
    ea_attrs.json keeps all 34 EA values unblended for the engine; the legacy 25
    stay so market/growth/valuation keep working unchanged.
    /api/fc27/attrs returns both schemas and lists what the projection drops.

POSITIONS - TWO GRANULARITIES, ONE ENUM
    formations.json and ea_positions.json share EA's 28-id enum, but NOT its
    granularity.  A formation slot is side-specific (4 RCB, 6 LCB, 9 RDM,
    24 RS); a player only ever carries the coarse central id (5 CB, 10 CDM,
    25 ST) - just 12 of the 28 ids appear on any player.  Comparing the raw ids
    directly leaves 1,998 of the 7,887 designated starters unable to fill their
    own club's formation.  ea_positions.json ships a slotCompat map that
    collapses a slot to the id a player can hold; with it all 7,887 fit.

        fc27.fits_slot(pid, slot)      does the comparison for you
        fc27.slot_compat()            the 28-entry map
        /api/fc27/attrs               returns slotCompat + the id->name enum

    positions.json / playpos.json remain the lossy 13-slot projection the
    older lineup code reads.  Do NOT match formation slots against those: it
    collapses RCB/LCB/CB into one CB and cannot express the side at all.

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
                                rivals, starting XI, last season's position,
                                captain/set pieces, coefficient, ownership
    /api/fc27/player?id=203376  one player incl. shirt, role, traits, loan
    /api/fc27/search?q=mbappe   accent-insensitive search
    /api/fc27/cups?women=0      cup list
    /api/fc27/loans?club=9      loans in/out for a club
    /api/fc27/attrs             EA-34 / legacy-25 schemas (ea / ab25) +
                                position enum + slotCompat map
    /api/fc27/national          national teams (?women=0|1)
    /api/fc27/national?id=1318  one national team + its squad, best first
    /api/fc27/calendar          transfer windows (?month=&day= -> open bool)
    /api/fc27/referees          officials (?league=13 for one league)
    /api/fc27/regen             name-pool and template counts for generation
    /api/fc27/matches           marquee fixtures (?a=&b= -> big/derby/owner)
    /api/fc27/tuning            match intensity + attendance (?diff=&minute=)

IDS ARE EA'S AND ARE NOT INTERCHANGEABLE (not cosmetic)
    FC 27 reuses small competition ids that meant DIFFERENT leagues in the
    removed game: 17 is Ligue 2 here, 19 is 1. Bundesliga.  Competition names
    come from data/fc27/comps.json, never from a merged table.
    Nationality ids are EA's too (4 Austria / 18 France / 21 Germany /
    27 Italy / 45 Spain).  As of r23 regrules carries FC 27 ids as its ONLY
    table - RULES, DOMESTIC and EU - derived from the extracted leagues and
    nations.  The old alternate-game tables and the runtime swap are gone.

ALSO REMOVED IN r12
    The foreign F7-dump database importer (/api/dbimport/preview, /apply,
    /faces).  A dump from another game has different player ids and a
    different attribute scale, so importing one would corrupt this database.
    Rebuild with tools/import_fc27.mjs instead.  The runtime reads only
    data/fc27/, with no fallback to data/ root.

SCOPE
    The database (r12-r20), the engine (r21) and multi-season rollover (r22)
    are built and verified.  r23 removed the PES backend.  There is no UI yet:
    static/index.html is kept unchanged as a design reference but addresses
    removed endpoints.  Overall rating is EA's own value, used directly rather
    than recomputed from attributes.  For simulation read ea_attrs.json (raw,
    lossless) rather than the lossy 25-attribute projection in ratings.json,
    and match formation slots through slotCompat rather than by raw id.

LICENSING - IMPORTANT
    eafc-db-kit's MIT licence covers the KIT'S CODE, not EA's football data.
    The player/club/rating content is EA's copyrighted material and is
    redistributed here without an explicit licence from the rights holder,
    at the repository owner's direction.  Read data/fc27/NOTICE.txt before
    publishing or selling this.  The importer and runtime depend only on the
    JSON schema, so the data can be swapped for a set you have rights to.

    CRESTS ARE A SEPARATE, ADDITIONAL PROBLEM.  The logo collection imported by
    tools/import_graphics.py is also MIT, but again only for its code and
    curation: every crest is the trademark and copyright of its club, league or
    federation, and no open-source licence grants those rights.  Because this
    repository is PUBLIC, the artwork is NOT committed - data/graphics/crests/
    is git-ignored, exactly like the older data/crests/.  Only the manifest and
    ATTRIBUTION.txt are tracked.  Run the importer locally for a personal
    install; do not publish the fetched files.  The generated shields in
    lib/graphics.py are original geometry and carry no third-party rights.

    PORTRAITS are restricted to the freely-licensed subset of Wikimedia Commons
    (CC0, public domain, CC BY, CC BY-SA).  Fair-use, non-free, non-commercial
    and no-derivatives images are refused, and every accepted image records its
    attribution.  Copyright is not the only right involved: a free photo still
    depicts a real person, so this is for editorial/fan display, not
    merchandising or endorsement.

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
13. r12-r15: FC 27 DATABASE.  PES is no longer a dependency: the game reads
   FC 27 only (21,623 players, 717 clubs, 41 leagues, 69 national teams) via
   tools/import_fc27.mjs -> data/fc27/ and lib/fc27.py.  The AI/transfer
   algorithms and the UI were kept, not rebranded.
   r13 added the engine reference tables (stadiums, managers, formations,
   rivals, loans, traits, cups, shirt numbers/squad roles, previous position).
   r14 fixed a LOSSY projection: the PES-25 attribute set silently dropped 9
   EA attributes, so ea_attrs.json now ships all 34 raw.
   r15 fixed two integration bugs found by auditing coordinate spaces:
   formation slots were side-specific while players carried coarse ids (now
   bridged by slotCompat, 7,887/7,887 starters fit), and 69 national-team ids
   in contract.natPos resolved nowhere (now national_teams.json).
14. r16: COMPLETENESS SWEEP.  All 268 upstream tables were checked for
   non-empty data the importer was skipping; 12 career-logic tables were added
   (captain/set pieces, coefficients, transfer windows, multi-club ownership,
   cup venues, last-season stats, referees, regen name pools and templates,
   rating weights, PlayStyle thresholds).  The importer now FAILS LOUDLY if an
   allowlisted table is missing - it previously wrote empty files in silence.
   Two id spaces proved undecodable and are shipped raw with warnings rather
   than guessed at (attribute enum, trait bits).
15. r17: SECOND-PASS AUDIT.  r16's "the rest is presentation-only" was checked
   table by table and found too sweeping: player affinities, former clubs,
   men's/women's counterparts, marquee fixtures, match intensity/attendance
   tuning and create-player templates were all real and are now extracted.
   A full reference sweep found 8 dangling team ids (CONMEBOL sides); it now
   ships external_teams.json + team_name(), leaving zero dangling references.
16. r18: COVERAGE AUDIT TOOL.  tools/audit_fc27_coverage.mjs regenerates
   data/fc27/COVERAGE.txt, accounting for all 268 upstream tables (43 read,
   53 empty, 46 excluded with reasons, 126 triaged by family).  It derives the
   read list from the importer and fails on any unclassified table, so a new
   upstream table cannot be silently skipped.
17. r19: FIELD-LEVEL SCAN.  Scanning fields (not table names) for football
   logic closed the last gap: 30 more tables were inspected and classified, and
   the scan of the players table itself found three unread career fields
   (playerjointeamdate, growthprofile, icontrait1/2), now extracted.  The audit
   reports 0 tables with an unexplained logic field.
18. r20: DATABASE VERIFIER.  tools/verify_fc27.py runs 64 integrity and
   readiness checks in ~0.5s with no server or save, and exits non-zero on
   failure.  It proves every club can field a matchday squad from this data
   alone.  Mutation-tested against 10 corrupted copies; all were caught.
19. r21: THE SEPARATE ENGINE.  lib/engine/ is a standalone FC 27 career with
   its own JSON save, no PES dependency.  Fixtures, match simulation on EA's
   34 raw attributes, tables, form, injuries and bans all work; a 380-match
   season simulates in ~2.4s and is calibrated against real Premier League
   rates.  11 new API routes.  tools/verify_engine.py adds 75 behavioural
   checks, mutation-tested 12/12.  279-endpoint differential vs r20: zero
   regressions, all 9 sampled fc27 payloads byte-identical.
   Cups, transfers, growth and the UI screens are the next pieces of work.
20. r22: MULTI-SEASON CAREERS.  A season closes and the next one opens: players
   age, develop or decline, retire and get revalued; every club gets a youth
   intake; surplus players are released and free agents age out.  Order matters
   and is enforced - champions, development, retirement, trim, intake, free
   agents, history, new season - because trimming AFTER intake left 26-man
   clubs with no graduates.  Player facts moved behind a save-aware roster so
   generated players are first-class (a database lookup for a youth keeper
   returned nothing and span a loop forever).  Save codecs became positional,
   cutting a three-season save from 7.12 MB to 2.49 MB.  verify_engine grew to
   129 checks, mutation-tested 14/14 after five weak checks were strengthened.
   279-endpoint differential vs r21: zero regressions.
21. r23: THE PES BACKEND IS REMOVED.  26 modules and 193 routes deleted;
   server.py fell from 21,322 lines to 841.  The kept AI/transfer algorithms
   were decoupled from save bytes and proven behaviourally identical.  A new
   tools/verify_backend.py adds 102 checks, mutation-tested 22/22.  63-endpoint
   live differential vs r22: zero regressions.  See the section below.
22. r24: GRAPHICS.  Established that FC 27 ships no artwork, then added crests
   and portraits in three degrading layers so nothing renders broken.  A pinned,
   country-scoped importer resolves 709/717 clubs, 32/41 leagues and 197/219
   nations; generated shields cover the rest and the whole of a fresh clone.
   Portraits are restricted to freely-licensed Commons images behind separate
   licence and identity gates, off by default.  Three new routes.  175 new
   checks, mutation-tested 24/24 after two weak checks were strengthened.  The
   artwork is git-ignored because this repository is public.  See GRAPHICS below.

REMOVING THE PES BACKEND (r23)
------------------------------
The PES/FL26 save-file companion is GONE.  server.py went from 21,322 lines to
841 and lib/ from 53 modules to 29.  There is no longer any code that opens,
decrypts, patches or re-encrypts another game's save, no install-path detection,
no live-process memory reading and no external encrypter tools.

Deleted modules (26): mlsave, mlwrite, pescrypt, pes17, pes17_write,
pes17_layout, pes17_pairs, pes17_setup, dbimport, facemap, layoutscan, loanscan,
savediff, seasonstats, kitsponsor, gamemem, coaches, bc7, dds, ftex and the six
fl26_* career readers.  Also deleted: data/teamids.json (a foreign club-id map),
data/fl26_installed_league_counts.json, lib/ovr_weights*.json (dead duplicates
of the live data/fc27 copies) and config_pes2017.example.json.

WHAT THE SERVER IS NOW
    GET  /api/fc27/*      15 routes over the database (players, clubs, leagues,
                          cups, loans, national teams, referees, regen, tuning)
    GET  /api/engine/*    6 routes over a career (careers, state, squad, table,
                          select, history)
    POST /api/engine/*    8 routes (new, play, advance, save, delete, transfer,
                          finish, close_season)
    GET  /api/art, /api/stadium, /api/venue, /api/clubcolors, /api/i18n,
         /api/fmtext, /api/myscene, /api/myscene-m   shared football assets
    GET  /api/crest       ?club= | ?league= | ?nation=   club/league/nation mark
    GET  /api/face        ?pid= | ?manager=              player/manager portrait
    GET  /api/graphics/status                            crest and portrait coverage
    plus /api/version, /api/clientlog, /api/quit and PIN-gated phone/tablet
    access on port+1.  Static files are served from static/ with a traversal
    guard.  Everything else returns 404.

    /api/crest and /api/face accept &meta=1 to return JSON instead of image
    bytes, reporting source ('vendored' | 'generated' for a crest, 'photo' |
    'avatar' for a face), mime, byte length and any portrait attribution.

THE OLD UI IS AN INERT REFERENCE
    static/index.html is deliberately UNCHANGED (byte-for-byte).  It is kept as
    a design reference only.  All 386 of its API call sites address the removed
    PES career endpoints, so it will not function against this server until a
    new UI is built on /api/engine/*.  This was a deliberate choice, not an
    oversight.  static/pes17.html is likewise inert.

ALGORITHMS KEPT, COUPLING REMOVED
The AI/transfer algorithms were kept, but they used to read PES save bytes.
They are now pure and take their data from the caller:

    lib/pitch.py      POS, the 13x13 role-distance matrix, hungarian() and
                      plan_label(), extracted VERBATIM from the old save
                      writer.  Proven identical on 1,300 random matrices.
                      The engine imports this instead of the save writer.
    aitransfers       plan()/plan_v2() now take a club dict, not a save object.
                      ai_world() replaces the two save readers and preserves
                      the exact admission rule (printable name of 3+ chars,
                      16..40 players, 11+ rated, managed club excluded) and the
                      strength calculation (mean of the top 14).  The budget
                      that was a u32 at club+1600 is now a budget_of(club)
                      callback in EUR, and the formation is formation_of(club).
                      A Differential against the pre-strip version on a
                      synthetic save: 32 comparisons, ZERO differences in
                      moves, order, reasons or stats.
    aimanager         the one dependency on the PES statistics module was a
                      pure date tuple; it is now a local _match_order().
    regrules          FC 27 ids are the ONLY table.  Previously the server
                      swapped them in at runtime; with that swap gone the module
                      itself had to change, or the kept transfer AI would have
                      silently used foreign league and nationality ids.
                      6,000 check() comparisons against the old swapped-in
                      tables: zero differences.  The EU set is now verified by
                      deriving it from the database's ISO codes.
    venues            was fl26_venue_metadata, which resolved a club name via a
                      PES club-id table and returned that foreign id.  It now
                      matches on name alone.  This RECOVERED 800 names and lost
                      none: FC 27 club coverage rose from 74 to 264 clubs, with
                      zero field changes for clubs that already resolved.

The 25-attribute projection stays because growth.py speaks it, but it lost its
PES branding: PES_AB -> AB25, project_pes -> project_ab25, pes_attrs ->
ab25_attrs, FM2PES -> FM2AB.  /api/fc27/attrs now returns ab25/ab25Source instead
of pes/pesSource, and the generated metadata key is ab25ProjectionDrops.  The
values, order and sources are unchanged.

VERIFYING THE BACKEND
    python3 tools/verify_backend.py     # 102 checks, about 1 second
    python3 tools/mutate_backend.py     # 22 mutants, about 25 seconds

It asserts that no PES module survives, that none is reachable through the
transitive import closure of either the server or the engine, that the route
surface is exactly the intended one, that the transfer AI is deterministic and
never mutates its caller's world, that budget/formation callbacks are honoured
and degrade safely, and that venue lookup refuses ambiguous names.

Mutation-tested 22/22: every mutant re-introduces one removed coupling or
defect and the verifier fails.  One weak check was found and fixed during this
step - the ambiguity guard was only tested with an UNKNOWN name (0 candidates),
which let a `len(candidates) < 1` mutation pass.  It now also tests a real
duplicate ('Club Nacional') and a synthetic pair with conflicting grounds.

A live differential against r22 (both servers running, same seeds) covered 63
kept endpoints including a full 380-match season and a rollover: ZERO
regressions, every payload byte-identical.  24 removed PES endpoints correctly
return 404, and the traversal guard still blocks ../ paths.

All 29 surviving modules import cleanly.  Totals are listed under VERIFYING
GRAPHICS below, which supersedes the r23 count of 297.

GRAPHICS: CRESTS AND PORTRAITS (r24)
------------------------------------
FC 27's database contains NO artwork.  The kit's own README says "external
crests/textures ... require the game's own tooling", so crests cannot come from
the same files as the players and ratings.  Extracting them from a game install
would need EA's texture pipeline (the ftex/bc7/dds tooling deleted in r23) and
would produce EA's copyrighted images.

Instead there are three layers, and every request resolves through them in
order.  Nothing ever renders broken:

    1. VENDORED   a real mark from the local cache built by the importer
    2. GENERATED  an original shield built from that club's own FC 27 colours
    3. (faces)    a freely-licensed Commons photo, else a generated avatar

IMPORTING CRESTS (optional, local, personal use)
    python3 tools/import_graphics.py --dry-run   # report coverage, write nothing
    python3 tools/import_graphics.py             # download pinned snapshot, extract

The upstream snapshot is pinned to a full commit sha so a re-import is
reproducible.  Matching is confined to each club's own country folder, because
an unscoped token match happily pairs Leverkusen with "Leverstock Green" and
Wolfsberger with Austria's "Wolfsberg".  Coverage measured against this database:

    clubs    709 / 717  (98.9%)   561 exact, 52 token, 71 alias, 24 global, 1 parent
    leagues   32 / 41
    nations  197 / 219
    874 unique files, about 33 MB

The 8 unmatched clubs are genuinely absent or ambiguous upstream and get
generated shields.  61 crests are legitimately shared by more than one club
(a women's side and its parent), so the manifest records 938 ids over 874 files.

Two matching problems are worth knowing about.  EA ships unlicensed clubs under
invented names - "Lombardia FC" is Inter and "Bergamo Calcio" is Atalanta - which
no similarity measure can resolve, so they are mapped explicitly.  And fuzzy
matching proposed several WRONG answers that would have shipped a rival's crest
(Stade Rennais -> Stade de Reims, Real Sociedad B -> Real Sociedad, Austria
Lustenau -> Austria Wien); every alias in the table was checked by eye and the
rejected proposals are recorded in a comment so they are not reintroduced.

The artwork is git-ignored (see LICENSING above).  A fresh clone with no cache
still renders all 717 clubs, all 41 leagues and all 219 nations from generated
geometry, which is the behaviour the verifier actually asserts.

PORTRAITS
    lib/faces.py accepts only freely-licensed images, behind two independent
    gates: licence_ok() refuses anything not explicitly free (a MISSING licence
    is a refusal, not a pass), and identity_ok() refuses the wrong human, since
    a name collision that ships another person's face is worse than no face.
    Network access is OFF by default (config faces_web); with it off the module
    reads the local cache and otherwise returns a generated avatar, so the game
    never silently phones out.  Accepted images are cached with their attribution
    and a line in data/graphics/faces/CREDITS.txt.  A network failure is NOT
    recorded as "no photo exists", so a transient error cannot poison the cache.

    The old lib/wiki.py photo fetchers requested iiprop=url|size|mime with no
    licence metadata at all.  They are unreachable from the server (only
    fetch_stadium is called) and were left alone rather than retrofitted; the
    new module is the only portrait path.

VERIFYING GRAPHICS
    python3 tools/verify_graphics.py                    # 175 checks, under 1 second
    python3 tools/verify_graphics.py --http http://127.0.0.1:8765   # 196 with a server
    python3 tools/mutate_graphics.py                    # 24 mutants, about 8 seconds

The portrait gates are tested against synthetic Commons payloads, not the live
API: the licence and identity decisions are pure functions, so they are verified
exhaustively offline.  THE LIVE NETWORK PATH IS NOT EXERCISED by these checks.

Mutation-tested 24/24.  Two weak checks were found and fixed during this step.
The traversal guard was only tested with paths ending in .py/.exe, which the
extension allowlist already rejected on its own, so removing the guard changed
nothing; it is now tested with ../../secret.svg and against a real file outside
the cache.  And the importer was only checked by reading the committed manifest,
which is a static file, so breaking the importer was invisible; the verifier now
RUNS it against a synthetic tarball where two clubs share one crest.

That second check guards a real bug found while building this: keying the
manifest by filename silently dropped 64 clubs whose crest was already present.

    Totals: verify_fc27 64 + verify_engine 131 + verify_backend 102
            + verify_graphics 175 = 472 checks passing.
    Mutation: mutate_backend 22/22, mutate_graphics 24/24.

WHAT IS STILL NOT BUILT
    * a UI on top of /api/engine/* (the old one is inert, by choice).  The
      graphics routes are ready for it to consume, but nothing draws them yet:
      the inert index.html does not call /api/crest or /api/face either.
    * cups and continental competition
    * a transfer market with negotiation and budgets actually spent
    * morale
    Rollover auto-renews expiring contracts until negotiation exists.

    Graphics limitations worth knowing: 8 clubs have no upstream crest and show
    a generated shield; 9 leagues and 22 nations likewise.  Portrait coverage is
    unmeasured - the live Commons path has never been exercised from this
    environment, so expect most of the 21,623 players (and the 265 unnamed
    managers) to show a generated avatar even with faces_web enabled.
