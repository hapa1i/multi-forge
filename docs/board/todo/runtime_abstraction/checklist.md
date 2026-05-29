# Runtime Abstraction Checklist

Manual multi-session plan for executing [`card.md`](./card.md).

This card is currently parked in `todo/`. Move the whole `runtime_abstraction/` directory to `docs/board/doing/` when
its execution branch is created, and to `docs/board/done/` after closeout.

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
wc -l docs/board/todo/runtime_abstraction/checklist.md
./scripts/count-tokens.py --model <agent-model> docs/board/todo/runtime_abstraction/checklist.md
```

## Current Focus

Phase 1: stabilize curated handoff as a schema-backed, user-reviewable cross-runtime substrate. Keep CLI default
behavior unchanged unless a separate default-change decision is recorded.

**Deferred prerequisite (memory_substrate reconciliation, 2026-05-29):**

- [ ] Reconcile this card's "curated handoff" vocabulary with the shipped **transfer** taxonomy, and retarget the
  proposed `forge session handoff regenerate|edit|diff` surface (now removed/tombstoned in favor of `forge memory ...`)
  before implementing the schema. The doc-updater is the **memory writer**; resume/fork context is **transfer**. Align
  with `docs/design.md` §3.9 (transfer) and §5.6 (memory writer). The concrete code surfaces in this card were repointed
  to `memory_writer.py`/`transfer.py` on 2026-05-29; the conceptual vocabulary was intentionally left for this card to
  own when it executes.

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

## Phase 1 - Curated Handoff Reframe

- [ ] Reposition `ai-curated` / curated handoff in `docs/design.md` as the primary cross-runtime and cross-topology
  transfer substrate, not merely a lossy fallback.
  - Assertion: design text distinguishes native resume, native-relocate, and curated handoff by user agency and runtime
    portability. This is a prose/schema reframe only; `structured` remains the CLI default unless an explicit default
    change is approved.
- [x] Verify `forge session resume --review` behavior.
  - Note: this shipped before the runtime-abstraction checklist was activated; it is retained here as verified Phase 1
    foundation.
  - Assertion: handoff-mode resume opens the generated child handoff file in `$EDITOR`; native mode rejects `--review`
    with an actionable error.
  - Verification: `src/forge/cli/session_lifecycle.py` implements the `resume --review` option, native-mode rejection,
    and `$EDITOR` launch for the generated child context; `docs/design.md` command reference documents the CLI contract;
    `tests/src/cli/test_session_resume_review.py` covers the behavior.
- [ ] Decide the resume-context command namespace before adding `regenerate|edit|diff`.
  - Assertion: command contract avoids collision with memory-doc handoff reports under `forge session handoff show`.
    Candidate surface: `forge session context regenerate|edit|diff`.
- [ ] Define the Forge-owned curated handoff schema contract in docs.
  - Assertion: schema records lineage, decisions with citations, current state, open questions, runtime hints, and user
    notes overlay.
- [ ] Implement the curated handoff schema in `src/forge/session/transfer.py`.
  - Assertion: generated handoff markdown has stable sections for the schema fields; existing
    `minimal|structured|full|ai-curated` strategies either emit that schema or document their compatibility fallback.
- [ ] Add tests for schema output and artifact durability.
  - Assertion: tests cover parent cache regeneration, per-child artifact preservation, and required schema sections for
    curated output.
- [ ] Define the user notes overlay convention.
  - Assertion: docs/code state where user notes live, how they compose with generated content, and that regeneration
    never overwrites authoritative user notes.
- [ ] Decide how `ctx` relates to Forge handoff.
  - Assertion: docs state whether `ctx` is only prior art, an import/export peer, or a future dependency.
- [ ] Confirm Phase 1 schema is stable enough for Phase 5 target-runtime tuning.
  - Assertion: Phase 5 can tune handoff presentation for Codex without changing transcript source artifacts or schema
    semantics.

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
- [ ] Tie the spike to the current no-op and handoff-only guards.
  - Assertion: checklist/test references cover the native-resume guard in `src/forge/session/manager.py` and the
    worktree-fork handoff branch in `src/forge/cli/session_fork.py`.
- [ ] Split native-relocate handling by code path.
  - Assertion: `fork --worktree`, `fork --into`, and `resume --fresh --resume-mode native-relocate` each have an
    explicit expected behavior before implementation.
- [ ] Gate path rewriting separately.
  - Assertion: absolute path rewriting is opt-in and disabled by default until tests prove it harmless.
- [ ] Preserve derivation and GC invariants for relocated artifacts.
  - Assertion: relocated JSONL, generated parent cache, and per-child handoff artifacts are traceable without orphaning
    or overwriting user-edited child files.
- [ ] Decide outcome of native-relocate.
  - Assertion: either introduce opt-in `--resume-mode native-relocate` or record why curated handoff remains the only
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
  - Assertion: consumes the stable Phase 1 handoff schema so output can be tuned for Codex without changing source
    transcript artifacts or schema semantics.
- [ ] Demonstrate Claude-to-Codex resume.
  - Assertion: a documented workflow can plan in Claude and implement in Codex using curated handoff.

## Phase 6 - Codex Frontend Beta

- [ ] Evaluate Codex as an interactive frontend runtime.
  - Assertion: decision is based on headless invocation, usage accounting, policy semantics, and curated handoff results
    from earlier phases.

## Open Decisions

Tracks Forge-local execution decisions for this checklist. For broader card questions, see
[`card.md` Open Questions](./card.md#open-questions).

- [ ] Should `forge session resume --review` become default for curated handoff workflows?
- [ ] Should the resume-context command surface be `forge session context ...` instead of overloading
  `forge session handoff ...`?
- [ ] Should Phase 1 remain prose/schema-only, or should it change the default strategy after schema tests land?
- [ ] Where do proxy cost logs, audit logs, and the future usage ledger converge?
- [ ] How should `FORGE_DEPTH` compose with future run-tree attribution ids?
