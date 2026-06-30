# T6b execution checklist: aux-consumer codex dispatch

**Lane**: `doing/` (member of `doing/epic_consumer_lanes/`). Branch `aux_consumer_codex_dispatch`. Card: `card.md`.

## Current focus

**Scope resolved (D1): shadow-curation only** -- memory-writer deferred to T6c, team-supervisor deferred (D2). **Phase 1
(codex arm) is implemented and unit-tested** (2026-06-30): the `codex` arm ships in `shadow_curation.py`, the CLI passes
the bound lane (validated via `resolve_lane`) + surfaces `CurationResult.error`, and the arm/CLI/lane/validation tests
pass, and a real `codex exec` E2E (`test_shadow_curation_codex_smoke.py`) passes against the host ChatGPT login.
Remaining: **Phase 2** (observability check + design-doc sync + epic roster).

## Decisions (resolved 2026-06-30)

- [x] **D1 -- Scope.** Resolved: **shadow-curation only** -- the clean mirror-T4 consumer. Memory-writer -> T6c;
  team-supervisor deferred (D2).
- [x] **D2 -- Team-supervisor plan context.** Resolved: **defer** -- a consequence of D1 (team-supervisor is out of T6b
  scope; its plan-blind codex problem is a separate context-model change, not folded in here).
- [x] **D3 -- Shadow-curation codex degrade.** Resolved (recommended default): **fail loud** on a cold/stale preflight
  or a codex failure (exit 1 + "run `forge runtime preflight codex`") -- no silent fall-back to claude.
- [x] **D4 -- Codex lane tuple.** Resolved (recommended default):
  `Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")`, `model` nominal (codex picks its own model).
- [x] **D5 -- Fail-loud hint carrier (from review).** Resolved (recommended): add `CurationResult.error: str | None`
  surfaced in the human failure branch AND `--json` (today both drop any non-`stdout` message, `cli/memory.py:935-957`);
  `stdout` is the human-only zero-schema fallback. The cold-preflight hint must be CLI-visible and tested.

## Phase 1 -- shadow-curation codex arm (implemented + unit-tested 2026-06-30)

D1 resolved to shadow-curation; Phase 1 was the implementation cursor.

- [x] Added the codex `allowed_lane` to `SHADOW_CURATION_CONSUMER` (`session/shadow_curation.py:28-36`):
  `Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")`. Verified:
  `test_shadow_curation_consumer_allows_codex_lane` (codex lane in `valid_lanes`, claude-max preserved);
  `test_set_shadow_curation_via_codex_runtime` (`lane set --runtime codex` resolves, exit 0, was `LaneError`).
- [x] Threaded the bound lane into `run_shadow_curation` (the CLI passes the `LaneRecord`; the function validates it and
  derives the runtime -- the validation hardening landed as a review follow-up, below). Verified by the dispatch tests
  selecting the arm through the public entry.
- [x] Inserted the runtime-keyed branch before the claude `on_dispatch`: `codex` -> early return into
  `_dispatch_codex_shadow_curation`; `claude_code` path left byte-identical. Verified:
  `test_claude_runtime_never_touches_codex` (claude path runs, codex preflight never read).
- [x] Implemented `_dispatch_codex_shadow_curation` mirroring `_dispatch_codex_supervisor`: `read_fresh_codex_preflight`
  ->
  `prepare_codex_request(sandbox="read-only", model=None, cwd=str(forge_root), attribution=Attribution(command="curation", session=session_name, operation="memory.shadow_curation"))`
  -> `CodexHeadlessInvoker().run` -> persist report from `result.stdout`. **`operation` pinned** (not the
  `workflow.worker` default, not `None` like the supervisor) so the invoker's auto upstream row matches the claude path.
  Verified: `test_dispatches_through_invoker_and_persists_from_stdout`, `test_pins_operation_and_skips_claude_emitter`.
- [x] Mapped codex failure into **fail-loud** degrade (D3) with a **CLI-visible** hint via the **D5** carrier (added
  `CurationResult.error: str | None`, surfaced in the human failure branch via `print_error` AND in `--json`).
  `HeadlessResult.runtime_is_error` is folded so an exit-0-but-failed turn fails loud. Verified:
  `test_cold_preflight_fails_loud_no_fallback_no_freeze`, `test_unready_preflight_surfaces_blocking_reason`,
  `test_failed_turn_fails_loud_but_still_freezes`, `test_exit_zero_but_runtime_error_fails_loud`, and CLI
  `test_review_curate_failure_surfaces_error_{json,human}`.
- [x] Single emitter per arm: the codex arm returns before the claude manual-emit block, so
  `emit_usage_for_session_result` is structurally claude-only; the codex arm emits solely via the invoker's auto
  `emit_codex_usage` + invoker-recorded upstream (driven by the pinned `Attribution`). Verified:
  `test_pins_operation_and_skips_claude_emitter` (`emit_usage_for_session_result` not called;
  `attribution.operation == "memory.shadow_curation"`). Note: the runtime=codex/billing_mode=subscription_quota usage
  event itself is proven at the invoker layer (`test_codex_emit.py`), not re-asserted here (the arm only owns the
  `Attribution`).
- [x] Freeze parity (with a timing refinement): `on_dispatch` fires **after** the preflight gate passes -- a
  cold-preflight skip-return never spawns codex, so per `impl_notes` ("freeze only past every skip-return") it must not
  freeze; a turn that spawns and then fails still freezes (claude-arm parity). Verified:
  `test_successful_dispatch_fires_freeze`, `test_failed_turn_fails_loud_but_still_freezes` (freeze fires),
  `test_cold_preflight_fails_loud_no_fallback_no_freeze` (freeze does not fire).

## Review follow-ups (2026-06-30, commits `a5089be3` + `baae7885`)

- [x] **Validate the bound lane before arm selection** (durable-state gap). The arm was selected from the raw
  `LaneRecord.runtime_id` with no catalog re-validation, so a stale/corrupt explicit binding could dispatch Codex on an
  invalid lane (codex runtime + non-codex backend, bypassing `allowed_lanes`) or silently fall through to Claude on an
  unknown runtime. `run_shadow_curation` now takes the `LaneRecord` and runs it through the same
  `LaneRecord -> Lane -> resolve_lane` guard as the supervisor (`run_supervisor_check`), mapped into shadow-curation's
  fail-loud contract: no dispatch, no freeze, and a `CurationResult.error` naming the re-pin/clear path; `None` resolves
  to the default Claude lane. Verified: `test_invalid_explicit_lane_fails_loud_no_dispatch_no_freeze`,
  `test_unknown_runtime_fails_loud_not_silent_claude`.
- [x] **Broaden the Claude-specific freeze wording** to runtime dispatch. `design.md`, `design_appendix.md`, and
  `consumer_lane_freeze.py` described the aux freeze as firing "at the actual `run_claude_session` call" -- stale for
  the codex arm, which freezes after the preflight gate and before `codex exec`. Reworded to "the actual runtime
  dispatch (`run_claude_session`, or `codex exec` on shadow-curation's codex lane)".

## Phase 2 -- observability + docs (design synced; closeout pending)

- [x] Observability. `forge session lane show` surfaces the bound + frozen codex lane today (T6a/T5 machinery, no new
  code in T6b). The `runtime=codex` / `billing_mode=subscription_quota` usage event (`forge telemetry activity`) rides
  the invoker's `emit_codex_usage` (shared with T4) and is now asserted by the real-codex E2E
  (`test_shadow_curation_codex_smoke.py`). No T6b-specific observability code was needed.
- [x] Design-doc sync: `design_appendix.md` consumer-lane note extended with a **Shadow-curation codex arm (T6b)**
  paragraph (fail-loud vs fail-open, `operation` pinned vs the supervisor's `None`, freeze-past-the-skip-gate) and the
  T6a `claude-max` paragraph's "no codex arm; that is T6b" forward-ref narrowed. `cli_reference.md` lane-set bullet now
  states `--runtime codex` dispatches a real arm for `supervisor`/`shadow_curation` only. `design.md` resolver narrative
  needed no change (runtime-keyed dispatch already described). end-user `policy.md`/`memory.md`: no change -- the curate
  UX is unchanged except the new fail-loud preflight hint, which is self-explanatory.
- [x] Epic updated: `epic_consumer_lanes/checklist.md` current-focus + roster note "Phase 1 landed in-branch"; T6c
  (memory-writer) + team-supervisor deferral already recorded in the epic card T6b row and this card.

## Acceptance tests (implemented + passing 2026-06-30)

| Test                              | Fixture                                         | Assertion                                                                                                                                                                                         | Test File / name                                                                                                                                                              |
| --------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| codex lane is selectable          | `SHADOW_CURATION_CONSUMER` + codex allowed_lane | `valid_lanes` includes codex (claude-max preserved); `lane set --runtime codex` resolves (no `LaneError`)                                                                                         | `test_shadow_curation.py::test_shadow_curation_consumer_allows_codex_lane`; `test_session_lane.py::test_set_shadow_curation_via_codex_runtime`                                |
| codex arm dispatches              | fresh preflight cached, `runtime_id="codex"`    | `CodexHeadlessInvoker.run` called once; report = codex stdout; no `run_claude_session`; read-only/`model=None`/`cwd=forge_root`                                                                   | `test_shadow_curation.py::test_dispatches_through_invoker_and_persists_from_stdout`                                                                                           |
| claude path unchanged             | default runtime                                 | claude path runs; `read_fresh_codex_preflight` never read (codex branch inert)                                                                                                                    | `test_shadow_curation.py::test_claude_runtime_never_touches_codex`                                                                                                            |
| cold cache fails loud             | `read_fresh_codex_preflight` -> None            | `success=False` + hint; NO claude fallback; NO spawn; skip-return -> NO freeze; CLI human + `--json` carry the hint                                                                               | `test_shadow_curation.py::test_cold_preflight_fails_loud_no_fallback_no_freeze`; `test_memory.py::test_review_curate_failure_surfaces_error_{json,human}`                     |
| no doctor in path                 | preflight cache present                         | `read_fresh_codex_preflight` read once (no `codex doctor` subprocess)                                                                                                                             | `test_shadow_curation.py::test_dispatches_through_invoker_and_persists_from_stdout` (`mock_read.assert_called_once_with()`)                                                   |
| single emitter / pinned operation | codex success                                   | claude `emit_usage_for_session_result` not called; `Attribution.operation == "memory.shadow_curation"`, `command="curation"` (invoker auto-emits the one event -- proven in `test_codex_emit.py`) | `test_shadow_curation.py::test_pins_operation_and_skips_claude_emitter`                                                                                                       |
| freeze parity                     | spy `on_dispatch`                               | success + failed-turn freeze; cold-preflight skip never freezes                                                                                                                                   | `test_shadow_curation.py::test_successful_dispatch_fires_freeze`, `::test_failed_turn_fails_loud_but_still_freezes`, `::test_cold_preflight_fails_loud_no_fallback_no_freeze` |
| runtime-error fold                | exit 0 + `runtime_is_error=True`                | folded to `success=False` (no empty report persisted); hint carries the stderr reason                                                                                                             | `test_shadow_curation.py::test_exit_zero_but_runtime_error_fails_loud`                                                                                                        |

## Verification gate

- [x] Focused suites green: `test_shadow_curation.py` (35), `test_memory.py`, `test_session_lane.py`,
  `test_consumer_lane_freeze.py`, `test_lanes.py`, `test_billing.py` -> 157 passed; plus wider regression sweep
  (`policy/semantic`, `core/invoker`, `core/usage`, `session/`, `codex_preflight_cache`) 1318 passed, and full
  `tests/src/cli` 2145 passed.
- [x] `make pre-commit` clean on changed files (ruff/black/isort/mypy/pyright/gitleaks all pass; black wrapped one
  ternary, re-staged).
- [x] Integration: **ran a real `codex exec` E2E and it passes** —
  `tests/integration/session/test_shadow_curation_codex_smoke.py::test_shadow_curation_codex_arm_real_dispatch` spawns
  real codex against the host ChatGPT login and asserts success, report persisted from codex stdout, freeze fired, and
  exactly one `runtime=codex`/`billing_mode=subscription_quota`/`route=codex_exec` usage event. Two real-system findings
  the mocks hid: (1) ChatGPT (`codex_store`) auth needs the host `CODEX_HOME` restored past the autouse
  `isolate_codex_home` fixture — the test captures it at import time (the existing `test_codex_exec_smoke.py` lacks
  this, so it is implicitly CODEX_API_KEY-only); (2) the upstream-outcome log is failure-biased, so a success emits the
  usage event but no outcome row (asserted). Run:
  `uv run pytest tests/integration/session/test_shadow_curation_codex_smoke.py`.

## Closeout

- [ ] Tick acceptance rows with verification recorded.
- [ ] `change_log.md` entry (Goal / Key changes / Verification).
- [ ] Move `doing/aux_consumer_codex_dispatch/` -> `done/`; update epic roster; promote durable lessons to
  `impl_notes.md` after human review.
