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
- [ ] Map the current `forge session memory` command implementation.
  - Assertion: command registration, add/list/remove behavior, duplicate-path failure, session config writes, and test
    coverage are identified before deleting the public command group.
- [ ] Map the current memory handoff path.
  - Assertion: auto-update mode resolution, `review-only` report generation, augment writes, designated-doc strategy
    prompts, and `forge session handoff show --latest` are tied to concrete code references.
- [ ] Inventory old memory UX references.
  - Assertion: docs, tests, skills, command help, README snippets, and status-doc setup examples that mention
    `forge session memory` are listed with a keep/update/remove decision.
- [ ] Decide which existing helpers stay private.
  - Assertion: reusable storage, validation, and handoff helpers are named, and public compatibility aliases are
    explicitly excluded.

## Phase 1 - Passport Model

- [ ] Add `forge_memory` frontmatter parsing and serialization.
  - Assertion: parser preserves unrelated Markdown content, validates `version`, `intent`, `captures`, `excludes`, and
    `update` fields, and reports actionable errors for malformed passports.
- [ ] Implement passport-required-at-rest behavior.
  - Assertion: `forge memory track` leaves every tracked official doc with a valid passport, synthesizes one from
    CLI flags when possible, and fails with a concrete suggested command when required fields are missing.
- [ ] Implement flag-vs-passport conflict handling.
  - Assertion: CLI flags win for the current invocation, warnings name the overridden passport field, and persisted
    updates are deterministic.
- [ ] Keep ownership split between passport and session manifest.
  - Assertion: the session manifest stores only participation and auto-update runtime state; Stop-time update logic
    re-reads passport intent, instructions, writers, strategy, mode, shadow path, and inheritance.
- [ ] Validate v1 writer semantics.
  - Assertion: `all-sessions` and exact session-name writers work; lineage and role semantics are rejected or deferred
    with clear errors.

## Phase 2 - Top-Level CLI

- [ ] Add the canonical `forge memory` command group.
  - Assertion: user-facing docs/help expose `forge memory`; the old public `forge session memory` group is removed with
    no compatibility alias.
- [ ] Implement `forge memory enable`.
  - Assertion: command sets `memory.auto_update.enabled=true`, defaults mode to `augment`, supports `--review-only`,
    prints current tracked/shadowed docs, and is idempotent when re-run.
- [ ] Implement idempotent `track`.
  - Assertion: direct tracking adds or upserts a doc, updates strategy/mode when rerun, auto-enables memory for the
    session when needed, and never creates duplicate entries.
- [ ] Implement idempotent `untrack`.
  - Assertion: untracking removes direct and shadow participation as requested, succeeds clearly when the doc is absent,
    and leaves passport frontmatter intact unless an explicit passport-edit command is added later.
- [ ] Implement `list` and `status` visibility.
  - Assertion: `forge memory list --session <name>` and `forge memory status --scope project|repo|all|--doc <path>`
    distinguish direct writers, shadow writers, handoff mode, strategy, session/worktree, and missing targets.
- [ ] Keep CLI language outcome-oriented.
  - Assertion: command output explains "tracks changelog directly" and "tracks impl_notes through a shadow proposal"
    without requiring users to understand the passport YAML shape.

## Phase 3 - Shadow Proposals

- [ ] Implement `track --propose`.
  - Assertion: proposal tracking derives `.forge/memory/suggested_<basename>.md` by default, implies `suggested`
    strategy when compatible, and supports explicit `--shadow <path>` overrides.
- [ ] Auto-create Forge-owned shadow docs.
  - Assertion: missing shadow files under `.forge/memory/` are created with parent directories; missing official docs
    and non-Forge-owned shadow paths are not auto-created.
- [ ] Define and test shadow-path collision handling.
  - Assertion: two official docs with the same basename cannot silently share one default shadow path; Forge either
    derives a disambiguated path or fails with an actionable override command.
- [ ] Add `forge memory shadows list|show`.
  - Assertion: shadow content can be grouped by official target and source session/worktree, separately from status
    configuration.
- [ ] Tune handoff-agent shadow behavior.
  - Assertion: shadow update prompts allow liberal, sourceable suggestions for durable memory, while direct-write docs
    remain compact and conservative.

## Phase 4 - Fork Inheritance

- [ ] Add `--inherit-memory all|none|shadowed` to session fork flows.
  - Assertion: default `all` preserves existing sticky-session expectations; `none` removes memory participation; and
    `shadowed` inherits only proposal/shadow docs.
- [ ] Apply passport inheritance overrides consistently.
  - Assertion: `--inherit-memory` overrides `forge_memory.update.inherit_on_fork` with warnings, and passport defaults
    apply when the flag is omitted.
- [ ] Materialize inherited shadow files in new worktrees.
  - Assertion: inherited `.forge/memory/` shadow files are created in the target worktree, non-Forge-owned shadows are
    reported but not created, and all created paths are shown to the user.
- [ ] Add fork/resume tests for inherited memory.
  - Assertion: tests cover normal worktree fork, `--into` existing worktree, and no-memory scratch forks.

## Phase 5 - Curated Shadow Review

- [ ] Implement read-only shadow curation.
  - Assertion: `forge memory shadows review --for <doc> --curate` reads official plus matching shadow docs, removes
    duplicates and already-promoted notes, groups related suggestions, and emits source-cited output.
- [ ] Route curation through shared LLM infrastructure.
  - Assertion: curation uses `forge.core.llm`, honors active session proxy configuration and configured spend caps, and
    reports per-invocation usage.
- [ ] Persist curated review reports.
  - Assertion: reports are written to `<forge_root>/.forge/artifacts/<session>/memory/review-<timestamp>.md`, and
    `forge memory shadows review --show-latest` retrieves the latest report.
- [ ] Enforce session ownership for repo-scope curation.
  - Assertion: `--scope repo --curate` requires `FORGE_SESSION` or `--session`; `--scope all --curate` remains deferred.
- [ ] Keep official durable docs human-approved.
  - Assertion: curation may produce a patch or promotion checklist, but never mutates `docs/status/impl_notes.md`
    without explicit user approval.

## Phase 6 - Docs, Tests, And Dogfooding

- [ ] Update user and developer docs for the new memory model.
  - Assertion: README/status docs/design/developer docs no longer teach `forge session memory`; they explain
    `forge memory`, passports, shadows, first-run review-only mode, idempotency, and clean-break migration.
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

- [ ] Should curation ship in the first memory PR, or should it become a follow-up after `track`/`status`/inheritance
  are dogfooded?
- [ ] Should the default shadow-path disambiguation encode parent directories or require explicit `--shadow` on
  collision?
- [ ] Should `forge memory passport show|set` land with the first CLI surface, or wait until users hit advanced-edit
  needs?
