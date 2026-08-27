# Forge Manual Testing -- Installation Verification & Feature Tour

Three skills verify that Forge is installed and working correctly, with escalating isolation:

| Mode        | Invocation                                        | What it does                                              | Runtime          | Install requirement |
| ----------- | ------------------------------------------------- | --------------------------------------------------------- | ---------------- | ------------------- |
| Smoke test  | Claude: `/forge:smoke-test`; Codex: `$smoke-test` | Read-only health check (no writes)                        | Claude and Codex | SKILLS module       |
| Walkthrough | `/forge:walkthrough`                              | Install + assert in sandbox, verify real system untouched | Claude Code only | SKILLS module       |
| Full QA     | `/forge:qa`                                       | Bounded exact-wheel checklist in Docker                   | Claude Code only | `full` profile      |

- Canonical architecture:
  [`docs/design_installation.md` section D](../design_installation.md#d-interactive-manual-testing)
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

`walkthrough` and `qa` remain Claude-only because they orchestrate Claude Code interaction. The nine portable skills are
`analyze`, `challenge`, `consensus`, `debate`, `panel`, `review`, `review-docs`, `smoke-test`, and `understand`.

---

## Smoke test

Runs a fixed set of read-only probes: `forge --version`, installation status, file existence checks. Prints a pass/fail
table. No intentional writes; sensitive paths are snapshotted before and after and asserted unchanged. No test repo
needed. Its compiled invocation identifies the selected runtime and directly executes the installed script, whose entry
point selects the interpreter independently of the session CWD.

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
/forge:qa                              # Build one wheel; development-only verdict
/forge:qa --wheel dist/multi_forge-X.Y.Z-py3-none-any.whl
                                       # Run the pinned blocking release gate
/forge:qa session proxy                # Run specific categories
/forge:qa --wheel <same-wheel> --from 4.1
                                       # Resume a run that began with --wheel
/forge:qa --from 10 --to 13            # Run sections 10-12; `--to` is exclusive
/forge:qa --runtime-track latest --extended
                                       # Non-blocking client compatibility/exploration
/forge:qa --codex-auth ~/.codex/auth.json
                                       # Copy only this Codex auth file into the container
/forge:qa --stop                       # Stop and remove the QA container
```

The agent reads the checklist section by section, runs commands inside the container via `docker exec`, and checks
assertions. Auto-annotated sections run silently; human-annotated sections pause for your input. State is stored inside
the mounted host QA directory for resume via `--from X.Y`. `--to X.Y` always means "stop before X.Y" rather than "run
through X.Y".

The default selection runs clean-wheel and human-acceptance evidence and excludes exhaustive contracts already owned by
automated tests. `--extended` adds provider-variance-prone exploratory journeys. The blocking plan is capped at 12 human
checkpoints and 8 subject-under-test model completions. A run over 45 minutes needs explicit review but does not become
a product failure solely because of duration.

Release sign-off requires an explicit prebuilt wheel on the repository-pinned Claude/Codex runtime track. Omitting
`--wheel` still exercises one exact locally built wheel, but its verdict is development-only. `latest`, category/range,
missing blocking evidence, and pending duration-review runs cannot report a release pass. Run artifacts record the wheel
path/version/SHA-256, observed runtime versions, provider profile, selection, counts, verdict, state, logs, and
transcript claim under `~/.forge/manual-testing/qa/runs/`.

Only runs started with an explicit prebuilt `--wheel` can resume the same container. Development runs are
single-invocation; start over with `--reset` if their container is still running. Their wheels remain under
`~/.forge/manual-testing/qa/artifacts/build.*` because the evidence records their exact paths; remove an old build
directory only after its development evidence is no longer needed.

The default `openrouter` profile is required for the blocking provider-trace and remote-reconciliation seam. The
`remote-litellm` profile remains available for diagnostic compatibility coverage, but a full run on that profile records
the unsupported OpenRouter-only step as an evidence gap instead of claiming a complete release verdict. The `latest`
runtime track also rebuilds its client layers and requires a fresh QA container so a cached `latest` tag cannot
masquerade as current compatibility evidence.

The Docker QA is the only manual flow that exercises the Codex user target (`$HOME/.agents/skills`), because its home is
container-isolated. It also verifies project targets, managed-runtime retention during automatic re-enable, explicit
runtime narrowing, persisted runtime selection during sync, duplicate safety and recovery output, local-scope rejection,
package health (including dangling leaves) in human/JSON status, strict tracking ownership, and disable/uninstall
cleanup.

## Runtime-aware extension checks

Use an explicit runtime when validating one runtime-owned extension surface:

```bash
# Project-scoped Codex skills (safe inside a disposable test repository)
forge extension enable --scope project --runtime codex
forge extension status --scope project --json
forge extension sync --scope project

# Claude skills
forge extension enable --scope user --profile minimal --with skills --without commands --runtime claude
```

Codex project packages install under `.agents/skills`; Codex user packages install under `$HOME/.agents/skills`. Claude
packages remain under `.claude/skills` or `$CLAUDE_HOME/skills`. Codex has no local/private skill target, so an explicit
`--scope local --runtime codex` request must fail rather than write into the shared project directory. At user scope,
`--runtime codex` also selects the Codex half of `hooks` and filters every Claude-only module; at project scope hooks
are scope-omitted, leaving Codex skills only.

`forge extension status` reports each tracked runtime package and its health (`present`, `missing`, `duplicate`, or
`invalid-target`). Use `--json` to assert `runtime`, `skill`, `target_dir`, `state`, `missing_file_paths`,
`duplicate_dirs`, and `recovery`. Automatic enable on an existing installation and `forge extension sync` preserve its
recorded runtime set even when a runtime binary is temporarily absent. An explicit `--runtime` refreshes selected
surfaces but preserves omitted tracked runtime ownership; disable owns removal. Cross-scope Forge-managed duplicates
report the owning scope's exact disable command, while only untracked duplicates get remove-or-rename guidance.
User-scope checks include valid, present tracked project/local packages outside the current directory chain because a
user package would be visible from those projects. A package root or descendant directory replaced by a symlink must
report `invalid-target`; enable, sync, and disable must refuse it without changing the link target or tracking row. A
dangling tracked leaf symlink must instead report `missing`, and sync must recreate it.

Run the following failure-path checks only in a disposable Forge home:

- From a subdirectory of a tracked Codex-only project, unscoped sync/disable/status must resolve the exact project row
  even without `.claude/`.
- A v3 `skill_packages` row with empty, out-of-package, or non-ledger-backed `file_paths` must make status/sync/disable
  fail before package or tracking mutation.
- If one target makes `forge extension disable --all --yes` fail, the command must still attempt the remaining rows and
  exit non-zero. `scripts/setup.sh --uninstall` must then preserve `$FORGE_HOME/installed.json`; it must also preserve
  that state when the Forge command is unavailable.

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
/forge:qa --wheel <path>              # Release-capable pinned run
/forge:qa --runtime-track latest      # Non-blocking compatibility run
/forge:qa --extended                  # Include exploratory checklist steps
/forge:qa --codex-auth <auth.json>    # Narrow Codex credential ingress
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
- **Before a release** -- build the candidate once and run `/forge:qa --wheel <candidate>` for the full pinned checklist
