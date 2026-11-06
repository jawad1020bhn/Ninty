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
  tables: ['players', 'playernames', 'teams', 'teamplayerlinks', 'leagues', 'leagueteamlinks', 'nations'],
});
const T = Object.fromEntries(main.databases.flatMap(d => d.tables).map(t => [t.name, t.records]));
for (const k of ['players', 'playernames', 'teams', 'teamplayerlinks', 'leagues', 'leagueteamlinks', 'nations']) {
  if (!T[k]) { console.error('missing table: ' + k); process.exit(1); }
  console.log('  ' + k.padEnd(18) + T[k].length);
}

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
w('fc27_meta.json', {
  source: 'eafc-db-kit (MIT) bundled FC 27 main template',
  upstream: 'https://github.com/ViniMacacari/eafc-db-kit',
  generated: new Date().toISOString(), asOf: AS_OF,
  counts: { players: players.length, clubs: Object.keys(clubs).length, leagues: Object.keys(leagues).length, nations: Object.keys(nations).length },
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
console.log('\nleagues:');
for (const [id, l] of Object.entries(leagues)) console.log('  %s %s (%s, L%d) %d teams', id.padStart(4), l.name.padEnd(28), l.countryName.padEnd(16), l.level, l.teams.length);
