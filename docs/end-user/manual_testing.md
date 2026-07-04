# Forge Manual Testing -- Installation Verification & Feature Tour

Three skills verify that Forge is installed and working correctly, with escalating isolation:

| Mode        | Command              | What it does                                              | Install profile |
| ----------- | -------------------- | --------------------------------------------------------- | --------------- |
| Smoke test  | `/forge:smoke-test`  | Read-only health check (no writes)                        | `standard`      |
| Walkthrough | `/forge:walkthrough` | Install + assert in sandbox, verify real system untouched | `standard`      |
| Full QA     | `/forge:qa`          | Full checklist in Docker                                  | `full`          |

- Canonical architecture: [`docs/design_appendix.md` section D](../design_appendix.md#d-interactive-manual-testing)
- Testing guidelines: [`testing_guidelines.md`](../developer/testing_guidelines.md)

---

## Quick start

Inside a Claude Code session:

```
/forge:smoke-test                      # Quick read-only health check
/forge:walkthrough                     # Default: interactive walkthrough
```

---

## Smoke test

Runs a fixed set of read-only probes: `forge --version`, installation status, file existence checks. Prints a pass/fail
table. No intentional writes; sensitive paths are snapshotted before and after and asserted unchanged. No test repo
needed.

## Walkthrough

The default mode creates a hermetic test environment, installs Forge extensions into it, and verifies:

1. Files landed in the test repo (not your real `~/.claude/`)
2. Your real system was not modified (mtime assertions)
3. Isolation invariants are correct (HOME, FORGE_HOME, CLAUDE_HOME redirected)

The agent walks through each step interactively, explaining what it's checking and why. Risky operations (install,
uninstall) go through `run-in-repo.sh`; read-only checks are done directly.

Use `--sidecar` for sidecar runtime coverage (Docker startup, shell access, cleanup). This is the only place sidecar
runtime is exercised -- `/forge:qa` runs inside a container and cannot safely launch sidecars against container-local
paths.

## Full QA (`/forge:qa`)

Runs the full checklist inside a Docker container. Requires Docker Desktop.

**Requires `full` install profile:**

```bash
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
forge-manual-test/
+-- .test-home/          # Redirected HOME, FORGE_HOME, CLAUDE_HOME
|   +-- .claude/
|   +-- .forge/
+-- .forge/manual-test/  # State file, env.sh, reports (never wiped)
+-- src/                 # Fixture source files
+-- tests/               # Fixture test files
+-- CLAUDE.md            # Fixture project file
```

Every risky operation passes through `run-in-repo.sh`, which sources `env.sh` and enforces 4 safety gates before running
any command. Your real home directory is never touched.

---

## When to run

- **After installing Forge** -- run `/forge:smoke-test` then `/forge:walkthrough`
- **After upgrading Forge** -- catch regressions with the walkthrough
- **Before a release** -- run `/forge:qa` for the full checklist
