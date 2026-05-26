# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the handoff agent with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/documentation-guidelines.md`: each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/board/change_log.md
./scripts/count-tokens.py --model <agent-model> docs/board/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/documentation-guidelines.md` "Change Log Policy" for
> the full spec.

## 2026-05-26

### CLI command-shape cleanup: groups orient, leaves act

**Goal**: Make confusing bare CLI invocations follow one documented rule before PR: non-leaf command groups print help,
while leaf commands perform a sensible default action.

**Key changes**:

- Documented the command-shape invariant in `docs/developer/coding-standards.md` and `docs/design.md`: groups orient,
  leaves act, removed group-level shortcuts may remain only as non-executing tombstones.
- `forge config` now prints help; `forge config show` is the explicit command that displays and auto-creates
  `~/.forge/config.yaml`. Updated `docs/end-user/configs.md` and design appendix references.
- Replaced the group-level `forge search -q/--query` action with `forge search query <terms>`. The old `-q` path now
  exits with a replacement tip instead of executing old behavior. Updated end-user docs, QA/walkthrough checklists, and
  tests/integration references.
- `forge proxy metrics` with multiple registered proxies now behaves like an acting leaf and shows all metrics
  (equivalent to `--all`) instead of erroring. `--json` follows the same implicit-all behavior.

**Verification**:
`uv run pytest tests/src/cli/test_config_cli.py tests/src/cli/test_proxy_commands.py tests/src/cli/test_search.py -q`
(146 passed); `make pre-commit`; smoke-checked `forge config`, `forge config -h`, `forge search -h`, and the
`forge search -q` tombstone.

## 2026-05-25

### CLI tip consistency: shared recovery-output helpers

**Goal**: Make equivalent CLI failures tip identically — the reported bug was `forge session start <existing>` showing a
recovery tip while `forge session fork ... --name <existing>` showed none.

**Key changes**:

- New leaf module `src/forge/cli/output.py`: `print_tip`, `print_error`, `print_error_with_tip`, and
  `handle_session_error` (a type→tip dispatch holding only context-free recoveries — currently just
  `SessionExistsError`). Imports only `rich` + `forge.session.exceptions`; never imported by `core/proxy/review`.
- Renamed `_handle_error` → `handle_session_error` across `session.py` and its four importers (`session_lifecycle.py`,
  `session_fork.py`, `session_manage.py`, `session_handoff.py`); `session.py` re-exports `console` +
  `handle_session_error` from `output.py`.
- §1 fix: `session fork` onto an existing name now routes through `handle_session_error`, emitting a
  different-name/delete tip (no "resume" — meaningless for a fork-name collision). `start` keeps its richer
  resume/delete wording as a call-site tip.
- Added recovery tips to `session resume` (not-found → start), proxy `edit/set/validate` (→ create) and `delete/metrics`
  (→ list), and backend `start/delete` (→ create).
- **BREAKING**: `forge backend create <existing>` now prints red `Error:` + tip and exits 1 (was yellow + exit 0),
  matching the session/proxy "already exists" shape. Reset path: run the suggested `forge backend start` instead.
- Migrated the remaining Rich `console.print` `Tip:` sites in `src/forge/cli/**` onto the helpers and added an invariant
  test that allows `[dim]Tip:` only in `output.py`.
- Documented the convention in `CLAUDE.md` (UX Guidelines → Console Output Formatting): use the helpers for CLI Rich
  recovery output, "Run '<command>'" vs "Use --flag", single quotes not backticks.

**Verification**: 291 targeted CLI + regression tests pass (incl. `test_output.py`,
`test_bug_fork_session_exists_tip.py`); `make pre-commit` clean on touched files (mypy + pyright pass repo-wide).

**Out of scope**: Plain-text recovery hints inside `core/proxy/review` exception messages and `click.echo`/hook-JSON
tips remain strings by design (layering).

### Auto-start proxies from templates for `--proxy` and `--supervisor-proxy`

**Goal**: Stop `--supervisor-proxy <template>` (and `--proxy <template>`) from hard-failing with "not found in registry"
when the named template exists but no proxy is running yet; bring the proxy up instead.

**Key changes**:

- Added `ensure_proxy()` (`src/forge/proxy/proxy_orchestrator.py`): resolves a proxy by id/template and starts one from
  a matching config template when no *live* proxy is available (reuse/adopt/spawn via `start_proxy`). Liveness-aware — a
  template entry recorded `healthy` but unreachable (e.g. after a reboot) is marked `unhealthy` before a replacement is
  registered, so follow-up template lookups do not become ambiguous. Re-raises `AmbiguousProxyError` (multiple active —
  pick one) and `ProxyNotFoundError` (no proxy and no template).
- Renamed `preflight_supervisor_proxy` -> `ensure_supervisor_proxy`; it auto-starts via `ensure_proxy`, returns
  `(proxy_id, started)`, and raises actionable `ValueError`s (no-template hint to `forge proxy template list`,
  ambiguous, start-failure). Covers `--supervisor-proxy` on `session fork`, `session start`, and `guard supervise`.
- Wired the launch routers `_resolve_routing_from_cli` (session start/resume/fork `--proxy`) and `forge claude --proxy`
  onto `ensure_proxy`; all five `--proxy`/`--supervisor-proxy` paths print a dim "Started proxy X from template Y"
  notice when they spin one up.
- `forge guard supervise` now validates the target session *before* ensuring the proxy, so a bad target can't orphan a
  freshly started proxy.
- A registered-but-stopped (or stale-dead) proxy for a known template now auto-starts (was: "none are active" error).
  Workflow `--proxy via` is intentionally excluded (different routing layer + one-shot lifecycle).
- **Behavior break** (research preview): naming a template with no live proxy used to error; it now starts one. Unknown
  names (no proxy, no template) still fail, now with a `forge proxy template list` hint. Updated `docs/design.md`
  §3.6.3, `docs/end-user/proxies.md`, and `docs/end-user/sessions.md`.

**Verification**: regression `test_bug_supervisor_proxy_autostart.py` + `test_bug_stale_healthy_proxy_not_restarted.py`;
`TestEnsureProxy` (8 cases) in `test_proxy_orchestrator.py`; updated supervisor/claude/session CLI tests; 348 related
proxy/guard/session/regression tests pass; `ruff check` on touched Python files and `git diff --check` clean.

### Protect live sessions from deletion

**Goal**: Stop `forge session delete` from silently discarding a session's Forge state while it is still running in
Claude Code, and stop a session deleted mid-run from crashing the launcher with a traceback.

**Key changes**:

- `forge session delete <name>` now refuses to delete a session with a live launch (exit 1) unless `--force`; `--yes` no
  longer overrides this guard. `forge session delete --all` skips live sessions and deletes the rest (`--force` includes
  them). Liveness uses the self-healing active registry, so a crashed/exited launcher still deletes without `--force`.
- The post-launch backfill (`_infer_launch_confirmation`) tolerates a manifest deleted mid-run: an `exists()` preflight
  skips the locked write (so the lock layer cannot resurrect the session as a lock-only directory), and a
  `SessionFileNotFoundError` guard covers the narrow delete race. The launcher prints a "was deleted during this run"
  note instead of a traceback.
- **Behavior break** (research preview): deleting an active session previously warned and proceeded; it now blocks
  without `--force`. Updated `docs/end-user/sessions.md`.

**Verification**: `tests/regression/test_bug_delete_live_session.py` (preflight + race branch) and the expanded
`tests/src/cli/test_session_commands.py` delete matrix (single/`--all` x force/no-force x tracked/orphan);
`make pre-commit` clean.

## 2026-05-24

### Memory Enhancement Completion, Design Doc Sync, and Proposal Lifecycle

**Goal**: Close out the memory enhancement proposal (PR #1), update design docs to reflect shipped passport model,
establish the proposal lifecycle pattern, and prepare for runtime-abstraction.

**Key changes**:

- Archived final memory enhancement card and checklist snapshots to `docs/board/done/memory_enhancement/`.
- Updated `docs/design.md` section 5.6: replaced old `DesignatedDoc` model with passport-authoritative ownership, added
  sections for passport frontmatter (5.6.2), shadow curation (5.6.3), and memory inheritance (5.6.4). Added
  `forge memory shadows review` to command table.
- Updated `docs/design_appendix.md` section G and `docs/end-user/handoff.md`: replaced old manifest-based examples with
  passport frontmatter and `forge memory` setup guidance.
- Pruned `impl_notes.md`: replaced Phase 0 pre-migration system map (100+ lines) with compact shipped-architecture
  summary preserving durable decisions.
- Established card lifecycle in `docs/developer/documentation-guidelines.md`: propose -> todo -> doing -> done (with
  per-phase design-doc updates). Design docs are normative (track shipped code), not aspirational.
- Updated `docs/board/README.md`: board lanes, curation workflow, design-doc verification step in lifecycle.
- Installed runtime-abstraction checklist under `docs/board/todo/runtime_abstraction/checklist.md` with per-phase
  design-doc update rule.

**Verification**: archived card+checklist at `docs/board/done/memory_enhancement/`; design.md sections 5.6.2-5 and
`docs/end-user/handoff.md` reflect passport model; active checklist tracks runtime-abstraction phases 0-6.

## 2026-05-23

### Phase 5: Curated Shadow Review (Memory Enhancement)

**Goal**: Add LLM-powered curation of shadow proposals so users can synthesize accumulated suggestions against the
official doc, with source-cited output and persistent reports.

**Key changes**:

- Created `src/forge/session/shadow_curation.py` with `ShadowEntry` dataclass, `collect_shadow_entries()` (moved from
  CLI layer), `build_curation_prompt()`, `_doc_slug()` with hash suffix for collision resistance,
  `persist_curation_report()` with `curation-` prefix, `report_glob_pattern()`, and `run_shadow_curation()`
  orchestrator.
- Added `forge memory shadows review` command with `--curate`, `--show-latest`, `--for`, `--scope`, `--json` flags.
  Mutual exclusivity, session ownership, and scope constraints enforced. Bare `review --for` shows raw content with
  hint.
- Refactored `_collect_shadow_entries()` in `memory.py` to delegate to session-layer `collect_shadow_entries()`, fixing
  a layering inversion (CLI code was owning discovery logic). `shadows list` and `shadows show` now use `ShadowEntry`
  attribute access instead of dict keys.
- Routing resolved in CLI via `resolve_handoff_base_url()`, passes `base_url` + `direct` into core function. Cost
  tracked via `track_verb_cost("curation", ...)`.

**Verification**: 4,595 unit tests pass (17 new `test_shadow_curation.py` + 11 new `TestShadowsReview` in
`test_memory.py`). All existing shadow tests pass after refactor. mypy and ruff clean.

### Phase 2: Top-Level CLI (Memory Enhancement)

**Goal**: Replace `forge session memory` with a new top-level `forge memory` command group, wire passport infrastructure
from Phase 1 into CLI commands, add legacy config detection, and complete Phase 1 deferred tasks 3-4.

**Key changes**:

- Created `src/forge/cli/memory.py` with 5 commands: `enable`, `track`, `untrack`, `list`, `status`. Registered as
  top-level `forge memory` in `main.py` with `mem` alias.
- `track` synthesizes passports for docs without one (`--as` required), rewrites passports when flags override existing
  values (passport-authoritative design), rejects shadow-only passports (Phase 3), and auto-enables memory on first
  tracked doc. Uses leaf-key overrides (`memory.auto_update.enabled`, `memory.auto_update.mode`) to preserve existing
  auto-update fields like `min_turns`.
- `status` aggregates across sessions using `list_sessions()` with scope filtering. JSON output includes `forge_root`
  and `session` for disambiguation. Inaccessible manifests skipped gracefully.
- Replaced `session_memory.py` with hidden tombstone group: old commands error with replacement guidance. Registration
  in `session.py:_register_subgroups()` unchanged.
- Legacy detection via `_check_legacy_docs()`: per-doc counting of missing vs malformed passports using
  `resolve_passport_source(doc)`. Warning says "manifest-fallback behavior" (accurate for Phase 1 fallback).
- Updated `design.md` command table: removed old `forge session memory` entries, added `forge memory` section.
- Completed Phase 1 tasks 3 (passport-required-at-rest: no passport + no `--as` fails) and 4 (flag-vs-passport
  conflicts: `--as` rewrites passport, warnings printed, round-trip verified).

**Verification**: 4,471 unit tests pass (38 new `test_memory.py` + 5 tombstone tests replacing 13 old tests). All
pre-commit hooks clean (ruff, black, mypy, mdformat).

## 2026-05-22

### Phase 1: Passport Model (Memory Enhancement)

**Goal**: Build passport model infrastructure (shared strategy enum, YAML frontmatter parsing/serialization, validation,
handoff agent integration) so Phase 2 can wire it into the `forge memory` CLI.

**Key changes**:

- Created `src/forge/session/passport.py` with `MemoryStrategy` enum, `Passport`/`PassportUpdate`/`ResolvedDocSpec`
  dataclasses, frontmatter parsing (`extract_frontmatter`, `parse_passport`, `read_passport`), atomic serialization
  (`write_passport`), synthesis (`synthesize_passport`), writer validation (`validate_writer_spec`,
  `check_writer_access`), and flag-vs-passport conflict handling (`resolve_with_overrides`).
- Added `PassportError(field_path, reason, hint)` to `forge.session.exceptions`, subclassing `ForgeSessionError`.
- Refactored `handoff_agent.py`: replaced inline `DOC_STRATEGIES` with import from `passport.STRATEGY_INSTRUCTIONS`.
  `build_multi_doc_prompt()` now takes `list[ResolvedDocSpec]` (no file I/O). `run_handoff_agent()` reads passports,
  filters by writer authorization, resolves effective doc specs, and includes full passport contract (intent, captures,
  excludes, approval, compact_when) in the prompt.
- Updated `session_memory.py` to import `VALID_STRATEGY_NAMES` from `passport.py`.
- Tasks 3 (passport-required-at-rest) and 4 (flag-vs-passport conflicts) have infrastructure built but CLI enforcement
  deferred to Phase 2.

**Verification**: 4,441 unit tests pass. Focused passport/handoff/session-memory suite passes 191 tests. `make lint` and
`make type-check` clean. Passport-less docs continue working identically.

### Phase 0: Branch and Baseline (Memory Enhancement)

**Goal**: Map the existing `forge session memory` surface, stop-time update path, handoff report surface, old UX
references, and helper reuse decisions before any code changes.

**Key changes**:

- Mapped CLI surface (session_memory.py, 3 commands, 13 tests), data model (DesignatedDoc, MemoryIntent, HandoffConfig),
  and the read-effective/write-override persistence split.
- Mapped the full stop-time chain: stop hook, work queue, fire-and-forget CLI startup handler, CLI runner, handoff agent
  core. Documented that detached failures are not retried by the queue.
- Mapped the handoff report/show surface (session_handoff.py) separately from the update agent.
- Inventoried 15 entries (8 UPDATE, 2 REMOVE, 5 KEEP) across docs, tests, and skills for old `forge session memory` and
  old-model `designated_docs[]` references.
- Decided 8 helpers + 2 patterns reuse privately behind new `forge memory` CLI; VALID_STRATEGIES moves to shared
  location in Phase 1; old commands become a non-executing tombstone diagnostic path.
- Recorded all maps and decisions in `docs/board/impl_notes.md`.

**Verification**: All six Phase 0 checklist tasks checked with verification notes.
