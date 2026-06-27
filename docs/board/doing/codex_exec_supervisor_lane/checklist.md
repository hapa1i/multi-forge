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
- [ ] **Override field shape.** *Recommend* a narrow `supervisor_runtime: str | None` on `SupervisorConfig`, validated
  in `__post_init__` against a small vocabulary (`{"claude_code", "codex"}`) -- precedent: `checker_effort` validation in
  the same `__post_init__`. The arm maps the string to the declared codex `allowed_lane` (a `Lane`, which is what
  `resolve_lane(override=...)` needs). Additive optional field -- **no `SCHEMA_VERSION` bump** (T1b owns the durable
  binding). Confirm name/vocabulary before code.
- [ ] **Plan-context strategy when no plan resolves** (review claim 1, the biggest codex problem). *Recommend*: the codex
  lane relies on the existing `plan_override_path` preamble injection (already in `prompt`); when **no** plan content
  resolves, **fail open (aligned)** -- a supervisor with no plan reference cannot meaningfully evaluate, and codex has no
  resume fallback. Pairs naturally with cascade (which resolves an approved-plan snapshot eagerly). Heavier alternative
  -- assemble transfer context from the supervisor target via the bridge -- is **deferred** (out of T4's "blind/
  transfer-fed, assembly is cheap" scope). Confirm before code.

## Phases

### Phase 0 -- Open the card (this change)

- [x] Branch `codex_exec_supervisor_lane` created from `main`.
- [x] `git mv docs/board/todo/codex_exec_supervisor_lane -> doing/`.
- [x] Author this `checklist.md`; update `card.md` lane line; update epic roster + link-control.
- [x] Sync `card.md` to the review findings (prompt framing, allowed_lanes, emit seam, preflight) so the durable framing
  does not fork from this checklist (review claim 5).

### Phase 1 -- Lane plumbing (candidate + override field)

- [ ] **Add the codex candidate to `SUPERVISOR_CONSUMER.allowed_lanes`** (`supervisor.py:113`):
  `Lane(runtime_id="codex", backend_id="chatgpt", model=<non-empty codex model id; nominal in T4>)`. **Assertion:**
  `resolve_lane(SUPERVISOR_CONSUMER, override=codex_lane)` returns the codex lane (no `LaneError`); `resolve_lane(...)`
  with no override still returns the `claude_code` default (T3 byte-identical).
- [ ] **Add `supervisor_runtime` override field to `SupervisorConfig`** (`session/models.py:149`), validated in
  `__post_init__` (reject values outside `{"claude_code", "codex"}`). **Assertion:** the field round-trips through dacite
  (manifest read + `forge session set`/override); an invalid value raises (-> `InvalidOverrideValueError` on the strict
  override path). Absent => `claude_code` default lane.
- [ ] `run_supervisor_check` maps the field to the override `Lane` and passes `resolve_lane(SUPERVISOR_CONSUMER,
  override=...)` **inside** the fail-open guard (Phase 3).

### Phase 2 -- The `codex` arm of `_dispatch_supervisor`

- [ ] Replace the `raise NotImplementedError` (`supervisor.py:469`) with `_dispatch_codex_supervisor`:
  - **Preflight (fail-open):** build `CodexPreflight` with `run_doctor=False`; if it raises, raise a
    `_SupervisorRoutingError` (caught -> fail-open "aligned"), do **not** propagate.
  - **Attribution:** build one `Attribution(command=usage_command, session=context.session_name, ...)` and pass it to
    `prepare_codex_request` (which stamps `runtime="codex"` + `billing_mode=preflight.billing_mode`).
  - **Dispatch:** `prepare_codex_request(prompt=prompt, preflight=..., attribution=..., sandbox="read-only",
    timeout_seconds=config.timeout_seconds, cwd=resolved.source_cwd)` -> `CodexHeadlessInvoker().run(...)`. **Sandbox is
    `read-only`**: a supervisor inspects, never edits (defense-in-depth; do not grant `workspace-write`).
  - **Result (adapt `HeadlessResult` -> `SessionResult`, ALL load-bearing fields):** carry `stdout`, `stderr`,
    `returncode`, `timed_out`, `error`, and `run_id`/`parent_run_id`/`root_run_id` -- the post-dispatch logic reads every
    one for fail-open classification + telemetry (on the success path too). **Fold `runtime_is_error`:** when the codex
    turn reported a failure (`runtime_is_error`, even at exit 0), set `SessionResult.error` to the codex failure reason so
    the returncode-based `success` gate (`supervisor.py:627`) fires and it is classified as a **runtime failure**, not
    parsed as an empty/unparseable verdict. Do **not** return only `stdout`.
- [ ] **Plan context:** rely on the existing preamble injection (plan already in `prompt` when `plan_override_path`
  resolves). **When no plan content resolves, fail open** (aligned) -- do not let codex evaluate against an empty plan
  (the Decision above). **Assertion:** codex dispatch with no resolvable plan -> verdict aligned, no codex spawn (or a
  spawn whose verdict is discarded for aligned -- prefer not spawning).
- [ ] **Verdict unchanged:** `parse_supervisor_verdict(result.stdout)` consumes codex stdout exactly as claude stdout
  (the normalized envelope is why). **Assertion:** a codex stdout sample parses to the same `SupervisorVerdict` shape.
- [ ] **Blind/transfer-fed only:** headless `codex exec`; no codex hook install, no enrollment, no Claude-UUID resume.
  **Assertion:** the arm's argv is `codex exec --json` with no hook/enrollment side effects (code review + test).

### Phase 3 -- Fail-open wiring (the T3 -> T4 carry-forward seams)

- [ ] Move `resolve_lane(SUPERVISOR_CONSUMER, override=...)` **inside** the `try/except` guard (`supervisor.py:609`), or
  pre-validate + degrade, so a bad override (`LaneError`) degrades to "aligned" instead of raising uncaught.
- [ ] The `codex`/unknown arms no longer brick the hook: their failure (preflight error, unknown runtime, plan-absent)
  converts to the supervisor fail-open decision (extend the caught set / wrap as `_SupervisorRoutingError`).
  **Assertion:** an invalid override, an unimplemented runtime, a preflight failure, and a plan-absent codex run all
  yield verdict=aligned, no exception escapes `run_supervisor_check`.

### Phase 4 -- Single usage emission via the invoker (NOT the Claude seam)

- [ ] The codex arm builds the `HeadlessRequest` with **exactly one** `Attribution`; `CodexHeadlessInvoker` emits
  **exactly one** `emit_codex_usage` (route `codex_exec`, `billing_mode` from the preflight -> `subscription_quota` for
  chatgpt). **Do NOT call `emit_usage_for_session_result`** (the Claude arm's seam; calling it here double-emits).
  **Assertion:** one `emit_codex_usage` per codex dispatch; **zero** `emit_usage_for_session_result` on the codex path.
- [ ] **Verify the upstream-operation label.** `_emit_codex` also records `record_upstream_operation(
  operation="workflow.worker")` (`codex.py:249`) -- but the supervisor is a **policy check**, not a workflow worker.
  Confirm whether reusing the invoker's built-in upstream emit mislabels the supervisor's operation (compare what the
  Claude arm records). If it mislabels, decide: pass a supervisor-appropriate operation, or suppress the invoker's
  upstream emit for this consumer. **Assertion:** the supervisor's upstream outcome is labeled as a supervisor/policy
  operation, not `workflow.worker`. Ties to T5.

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
| Single usage emission | codex dispatch | exactly one `emit_codex_usage`; **zero** `emit_usage_for_session_result` | `test_supervisor.py` |
| Upstream label correct | codex dispatch | upstream operation is supervisor/policy, not `workflow.worker` | `test_supervisor.py` |
| Blind/transfer-fed only | -- | `codex exec --json`; no codex hook install / enrollment | code review + assertion |

- [ ] All acceptance rows green.
- [ ] Existing supervisor suite (94 unit + 215 `tests/src/policy/semantic`) stays green -- default path unchanged.

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
