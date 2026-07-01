# T3 -- Supervisor becomes lane-driven (Claude default, byte-identical)

**Epic**: `docs/board/done/epic_consumer_lanes/` -- read the epic for the shared lane contract.

**Lane**: `todo/` (accepted, first wave). No execution branch open yet.

**Proves**: the T1a resolver drives a real consumer on the existing case, changing nothing observable.

## Goal

Refactor `run_supervisor_check` so the supervisor is a `Consumer` whose lane is resolved (T1a) then dispatched. The
default lane is `claude -p` and the run must be **byte-identical to today**. No durable schema -- the lane is the
computed default, not a stored override.

## Byte-identical contract (what must not change) -- `src/forge/policy/semantic/supervisor.py:468-519`

- `config.direct` true -> `base_url=None`, `model=None`, `unset_env_vars=None`.
- else ->
  `base_url = resolve_subprocess_routing(explicit_base_url=config.base_url, explicit_proxy=config.proxy, require_route=False).base_url`;
  on raise -> fail-open `proxy_not_found` decision (unchanged).
- `model = "opus" if base_url else None`; `unset_env_vars = _CLAUDE_MODEL_PIN_ENV_VARS if base_url else None`.
- dispatch ->
  `run_claude_session(prompt, resume_id, fork_session, model, reasoning_effort=config.supervisor_effort, base_url, direct, timeout_seconds, cwd, extra_env={FORGE_COMMAND_VAR: "supervisor", ...}, unset_env_vars)`.
- `emit_usage_for_session_result(...)` stays the **SOLE** usage emitter for the run (`:521`) -- no double-emit, no drop,
  failed runs still recorded.
- prompt composition (`SUPERVISOR_PROMPT.format(...)` + optional `_PLAN_OVERRIDE_PREAMBLE`, `:458-466`) unchanged.

## Scope

- Introduce a `supervisor` `Consumer` (capability floor = tool-agent; default runtime = `claude_code`).
- Introduce a thin **dispatch seam**: `dispatch(lane, prompt, params) -> result` (result exposes `.stdout`). T3
  implements only the `claude_code` arm, delegating to the existing `run_claude_session` path verbatim. (T4 adds the
  `codex` arm.)
- `run_supervisor_check` resolves the lane (the default), then calls the seam; all routing/model/env logic above moves
  behind the `claude_code` arm unchanged.
- `parse_supervisor_verdict(result.stdout)` is already runtime-neutral (`verdict.py:86`) -- no change.

## Acceptance (definition of done)

| Test                          | Fixture                             | Assertion                                                                                                     | Test File                                      |
| ----------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Default lane == today, proxy  | proxy configured, `direct=False`    | dispatch args match pre-refactor: `base_url` set, `model="opus"`, `unset_env_vars=_CLAUDE_MODEL_PIN_ENV_VARS` | `tests/src/policy/semantic/test_supervisor.py` |
| Default lane == today, direct | `config.direct=True`                | `base_url=None`, `model=None`, `unset_env_vars=None`; `run_claude_session` called                             | `tests/src/policy/semantic/test_supervisor.py` |
| Fail-open preserved           | `resolve_subprocess_routing` raises | returns the `proxy_not_found` fail-open decision; no dispatch                                                 | `tests/src/policy/semantic/test_supervisor.py` |
| Single usage emission         | one supervisor run                  | `emit_usage_for_session_result` called exactly once (including failed runs)                                   | `tests/src/policy/semantic/test_supervisor.py` |
| Existing supervisor suite     | --                                  | all current supervisor tests pass unchanged                                                                   | `tests/src/policy/semantic/test_supervisor.py` |

## Non-goals

- No Codex (T4); the `codex` dispatch arm is `NotImplementedError` here.
- No durable schema / stored override (T1b). The lane is the computed default only.
- No new `SupervisorConfig` field yet (T4 adds the narrow runtime field).

## Depends on

T1a.
