# Runtime Abstraction Checklist

Manual multi-session plan for executing `docs/proposals/runtime_abstraction.md`.

`docs/status/checklist.md` tracks one active milestone/proposal at a time. After this proposal is fully executed, move
this file to `docs/status/archive/runtime_abstraction.md` and start a fresh checklist for the next active proposal.

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

Phase 1: make curated handoff the explicit cross-runtime substrate and expose the user-review workflow cleanly.

## Phase 0 - Baseline Confirmation

- [ ] Confirm PR #8 cost-control and routing foundation state.
  - Assertion: `docs/proposals/runtime_abstraction.md` Phase 0 items either map to shipped code/tests or have explicit
    follow-up checklist items.
- [ ] Record any Phase 0 gaps before starting Phase 1 work.
  - Assertion: gaps are listed under this checklist or moved to a tracked issue.

## Phase 1 - Curated Handoff Reframe

- [ ] Reposition `ai-curated` / curated handoff in `docs/design.md` as the primary cross-runtime and cross-topology
  transfer substrate, not merely a lossy fallback.
  - Assertion: design text distinguishes native resume, native-relocate, and curated handoff by user agency and runtime
    portability.
- [ ] Add or verify `forge session resume --review` behavior.
  - Assertion: handoff-mode resume opens the generated child handoff file in `$EDITOR`; native mode rejects `--review`
    with an actionable error.
- [ ] Define the Forge-owned curated handoff schema.
  - Assertion: schema records lineage, decisions with citations, current state, open questions, runtime hints, and user
    notes overlay.
- [ ] Decide how `ctx` relates to Forge handoff.
  - Assertion: docs state whether `ctx` is only prior art, an import/export peer, or a future dependency.
- [ ] Add `forge session handoff regenerate|edit|diff` design or implementation.
  - Assertion: command contract is documented before implementation, or implemented with tests if scope is clear.

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
    signature-validation failure.
- [ ] Gate path rewriting separately.
  - Assertion: absolute path rewriting is opt-in and disabled by default until tests prove it harmless.
- [ ] Decide outcome of native-relocate.
  - Assertion: either introduce opt-in `--resume-mode native-relocate` or record why curated handoff remains the only
    cross-CWD path.

## Phase 4 - Runtime Abstraction Core

- [ ] Introduce `HeadlessInvoker` interface and `ClaudeHeadlessInvoker`.
  - Assertion: existing supervisor, handoff, and workflow behavior stays user-visible compatible.
- [ ] Move review-engine fan-out behind invoker lifecycle management.
  - Assertion: process-group cleanup, timeout handling, cancellation, and parallel fan-out are covered by tests.
- [ ] Add runtime registry capability matrix.
  - Assertion: registry answers installed, interactive, headless, hooks, usage, native resume, and scope capabilities.
- [ ] Normalize hook payloads into `ActionContext` / `PolicyDecision`.
  - Assertion: Claude hook adapter behavior is unchanged, and Codex adapter limitations are represented as capabilities.
- [ ] Start durable usage ledger design or implementation.
  - Assertion: `~/.forge/usage/events.jsonl` event schema covers runtime, provider, model, proxy, billing mode, tokens,
    latency, status, and attribution ids.

## Phase 5 - Cross-Runtime Resume

- [ ] Add `CodexHeadlessInvoker`.
  - Assertion: uses `codex exec` JSONL output and captures usage events when available.
- [ ] Add runtime/auth preflight for native Codex execution.
  - Assertion: unsupported auth paths fail before launch with setup guidance.
- [ ] Add target-runtime-aware curator.
  - Assertion: handoff output can be tuned for Codex without changing the source transcript artifacts.
- [ ] Demonstrate Claude-to-Codex resume.
  - Assertion: a documented workflow can plan in Claude and implement in Codex using curated handoff.

## Phase 6 - Codex Frontend Beta

- [ ] Evaluate Codex as an interactive frontend runtime.
  - Assertion: decision is based on headless invocation, usage accounting, policy semantics, and curated handoff results
    from earlier phases.

## Open Decisions

Tracks Forge-local execution decisions for this checklist. For broader proposal questions, see
[`docs/proposals/runtime_abstraction.md` Open Questions](../proposals/runtime_abstraction.md#open-questions).

- [ ] Should `forge session resume --review` become default for curated handoff workflows?
- [ ] Where do proxy cost logs, audit logs, and the future usage ledger converge?
- [ ] How should `FORGE_DEPTH` compose with future run-tree attribution ids?
