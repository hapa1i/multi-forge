# Checklist: T3 -- Supervisor becomes lane-driven (Claude default, byte-identical)

**Card**: `card.md` (this dir). **Epic**: `docs/board/done/epic_consumer_lanes/`. **Branch**: `supervisor_lane_driven`
(off `main` @ `b84e2462`, the T1a merge).

## Current focus

**Done -- shipped via PR #52 (`e66490af` on `main`); card closed out.** `run_supervisor_check` resolves
`SUPERVISOR_CONSUMER` via `resolve_lane` then dispatches through `_dispatch_supervisor`; the `claude_code` arm is the
pre-T3 path moved verbatim. 94 supervisor tests (89 existing unchanged + 5 new) + 215 `policy/semantic` pass;
mypy/pyright clean; a 4-lens adversarial byte-diff workflow returned **BYTE_IDENTICAL_HOLDS, 0 real divergences**. Lane
move done; epic roster T3 -> done.

## Verified touchpoints (2026-06-25 sweep, post-T1a)

- Dispatch block to relocate: `supervisor.py:468-519` (routing -> model/env) + `:506-519` (`track_verb_cost` +
  `run_claude_session`) + `:522-530` (`emit_usage_for_session_result`, the **SOLE** emitter).
- `run_claude_session` returns `SessionResult` (`core/reactive/session_runner.py:37`); `.stdout` is what
  `parse_supervisor_verdict_with_status` consumes (`verdict.py`, runtime-neutral -- no change).
- Resolver API: `Lane(runtime_id, backend_id, model)`, `Consumer(id, capability_floor, default_lane, allowed_lanes)`,
  `resolve_lane(consumer, *, override=None)` (`core/lanes.py`). Runtime ids: `claude_code` is a `tool_agent` in
  `RUNTIMES`; `core_llm` is `single_shot`. Backend ids that resolve: `anthropic-direct`, `anthropic-passthrough`,
  `openrouter`, `litellm-*` (`backend/sources.py:271-358`).
- **Patch-surface constraint (load-bearing)**: every existing test patches
  `forge.policy.semantic.supervisor.{run_claude_session,resolve_subprocess_routing}`. The seam MUST live in
  `supervisor.py` and call those module-globals, or the patches miss and existing tests break. `track_verb_cost` /
  `emit_usage_for_session_result` are **local** imports -> patched at source (`forge.core.usage.*`,
  `forge.core.reactive.cost_tracking.*`).
- Existing dispatch tests already covering 4/5 acceptance rows: `test_proxied_supervisor_uses_proxy_opus_tier_*`
  (`:569`), `test_direct_mode_skips_routing_resolver` (`:603`), `test_proxy_not_found_is_structural_fail_open` (`:624`),
  `test_unparseable_response_is_structural_fail_open` (`:641`). Must stay green **unchanged**.
- Callers of `run_supervisor_check`: `invoke_supervisor` (`:578`) and the shadow auditor
  (`usage_command="supervisor-shadow"`). Both flow through the seam; verify neither double-emits.

## Decisions (resolve in this ticket; flagged for review)

- [x] **Seam lives in `supervisor.py`, not a new module** -- forced by the patch surface (above). Generalization to a
  shared cross-consumer dispatcher is T1b/T6.
- [x] **Routing moves into the `claude_code` arm; fail-open via a typed `_SupervisorRoutingError`.** The arm owns
  routing -> model/env -> dispatch -> emit (all runtime-specific; Codex transport differs in T4). On
  `resolve_subprocess_routing` raising, the arm logs the **identical** line and raises `_SupervisorRoutingError`;
  `run_supervisor_check` catches it and returns the **identical** `proxy_not_found` fail-open decision.
- [x] **Nominal backend = `anthropic-direct`, model = `opus`** on the supervisor's default lane. **Only `runtime_id` is
  load-bearing in T3** (it selects the dispatch arm); the `claude_code` arm still derives `base_url` (transport) and the
  `opus` pin dynamically per the byte-identical contract, so `backend_id`/`model` are not yet consulted. T2 makes
  backend load-bearing; document this in code + flag for reviewer. (No single backend is "correct" -- a proxied
  supervisor routes through whatever proxy -- so a documented nominal id over today's catalog is the honest T3 choice.)
- [x] **Dispatch params passed as explicit kwargs** (not a `params` dataclass) for a thin T3 seam; a params bundle is
  deferred to T4 if the Codex arm wants it.

## Phase 1 -- Seam + consumer (`src/forge/policy/semantic/supervisor.py`)

- [x] Import `Consumer`, `Lane`, `LaneError`, `resolve_lane` from `forge.core.lanes` (+ `SessionResult`).
- [x] Module-level
  `SUPERVISOR_CONSUMER = Consumer(id="supervisor", capability_floor="tool_agent", default_lane=Lane("claude_code", "anthropic-direct", "opus"))`,
  with a comment stating backend/model are nominal in T3. (Pure construction -- dict lookups only, no I/O; safe at
  import; verified no cycle.)
- [x] `_SupervisorRoutingError(Exception)` -- internal control-flow signal for a failed claude-arm routing resolution.
- [x] `_dispatch_supervisor(lane, *, prompt, config, context, resolved, usage_command) -> SessionResult`: switch on
  `lane.runtime_id` -- `claude_code` -> `_dispatch_claude_supervisor(...)`; `codex` -> `NotImplementedError` (T4); else
  -> `LaneError`.
- [x] `_dispatch_claude_supervisor(...)`: the **verbatim** body (routing/model/env, `spawn_env`, `track_verb_cost` +
  `run_claude_session`, `emit_usage_for_session_result`), raising `_SupervisorRoutingError` instead of the inline
  early-return on routing failure; returns `SessionResult`. (Byte-diff confirmed verbatim.)
- [x] **T3 local review**: commented that the `codex`/unknown arms are unreachable via `run_supervisor_check` in T3
  (only direct unit calls reach them, since `resolve_lane` takes no override). The three forward-looking seams that flip
  live in T4 -- `resolve_lane` outside the fail-open guard, unsupported-lane fail-loud-vs-open, import-time `Lane`
  validation -- are recorded in epic `card.md` ("T3 -> T4 carry-forward seams") with the open decision in the epic
  checklist's Decisions owed.

## Phase 2 -- Rewire `run_supervisor_check`

- [x] Replaced the inline routing/dispatch/emit block with: `lane = resolve_lane(SUPERVISOR_CONSUMER)` then
  `try: result = _dispatch_supervisor(lane, ...)` /
  `except _SupervisorRoutingError as e: return SupervisorRun( _supervisor_fail_open_decision(str(e), failure_type="proxy_not_found"))`.
- [x] Left untouched: the depth guard, `resume_id` guard, `_resolve_resume_target`, prompt composition, the
  `if not result.success` failure branch, and the verdict parse + return. (Lens 1+4 confirmed character-identical.)

## Phase 3 -- Tests (`tests/src/policy/semantic/test_supervisor.py`)

New `TestSupervisorLaneDispatch` class; existing tests untouched.

| Test                        | Fixture                                                                         | Assertion                                                                                                  |
| --------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| consumer is resolvable      | --                                                                              | `resolve_lane(SUPERVISOR_CONSUMER)` == `Lane("claude_code","anthropic-direct","opus")`; floor `tool_agent` |
| single emission, success    | patch `forge.core.usage.emit_usage_for_session_result`, `run_claude_session` ok | emit called exactly once                                                                                   |
| single emission, failed run | `run_claude_session` returns `returncode=1`                                     | emit still called exactly once (before the failure branch)                                                 |
| codex arm stubbed           | call `_dispatch_supervisor(Lane("codex",...), ...)`                             | raises `NotImplementedError`                                                                               |
| existing dispatch suite     | --                                                                              | `test_proxied_*`, `test_direct_mode_*`, `test_proxy_not_found_*`, `test_unparseable_*` pass unchanged      |

## Phase 4 -- Verify + closeout

- [x] `uv run pytest tests/src/policy/semantic/test_supervisor.py` green: 94 passed (89 existing unchanged + 5 new).
- [x] Adversarial byte-identical verification (4-lens workflow `verify-t3-byte-identical`): control-flow / emit+cost /
  dispatch-args / blast-radius, each byte-diffing against `main` -> **BYTE_IDENTICAL_HOLDS, 0 real divergences**.
  Nothing to fix.
- [x] `run_supervisor_check` callers confirmed: `invoke_supervisor` (`supervisor.py:667`) + shadow auditor
  (`shadow_runner.py:142`, `usage_command="supervisor-shadow"`). Both route through the seam -> single-emit. 215
  `tests/src/policy/semantic` pass (incl. shadow).
- [x] `mypy` + `pyright` clean on changed source. `make pre-commit` clean.
- [x] **Design-doc sync**: `design_appendix.md` §G consumer-lane layering note added. **Debt (deferred):** design.md
  §3.6.12 narrative left unchanged -- the supervisor is one byte-identical consumer; defer the §3.6.12 lane paragraph to
  T1b/T6 when >1 consumer is wired and a durable binding exists. (Epic design-doc-sync item stays open for that.)
- [x] `change_log.md` entry added (2026-06-25, newest-first).
- [x] PR #52 merged to `main` (`e66490af`); card moved `doing/` -> `done/`; epic roster T3 -> done (2026-06-25).

## Non-goals (from card)

- No Codex dispatch (T4); the `codex` arm is `NotImplementedError`.
- No durable schema / stored override (T1b); the lane is the computed default only.
- No new `SupervisorConfig` field (T4 adds the narrow runtime override).
