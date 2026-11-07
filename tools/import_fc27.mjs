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

// lib/dbimport.py AB order (25 PES attributes) <- FC 27 field names
const AB = ['OffensiveAwareness', 'BallControl', 'Dribbling', 'TightPossession', 'LowPass',
  'LoftedPass', 'Finishing', 'Heading', 'PlaceKicking', 'Curl', 'Speed', 'Acceleration',
  'KickingPower', 'Jump', 'PhysicalContact', 'Balance', 'Stamina', 'DefensiveAwareness',
  'BallWinning', 'Aggression', 'GKAwareness', 'GKCatching', 'GKClearing', 'GKReflexes', 'GKReach'];
const AB_SRC = ['positioning', 'ballcontrol', 'dribbling', '@tight', 'shortpassing',
  'longpassing', 'finishing', 'headingaccuracy', 'freekickaccuracy', 'curve', 'sprintspeed',
  'acceleration', 'shotpower', 'jumping', 'strength', 'balance', 'stamina',
  'defensiveawareness', 'standingtackle', 'aggression', 'gkpositioning', 'gkhandling',
  'gkkicking', 'gkreflexes', 'gkdiving'];

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
    'competition', 'competitionseeds'],
});
const T = Object.fromEntries(main.databases.flatMap(d => d.tables).map(t => [t.name, t.records]));
for (const k of ['players', 'playernames', 'teams', 'teamplayerlinks', 'leagues', 'leagueteamlinks', 'nations']) {
  if (!T[k]) { console.error('missing table: ' + k); process.exit(1); }
  console.log('  ' + k.padEnd(18) + T[k].length);
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
/* STATIC reference only. Season state (points, fixtures, results, budgets,
   form, injuries) is deliberately NOT extracted: the engine owns that and will
   keep it in its own save. The template's partial standings are not a played
   season (points are non-zero for only 295/870 clubs), so importing them would
   seed a career with contradictory numbers. */
const CLUB_IDS = new Set(Object.keys(clubs).map(Number));
const pidKnown = new Set(players.map(r => r[0]));

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
w('cups.json', cups);
w('prev_pos.json', prevPos);
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
console.log('\nleagues:');
for (const [id, l] of Object.entries(leagues)) console.log('  %s %s (%s, L%d) %d teams', id.padStart(4), l.name.padEnd(28), l.countryName.padEnd(16), l.level, l.teams.length);
