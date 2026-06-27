# T4 execution checklist -- Codex-exec supervisor lane

**Epic**: `docs/board/doing/epic_consumer_lanes/` (lane contract; T3 -> T4 carry-forward seams).
**Card**: `card.md` (scope, non-goals, acceptance).
**Branch**: `codex_exec_supervisor_lane` (opened 2026-06-26; `git mv` from `todo/`).

## Current focus

Activate the **inert codex seam** T3 left behind: declare a codex candidate lane, add a narrow runtime override to
`SupervisorConfig`, implement the `codex` arm of `_dispatch_supervisor`, and make the now-reachable non-claude paths
**fail-open** (the supervisor's contract -- design_workflows §1.2). Default (no override) must stay **byte-identical to
T3** (`claude_code` lane).

**Verified seam (2026-06-26, against shipped code):**

- **Lane override gating** -- `resolve_lane(consumer, override=...)` (`core/lanes.py:133`) returns the override **only if
  it is in `valid_lanes(consumer)`**, else raises `LaneError` (`:145`). `valid_lanes` = `default_lane + allowed_lanes`
  filtered by floor + reachability (`:111`). `SUPERVISOR_CONSUMER` (`supervisor.py:113`) declares **no `allowed_lanes`**,
  so a codex override fails closed today. **A codex candidate must be added** (Phase 1). `Lane(runtime_id="codex",
  backend_id="chatgpt", model=<non-empty>)` **is** constructible + valid: `chatgpt.reachable_via=("codex",)` (T2) passes
  `_reachable`, and codex is a `tool_agent` satisfying the `tool_agent` floor.
- **Plan reaches the model via the prompt, not resume (codex has no `--resume`)** -- the Claude arm passes
  `resume_id=resolved.resume_id` (`supervisor.py:524`); the plan lives in that forked conversation (CLI-Fork
  Supervision, design_workflows §1.2). The prompt literally says "the approved plan **in your context**"
  (`supervisor.py:55`). **But** `run_supervisor_check` already prepends `_PLAN_OVERRIDE_PREAMBLE` to `prompt` when
  `load_plan_override(config)` resolves (`supervisor.py:601-603`). So for codex: plan present in `prompt` iff
  `plan_override_path` resolves; **no plan otherwise** (Phase 2 must fail open in that case).
- **Codex emits through the invoker, not the Claude seam** -- `CodexHeadlessInvoker._emit -> _emit_codex` auto-emits
  **one** `emit_codex_usage` (route `codex_exec`, tokens-only) **and** one `record_upstream_operation` whenever
  `request.attribution` is set (`core/invoker/codex.py:112,215-258`). `prepare_codex_request` **requires** `attribution`
  and stamps `billing_mode=preflight.billing_mode` (`:156,211`). **Do NOT also call `emit_usage_for_session_result`**
  (the Claude arm's sole emitter at `supervisor.py:537`) -- that double-emits.
- **Preflight is a ~20s probe by default** -- `prepare_codex_request` needs a `CodexPreflight` (`codex.py:155`);
  `preflight_codex`/`assert_codex_ready` default `run_doctor=True` (~20s `codex doctor`); `run_doctor=False` skips it
  (`codex_preflight.py:165,182,225`). A per-Write/Edit hook must use `run_doctor=False` and fail open on preflight
  failure.
- **`SupervisorConfig` round-trips + validates in `__post_init__`** -- dacite deserializes it "on every manifest read /
  session set / start / fork" and runs `__post_init__`, which already rejects bad `checker_effort`/`supervisor_effort`
  (auto-wrapped to `InvalidOverrideValueError` on the strict override path) (`session/models.py:149,~195`). A new runtime
  field both persists and has an obvious validation home.
- **Result-type bridge + the `runtime_is_error` trap (review claim 7).** `_dispatch_supervisor` returns a
  `SessionResult`, but `CodexHeadlessInvoker.run` returns a **`HeadlessResult`** -- the codex arm is the first seam in the
  codebase to bridge the two. `run_supervisor_check` reads `success`/`error`/`returncode`/`timed_out` (fail-open gate +
  classification, `supervisor.py:627-637`), `run_id`/`parent_run_id`/`root_run_id` (telemetry on **both** the fail-open
  **and** success paths, `:638-655`), and `stdout` (verdict). **Trap:** `HeadlessResult.success` **and**
  `SessionResult.success` are **returncode-only** -- both deliberately ignore `runtime_is_error` (`types.py:106-109`,
  `session_runner.py:69-72`). Codex sets `runtime_is_error=True` on a failed turn **at exit 0**, so a naive copy skips the
  runtime-failure gate and parses empty stdout -- logging a real codex failure as "unparseable output" (and miscounting
  the supervisor-health streak). The adapter MUST fold `runtime_is_error` into the failure signal (set `error`) so
  `success` becomes False.
- Assembly (shipped): `CodexHeadlessInvoker.run` (`core/invoker/codex.py:68`, normalizes final text to
  `HeadlessResult.stdout`); `prepare_codex_request` (`:152`); `parse_supervisor_verdict(response: str)` (`verdict.py:86`)
  \+ `parse_supervisor_verdict_with_status` (`:53`, the `parsed` flag for error-vs-inconclusive). The supervisor `prompt`
  is **already complete** (`SUPERVISOR_PROMPT` + the plan preamble) -- dispatch it directly (see Decisions).

## Decisions

- [x] **Unsupported-lane failure mode = catch + fail-open** (epic-resolved 2026-06-26, consistent with
  `proxy_not_found`). An unimplemented/unknown/misconfigured runtime degrades to "aligned", never propagates.
- [x] **Prompt framing = dispatch the composed supervisor `prompt` directly** (resolves the card<->checklist fork the
  review flagged). The supervisor prompt is self-contained (`SUPERVISOR_PROMPT` + the `_PLAN_OVERRIDE_PREAMBLE` already
  prepended in `run_supervisor_check`). `compose_codex_initial_message` is the **bridge's transfer-framer**
  (`transfer_body` + a separate `task`) -- the wrong shape here. **Card synced** (Phase 0).
- [x] **Preflight in the hook path = `run_doctor=False` + fail open** (review claim 4). Skip the ~20s `codex doctor`
  probe in the per-Write/Edit hot path; if preflight raises (codex absent / not ready), degrade to "aligned".
- [x] **Override field shape = narrow `supervisor_runtime: str | None`** (epic-decided: T4 rides a narrow
  `SupervisorConfig` field; T1b generalizes). Validated in `__post_init__` against `{"claude_code", "codex"}` --
  precedent: `checker_effort` validation in the same `__post_init__`. The arm maps the string to the declared codex
  `allowed_lane` (a `Lane`, which is what `resolve_lane(override=...)` needs). Additive optional field -- **no
  `SCHEMA_VERSION` bump** (T1b owns the durable binding).
- [x] **Plan-context when no plan resolves = fail open, observable, re-checkable** (user-decided 2026-06-26, review claim
  1). When the codex lane is selected but `load_plan_override(config)` yields nothing (codex has no `--resume`, so the
  plan can only reach it via `plan_override_path`/cascade):
  - **Do not spawn Codex** -- short-circuit before the subprocess (no wasted ~spawn, no empty-plan evaluation).
  - Return a **structured fail-open allow** (`_supervisor_fail_open_decision`), **not** a normal "aligned" verdict, with a
    distinct `failure_type="plan_missing"` (a `configuration_error` flavor) so it is visibly attributed.
  - **Surface in telemetry** (`forge telemetry activity` / the fail-open upstream outcome) -- not a silent no-op.
  - **Re-checkable, never permanently disabled**: the per-check decision is not a persistent disable; the throttle cache
    key already includes the plan fingerprint, so setting `plan_override_path` or `%policy supervisor reload` makes the
    next check re-evaluate and the lane start supervising. Heavier alternative (assemble transfer context from the
    supervisor target via the bridge) stays **deferred** (out of T4's narrow scope).

## Phases

### Phase 0 -- Open the card (this change)

- [x] Branch `codex_exec_supervisor_lane` created from `main`.
- [x] `git mv docs/board/todo/codex_exec_supervisor_lane -> doing/`.
- [x] Author this `checklist.md`; update `card.md` lane line; update epic roster + link-control.
- [x] Sync `card.md` to the review findings (prompt framing, allowed_lanes, emit seam, preflight) so the durable framing
  does not fork from this checklist (review claim 5).

### Phase 1 -- Lane plumbing (candidate + override field)

- [x] **Add the codex candidate to `SUPERVISOR_CONSUMER.allowed_lanes`**
  (`Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")`; backend/model nominal). Verified:
  `test_supervisor_consumer_allows_codex_override` (override resolves; default still `claude_code`); import-time lane
  validation passes (chatgpt reachable via codex, T2).
- [x] **Add `supervisor_runtime` override field to `SupervisorConfig`** (`session/models.py`), validated in
  `__post_init__` against `_SUPERVISOR_RUNTIMES = ("claude_code", "codex")`. Verified: `test_supervisor_runtime_*`
  (none/codex/claude_code valid, bogus rejected) + `test_supervisor_runtime_round_trip` (survives `store.write`/`read`).
- [x] `run_supervisor_check` maps the field to the override `Lane` (`_supervisor_lane_override`) and passes
  `resolve_lane(SUPERVISOR_CONSUMER, override=...)` **inside** the fail-open guard. Done with Phase 2/3 (the wiring needs
  the codex arm + the fail-open boundary to be meaningful). Verified: `test_override_dispatches_to_codex_and_parses_verdict`
  (override -> codex arm) + `test_bad_lane_resolution_fails_open` (LaneError inside the guard).

### Phase 2 -- The `codex` arm of `_dispatch_supervisor`

- [x] Replaced the `raise NotImplementedError` with `_dispatch_codex_supervisor` (the codex arm of `_dispatch_supervisor`):
  - **Preflight (fail-open):** `preflight_codex(run_doctor=False)`; an unready preflight raises
    `_SupervisorRoutingError(failure_type="codex_unavailable")` (caught -> fail-open), never propagates. Verified:
    `test_codex_arm_unready_preflight_raises_routing_error` + `test_preflight_unavailable_fails_open`.
  - **Attribution:** builds one `Attribution(command=usage_command, session=context.session_name)` passed to
    `prepare_codex_request` (which stamps `runtime="codex"` + `billing_mode=preflight.billing_mode`). Verified:
    `test_no_double_emit_on_codex_path` (attribution carries command/session).
  - **Dispatch:** `prepare_codex_request(prompt=..., preflight=..., attribution=..., sandbox="read-only", model=None,
    timeout_seconds=config.timeout_seconds, cwd=resolved.source_cwd)` -> `CodexHeadlessInvoker().run(...)`. **Sandbox is
    `read-only`** (a supervisor inspects, never edits). Verified: `test_codex_arm_dispatches_through_invoker`
    (`sandbox == "read-only"`, `model is None`).
  - **Result (adapt `HeadlessResult` -> `SessionResult`, ALL load-bearing fields):** `_headless_to_session_result` carries
    `stdout`/`stderr`/`returncode`/`timed_out`/`error`/`run_id`/`parent_run_id`/`root_run_id` + tokens/envelope. **Folds
    `runtime_is_error`:** an exit-0 failed turn gets `error` set so the returncode-based `success` gate fires (runtime
    failure, not empty-verdict parse). Verified: `test_headless_to_session_result_maps_fields_and_folds_runtime_error`
    (unit) + `test_runtime_error_at_exit_zero_is_runtime_failure_not_unparseable` (e2e -> `subprocess_error`, ids carried).
- [x] **Plan context:** relies on the existing preamble injection (plan already in `prompt` when `plan_override_path`
  resolves). When no plan resolves, `run_supervisor_check` **fails open WITHOUT spawning codex** (`failure_type="plan_missing"`).
  Verified: `test_plan_absent_fails_open_without_spawning_codex` (preflight + invoker both `assert_not_called`).
- [x] **Verdict unchanged:** `parse_supervisor_verdict_with_status(result.stdout)` consumes codex stdout exactly as claude
  stdout. Verified: `test_override_dispatches_to_codex_and_parses_verdict` (codex `_VALID_VERDICT_STDOUT` -> `parsed=True`,
  decision allow).
- [x] **Blind/transfer-fed only:** headless `codex exec`; no codex hook install, no enrollment, no Claude-UUID resume. The
  arm calls only preflight + `prepare_codex_request` + `run`. Verified: `test_override_dispatches_to_codex_and_parses_verdict`
  asserts `resume_thread_id is None` (no resume); no enrollment/hook-install symbol is referenced by the arm (code review).

### Phase 3 -- Fail-open wiring (the T3 -> T4 carry-forward seams)

- [x] `resolve_lane(SUPERVISOR_CONSUMER, override=...)` now runs **inside** a `try/except LaneError` guard; a bad override
  degrades to `failure_type="configuration_error"` instead of raising uncaught. Verified: `test_bad_lane_resolution_fails_open`.
- [x] The `codex`/unknown arms no longer brick the hook. The dispatch `except _SupervisorRoutingError` now propagates
  `e.failure_type` (`codex_unavailable` for preflight), `LaneError` is caught at resolution (`configuration_error`), and
  plan-absent short-circuits to `plan_missing` -- all converge on `_supervisor_fail_open_decision`. Verified: the four
  fail-open e2e tests (`test_bad_lane_resolution_fails_open`, `test_preflight_unavailable_fails_open`,
  `test_plan_absent_fails_open_without_spawning_codex`, `test_runtime_error_at_exit_zero_is_runtime_failure_not_unparseable`)
  -- each yields `fail_open=True` and no exception escapes `run_supervisor_check`.

### Phase 4 -- Single usage emission via the invoker (NOT the Claude seam)

- [x] The codex arm builds the `HeadlessRequest` with **exactly one** `Attribution`; `CodexHeadlessInvoker` emits the
  usage event (route `codex_exec`, `billing_mode` from the preflight). The arm does **not** call
  `emit_usage_for_session_result` (the Claude seam), so there is no double-count. Verified: `test_no_double_emit_on_codex_path`
  (`emit_usage_for_session_result` `assert_not_called`; the request carries an `Attribution(command="supervisor")`).
- [~] **Upstream-operation label = known limitation, deferred to T5.** `_emit_codex` hardcodes
  `record_upstream_operation(operation="workflow.worker")` (`codex.py:249`), so a codex supervisor's upstream outcome is
  mislabeled `workflow.worker` instead of a policy/supervisor operation. **Decision:** accept for T4 -- relabeling needs the
  **shared invoker's** emit contract to accept an operation (it affects every invoker consumer, e.g. review workers), which
  is T5's telemetry scope, not T4's narrow lane scope. The mislabel is non-fatal: tokens + `billing_mode` are correct, only
  the `operation` string is wrong; no double-emit, no fail-open impact. Documented in `_dispatch_codex_supervisor`'s
  docstring and carried to the change log + impl_notes. **Carry-forward to T5.**

### Phase 5 -- Tests (card acceptance + review-driven additions)

| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Codex candidate lane resolves | `SUPERVISOR_CONSUMER` + codex override | `resolve_lane(override=codex_lane)` returns it, no `LaneError` | `tests/src/policy/semantic/test_supervisor.py` / `test_lanes.py` |
| Override dispatches to codex | codex override + mock `CodexHeadlessInvoker` | dispatch arm = codex, not `run_claude_session` | `test_supervisor.py` |
| Default unchanged | no override | claude arm, byte-identical to T3 | `test_supervisor.py` |
| `SupervisorConfig` field round-trips + rejects bad value | manifest read / `session set` | field persists; invalid runtime raises (`InvalidOverrideValueError`) | `tests/src/session/test_models.py` / `test_supervisor.py` |
| Verdict parses codex stdout | codex `HeadlessResult.stdout` sample | `parse_supervisor_verdict` returns the verdict | `test_supervisor.py` / `test_verdict.py` |
| Bad/unknown lane fails open | invalid override | verdict=aligned, no exception, hook not bricked | `test_supervisor.py` |
| Preflight failure fails open | codex preflight raises | verdict=aligned, hook not bricked; no ~20s probe (`run_doctor=False`) | `test_supervisor.py` |
| Plan-absent fails open | codex lane, no `plan_override_path` | verdict=aligned; codex not evaluated against empty plan | `test_supervisor.py` |
| Codex runtime failure classified right | codex `runtime_is_error=True`, exit 0 | `success=False` -> runtime fail-open (not "unparseable"); `run_id`/`parent`/`root` carried | `test_supervisor.py` |
| Single usage emission | codex dispatch | **zero** `emit_usage_for_session_result` (no double-count) | `test_no_double_emit_on_codex_path` |
| Upstream label (T5) | codex dispatch | **deferred:** invoker hardcodes `workflow.worker` -- documented limitation, carried to T5 | n/a (see Phase 4) |
| Blind/transfer-fed only | codex override | no resume thread id; arm calls only preflight/prepare/run | `test_override_dispatches_to_codex_and_parses_verdict` |

- [x] All acceptance rows green **except** "Upstream label" (deferred to T5 by decision -- see Phase 4). The 8 new T4
  tests + the 2 Phase-1 tests cover every other row.
- [x] Existing supervisor suite stays green -- default (no-override) path unchanged. Verified:
  `uv run pytest tests/src/policy/semantic/ tests/src/session/test_store.py` -> **269 passed**
  (`test_supervisor.py`: 103 passed).

### Phase 6 -- Docs + closeout

- [ ] design.md / design_appendix.md §G: note the supervisor lane now admits a codex runtime arm (first non-claude
  consumer lane). Coordinate with the epic's still-open §G/§3.6.12 sync debt.
- [ ] `make pre-commit` clean (ruff, black, isort, mypy, pyright, mdformat, gitleaks).
- [ ] Integration: the supervisor is a hook path -- run `tests/integration/docker/test_supervisor_e2e.py` before
  finishing (CLAUDE.md: hooks/supervisor changes need the integration tier, not just unit). A real codex E2E (codex
  installed + a chatgpt login) is a stretch goal, not a gate -- the unit assertions mock the invoker.
- [ ] change_log.md entry (Goal / Key changes / Verification); promote durable lessons to `impl_notes.md` after review.
- [ ] Update epic roster T4 -> done; `git mv doing/ -> done/`.

## Blockers / deferred

- **No Codex hooks or policy enforcement** (card non-goal) -- blind/transfer-fed only; do not expand to a
  supervised-Codex-executor.
- **No general consumer-lane manifest persistence** -- that is T1b. T4's choice rides only the narrow `SupervisorConfig`
  field.
- **No fallback between lanes** -- subscription-exhaustion fail-open is T7 (`proposed/`), downstream of this card. (A
  plan-absent or preflight-failed codex run fails open to *aligned*; it does **not** fall back to the claude lane -- that
  stickier degradation is T7.)
