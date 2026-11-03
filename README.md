# Ninty

Reverse-engineering harness built on [REA](https://github.com/morluto/rea) — one CLI
and MCP server for inspecting binaries, Electron/JavaScript apps, .NET assemblies,
Android packages, firmware and captured traffic, with Evidence attached to every
finding.

REA is installed locally and pinned; this repository owns the launcher, the
readiness check and the agent registration.

## Setup

```bash
npm install      # installs rea-agents (pinned)
npm run rea:check
```

## Use

```bash
npm run rea -- --help
npm run rea -- inspect-elf-notes /bin/ls
npm run rea -- analyze-javascript-application /path/to/app --json
npm run rea -- doctor
```

Agents connect over MCP using `.mcp.json`, or via `npm run rea -- setup --client <agent>`.

## Documentation

- **[docs/rea.md](docs/rea.md)** — what is installed, what works on this host, how to
  supply an analysis engine, the runtime caveat, and troubleshooting.
- **[.agents/skills/reverse-engineer-anything/](.agents/skills/reverse-engineer-anything/SKILL.md)**
  — the REA workflow guide agents read.
- Upstream: <https://rea.tools/> · <https://github.com/morluto/rea>

## Requirements

Node.js `^22.23.4 || ^24.22.1 || >=26.12.1` for REA's configuration commands.
Analysis commands run on the host's Node; see
[docs/rea.md §5](docs/rea.md#5-runtime-why-there-is-a-waiver) for this sandbox's
situation.
