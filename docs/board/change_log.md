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
