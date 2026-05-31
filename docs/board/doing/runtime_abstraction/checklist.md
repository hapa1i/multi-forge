# Runtime Abstraction Checklist

Manual multi-session plan for executing [`card.md`](./card.md).

This card is in active execution under `doing/`. Move the whole `runtime_abstraction/` directory to `docs/board/done/`
after closeout.

## Maintenance

- Update this file during implementation sessions and once before ending a session.
- Keep tasks high-level, with concrete assertions that prove completion.
- Tick a task only when the assertion is satisfied and verification is recorded.
- Add short blocker notes inline under the relevant phase.
- Move completed-session details to `docs/board/change_log.md`; keep only active plan state here.
- Promote durable lessons to `docs/board/impl_notes.md` after human review.
- Update design docs per-phase as code ships (design docs are normative, not aspirational).
- Move the card directory to `docs/board/done/<slug>/` after the card is fully executed.
- Check size periodically while a card is active:

```bash
wc -l docs/board/doing/runtime_abstraction/checklist.md
./scripts/count-tokens.py --model <agent-model> docs/board/doing/runtime_abstraction/checklist.md
```

## Current Focus

Phase 1 largely shipped (commit `2b70c29`, 2026-05-31): schema-backed curated transfer, the `children/<child>.notes.md`
overlay, and the top-level `forge transfer show|regenerate|edit|diff` CLI; `docs/design.md` §3.9 and
`docs/design_appendix.md` §M reflect it. Remaining Phase 1 work: record a `ctx` interop decision in a design doc, then
the closeout sign-off (schema-stable-for-Phase-5). CLI default stays `structured` unless a separate default-change
decision is recorded (see Open Decisions).

**Deferred prerequisite (memory_substrate reconciliation) -- RESOLVED 2026-05-30:**

- [x] Reconcile this card's "curated handoff" vocabulary with the shipped **transfer** taxonomy, and retarget the
  proposed `forge session handoff regenerate|edit|diff` surface before implementing the schema.
  - Resolution: `card.md` now uses **curated transfer** throughout (the `ai-curated` transfer strategy, repositioned as
    the primary cross-runtime substrate), with a vocabulary note in the "Curated Transfer as Cross-Runtime Substrate"
    section tying it to `docs/design.md` §3.9 (transfer) and §5.6 (memory writer). The doc-updater stays the **memory
    writer**; resume/fork context stays **transfer**.
  - Namespace: the retargeted verbs live under a new **top-level `forge transfer` group**
    (`forge transfer show|regenerate|edit|diff`), chosen over `forge session transfer` on user-mental-model grounds so
    it pairs with `forge memory`. `forge session resume --fresh --review` stays the ergonomic entry point, not a second
    namespace. See the resolved namespace task in Phase 1 and the Open Decisions.
  - Verification: `rg "handoff" card.md` returns only intentional refs (the quoted historical term in the vocabulary
    note + `forge session handoff` tombstone mentions); `rg "forge session transfer" card.md` returns nothing.

## Phase 0 - Baseline Confirmation

- [x] Confirm PR #8 cost-control and routing foundation state.
  - Verification: Phase 0 foundations map to shipped code: subprocess routing in `src/forge/core/reactive/routing.py`
    and `src/forge/review/routing.py`; proxy request cost logs/caps in `src/forge/proxy/cost_logger.py`,
    `src/forge/proxy/server.py`, and `src/forge/config/schema.py`; session subprocess proxy inheritance in
    `tests/src/session/test_subprocess_proxy_inheritance.py`.
- [x] Record Phase 0 gaps before starting Phase 1 work.
  - Verification: foundation is confirmed, with future gaps carried forward below.

Phase 0 gaps carried forward:

- Team supervisor verb-cost snapshots remain future for `src/forge/policy/team/handlers.py`; track under Phase 4 usage
  ledger callsites.
- Review engine routing plans shipped, but review fan-out is still outside the invoker abstraction; track under Phase 4
  `HeadlessInvoker` and fan-out migration.
- Session and Claude launchers have subprocess-proxy environment wiring, but the durable runtime usage ledger remains
  future; track under Phase 4 usage ledger callsites.

## Phase 1 - Curated Transfer Reframe

- [x] Reposition `ai-curated` / curated transfer in `docs/design.md` as the primary cross-runtime and cross-topology
  transfer substrate, not merely a lossy fallback.
  - Assertion: design text distinguishes native resume (byte-faithful but opaque and CWD-locked) from curated transfer
    (runtime-neutral, user-editable) by user agency and runtime portability; `structured` remains the CLI default unless
    an explicit default change is approved.
  - Scope note (assertion refined 2026-05-31): the native-*relocate* leg of the agency reframe stays in `card.md` and
    lands in `design.md` only when Phase 3 ships native-relocate. Design docs describe shipped behavior
    (documentation-guidelines Rule 2), so an unshipped Phase 3 spike must not be written as current design; the original
    assertion's "native-relocate" clause was dropped for this reason.
  - Verification (2026-05-31): `docs/design.md` §3.9 ("Curated transfer is the primary cross-boundary substrate, not a
    lossy fallback") shipped in commit `2b70c29`; `structured` confirmed still the CLI default in both the prose and
    `transfer.py`.
- [x] Verify `forge session resume --fresh --review` behavior.
  - Note: this shipped before the runtime-abstraction checklist was activated; it is retained here as verified Phase 1
    foundation.
  - Assertion: transfer-mode resume opens the per-child user-notes overlay (`children/<child>.notes.md`) in `$EDITOR`;
    native mode rejects `--review` with an actionable error.
  - Verification: `src/forge/cli/session_lifecycle.py` implements the `resume --review` option, native-mode rejection,
    and `$EDITOR` launch for the user-notes overlay; `docs/design.md` command reference documents the CLI contract;
    `tests/src/cli/test_session_resume_review.py` covers the behavior.
- [x] Decide the resume-context command namespace before adding `regenerate|edit|diff`.
  - Decision (2026-05-30): **top-level `forge transfer` group** -- `forge transfer show|regenerate|edit|diff`. Chosen
    over the `forge session transfer` subgroup on user-mental-model grounds: users think "inspect/reshape the context
    that moves forward," not "a subresource of session," and it pairs with the top-level `forge memory` as the two
    halves of the former "handoff." This is a user-facing-namespace choice, not a scoping claim -- transfer is still
    session-derived and every verb takes a parent session argument.
  - Verified free/occupied (2026-05-30): `forge transfer` is unclaimed (no CLI command; `transfer` appears only as the
    `--resume-mode` value, a `forge clean` category key, and internal `transfer.py` symbols). `forge session handoff` is
    a removed-command tombstone (redirects to `forge memory report show`) and `forge session context` is a hidden
    deprecated alias for `forge session show` -- neither reusable. `forge transfer show` (assembled transfer artifact)
    is deliberately distinct from the deprecated `forge session context` (a running session's runtime context).
  - Single canonical namespace only: `forge session resume --fresh --review` remains a delegating entry point, not a
    competing surface.
- [x] Define the Forge-owned curated transfer schema contract in docs.
  - Assertion: schema records lineage, decisions with citations, current state, open questions, runtime hints, and user
    notes overlay.
  - Verification (2026-05-31): `docs/design_appendix.md` §M documents the contract -- §M.1 child-agnostic frontmatter
    (`schema_version: 1`, `schema`, `strategy`, `lineage`, `target_runtime`), §M.2 the 8 canonical sections (Lineage,
    Goal/Current Task, Decisions cited, Current State, Relevant Files, Open Questions, Runtime Hints, User Notes), §M.3
    the three-file layout + overlay. Shipped in `2b70c29`.
- [x] Implement the curated transfer schema in `src/forge/session/transfer.py`.
  - Assertion: generated transfer markdown has stable sections for the schema fields; existing
    `minimal|structured|full|ai-curated` strategies either emit that schema or document their compatibility fallback.
  - Verification (2026-05-31): `transfer.py` `_build_ai_curated_output()` emits canonical sections 1-7 (section 8 is the
    `.notes.md` overlay merged at show/launch); `_build_frontmatter()` stamps `schema: "full"` only for a successful
    ai-curated body and `schema: "compatibility-fallback"` for `minimal|structured|full`;
    `_validate_decision_citations()` drops fabricated citations so `schema: full` stays honest. Shipped in `2b70c29`.
- [x] Add tests for schema output and artifact durability.
  - Assertion: tests cover parent cache regeneration, per-child artifact preservation, and required schema sections for
    curated output.
  - Verification (2026-05-31): 113 passed -- `tests/src/session/test_transfer.py`
    (`test_ai_curated_renders_schema_sections`, `test_compatibility_fallback_frontmatter`,
    `test_generated_and_child_are_byte_identical`, citation grounding), `tests/src/cli/test_transfer_cli.py`
    (`test_regenerate_preserves_strategy`, `test_regenerate_does_not_touch_notes`,
    `test_show_json_includes_section_map`), `tests/src/session/test_prev_sessions.py` (notes round-trip, compose,
    `iter_children` excludes notes), and regression `tests/regression/test_bug_transfer_notes_not_gc_orphaned.py`.
- [x] Define the user notes overlay convention.
  - Assertion: docs/code state where user notes live, how they compose with generated content, and that regeneration
    never overwrites authoritative user notes.
  - Verification (2026-05-31): `children/<child>.notes.md` is the editable overlay (design.md §3.9, appendix §M.3);
    `prev_sessions.py` composes notes after the frozen snapshot at launch, `ensure_child` never overwrites an existing
    child, and `forge transfer regenerate` rewrites only `generated.md`. Covered by `test_prev_sessions.py`
    (`test_snapshot_notes_round_trip`, `test_compose_merges_user_notes`, `test_compose_skips_empty_notes`). Shipped in
    `2b70c29`.
- [ ] Decide how `ctx` relates to Forge transfer.
  - Assertion: docs state whether `ctx` is only prior art, an import/export peer, or a future dependency.
  - Status (2026-05-31): NOT done. `card.md` leans "Forge-owned schema; `ctx` as prior art/peer, not a first
    dependency," but `docs/design.md` records no `ctx` decision and the card still lists interop as an Open Question.
    Tick only once the posture is written into a design doc.
- [ ] Confirm Phase 1 schema is stable enough for Phase 5 target-runtime tuning.
  - Assertion: Phase 5 can tune transfer presentation for Codex without changing transcript source artifacts or schema
    semantics.
  - Status (2026-05-31): supporting evidence exists -- the schema reserves `target_runtime` (frontmatter +
    `TRANSFER_TARGET_RUNTIME`, appendix §M.1) and code owns the section skeleton, so Phase 5 can retarget presentation
    without touching transcript artifacts. Left unchecked as the deliberate Phase 1 closeout sign-off (pending the `ctx`
    decision and the default-strategy decision in Open Decisions).

## Phase 2 - Optional Audit Proxy

- [ ] Add Anthropic passthrough proxy template design.
  - Assertion: template is pure passthrough with explicit logging/intercept modes and no tier mapping confusion.
- [ ] Define intercept modes: `passthrough`, `inspect`, `override`.
  - Assertion: preflight reports which mode is active and what Forge can or cannot inspect.
- [ ] Design full-body audit logging with redaction.
  - Assertion: redaction policy covers headers, request bodies, response bodies, and tool payloads before
    `audit_full_body` can be enabled.
- [ ] Add audit CLI surface design.
  - Assertion: `forge proxy audit show|diff` behavior is specified with safe defaults.

## Phase 3 - Native-Relocate Spike

- [ ] Spike cross-CWD Claude JSONL relocation.
  - Assertion: integration contract test proves Claude Code can resume relocated JSONL across CWD boundary without
    signature-validation failure, while explicitly acknowledging the prior Claude Code 2.1.90 negative result documented
    in `docs/design.md` §3.9.
- [ ] Tie the spike to the current no-op and transfer-only guards.
  - Assertion: checklist/test references cover the native-resume guard in `src/forge/session/manager.py` and the
    worktree-fork transfer branch in `src/forge/cli/session_fork.py`.
- [ ] Split native-relocate handling by code path.
  - Assertion: `fork --worktree`, `fork --into`, and `resume --fresh --resume-mode native-relocate` each have an
    explicit expected behavior before implementation.
- [ ] Gate path rewriting separately.
  - Assertion: absolute path rewriting is opt-in and disabled by default until tests prove it harmless.
- [ ] Preserve derivation and GC invariants for relocated artifacts.
  - Assertion: relocated JSONL, generated parent cache, and per-child transfer artifacts are traceable without orphaning
    or overwriting user-edited child files.
- [ ] Decide outcome of native-relocate.
  - Assertion: either introduce opt-in `--resume-mode native-relocate` or record why curated transfer remains the only
    cross-CWD path.

## Phase 4 - Runtime Abstraction Core

- [ ] Introduce `HeadlessInvoker` interface and `ClaudeHeadlessInvoker`.
  - Assertion: existing single headless callers of `run_claude_session()` keep user-visible behavior, timeout semantics,
    environment routing, and fail-open/fail-closed choices.
- [ ] Move review-engine fan-out behind invoker lifecycle management.
  - Assertion: `src/forge/review/engine.py` parallel `subprocess.Popen()` fan-out, process-group cleanup, timeout
    handling, cancellation, and deterministic result ordering are preserved and covered by tests.
- [ ] Add runtime registry capability matrix.
  - Assertion: registry answers installed, interactive, headless, hooks, usage, native resume, and scope capabilities.
- [ ] Generalize existing `ActionContext` / `PolicyDecision` for runtime adapters.
  - Assertion: current Claude hook adapter behavior is unchanged, runtime identity is represented explicitly, and Codex
    adapter limitations are represented as capabilities instead of implied parity.
- [ ] Define durable usage ledger schema.
  - Assertion: `~/.forge/usage/events.jsonl` event schema covers runtime, provider, model, proxy, billing mode, tokens,
    latency, status, and attribution ids.
- [ ] Instrument usage ledger callsites in staged order.
  - Assertion: workflow verbs (`src/forge/cli/workflow.py`), memory writer (`src/forge/session/memory_writer.py`),
    review engine (`src/forge/review/engine.py`), semantic supervisor (`src/forge/policy/semantic/supervisor.py`), team
    supervisor (`src/forge/policy/team/handlers.py`), Claude launcher (`src/forge/cli/claude.py`), and session launcher
    (`src/forge/cli/session.py`) each have an explicit done/deferred status.

## Phase 5 - Cross-Runtime Resume

- [ ] Add `CodexHeadlessInvoker`.
  - Assertion: uses `codex exec` JSONL output and captures usage events when available.
- [ ] Add runtime/auth preflight for native Codex execution.
  - Assertion: unsupported auth paths fail before launch with setup guidance.
- [ ] Add target-runtime-aware curator.
  - Assertion: consumes the stable Phase 1 transfer schema so output can be tuned for Codex without changing source
    transcript artifacts or schema semantics.
- [ ] Demonstrate Claude-to-Codex resume.
  - Assertion: a documented workflow can plan in Claude and implement in Codex using curated transfer.

## Phase 6 - Codex Frontend Beta

- [ ] Evaluate Codex as an interactive frontend runtime.
  - Assertion: decision is based on headless invocation, usage accounting, policy semantics, and curated transfer
    results from earlier phases.

## Open Decisions

Tracks Forge-local execution decisions for this checklist. For broader card questions, see
[`card.md` Open Questions](./card.md#open-questions).

- [ ] Should `forge session resume --fresh --review` become default for curated transfer workflows?
- [x] Which transfer-owned namespace should the resume-context commands use? **Resolved 2026-05-30: top-level
  `forge transfer ...`** (not `forge session transfer ...`), pairing with `forge memory`. Rationale and free/occupied
  verification are recorded in the Phase 1 namespace task above.
- [ ] Should Phase 1 remain prose/schema-only, or should it change the default strategy after schema tests land?
- [ ] Where do proxy cost logs, audit logs, and the future usage ledger converge?
- [ ] How should `FORGE_DEPTH` compose with future run-tree attribution ids?
