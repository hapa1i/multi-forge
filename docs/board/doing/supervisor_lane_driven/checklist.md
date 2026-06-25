# Checklist: T3 -- Supervisor becomes lane-driven (Claude default, byte-identical)

**Card**: `card.md` (this dir). **Epic**: `docs/board/doing/epic_consumer_lanes/`. **Branch**: `supervisor_lane_driven`
(off `main` @ `b84e2462`, the T1a merge).

## Current focus

Refactor `run_supervisor_check` (`src/forge/policy/semantic/supervisor.py:412-564`) so the supervisor is a `Consumer`
whose lane is resolved (T1a `resolve_lane`) then dispatched through a thin, runtime-keyed seam. The `claude_code` arm is
the existing path moved **verbatim**; the run must be **byte-identical to today**. No durable schema; no Codex (T4).

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
- Callers of `run_supervisor_check`: `invoke_supervisor` (`:578`) and the shadow auditor (`usage_command="supervisor-shadow"`).
  Both flow through the seam; verify neither double-emits.

## Decisions (resolve in this ticket; flagged for review)

- [x] **Seam lives in `supervisor.py`, not a new module** -- forced by the patch surface (above). Generalization to a
  shared cross-consumer dispatcher is T1b/T6.
- [x] **Routing moves into the `claude_code` arm; fail-open via a typed `_SupervisorRoutingError`.** The arm owns
  routing -> model/env -> dispatch -> emit (all runtime-specific; Codex transport differs in T4). On
  `resolve_subprocess_routing` raising, the arm logs the **identical** line and raises `_SupervisorRoutingError`;
  `run_supervisor_check` catches it and returns the **identical** `proxy_not_found` fail-open decision.
- [x] **Nominal backend = `anthropic-direct`, model = `opus`** on the supervisor's default lane. **Only `runtime_id` is
  load-bearing in T3** (it selects the dispatch arm); the `claude_code` arm still derives `base_url` (transport) and the
  `opus` pin dynamically per the byte-identical contract, so `backend_id`/`model` are not yet consulted. T2 makes backend
  load-bearing; document this in code + flag for reviewer. (No single backend is "correct" -- a proxied supervisor routes
  through whatever proxy -- so a documented nominal id over today's catalog is the honest T3 choice.)
- [x] **Dispatch params passed as explicit kwargs** (not a `params` dataclass) for a thin T3 seam; a params bundle is
  deferred to T4 if the Codex arm wants it.

## Phase 1 -- Seam + consumer (`src/forge/policy/semantic/supervisor.py`)

- [ ] Import `Consumer`, `Lane`, `LaneError`, `resolve_lane` from `forge.core.lanes`.
- [ ] Module-level `SUPERVISOR_CONSUMER = Consumer(id="supervisor", capability_floor="tool_agent",
  default_lane=Lane("claude_code", "anthropic-direct", "opus"))`, with a comment stating backend/model are nominal in T3.
  (Pure construction -- dict lookups only, no I/O; safe at import.)
- [ ] `_SupervisorRoutingError(Exception)` -- internal control-flow signal for a failed claude-arm routing resolution.
- [ ] `_dispatch_supervisor(lane, *, prompt, config, context, resolved, usage_command) -> SessionResult`: switch on
  `lane.runtime_id` -- `claude_code` -> `_dispatch_claude_supervisor(...)`; `codex` -> `NotImplementedError` (T4);
  else -> `LaneError`.
- [ ] `_dispatch_claude_supervisor(...)`: the **verbatim** body of `:468-530` (routing/model/env, `spawn_env`,
  `track_verb_cost` + `run_claude_session`, `emit_usage_for_session_result`), raising `_SupervisorRoutingError` instead
  of the inline early-return on routing failure; returns `SessionResult`.

## Phase 2 -- Rewire `run_supervisor_check`

- [ ] Replace the inline routing/dispatch/emit block (`:468-530`) with: `lane = resolve_lane(SUPERVISOR_CONSUMER)` then
  `try: result = _dispatch_supervisor(lane, ...)` / `except _SupervisorRoutingError as e: return SupervisorRun(
  _supervisor_fail_open_decision(str(e), failure_type="proxy_not_found"))`.
- [ ] Leave untouched: the depth guard, `resume_id` guard, `_resolve_resume_target`, prompt composition
  (`:458-466`), the `if not result.success` failure branch (`:532-548`), and the verdict parse + return (`:550-564`).

## Phase 3 -- Tests (`tests/src/policy/semantic/test_supervisor.py`)

New `TestSupervisorLaneDispatch` class; existing tests untouched.

| Test | Fixture | Assertion |
| ---- | ------- | --------- |
| consumer is resolvable | -- | `resolve_lane(SUPERVISOR_CONSUMER)` == `Lane("claude_code","anthropic-direct","opus")`; floor `tool_agent` |
| single emission, success | patch `forge.core.usage.emit_usage_for_session_result`, `run_claude_session` ok | emit called exactly once |
| single emission, failed run | `run_claude_session` returns `returncode=1` | emit still called exactly once (before the failure branch) |
| codex arm stubbed | call `_dispatch_supervisor(Lane("codex",...), ...)` | raises `NotImplementedError` |
| existing dispatch suite | -- | `test_proxied_*`, `test_direct_mode_*`, `test_proxy_not_found_*`, `test_unparseable_*` pass unchanged |

## Phase 4 -- Verify + closeout

- [ ] `uv run pytest tests/src/policy/semantic/test_supervisor.py -v` green (existing + new).
- [ ] Adversarial byte-identical verification (workflow): skeptics try to find any divergence in control flow, emit
  count, env/kwargs, fail-open message, or log lines; fix anything real.
- [ ] Grep `run_supervisor_check` callers (`invoke_supervisor`, shadow auditor) -> confirm no double-emit / no behavior
  change. Run the shadow suite (`tests/src/policy/semantic/test_shadow*.py` if present).
- [ ] `mypy` + `pyright` on `supervisor.py`; `make pre-commit` clean.
- [ ] **Design-doc sync** (epic checklist item): add a brief note to `design_appendix.md` §G that the supervisor consumer
  resolves a default lane then dispatches (transport still via `resolve_subprocess_routing`). Keep design.md §3.6.12
  narrative deferred until >1 consumer is wired (T1b/T6) -- record as checklist debt if not done here.
- [ ] `change_log.md` entry; flip the epic roster T3 -> done note (stays `doing` until merge).
- [ ] After PR merges to `main`: move `doing/supervisor_lane_driven/` -> `done/`; epic roster T3 -> done.

## Non-goals (from card)

- No Codex dispatch (T4); the `codex` arm is `NotImplementedError`.
- No durable schema / stored override (T1b); the lane is the computed default only.
- No new `SupervisorConfig` field (T4 adds the narrow runtime override).
