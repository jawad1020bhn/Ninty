# REA — reverse-engineering toolchain

[REA](https://github.com/morluto/rea) (`rea-agents` on npm) is a reverse-engineering
CLI and MCP server: one interface for binaries, Electron/JavaScript apps, .NET
assemblies, Android packages, firmware, packet captures and more. Every result is
returned as **Evidence** — findings with the observations, limitations and
provenance behind them.

This repository installs REA locally and wires it for both terminal use and agent
use. Nothing here re-implements REA; the repo owns the pinned version, the
launcher, the readiness check and the agent registration.

- **Pinned version:** `rea-agents@6.8.0` (`package.json`)
- **Upstream source:** <https://github.com/morluto/rea> · <https://rea.tools/>
- **License:** MIT (see `node_modules/rea-agents/LICENSE`)

> Install only from the official sources above. A similar repository name or a
> copied README does not establish that a package is official.

---

## 1. Quick start

```bash
npm install                 # installs the pinned REA
npm run rea:check           # verify the install (see §7)
```

Run any REA command through the launcher:

```bash
npm run rea -- --help
npm run rea -- <command> [arguments] [flags]
```

Examples that work on this host today:

```bash
# ELF/PE/Mach-O static facts, no analysis engine needed
npm run rea -- inspect-elf-notes /bin/ls
npm run rea -- inspect-go-binary /path/to/go-tool
npm run rea -- inspect-artifact /path/to/app.app

# JavaScript / Electron app, statically reconstructed (modules, IPC, preload)
npm run rea -- analyze-javascript-application /path/to/unpacked-app --json

# GNU objdump as a caller-supplied native provider
npm run rea -- inspect-with-objdump /bin/ls symbols
npm run rea -- inspect-with-objdump /bin/ls disassemble --symbol main

# Readiness and provider inventory
npm run rea -- doctor
npm run rea -- providers
npm run rea -- capabilities
```

`npm run rea -- <command> --schema` prints the exact JSON schema for a command;
`--llms` / `--llms-full` print the machine-readable command manifest. Prefer those
over guessing flags.

---

## 2. What was added to the repository

| Path                        | Purpose                                                                    |
| --------------------------- | -------------------------------------------------------------------------- |
| `package.json`              | Pins `rea-agents`, exposes the `rea:*` scripts, declares the Node engines.  |
| `scripts/rea.mjs`           | Single launcher for every REA command and for the MCP server.               |
| `scripts/runtime-waiver.cjs`| Contained runtime waiver for config commands only (see §5).                 |
| `scripts/rea-check.mjs`     | Readiness check: package, runtime, CLI, MCP inventory, analysis paths.       |
| `scripts/rea-skill.mjs`     | Copies REA's agent skill into `.agents/skills/`.                            |
| `.agents/skills/reverse-engineer-anything/` | REA workflow instructions for agents working in this repo. |
| `.mcp.json`                 | Project-scoped MCP registration for agents that read it.                    |
| `.gitignore`                | Keeps Evidence bundles, extracted artifacts and exports out of Git.         |

Useful npm scripts:

| Script                | Runs                                             |
| --------------------- | ------------------------------------------------ |
| `npm run rea`         | `scripts/rea.mjs` — the launcher                 |
| `npm run rea:mcp`     | REA as a stdio MCP server                        |
| `npm run rea:doctor`  | `rea doctor`                                     |
| `npm run rea:check`   | Full readiness check (`--json` for machine output) |
| `npm run rea:skill`   | Reinstall the bundled agent skill                |

### Agent registration

`.mcp.json` registers the server for clients that read project-scoped config:

```json
{
  "mcpServers": {
    "rea": {
      "command": "node",
      "args": ["scripts/rea.mjs", "--mcp"],
      "env": { "REA_OBJDUMP_COMMAND": "/usr/bin/objdump" }
    }
  }
}
```

For clients that keep their own config, prefer REA's own setup, which writes the
correct registration and backs up existing config:

```bash
npm run rea -- setup --client codex      # or claude_code, cursor, gemini_cli, vscode, ...
npm run rea -- setup --all-detected
npm run rea -- setup --dry-run           # preview the plan first
npm run rea -- uninstall                 # remove REA-owned config and skill
```

Restart the agent after registering so it picks up the new tool list.

---

## 3. How to work with REA

1. **Pick the narrowest command** that answers the question. Static parsers
   (`inspect-*`) are cheap and need no engine; `analyze-javascript-application`
   reconstructs an app graph; deep native work needs a decompiler provider.
2. **Keep the Evidence.** Every result carries an `evidence_id`, a `subject`
   digest, `limitations` and `confidence`. Cite those instead of paraphrasing.
3. **Use `--format json`** for programmatic use, and `--filter-output key.path` /
   `--token-limit n` to keep large results readable. Retained results can be
   re-read with `inspect-analysis-view` rather than re-running the analysis.
4. **Read the failure codes.** `provider_unavailable` means a provider is not
   configured — not that the target is unanalyzable. The `remediation.action`
   field names the exact setting or tool to supply.
5. **Treat empty results as bounded.** REA documents where a scan is incomplete;
   an empty search is not proof of absence.

For agent-facing guidance (when to use REA at all, recovery ladders, Evidence
workflow), read `.agents/skills/reverse-engineer-anything/SKILL.md` and its
`references/` directory.

---

## 4. What works on this host

REA ships its own static parsers, so a large part of its surface needs no
external engine. **Verified in this sandbox:**

| Capability                                        | Command                                                            |
| ------------------------------------------------- | ------------------------------------------------------------------ |
| ELF notes (build-id, ABI tags)                    | `inspect-elf-notes`                                                |
| Go build info (compiler, modules)                 | `inspect-go-binary`                                                |
| Artifact/package inventory (incl. ASAR expansion) | `inspect-artifact`                                                 |
| Desktop runtime candidates                        | `inspect-desktop-application`                                      |
| JavaScript / Electron static application graph    | `analyze-javascript-application`                                   |
| GNU objdump as a native provider                  | `REA_OBJDUMP_COMMAND=/usr/bin/objdump` → `inspect-with-objdump`     |
| MCP server, 229 tools, 6 prompts                  | `npm run rea -- mcp doctor`                                        |

**Provider-free, documented upstream but not exercised here:** `inspect-pe-imports`,
`inspect-pe-certificates`, `inspect-pe-resources`, `inspect-pe-load-config`,
`inspect-managed-artifact` / `inspect-managed-members` (.NET static),
`inspect-apk-signature`, `inspect-dart-aot`, `identify-flutter-build`,
`inspect-gpu-code-objects`, `inspect-model-artifact`, `inspect-il2cpp-metadata`,
`inspect-erlang-beam`, `inspect-kernel-module`, `inspect-byte-entropy`,
`inspect-devicetree`, extraction and inventory commands.

**Blocked by prerequisites in this sandbox:**

| Missing                        | Unlocks                                                     | To enable                                                    |
| ------------------------------ | ----------------------------------------------------------- | ------------------------------------------------------------ |
| Ghidra, Hopper, IDA, Kuna      | Decompilation, pseudocode, xrefs, `analyze`/`decompile`      | Supply an engine (§6)                                        |
| JDK + JADX JAR                 | Android APK class/method inspection                          | `REA_JADX_MCP_JAR=/abs/path/jadx-headless-mcp.jar`            |
| pwntools Python env            | ELF layout, recorded-crash decoding, EVM bytecode             | `REA_PWNTOOLS_PYTHON=/abs/path/python`                       |
| Chrome-family browser          | Website capture, screenshots, Playwright scenarios            | `REA_BROWSER_EXECUTABLE=/abs/path/chrome`                    |
| tshark / binwalk / adb / WABT  | Packet captures, firmware, Android devices, WASM              | Install and point the matching `REA_*_COMMAND` at it          |

REA **never installs** these for you (Hopper is the one exception, and only with
explicit approval during `setup --install-hopper`); it takes caller-supplied
paths and verifies them.

Check the live picture at any time:

```bash
npm run rea -- providers --format json     # what is available right now
npm run rea:check                          # summarized readiness
```

---

## 5. Runtime: why there is a waiver

REA 6.8.0 declares `engines.node: ^22.23.4 || ^24.22.1 || >=26.12.1` and enforces
it for its **configuration** commands (`setup`, `update`, `uninstall`, `mcp add`).

This sandbox runs **Node 22.22.3** — one patch below the gate. No compliant
runtime is obtainable here: `nodejs.org` is unreachable, no npm or PyPI
distribution ships a matching Node build, and the Bun build that satisfies the
gate by its Node-compatibility version fails REA's analysis workers (verified:
`analyze-javascript-application` errors under Bun but succeeds under Node).

Every analysis command, `doctor`, `capabilities` and `providers` run correctly on
22.22.3. Only the config commands consult the gate, so `scripts/runtime-waiver.cjs`
is preloaded **only for those four commands**, and only when the real runtime is
below the supported range. It reports the gate's own minimum (`22.23.4`), which is
the smallest possible deviation, and announces itself on stderr.

Deliberate limits:

- **Analysis commands and the MCP server are never wrapped.** If they genuinely
  need a newer runtime they must fail loudly rather than run on an unbacked claim.
- **REA's source is not modified.** The waiver is a preload, reverted by deleting
  one file.
- **Bun is left alone** — it reports its own identity.
- Set `REA_RUNTIME_WAIVER=0` to disable it and see the raw gate.

**Remove the waiver as soon as the host runs a supported Node release:** upgrade
Node to ≥22.23.4 (or a supported 24.x / 26.x), then delete
`scripts/runtime-waiver.cjs` and the `needsWaiver` block in `scripts/rea.mjs`.
`npm run rea:check` reports the real runtime, so the waiver is never hidden.

---

## 6. Supplying an analysis engine

Deep native analysis (pseudocode, xrefs, function graphs) needs one of:

| Engine | Setting                                                                                                                                 |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Ghidra | `GHIDRA_INSTALL_DIR=/abs/path/ghidra_12.x` (needs a JDK 21+; `java` is not installed here)                                               |
| Hopper | `HOPPER_LAUNCHER_PATH=/abs/path/Hopper` (Linux: X11 launcher; `setup --install-hopper` can fetch the demo)                                 |
| IDA    | `REA_IDA_MCP_CONFIG` pointing at your IDA MCP registration JSON                                                                          |
| Kuna   | `REA_KUNA_COMMAND=/abs/path/kuna`                                                                                                        |
| objdump| `REA_OBJDUMP_COMMAND=/usr/bin/objdump` — already set in `.mcp.json`; raw disassembly, no decompiler                                      |
| Rizin  | `REA_RIZIN_COMMAND` / Cutter bridge, for disassembly and debugger sessions                                                                |

Put provider settings in the MCP registration `env` (see `.mcp.json`) so the
server and the terminal share them, then re-run `npm run rea:check`. Large
binaries may need a longer startup deadline: `REA_GHIDRA_STARTUP_TIMEOUT_MS`,
`REA_HOPPER_STARTUP_TIMEOUT_MS`.

---

## 7. Verifying the installation

```bash
npm run rea:check            # package, runtime, CLI, MCP inventory, analysis paths
npm run rea:check -- --json  # same, machine-readable
npm run rea -- mcp doctor    # MCP startup, tool/prompt inventory, catalog digest
npm run rea -- doctor        # host, runtime and provider diagnostics
```

`rea:check` exits non-zero only when REA itself is unusable. Missing optional
engines are reported as `info`/`warn`, because they affect only the targets that
need them.

---

## 8. Troubleshooting

| Symptom                                                     | Cause / fix                                                                                                       |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `code: provider_unavailable`                                | A provider is unconfigured. Read `remediation.action`; set the named `REA_*` variable (§6).                        |
| `code: resource_constraint` (e.g. `max_file_bytes`)         | The input exceeds a read budget. Select a smaller artifact or raise the limit named in the message.                |
| `code: target_unavailable`                                  | The file is malformed or unsupported. The message names the format reason; confirm the target first.               |
| `VALIDATION_ERROR`                                          | Wrong arguments. Run `npm run rea -- <command> --help` and `--schema`, then retry.                                 |
| Tools missing in an agent after registering                 | Restart the client. `doctor` cannot prove the current session connected.                                          |
| `mcp doctor` unhealthy                                      | The server did not start. Run `npm run rea -- doctor`, then check the client's registration and shell `PATH`.       |
| Config command reports the Node gate                        | Expected without the waiver. Upgrade Node, or keep the waiver (§5).                                               |
| MCP call hangs                                              | Check the command's timeout flag before retrying; do not repeat an unchanged call that may still be running.       |

---

## 9. Upgrading

REA changes quickly. To upgrade, change the exact version in `package.json`, then:

```bash
npm install
npm run rea:skill                       # refresh the bundled skill
npm run rea -- setup --dry-run          # re-register agents if the registration changed
npm run rea:check
```

Keep the version **exact** (no `^`): Evidence schemas and MCP tool contracts are
part of what a task relies on. A globally installed CLI can update itself with
`npm run rea -- update`; this repository uses the local pinned install instead.
