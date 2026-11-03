#!/usr/bin/env node
/**
 * Install REA's agent skill into this repository
 * ---------------------------------------------------------------------------
 * Copies the skill bundled with the pinned `rea-agents` package into
 * `.agents/skills/reverse-engineer-anything`, so an agent working in this
 * repository reads REA's workflow instructions (when to use REA, how to read
 * Evidence, how to recover from a blocked provider) without depending on a
 * global install.
 *
 *   npm run rea:skill
 *
 * The copy is verbatim and versioned with the package: re-run this after
 * upgrading `rea-agents`. `npm run rea -- setup` performs the same install for
 * the user-level agents directory (`~/.agents/skills`) instead.
 */
import { createRequire } from 'node:module';
import { cp, mkdir, readFile, rm } from 'node:fs/promises';
import path from 'node:path';

const require = createRequire(import.meta.url);
const SKILL = 'reverse-engineer-anything';

let packageRoot;
try {
  packageRoot = path.dirname(require.resolve('rea-agents/package.json'));
} catch {
  process.stderr.write('[ninty] rea-agents is not installed — run `npm install` first.\n');
  process.exit(1);
}

const source = path.join(packageRoot, 'skills', SKILL);
const target = path.resolve(process.cwd(), '.agents', 'skills', SKILL);

await rm(target, { recursive: true, force: true });
await mkdir(path.dirname(target), { recursive: true });
await cp(source, target, { recursive: true });

// Report the identity the agent will see, straight from the skill front matter.
const frontmatter = (await readFile(path.join(target, 'SKILL.md'), 'utf8')).split('---')[1] ?? '';
const version = /version:\s*"?([^"\n]+)"?/.exec(frontmatter)?.[1] ?? 'unknown';
const tools = /tool_count:\s*(\d+)/.exec(frontmatter)?.[1] ?? 'unknown';

process.stdout.write(
  `Installed REA skill ${SKILL} v${version} (${tools} tools)\n` +
    `  ${path.relative(process.cwd(), target)}/\n`,
);
