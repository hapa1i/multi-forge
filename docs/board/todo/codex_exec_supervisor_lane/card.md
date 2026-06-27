# T4 -- Codex-exec supervisor lane

**Epic**: `docs/board/doing/epic_consumer_lanes/` -- read the epic for the shared lane contract (runtime x backend x
model; resolve once, frozen). This is the **headline capability demo**: the first consumer placed on a *non-Claude*
runtime, proving the lane abstraction admits a real new lane swappably.

**Lane**: `todo/` (accepted; the next member to open -- next queued execution target, no execution branch yet).

**Proves**: a real new lane (codex-exec) is swappable behind one narrow field -- the lane model is more than the
byte-identical Claude default T3 shipped.

## Goal

Wire `CodexHeadlessInvoker` as a supervisor dispatch target. The choice rides a **narrow `SupervisorConfig` field**
(already session-owned and persisted), so it needs no general durable schema (that is T1b). **Acceptance:
blind/transfer-fed only -- the claim MUST NOT use Codex hooks or policy enforcement.**

## Why this is cheap (verified -- epic card "Assembly is cheap")

The pieces are shipped:

- `parse_supervisor_verdict(response: str)` takes a plain string (`verdict.py:86`).
- `CodexHeadlessInvoker` already returns its final text in the same `HeadlessResult.stdout` envelope (`codex.py:96`) --
  which is exactly why the verdict parser works for Claude and Codex alike.
- `compose_codex_initial_message(transfer_body, task)` (`codex_bridge.py`) already frames a curated transfer + task into
  a `codex exec` prompt.
- The supervisor prompt is already text-composition with precedent for context injection (`supervisor.py:458-466`).

## Scope (concrete changes)

- **`SupervisorConfig` gains a narrow lane/runtime override** (`supervisor.py:237` has no `runtime` field today).
  Default resolves to the `claude_code` lane (byte-identical to T3); an override selects the `codex` lane.
- **Implement the `codex` arm of `_dispatch_supervisor`** (`supervisor.py:463-464` raises `NotImplementedError` today):
  compose via `compose_codex_initial_message`, dispatch via `CodexHeadlessInvoker`, parse via
  `parse_supervisor_verdict(stdout)`.
- **Single usage emission preserved.** The codex arm emits exactly one usage event (the claude arm's sole
  `emit_usage_for_session_result`), with `billing_mode` reflecting the codex/chatgpt lane. Ties to T5.
- **Fail-open wiring (the T3 -> T4 carry-forward seams -- see epic `card.md`).** These flip live the instant the codex
  arm + override exist; the supervisor's contract is fail-open (design_workflows §1.2):
  - Move `resolve_lane(SUPERVISOR_CONSUMER, override=...)` **inside** the `try/except _SupervisorRoutingError`
    (`supervisor.py:603`), or pre-validate + degrade -- a bad override must not crash the policy hook.
  - **Unsupported-lane failure mode is DECIDED: catch + fail-open** (consistent with `proxy_not_found`). An
    unimplemented/unknown runtime degrades to "aligned" (design_workflows §1.2), never propagates to brick the hook.
    (Recorded in the epic checklist + the 2026-06-26 workweave/Avengers-Pro discussion.)

## Acceptance (definition of done)

| Test                         | Fixture                                                         | Assertion                                                 | Test File                                      |
| ---------------------------- | --------------------------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------- |
| Override dispatches to codex | `SupervisorConfig` codex override + mock `CodexHeadlessInvoker` | dispatch arm = codex, not `run_claude_session`            | `tests/src/policy/semantic/test_supervisor.py` |
| Default unchanged            | no override                                                     | claude arm, byte-identical to T3                          | `test_supervisor.py`                           |
| Verdict parses codex stdout  | codex `HeadlessResult.stdout` sample                            | `parse_supervisor_verdict` returns the verdict            | `test_supervisor.py` / `test_verdict.py`       |
| Bad/unknown lane fails open  | invalid override                                                | verdict = aligned, no exception, hook not bricked         | `test_supervisor.py`                           |
| Single usage emission        | codex dispatch                                                  | exactly one `emit_usage_for_session_result`               | `test_supervisor.py`                           |
| Blind/transfer-fed only      | --                                                              | headless `codex exec`; no codex hook install / enrollment | code review + assertion                        |

## Non-goals

- **No Codex hooks or policy enforcement** -- blind/transfer-fed only; do not expand to supervised-Codex-executor.
- No Claude-UUID resume (codex exec is transfer-fed/blind).
- No *general* consumer-lane manifest persistence (T1b) -- the choice rides **only** the narrow `SupervisorConfig` field
  (itself already session-persisted, like any supervisor setting).
- No fallback between lanes -- subscription-exhaustion fail-open is **T7**, downstream of this card.

## Depends on

T1a (resolver), T2 (codex/chatgpt backend + reachability), T3 (lane-driven supervisor seam) -- all **done**.
