# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-Forge consolidates multiple AI developer tools (proxy, session manager, status line, TDD guard) into a unified
monorepo. The architecture is a "glue approach" — connective tissue between specialized tools, not a monolith.

## Development Commands

```bash
# Install dependencies
uv sync

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
[testing-guidelines.md](docs/developer/testing-guidelines.md#when-to-run-integration-tests).

## Git Branching

- **`main`**: Primary branch. All PRs target `main`.
- **Feature branches**: Branch from `main`, PR back into `main`.

## Release Process

Version is in `pyproject.toml`. Publishing is tag-triggered via GitHub Actions (trusted publishing, no local credentials
needed):

```bash
# 1. Bump version in pyproject.toml on main
# 2. Create an annotated tag and push
git tag -a v0.X.Y -m "Release v0.X.Y"
git push origin v0.X.Y
# 3. Create a GitHub release
gh release create v0.X.Y --title "v0.X.Y" --notes "..."
```

The `Publish to PyPI` workflow (`.github/workflows/publish.yml`) builds and publishes on any `v*` tag push.

## Work Board Quick Semantics

The authoritative board workflow is in `docs/developer/board-contract.md`. In short: `todo/` means accepted but parked.
When asked to work on a `todo/` card, create or switch to its execution branch, move the card directory to
`docs/board/doing/<slug>/`, and create/update `checklist.md`. `doing/` is active work; `done/` means shipped, verified,
design docs synced, and closeout recorded.

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

## Critical Thinking on User Input

When the user (or another AI model) provides feedback, corrections, claims, or design notes, do not blindly accept them.
Instead:

1. **Verify claims against the codebase** — check that referenced behavior, files, or patterns actually exist as
   described
2. **Reason through the implications** — consider whether the suggested change is consistent with existing architecture
3. **Push back when warranted** — if evidence contradicts the user's claim, say so clearly with specifics
4. **Ask clarifying questions** — if a claim is ambiguous or untestable, ask before assuming it's correct

**Especially in planning mode**: When the user provides feedback on a plan, independently verify their corrections
before incorporating them. A wrong assumption accepted during planning cascades into a flawed implementation. Treat plan
reviews as a dialogue, not a dictation.

The user values being challenged over being agreed with. Sycophantic acceptance leads to wasted work and subtle bugs.

## Code Reviews

When performing code reviews, do a COMPLETE first pass covering ALL findings before presenting results. Do not present a
partial subset — the user expects comprehensive coverage in a single pass.

## Editing Discipline

When editing documents or code, preserve the user's preferred terminology. Do not replace domain-specific terms (e.g.,
fact_id, orchestration) unless explicitly asked. When in doubt, ask before renaming.

## Guidelines (load into context)

@docs/developer/coding-standards.md @docs/developer/testing-guidelines.md @docs/developer/documentation-guidelines.md
@docs/developer/board-contract.md

## Platform & Environment

**macOS (Darwin)** — use GNU tools, not BSD: `gsed` (not `sed`; different `-i` syntax), `gawk`, `ggrep` (or `rg`; perl
regex), `gdate` (`--date` parsing), `greadlink -f` (BSD lacks `-f`).

## Key Documents

- `docs/design.md` - Unified design and migration plan (canonical)
- `docs/design_appendix.md` - Reference details (schemas, config tables)
- `docs/design_workflows.md` - Policy, skills, workflow runners, and memory architecture
- `docs/cli_reference.md` - Terminal and direct-command inventory
- `docs/developer/board-contract.md` - Work-board lane, checklist, and closeout contract
- `docs/board/README.md` - Board directory guide and dogfood examples
- `docs/end-user/` - End-user guides (sessions, proxies, hooks, configs)

## UX Guidelines

### Error Handling

Keep user-facing error messages simple and accurate. Don't suggest installation methods or workarounds that don't apply
here. When fixing errors, match the existing error-message style.

### Console Output Formatting

**Use the `forge.cli.output` helpers for CLI Rich recovery output** so equivalent situations tip identically. All Rich
`Tip:` output in `src/forge/cli/**` must go through them; tests enforce that `[dim]Tip:` appears only in `output.py`.
Reach for:

```python
from forge.cli.output import print_tip, print_error, print_error_with_tip, handle_session_error

# Error + recovery tip (the common "already exists" / "not found" shape)
print_error_with_tip(
    f"Proxy '{proxy_id}' not found at {display_path(proxy_path)}",
    f"Run 'forge proxy create <template> --name {proxy_id}' to create it.",
    console=console,  # pass your file's local console so width=200 tables stay aligned
)

# Typed ForgeSessionError → prints the error, looks up a context-free tip, sys.exits(1)
except ForgeSessionError as e:
    handle_session_error(e, console=console)

# Multi-line / placeholder commands render as a copy-paste block
print_error_with_tip(
    f"Backend config already exists: {display_path(config_path)}",
    "Start an instance with:",
    commands=[f"forge backend start {adapter} --port 4000"],
    console=console,
)
```

Always pass the call site's local `console`; only `output.py`'s own fallback is width-less.

**Wording conventions** (the helpers preserve the literal `Tip:` / `Error:` prefixes):

- **Commands → `Run '<full command>'`**; **flags/options → `Use --flag`** (e.g. `Run 'forge proxy start'`, but
  `Use --force to override.`).
- Inline commands in **single quotes**; never backticks (`` `git branch -d X` `` → `'git branch -d X'`).
- Multi-line or placeholder commands go in the `commands=` copy-paste block, not inline prose.

**Do NOT use:**

- `Hint:` — inconsistent, slightly condescending tone
- Unprefixed suggestions — harder for users to scan/recognize
- Hand-rolled `[dim]Tip: …[/dim]` in CLI modules — use `print_tip` / `print_error_with_tip`

**Other output categories** (no prefix needed):

- Informational: `[dim]Already up to date.[/dim]`
- Status: `[dim]Backup: {path}[/dim]`
- Dry-run: `[dim](dry-run)[/dim] Would patch...`
- Next steps: `\n[dim]Next steps:[/dim]` followed by bullet list
