# Repository Guidelines

## Project Structure & Module Organization

`src/forge/` contains the Python app, split by domain (`cli/`, `session/`, `proxy/`, `policy/`, `core/`, `install/`,
`search/`, `review/`, `sidecar/`, `backend/`, `logs/`). Agent assets live in `src/skills/`, `src/commands/`, and
`src/agents/`. Tests are split by scope: `tests/src/` mirrors `src/forge/`, `tests/integration/` covers end-to-end and
Docker-backed flows, `tests/regression/` holds bug reproductions, and `tests/fixtures/` provides shared helpers. Keep
docs in `docs/`, runtime images in `docker/`, and automation scripts in `scripts/`.

## Documentation Guide

Use the repo docs as the source of truth for their domains: `README.md` for the overview and `docs/developer/` for
setup. This `AGENTS.md` is the primary repository-wide agent context. `CLAUDE.md` is a thin Claude Code entry point that
imports this file; keep shared instructions here and only Claude-specific routing there.
`docs/developer/coding_standards.md`, `testing_guidelines.md`, `documentation_guidelines.md`, `cli_style_guidelines.md`,
and `board_contract.md` define code style, test policy, doc writing, CLI command shape, and board workflow rules.
`docs/board/README.md` is a board directory guide with examples, not the authority. Update `docs/design.md` or the
corresponding session, runtime, telemetry, installation, workflow, or memory design document when architecture or file
ownership changes. When changing config ownership, auth resolution, installer behavior, proxy/session semantics, or
workflow prerequisites, also update the relevant `docs/end-user/*` guide so wheel-installed users get the right Day 1
path. Repository file-size thresholds and token-counter policy live in the tracked root `.file-size-limits.json`; a
personal hook may invoke the checker, but it does not own Multi-Forge's limits.

Board quick semantics: `todo/` means accepted but parked; starting a todo card means create or switch to the execution
branch, move the card directory to `doing/`, and create/update its `checklist.md`. `doing/` is active work; `paused/` is
partially-done work on hold and moves back to `doing/` when resumed; `done/` means shipped, verified, design docs
synced, and closeout recorded. `retired/` is terminal work that did not ship independently; it is excluded from live and
done counts, and reconsideration starts a new `proposed/` card.

Per-card branches and PRs remain the default. A shared two- or three-card batch is allowed only when an active epic
records fixed membership and order, the branch base, parallel or sequential boundaries, and integration ownership. Each
card still needs its own checklist, commit series, evidence, and closeout; run the applicable aggregate unit,
regression, pre-commit, and board/link checks on the integrated head before closing the batch together.

## Build, Test, and Development Commands

Use `uv` for dependencies and `make` for the standard workflow:

- `uv sync` installs runtime and dev dependencies.
- `./scripts/setup.sh --local` performs the editable local install used for development.
- `FORGE_DEV="$PWD" uv run forge session start dev-hooks` launches a managed session whose host hooks use this checkout;
  `FORGE_DEV` must be an absolute root, and the session must be relaunched after changing or unsetting it.
- `make deps` syncs dev dependencies and is the prerequisite behind the standard targets.
- `make build` builds the source distribution and wheel with `uv`.
- `uv run forge --help` checks the CLI entry point.
- `make test-unit` runs tests.
- `make test-integration` builds Docker images, starts test infrastructure, and runs integration-marked tests.
- `./scripts/test-integration.sh <path-or-pytest-args>` runs targeted integration tests with the same Docker/LiteLLM
  prerequisites; paths, `-k`, and other pytest flags pass through. When `GEMINI_API_KEY` is available, the script owns a
  temporary `FORGE_HOME` LiteLLM process on port 4001 and removes it on exit, so that port must be free.
- `./scripts/test-wheel-runtime.sh` builds and installs a clean wheel with dependencies resolved outside `uv.lock`, then
  smoke-tests packaged LiteLLM start/health/stop; run it when the LiteLLM compatibility ceiling or Forge-owned proxy
  dependency set changes.
- `make test-regression` runs regression tests.
- `make test` runs the full test suite.
- `make pre-commit` runs the full hook suite (ruff, black, isort, mypy, pyright, mdformat, gitleaks); run it before
  committing.
- `make pre-commit-md` runs the Markdown-only hook subset for docs-only changes.
- For targeted reruns, use direct `pytest` only after `make` has prepared prerequisites; integration flows depend on the
  setup performed by `make test-integration`.

The configured global pre-commit hook normalizes staged text, including replacing emoji with ASCII. Use `\U` escapes for
emoji that must survive in source strings. If a hook reformats a staged file, review and restage it before retrying the
commit.

## Release & UX Verification

Editable installs can hide packaging and clean-environment bugs. For changes that affect `pyproject.toml`,
`scripts/setup.sh`, installer code, bundled extensions (`src/skills/`, `src/commands/`, `src/agents/`), or runtime files
loaded with `importlib.resources`, build a wheel/sdist and verify the behavior from a clean install path when practical.
After installing or upgrading, run `/smoke-test` in Claude or `$smoke-test` in Codex; use Claude's `/walkthrough` for
the hermetic Day 1 path. Before a release, build one candidate with `make build`, install/sync that same wheel, restart
Claude, and run `/qa --wheel dist/multi_forge-X.Y.Z-py3-none-any.whl` on the default pinned runtime track. `/qa`
requires `forge extension enable --profile full`, and its installed driver must match the selected wheel.
`/qa --runtime-track latest --extended` is non-blocking compatibility evidence, not a release gate.

For Day 1 install or extension lifecycle changes, verify the global-tool path with `forge extension doctor` (use
`--json` when checking install kind, PATH reachability, hook dispatcher, project registry, and compatibility fields),
then verify `forge extension enable --scope user` for runtime hooks and `forge extension enable` for project setup. For
runtime-skill/compiler changes, verify `forge runtime list --json`, `forge extension enable --runtime claude|codex|all`,
and `forge extension status --json`; also exercise `forge extension sync` and
`forge extension disable --runtime claude|codex|all` when package ownership changes. `--runtime` filters every module by
its runtime ownership, while sync preserves the installation's tracked runtime set and runtime-package health belongs to
`extension status`, not `extension doctor`. Runtime-scoped disable removes only selected ownership; omitted runtime
surfaces and unrelated user content must remain, while omitting `--runtime` retains whole-installation behavior. Codex
skills support user and project scopes only (`$HOME/.agents/skills` and `<root>/.agents/skills`); never map Forge local
scope onto the shared project target. For installer/GC changes involving untracked runtime packages, verify the
schema-v3 `forge extension status --json` object (`installations` plus `unmanaged_skill_packages`), then preview cleanup
with `forge clean --scope <project|workspace|all> --verbose` before applying the same scope with `--yes`. Cleanup must
remain fail-closed: unmarked, modified, malformed/newer, or unsafe packages are report-only and must not be removed
automatically. For Codex-hook disable changes, also verify behavior after `$CODEX_HOME` changes: disable must name both
config paths and preserve the managed block and tracking row without mutating either.

For auth, proxy, and workflow changes, test the no-`.env` path explicitly: credentials should resolve from environment
variables first and `~/.forge/credentials.yaml` second, CLI failures should be actionable rather than raw tracebacks,
and workflow preflight should fail fast when required auth or proxies are missing. Remember that proxy health only
confirms the local proxy process is reachable; use `forge proxy start <proxy_id> --smoke-test` to verify upstream LLM
connectivity after first setup, credential changes, or proxy auth changes. For create-path changes, also verify
`forge proxy create <template> --json --smoke-test`: it emits one result object, and a failed probe exits non-zero while
retaining the created, reused, or adopted proxy for inspection and retry. For packaged model/template updates, verify a
fresh realization and a pre-existing user-owned snapshot: upgrades must not rewrite `proxy.yaml` or materialized LiteLLM
config, and new routes require `forge proxy edit <proxy_id>` or recreation of the affected proxy/backend before restart.

For downstream-telemetry retention or config-ownership changes, inspect configured, effective, and source state with
`forge config show --json`; preview legacy proxy-key migration with `forge config migrate-retention [--json]`, apply it
with `--yes`, and restart running proxies. Without an explicit global policy, conflicting or unreadable legacy inputs
must disable pruning and block migration instead of selecting a value. Apply writes the global policy before removing
still-matching legacy keys, and normal proxy startup must not rewrite user-owned proxy files.

For workflow-worker or review-engine changes, run `forge workflow list-models --available --json`, refresh Codex
readiness with `forge runtime preflight codex`, then exercise `forge workflow panel -p "<review prompt>" -m codex` and
`forge workflow panel -p "<review prompt>" -m claude-opus,codex`. Codex workers are opt-in and run read-only; panels
that include one must use blind context (`--context blind`). The default worker set remains Claude-backed. `--proxy`
does not reroute direct Claude or Codex workers, and `--effort` applies only to Claude workers.

For policy CLI or hook changes, exercise `forge policy check --bundle coding_standards --file <path>` and
`git diff | forge policy check --bundle coding_standards --diff`; exactly one content source is valid. Unknown policy
bundle names, unknown `bundle_config` owners, and invalid supported-bundle field types must fail atomic engine
construction. The diff path splits multi-file patches into per-file contexts, evaluates tests before implementation
through one engine, and reports `files_checked` plus each violation's `file_path` in JSON. It must preserve boundaries
for Git C-quoted paths, renames, copies, binary patches, and combined diffs, and fail closed when a non-deletion chunk
cannot be attributed. The removed `workflow` bundle diagnostic must name both `policy.bundles` and
`policy.bundle_config.workflow`. Claude and Codex hooks report that build error and allow the action before the
configured fail mode applies.

For CLI surface changes, check `docs/developer/cli_style_guidelines.md`: use explicit leaf verbs, keep read-command
results on stdout, route diagnostics/errors/prompts to stderr, expose stable `--json` on scriptable list/show/status
surfaces, and send recovery output through `forge.cli.output` helpers. Conflict-bearing dry-run previews remain on
stdout even when they exit non-zero; only the terminating failure diagnostic goes to stderr. Keep error messages
accurate and offer only recovery commands that apply to the current install and runtime. Extend
`tests/src/cli/test_output_streams.py` when a new read leaf could split result and diagnostic streams.

For backend-source, telemetry, provider-trace, and cost-accounting changes, verify the operator read paths:
`forge model backend list|show <source-or-backend-id>|test-auth <source-id>`,
`forge telemetry trace list|show <request_id>|explain <request_id>`, and
`forge telemetry costs show --by-model|--by-verb`, plus `forge proxy metrics [proxy_id] --json`. Cost breakdown flags
are mutually exclusive; JSON retains both summaries, and verb runs count unique Forge run IDs separately from requests.
Bare metrics JSON is always a proxy-ID-to-metrics/null map, while a selected proxy returns its raw metrics object. Use
`forge telemetry costs reset --dry-run` before destructive telemetry resets; `reset` wipes legacy costs,
downstream/upstream telemetry, cap state, audit sidecar state, usage events, and derived status-line caches, while
running proxies keep in-memory cost/cap counters until restarted. For backend lifecycle or remote-reconcile changes,
also verify `forge model backend start <source-or-adapter>`, `forge model backend stop <runtime-id>...|--all`,
`forge model backend delete <adapter>`, and `forge model backend reconcile <source-id> --request-id|--remote-id`; `stop`
targets runtime instance ids from `list`, not source ids or adapter names.

For resume, transfer, memory-writer, and activity changes, verify the user-facing surfaces:
`forge session resume <name> --fresh --review`, `forge session transfer show|regenerate|edit|diff`,
`forge session memory report [session] [--latest|--all|--json]`, and `forge telemetry activity [session]`; `forge usage`
is removed, and `forge telemetry costs show` remains the authoritative proxy-scoped spend view. For fresh-transfer
ancestry changes, verify `forge session resume <parent> --fresh --depth <N|all>`; explicit uses of `--strategy` or
`--depth` require `--fresh`, `N` must be positive, and `all` follows lineage to the terminal ancestor. For rewind
launch-strategy changes, verify `forge session resume <parent> --fresh --strategy rewind --drop-last N` and
`forge session fork <parent> --worktree|--into <path> --strategy rewind --drop-last N`; `rewind` is not a
`forge session transfer regenerate` strategy.

For session-store, launchability, repair, or workspace-scope changes, preview orphan recovery with
`forge session repair [--json]`, apply it with `forge session repair --yes`, check degraded records with
`forge session list --scope workspace --json` and `forge session show <session> --json`, and inspect Git worktree
membership and session occupancy with `forge workspace worktrees [--json]`. Repair is scoped to the current Forge root;
it must never recreate missing worktrees or accept collision/corrupt records. Valid missing-worktree sessions remain
visible but unlaunchable until the checkout returns.

For session deletion or cleanup changes, cancel an unconfirmed `forge session delete <name>` and compare the default
`forge session clean --older-than <days>` preview with the corresponding `--yes` apply, including `--delete-worktree`
cases. Pre-confirmation reads must not rewrite session or active indexes, preview and apply must agree on targets and
refusals, and artifact-retention output is valid only when the containing Forge root survives. Confirmed deletion may
still repair derived index state.

For Claude model-route changes, exercise `forge session start|resume|fork|incognito --model <catalog-id-or-alias>` and
use `--model-tier haiku|sonnet|opus` only to disambiguate a multi-tier proxy match. Inspect intent, durable commitment,
current proxy facts, and the validated event sequence with `forge session model show|history <session> --json`. Explicit
`--proxy` is strict, `--no-proxy` accepts only direct Claude models, and bare resume or inherited-route fork reuses
stored route intent. `--model` alone cannot cross an inherited proxy boundary; refusal recovery must offer only
applicable restart or reroute commands, preserve the exact resume target and complete intended fork action, and add
`--model-tier` only when disambiguation is needed. A non-Claude `--model` may start a paid proxy even with
`--no-launch`; Codex sessions reject these route-selection flags.

For native-session adoption changes, run `forge session adopt [--json]` from the native launch directory, adopt a full
Claude conversation or Codex thread id with `forge session adopt <conversation-id> --name <name>`, then resume the
managed session. Bare preview lists Claude conversations only and `--model` is Claude-only; runtime selection must come
from on-disk evidence, ambiguous or unverifiable matches must fail closed, and deleting the Forge session must preserve
the original transcript or rollout.

For Codex-runtime session changes, start with `forge runtime preflight codex`, then verify the relevant launch path:
`forge session start <name> --runtime codex --resume-from <parent> --task "..."`,
`forge session resume <name> --task "..."`, or the interactive TUI path that omits `--task`. `--context-delivery hook`
and Codex policy enforcement require Codex hook registration/trust for `$FORGE_HOME/bin/forge-hook codex-session-start`
and `$FORGE_HOME/bin/forge-hook codex-policy-check`; use `forge codex status` for static registration and
`forge runtime preflight codex --verify-enrollment` for empirical user-scope trust verification (it runs one cheap Codex
turn). The default transfer delivery is `initial-message`. Runtime hooks are user-scoped via the `forge-hook <name>`
dispatcher, while project/local extension installs own status line and project assets. For consumer-lane or
subscription-billing changes, verify
`forge session lane set|show|clear --consumer <supervisor|memory_writer|shadow_curation|team_supervisor>`,
`forge policy supervisor status`, and `forge telemetry activity [session]`; `--backend claude-max` should label only
keyless direct runs as `subscription_quota`, while resolvable keys remain `api` and proxied runs remain `unknown`.

## Coding Style & Naming Conventions

Target Python 3.11 with 4-space indentation and a 120-character line length. Use `snake_case` for modules, functions,
and variables, `CamelCase` for classes, and `UPPER_CASE` for constants. Follow the repo’s Python conventions: public
methods before private ones, type hints on public functions, and comments that explain why. Quality checks center on
`make pre-commit`, which runs ruff, black, isort, mypy, pyright, mdformat, and gitleaks.

## Design and Review Discipline

Treat user-defined domain concepts as first-class architecture unless the user explicitly narrows them. Do not collapse
a named abstraction into an implementation detail; ask for clarification when its scope is genuinely ambiguous.

For code or document review requests, complete one full pass and report all findings together unless the user explicitly
asks for an iterative review.

## Testing Guidelines

Use `pytest`, not `unittest`. Mirror source paths in `tests/src/` (for example, `src/forge/session/store.py` maps to
`tests/src/session/test_store.py`). Mark integration files with `pytest.mark.integration`. Name regression files
`test_bug_<id>_<description>.py` and mark them `regression`. Every bug fix should include a regression test, and broken
tests should be fixed or removed rather than skipped. Docker is expected to be running locally: run integration tests
(target relevant files via `./scripts/test-integration.sh <path-or-pytest-args>`, not the full suite) for changes
touching hooks, sessions (including Codex runtime/frontend), the memory writer, proxy runtime, backend source catalog,
consumer-lane bindings, telemetry/cost/provider-trace paths, rewind resume/fork behavior, workflow-worker/headless
invoker fan-out, or the installer — don't defer them to closeout.

Indexed-session tests must publish and delete coherent state through `tests.fixtures.session_state`: use
`publish_session`, `publish_session_from_fields`, and `delete_published_session`. Reserve `seed_row_only_session` and
`remove_index_row_only` for deliberately incomplete states and explain the violated invariant at the call site; do not
restore the retired `IndexStore.add_session`, `add_from_state`, or `remove_session` shortcuts.

## GitHub CLI Auth

GitHub CLI operations use `GH_TOKEN` from direnv. This repo's `.envrc` reads `~/.keys/github_token`, but long-lived
shells can keep a stale token after that file changes. When `gh` reports `Bad credentials` even though direnv is
configured, re-evaluate `.envrc` for the command instead of trusting the already loaded environment:

```bash
direnv exec . gh auth status
direnv exec . gh pr view
direnv exec . gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <notes.md> --latest
```

Do not print token values while debugging. To diagnose safely, compare presence/length or make a status-only API probe
through `direnv exec .`; `gh` gives `GH_TOKEN` precedence over stored credentials, and unsetting `GH_TOKEN` may make
`gh` appear logged out even though SSH-based `git push` still works.

This clone has both `origin` and a parent upstream remote. For PR creation, pin the GitHub repository and branch
coordinates explicitly: `direnv exec . gh pr create --repo <owner>/<repo> --base main --head <branch>`.

In a network-restricted Codex sandbox, `gh auth status` can misleadingly label a valid token as invalid when the real
failure is inability to reach `api.github.com`. Do not ask the user to rotate the token from that message alone. First
confirm, without printing the secret, that direnv's token is present and matches the trimmed token file; then run
`direnv exec . gh api user --silent`. If that reports a connection error, rerun the auth/API probe with approved network
access before diagnosing credentials. The connected GitHub plugin authenticates independently of `GH_TOKEN`; a plugin
profile/repository read can separately confirm connector identity and repository permissions while CLI connectivity is
being debugged.

## Release Process

Version lives in `pyproject.toml`. PyPI publishing is automated: push an annotated `v*` tag to trigger the
`.github/workflows/publish.yml` workflow (trusted publishing via OIDC). No local PyPI credentials are needed.

Release checklist:

1. Verify the current version and latest tag: `rg -n '^version =' pyproject.toml && git tag --sort=-v:refname | head`.
2. Bump `pyproject.toml`, then run `uv lock` so `uv.lock` records the project version.
3. Build locally before tagging: `make build`.
4. Run release-appropriate checks, normally `make pre-commit` for a package release.
5. Commit on `main`, create an annotated tag, and push both: `git commit -m "chore: release X.Y.Z"`,
   `git tag -a vX.Y.Z -m "Release X.Y.Z"`, `git push origin main vX.Y.Z`.
6. Confirm the `Publish to PyPI` workflow succeeds and verify PyPI lists the new wheel and sdist. The public JSON and
   simple-index endpoints are useful checks: `https://pypi.org/pypi/multi-forge/X.Y.Z/json` and
   `https://pypi.org/simple/multi-forge/`.
7. Create the GitHub release after the tag exists:
   `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <notes.md> --latest`.

## Commit and PR Writing Style

**Core Philosophy:** Write for a human reviewer, not an execution log. Detail must scale with *risk and novelty*, not
diff size. Every sentence must earn its place by actively helping someone review, test, or understand the change.

### Commits

- **DO** use conventional prefixes (`feat:`, `fix:`, `docs:`, `chore:`).
- **DO** write short, imperative, and concrete subjects.
- **DO** default to a subject line only. Add a body *only* when risk or novelty needs it (non-obvious decision,
  migration, subtle bug). Mechanical or obvious changes stay subject-only — a blank body is not incompleteness.
- **DO** split commits by reviewable intent when practical. Avoid noisy checkpoint commits.
- **DO NOT** use generic AI filler words (e.g., "comprehensive", "robust", "seamless", "key changes", "delves",
  "significantly improves") unless backed by hard metrics.
- **DO NOT** narrate the development process, implementation phases, or your internal agent reasoning.

### Pull Requests

- **Title for the code, not the author:** Do not prefix PR titles with agent/source tags such as `[codex]`; use the same
  concise, human-readable style as commit subjects.
- **Focus on the "Why" and "How":** Summarize the intent. Call out non-obvious design decisions, risks, limitations,
  migrations, and specific areas where the reviewer should focus.
- **Provide Proof:** Name the commands you ran and any non-passing results (failures/skips) — not full logs.
- **Skip the Inventory:** DO NOT write file-by-file, commit-by-commit, or function-by-function summaries. Group details
  by *review concern*, not component inventory.
- **No Transcripts:** DO NOT include implementation diaries, phase histories, or exhaustive rationale. Move deep context
  to linked docs. The PR body is a review interface, not a transcript.
- **Don't Repeat the Diff:** If the code makes it obvious, do not write it in the PR body.

### Final Self-Correction

Before committing or opening or updating a PR re-read your generated description. **Delete any sentence** that is
filler, states the obvious, or would not change how a human reviews, tests, or understands the commit or the PR.
