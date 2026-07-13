# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-Forge consolidates multiple AI developer tools (proxy, session manager, status line, TDD guard) into a unified
monorepo. The architecture is a "glue approach" — connective tissue between specialized tools, not a monolith.

## Development Commands

```bash
# Install dependencies
uv sync

# One-time contributor launcher. When FORGE_DEV is unset, eligible host hooks
# use an executable recorded or known-location launcher and fail with exit 127
# when neither exists. FORGE_DEV explicitly selects the checkout venv.
./scripts/setup.sh --local

# Run tests (ALWAYS use make - handles prerequisites)
make test-unit              # Fast unit tests (no Docker)
make test-integration       # Docker-based integration tests (auto-starts local LiteLLM)
make test                   # Full suite

# Why use make? It ensures prerequisites:
# - Builds Docker images if missing
# - Starts local LiteLLM on test port (4001) if needed
# - Uses litellm-gemini-test template for test isolation (port 4001)
#
# Advanced: Direct pytest (only AFTER running make once to set up prerequisites)
# uv run pytest tests/src -m "not integration" -v
# uv run pytest tests/integration -v

# Exercise this checkout's unreleased hooks in a new managed session.
# FORGE_DEV must be an absolute checkout root; relaunch after changing/unsetting it.
FORGE_DEV="$PWD" uv run forge session start dev-hooks

# Code quality (run `make pre-commit` before every commit; includes type checks)
make pre-commit            # All hooks: ruff, black, isort, mypy, pyright, mdformat, gitleaks
make clean                 # Remove caches

# Direct tool usage (read-only checks; let pre-commit own formatting)
uv run ruff check src/
uv run mypy src/
uv run pre-commit run --all-files
```

**Run integration tests when needed.** Docker is expected to be running locally — `make test-integration` is routine,
not special-occasion. For changes touching hooks, session start/resume/fork, the memory writer, proxy runtime, or the
installer, run the relevant integration tests before finishing; unit tests never exercise the `claude -p` / Docker paths
these flows use. Stay cost-conscious by targeting files
(`./scripts/test-integration.sh tests/integration/.../test_*.py`) instead of the full suite. See
[testing_guidelines.md](docs/developer/testing_guidelines.md#when-to-run-integration-tests).

## Git Branching

- **`main`**: Primary branch. All PRs target `main`.
- **Feature branches**: Branch from `main`, PR back into `main`.

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

## GitHub CLI Auth

`gh` authenticates with `GH_TOKEN`, sourced by direnv from `~/.keys/github_token`. Long-lived shells can keep a stale
token after that file changes, so `gh` reports `Bad credentials` even though SSH `git push` still works (SSH auth is
separate). Re-evaluate `.envrc` per command rather than trusting the already-loaded environment:

```bash
direnv exec . gh auth status
direnv exec . gh pr create --base main ...
direnv exec . gh release create vX.Y.Z --notes-file <notes.md> --latest
```

`gh` gives `GH_TOKEN` precedence over stored credentials, so unsetting it makes `gh` look logged out even when
`git push` works — re-source `.envrc`, don't clear the token. Never print token values; probe with status-only calls
through `direnv exec .`.

With multiple remotes (this clone has `origin` plus a parent upstream), `gh pr create` can misresolve the branch or
target the wrong repo. Pin coordinates explicitly: `gh pr create --repo <owner>/<repo> --base main --head <branch>`.

## Release Process

Version lives in `pyproject.toml`. PyPI publishing is automated: pushing an annotated `v*` tag triggers
`.github/workflows/publish.yml` (trusted publishing via OIDC — no local PyPI credentials needed).

Release checklist:

1. Verify current version and latest tag: `rg -n '^version =' pyproject.toml && git tag --sort=-v:refname | head`.
2. Bump `pyproject.toml`, then `uv lock` so `uv.lock` records the new version.
3. Build locally before tagging: `uv build`.
4. Run `make pre-commit` (release-appropriate checks).
5. Commit on `main`, tag, and push both: `git commit -m "chore: release X.Y.Z"`, `git tag -a vX.Y.Z -m "Release X.Y.Z"`,
   `git push origin main vX.Y.Z`.
6. Confirm the `Publish to PyPI` workflow succeeds and PyPI lists the new wheel + sdist:
   `https://pypi.org/pypi/multi-forge/X.Y.Z/json` and `https://pypi.org/simple/multi-forge/`.
7. Create the GitHub release after the tag exists (see GitHub CLI Auth above for the `direnv exec .` prefix):
   `direnv exec . gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <notes.md> --latest`.

## Work Board Quick Semantics

The authoritative board workflow is in `docs/developer/board_contract.md`. In short: `todo/` means accepted but parked.
When asked to work on a `todo/` card, create or switch to its execution branch, move the card directory to
`docs/board/doing/<slug>/`, and create/update `checklist.md`. `doing/` is active work; `paused/` is partially completed
work on hold; `done/` means shipped, verified, design docs synced, and closeout recorded. `retired/` is terminal work
that did not ship independently; it is excluded from live and done counts, and reconsideration starts a new `proposed/`
card.

## Git Hooks

Pre-commit hooks reformat code (black, isort) and **strip emoji from staged files** (personal `normalize-text` hook).
Use `\U` escape sequences (e.g., `"\U0001F504"`) for emoji that must survive commits. After edits, run `git add -u` to
re-stage auto-formatted files. If a commit fails due to formatting, re-stage and retry without asking.

## Architecture

### File-Based State System (Core Design)

Forge uses a three-tier file-based state system instead of a database:

1. **Session manifest** (per-session): `.forge/sessions/<name>/forge.session.json` - contains intent (what session
   should be) and confirmed state (what Claude Code actually did). Multiple sessions can coexist per worktree.
2. **Proxy registry** (global): `~/.forge/proxies/index.json` - running proxies (template, base_url, pid).
3. **Runtime truth**: Live proxy introspection via `ANTHROPIC_BASE_URL`.

### Directory Structure

```
src/forge/
├── cli/        # Click-based CLI commands (forge session, forge proxy, etc.)
│   └── hooks/  # Hook handlers invoked by Claude Code
├── config/     # Configuration loading and proxy templates
├── core/       # Shared libraries (auth, models, state, llm, workqueue, reactive)
├── policy/      # Policy enforcement (TDD, coding standards, semantic supervisor)
├── install/    # Extension installer and tracking
├── proxy/      # Model routing proxy
├── review/     # Multi-model review engine (fan-out, adversarial)
├── search/     # Transcript search (BM25 index)
├── session/    # Session manager (worktrees, artifacts, resume)
└── sidecar/    # Docker sidecar mode (proxy + Claude in container)
```

### Shared Libraries (`src/forge/core/`)

- `forge.core.auth` - Credential resolution (env > `~/.forge/credentials.yaml`), template-to-secrets mapping
- `forge.core.llm` - Async-first LLM client abstraction (see design_appendix.md §E)
- `forge.core.models` - Model catalog with templates/tiers
- `forge.core.state` - State read/write operations
- `forge.core.workqueue` - File-based async work queue
- `forge.core.reactive` - Shared reactive library (session runner, throttle cache, tagger)

### Key Concepts

- **Templates**: Operational profiles that map to proxy ports (e.g., `litellm-gemini` on port 8084)
- **Tiers**: User-facing abstraction (`haiku`/`sonnet`/`opus`) that maps to backend models
- **Intent vs Confirmed**: Session manifest separates what Forge requested from what Claude Code actually did

## Implementation Status

Test suite has ~3,900 tests with Docker-based isolation. Key capabilities: multi-model proxy routing, session management
with resume/transfer, policy engine (TDD + semantic supervisor), search, workflow runners (fan-out, adversarial), skills
architecture, and interactive manual testing (`/forge:smoke-test`, `/forge:walkthrough`, `/forge:qa`).

**Install profiles**: `standard` (default) includes most skills. `full` adds `/forge:qa` (Docker-based QA).

See [design.md](docs/design.md) for architecture details.

## Design & Implementation

When the user describes a new concept (e.g., 'backend', 'work queue'), treat it as a FIRST-CLASS architectural concept
unless told otherwise. Do not reduce user-defined abstractions to internal implementation details. Ask for clarification
if scope is unclear rather than assuming minimal scope.

## Code Reviews

When performing code reviews, do a COMPLETE first pass covering ALL findings before presenting results. Do not present a
partial subset — the user expects comprehensive coverage in a single pass.

## Guidelines (load into context)

@docs/developer/coding_standards.md @docs/developer/testing_guidelines.md @docs/developer/documentation_guidelines.md
@docs/developer/board_contract.md

## Key Documents

- `docs/design.md` - Unified design and migration plan (canonical)
- `docs/design_appendix.md` - Reference details (schemas, config tables)
- `docs/design_workflows.md` - Policy, skills, workflow runners, and memory architecture
- `docs/cli_reference.md` - Terminal and direct-command inventory
- `docs/developer/board_contract.md` - Work-board lane, checklist, and closeout contract
- `docs/board/README.md` - Board directory guide and dogfood examples
- `docs/end-user/` - End-user guides (sessions, proxies, hooks, configs)

## UX Guidelines

### Error Handling

Keep user-facing error messages simple and accurate. Don't suggest installation methods or workarounds that don't apply
here. When fixing errors, match the existing error-message style.

### Console Output Formatting

CLI command shape and recovery-output style live in
[docs/developer/cli_style_guidelines.md](docs/developer/cli_style_guidelines.md). Always-on essentials:

- **Use the `forge.cli.output` helpers** (`print_tip`, `print_error`, `print_error_with_tip`, `handle_session_error`)
  for all recovery output. Never hand-roll a `Tip:` line or `[red]Error:[/red]` markup in `src/forge/cli/**` —
  `test_cli_rich_tips_go_through_output_helpers` scans for the literal `Tip:` and
  `test_cli_rich_errors_go_through_print_error` for `[red]Error:[/red]`, both enforcing the prefixes live only in
  `output.py` (the assistant-facing `hooks/direct_commands.py` payloads are the sole `Tip:` exception).
- Always pass the call site's local `console`; only `output.py`'s own fallback is width-less.
- Commands use `Run '<full command>'`; flags use `Use --flag`. Inline commands in single quotes, never backticks.
  Multi-line/placeholder commands go in the `commands=[...]` block. Never use `Hint:`.

See the guide for the helper table (including which helpers exit), the `--json`/`as_json` idiom, and the non-recovery
output categories (informational, status, dry-run, next steps).
