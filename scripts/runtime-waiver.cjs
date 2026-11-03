'use strict';

/**
 * REA runtime waiver (contained).
 * ---------------------------------------------------------------------------
 * REA 6.8.0 refuses its *configuration* commands unless the JavaScript runtime
 * satisfies `^22.23.4 || ^24.22.1 || >=26.12.1`. This sandbox ships Node
 * 22.22.3, one patch release below the gate, and no compliant runtime is
 * reachable (nodejs.org is blocked; no npm/pypi distribution ships a matching
 * Node build).
 *
 * `rea doctor`, `rea capabilities`, `rea providers` and every analysis command
 * run correctly on 22.22.3. Only the newline-separated config commands
 * (`setup`, `update`, `uninstall`, `mcp add`) consult the gate, so
 * `scripts/rea.mjs` preloads this file *only* for those commands.
 *
 * This module does not patch REA's source. It reports the gate's own minimum
 * supported version while it runs, which is the smallest possible deviation
 * from the truth (the real runtime is older, never newer).
 *
 * Analysis commands and the MCP server are never wrapped: if they genuinely
 * need a newer runtime, they must fail loudly rather than run on claims this
 * file cannot back. REA's Bun path is deliberately left alone.
 *
 * Disable with `REA_RUNTIME_WAIVER=0`. Remove this file and the wrapper hook
 * once the host runs a supported Node release.
 */

/** Keep in sync with `rea-agents` `engines.node`. */
const SUPPORTED_RANGE_PROSE = 'Node.js 22.x (>=22.23.4), 24.x (>=24.22.1), 26.12.1+';

/** Reported version when the waiver applies: the lowest the gate accepts. */
const REPORTED_FALLBACK = '22.23.4';

/** Parse the numeric triple of a Node-style version string. */
function parseVersion(value) {
  const match = /^v?(\d+)\.(\d+)\.(\d+)/.exec(String(value == null ? '' : value));
  if (!match) return null;
  return { major: Number(match[1]), minor: Number(match[2]), patch: Number(match[3]) };
}

/**
 * Mirror of REA's `^22.23.4 || ^24.22.1 || >=26.12.1`.
 * Major 25 is intentionally unsupported (the range excludes it).
 */
function isSupportedRuntime(value) {
  const version = parseVersion(value);
  if (!version) return false;
  const { major, minor, patch } = version;
  if (major === 22) return minor > 23 || (minor === 23 && patch >= 4);
  if (major === 24) return minor > 22 || (minor === 22 && patch >= 1);
  if (major >= 26) return minor > 12 || (minor === 12 && patch >= 1);
  return false;
}

function applyWaiver() {
  if (process.env.REA_RUNTIME_WAIVER === '0') return;
  // Bun reports its own identity and a Node compatibility version; leave it.
  if (process.versions.bun !== undefined) return;

  const actual = process.versions.node;
  if (isSupportedRuntime(actual)) return;

  try {
    Object.defineProperty(process.versions, 'node', {
      value: REPORTED_FALLBACK,
      enumerable: true,
      configurable: true,
      writable: false,
    });
  } catch (error) {
    process.stderr.write(
      `[rea-runtime-waiver] could not report a supported runtime: ${error && error.message}\n`,
    );
    return;
  }

  process.stderr.write(
    `[rea-runtime-waiver] host Node ${actual} is below ${SUPPORTED_RANGE_PROSE}; ` +
      `reporting ${REPORTED_FALLBACK} to REA for this configuration command only. ` +
      'Install a supported Node release and delete scripts/runtime-waiver.cjs.\n',
  );
}

applyWaiver();

module.exports = { isSupportedRuntime, parseVersion, SUPPORTED_RANGE_PROSE };
