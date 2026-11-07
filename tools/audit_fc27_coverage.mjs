#!/usr/bin/env node
/**
 * audit_fc27_coverage.mjs - BUILD-TIME ONLY: account for every upstream table.
 *
 * Writes data/fc27/COVERAGE.txt, which records for each of the 268 tables in
 * the FC 27 template whether it is extracted, empty upstream, excluded after
 * inspection (with the reason), or triaged by family only. It exists so the
 * completeness claim is checkable instead of asserted - and so the next person
 * can see WHY something was left out before re-adding it.
 *
 * The "read" list is derived from tools/import_fc27.mjs itself, so it cannot
 * drift from what the importer actually does. The exclusion reasons are the
 * findings of the r16/r17 probes; if you re-probe a table, update it here.
 *
 * Usage:
 *   node tools/audit_fc27_coverage.mjs [--kit <path>] [--out data/fc27/COVERAGE.txt]
 *
 * Same kit resolution as the importer (--kit, EAFC_KIT, node_modules).
 * Exits non-zero if any table ends up unaccounted for.
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };
const kitCandidates = [
  arg('--kit', ''),
  process.env.EAFC_KIT || '',
  resolve(ROOT, '../_vendor/kit/package'),
  resolve(ROOT, 'node_modules/eafc-db-kit'),
].filter(Boolean);
const KIT = kitCandidates.find(p => existsSync(join(p, 'dist', 'index.js')));
if (!KIT) {
  console.error('eafc-db-kit not found. Looked in:\n  ' + kitCandidates.join('\n  '));
  console.error('\nPass --kit <path> (see the header of tools/import_fc27.mjs).');
  process.exit(1);
}
const { readTemplateDatabase } = await import(pathToFileURL(join(KIT, 'dist', 'index.js')).href);
const DEST = resolve(ROOT, arg('--out', 'data/fc27/COVERAGE.txt'));
const fs = { writeFileSync: (p, s) => writeFileSync(p, s) };
const main = await readTemplateDatabase({ version: 'FC 27', database: 'main' });
const T = Object.fromEntries(main.databases.flatMap(d => d.tables).map(t => [t.name, t.records]));
const src = readFileSync(join(ROOT, 'tools', 'import_fc27.mjs'), 'utf8');
const used = [...new Set([...src.matchAll(/\bT\.([a-zA-Z_0-9]+)/g)].map(m => m[1]))].filter(k => T[k]).sort();
const empty = Object.keys(T).filter(k => !T[k].length).sort();
const rest = Object.keys(T).filter(k => T[k].length && !used.includes(k)).sort();
// individually probed during r16/r17 and deliberately excluded, with the reason
const probed = {
  agents: 'all 29 rows are "Agent Test N" placeholders; no real names',
  sponsors: 'names are texture asset keys (dynamic_01, Tottenham_Hotelscom); no contract/value fields',
  teamsponsorlinks: 'links teams to those texture assets; no financial terms',
  competitionsponsorlinks: 'links competitions to texture assets; no financial terms',
  competitionmatchups: 'partial UEFA pot draw (4 cups), not a fixture list; a draw is engine season state',
  height_weight_impact: 'attribute id space unresolved',
  height_weight_impact_range: 'attribute id space unresolved (ids up to 100+)',
  createplayerpositiontemplates: 'attribute ids 75..111, outside the 34-field range',
  turfattributesmap: 'attribute id space unresolved',
  positionbonus: 'every value is 0',
  rankweight: 'every value is 0',
  attribute_strengths: 'attribute id space unresolved',
  specialization_attr_strengths: 'Pro Clubs specialization, attribute ids unresolved',
  playstyles: 'id/type columns only (type is empty); thresholds come from playstyle_attribute_requirement',
  signature_playstyles: 'Pro Clubs archetype unlock order',
  specialization_map: 'Pro Clubs spec -> archetype',
  specialization_perks: 'Pro Clubs',
  signature_perks: 'Pro Clubs',
  signatureabilitymap: 'Pro Clubs / gameplay',
  associatedplayers: 'archetype ids (Pro Clubs), 15 rows',
  associateplayerspec: 'Pro Clubs specializations',
  archetypes: 'Pro Clubs archetype definitions',
  perks: 'Pro Clubs perks',
  level_caps: 'Pro Clubs archetype level caps',
  career_birthingpool: 'appearance assets for generated players (head/hair/skin codes)',
  career_youth_skins: 'appearance assets for youth players',
  career_createplayerattributes: 'EXTRACTED via regen_templates.create (listed here only if missed)',
  fifaGameSettings: 'engine/renderer settings, not football data',
  MatchIntensity: 'EXTRACTED via match_tuning.json',
  formationoffsets: 'pitch offsets; formations.json already carries per-slot xy',
  playerpositionzones: 'pitch geometry for the renderer',
  fieldpositionboundingboxes: 'pitch geometry for the renderer',
  mentalities: 'pitch offset arrays (renderer tactical shapes)',
  defaultteamdata: 'pitch offset arrays (renderer)',
  default_mentalities: 'pitch offset arrays (renderer)',
  teamsheets: '802 user-saved sheets, mostly empty names; default_teamsheets is the authoritative one',
  teamsheetanalysis: 'recorded positions per player, superseded by teamplayerlinks role',
  broadcastleague: 'broadcast presentation grouping',
  previousteam: 'EXTRACTED as former_clubs.json',
  teamcounterparts: 'EXTRACTED as counterparts.json',
  bigmatchups: 'EXTRACTED as big_matches.json',
  player_grudgelove: 'EXTRACTED as affinities.json',
  clubcustomization_stadium: 'cosmetic stadium unlocks',
  reset_cost: 'Pro Clubs respec cost',
  playerpronouns: '1 row',
  playerbodyrestrictions: '1 row',
  playersockoverride: '4 cosmetic rows',
  factory_teams: '1 default team row',
  version: 'schema metadata',
  dbversion: 'schema metadata',
  ftue_presets: 'first-run tutorial preset',
  playernamemap: 'commentary audio id -> player id; only 42/106 ids are in the roster',
  cmplayers: 'Pro Clubs squads; the 75 ids outside our roster are retired legends (Kanu, Aimar, Quaresma)',
  smplayers: 'story-mode squads; 572 outside roster incl. the fictional Alex Hunter',
  smteams: 'story-mode teams (8 rows)',
  trainingteamplayers: '16 training dummies with concatenated placeholder names',
  trainingteamplayerlinks: 'links to those 16 training dummies',
  trainingteamplayernames: 'name ids for the training dummies',
  matchscenarios: '4 scripted preset matches (tutorial/play-now), not a schedule',
  gp_ucc: 'gameplay celebration animation ids',
  playervoicemap: 'commentary voice assignment, 20 rows',
  mascot: 'team mascot assets',
  adboardlogicexceptions: 'ad-board rendering rules keyed by competition',
  adboardconsoleoverrides: 'ad-board texture swaps per console',
  competitionballs: 'ball asset per competition stage',
  competitionbadges: 'badge asset per competition',
  competitionkits: 'kit rendering per competition',
  competitionrefereekits: 'referee kit asset per competition',
  slc_competition_overrides: 'seasonal outfit overrides per competition',
  clubcustomization_kit: 'cosmetic kit unlocks',
  clubcustomization_facilitycards: 'cosmetic facility card unlocks (starrating is art tier)',
  kitrewardsmapping: 'cosmetic kit rewards',
  teamkithudvalues: 'kit colour values for the HUD',
  tifo: 'crowd banner assets per team',
  customcoloredsmoke: 'crowd smoke colour per team',
  crowdbodies: 'crowd body assets tinted per team',
  highresasset: 'high-res head/appearance assets',
  audionation: 'commentary audio per nation',
  deactivatedstories: 'disabled commentary story ids',
  ssfstadiums: 'small-sided (Volta) venue walls',
  createplayerpresets: 'appearance presets for the player creator',
  crowdoldsystem: 'crowd prop flags (coffee/grill/phone are props, not fees)',
  slc: 'sideline character appearance; seasonalhair/seasonaloutfit are clothing',
  ucc: 'player -> celebration animation id + probability; purely cosmetic',
  career_calendar: 'EXTRACTED as calendar.json (windows only)',
};
delete probed.career_createplayerattributes; delete probed.MatchIntensity;
delete probed.previousteam; delete probed.teamcounterparts; delete probed.bigmatchups;
delete probed.player_grudgelove; delete probed.career_calendar;
const cm = rest.filter(k => /^cm_/.test(k));
const families = [
  ['appearance / rendering assets', /^(skins|highres|basehead|preset_|slc|spa|crowd|lowresasset|tattoo|footwear|playerboots|goalkeepergloves|shoecolors|outfit|wardrobe|accessories|vanitystore|kit|teamkits|competitionkits|netpattern|linecolor|seatcolor|stadiumcolor|teamkithud|playersock|customcoloredsmoke|tifo|mascot|genericmascot|bannerplayers|vipplayers|celebrations|goalcelebration|emotelink|Customizable|clubcustomization|ucc|gp_ucc|videos|presentationmode|dynamicimages|brand|adboard|modeadboard|competitionballs|teamballs|competitionbadges|competitionrefereekits)/],
  ['audio / commentary', /^(audio|commentarynames|clubcommentary|playercalls|playervoicemap|SMPlayerCallLang|AudioDeactivated|deactivatedstories|womendeactivated)/],
  ['other game modes (Pro Clubs / Volta / training)', /^(cm|cmplayers|smplayers|smteams|wt|main_world|gameplay_site|activity_config|kickabout|createplayer|createplayerviews|trainingteam|matchscenarios|skillmeter|rankweight|mls_group)/],
  ['pitch geometry / renderer tactics', /^(formationoffsets|playerpositionzones|fieldposition|mentalities|defaultteamdata|default_mentalities|ssfformations|ssfstadiums|turfsquadtypemap)/],
];
// Field-level scan of everything still unclassified. Name-based triage is what
// failed in r16, so this checks FIELDS for football logic (entity references and
// career quantities) rather than trusting the table name. Cosmetic field names
// are filtered out because e.g. crowdhairs.age and tifo.teamid are not logic.
const SIG = /playerid|teamid|leagueid|competitionid|nationid|contract|wage|salary|value|budget|\bfee|morale|fitness|injur|suspend|transfer|loan|growth|potential|overall|rating|points|standing|fixture|season|scout|youth|retire|birthdate/i;
const COSMETIC = /^(head|hair|skin|face|eye|brow|lip|ear|nose|chin|jaw|cheek|temple|neck|fl_|fa_|ca_|bs_|mu_|body|cloth|shoe|sock|jersey|shorts|kit|texture|mesh|asset|outfit|tint|colour|color|tattoo|accessor|crowd|tifo|banner|smoke|net|seat|line|ball|boot|glove|celebr|emote|mascot|audio|commentary|video|render|light|camera)/i;
const scanned = rest.filter(k => !Object.keys(probed).includes(k) && !/^cm_/.test(k));
const flagged = [];
for (const k of scanned) {
  const logic = Object.keys(T[k][0]).filter(f => SIG.test(f) && !COSMETIC.test(f));
  if (logic.length) flagged.push([k, logic]);
}
const assigned = new Set([...Object.keys(probed), ...cm]);
const fam = {};
for (const [label, re] of families) {
  fam[label] = rest.filter(k => !assigned.has(k) && re.test(k));
  for (const k of fam[label]) assigned.add(k);
}
const other = rest.filter(k => !assigned.has(k));
const out = [];
out.push('FC 27 EXTRACTION COVERAGE');
out.push('=========================');
out.push('');
out.push('Source: eafc-db-kit 1.1.0 bundled "FC 27" main template.');
out.push(`Tables in template: ${Object.keys(T).length}`);
out.push(`  non-empty: ${Object.keys(T).filter(k=>T[k].length).length}`);
out.push(`  empty:     ${empty.length}`);
out.push(`  READ by tools/import_fc27.mjs: ${used.length}`);
out.push('');
out.push('This file exists so the completeness claim can be checked, not taken on trust.');
out.push('Regenerate the reasoning by re-running the importer against the kit; the');
out.push('importer exits non-zero if any allowlisted table is missing or empty.');
out.push('');
out.push(`1. READ AND EXTRACTED (${used.length} tables)`);
out.push('-'.repeat(60));
for (const k of used) out.push(`   ${k.padEnd(36)} ${String(T[k].length).padStart(6)} rows`);
out.push('   + localization bundle (LanguageStrings1/2, 115843 strings) for cup,');
out.push('     competition and PlayStyle display names.');
out.push('');
out.push(`2. EMPTY UPSTREAM (${empty.length} tables) - nothing to extract`);
out.push('-'.repeat(60));
out.push('   ' + empty.join(', '));
out.push('');
out.push('   Verified: fixtures = 0 rows, transfers = 0 rows, and the career_* state');
out.push('   tables (teamofweek, playerawards, managerawards, youthplayers, scouts,');
out.push('   playergrowthuserseason, ...) are all 0 rows. Others such as');
out.push('   career_playercontract / career_playerstats / career_leaguetable are not');
out.push('   present in this template at all. career_calendar has exactly 1 row and');
out.push('   its absolute dates are a 2008 placeholder (only the windows are shipped).');
out.push('');
out.push('   Consequence: match results, schedules, tables, budgets and market value');
out.push('   genuinely do not exist upstream - the engine must generate and own them.');
out.push('');
const probedRest = Object.keys(probed).filter(k => rest.includes(k)).sort();
out.push(`3. INSPECTED INDIVIDUALLY AND EXCLUDED (${probedRest.length} tables)`);
out.push('-'.repeat(60));
for (const k of probedRest) out.push(`   ${k.padEnd(34)} ${String(T[k].length).padStart(5)}  ${probed[k]}`);
out.push('');
out.push(`4. NOT INDIVIDUALLY PROBED - classified by family (${rest.length - probedRest.length} tables)`);
out.push('-'.repeat(60));
out.push('   Triaged by name AND by a field-level scan for football logic (entity');
out.push('   references, contract/wage/growth/fitness quantities), not row-by-row.');
out.push('   Cosmetic field names are excluded from that scan, so crowdhairs.age');
out.push('   and tifo.teamid do not count as logic.');
out.push('');
out.push(`   Field scan: ${scanned.length} tables checked, ${flagged.length} still flag a logic field.`);
if (flagged.length) {
  out.push('   Flagged for a future look (asset tables keyed by an entity id):');
  for (const [k, f] of flagged) out.push(`     ${k.padEnd(32)} ${f.join(', ').slice(0, 90)}`);
}
out.push('');
out.push('   If the engine later needs one, it is a small importer addition.');
for (const [label, arr] of Object.entries(fam)) {
  if (!arr.length) continue;
  out.push('');
  out.push(`   ${label} (${arr.length}):`);
  out.push('     ' + arr.join(', '));
}
if (cm.length) { out.push(''); out.push(`   Pro Clubs progression curves (${cm.length}):`); out.push('     ' + cm.join(', ')); }
if (other.length) { out.push(''); out.push(`   other (${other.length}):`); out.push('     ' + other.join(', ')); }
out.push('');
out.push('KNOWN LIMITATIONS OF WHAT IS SHIPPED');
out.push('-'.repeat(60));
out.push('See NOTICE.txt for provenance and licensing. In summary:');
out.push('  - ratings.json is a LOSSY PES-25 projection; use ea_attrs.json (34 raw).');
out.push('  - formation slots are side-specific, player positions are coarse; bridge');
out.push('    them with ea_positions.json slotCompat (7887/7887 starters fit).');
out.push('  - ovr_weights.json / playstyles.json attribute ids use an UNRESOLVED EA');
out.push('    enum. Shipped raw with warnings; do not index ea_attrs.json with them.');
out.push('  - traits.json bitmasks are raw: no defensible PlayStyle mapping was found.');
out.push('  - style/form/inj in ratings.json are placeholders (single-valued).');
out.push('  - affinities.json emotion scale is inferred, not documented.');
out.push('  - 452/717 managers are named; the rest are upstream placeholders.');
out.push('  - Libertadores (1003) / Sudamericana (1014) seeds are outside the 717-club');
out.push('    universe; their names ship in external_teams.json.');
fs.writeFileSync(DEST, out.join('\n') + '\n');
console.log('coverage written: %d read, %d empty, %d probed-excluded, %d by-family',
  used.length, empty.length, probedRest.length, rest.length - probedRest.length);
const accounted = used.length + empty.length + rest.length;
console.log('total accounted: %d of %d -> %s', accounted, Object.keys(T).length, DEST);
if (accounted !== Object.keys(T).length) {
  console.error('COVERAGE GAP: some tables are unaccounted for');
  process.exit(1);
}
if (other.length) {
  console.error('UNCLASSIFIED tables (add a reason or a family): %s', other.join(', '));
  process.exit(1);
}
