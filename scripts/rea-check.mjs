#!/usr/bin/env node
/**
 * REA readiness check
 * ---------------------------------------------------------------------------
 * Verifies the installed REA build and the capabilities this host actually
 * has, without touching any target. Run it after `npm install`, after changing
 * a provider setting, or when an analysis command starts failing.
 *
 *   npm run rea:check          # human-readable report
 *   npm run rea:check --json   # same data as JSON
 *
 * Exit code is 1 only when REA itself is unusable (missing install, broken MCP
 * inventory, or no working analysis path). Missing optional analysis engines
 * are reported but do not fail the check.
 */
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const wantJson = process.argv.includes('--json');
const results = [];

function run(args, { timeout = 180_000 } = {}) {
  const child = spawnSync(process.execPath, [new URL('./rea.mjs', import.meta.url).pathname, ...args], {
    encoding: 'utf8',
    timeout,
    env: process.env,
  });
  return {
    code: child.status,
    stdout: child.stdout ?? '',
    stderr: child.stderr ?? '',
    timedOut: child.error?.code === 'ETIMEDOUT',
  };
}

/** REA prints a progress stream before the final JSON value on some commands. */
function lastJson(text) {
  const lines = text.split('\n').filter((line) => line.trim().startsWith('{'));
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try {
      return JSON.parse(lines[index]);
    } catch {
      // keep looking backwards
    }
  }
  return null;
}

function record(name, state, detail) {
  results.push({ name, state, detail });
}

// ---------------------------------------------------------------------------
// 1. Package identity
// ---------------------------------------------------------------------------
let packageVersion = null;
try {
  packageVersion = require('rea-agents/package.json').version;
  record('package', 'ok', `rea-agents@${packageVersion}`);
} catch {
  record('package', 'fail', 'rea-agents is not installed — run `npm install`');
}

// ---------------------------------------------------------------------------
// 2. Runtime
// ---------------------------------------------------------------------------
const nodeVersion = process.versions.node;
const runtimeDetail =
  process.versions.bun !== undefined
    ? `bun ${process.versions.bun} (Node ${nodeVersion} compatibility)`
    : `node ${nodeVersion}`;
record(
  'runtime',
  'info',
  `${runtimeDetail} — analysis commands run on the real runtime, unwaived`,
);

// ---------------------------------------------------------------------------
// 3. CLI responds
// ---------------------------------------------------------------------------
if (packageVersion) {
  const version = run(['--version']);
  const reported = version.stdout.trim().split('\n').pop();
  if (version.code === 0 && reported?.includes(packageVersion)) {
    record('cli', 'ok', `rea --version → ${reported}`);
  } else {
    record(
      'cli',
      'fail',
      `rea --version failed (exit ${version.code}${version.timedOut ? ', timed out' : ''})`,
    );
  }
}

// ---------------------------------------------------------------------------
// 4. MCP server: startup, inventory and one real tool call
// ---------------------------------------------------------------------------
if (packageVersion) {
  const mcp = run(['mcp', 'doctor', '--format', 'json']);
  const report = lastJson(mcp.stdout);
  if (report?.healthy) {
    record(
      'mcp',
      'ok',
      `server ${report.server.version} · protocol ${report.server.protocol_version} · ` +
        `${report.inventory.tools.observed} tools · ${report.inventory.prompts.observed} prompts · digest matches`,
    );
  } else {
    record(
      'mcp',
      'fail',
      `mcp doctor unhealthy${report ? `: ${JSON.stringify(report.checks ?? report.message)}` : ''}`,
    );
  }
}

// ---------------------------------------------------------------------------
// 5. Analysis paths that need no external engine
// ---------------------------------------------------------------------------
if (packageVersion) {
  const elf = run(['inspect-elf-notes', process.execPath, '--format', 'json']);
  const elfReport = lastJson(elf.stdout);
  if (elfReport?.evidence_id) {
    record('built-in parsers', 'ok', `ELF parser produced ${elfReport.evidence_id.slice(0, 19)}…`);
  } else if (elfReport?.code === 'resource_constraint') {
    record('built-in parsers', 'ok', `ELF parser reachable (input budget: ${elfReport.message})`);
  } else {
    record('built-in parsers', 'warn', `ELF parser returned ${elfReport?.code ?? elf.code}`);
  }

  const providers = run(['providers', '--format', 'json']);
  const providerReport = lastJson(providers.stdout);
  if (providerReport?.capabilities) {
    const available = providerReport.capabilities
      .filter((entry) => entry.groups.some((group) => group.available))
      .map((entry) => entry.provider.id);
    record('static providers', available.length ? 'ok' : 'warn', available.join(', ') || 'none');
  }

  const deep = providerReport?.analysis_provider_candidates ?? [];
  const usable = deep.filter((entry) => entry.availability?.status === 'available');
  if (usable.length) {
    record('deep analysis engines', 'ok', usable.map((entry) => entry.provider.id).join(', '));
  } else {
    record(
      'deep analysis engines',
      'info',
      `none configured (${deep.map((entry) => entry.provider.id).join(', ')} unavailable) — ` +
        'static/BYOP analysis only; see docs/rea.md',
    );
  }
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------
const failed = results.filter((entry) => entry.state === 'fail');

if (wantJson) {
  process.stdout.write(
    `${JSON.stringify({ ok: failed.length === 0, results }, null, 2)}\n`,
  );
} else {
  const badge = { ok: 'ok  ', fail: 'FAIL', warn: 'warn', info: 'info' };
  process.stdout.write(`Ninty · REA readiness (${packageVersion ? `rea-agents@${packageVersion}` : 'not installed'})\n`);
  process.stdout.write(`${'-'.repeat(72)}\n`);
  for (const entry of results) {
    process.stdout.write(`${badge[entry.state] ?? '    '}  ${entry.name.padEnd(22)} ${entry.detail}\n`);
  }
  process.stdout.write(`${'-'.repeat(72)}\n`);
  process.stdout.write(
    failed.length === 0
      ? 'REA is ready for use. See docs/rea.md for how the environment is wired.\n'
      : `${failed.length} check(s) failed.\n`,
  );
}

process.exit(failed.length === 0 ? 0 : 1);
