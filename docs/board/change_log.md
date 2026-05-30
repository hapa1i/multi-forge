# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board-contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
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
> `**Verification**:`. Use newest-first order. See `docs/developer/board-contract.md` "Change Log Policy" for the full
> spec.

## 2026-05-29

### fix: tombstone `forge handoff run` (memory_substrate follow-up)

**Goal**: Make the removed runner path fail with an actionable message, matching the report path.

**Key changes**: The memory_substrate closeout tombstoned `forge session handoff show` but left `forge handoff run` as a
generic Click "No such command 'handoff'" dead-end. Added a hidden top-level `handoff` tombstone group
(`cli/memory_writer.py`, registered in `main.py`) whose `run` command errors with "Use: forge memory-writer run",
mirroring `session_handoff.py`.

**Verification**: `forge handoff run` (bare and with old flags) exits non-zero naming `forge memory-writer run`, not
Click's "No such option"; regression `TestOldHandoffRunTombstone` in `test_memory_writer_cli.py` (2 tests).

### memory_substrate: resolve "handoff" naming → memory writer + transfer

**Goal**: Split the overloaded "handoff" term into two clear concepts — the **memory writer** (Stop-time project-doc
curation) and **transfer** (resume/fork context assembly) — across code, CLI, config, durable state, docs, and skills.

**Key changes**:

- **Session layer**: `git mv handoff_agent.py → memory_writer.py`, `handoff.py → transfer.py`; renamed
  `HandoffConfig→MemoryWriterConfig`, `HandoffResult→TransferResult`, `process_handoff→assemble_transfer_context`,
  `run_handoff_agent→run_memory_writer`, `review_dir→memory_report_dir`.
- **CLI**: `forge session handoff show → forge memory report show` (new `cli/memory_report.py`);
  `forge handoff run → forge memory-writer run`; old paths are actionable tombstones.
- **Durable state**: `--resume-mode handoff → transfer` with `confirmed.derivation.resume_mode` accept-and-tolerate
  (legacy `"handoff"`/`None` read as transfer); config key `handoff_timeout → memory_writer_timeout` (stale-key
  warn-and-ignore).
- **Docs/skills**: `docs/end-user/handoff.md → memory.md`; QA `16-handoff.md → 16-memory.md`; 3-layer memory taxonomy
  table added to design.md §5.6; design/appendix/diagrams/skills synced.
- **Internal naming sweep (closeout)**: drove residual `handoff` in `src/forge/` from 207 (Phase 0) to 39, all
  intentional KEEPs. Renamed `handoff_result→transfer_result` (manager.py, session_lifecycle.py); the GC
  transfer-context subsystem (`_detect_orphan_handoff_files`, `_build_handoff_context_reference_set`,
  `_clean_handoff_files` → `…transfer…`, incl. the **user-visible** `forge clean` category key
  `handoff_files→transfer_files`); the cost-tracking verb `handoff→memory-writer`; user-facing resume messages/help; and
  ~12 `core/reactive`/proxy docstrings ("handoff agent"→"memory writer"). Coupled tests updated (`test_gc.py` ×2,
  `test_session_resume_review.py`).

**Intentional KEEPs** (durable state / routing / fixtures): work-queue marker `kind="handoff"`,
`enqueue_handoff_marker()`, `marker_id="handoff-<id>"`, the `.forge/artifacts/<session>/handoff/` artifact path, the
`queued_handoff` Stop-hook field, the `forge session handoff` tombstone, the legacy-value migration messages, and the
generic-English passport "project-state" wording.

**Verification**: full unit+regression green (4902 passed); the 2 failures
(`test_session_resume_review::test_editor_nonzero_aborts_launch`,
`test_removal_patching_system::test_forge_info_no_traceback`) reproduce identically on `origin/main` (f8c07d9) —
pre-existing, unrelated. `test_handoff_integration.py` (10) green — renamed runtime + `forge memory report show`
end-to-end. `make pre-commit` clean. Shipped as PR #8; unrelated gemini-3.5-flash catalog work split to PR #9.

## 2026-05-28

### Rename Claude Opus 4.7 → 4.8 (retain 4.6)

**Goal**: Make Opus 4.8 (released 2026-05-28) replace every Opus 4.7 reference, while leaving Opus 4.6 — a distinct,
still-default model — untouched.

**Key changes**:

- Catalog + pricing: `claude-opus-4-7` → `claude-opus-4-8` (entry, 5 aliases, `friendly_name`); researched 4.8 specs
  kept ($5/$25/$0.50, 1M context, 128K output, adaptive-only, fixed temperature, `xhigh`); `intelligence_score` 99→100;
  `pricing.yaml` `updated_at` bumped. The `opus`/`claude-opus` defaults and proxy tier mappings stay on 4.6 — 4.8 is
  opt-in (`--model claude-opus-4-8`), inheriting 4.7's role.
- Review workflow: `claude-opus-4.8` ModelSpec + `_CLAUDE_48_BOUNDED_REVIEW_PROMPT`; three Anthropic proxy templates'
  `model_alternatives.opus` repointed.
- Review guide `references/claude-4.7.md` → `claude-4.8.md`, rewritten against the live 4.8 docs (release date, from-4.7
  migration framing, dropped "new xhigh"; added mid-conversation system messages, fast mode, 1,024-token cache minimum,
  refusal `stop_details`; kept inherited constraints and 4.6 comparisons).
- Did NOT add a `max` effort tier (pre-existing cross-model Anthropic effort Forge omits; would fail `_EFFORT_RANK`
  validation). Left `glm-4.7-flash`, Sonnet/Haiku versions, and `### 4.7` QA section headings untouched.
- Tests moved in lockstep (catalog/pricing/review/proxy/session/config/supervisor); cosmetic test renames; negative
  tests now `claude-opus-4.8.1`; new `claude-opus-4-8` pricing test.

**Verification**: full unit suite green (4649 passed; the lone failure is a pre-existing COLUMNS-width-dependent test in
`test_session_resume_review.py`, reproduced identically on `origin/main`); integration tests pass; `make pre-commit`
clean; built-wheel clean-install smoke confirms catalog/pricing/guide load via `importlib.resources` and `opus` still
resolves to `claude-opus-4-6`.

### Simplify memory strategies: 7 to 4, shadow mode orthogonal

**Goal**: Reduce strategy enum from 7 to 4 by removing redundant entries, make shadow mode orthogonal to strategy, and
rename `--as` to `--strategy`.

**Key changes**:

- Removed `debugging`, `patterns` strategies (topic scoping via passport `intent`/`captures` fields instead).
- Removed `suggested` strategy (shadow mode is now orthogonal -- `--propose` works with any strategy).
- Renamed `--as` to `--strategy`; `--as` is a hidden tombstone with rename guidance.
- Shadow path prefix changed from `suggested_*` to `shadow_*` in `derive_shadow_path()`.
- Shadow framing in `build_multi_doc_prompt()` now includes proposal-format instructions (checkboxes, rationale,
  self-prune) that were previously in the `suggested` strategy instruction.
- Stale passports with removed strategies rejected with actionable hints (`_REMOVED_STRATEGIES`).
- `_validate_designated_docs()` empty-shadows guard applies unconditionally; `suggested` coupling removed.
- `--propose` preserves existing passport strategy unless `--strategy` is explicitly passed.

**Verification**: full unit suite passes; `make pre-commit` clean.

## 2026-05-26

### Phase 1 / Slices 4-7: Simplify memory to passports + session activation

**Goal**: Reduce the memory system from three layers (passports, checkout activation, session participation) to two
primitives: passports select docs, session activation decides whether the memory writer runs. Research-preview clean
break.

**Key changes**:

- Removed `.forge/memory.yaml` (checkout-scoped activation), `forge memory extra add`, `forge memory untrack`,
  `DesignatedDoc.origin`, `MemoryIntent.designated_docs` (field removed from manifest schema), session-scoped doc lists,
  `--inherit-extras`/`--no-inherit-extras`, `--inherit-memory` tombstones, `--no-copy-memory-activation`,
  `ProjectMemoryConfig`, `memory_activation()` three-tier resolver, `copy_memory_activation()`.
- Added `forge memory disable`, `--memory on|off` on `fork`/`resume --fresh`/`start`.
- `forge memory enable`/`disable` are session-scoped only (resolve `$FORGE_SESSION` or `--session`).
- `forge memory list` is a sessionless passport scan (no writer filtering, no session needed).
- Stop hook and handoff runner check `effective.memory.auto_update.enabled` directly (incognito guard preserved).
- Handoff runner uses `scan_passported_docs()` as sole doc source (no doc fusion).
- `apply_memory_inheritance()` constructs a fresh `MemoryIntent(auto_update=...)` from parent; `--memory on` reuses
  parent config, `--memory off` writes explicit `HandoffConfig(enabled=False)`, `None` inherits.
- `strip_preview_memory_doc_lists()` sanitizer warns-and-strips stale `designated_docs` from old manifests per
  coding-standards section 5.
- Stale `.forge/memory.yaml` is now ignored; safe to delete.

**Verification**: 4645 unit tests pass; `make pre-commit` clean.

### Phase 1 / Slice 3: Fork activation copy + retire `--inherit-memory`

**Goal**: Make memory activation follow Forge-created worktrees by default and replace the multi-mode `--inherit-memory`
flag with a narrower extras-only inheritance model.

**Key changes**:

- `fork --worktree` copies `.forge/memory.yaml` from parent to child checkout by default (never overwrites existing;
  `--no-copy-memory-activation` opt-out; corrupt source warns and skips). `--into` forks skip the copy.
- Replaced `--inherit-memory all|none|shadowed` with `--inherit-extras` / `--no-inherit-extras` on both `fork` and
  `resume --fresh`. Default inherits `origin="extra"` entries only; project-discovered docs are not affected.
- Simplified `memory_inheritance.py`: removed `InheritMemoryMode` enum and multi-mode branching; extras-only filter.
- `--inherit-memory` is now a hidden tombstone with per-value replacement guidance.
- Docs: updated `design.md §5.6.4`, `docs/end-user/handoff.md` fork/resume memory sections.

**Verification**: `test_memory_inheritance.py` (25 tests) + `test_project_memory.py::TestCopyMemoryActivation` (5 tests)
pass; full `tests/src -m "not integration"` green (4718 passed).

### CLI command-shape cleanup: groups orient, leaves act

**Goal**: Make confusing bare CLI invocations follow one documented rule before PR: non-leaf command groups print help,
while leaf commands perform a sensible default action.

**Key changes**:

- Documented the command-shape invariant in `docs/developer/coding-standards.md` and `docs/design.md`: groups orient,
  leaves act, removed group-level shortcuts may remain only as non-executing tombstones.
- `forge config` now prints help; `forge config show` is the explicit command that displays and auto-creates
  `~/.forge/config.yaml`. Updated `docs/end-user/config.md` and design appendix references.
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

### Phase 1 / Slice 2: Sessionless `track` + participation-only `extra add`

**Goal**: Split the welded lifetimes in `forge memory track` so each verb owns one lifetime — `track` authors a
project-lifetime passport (sessionless), `extra add` records session-only participation (no passport), and `enable` owns
activation.

**Key changes**:

- `forge memory track` is now passport-only and sessionless: resolves `forge_root` from cwd, never writes
  `memory.designated_docs`, never auto-enables, ignores `$FORGE_SESSION`. It is a no-op (exit 0) on an
  already-passported doc with no flags, warns when the doc is outside the scan roots, and degrades (warn, still authors)
  on a corrupt `.forge/memory.yaml`. `--session`/`-s` is a hidden tombstone that errors and names `extra add`.
- New `forge memory extra add <path> --as <strategy>`: session-scoped participation with `origin="extra"`, echoes the
  resolved session, rejects `--as suggested` only when the target has no passport, and warns on writer-veto (case B) or
  redundant-under-root (case A).
- `DesignatedDoc.origin: Literal["extra"] | None` added, persisted, and inherited; `_check_legacy_docs` skips extras and
  names both new verbs; `list`/`status` expose `origin`; `untrack` warns when a passport remains under the roots.
- Shadow workflow no longer depends on the manifest: new `scan_shadow_passports()` and
  `check_shadow_path_collision_in_roots()` in `project_memory.py`; `collect_shadow_entries()` unions project-origin
  shadows (scope-correct roots) with session entries, de-duped by `(forge_root, shadow_path)`. Removed the now-dead
  manifest-based `check_shadow_path_collision`.
- Docs: `design.md` §4.0 table + new §5.6.7 verb taxonomy; `design_appendix.md §G.2`; board README; end-user
  `handoff.md`; QA and walkthrough skill checklists.

**Verification**: `tests/src/cli/test_memory.py` and
`tests/src/session/{test_handoff_agent,test_memory_inheritance,test_project_memory,test_shadow_curation}.py` pass; full
`tests/src -m "not integration"` green (4689 passed); `mypy` clean on touched modules.

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
  ambiguous, start-failure). Covers `--supervisor-proxy` on `session fork`, `session start`, and `policy supervise`.
- Wired the launch routers `_resolve_routing_from_cli` (session start/resume/fork `--proxy`) and `forge claude --proxy`
  onto `ensure_proxy`; all five `--proxy`/`--supervisor-proxy` paths print a dim "Started proxy X from template Y"
  notice when they spin one up.
- `forge policy supervise` now validates the target session *before* ensuring the proxy, so a bad target can't orphan a
  freshly started proxy.
- A registered-but-stopped (or stale-dead) proxy for a known template now auto-starts (was: "none are active" error).
  Workflow `--proxy via` is intentionally excluded (different routing layer + one-shot lifecycle).
- **Behavior break** (research preview): naming a template with no live proxy used to error; it now starts one. Unknown
  names (no proxy, no template) still fail, now with a `forge proxy template list` hint. Updated `docs/design.md`
  §3.6.3, `docs/end-user/proxy.md`, and `docs/end-user/session.md`.

**Verification**: regression `test_bug_supervisor_proxy_autostart.py` + `test_bug_stale_healthy_proxy_not_restarted.py`;
`TestEnsureProxy` (8 cases) in `test_proxy_orchestrator.py`; updated supervisor/claude/session CLI tests; 348 related
proxy/policy/session/regression tests pass; `ruff check` on touched Python files and `git diff --check` clean.

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
  without `--force`. Updated `docs/end-user/session.md`.

**Verification**: `tests/regression/test_bug_delete_live_session.py` (preflight + race branch) and the expanded
`tests/src/cli/test_session_commands.py` delete matrix (single/`--all` x force/no-force x tracked/orphan);
`make pre-commit` clean.

## 2026-05-24

### Phase 1 / Slice 1: Project-Scoped Memory Activation

**Goal**: Activate the handoff agent once per checkout via `.forge/memory.yaml` instead of per-session
`forge memory enable`, through a single resolver consulted at both activation gates.

**Key changes**:

- New `src/forge/session/project_memory.py`: versioned `ProjectMemoryConfig` (strict `dacite` reader modeled on
  `SessionStore`, raises `ProjectMemoryConfigError`); the `memory_activation()` three-tier resolver (project baseline /
  whole-block legacy intent overlay only when `enabled is True` / sparse per-leaf overrides, the only tier that can
  disable); and `scan_passported_docs()` (root-contained via `_reject_unsafe_path`, which rejects absolute, escaping,
  and `..`-traversal roots and shadow paths; deterministic; shadow-materializing; capped at 50 after filtering).
- Both gates call the resolver: the Stop-hook enqueue site (`cli/hooks/commands.py`) and the detached runner
  (`cli/handoff.py`). The runner unions scanned passports with session `designated_docs` (session wins, de-duped by
  passport source + write path) while preserving the existing proxy-routing chain.
- `forge memory enable` is now dual-path: bare writes project `.forge/memory.yaml`; `--session X` keeps the sparse
  manifest override.
- Design docs: added `design.md §5.6.6` and `design_appendix.md §G.5`.

**Behavior change**: bare `forge memory enable` no longer targets the ambient `$FORGE_SESSION`; it enables the whole
checkout (prints a `Tip:` when `$FORGE_SESSION` is set). Use `--session <name>` for the per-session override. Additive,
no schema break; incognito sessions never activate.

**Verification**: `tests/src/session/test_project_memory.py` (38: config I/O + resolver + scanner, incl. unsafe-root and
unsafe-shadow-path rejection), `test_handoff.py` (+5 run_cmd; 2 legacy proxy tests still green),
`test_artifact_hooks.py::TestStopHook` (+3), `test_memory.py` (`TestMemoryEnableProject` +6; `TestMemoryEnable` pinned
to `--session`). Full `tests/src/session` + `tests/src/cli` unit suites: 2193 passed. mypy clean on touched files;
`make pre-commit` clean.

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
