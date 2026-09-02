# Forge Manual Testing -- Installation Verification & Feature Tour

Three skills verify that Forge is installed and working correctly, with escalating isolation:

| Mode        | Invocation                                  | What it does                                              | Runtime          | Install requirement |
| ----------- | ------------------------------------------- | --------------------------------------------------------- | ---------------- | ------------------- |
| Smoke test  | Claude: `/smoke-test`; Codex: `$smoke-test` | Read-only health check (no writes)                        | Claude and Codex | SKILLS module       |
| Walkthrough | `/walkthrough`                              | Install + assert in sandbox, verify real system untouched | Claude Code only | SKILLS module       |
| Full QA     | `/qa`                                       | Bounded exact-wheel checklist in Docker                   | Claude Code only | `full` profile      |

- Canonical architecture:
  [`docs/design_installation.md` section D](../design_installation.md#d-interactive-manual-testing)
- Testing guidelines: [`testing_guidelines.md`](../developer/testing_guidelines.md)

---

## Quick start

Inside a Claude Code session:

```
/smoke-test                      # Quick read-only health check
/walkthrough                     # Default: interactive walkthrough
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

The default creates a hermetic repository and teaches the complete direct managed-session loop without a provider key:

1. Verify package identity and snapshot the real Claude/Codex extension paths using privacy-preserving tree digests.
2. Enable sandboxed user runtime hooks and local project assets, then inspect which scope owns each surface.
3. Compare a managed session with the sessionless `forge claude start` and `forge codex start` launchers.
4. Create `walkthrough-demo` with `--model claude-haiku-4-5 --no-proxy --no-launch`. Before launch, inspect canonical
   route intent and the honest absence of committed runtime evidence.
5. Resume the session through Forge, confirm hook-written lifecycle evidence, use `%help` and `%session model show`, and
   try one visible policy interaction.
6. Exit cleanly and inspect the transcript, search, activity, and cost surfaces. Direct interactive activity can be
   sparse and direct-session spend can be unavailable; the walkthrough never invents proxy cost.
7. Resume into one fresh child with deterministic `structured` transfer, demonstrate incognito ephemerality, and clean
   every walkthrough-owned resource.

Session A is the guide. You open one Terminal inside the generated sandbox and launch the managed Claude child there.
The default has seven human checkpoints and two intentional model completions; more than 30 minutes is recorded for
review, not treated as a correctness failure by itself. Every Forge or sandbox-mutating command run by the guide goes
through the packaged `run-in-repo.sh` safety wrapper. Walkthrough Forge state is redirected; the six protected real
Claude settings/asset and Codex skill paths are compared before and after by type, mode, and content/tree digest without
copying their contents.

The sandbox keeps Forge-installed Claude hooks and skills separate from your real user settings. A generated launcher
shim loads those sandbox settings explicitly while retaining your existing native Claude authentication and transcript
store. Cleanup deletes the walkthrough's two native Claude transcripts and its sandbox artifact copies; it does not load
or modify unrelated real user settings.

Reset also checks the sandbox's raw Forge installation registry before removing anything. If a command run from a
sandboxed Terminal accidentally recorded another project's extension installation there, or an apparently owned row
points beyond its sandbox boundary, reset refuses and lists only the installation id, scope, project path, and refusal
reason. Reconcile that row from the listed project using the sandbox `FORGE_HOME`, restore the project's extension
package from a normal Forge environment, and retry reset. Do not delete `installed.json`: that would discard ownership
while leaving its target files behind.

The separate project registry inside the walkthrough's isolated Forge home grants hook trust but owns no files in its
enrolled checkouts. Cleanup strictly validates and clears that sandbox registry without modifying those checkouts; an
unreadable, malformed, or non-regular registry blocks reset. A previously rendered standalone dispatcher may remain
valid across runs, so the first doctor check accepts `current` or shows recovery when it is `missing` or `stale`.

`--from <section-or-step>` resumes only when the preserved checklist prefix and the selected options still match. A
version mismatch, changed or unverified prefix, or orphaned record refuses without changing the state and directs you to
`--reset`. `--report` saves package provenance, selected options, state, step and Forge logs, metrics, and a transcript
claim under `~/.forge/manual-testing/walkthrough/runs/`, outside sandbox cleanup.

Optional chapters are bounded and do not change the default result:

- `--codex` adds readiness plus one managed headless Codex continuation. Transfer uses `initial-message`, so hook trust
  enrollment is not required. The isolated `CODEX_HOME` accepts either an environment key/token or one explicitly
  supplied `--codex-auth <auth.json>` file; native `~/.codex/auth.json` is never imported implicitly.
- `--sidecar` adds launch through the packaged `openrouter-anthropic` template, one container/mount observation, and
  cleanup. It requires Docker, the configured sidecar image, and OpenRouter auth available to the sandbox (normally
  `OPENROUTER_API_KEY`). The default probes none of them.

The skill frontend remains Claude-only. Codex is an optional subject under test; Codex users still have the portable
`$smoke-test` Day 1 health check.

## Full QA (`/qa`)

Runs the full checklist inside a Docker container. Requires Docker Desktop.

**Requires `full` install profile:**

```bash
forge extension enable --scope user --profile full
forge extension enable --profile full
```

Then in Claude Code:

```
/qa                              # Build one wheel; development-only verdict
/qa --wheel dist/multi_forge-X.Y.Z-py3-none-any.whl
                                       # Run the pinned blocking release gate
/qa session proxy                # Run specific categories
/qa --wheel <same-wheel> --from 4.1
                                       # Resume a run that began with --wheel
/qa --from 10 --to 13            # Run sections 10-12; `--to` is exclusive
/qa --runtime-track latest --extended
                                       # Non-blocking client compatibility/exploration
/qa --codex-auth ~/.codex/auth.json
                                       # Copy only this Codex auth file into the container
/qa --stop                       # Stop and remove the QA container
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
path/version/SHA-256, matching host QA-driver SHA-256, observed runtime versions, provider profile, selection, counts,
verdict, state, logs, and transcript claim under `~/.forge/manual-testing/qa/runs/`.

The installed `/qa` driver must match the QA package inside the selected wheel. A mismatch stops before Docker mutation
instead of letting an older checklist produce evidence for a newer artifact. Run the selected wheel's
`forge extension sync --scope <owning-scope> --force`, then restart Claude Code so it reloads the synchronized skill
before starting a fresh QA run. If a legacy local tracking row makes sync reject Codex's unsupported local scope,
re-enable only the Claude assets with
`forge extension enable --scope local --runtime claude --profile full --copy --force` instead.

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
/walkthrough --setup-only              # Create/prove sandbox + installed package, then stop
/walkthrough --reset                   # Reclaim owned resources and recreate the baseline
/walkthrough --report                  # Save report, provenance, logs, state, and transcript claim
/walkthrough --from 10.2 --report      # Resume after validating preserved evidence/options
/walkthrough --codex                   # Add the optional Codex initial-message chapter
/walkthrough --codex --codex-auth ~/.codex/auth.json
                                            # Copy exactly one auth file into isolated CODEX_HOME
/walkthrough --sidecar                 # Add the optional Docker sidecar chapter
```

QA:

```
/qa --wheel <path>              # Release-capable pinned run
/qa --runtime-track latest      # Non-blocking compatibility run
/qa --extended                  # Include exploratory checklist steps
/qa --codex-auth <auth.json>    # Narrow Codex credential ingress
/qa --stop                       # Stop and remove the QA container
/qa --keep                       # Keep container running after completion
```

---

## How isolation works

The setup script creates a hermetic environment at `~/.forge/manual-testing/walkthrough/test-repo/` (override with
`FORGE_TEST_REPO`):

```
test-repo/
+-- .forge-home/         # Redirected Forge global state
+-- .claude-user/        # Redirected user-scope Claude extensions
+-- .codex-user/         # Redirected Codex config and optional explicit auth copy
+-- .forge/walkthrough/  # Generated environment, protected-path baseline, and progress
+-- src/                 # Fixture source files
+-- tests/               # Fixture test files
+-- CLAUDE.md            # Fixture project file
```

Every risky operation passes through `run-in-repo.sh`, which applies a dangerous-path denylist, sources `env.sh`, and
enforces six numbered isolation/structure gates before running any command. The ordinary `HOME` value remains available
to the managed Claude runtime for its existing login, but the walkthrough's owned Forge/Claude/Codex paths are
redirected and protected real extension targets must remain digest-identical. Reports live beside, not inside,
`test-repo/`.

---

## When to run

- **After installing Forge** -- run `/smoke-test` in Claude or `$smoke-test` in Codex; add the Claude-only
  `/walkthrough` for the interactive tour
- **After upgrading Forge** -- use the walkthrough to relearn and verify the managed-session loop
- **Before accepting walkthrough release evidence** -- install or sync the exact candidate wheel from a normal Terminal
  that has not sourced the walkthrough sandbox's `env.sh`, restart Claude so it reloads the candidate skill, and run
  `/walkthrough --setup-only` before the full reported journey
- **Before a release** -- build the candidate once and run `/qa --wheel <candidate>` for the full pinned checklist
