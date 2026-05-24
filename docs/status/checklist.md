# Memory Enhancement Checklist

Manual multi-session plan for executing `docs/proposals/memory_enhancement.md`.

`docs/status/checklist.md` tracks one active milestone/proposal at a time. After this proposal is fully executed, move
this file to `docs/status/archive/memory_enhancement.md` and start a fresh checklist for the next active proposal.

## Maintenance

- Update this file during implementation sessions and once before ending a session.
- Keep tasks high-level, with concrete assertions that prove completion.
- Tick a task only when the assertion is satisfied and verification is recorded.
- Add short blocker notes inline under the relevant phase.
- Move completed-session details to `docs/status/change_log.md`; keep only active plan state here.
- Promote durable lessons to `docs/status/impl_notes.md` after human review.
- Archive the whole checklist under `docs/status/archive/` after the proposal or milestone is fully executed.
- Check size periodically while a proposal is active:

```bash
wc -l docs/status/checklist.md
./scripts/count-tokens.py --model <agent-model> docs/status/checklist.md
```

## Current Focus

Replace the old session-scoped memory UX with a clean top-level `forge memory` surface, using memory-doc passports as
the authoritative contract and session manifests only as resolved participation state.

## Phase 0 - Branch And Baseline

- [x] Preserve the runtime-abstraction checklist on an icebox branch.
  - Assertion: `feat/runtime-abstraction` points at the previous runtime checklist state, while the active branch is
    `feat/memory-enhancement`.
  - Verification: branch split performed before replacing this checklist.
- [x] Map the current `forge session memory` command implementation.
  - Assertion: command registration, add/list/remove behavior, duplicate-path failure, session config writes, and test
    coverage are identified before deleting the public command group. Include `src/forge/cli/session_memory.py`,
    subgroup registration in `src/forge/cli/session.py`, `tests/src/cli/test_session_memory.py`, and integration
    coverage that shells out to the old commands.
  - Verification: CLI module (session_memory.py), registration (session.py:869-877), model (models.py:79-139, covering
    HandoffConfig, DesignatedDoc, MemoryIntent), 13 tests (test_session_memory.py), and read-effective/write-override
    persistence path all mapped in impl_notes.md.
- [x] Map the Stop-time memory update path.
  - Assertion: auto-update mode resolution, `review-only` report generation, augment writes, designated-doc strategy
    prompts, and `src/forge/session/handoff_agent.py` update behavior are tied to concrete code references.
  - Verification: full 5-step chain (stop hook, work queue, CLI startup fire-and-forget, CLI runner, agent core) with
    code references and fire-and-forget queue semantics mapped in impl_notes.md.
- [x] Map the handoff report/show surface.
  - Assertion: `forge session handoff show --latest`, review artifact paths, and any CLI read paths are tied to concrete
    code references separately from the update-side handoff agent.
  - Verification: show command (session_handoff.py), review_dir(), report listing (\_list_reports), artifact path
    pattern, and test_session_handoff_show.py mapped separately from update-side agent in impl_notes.md.
- [x] Inventory old memory UX references.
  - Assertion: docs, tests, skills, command help, README snippets, and status-doc setup examples that mention
    `forge session memory` are listed with a keep/update/remove decision. Include, at minimum, `docs/status/README.md`,
    `docs/design.md`, `docs/end-user/handoff.md`, `tests/integration/cli/`, `tests/src/cli/test_session_memory.py`,
    `src/skills/qa/resources/checklist/`, and `src/skills/walkthrough/resources/checklist.md`.
  - Verification: 8 UPDATE (including old-model YAML config in handoff.md, design_appendix.md G.2, and design.md
    DesignatedDoc schema), 2 REMOVE, 5 KEEP -- full inventory with line numbers in impl_notes.md. Includes
    test_session_handoff_show.py (KEEP) and proposals/memory_enhancement.md (KEEP).
- [x] Decide which existing helpers stay private.
  - Assertion: reusable storage, validation, and handoff helpers are named, and public compatibility aliases are
    explicitly excluded.
  - Verification: 8 helpers + 2 patterns named with reuse-privately decision; VALID_STRATEGIES moves to shared location
    in Phase 1; tombstone diagnostic path replaces old commands (no alias). Decision in impl_notes.md.

## Phase 1 - Passport Model

- [x] Define the v1 memory strategy enum.
  - Assertion: the supported `--as <strategy>` set is named in one shared place and used by passport validation, CLI
    validation, and handoff prompts. Initial set: `project-state`, `checklist`, `changelog`, `debugging`, `patterns`,
    `suggested`, and `generic`.
  - Verification: `MemoryStrategy(str, Enum)` with `VALID_STRATEGY_NAMES` and `STRATEGY_INSTRUCTIONS` in
    `src/forge/session/passport.py`. `session_memory.py` and `handoff_agent.py` both import from this shared source.
    Inline `DOC_STRATEGIES` removed from runtime code; legacy prompt tests alias `STRATEGY_INSTRUCTIONS` locally.
    `TestMemoryStrategy` covers enum/instruction shape.
- [x] Add `forge_memory` frontmatter parsing and serialization.
  - Assertion: parser preserves unrelated Markdown content, validates `version`, `intent`, `captures`, `excludes`, and
    all `update` subfields from the proposal examples (`instruction`, `strategy`, `mode`, `writers`, `inherit_on_fork`,
    `compact_when`, optional `shadow_path`, optional `approval`), and reports actionable errors for malformed passports.
  - Verification: `extract_frontmatter()`, `parse_passport()`, `read_passport()`, `write_passport()`,
    `serialize_passport()` in `passport.py`. `PassportError(field_path, reason, hint)` in `exceptions.py`. Strict
    validation rejects unknown keys, validates all fields. Atomic write via `atomic_write_text()`. Omits None fields.
    Round-trip test proves write-then-read identity. Focused tests cover frontmatter extraction, parsing, reading, and
    writing.
- [x] Implement passport-required-at-rest behavior.
  - Assertion: `forge memory track` leaves every tracked official doc with a valid passport, synthesizes one from CLI
    flags when possible, and fails with a concrete suggested command when required fields are missing.
  - Verification: no passport + no `--as` fails with actionable command suggestion listing valid strategies; no passport
    - `--as` synthesizes via `synthesize_passport()` and writes via `write_passport()` before persisting manifest entry.
      `test_track_without_passport_and_without_as_fails` and `test_track_synthesizes_passport` verify both paths.
- [x] Implement flag-vs-passport conflict handling.
  - Assertion: CLI flags win for the current invocation, warnings name the overridden passport field, and persisted
    updates are deterministic.
  - Verification: `--as` override calls `resolve_with_overrides()`, rewrites passport file (not session-scoped), and
    prints "Future sessions will use the new values." `read_passport()` after track confirms the rewritten strategy.
    `test_track_as_flag_overrides_and_rewrites_passport` verifies round-trip.
- [x] Keep ownership split between passport and session manifest.
  - Assertion: the session manifest stores only participation and auto-update runtime state; Stop-time update logic
    re-reads passport intent, instructions, writers, strategy, mode, shadow path, and inheritance.
  - Verification target: a test edits a tracked doc's passport after session participation is configured but before the
    Stop-time handoff update, then proves the handoff behavior follows the edited passport without re-running
    `forge memory track`.
  - Verification: `run_handoff_agent()` reads passports via `resolve_passport_source()`, filters by
    `check_writer_access()`, resolves via `resolve_doc_spec()`, passes `list[ResolvedDocSpec]` to
    `build_multi_doc_prompt()`. Prompt builder has no file I/O. Passport-less docs use DesignatedDoc fallbacks.
    `TestPassportLessDocsWork` proves backward compat. Full passport contract (intent, captures, excludes, compact_when,
    approval) appears in prompt context.
- [x] Validate v1 writer semantics.
  - Assertion: `all-sessions` and exact session-name writers work; lineage and role semantics are rejected or deferred
    with clear errors.
  - Verification: `validate_writer_spec()` and `check_writer_access()` in `passport.py`. `lineage:` and `role:` prefixes
    rejected with deferral message. `none` rejected. Invalid session names rejected via `validation.validate_name()`. 10
    tests across `TestWriterValidation` and `TestCheckWriterAccess`.

## Phase 2 - Top-Level CLI

- [x] Add the canonical `forge memory` command group.
  - Assertion: user-facing CLI help exposes `forge memory enable|track|untrack|list|status|shadows`; mutating commands
    require `--session <name>` unless an active session is resolved.
  - Verification: `src/forge/cli/memory.py` with 5 commands (enable, track, untrack, list, status) registered as
    top-level `forge memory` in `main.py` with `mem` alias. `shadows` deferred to Phase 3. All commands accept
    `--session` with `$FORGE_SESSION` fallback.
- [x] Delete the old public `forge session memory` surface.
  - Assertion: `src/forge/cli/session_memory.py` is removed or made private, subgroup registration is removed from
    `src/forge/cli/session.py`, old command tests are deleted or rewritten for `forge memory`, docs no longer list the
    old command table entries, there is no compatibility alias, and old invocations fail with a helpful replacement
    message instead of a generic unknown-command dead end.
  - Verification: `session_memory.py` replaced with hidden tombstone group (3 commands that error with replacement
    guidance). Registration in `session.py:_register_subgroups()` unchanged (imports the same `memory_group` name). Old
    13 tests replaced with 5 tombstone tests (bare group, help, and 3 command tombstones). `design.md` command table
    updated to remove old entries and add `forge memory` section.
- [x] Detect ignored legacy designated-doc config.
  - Assertion: when a session manifest contains a non-empty legacy `intent.memory.designated_docs[]`, Forge ignores it
    for behavior but emits a one-time notice or actionable warning that explains the clean break and points to
    `forge memory enable` / `forge memory track`.
  - Verification: `_check_legacy_docs()` counts missing vs malformed passports per-doc using
    `resolve_passport_source(doc)`. Warning says "manifest-fallback behavior" (accurate: passport-less docs still work).
    Separate counts for missing and malformed. 5 tests in `TestLegacyDetection` including shadow-doc passport source
    resolution.
- [x] Implement `forge memory enable`.
  - Assertion: command sets `memory.auto_update.enabled=true`, defaults mode to `augment`, supports `--review-only`,
    prints current tracked/shadowed docs, and is idempotent when re-run.
  - Verification: leaf-key overrides (`memory.auto_update.enabled`, `memory.auto_update.mode`) preserve existing fields
    like `min_turns`. 5 tests in `TestMemoryEnable` covering idempotency, review-only mode, doc count display.
- [x] Implement idempotent `track`.
  - Assertion: direct tracking adds or upserts a doc, updates strategy/mode when rerun, auto-enables memory for the
    session when needed, validates `--as` against the v1 strategy enum, and never creates duplicate entries.
  - Verification: 15 tests in `TestMemoryTrack` covering passport synthesis, flag-override rewrite with round-trip
    verification, upsert without duplicates, auto-enable with min_turns preservation, shadow-only rejection, invalid
    path/file/strategy rejection, output order, and custom intent.
- [x] Implement idempotent `untrack`.
  - Assertion: untracking removes direct and shadow participation as requested, succeeds clearly when the doc is absent,
    and leaves passport frontmatter intact unless an explicit passport-edit command is added later.
  - Verification: 4 tests in `TestMemoryUntrack` covering removal, absent-path success, leaves-others, and
    passport-intact.
- [x] Implement `list` and `status` visibility.
  - Assertion: `forge memory list --session <name>` and `forge memory status --scope project|repo|all --doc <path>`
    distinguish direct writers, shadow writers, handoff mode, strategy, session/worktree, and missing targets.
  - Verification: `list` shows Rich table with Path/Strategy/Mode/Writers/Passport columns and reads passport info
    per-doc (best-effort). `status` aggregates across sessions via `list_sessions()` with scope filtering. JSON output
    includes `forge_root` and `session` for disambiguation. 9 tests across `TestMemoryList` and `TestMemoryStatus`.
- [x] Implement cross-`forge_root` discovery for read-only `--scope all`.
  - Assertion: `forge memory status --scope all` can discover readable Forge roots, handles missing or inaccessible
    roots without failing the whole command, and clearly reports which roots were scanned.
  - Verification: `status` uses `list_sessions(scope="all")` which returns sessions across all forge_roots. Inaccessible
    manifests are skipped with debug log. JSON output includes `scanned_roots` array. Rich output shows root count.
    `test_inaccessible_manifest_skipped` monkeypatches `SessionManager.get_session` to simulate failure.
- [x] Keep CLI language outcome-oriented.
  - Assertion: command output explains "tracks changelog directly" and "tracks impl_notes through a shadow proposal"
    without requiring users to understand the passport YAML shape.
  - Verification: `track` output says "Tracking docs/checklist.md directly as checklist" and "Updated tracking for
    docs/changelog.md (strategy: debugging)". `enable` says "Memory auto-update enabled (mode: augment)". `untrack` says
    "Untracked docs/checklist.md." No YAML shape references in user-facing output.

## Phase 3 - Shadow Proposals

- [x] Implement `track --propose`.
  - Assertion: proposal tracking derives `.forge/memory/suggested_<basename>.md` by default, implies `suggested`
    strategy when compatible, and supports explicit `--shadow <path>` overrides.
  - Verification: `--propose` and `--shadow` flags on `forge memory track`. `derive_shadow_path()` encodes parent
    directory for disambiguation (e.g., `docs/status/notes.md` -> `.forge/memory/suggested_status_notes.md`).
    `resolve_with_overrides()` extended with `shadow_path` parameter. Direct-to-shadow conversion with 3-key upsert.
- [x] Auto-create Forge-owned shadow docs.
  - Assertion: missing shadow files under `.forge/memory/` are created with parent directories; missing official docs
    and non-Forge-owned shadow paths are not auto-created.
  - Verification: auto-creation with traversal safety in `forge memory track --propose`. Tests cover auto-create under
    `.forge/memory/` and missing non-Forge-owned paths failing unless pre-created.
- [x] Define and test shadow-path collision handling.
  - Assertion: two official docs with the same basename cannot silently share one default shadow path; Forge either
    derives a disambiguated path or fails with an actionable override command.
  - Verification: `check_shadow_path_collision()` in `passport.py` detects collisions and returns actionable error.
    Immediate-parent encoding in `derive_shadow_path()` reduces collisions. Tests in `test_passport.py`.
- [x] Add `forge memory shadows list|show`.
  - Assertion: shadow content can be grouped by official target and source session/worktree, separately from status
    configuration; `--scope all` uses the Phase 2 read-only discovery path.
  - Verification: `forge memory shadows` subgroup with `list` and `show` commands. `--scope all` uses `list_sessions()`.
    Rich tables and JSON output.
- [x] Tune handoff-agent shadow behavior.
  - Assertion: shadow update prompts allow liberal, sourceable suggestions for durable memory, while direct-write docs
    remain compact and conservative.
  - Verification: shadow-specific prompt additions in `handoff_agent.py`. Tests in `test_handoff_agent.py`.

## Phase 4 - Fork Inheritance

Tasks in this phase are coupled: do not ship `--inherit-memory shadowed` without inherited-shadow materialization and
passport override handling in the same slice.

- [x] Build inherited-shadow materialization support.
  - Assertion: inherited `.forge/memory/` shadow files can be created in the target worktree before a child session is
    persisted; non-Forge-owned shadows are reported but not created.
  - Verification: `materialize_inherited_shadows()` in `memory_inheritance.py` creates shadow files under
    `.forge/memory/` with traversal safety. Non-Forge-owned shadows reported via `warnings_sink` pattern.
- [x] Add `--inherit-memory all|none|shadowed` to session fork flows.
  - Assertion: default `all` preserves existing sticky-session expectations; `none` removes memory participation; and
    `shadowed` inherits only proposal/shadow docs while using the materialization helper above.
  - Verification: `InheritMemoryMode` enum, `filter_docs_for_inheritance()`, `apply_memory_inheritance()` in
    `memory_inheritance.py`. CLI flags on `fork` and `resume --fresh`. Default `all` preserves existing behavior. Fixed
    override-loss bug where docs tracked via `forge memory track` (stored in overrides) were silently lost on fork
    because only `intent.memory` was deep-copied.
- [x] Apply passport inheritance overrides consistently.
  - Assertion: `--inherit-memory` overrides `forge_memory.update.inherit_on_fork` with warnings, and passport defaults
    apply when the flag is omitted.
  - Verification: passport-authoritative shadow classification in `filter_docs_for_inheritance()`. Writer warnings
    emitted via `warnings_sink`. Tests cover passport override handling.
- [x] Add fork/resume tests for inherited memory.
  - Assertion: tests cover inheritance helper behavior, manager relaunch override preservation, fork/resume CLI flag
    gating, and fork-then-track persistence.
  - Verification: 38 tests in `test_memory_inheritance.py` covering filtering, materialization, passport-authoritative
    shadow classification, writer warnings, override-only inheritance, relaunch regression, fork-then-track, and CLI
    flag gating.

## Phase 5 - Curated Shadow Review

- [x] Implement read-only shadow curation.
  - Assertion: `forge memory shadows review --for <doc> --curate` reads official plus matching shadow docs, removes
    duplicates and already-promoted notes, groups related suggestions, and emits source-cited output.
  - Verification: `build_curation_prompt()` in `shadow_curation.py` inlines official + shadow content with forge_root
    citations. Self-contained prompt (no tool use). Bare `review --for` shows raw content + hint about `--curate` and
    `--show-latest`. `--json` output for both `--curate` and `--show-latest`. 11 CLI tests + 17 unit tests.
- [x] Route curation through shared LLM infrastructure.
  - Assertion: curation runs through `run_claude_session()` routed via `resolve_handoff_base_url()` so active session
    proxy configuration and proxy spend caps apply. Per-invocation cost attribution is logged best-effort through verb
    cost logs; direct usage display is deferred.
  - Verification: `run_shadow_curation()` wraps call in `track_verb_cost("curation", ...)`. CLI resolves routing and
    passes `base_url` + `direct` into core function. `test_passes_base_url_and_direct` verifies forwarding.
- [x] Persist curated review reports.
  - Assertion: reports are written to `<forge_root>/.forge/artifacts/<session>/memory/curation-{slug}-{hash}-{ts}.md`,
    and `forge memory shadows review --show-latest --for <doc>` retrieves the latest report for that doc.
  - Verification: `persist_curation_report()` uses `curation-` prefix (distinct from handoff `review-` reports).
    `_doc_slug()` with 6-char hash suffix prevents collision between `a/b.md` and `a_b.md`. `report_glob_pattern()`
    enables doc-filtered retrieval. Glob tests verify correct filtering.
- [x] Enforce session ownership for repo-scope curation.
  - Assertion: `--scope repo --curate` requires `FORGE_SESSION` or `--session`; `--scope all --curate` remains deferred.
    `--show-latest` is session-scoped; rejects `--scope repo` and `--scope all`.
  - Verification: `test_review_curate_requires_session`, `test_review_scope_all_curate_rejected`,
    `test_review_show_latest_requires_session`, `test_review_show_latest_rejects_scope_repo`.
- [x] Keep official durable docs human-approved.
  - Assertion: curation may produce a patch or promotion checklist, but never mutates `docs/status/impl_notes.md`
    without explicit user approval.
  - Verification: The Python orchestration never writes official docs (no file-write calls in `_review_curate()` or
    `run_shadow_curation()`). `test_review_curate_does_not_mutate_official` verifies this for the orchestration layer.
    The curation subprocess (`claude -p`) runs with write-capable tools but is instructed read-only via the prompt. Same
    trust model as the handoff agent's `review-only` mode. A `--read-only` subprocess mode is a useful future
    enhancement but is not blocked on this phase.

## Phase 6 - Docs, Tests, And Dogfooding

- [ ] Update user and developer docs for the new memory model.
  - Assertion: Phase 0's old-UX inventory has been applied. README/status docs/design/developer docs/end-user guides and
    skill checklists no longer teach `forge session memory`; they explain `forge memory`, passports, shadows, first-run
    review-only mode, idempotency, and clean-break migration.
- [ ] Add targeted unit and CLI tests.
  - Assertion: tests cover passport parsing, track/untrack idempotency, enable behavior, status scopes, shadow
    auto-create, inheritance modes, and curation report ownership.
- [ ] Dogfood on the active status docs.
  - Assertion: this branch uses `forge memory` to track `docs/status/change_log.md` directly and
    `docs/status/impl_notes.md` through shadow proposals, with the first review-only report inspected before augment.
- [ ] Record the outcome before returning to runtime abstraction.
  - Assertion: `docs/status/change_log.md` has a compact final entry, durable lessons are promoted to
    `docs/status/impl_notes.md`, and the runtime-abstraction branch can resume with the preserved checklist.

## Open Decisions

Tracks Forge-local execution decisions for this checklist. For proposal-level context, see
[`docs/proposals/memory_enhancement.md`](../proposals/memory_enhancement.md).

- [x] Should curation ship in the first memory PR, or should it become a follow-up after `track`/`status`/inheritance
  are dogfooded?
  - **Decision**: Ship with the first memory PR. Phase 5 is part of the same branch.
- [x] Should the default shadow-path disambiguation encode parent directories or require explicit `--shadow` on
  collision?
  - **Decision**: Encode the immediate parent directory in the shadow filename (e.g., `docs/status/notes.md` ->
    `.forge/memory/suggested_status_notes.md`). Implemented in `derive_shadow_path()`. Collision checking via
    `check_shadow_path_collision()` catches remaining edge cases.
- [ ] Should `forge memory passport show|set` land with the first CLI surface, or wait until users hit advanced-edit
  needs?
