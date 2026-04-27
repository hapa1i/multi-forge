# Repository Guidelines

## Project Structure & Module Organization

`src/forge/` contains the Python app, split by domain (`cli/`, `session/`, `proxy/`, `guard/`, `core/`, `install/`,
`search/`, `review/`, `sidecar/`, `backend/`, `logs/`). Agent assets live in `src/skills/`, `src/commands/`, and
`src/agents/`. Tests are split by scope: `tests/src/` mirrors `src/forge/`, `tests/integration/` covers end-to-end and
Docker-backed flows, `tests/regression/` holds bug reproductions, and `tests/fixtures/` provides shared helpers. Keep
docs in `docs/`, runtime images in `docker/`, and automation scripts in `scripts/`.

## Documentation Guide

Use the repo docs as the source of truth for their domains: `README.md` for the overview, `docs/developer/` for setup,
and `CLAUDE.md` for agent context. `docs/developer/coding-standards.md`, `testing-guidelines.md`, and
`documentation-guidelines.md` define code style, test policy, and doc maintenance rules. Update `docs/design.md` when
architecture or file ownership changes.

## Build, Test, and Development Commands

Use `uv` for dependencies and `make` for the standard workflow:

- `uv sync` installs runtime and dev dependencies.
- `uv run forge --help` checks the CLI entry point.
- `make test-unit` runs tests.
- `make test-integration` builds Docker images, starts test infrastructure, and runs integration-marked tests.
- `make test-regression` runs regression tests.
- `make lint`, `make format`, `make type-check`, and `make pre-commit` run Ruff, formatting, mypy, and the full hook
  suite.

## Coding Style & Naming Conventions

Target Python 3.11 with 4-space indentation and a 120-character line length. Use `snake_case` for modules, functions,
and variables, `CamelCase` for classes, and `UPPER_CASE` for constants. Follow the repo’s Python conventions: public
methods before private ones, type hints on public functions, and comments that explain why. Quality checks center on
Ruff and mypy; pre-commit also runs isort, Black, and gitleaks.

## Testing Guidelines

Use `pytest`, not `unittest`. Mirror source paths in `tests/src/` (for example, `src/forge/session/store.py` maps to
`tests/src/session/test_store.py`). Mark integration files with `pytest.mark.integration`. Name regression files
`test_bug_<id>_<description>.py` and mark them `regression`. Every bug fix should include a regression test, and broken
tests should be fixed or removed rather than skipped.

## Commit & Pull Request Guidelines

Recent history follows conventional prefixes such as `feat:`, `fix:`, `docs:`, and `chore:` with short imperative
subjects; issue references are appended when relevant, for example
`fix: session resume fails for nested worktree forks (#12)`. Branch from `main` and open PRs back to `main`. Before
requesting review, run `make pre-commit` and the relevant test targets, summarize behavior changes, list verification
commands, and link the issue. Include terminal output or screenshots when CLI-visible behavior changes.
