# Forge Manual Testing -- Installation Verification & Feature Tour

Three skills verify that Forge is installed and working correctly, with escalating isolation:

| Mode        | Invocation                                        | What it does                                              | Runtime          | Install requirement |
| ----------- | ------------------------------------------------- | --------------------------------------------------------- | ---------------- | ------------------- |
| Smoke test  | Claude: `/forge:smoke-test`; Codex: `$smoke-test` | Read-only health check (no writes)                        | Claude and Codex | SKILLS module       |
| Walkthrough | `/forge:walkthrough`                              | Install + assert in sandbox, verify real system untouched | Claude Code only | SKILLS module       |
| Full QA     | `/forge:qa`                                       | Full checklist in Docker                                  | Claude Code only | `full` profile      |

- Canonical architecture: [`docs/design_appendix.md` section D](../design_appendix.md#d-interactive-manual-testing)
- Testing guidelines: [`testing_guidelines.md`](../developer/testing_guidelines.md)

---

## Quick start

Inside a Claude Code session:

```
/forge:smoke-test                      # Quick read-only health check
/forge:walkthrough                     # Default: interactive walkthrough
```

Inside Codex, explicitly invoke the portable smoke skill:

```
$smoke-test
```

`walkthrough` and `qa` remain Claude-only because they orchestrate Claude Code interaction. The portable skills are
`challenge`, `smoke-test`, `review`, `review-docs`, and `understand`; `analyze`, `consensus`, `debate`, `panel`, `qa`,
and `walkthrough` remain Claude-only.

---

## Smoke test

Runs a fixed set of read-only probes: `forge --version`, installation status, file existence checks. Prints a pass/fail
table. No intentional writes; sensitive paths are snapshotted before and after and asserted unchanged. No test repo
needed. Its compiled invocation identifies the selected runtime to the shared read-only script.

## Walkthrough

The default mode creates a hermetic test environment, installs Forge extensions into it, and verifies:

1. Files landed in the test repo (not your real `~/.claude/`)
2. Your real system was not modified (mtime assertions)
3. Isolation invariants are correct (`FORGE_HOME`, `CLAUDE_HOME`, and `CODEX_HOME` redirected; `HOME` unchanged for
   existing authentication)

Codex verification in the walkthrough is deliberately project-scoped under the hermetic repo at
`$FORGE_TEST_REPO/.agents/skills`. It never installs Codex user skills under the real `$HOME/.agents/skills`. Codex
planning/status subprocesses temporarily point `HOME` at a directory inside the test repo so duplicate discovery cannot
depend on or inspect real user skill packages; the interactive environment keeps the real `HOME` for auth.

The agent walks through each step interactively, explaining what it's checking and why. Risky operations (install,
uninstall) go through `run-in-repo.sh`; read-only checks are done directly.

Use `--sidecar` for sidecar runtime coverage (Docker startup, shell access, cleanup). This is the only place sidecar
runtime is exercised -- `/forge:qa` runs inside a container and cannot safely launch sidecars against container-local
paths.

## Full QA (`/forge:qa`)

Runs the full checklist inside a Docker container. Requires Docker Desktop.

**Requires `full` install profile:**

```bash
forge extension enable --scope user --profile full
forge extension enable --profile full
```

Then in Claude Code:

```
/forge:qa                              # Run full checklist
/forge:qa session proxy                # Run specific categories
/forge:qa --from 4.1                   # Resume from section 4.1
/forge:qa --from 10 --to 13            # Run sections 10-12; `--to` is exclusive
/forge:qa --stop                       # Stop and remove the QA container
```

The agent reads the checklist section by section, runs commands inside the container via `docker exec`, and checks
assertions. Auto-annotated sections run silently; human-annotated sections pause for your input. State is stored inside
the container for resume via `--from X.Y`. `--to X.Y` always means "stop before X.Y" rather than "run through X.Y".

The Docker QA is the only manual flow that exercises the Codex user target (`$HOME/.agents/skills`), because its home is
container-isolated. It also verifies project targets, persisted runtime selection during sync, duplicate safety,
local-scope rejection, package health in human/JSON status, and disable/uninstall cleanup.

## Runtime-aware extension checks

Use an explicit runtime when validating one skill surface:

```bash
# Project-scoped Codex skills (safe inside a disposable test repository)
forge extension enable --scope project --runtime codex --profile minimal --with skills --without commands
forge extension status --scope project --json
forge extension sync --scope project

# Claude skills
forge extension enable --scope user --profile minimal --with skills --without commands --runtime claude
```

Codex project packages install under `.agents/skills`; Codex user packages install under `$HOME/.agents/skills`. Claude
packages remain under `.claude/skills` or `$CLAUDE_HOME/skills`. Codex has no local/private skill target, so an explicit
`--scope local --runtime codex` request must fail rather than write into the shared project directory.

`forge extension status` reports each tracked runtime package and its health (`present`, `missing`, `duplicate`, or
`invalid-target`). Use `--json` to assert `runtime`, `skill`, `target_dir`, `state`, `missing_file_paths`,
`duplicate_dirs`, and `recovery`. `forge extension sync` preserves the installation's recorded runtime set even when a
runtime binary is temporarily absent.

---

## Other flags

Walkthrough:

```
/forge:walkthrough --setup-only        # Create test repo without running tests
/forge:walkthrough --reset             # Reset test repo to clean baseline
/forge:walkthrough --report            # Save report + logs + transcript after run
```

QA:

```
/forge:qa --stop                       # Stop and remove the QA container
/forge:qa --keep                       # Keep container running after completion
```

---

## How isolation works

The setup script creates a hermetic environment at `~/.forge/manual-testing/walkthrough/test-repo/` (override with
`FORGE_TEST_REPO`):

```
test-repo/
+-- .forge-home/         # Redirected Forge global state
+-- .claude-user/        # Redirected user-scope Claude extensions
+-- .codex-user/         # Redirected user-scope Codex config
+-- .agents/skills/      # Project-scoped portable Codex packages
+-- .forge/walkthrough/  # State, reports, fake Codex, and duplicate-scan HOME
+-- src/                 # Fixture source files
+-- tests/               # Fixture test files
+-- CLAUDE.md            # Fixture project file
```

Every risky operation passes through `run-in-repo.sh`, which applies a dangerous-path denylist, sources `env.sh`, and
enforces six numbered isolation/structure gates before running any command. Your real home directory is never touched.

---

## When to run

- **After installing Forge** -- run `/forge:smoke-test` in Claude or `$smoke-test` in Codex; add the Claude-only
  `/forge:walkthrough` for the interactive tour
- **After upgrading Forge** -- catch regressions with the walkthrough
- **Before a release** -- run `/forge:qa` for the full checklist
