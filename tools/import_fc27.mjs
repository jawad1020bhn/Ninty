#!/usr/bin/env node
/**
 * import_fc27.mjs - BUILD-TIME ONLY: EA SPORTS FC 27 -> The Gaffer database.
 *
 * The runtime game stays pure-stdlib Python.  This script is the only place Node
 * is used, and only when you want to regenerate data/fc27/ from the upstream
 * eafc-db-kit templates.  The generated JSON is committed, so playing the game
 * needs no Node, no npm install and no network.
 *
 * Usage:
 *   node tools/import_fc27.mjs [--kit <path-to-eafc-db-kit>] [--out data/fc27]
 *                              [--as-of 2026-08-01]
 *
 * The kit is NOT vendored into this repo (it is ~208 MB).  Get it with:
 *   npm pack eafc-db-kit && tar xzf eafc-db-kit-*.tgz -C /tmp/kit
 *   node tools/import_fc27.mjs --kit /tmp/kit/package
 * or point EAFC_KIT at an existing checkout / node_modules install.
 *
 * Source: https://github.com/ViniMacacari/eafc-db-kit  (MIT, (c) 2026 ViniMacacari)
 * The bundled FC 27 tables are EA's game data; see data/fc27/NOTICE.txt.
 *
 * ---------------------------------------------------------------------------
 * Reverse-engineered conventions (verified against known players):
 *   playernames.nameid    -> firstnameid / lastnameid / commonnameid
 *   teams.assetid         -> teamplayerlinks.teamid
 *   leagueteamlinks       -> one row per team, gives its league
 *   birthdate             -> days since 1582-10-14 (Gregorian reform)
 *                            Messi 147811 = 1987-06-24, Ronaldo 146942 = 1985-02-05
 *   preferredfoot         -> 1 = right, 2 = left
 *   preferredposition1..7 -> EA 28-slot position enum (see EA_POS below)
 *
 * A player has SEVERAL teamplayerlinks (club + national + All-Star/Classic).
 * Picking the last one silently gives "Messi -> Argentina" and
 * "Kane -> Bayern Muenchen Classic", so club assignment filters by league kind.
 * ---------------------------------------------------------------------------
 */
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');

/* ------------------------------------------------------------------ args */
const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const OUT = resolve(ROOT, arg('--out', 'data/fc27'));
const AS_OF = arg('--as-of', '2026-08-01');          // FC 27 season start

const kitCandidates = [
  arg('--kit', ''),
  process.env.EAFC_KIT || '',
  resolve(ROOT, '../_vendor/kit/package'),
  resolve(ROOT, 'node_modules/eafc-db-kit'),
].filter(Boolean);
const KIT = kitCandidates.find(p => existsSync(join(p, 'dist', 'index.js')));
if (!KIT) {
  console.error('eafc-db-kit not found. Looked in:\n  ' + kitCandidates.join('\n  '));
  console.error('\nPass --kit <path> (see the header of this script).');
  process.exit(1);
}
console.log('kit:', KIT);
const { readTemplateDatabase } = await import(pathToFileURL(join(KIT, 'dist', 'index.js')).href);

/* --------------------------------------------------------------- mappings */
// EA 28-slot position enum -> our 13-slot POSN_ABBR index
// POSN_ABBR = GK CB LB RB DMF CMF LMF RMF AMF LWF RWF SS CF
const EA_POS = {
  0: 0,                     // GK
  1: 1,                     // SW  -> CB
  2: 3, 3: 3,               // RWB, RB
  4: 1, 5: 1, 6: 1,         // RCB, CB, LCB
  7: 2, 8: 2,               // LB, LWB
  9: 4, 10: 4, 11: 4,       // RDM, CDM, LDM
  12: 7,                    // RM
  13: 5, 14: 5, 15: 5,      // RCM, CM, LCM
  16: 6,                    // LM
  17: 8, 18: 8, 19: 8,      // RAM, CAM, LAM
  20: 10,                   // RF
  21: 11,                   // CF -> SS
  22: 9,                    // LF
  23: 10,                   // RW
  24: 12, 25: 12, 26: 12,   // RS, ST, LS
  27: 9,                    // LW
};
const POSN = ['GK', 'CB', 'LB', 'RB', 'DMF', 'CMF', 'LMF', 'RMF', 'AMF', 'LWF', 'RWF', 'SS', 'CF'];

// AB order (the legacy 25 attributes) <- FC 27 field names
const AB = ['OffensiveAwareness', 'BallControl', 'Dribbling', 'TightPossession', 'LowPass',
  'LoftedPass', 'Finishing', 'Heading', 'PlaceKicking', 'Curl', 'Speed', 'Acceleration',
  'KickingPower', 'Jump', 'PhysicalContact', 'Balance', 'Stamina', 'DefensiveAwareness',
  'BallWinning', 'Aggression', 'GKAwareness', 'GKCatching', 'GKClearing', 'GKReflexes', 'GKReach'];
const AB_SRC = ['positioning', 'ballcontrol', 'dribbling', '@tight', 'shortpassing',
  'longpassing', 'finishing', 'headingaccuracy', 'freekickaccuracy', 'curve', 'sprintspeed',
  'acceleration', 'shotpower', 'jumping', 'strength', 'balance', 'stamina',
  'defensiveawareness', 'standingtackle', 'aggression', 'gkpositioning', 'gkhandling',
  'gkkicking', 'gkreflexes', 'gkdiving'];

// EA's own attribute set, kept RAW and lossless alongside the legacy 25 above.
// The 25-attribute mapping is lossy: it has no slot for crossing, volleys, reactions,
// longshots, interceptions, vision, penalties, composure or slidingtackle, and
// it blends agility into TightPossession. A match engine wants the real values
// (an interceptor and a slider are not the same defender), so both are shipped:
// the legacy 25 keep the growth algorithm working, ea_attrs feeds the engine.
const EA_ATTRS = ['crossing', 'finishing', 'headingaccuracy', 'shortpassing', 'volleys',
  'dribbling', 'curve', 'freekickaccuracy', 'longpassing', 'ballcontrol', 'acceleration',
  'sprintspeed', 'agility', 'reactions', 'balance', 'shotpower', 'jumping', 'stamina',
  'strength', 'longshots', 'aggression', 'interceptions', 'positioning', 'vision',
  'penalties', 'composure', 'defensiveawareness', 'standingtackle', 'slidingtackle',
  'gkdiving', 'gkhandling', 'gkkicking', 'gkreflexes', 'gkpositioning'];

// Formations and players use the SAME 28-id enum but at different granularity.
// formations.positionN is side-specific (4 RCB, 6 LCB, 9 RDM, 24 RS...), while
// players.preferredpositionN only ever carries the coarse central id (5 CB,
// 10 CDM, 25 ST...). Verified: players use just 12 of the 28 ids, and 10 slot
// ids used by formations never appear on any player. Comparing them directly
// leaves 1998 of 7887 designated starters unable to fill their own club's
// formation. This map collapses a slot to the id a player can actually hold;
// with it, coverage is 7887/7887.
const SLOT_COMPAT = {
  1: 5, 2: 3, 4: 5, 6: 5, 8: 7, 9: 10, 11: 10, 13: 14, 15: 14,
  17: 18, 19: 18, 20: 23, 21: 25, 22: 27, 24: 25, 26: 25,
};
const slotCompat = {};
for (let i = 0; i < 28; i++) slotCompat[i] = SLOT_COMPAT[i] != null ? SLOT_COMPAT[i] : i;

// leagues that are NOT real club competitions
const SPECIAL = new Set([111, 382, 383, 2000, 2028, 2092, 2240, 2255, 2260, 2261, 2262, 2263]);
const REST = new Set([76, 2226]);
const CUP = new Set([1003, 1014]);

const clamp = (v, lo = 1, hi = 99) => Math.max(lo, Math.min(hi, Math.round(Number(v) || 0)));
const EPOCH = Date.UTC(1582, 9, 14);
const asOf = Date.parse(AS_OF + 'T00:00:00Z');
if (Number.isNaN(asOf)) { console.error('bad --as-of date: ' + AS_OF); process.exit(1); }
const ageOf = raw => {
  if (!raw) return 0;
  const b = new Date(EPOCH + raw * 86400000);
  const r = new Date(asOf);
  let a = r.getUTCFullYear() - b.getUTCFullYear();
  if (r.getUTCMonth() < b.getUTCMonth() ||
      (r.getUTCMonth() === b.getUTCMonth() && r.getUTCDate() < b.getUTCDate())) a--;
  return Math.max(15, Math.min(50, a));
};
const dobOf = raw => raw ? new Date(EPOCH + raw * 86400000).toISOString().slice(0, 10) : '';
const hex = (r, g, b) => '#' + [r, g, b].map(x => clamp(x, 0, 255).toString(16).padStart(2, '0')).join('');

/* ------------------------------------------------------------------- read */
console.log('reading FC 27 main + localization ...');
const main = await readTemplateDatabase({
  version: 'FC 27',
  tables: ['players', 'playernames', 'teams', 'teamplayerlinks', 'leagues', 'leagueteamlinks', 'nations',
    // engine-facing reference tables (venues, staff, kit numbers, XI, rivalries,
    // formations, loans, cup fields). Verified present in the FC 27 template.
    'stadiums', 'teamstadiumlinks', 'manager', 'playerloans', 'rivals', 'formations',
    'competition', 'competitionseeds',
    // career logic (r16). This reader takes an explicit allowlist: a table that
    // is not named here silently arrives as undefined, so every new extraction
    // must be added to this list as well as read below.
    'default_teamsheets', 'attributeprefpositionformula', 'attributecategorymap',
    'starratingboundaries', 'clubcoefficients', 'nationcoefficients',
    'career_calendar', 'multiclubownership', 'mls_group_structure',
    'competitionstadiumlinks', 'prevcompetitionstats', 'referee', 'leaguerefereelinks',
    'career_firstnames', 'career_lastnames', 'career_commonnames',
    'career_youthplayerposattributes', 'career_regenplayerattributes',
    'playstyle_attribute_requirement', 'teamnationlinks',
    // r17: a second pass over the tables r16 had dismissed as presentation
    // found these carry real career logic after all.
    'player_grudgelove', 'previousteam', 'teamcounterparts', 'bigmatchups',
    'career_createplayerattributes', 'MatchIntensity', 'BigAttendance', 'NoAttendance'],
});
const T = Object.fromEntries(main.databases.flatMap(d => d.tables).map(t => [t.name, t.records]));
for (const k of ['players', 'playernames', 'teams', 'teamplayerlinks', 'leagues', 'leagueteamlinks', 'nations']) {
  if (!T[k]) { console.error('missing table: ' + k); process.exit(1); }
  console.log('  ' + k.padEnd(18) + T[k].length);
}

// Guard: an absent table would otherwise be written out as an empty file.
for (const k of ['default_teamsheets', 'attributeprefpositionformula', 'clubcoefficients',
  'career_calendar', 'prevcompetitionstats', 'referee', 'career_firstnames',
  'career_regenplayerattributes', 'playstyle_attribute_requirement', 'teamnationlinks']) {
  if (!T[k] || !T[k].length) { console.error('missing/empty table: ' + k); process.exit(1); }
}

// Cup/trophy display names are not columns: they live in the localization
// bundle as LeagueName_<id> / TrophyName_<id>.
const loc = await readTemplateDatabase({ version: 'FC 27', database: 'localization' });
const LOC = new Map();
for (const t of loc.databases.flatMap(d => d.tables)) for (const s of t.records) LOC.set(s.stringid, s.sourcetext);
console.log('  localization'.padEnd(20) + LOC.size);
const compName = id => LOC.get('LeagueName_' + id) || LOC.get('TrophyName_' + id) || '';

const NAME = new Map(T.playernames.map(r => [r.nameid, r.name]));
const TEAM = new Map(T.teams.map(r => [r.assetid, r]));
const NATION = new Map(T.nations.map(r => [r.nationid, r]));
const LEAGUE = new Map(T.leagues.map(r => [r.leagueid, r]));
const TLEAGUE = new Map(T.leagueteamlinks.map(r => [r.teamid, r.leagueid]));

const kindOf = lid => {
  const l = LEAGUE.get(lid);
  if (!l) return 'special';
  if (l.isinternationalleague) return 'intl';
  if (CUP.has(lid)) return 'cup';
  if (REST.has(lid)) return 'rest';
  if (SPECIAL.has(lid)) return 'special';
  return 'league';
};
// Junk squads that live inside real leagues but are not football clubs.
const JUNK_TEAM = /^(Marketing Team\b|MLS All Stars$|.*\bAll[- ]Stars?$|Create Player\b|OTP\b)/i;

// "England Premier League (1)" -> "Premier League"
const ALIAS = { 95: ['USA '], 34: ['Holland '], 167: ['Korea '], 48: ['Turkey '], 25: ['Rep. Ireland '] };
const cleanLeague = l => {
  const raw = String(l.leaguename || '').replace(/\s*\(\d+\)\s*$/, '').trim();
  // "Rest of World Men" / "Rest of World Women": the country IS "Rest of World",
  // so stripping it would leave the meaningless names "Men" / "Women".
  if (REST.has(l.leagueid)) return raw;
  const nat = NATION.get(l.countryid);
  const prefixes = [...(ALIAS[l.countryid] || []), ...(nat ? [nat.nationname + ' '] : [])];
  for (const p of prefixes) {
    if (!raw.startsWith(p)) continue;
    const rest = raw.slice(p.length).trim();
    // "France 1 Women's League" -> stripping "France " leaves "1 Women's League",
    // so keep the country there.  But "1. Bundesliga" / "3. Liga" are proper
    // names on their own, so a leading "N." is fine to strip.
    if (!rest || (/^\d/.test(rest) && !/^\d+\.\s/.test(rest))) return raw;
    return rest;
  }
  return raw;
};

/* ------------------------------------------------- club assignment per player */
const linksBy = new Map();
for (const l of T.teamplayerlinks) {
  if (!linksBy.has(l.playerid)) linksBy.set(l.playerid, []);
  linksBy.get(l.playerid).push(l);
}
const RANK = { league: 0, rest: 1, cup: 2, intl: 3, special: 4 };
function pickClub(pid) {
  const ls = linksBy.get(pid) || [];
  const c = ls.map(l => {
    const lid = TLEAGUE.get(l.teamid);
    const lg = LEAGUE.get(lid);
    return { l, lid, kind: kindOf(lid), level: lg ? lg.level : 9, women: lg ? lg.iswomencompetition : 0 };
  }).filter(x => (x.kind === 'league' || x.kind === 'rest')
                 && !JUNK_TEAM.test(String((TEAM.get(x.l.teamid) || {}).teamname || '')));
  if (!c.length) return null;
  c.sort((a, b) => RANK[a.kind] - RANK[b.kind] || a.level - b.level || a.l.teamid - b.l.teamid);
  return c[0];
}

/* --------------------------------------------------------------- transform */
const players = [], ratings = {}, positions = {}, playpos = {}, nats = {}, pot = {}, dob = {}, extra = {};
const eaAttrs = {};   // raw EA attribute values, EA_ATTRS order
const eaPos = {};     // raw EA preferred positions, most preferred first
const squads = new Map();
let noClub = 0, noName = 0, women = 0;

for (const p of T.players) {
  const pid = p.playerid;
  const first = NAME.get(p.firstnameid) || '';
  const last = NAME.get(p.lastnameid) || '';
  const common = NAME.get(p.commonnameid) || '';
  const full = [first, last].filter(Boolean).join(' ').trim() || common;
  if (!full) { noName++; continue; }
  const short = common || last || full;

  const club = pickClub(pid);
  const tid = club ? club.l.teamid : 0;
  if (!club) noClub++;
  else {
    if (!squads.has(tid)) squads.set(tid, []);
    squads.get(tid).push(pid);
  }
  if (p.gender === 1) women++;

  const attrs = AB_SRC.map(k => k === '@tight'
    ? clamp((clamp(p.ballcontrol) * 2 + clamp(p.dribbling) + clamp(p.agility)) / 4)
    : clamp(p[k]));

  // Raw EA values, unclamped and unblended, in EA_ATTRS order.
  eaAttrs[String(pid)] = EA_ATTRS.map(k => Number(p[k]) || 0);

  // formations.json slots are EA position ids (4 = RCB, 11 = LDM, 25 = ST...).
  // The legacy 13-slot projection collapses those (RCB/LCB/CB -> CB), so matching a
  // player to a formation slot needs the raw list, in preference order.
  eaPos[String(pid)] = [1, 2, 3, 4, 5, 6, 7]
    .map(i => p['preferredposition' + i])
    .filter(v => v != null && v >= 0);

  const pp = new Array(13).fill(0);
  for (let i = 1; i <= 7; i++) {
    const ea = p['preferredposition' + i];
    if (ea == null || ea < 0) continue;
    const idx = EA_POS[ea];
    if (idx == null) continue;
    pp[idx] = Math.max(pp[idx], i === 1 ? 2 : 1);
  }
  const mainEa = p.preferredposition1;
  const pos = EA_POS[mainEa] != null ? EA_POS[mainEa] : (pp.findIndex(v => v > 0) + 1 || 5) - 1;
  if (!pp.some(v => v)) pp[pos] = 2;

  players.push([pid, full, short]);
  // [ovr, age, h, w, foot('True'=left), style, wfu, wfa, form, inj, attrs]
  ratings[String(pid)] = [
    clamp(p.overallrating), ageOf(p.birthdate), clamp(p.height, 130, 220), clamp(p.weight, 30, 130),
    p.preferredfoot === 2 ? 'True' : 'False',
    0,                                                   // playing style: none
    clamp(p.skillmoves, 1, 4),                             // weak-foot usage proxy
    clamp(p.weakfootabilitytypecode, 1, 4),
    4, 2,                                                // form (mid), injury resistance (mid)
    attrs,
  ];
  positions[String(pid)] = pos;
  playpos[String(pid)] = pp.join('');
  nats[pid] = p.nationality;
  pot[String(pid)] = clamp(p.potential);
  dob[String(pid)] = dobOf(p.birthdate);
  extra[String(pid)] = {
    value: Number(p.wage) || 0, contract: Number(p.contractvaliduntil) || 0,
    release: Number(p.releaseclause) || 0, intRep: Number(p.internationalrep) || 0,
    gender: Number(p.gender) || 0,
    natPos: (linksBy.get(pid) || []).filter(l => kindOf(TLEAGUE.get(l.teamid)) === 'intl').map(l => l.teamid),
    // r19: found by field-scanning the players table for career quantities the
    // importer had never read. joinedClub uses the same 1582 epoch as birthdate
    // and decodes correctly (van Dijk 2018-01-01, Messi 2023-07-16, Mbappe
    // 2024-07-01). Feeds squad tenure / homegrown / loyalty logic.
    joinedClub: dobOf(Number(p.playerjointeamdate) || 0),
    // growthprofile is 1..6 and tracks career stage: profile 6 averages age
    // 24.7 with +9.4 potential headroom, profile 4 age 30.6 with +1.4. Upstream
    // does not name the curves, so the id is shipped raw for the engine's
    // growth model rather than being mapped to an invented label.
    growthProfile: Number(p.growthprofile) || 0,
  };
}
players.sort((a, b) => a[0] - b[0]);

/* ----------------------------------------------------------- clubs/leagues */
const clubs = {}, leagues = {}, comps = {}, teamids = {};
for (const t of T.teams) {
  const lid = TLEAGUE.get(t.assetid);
  const lg = LEAGUE.get(lid);
  const kind = kindOf(lid);
  if (kind !== 'league' && kind !== 'rest') continue;      // skip intl / classic / all-star
  if (JUNK_TEAM.test(String(t.teamname || ''))) continue;  // marketing / all-star placeholders
  const tid = t.assetid;
  teamids[String(tid)] = t.teamname;
  clubs[String(tid)] = {
    name: t.teamname, league: lid, country: lg ? lg.countryid : 0,
    colors: [hex(t.teamcolor1r, t.teamcolor1g, t.teamcolor1b),
             hex(t.teamcolor2r, t.teamcolor2g, t.teamcolor2b),
             hex(t.teamcolor3r, t.teamcolor3g, t.teamcolor3b)],
    founded: Number(t.foundationyear) || 0, capacity: Number(t.teamstadiumcapacity) || 0,
    prestige: Number(t.domesticprestige) || 0, intlPrestige: Number(t.internationalprestige) || 0,
    worth: Number(t.clubworth) || 0, rival: Number(t.rivalteam) || 0,
    ovr: Number(t.matchdayoverallrating) || 0, att: Number(t.attackrating) || 0,
    mid: Number(t.midfieldrating) || 0, def: Number(t.defenserating) || 0,
    women: lg ? Number(lg.iswomencompetition) || 0 : 0,
  };
}
for (const l of T.leagues) {
  const kind = kindOf(l.leagueid);
  if (kind !== 'league' && kind !== 'rest') continue;
  const nm = cleanLeague(l);
  const teams = T.leagueteamlinks.filter(x => x.leagueid === l.leagueid).map(x => x.teamid)
    .filter(id => teamids[String(id)]).sort((a, b) => a - b);
  leagues[String(l.leagueid)] = {
    name: nm, raw: l.leaguename, country: l.countryid,
    countryName: (NATION.get(l.countryid) || {}).nationname || '',
    level: kind === 'rest' ? 1 : (Number(l.level) || 1),
    kind, women: Number(l.iswomencompetition) || 0, teams,
  };
  comps[String(l.leagueid)] = { name: nm, name_en: nm, kind: 'league' };
}
const nations = {};
for (const n of T.nations) nations[String(n.nationid)] = { name: n.nationname, iso: n.isocountrycode, confed: n.confederation };

const squadObj = {};
for (const [tid, ps] of squads) if (teamids[String(tid)]) squadObj[String(tid)] = ps.sort((a, b) => a - b);

/* ------------------------------------------- engine-facing reference data */
const CLUB_IDS = new Set(Object.keys(clubs).map(Number));
const pidKnown = new Set(players.map(r => r[0]));

// National teams. contract.json's natPos points at these ids, but they are not
// clubs and were deliberately excluded from clubs.json, which left those
// references dangling. Ship them in their own table so they resolve.
const natTeams = {};
const natSquads = new Map();
for (const l of (T.teamplayerlinks || [])) {
  if (kindOf(TLEAGUE.get(l.teamid)) !== 'intl') continue;
  if (!natSquads.has(l.teamid)) natSquads.set(l.teamid, []);
  if (pidKnown.has(l.playerid)) natSquads.get(l.teamid).push(l.playerid);
}
for (const l of (T.leagueteamlinks || [])) {
  const lg = LEAGUE.get(l.leagueid);
  if (!lg || !lg.isinternationalleague) continue;
  const t = TEAM.get(l.teamid);
  if (!t) continue;
  natTeams[String(l.teamid)] = {
    name: String(t.teamname || ''), gender: Number(t.gender) || 0,
    ovr: Number(t.matchdayoverallrating) || 0,
    league: Number(l.leagueid) || 0,
    colors: [hex(t.teamcolor1r, t.teamcolor1g, t.teamcolor1b),
      hex(t.teamcolor2r, t.teamcolor2g, t.teamcolor2b)],
    squad: (natSquads.get(l.teamid) || []).sort((a, b) => a - b),
  };
}

/* STATIC reference only. Season state (points, fixtures, results, budgets,
   form, injuries) is deliberately NOT extracted: the engine owns that and will
   keep it in its own save. The template's partial standings are not a played
   season (points are non-zero for only 295/870 clubs), so importing them would
   seed a career with contradictory numbers. */
// Venues: teams.teamstadiumcapacity is just a number. The name, city, country
// and pitch dimensions live in stadiums + teamstadiumlinks (870/870 resolve).
const STADIUM = new Map((T.stadiums || []).map(s => [s.stadiumid, s]));
const TSTADIUM = new Map((T.teamstadiumlinks || []).map(l => [l.teamid, l.stadiumid]));
const stadiums = {};
for (const s of (T.stadiums || [])) {
  if (!s.name) continue;
  stadiums[String(s.stadiumid)] = {
    name: String(s.name), capacity: Number(s.capacity) || 0,
    city: Number(s.cityid) || 0, country: Number(s.countrycode) || 0,
    home: Number(s.hometeamid) || 0, licensed: Number(s.islicensed) || 0,
    pitch: [Number(s.stadiumpitchlength) || 0, Number(s.stadiumpitchwidth) || 0],
  };
}
for (const [tid, c] of Object.entries(clubs)) {
  const sid = TSTADIUM.get(Number(tid));
  if (sid != null && STADIUM.has(sid) && stadiums[String(sid)]) c.stadium = sid;
}

// Managers: commonname where licensed, else firstname + surname. Many are
// generic placeholders with no name at all - keep stars/nationality anyway.
const managers = {};
for (const m of (T.manager || [])) {
  if (!CLUB_IDS.has(m.teamid)) continue;
  const nm = String(m.commonname || '').trim()
    || [m.firstname, m.surname].filter(Boolean).join(' ').trim();
  managers[String(m.teamid)] = {
    id: Number(m.managerid) || 0, name: nm,
    nation: Number(m.nationality) || 0, stars: Number(m.starrating) || 0,
    gender: Number(m.gender) || 0,
  };
}

// Kit numbers + the template's designated XI. teamplayerlinks.position doubles
// as a squad role: 0..27 = in the XI (with an EA position), 28 = sub, 29 =
// reserve. Verified: 856/860 clubs have exactly 11 entries below 28.
const squadMeta = {};
for (const l of (T.teamplayerlinks || [])) {
  if (!CLUB_IDS.has(l.teamid) || !pidKnown.has(l.playerid)) continue;
  const p = Number(l.position);
  const role = p >= 29 ? 2 : (p >= 28 ? 1 : 0);
  (squadMeta[String(l.teamid)] = squadMeta[String(l.teamid)] || {})[String(l.playerid)] =
    [Number(l.jerseynumber) || 0, role, role === 0 ? p : -1];
}

// Rivalries with intensity, richer than teams.rivalteam's single id.
const rivals = {};
for (const r of (T.rivals || [])) {
  const a = Number(r.teamid1), b = Number(r.teamid2);
  if (CLUB_IDS.has(a) && CLUB_IDS.has(b)) {
    (rivals[String(a)] = rivals[String(a)] || []).push([b, Number(r.team1intensity) || 0, Number(r.rivaltype) || 0]);
    (rivals[String(b)] = rivals[String(b)] || []).push([a, Number(r.team2intensity) || 0, Number(r.rivaltype) || 0]);
  }
}
for (const v of Object.values(rivals)) v.sort((x, y) => y[1] - x[1]);

// Formations: name, the 11 slots, per-slot roles and pitch offsets for the UI.
const r3 = n => Math.round(Number(n) * 1000) / 1000;
const formations = {};
for (const f of (T.formations || [])) {
  if (!CLUB_IDS.has(f.teamid)) continue;
  const pos = [], role = [], xy = [];
  for (let i = 0; i < 11; i++) {
    pos.push(Number(f['position' + i]));
    role.push(Number(f['pos' + i + 'role']) || 0);
    xy.push([r3(f['offset' + i + 'x']), r3(f['offset' + i + 'y'])]);
  }
  (formations[String(f.teamid)] = formations[String(f.teamid)] || []).push({
    id: Number(f.formationid) || 0, name: String(f.formationname || ''),
    pos, role, xy, attack: Number(f.offensiverating) || 0,
    lines: [Number(f.defenders) || 0, Number(f.midfielders) || 0, Number(f.attackers) || 0],
  });
}

// Reverse index pid -> current club, from the squads already resolved above.
const clubOfPid = new Map();
for (const [tid, ps] of Object.entries(squadObj)) for (const pid of ps) clubOfPid.set(pid, Number(tid));

// Loans: which club owns a player out on loan, and until when. loandateend uses
// the same 1582-10-14 day epoch as birthdate.
const loans = [];
for (const l of (T.playerloans || [])) {
  if (!pidKnown.has(l.playerid)) continue;
  const from = Number(l.teamidloanedfrom) || 0;
  loans.push({
    pid: l.playerid, from, fromName: (TEAM.get(from) || {}).teamname || '',
    to: clubOfPid.get(l.playerid) || 0, end: dobOf(l.loandateend),
    toBuy: Number(l.isloantobuy) || 0, futureOption: Number(l.futureoptiontobuy) || 0,
  });
}
loans.sort((a, b) => a.pid - b.pid);

// Player traits are BITFLAGS. The individual bit meanings are not documented in
// the template, so they are stored raw rather than guessed at.
const traits = {};
for (const p of T.players) {
  if (!pidKnown.has(p.playerid)) continue;
  traits[String(p.playerid)] = {
    t1: Number(p.trait1) >>> 0, t2: Number(p.trait2) >>> 0,
    retiring: Number(p.isretiring) || 0,
    smLikelihood: Number(p.skillmoveslikelihood) || 0,
    // Icon/Hero bitflags, separate from trait1/trait2 (327 and 30 players).
    // Raw for the same reason: the bit meanings are not documented upstream.
    icon1: Number(p.icontrait1) >>> 0, icon2: Number(p.icontrait2) >>> 0,
  };
}

// Cups and other non-league competitions.
//
// Identity (name, country, importance, trophy) is STATIC reference data the
// engine needs. Who qualifies is SEASON state the engine decides, so a cup is
// emitted whenever it has a name - requiring seeded teams here would drop the
// FA Cup, DFB-Pokal and Coppa Italia, which ship with empty seed tables.
// Template seeds are kept only as an optional starting hint.
const SEEDS = new Map();
for (const s of (T.competitionseeds || [])) {
  if (!SEEDS.has(s.competitionid)) SEEDS.set(s.competitionid, []);
  SEEDS.get(s.competitionid).push(s);
}
const cups = {};
let cupNoName = 0, cupSeeded = 0;
for (const c of (T.competition || [])) {
  const id = c.competitionid;
  if (LEAGUE.has(id)) continue;                       // leagues already emitted
  const nm = compName(id);
  if (!nm) { cupNoName++; continue; }                 // genuinely unnamed in loc
  // Seed teams are only a hint: keep the ones that are clubs we actually ship.
  const seeds = (SEEDS.get(id) || []).filter(s => CLUB_IDS.has(s.teamid));
  const groups = {};
  for (const s of seeds) (groups[String(s.group)] = groups[String(s.group)] || []).push(s.teamid);
  if (seeds.length) cupSeeded++;
  const cc = Number(c.country_lock);
  cups[String(id)] = {
    name: nm, kind: 'cup',
    // country_lock is -1 for many licensed cups (DFB-Pokal, Coupe de France);
    // that means "not locked in the data", not "unknown country." Do not guess.
    country: Number.isFinite(cc) ? cc : -1,
    countryName: (NATION.get(cc) || {}).nationname || '',
    importance: Number(c.competitionimportance) || 0,
    women: Number(c.iswomencompetition) || 0, real: Number(c.isrealcompetition) || 0,
    trophy: Number(c.hastrophy) || 0,
    seeded: seeds.length > 0, groups,
    teams: [...new Set(seeds.map(s => s.teamid))].sort((a, b) => a - b),
  };
}

// Last season's finish per club: useful for reputation, board expectations and
// continental qualification. This is a real static column (870/870 populated),
// unlike the template's half-filled current standings.
const prevPos = {};
for (const l of (T.leagueteamlinks || [])) {
  if (!CLUB_IDS.has(l.teamid)) continue;
  prevPos[String(l.teamid)] = {
    prev: Number(l.previousyeartableposition) || 0,
    prevLeague: Number(l.prevleagueid) || 0,
  };
}

/* ------------------------------------------------- r16: engine tables ---
 * Found by sweeping all 268 upstream tables for non-empty ones the importer
 * did not read. Of 215 non-empty tables, most are presentation-only (skins,
 * crowds, kits, vanity, audio) and stay out. These carry career logic.
 */

// Captain + set-piece takers. 717/717 clubs, every taker verified in-squad.
const teamsheets = {};
for (const r of (T.default_teamsheets || [])) {
  if (!CLUB_IDS.has(r.teamid)) continue;
  const pick = f => (r[f] > 0 && pidKnown.has(r[f]) ? r[f] : null);
  teamsheets[String(r.teamid)] = {
    captain: pick('captainid'),
    penalty: pick('penaltytakerid'),
    freeKick: pick('freekicktakerid'),
    leftFreeKick: pick('leftfreekicktakerid'),
    rightFreeKick: pick('rightfreekicktakerid'),
    leftCorner: pick('leftcornerkicktakerid'),
    rightCorner: pick('rightcornerkicktakerid'),
    longKick: pick('longkicktakerid'),
  };
}

// EA's own per-position rating weights (percentages sum to 100 per position).
// WARNING: `attribute` here is EA's INTERNAL attribute enum, which is NOT the
// players-table field order used by ea_attrs.json. Assuming identity puts only
// 29% of players top in their own position (van Dijk rated higher at ST than
// CB). An unconstrained fit reached just 48% and still made impossible
// assignments - a GK formula weighting freekickaccuracy while gkkicking sat
// outside it - and attributecategorymap contradicts it (ids 29..33 are the five
// GK fields, all weight 0). Five ids (3,9,17,27,28) appear in no formula at all
// and cannot be identified. So the ids are shipped RAW and UNMAPPED: do not
// index ea_attrs with them. Kept because the weights themselves are real.
const ovrWeights = {};
for (const r of (T.attributeprefpositionformula || [])) {
  (ovrWeights[String(r.position)] ||= []).push([r.attribute, r.percentage]);
}
for (const v of Object.values(ovrWeights)) v.sort((x, y) => y[1] - x[1]);
const attrCategories = (T.attributecategorymap || [])
  .slice().sort((a, b) => a.attribute - b.attribute)
  .map(r => ({ attr: r.attribute, category: r.category, gkCategory: r.gkcategory,
               weight: Math.round(r.weight * 1000) / 1000 }));
const starBounds = (T.starratingboundaries || [])
  .slice().sort((a, b) => a.starratingfrom - b.starratingfrom)
  .map(r => ({ stars: r.stars, from: r.starratingfrom, to: r.starratingto }));

// UEFA-style coefficients: 5 yearly scores + total, for seeding/reputation.
const clubCoeff = {};
for (const r of (T.clubcoefficients || [])) {
  if (!CLUB_IDS.has(r.teamid)) continue;
  clubCoeff[String(r.teamid)] = {
    points: r.points, years: [r.year1, r.year2, r.year3, r.year4, r.year5],
  };
}
const nationCoeff = {};
for (const r of (T.nationcoefficients || [])) {
  nationCoeff[String(r.countryid)] = {
    points: r.points, years: [r.year1, r.year2, r.year3, r.year4, r.year5],
  };
}

// Transfer windows as MMDD (701 = 1 Jul, 831 = 31 Aug, 101/131 = January).
// The absolute dates in this table are a 2008 placeholder - do NOT use them.
const cal = (T.career_calendar || [])[0] || {};
const mmdd = v => (v > 0 ? { month: Math.floor(v / 100), day: v % 100 } : null);
const calendar = {
  windows: [
    { open: mmdd(cal.transferwindowstart1), close: mmdd(cal.transferwindowend1) },
    { open: mmdd(cal.transferwindowstart2), close: mmdd(cal.transferwindowend2) },
  ].filter(x => x.open && x.close),
  note: 'month/day only; the template absolute dates are a 2008 placeholder',
};

// Multi-club ownership: blocks transfers between clubs in the same group.
const ownGroups = new Map();
for (const r of (T.multiclubownership || [])) {
  if (!CLUB_IDS.has(r.teamid)) continue;
  if (!ownGroups.has(r.multiclubid)) ownGroups.set(r.multiclubid, []);
  ownGroups.get(r.multiclubid).push({ tid: r.teamid, seniority: r.seniority });
}
const ownership = {};
for (const [gid, arr] of ownGroups) {
  if (arr.length < 2) continue;
  arr.sort((a, b) => a.seniority - b.seniority);
  for (const c of arr) {
    ownership[String(c.tid)] = {
      group: gid, seniority: c.seniority,
      siblings: arr.filter(x => x.tid !== c.tid).map(x => x.tid),
    };
  }
}

// MLS conference split (the only league upstream ships a group structure for).
const leagueGroups = {};
for (const r of (T.mls_group_structure || [])) {
  if (!CLUB_IDS.has(r.teamid)) continue;
  leagueGroups[String(r.teamid)] = r.groupid;
}

// Neutral/final venues per competition.
const compVenues = {};
for (const r of (T.competitionstadiumlinks || [])) {
  const k = String(r.competitionid);
  (compVenues[k] ||= []).push({ stadium: r.stadiumid, final: !!r.iscupfinal });
}

// Last season's per-competition player stats - real history to seed the first
// season's awards/reputation. Keyed pid -> rows (a player can appear in several
// competitions, and a few pid/comp pairs repeat upstream, so keep them all).
const prevStats = {};
for (const r of (T.prevcompetitionstats || [])) {
  if (!pidKnown.has(r.playerid)) continue;
  (prevStats[String(r.playerid)] ||= []).push([
    r.competitionid, r.appearances, r.goals, r.assists,
    r.yellowcards, r.redcards, r.cleansheets,
  ]);
}

// Referees: strictness feeds card/foul rates in match simulation.
const referees = {};
for (const r of (T.referee || [])) {
  referees[String(r.refereeid)] = {
    name: [r.firstname, r.surname].filter(Boolean).join(' '),
    nation: r.nationalitycode, league: r.leagueid,
    cards: r.cardstrictness, fouls: r.foulstrictness, real: !!r.isreal,
  };
}
const leagueRefs = {};
for (const r of (T.leaguerefereelinks || [])) {
  (leagueRefs[String(r.leagueid)] ||= []).push(r.refereeid);
}

// Regen/youth name pools. groupid is a language/region pool, NOT a nation id
// (no upstream table maps the two), so it is kept as an opaque pool id.
const nameOf = id => NAME.get(id) || '';
const regenNames = { first: [], last: [], common: [] };
for (const r of (T.career_firstnames || [])) {
  const n = nameOf(r.firstname);
  if (n) regenNames.first.push([n, r.groupid, r.gender]);
}
for (const r of (T.career_lastnames || [])) {
  const n = nameOf(r.lastname);
  if (n) regenNames.last.push([n, r.groupid, r.gender]);
}
for (const r of (T.career_commonnames || [])) {
  const n = [nameOf(r.firstname), nameOf(r.lastname)].filter(Boolean).join(' ');
  if (n) regenNames.common.push([n, r.groupid, r.gender]);
}

// Attribute templates for generated players, by position group and age.
// Youth ages are months (140..176); regen ages are years (16..21).
const tplRow = r => {
  const o = { posGroup: r.playerposgroup, age: r.age };
  for (const f of EA_ATTRS) if (r[f] != null) o[f] = r[f];
  if (r.overall != null) o.overall = r.overall;
  if (r.potential != null) o.potential = r.potential;
  return o;
};
const regenTemplates = {
  youthAgeUnit: 'months', regenAgeUnit: 'years',
  youth: (T.career_youthplayerposattributes || []).map(tplRow),
  regen: (T.career_regenplayerattributes || []).map(tplRow),
};

// PlayStyle unlock thresholds. `attributeid` uses the same unresolved EA
// internal enum as ovr_weights.json, so these are shipped raw too. Names come from
// localization (txt_signature_playstyle_N); only the signature subset is
// named upstream. NOTE: players.trait1/trait2 could NOT be mapped to these ids
// (tested every bit against every requirement set: best F1 0.32), so traits
// stay raw and this table is offered as thresholds only, not a decode.
const playstyleNames = {};
for (let i = 0; i < 64; i++) {
  const v = LOC.get('txt_signature_playstyle_' + i);
  if (v) playstyleNames[i] = v;
}
const playstyles = {};
for (const r of (T.playstyle_attribute_requirement || [])) {
  const k = String(r.playstyleid);
  (playstyles[k] ||= { name: playstyleNames[k] || '', requires: [] }).requires
    .push([r.attributeid, r.value]);
}

// National team -> nation id (teamnationlinks), so intl squads can be tied to
// the nation whose players they draw from.
const TNATION = new Map((T.teamnationlinks || []).map(r => [r.teamid, r.nationid]));
for (const [tid, t] of Object.entries(natTeams)) {
  const n = TNATION.get(Number(tid));
  if (n != null) t.nation = n;
}

/* ------------------------------------------------- r17: second-pass audit ---
 * r16 called the remaining non-empty tables "presentation-only". Re-checking
 * them individually showed that was too sweeping: these carry career logic.
 * Still excluded, with reasons verified rather than assumed:
 *   agents (29)      - every row is "Agent Test N"; 0 real names.
 *   sponsors (392)   - names are texture asset keys (dynamic_01,
 *                      Tottenham_Hotelscom), no contract/value fields.
 *   competitionmatchups (450) - a partial pot draw for the 4 UEFA cups, not a
 *                      fixture list; the draw is season state the engine owns.
 *   cm_* / level_caps - Pro Clubs archetype XP, not manager career.
 *   height_weight_impact, createplayerpositiontemplates, turfattributesmap -
 *                      further unresolved attribute id spaces (the latter uses
 *                      ids 75..111, outside the 34-field range entirely).
 *   positionbonus, rankweight - every value is 0.
 */

// Player -> club emotional ties. Feeds transfer willingness (a player with a
// strong tie to a rival is a harder sell). 303 rows, all players known; the
// club ids include 5 national teams, which resolve via national_teams.json.
const affinities = {};
for (const r of (T.player_grudgelove || [])) {
  if (!pidKnown.has(r.playerid)) continue;
  (affinities[String(r.playerid)] ||= []).push([r.emotional_teamid, r.level_of_emotion]);
}
for (const v of Object.values(affinities)) v.sort((a, b) => b[1] - a[1]);

// Former club - verified none of these players is still at that club.
const formerClubs = {};
for (const r of (T.previousteam || [])) {
  if (!pidKnown.has(r.playerid) || !(r.previousteamid > 0)) continue;
  formerClubs[String(r.playerid)] = r.previousteamid;
}

// Men's <-> women's side of the same club (64 pairs, all real clubs).
const counterparts = {};
for (const r of (T.teamcounterparts || [])) {
  const m = String(r.maleteamid), f = String(r.femaleteamid);
  if (!CLUB_IDS.has(r.maleteamid) || !CLUB_IDS.has(r.femaleteamid)) continue;
  counterparts[m] = r.femaleteamid;
  counterparts[f] = r.maleteamid;
}

// Marquee fixtures. Only 7 of 38 overlap rivals.json, so this is genuinely
// extra signal. Upstream is not symmetric (2/38 reversed), so normalise.
const bigSet = new Set();
const bigMatches = [];
for (const r of (T.bigmatchups || [])) {
  if (!CLUB_IDS.has(r.teamid1) || !CLUB_IDS.has(r.teamid2)) continue;
  const a = Math.min(r.teamid1, r.teamid2), b = Math.max(r.teamid1, r.teamid2);
  const k = a + ':' + b;
  if (bigSet.has(k)) continue;
  bigSet.add(k);
  bigMatches.push([a, b]);
}
bigMatches.sort((x, y) => x[0] - y[0] || x[1] - y[1]);

// Match tuning: intensity by score difference x minute bucket, and the
// attendance-emotion bands for big matches vs no crowd.
const buckets = [15, 30, 45, 60, 75, 90, 120];
const matchTuning = {
  intensityMinutes: buckets,
  intensity: (T.MatchIntensity || []).slice().sort((a, b) => a.scorediff - b.scorediff)
    .map(r => ({ scoreDiff: r.scorediff, byMinute: buckets.map(m => r['time' + m]) })),
  attendance: {
    big: (T.BigAttendance || []).slice().sort((a, b) => a.emotion - b.emotion)
      .map(r => ({ emotion: r.emotion, min: r.min, max: r.max })),
    none: (T.NoAttendance || []).slice().sort((a, b) => a.emotion - b.emotion)
      .map(r => ({ emotion: r.emotion, min: r.min, max: r.max })),
  },
};

// Create-player attribute templates by position group, age range and OVR band.
// Keyed by FIELD NAME (safe), unlike the unresolved enum tables.
regenTemplates.create = (T.career_createplayerattributes || []).map(r => {
  const o = tplRow(r);
  o.ageMin = r.agemin; o.ageMax = r.agemax;
  o.overallMin = r.overallmin; o.overallMax = r.overallmax;
  delete o.age;
  return o;
});

// Some shipped rows reference teams outside the 717-club universe: the
// CONMEBOL Libertadores/Sudamericana sides (Flamengo, Corinthians, Penarol...).
// They appear in affinities and former_clubs, and as cup seeds. Rather than
// drop real history or leave dangling ids, collect every referenced id that
// resolves to neither clubs.json nor national_teams.json and ship its name.
// Computed from the emitted structures, so new references are covered too.
const externalTeams = {};
const noteRef = id => {
  if (!(id > 0)) return;
  const k = String(id);
  if (clubs[k] || natTeams[k] || externalTeams[k]) return;
  const t = TEAM.get(id);
  if (!t) return;
  const lid = TLEAGUE.get(id);
  externalTeams[k] = { name: t.teamname || '', competition: lid || 0,
                       competitionName: lid ? compName(lid) : '' };
};
for (const v of Object.values(affinities)) for (const [t] of v) noteRef(t);
for (const t of Object.values(formerClubs)) noteRef(t);
for (const v of Object.values(ownership)) for (const t of v.siblings) noteRef(t);
for (const v of Object.values(rivals)) for (const r of v) noteRef(r[0]);
for (const l of loans) { noteRef(l.from); noteRef(l.to); }
for (const c of Object.values(cups)) for (const t of (c.teams || [])) noteRef(t);
for (const [a, b] of bigMatches) { noteRef(a); noteRef(b); }
for (const t of Object.values(counterparts)) noteRef(t);

/* ------------------------------------------------------------------ write */
mkdirSync(OUT, { recursive: true });
const w = (f, o) => writeFileSync(join(OUT, f), JSON.stringify(o), 'utf8');
w('players.json', players);
w('ratings.json', { ab: AB, f: 'o,age,h,w,foot,style,wfu,wfa,form,inj,stats', p: ratings });
w('positions.json', positions);
w('playpos.json', playpos);
w('teamids.json', teamids);
w('comps.json', comps);
w('clubs.json', clubs);
w('leagues.json', leagues);
w('squads.json', squadObj);
w('nations.json', nations);
w('nats.json', nats);
w('potential.json', pot);
w('birthdays.json', dob);
w('contract.json', extra);
w('stadiums.json', stadiums);
w('managers.json', managers);
w('squad_meta.json', squadMeta);
w('rivals.json', rivals);
w('formations.json', formations);
w('loans.json', loans);
w('traits.json', traits);
w('ea_attrs.json', { ab: EA_ATTRS, p: eaAttrs });
w('ea_positions.json', { enum: EA_POS, slotCompat, p: eaPos });
w('national_teams.json', natTeams);
w('cups.json', cups);
w('prev_pos.json', prevPos);
w('teamsheets.json', teamsheets);
w('ovr_weights.json', {
  attrIdSpace: 'EA internal attribute enum - NOT ea_attrs.json field order; unresolved, do not index ea_attrs with these ids',
  positions: ovrWeights, categories: attrCategories, stars: starBounds,
});
w('coefficients.json', { clubs: clubCoeff, nations: nationCoeff });
w('calendar.json', calendar);
w('ownership.json', ownership);
w('league_groups.json', leagueGroups);
w('comp_venues.json', compVenues);
w('prev_stats.json', { f: 'comp,apps,goals,assists,yellow,red,cleanSheets', p: prevStats });
w('referees.json', { refs: referees, leagues: leagueRefs });
w('regen_names.json', regenNames);
w('regen_templates.json', regenTemplates);
w('playstyles.json', playstyles);
w('affinities.json', affinities);
w('former_clubs.json', formerClubs);
w('counterparts.json', counterparts);
w('big_matches.json', bigMatches);
w('match_tuning.json', matchTuning);
w('external_teams.json', externalTeams);
w('fc27_meta.json', {
  source: 'eafc-db-kit (MIT) bundled FC 27 main template',
  upstream: 'https://github.com/ViniMacacari/eafc-db-kit',
  generated: new Date().toISOString(), asOf: AS_OF,
  counts: {
    players: players.length, clubs: Object.keys(clubs).length, leagues: Object.keys(leagues).length, nations: Object.keys(nations).length,
    stadiums: Object.keys(stadiums).length, managers: Object.keys(managers).length,
    cups: Object.keys(cups).length, loans: loans.length,
    rivalPairs: Object.values(rivals).reduce((n, v) => n + v.length, 0) / 2,
    formations: Object.values(formations).reduce((n, v) => n + v.length, 0),
  },
  cupsSkipped: { noName: cupNoName }, cupsWithTemplateSeeds: cupSeeded,
  squadRole: { 0: 'starting XI', 1: 'substitute', 2: 'reserve' },
  notExtracted: ['points', 'fixtures', 'results', 'budgets', 'form', 'injuries', 'market value'],
  notExtractedWhy: 'season state belongs to the engine save; market value is not a column in FC 27 (only wage/releaseclause), so the engine derives it',
  skipped: { noName, noClub, womenPlayers: women },
  posn: POSN, ab: AB, abSource: AB_SRC, eaPos: EA_POS,
  eaAttrs: EA_ATTRS,
  eaPositionsNote: 'ea_positions.json holds raw EA slot ids in preference order; formations.json uses the same enum but side-specific slots. Use its slotCompat map to collapse a formation slot to the coarse id a player can hold. positions.json/playpos.json are the lossy legacy 13-slot projection.',
  slotCompat: SLOT_COMPAT,
  nationalTeams: Object.keys(natTeams).length,
  teamsheets: Object.keys(teamsheets).length,
  ovrWeightPositions: Object.keys(ovrWeights).length,
  clubCoefficients: Object.keys(clubCoeff).length,
  nationCoefficients: Object.keys(nationCoeff).length,
  ownershipGroups: new Set(Object.values(ownership).map(o => o.group)).size,
  referees: Object.keys(referees).length,
  prevStatPlayers: Object.keys(prevStats).length,
  regenNames: { first: regenNames.first.length, last: regenNames.last.length, common: regenNames.common.length },
  regenTemplates: { youth: regenTemplates.youth.length, regen: regenTemplates.regen.length },
  playstyles: Object.keys(playstyles).length,
  affinityPlayers: Object.keys(affinities).length,
  formerClubs: Object.keys(formerClubs).length,
  counterpartClubs: Object.keys(counterparts).length,
  bigMatches: bigMatches.length,
  createTemplates: regenTemplates.create.length,
  externalTeams: Object.keys(externalTeams).length,
  joinedClubDates: Object.values(extra).filter(e => e.joinedClub).length,
  growthProfiles: [...new Set(Object.values(extra).map(e => e.growthProfile))].sort(),
  growthProfileNote: 'raw 1..6 career-stage id; upstream does not name the curves. Observed: profile 6 mean age 24.7 / +9.4 potential headroom, profile 4 mean age 30.6 / +1.4.',
  iconTraits: 'icontrait1/icontrait2 shipped raw in traits.json (327 / 30 players); bit meanings undocumented',
  externalTeamsNote: 'team ids referenced by shipped rows but outside clubs.json/national_teams.json (CONMEBOL sides). Names are shipped so no reference dangles; they are not playable clubs in this database.',
  affinityNote: 'level_of_emotion is shipped raw; upstream does not document the scale. Observed: Iniesta->Barcelona 7, Iniesta->Athletic Club 1, Buffon->Juventus 6, consistent with low=grudge / high=affection, but that reading is inferred, not confirmed.',
  stillExcluded: {
    agents: 'all 29 rows are "Agent Test N" placeholders',
    sponsors: 'names are texture asset keys, no contract or value fields',
    competitionmatchups: 'partial UEFA pot draw, not fixtures; a draw is engine season state',
    cmTables: 'Pro Clubs archetype XP, not manager career',
    heightWeightImpact: 'unresolved attribute id space',
    createplayerpositiontemplates: 'attribute ids 75..111, outside the 34-field range',
    positionBonus: 'every value is 0',
  },
  attrIdSpaceNote: 'ovr_weights.json and playstyles.json reference EA\'s internal attribute enum, which is NOT the ea_attrs.json field order and could not be resolved (identity mapping tops only 29% of players in their own position; best fit 48% with impossible assignments). Ids are shipped raw and unmapped; the star bands in ovr_weights.json are rating-based and safe to use.',
  traitsNote: 'trait1/trait2 remain RAW: no defensible mapping to playstyle ids was found (best F1 0.32 across every bit/requirement pairing), so playstyles.json ships unlock thresholds only',
  calendarNote: 'transfer windows are month/day; template absolute dates are a 2008 placeholder and are not shipped',
  eaAttrsNote: 'raw EA values, lossless; the legacy 25 in ratings.json are a lossy projection kept for the growth algorithm',
  ab25ProjectionDrops: ['crossing', 'volleys', 'reactions', 'longshots', 'interceptions',
    'vision', 'penalties', 'composure', 'slidingtackle', 'agility (blended into TightPossession)'],
  birthEpoch: '1582-10-14', foot: { 1: 'R', 2: 'L' },
});

/* ------------------------------------------------------------- diagnostics */
console.log('\n--- written to ' + OUT + ' ---');
console.log('players %d | clubs %d | leagues %d | nations %d',
  players.length, Object.keys(clubs).length, Object.keys(leagues).length, Object.keys(nations).length);
console.log('skipped: noName=%d | no real club=%d | women=%d', noName, noClub, women);
const TN = new Map(Object.entries(teamids).map(([k, v]) => [Number(k), v]));
const NM = new Map(players.map(r => [r[0], r[2]]));
console.log('\nspot check (club must be the real one, not national/classic):');
for (const id of [158023, 20801, 231747, 202126, 192985, 239085, 203376]) {
  const r = ratings[String(id)];
  if (!r) { console.log('  ' + id + ' MISSING'); continue; }
  const sq = Object.entries(squadObj).find(([, v]) => v.includes(id));
  console.log('  %s | %s | OVR %d POT %d | age %d | %s | %s | %s',
    String(NM.get(id)).padEnd(20), POSN[positions[String(id)]].padEnd(3),
    r[0], pot[String(id)], r[1], r[4] === 'True' ? 'L' : 'R',
    dob[String(id)], sq ? TN.get(Number(sq[0])) : '(no club)');
}
const sizes = Object.entries(squadObj).map(([k, v]) => [TN.get(Number(k)), v.length]).sort((a, b) => b[1] - a[1]);
console.log('\nlargest squads:', sizes.slice(0, 5).map(x => x.join('=')).join(', '));
console.log('smallest squads:', sizes.slice(-5).map(x => x.join('=')).join(', '));
console.log('  ea attrs   %d players x %d raw EA attributes (%d dropped by the 25-attribute projection)',
  Object.keys(eaAttrs).length, EA_ATTRS.length, 10);
console.log('  ea pos     %d players | national teams %d (%d capped players)',
  Object.keys(eaPos).length, Object.keys(natTeams).length,
  Object.values(natTeams).reduce((n, t) => n + t.squad.length, 0));
{
  let ok = 0, tot = 0;
  for (const [tid, fs] of Object.entries(formations)) {
    const slots = new Set(fs[0].pos.map(s => slotCompat[s]));
    for (const [pid, v] of Object.entries(squadMeta[tid] || {})) {
      if (v[1] !== 0) continue;
      tot++;
      if ((eaPos[pid] || []).some(p => slots.has(slotCompat[p]))) ok++;
    }
  }
  console.log('  slot fit   %d/%d designated starters match a slot of their club formation', ok, tot);
}
console.log('\nengine reference data:');
console.log('  stadiums   %d (%d/%d clubs linked)', Object.keys(stadiums).length,
  Object.values(clubs).filter(c => c.stadium != null).length, Object.keys(clubs).length);
console.log('  managers   %d (%d named)', Object.keys(managers).length, Object.values(managers).filter(m => m.name).length);
console.log('  squad meta %d clubs | XI %d | subs %d | reserves %d', Object.keys(squadMeta).length,
  ...[0, 1, 2].map(r => Object.values(squadMeta).reduce((n, m) => n + Object.values(m).filter(v => v[1] === r).length, 0)));
console.log('  rivalries  %d pairs | formations %d | loans %d',
  Object.values(rivals).reduce((n, v) => n + v.length, 0) / 2,
  Object.values(formations).reduce((n, v) => n + v.length, 0), loans.length);
console.log('  cups       %d named (%d with template seeds; %d unnamed skipped)', Object.keys(cups).length, cupSeeded, cupNoName);
for (const id of ['201', '202', '206', '208', '210', '223', '224', '1003']) {
  const c = cups[id];
  if (c) console.log('    %s %s - %s, seeds %d', id.padStart(5), c.name.padEnd(30), (c.countryName || 'not country-locked').padEnd(14), c.teams.length);
}
const liv = formations['9'];
if (liv) console.log('  Liverpool formation: %s (id %d)', liv[0].name, liv[0].id);
const anfield = clubs['9'] && clubs['9'].stadium;
if (anfield) console.log('  Liverpool stadium: %s (%s seats)', stadiums[String(anfield)].name, stadiums[String(anfield)].capacity);
console.log('\ncareer logic tables (r16):');
console.log('  teamsheets %d clubs (captain + 7 set-piece takers)', Object.keys(teamsheets).length);
console.log('  ovr weights %d positions | %d star bands', Object.keys(ovrWeights).length, starBounds.length);
console.log('  coefficients %d clubs / %d nations | ownership %d clubs in %d groups',
  Object.keys(clubCoeff).length, Object.keys(nationCoeff).length, Object.keys(ownership).length,
  new Set(Object.values(ownership).map(o => o.group)).size);
console.log('  windows %s | referees %d | prev stats %d players',
  calendar.windows.map(x => `${x.open.month}/${x.open.day}-${x.close.month}/${x.close.day}`).join(', '),
  Object.keys(referees).length, Object.keys(prevStats).length);
console.log('  regen names %d first / %d last / %d common | templates %d youth + %d regen',
  regenNames.first.length, regenNames.last.length, regenNames.common.length,
  regenTemplates.youth.length, regenTemplates.regen.length);
console.log('  playstyles %d (%d named) - thresholds only, traits stay raw',
  Object.keys(playstyles).length, Object.values(playstyles).filter(p => p.name).length);
console.log('\nsecond-pass career tables (r17):');
console.log('  affinities %d players | former clubs %d | counterparts %d clubs',
  Object.keys(affinities).length, Object.keys(formerClubs).length, Object.keys(counterparts).length);
console.log('  big matches %d pairs | create templates %d | intensity rows %d',
  bigMatches.length, regenTemplates.create.length, matchTuning.intensity.length);
console.log('  external teams %d (referenced but outside the club universe)', Object.keys(externalTeams).length);
console.log('  joined-club dates %d | growth profiles %s | icon traits %d/%d',
  Object.values(extra).filter(e => e.joinedClub).length,
  [...new Set(Object.values(extra).map(e => e.growthProfile))].sort().join(','),
  Object.values(traits).filter(t => t.icon1).length, Object.values(traits).filter(t => t.icon2).length);
console.log('\nleagues:');
for (const [id, l] of Object.entries(leagues)) console.log('  %s %s (%s, L%d) %d teams', id.padStart(4), l.name.padEnd(28), l.countryName.padEnd(16), l.level, l.teams.length);
