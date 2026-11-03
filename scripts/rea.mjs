#!/usr/bin/env node
/**
 * REA launcher
 * ---------------------------------------------------------------------------
 * Single entry point for every REA command in this repository.
 *
 *   npm run rea -- doctor
 *   npm run rea -- inspect-elf-notes ./target.bin
 *   npm run rea -- analyze-javascript-application /path/to/app --json
 *   npm run rea:mcp                      # stdio MCP server for an agent
 *
 * The runtime waiver (scripts/runtime-waiver.cjs) is preloaded for
 * configuration commands only; analysis commands and the MCP server are never
 * wrapped. See that file for the full rationale.
 */
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Commands that consult REA's runtime gate. Everything else must run unwrapped. */
const CONFIG_COMMANDS = new Set([
  'setup',
  'update',
  'uninstall',
  'mcp:add',
  'mcp-add',
]);

function firstCommand(argv) {
  const args = argv.filter((arg) => arg !== '--');
  const command = args.find((arg) => !arg.startsWith('-'));
  if (command !== 'mcp') return command ?? null;
  // `rea mcp add` is a config command; `rea mcp doctor` is a diagnostic.
  const sub = args[args.indexOf(command) + 1];
  return sub === 'add' ? 'mcp:add' : 'mcp';
}

function fail(message) {
  process.stderr.write(`[ninty] ${message}\n`);
  process.exit(1);
}

let entry;
try {
  entry = require.resolve('rea-agents/scripts/rea.mjs');
} catch {
  fail(
    'REA is not installed. Run `npm install` first ' +
      '(REA is pinned in package.json as rea-agents).',
  );
}

const args = process.argv.slice(2);
const command = firstCommand(args);
const needsWaiver = command !== null && CONFIG_COMMANDS.has(command);

const env = { ...process.env };
if (needsWaiver && env.REA_RUNTIME_WAIVER !== '0') {
  const waiver = path.join(repoRoot, 'scripts', 'runtime-waiver.cjs');
  env.NODE_OPTIONS = [env.NODE_OPTIONS, `--require ${JSON.stringify(waiver)}`]
    .filter(Boolean)
    .join(' ')
    .trim();
}

const child = spawn(process.execPath, [entry, ...args], {
  stdio: 'inherit',
  env,
});

child.on('error', (error) => fail(`failed to start REA: ${error.message}`));

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal));
}

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
