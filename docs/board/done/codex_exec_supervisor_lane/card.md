# T4 -- Codex-exec supervisor lane

**Epic**: `docs/board/doing/epic_consumer_lanes/` -- read the epic for the shared lane contract (runtime x backend x
model; resolve once, frozen). This is the **headline capability demo**: the first consumer placed on a *non-Claude*
runtime, proving the lane abstraction admits a real new lane swappably.

**Lane**: `done/` (opened 2026-06-26 on branch `codex_exec_supervisor_lane`; shipped via PR #55, `40b7a1b6`; moved
`doing/ -> done/` at closeout 2026-06-27).

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
- The supervisor `prompt` is **already a complete, self-contained instruction** (`SUPERVISOR_PROMPT` + the
  `_PLAN_OVERRIDE_PREAMBLE` that `run_supervisor_check` prepends when a plan resolves), so the codex arm **dispatches it
  directly**. (`compose_codex_initial_message` is the bridge's *transfer-framer* -- `transfer_body` + a separate `task`
  -- the wrong shape for the supervisor; not used here.)

## Scope (concrete changes)

- **Declare a codex candidate lane.** `SUPERVISOR_CONSUMER` (`supervisor.py:113`) has **no `allowed_lanes`** today, so
  `resolve_lane(override=codex_lane)` would raise `LaneError`. Add
  `Lane(runtime_id="codex", backend_id="chatgpt", model=...)` to its `allowed_lanes` (constructible + reachable:
  `chatgpt.reachable_via=("codex",)` from T2).
- **`SupervisorConfig` gains a narrow runtime override** (`session/models.py:149` -- no `runtime` field today; validate
  in `__post_init__`, the existing seam for `checker_effort`). Default resolves to the `claude_code` lane
  (byte-identical to T3); an override selects `codex`.
- **Implement the `codex` arm of `_dispatch_supervisor`** (`supervisor.py:469` raises `NotImplementedError` today): read
  a **cached** `CodexPreflight` (see preflight bullet below), `prepare_codex_request` with the composed `prompt` + one
  `Attribution`, dispatch via `CodexHeadlessInvoker` (sandbox `read-only` -- a supervisor inspects, never edits), parse
  via `parse_supervisor_verdict(stdout)`. **Adapt the invoker's `HeadlessResult` into the `SessionResult`** the caller
  expects, carrying run/telemetry fields and **folding `runtime_is_error`** (a Codex turn can fail at exit 0) into the
  failure signal, so a runtime failure isn't misread as unparseable output. When no approved plan resolves, **fail
  open** (codex has no `--resume` context). **All setup failures** (cache miss, request shaping) degrade to
  `codex_unavailable` fail-open, never an uncaught raise.
- **Preflight is cached, never probed in the hook** (revised after 2026-06-27 review -- the original `run_doctor=False`
  plan was inert for the `chatgpt` backend this lane declares). `run_doctor=False` sees only env auth, so a
  `codex login --device-auth` (ChatGPT subscription) user would fail closed forever even though `codex exec` runs. A
  setup-time command (`forge runtime preflight codex`) runs the full `run_doctor=True` preflight once and writes a
  secret-free disk cache (`core/runtime/codex_preflight_cache.py`); the hook reads it with cheap `stat()`s (codex binary
  \+ `$CODEX_HOME/auth.json` mtime + TTL invalidation), **no `codex doctor` in the hot path**. Cache miss/stale/unready
  -> fail open with a "run `forge runtime preflight codex`" hint; a stale-positive self-corrects via the runtime-failure
  fail-open.
- **Single usage emission -- via the invoker, not the Claude seam.** The codex request carries **one** `Attribution`;
  `CodexHeadlessInvoker` then emits **one** `emit_codex_usage` (`billing_mode` from the preflight). Do **not** also call
  `emit_usage_for_session_result` (the Claude arm's emitter) -- that double-emits. Verify the invoker's built-in
  `record_upstream_operation` does not mislabel the supervisor as a `workflow.worker`. Ties to T5.
- **Fail-open wiring (the T3 -> T4 carry-forward seams -- see epic `card.md`).** These flip live the instant the codex
  arm + override exist; the supervisor's contract is fail-open (design_workflows §1.2):
  - Move `resolve_lane(SUPERVISOR_CONSUMER, override=...)` **inside** the `try/except _SupervisorRoutingError`
    (`supervisor.py:603`), or pre-validate + degrade -- a bad override must not crash the policy hook.
  - **Unsupported-lane failure mode is DECIDED: catch + fail-open** (consistent with `proxy_not_found`). An
    unimplemented/unknown runtime degrades to "aligned" (design_workflows §1.2), never propagates to brick the hook.
    (Recorded in the epic checklist + the 2026-06-26 workweave/Avengers-Pro discussion.)

## Acceptance (definition of done)

| Test                           | Fixture                                                         | Assertion                                                                   | Test File                                      |
| ------------------------------ | --------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------- |
| Override dispatches to codex   | `SupervisorConfig` codex override + mock `CodexHeadlessInvoker` | dispatch arm = codex, not `run_claude_session`                              | `tests/src/policy/semantic/test_supervisor.py` |
| Default unchanged              | no override                                                     | claude arm, byte-identical to T3                                            | `test_supervisor.py`                           |
| Verdict parses codex stdout    | codex `HeadlessResult.stdout` sample                            | `parse_supervisor_verdict` returns the verdict                              | `test_supervisor.py` / `test_verdict.py`       |
| Bad/unknown lane fails open    | invalid override                                                | verdict = aligned, no exception, hook not bricked                           | `test_supervisor.py`                           |
| Preflight failure fails open   | codex preflight raises                                          | verdict = aligned, hook not bricked; `run_doctor=False`                     | `test_supervisor.py`                           |
| Plan-absent fails open         | codex lane, no resolvable plan                                  | verdict = aligned; not evaluated against an empty plan                      | `test_supervisor.py`                           |
| Runtime field round-trips      | manifest read / `session set`                                   | field persists via dacite; invalid value rejected                           | `test_models.py` / `test_supervisor.py`        |
| Codex runtime failure (exit 0) | `runtime_is_error=True` stream                                  | classified as runtime failure (fail-open), not unparseable; run ids carried | `test_supervisor.py`                           |
| Single usage emission          | codex dispatch                                                  | one `emit_codex_usage`; zero `emit_usage_for_session_result`                | `test_supervisor.py`                           |
| Blind/transfer-fed only        | --                                                              | headless `codex exec`; no codex hook install / enrollment                   | code review + assertion                        |

## Non-goals

- **No Codex hooks or policy enforcement** -- blind/transfer-fed only; do not expand to supervised-Codex-executor.
- No Claude-UUID resume (codex exec is transfer-fed/blind).
- No *general* consumer-lane manifest persistence (T1b) -- the choice rides **only** the narrow `SupervisorConfig` field
  (itself already session-persisted, like any supervisor setting).
- No fallback between lanes -- subscription-exhaustion fail-open is **T7**, downstream of this card.

## Depends on

T1a (resolver), T2 (codex/chatgpt backend + reachability), T3 (lane-driven supervisor seam) -- all **done**.
