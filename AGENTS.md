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
`documentation_guidelines.md`, and `board_contract.md` define code style, test policy, doc writing, and board workflow
rules. `docs/board/README.md` is a board directory guide with examples, not the authority. Update `docs/design.md` and
`docs/design_appendix.md` when architecture or file ownership changes. When changing config ownership, auth resolution,
installer behavior, proxy/session semantics, or workflow prerequisites, also update the relevant `docs/end-user/*` guide
so wheel-installed users get the right Day 1 path.

Board quick semantics: `todo/` means accepted but parked; starting a todo card means create or switch to the execution
branch, move the card directory to `doing/`, and create/update its `checklist.md`. `doing/` is active work; `paused/` is
partially-done work on hold and moves back to `doing/` when resumed; `done/` means shipped, verified, design docs
synced, and closeout recorded.

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

For auth, proxy, and workflow changes, test the no-`.env` path explicitly: credentials should resolve from environment
variables first and `~/.forge/credentials.yaml` second, CLI failures should be actionable rather than raw tracebacks,
and workflow preflight should fail fast when required auth or proxies are missing. Remember that proxy health only
confirms the local proxy process is reachable; use `forge proxy start <proxy_id> --smoke-test` to verify upstream LLM
connectivity after first setup, credential changes, or proxy auth changes.

For backend-source, telemetry, provider-trace, and cost-accounting changes, verify the operator read paths:
`forge backend list|show <source-or-backend-id>|test-auth <source-id>`,
`forge provider trace list|show <request_id>|explain <request_id>`, and `forge proxy costs show --by-model|--by-verb`.
Use `forge proxy costs reset --dry-run` before destructive telemetry resets; `reset` wipes legacy costs,
downstream/upstream telemetry, cap state, audit sidecar state, usage events, and derived status-line caches, while
running proxies keep in-memory cost/cap counters until restarted.

For resume, transfer, memory-writer, and activity changes, verify the user-facing surfaces:
`forge session resume <name> --fresh --review`, `forge transfer show|regenerate|edit|diff`,
`forge memory report show [--all]`, and `forge activity [session]`; `forge usage` is removed, and
`forge proxy costs show` remains the authoritative proxy-scoped spend view.

For Codex-runtime session changes, start with `forge runtime preflight codex`, then verify the relevant launch path:
`forge session start <name> --runtime codex --resume-from <parent> --task "..."`,
`forge session resume <name> --task "..."`, or the interactive TUI path that omits `--task`. `--context-delivery hook`
and Codex policy enforcement require manual Codex hook registration/trust for `forge hook codex-session-start` and
`forge hook codex-policy-check`; the default transfer delivery is `initial-message`.

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
telemetry/cost/provider-trace paths, or the installer — don't defer them to closeout.

## Release Process

Version lives in `pyproject.toml`. PyPI publishing is automated: push an annotated `v*` tag to trigger the
`.github/workflows/publish.yml` workflow (trusted publishing via OIDC). After tagging, create a GitHub release with
`gh release create`. No local PyPI credentials are needed.

## Commit & Pull Request Guidelines

Recent history follows conventional prefixes such as `feat:`, `fix:`, `docs:`, and `chore:` with short imperative
subjects; issue references are appended when relevant, for example
`fix: session resume fails for nested worktree forks (#12)`. Branch from `main` and open PRs back to `main`. Before
requesting review, run `make pre-commit` and the relevant test targets, summarize behavior changes, list verification
commands, and link the issue. Include terminal output or screenshots when CLI-visible behavior changes.

## Platform & Environment

**macOS (Darwin)** - Use GNU tools instead of BSD versions: gsed, gawk, ggrep (can also use rg), gdate, greadlink
