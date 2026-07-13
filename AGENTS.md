# Repository Guidelines

## Project Structure & Module Organization

`src/forge/` contains the Python app, split by domain (`cli/`, `session/`, `proxy/`, `policy/`, `core/`, `install/`,
`search/`, `review/`, `sidecar/`, `backend/`, `logs/`). Agent assets live in `src/skills/`, `src/commands/`, and
`src/agents/`. Tests are split by scope: `tests/src/` mirrors `src/forge/`, `tests/integration/` covers end-to-end and
Docker-backed flows, `tests/regression/` holds bug reproductions, and `tests/fixtures/` provides shared helpers. Keep
docs in `docs/`, runtime images in `docker/`, and automation scripts in `scripts/`.

## Documentation Guide

Use the repo docs as the source of truth for their domains: `README.md` for the overview, `docs/developer/` for setup,
and `CLAUDE.md` for agent context. `docs/developer/coding_standards.md`, `testing_guidelines.md`,
`documentation_guidelines.md`, `cli_style_guidelines.md`, and `board_contract.md` define code style, test policy, doc
writing, CLI command shape, and board workflow rules. `docs/board/README.md` is a board directory guide with examples,
not the authority. Update `docs/design.md` and `docs/design_appendix.md` when architecture or file ownership changes.
When changing config ownership, auth resolution, installer behavior, proxy/session semantics, or workflow prerequisites,
also update the relevant `docs/end-user/*` guide so wheel-installed users get the right Day 1 path.

Board quick semantics: `todo/` means accepted but parked; starting a todo card means create or switch to the execution
branch, move the card directory to `doing/`, and create/update its `checklist.md`. `doing/` is active work; `paused/` is
partially-done work on hold and moves back to `doing/` when resumed; `done/` means shipped, verified, design docs
synced, and closeout recorded. `retired/` is terminal work that did not ship independently; it is excluded from live and
done counts, and reconsideration starts a new `proposed/` card.

## Build, Test, and Development Commands

Use `uv` for dependencies and `make` for the standard workflow:

- `uv sync` installs runtime and dev dependencies.
- `./scripts/setup.sh --local` performs the editable local install used for development.
- `make deps` syncs dev dependencies and is the prerequisite behind the standard targets.
- `uv run forge --help` checks the CLI entry point.
- `make test-unit` runs tests.
- `make test-integration` builds Docker images, starts test infrastructure, and runs integration-marked tests.
- `./scripts/test-integration.sh <path-or-pytest-args>` runs targeted integration tests with the same Docker/LiteLLM
  prerequisites; paths, `-k`, and other pytest flags pass through.
- `make test-regression` runs regression tests.
- `make test` runs the full test suite.
- `make pre-commit` runs the full hook suite (ruff, black, isort, mypy, pyright, mdformat, gitleaks); run it before
  committing.
- `make pre-commit-md` runs the Markdown-only hook subset for docs-only changes.
- For targeted reruns, use direct `pytest` only after `make` has prepared prerequisites; integration flows depend on the
  setup performed by `make test-integration`.

## Release & UX Verification

Editable installs can hide packaging and clean-environment bugs. For changes that affect `pyproject.toml`,
`scripts/setup.sh`, installer code, bundled extensions (`src/skills/`, `src/commands/`, `src/agents/`), or runtime files
loaded with `importlib.resources`, build a wheel/sdist and verify the behavior from a clean install path when practical.
For Day 1 install or extension lifecycle changes, verify the global-tool path with `forge extension doctor` (use
`--json` when checking install kind, PATH reachability, hook dispatcher, project registry, and compatibility fields),
then verify `forge extension enable --scope user` for runtime hooks and `forge extension enable` for project setup.

For auth, proxy, and workflow changes, test the no-`.env` path explicitly: credentials should resolve from environment
variables first and `~/.forge/credentials.yaml` second, CLI failures should be actionable rather than raw tracebacks,
and workflow preflight should fail fast when required auth or proxies are missing. Remember that proxy health only
confirms the local proxy process is reachable; use `forge proxy start <proxy_id> --smoke-test` to verify upstream LLM
connectivity after first setup, credential changes, or proxy auth changes.

For CLI surface changes, check `docs/developer/cli_style_guidelines.md`: use explicit leaf verbs, keep read-command
results on stdout, route diagnostics/errors/prompts to stderr, expose stable `--json` on scriptable list/show/status
surfaces, and send recovery output through `forge.cli.output` helpers. Extend `tests/src/cli/test_output_streams.py`
when a new read leaf could split result and diagnostic streams.

For backend-source, telemetry, provider-trace, and cost-accounting changes, verify the operator read paths:
`forge model backend list|show <source-or-backend-id>|test-auth <source-id>`,
`forge telemetry trace list|show <request_id>|explain <request_id>`, and
`forge telemetry costs show --by-model|--by-verb`. Use `forge telemetry costs reset --dry-run` before destructive
telemetry resets; `reset` wipes legacy costs, downstream/upstream telemetry, cap state, audit sidecar state, usage
events, and derived status-line caches, while running proxies keep in-memory cost/cap counters until restarted. For
backend lifecycle or remote-reconcile changes, also verify `forge model backend start <source-or-adapter>`,
`forge model backend stop <runtime-id>...|--all`, `forge model backend delete <adapter>`, and
`forge model backend reconcile <source-id> --request-id|--remote-id`; `stop` targets runtime instance ids from `list`,
not source ids or adapter names.

For resume, transfer, memory-writer, and activity changes, verify the user-facing surfaces:
`forge session resume <name> --fresh --review`, `forge session transfer show|regenerate|edit|diff`,
`forge session memory report [session] [--latest|--all|--json]`, and `forge telemetry activity [session]`; `forge usage`
is removed, and `forge telemetry costs show` remains the authoritative proxy-scoped spend view. For rewind
launch-strategy changes, verify `forge session resume <parent> --fresh --strategy rewind --drop-last N` and
`forge session fork <parent> --worktree|--into <path> --strategy rewind --drop-last N`; `rewind` is not a
`forge session transfer regenerate` strategy.

For Codex-runtime session changes, start with `forge runtime preflight codex`, then verify the relevant launch path:
`forge session start <name> --runtime codex --resume-from <parent> --task "..."`,
`forge session resume <name> --task "..."`, or the interactive TUI path that omits `--task`. `--context-delivery hook`
and Codex policy enforcement require Codex hook registration/trust for `$FORGE_HOME/bin/forge-hook codex-session-start`
and `$FORGE_HOME/bin/forge-hook codex-policy-check`; the default transfer delivery is `initial-message`. Runtime hooks
are user-scoped via the `forge-hook <name>` dispatcher, while project/local extension installs own status line and
project assets. For consumer-lane or subscription-billing changes, verify
`forge session lane set|show|clear --consumer <supervisor|memory_writer|shadow_curation|team_supervisor>`,
`forge policy supervisor status`, and `forge telemetry activity [session]`; `--backend claude-max` should label only
keyless direct runs as `subscription_quota`, while resolvable keys remain `api` and proxied runs remain `unknown`.

## Coding Style & Naming Conventions

Target Python 3.11 with 4-space indentation and a 120-character line length. Use `snake_case` for modules, functions,
and variables, `CamelCase` for classes, and `UPPER_CASE` for constants. Follow the repo’s Python conventions: public
methods before private ones, type hints on public functions, and comments that explain why. Quality checks center on
`make pre-commit`, which runs ruff, black, isort, mypy, pyright, mdformat, and gitleaks.

## Testing Guidelines

Use `pytest`, not `unittest`. Mirror source paths in `tests/src/` (for example, `src/forge/session/store.py` maps to
`tests/src/session/test_store.py`). Mark integration files with `pytest.mark.integration`. Name regression files
`test_bug_<id>_<description>.py` and mark them `regression`. Every bug fix should include a regression test, and broken
tests should be fixed or removed rather than skipped. Docker is expected to be running locally: run integration tests
(target relevant files via `./scripts/test-integration.sh <path-or-pytest-args>`, not the full suite) for changes
touching hooks, sessions (including Codex runtime/frontend), the memory writer, proxy runtime, backend source catalog,
consumer-lane bindings, telemetry/cost/provider-trace paths, rewind resume/fork behavior, or the installer — don't defer
them to closeout.

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
3. Build locally before tagging: `uv build`.
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
