# T6b execution checklist: aux-consumer codex dispatch

**Lane**: `doing/` (member of `doing/epic_consumer_lanes/`). Branch `aux_consumer_codex_dispatch`. Card: `card.md`.

## Current focus

**Scope resolved (D1): shadow-curation only** -- memory-writer deferred to T6c, team-supervisor deferred (D2). Research
complete (2026-06-30 sweep; verified touchpoints in `card.md`). **Phase 1 is ready to start on the next go-ahead;** no
`src/` change has been made yet.

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

## Phase 1 -- shadow-curation codex arm (recommended core; unstarted)

D1 resolved to shadow-curation; Phase 1 is the implementation cursor.

- [ ] Add the codex `allowed_lane` to `SHADOW_CURATION_CONSUMER` (`session/shadow_curation.py:28-33`):
  `Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")`. Assertion:
  `valid_lanes(SHADOW_CURATION_CONSUMER)` contains the codex lane;
  `forge session lane set --consumer shadow_curation --runtime codex` resolves (was `LaneError`).
- [ ] Thread the resolved `Lane`/`runtime_id` into `run_shadow_curation` (currently receives `backend_id` +
  `on_dispatch` but not the runtime). Assertion: the dispatch function can read `runtime_id` at the branch point.
- [ ] Insert the runtime-keyed branch at `session/shadow_curation.py:315`: `claude_code` -> existing
  `run_claude_session`; `codex` -> new `_dispatch_codex_shadow_curation`. Assertion: a claude-lane run is byte-identical
  to today (golden/diff).
- [ ] Implement `_dispatch_codex_shadow_curation` mirroring `_dispatch_codex_supervisor`: `read_fresh_codex_preflight`
  ->
  `prepare_codex_request(prompt, preflight, sandbox="read-only", model=None, attribution=Attribution(command="curation", session=session_name, operation="memory.shadow_curation"))`
  -> `CodexHeadlessInvoker().run` -> `CurationResult(success=..., stdout=result.stdout, report_path=...)`. Assertion: a
  successful codex run persists the curation report from codex stdout; no file writes by codex (read-only). **Pin
  `operation="memory.shadow_curation"`** (not the `Attribution` default `workflow.worker`, `types.py:42`; not `None`) so
  the invoker's auto-recorded upstream row matches the claude path (`shadow_curation.py:341-342`) -- no T4 mislabel.
- [ ] Map codex-arm failure into shadow-curation's **fail-loud** degrade (D3) with a **CLI-visible** hint:
  cold/stale/missing preflight or a failed codex turn -> `CurationResult(success=False, ...)` carrying "Codex not ready
  -- run `forge runtime preflight codex`". **Carrier (D5):** `CurationResult` has no message field (only
  `success`/`report_path`/`stdout`, `shadow_curation.py:53-59`) and the CLI prints only `stdout` on the human failure
  branch while `--json` omits it (`cli/memory.py:935-957`) -- add `CurationResult.error: str | None`, surfaced in BOTH
  the human branch and `--json` (`stdout` is the human-only zero-schema fallback). Assertion: cold-cache run does NOT
  fall back to claude, does NOT silently succeed, AND the CLI failure output (human + `--json`) contains the preflight
  hint.
- [ ] Single emitter per arm: the **manual** emit block (`emit_usage_for_session_result` + `record_upstream_operation`,
  `shadow_curation.py:325-351`) is **claude-arm-only** -- move it inside the claude branch. The codex arm emits **only**
  via the invoker's auto `emit_codex_usage` + invoker-recorded upstream (driven by the pinned `Attribution`). Assertion:
  exactly one usage event per run; the codex usage carries `runtime=codex`/`billing_mode=subscription_quota` AND its
  upstream row carries `operation="memory.shadow_curation"` (not `workflow.worker`); no double-emit.
- [ ] Freeze parity: confirm `persist_lane_freeze` still fires on a real codex dispatch via the existing `on_dispatch`
  hook, with the `read_bound_lane == dispatched_lane` equality guard threading the codex lane. Assertion: a codex
  dispatch freezes the codex lane into `confirmed.consumer_lanes`; a skip never freezes.

## Phase 2 -- observability + docs (unstarted)

- [ ] `forge telemetry activity` shows the shadow-curation run on `runtime=codex` / `billing_mode=subscription_quota`;
  `forge session lane show` shows the bound + frozen codex lane.
- [ ] Design-doc sync: `design_appendix.md` §G (extend the consumer-lane note -- aux consumers can now take a codex
  dispatch arm, not just the supervisor); `design.md` §3.6.12 if the resolver narrative needs it; `cli_reference.md`
  (`forge session lane set --consumer shadow_curation --runtime codex` now valid). end-user `policy.md`/`memory.md` if
  the user-facing curation flow changes.
- [ ] Update epic `doing/epic_consumer_lanes/` roster + `card.md` T6b references for whatever ships vs defers (T6c for
  memory-writer; team-supervisor decision recorded).

## Acceptance tests (fixture-grounded; unstarted)

| Test                     | Fixture                                         | Assertion                                                                                                                                                                     | Test File                                                            |
| ------------------------ | ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| codex lane is selectable | `SHADOW_CURATION_CONSUMER` + codex allowed_lane | `valid_lanes` includes codex; `lane set --runtime codex` resolves (no `LaneError`)                                                                                            | `tests/src/core/test_lanes.py`, `tests/src/cli/test_session_lane.py` |
| codex arm dispatches     | fresh preflight cached, codex lane bound        | `CodexHeadlessInvoker.run` called once; curation report = codex stdout; no `run_claude_session` call                                                                          | `tests/src/session/test_shadow_curation.py`                          |
| claude path unchanged    | default lane                                    | claude dispatch byte-identical to pre-T6b (no codex branch taken)                                                                                                             | `tests/src/session/test_shadow_curation.py`                          |
| cold cache fails loud    | no/stale preflight, codex lane bound            | `success=False` + preflight hint surfaced by the CLI failure output, human + `--json` (`tests/src/cli/test_memory.py`); NO claude fallback; NO silent success                 | `tests/src/session/test_shadow_curation.py`                          |
| no doctor in path        | preflight cache present                         | `read_fresh_codex_preflight` read; `codex doctor` never spawned                                                                                                               | `tests/src/session/test_shadow_curation.py`                          |
| single usage event       | codex success                                   | exactly one usage event; codex usage `runtime=codex`/`billing_mode=subscription_quota`; upstream `operation="memory.shadow_curation"` (not `workflow.worker`); no double-emit | `tests/src/session/test_shadow_curation.py` (+ usage assertions)     |
| freeze on codex dispatch | codex lane bound, real dispatch                 | codex lane frozen into `confirmed`; equality guard holds; skip never freezes                                                                                                  | `tests/src/cli/test_consumer_lane_freeze.py`                         |

## Verification gate

- [ ] Focused suites green: `test_shadow_curation.py`, `test_lanes.py`, `test_session_lane.py`,
  `test_consumer_lane_freeze.py`, billing.
- [ ] `make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat/gitleaks).
- [ ] Integration: codex-lane dispatch is a real `codex exec` path -- run the relevant integration/real-codex check if
  reachable, else record the gap (ChatGPT-login E2E may be release-tier, like T4's codex E2E).

## Closeout

- [ ] Tick acceptance rows with verification recorded.
- [ ] `change_log.md` entry (Goal / Key changes / Verification).
- [ ] Move `doing/aux_consumer_codex_dispatch/` -> `done/`; update epic roster; promote durable lessons to
  `impl_notes.md` after human review.
