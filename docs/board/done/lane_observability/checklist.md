# T5 execution checklist -- Lane observability

**Epic**: `docs/board/done/epic_consumer_lanes/` (lane contract). **Card**: `card.md` (scope, decisions, acceptance,
non-goals). **Branch**: `lane_observability` (opened 2026-06-27; promoted from the epic's inline T5 sketch).

## Current focus

**DONE 2026-06-27 -- shipped via PR #56 (`4fc705b4`) and closed out to `done/`.** All five phases complete (WS1/WS2/WS3
\+ tests + docs); design docs synced in the PR; change_log + epic roster updated at closeout. Decisions D1-D4 resolved.
This checklist scaffolds T5 from the 2026-06-27 read-only surface map (4 parallel readers, high-confidence), with the
review's three fixes folded in: (M1) "chosen lane" is split across two honest surfaces -- per-call
`runtime`/`billing_mode` in `forge telemetry activity` (the usage event has no backend id) and the full
`(runtime, backend, model)` lane in `forge policy supervisor status`; (M2) WS2 emissions are **session-tagged** (else
they miss per-session activity); (M3 low) the epic roster/card/link-control updates landed in this change. Scope is
three workstreams: WS1 invoker upstream-label fix (the T4 carry-forward), WS2 close the M3 no-emission gaps, WS3 the two
read surfaces. **Observability only** -- no durable consumer-lane binding (T1b), no billing-inference fix (T0).

## Verified surface (2026-06-27 map, against shipped code on `main`)

**Emit seam (WS1).**

- `_emit_worker` (`core/invoker/claude.py:123-171`, hardcode at `:162`) and `_emit_codex`
  (`core/invoker/codex.py:215-258`, hardcode at `:249`) both call
  `record_upstream_operation(operation="workflow.worker")` with no caller override.
- `Attribution` (`core/invoker/types.py:22-38`) carries `command/workflow/session/runtime/billing_mode` -- **no
  `operation`**. `billing_mode` was threaded the same way the fix needs (`codex.py:211`:
  `replace(attribution, runtime="codex", billing_mode=preflight.billing_mode)`; read at emit `codex.py:238`).
- `record_upstream_operation` (`core/telemetry/upstream.py:108-164`) already takes `operation: str | None = None`;
  `UpstreamOutcome.operation` is first-class (`:47-68`). The telemetry model is ready; only the invoker call sites
  hardcode.
- Codex supervisor double-row is documented at `supervisor.py:598-604` (engine `policy.evaluate` + invoker
  `workflow.worker`). The claude arm uses `run_claude_session`, **not** the invoker, so it emits one row -- the parity
  target.
- Invoker consumers (blast radius of the contract change): review engine (`review/engine.py:214,312`), codex supervisor
  (`supervisor.py:620,634`), codex bridge (`core/ops/codex_bridge.py:375,382`), codex enrollment
  (`core/ops/codex_enrollment.py:240`), codex session (`core/ops/codex_session.py:496`). Adding an optional field to
  `Attribution` is additive -- consumers that do not set it default to `workflow.worker`.

**M3 no-emission gaps (WS2) -- epic "agent-reported, verify" CONFIRMED.**

- Silent: `CheckerStage.check()` `adapter.ask(...)` (`policy/workflow/stages.py:100`); `ReviewerStage.review()`
  `adapter.ask(...)` (`policy/workflow/stages.py:143`); team `_classify_event()` `SyncAdapter.ask(...)`
  (`policy/team/handlers.py:157`). None call any `emit_*`.
- `.ask()` already builds the system `Message` (`core/llm/__init__.py:208-210` -- **not** a flatten) but returns only
  `response.text` and discards the `CompletionResponse.usage`. So the switch is `.ask()` -> `.complete()` to capture
  usage, and the caller must hand-build `Message(role="system", ...)` to preserve the system prompt (omit it = silent
  regression), then `emit_direct_llm_usage`. Reference: action tagger (`core/reactive/tagger.py:71,77`); success+failure
  emission reference: plan-check (`policy/semantic/plan_check.py:446,452,471`).
- Already-emitting consumers (do NOT touch): action tagger, plan-check, semantic supervisor (`supervisor.py:558`), team
  supervisor (`team/handlers.py:211`), memory writer (`memory_writer.py:526`), workflow verbs
  (`cli/workflow.py:505,889,1333,2039`), per-worker fan-out (`emit_worker_usage`).
- Test gap: `tests/src/policy/workflow/test_stages.py` has **zero** usage-emission tests today (acceptance must add
  them); references exist at `tests/src/policy/team/test_handlers.py:202` and
  `tests/src/policy/semantic/test_plan_check.py:308`.

**Read surfaces (WS3).**

- `UsageEvent` carries `runtime` + `billing_mode` (`core/usage/ledger.py:110,116-123`), but `_aggregate_ledger`
  (`core/ops/usage_summary.py:684-725`) never reads them.
- **`UsageEvent` has no backend/source id** (`ledger.py:97-146` -- runtime/provider/model/billing_mode only). So
  per-call telemetry can show `runtime` + `billing_mode`, **not** the catalog backend (`chatgpt`); the full lane shows
  via supervisor status. Adding `UsageEvent.backend_id` is the deferred D-backend option.
- No activity DTO carries lane/billing: `CommandUsage` (`:54-79`), `ModelCallActivity` (`:170-187`), `OperationActivity`
  (`:138-152`), `SessionActivitySummary` (`:207-236`); `activity_summary_to_json` (`:376-386`) has no such keys.
- Human table `cli/activity.py:_render` (`:147-175`) columns: Command/Calls/Workers/Attempts/Errors/Join/Tokens/Cost --
  no lane/billing. `proxy_costs.py` show (`:103-191`) and status line (`status_line.py:format_launch:1312-1342`,
  `render_summary_line:305-374`) likewise carry none.
- `SupervisorConfig.supervisor_runtime` (`session/models.py:163-166`) is stored but never shown in
  `forge policy supervisor status`.

**Session attribution (WS2 prerequisite).** `emit_direct_llm_usage` (`core/usage/emit.py:426`) **no-ops without an
ambient run identity** (`:454-457`) and needs an explicit `session=` or the event misses per-session
`forge telemetry activity`. `ActionContext.session_name` exists (`policy/types.py:65`) -> checker/reviewer tag it
directly. The team handlers take only `(data, config, cache)` (`handlers.py:31,71`) -- no Forge session -> the tagger
resolves `session` from `FORGE_SESSION` best-effort, else ambient.

## Decisions (resolved at review 2026-06-27)

- [x] **D1 -- emit-seam shape.** `operation: str | None = "workflow.worker"` on `Attribution`; invoker emits the
  upstream row iff `operation is not None`; codex supervisor sets `operation=None` (emit usage, suppress upstream
  outcome -> codex==claude). Codex bridge/session/enrollment **keep** `workflow.worker` in T5 (relabel = a future
  operation-taxonomy card).
- [x] **D2 -- M3 emission shape.** `.ask()` -> `.complete([Message(role="system", ...), Message(role="user", ...)])`
  (preserves the system prompt, captures tokens); commands `policy-checker`/`policy-reviewer`/`team-tagger`; explicit
  `session` tagging (checker/reviewer from `context.session_name`, team tagger from `FORGE_SESSION` best-effort else
  ambient); `status="error"` on parse-failure/exception.
- [x] **D3 -- read-surface shape.** Additive fields on existing DTOs in the existing downstream pane (+ `--json` keys),
  no new pane. Status-line/summary-line lane indicator **deferred** (out of scope).
- [x] **D4 -- billing/runtime rollup.** Uniform `runtime`/`billing_mode` per row; `mixed` when >1 distinct value;
  downstream-only rows with no usage-event source render `unknown`/`-`, never `mixed`.
- **D-backend (deferred).** `UsageEvent.backend_id` (additive) would give per-call backend attribution; out of scope for
  T5 (the full lane is on supervisor status). Revisit with T1b.

## Phases (start only after Decisions resolved)

### Phase 0 -- Open the card (this change)

- [x] Branch `lane_observability` created from `main`.
- [x] Author `card.md` (durable framing, epic link) + this `checklist.md` from the surface map.
- [x] Update epic roster + card + link-control: T5 -> `doing/lane_observability/` (in progress); next cursor + the
  M3-no-emission-verify item updated.
- [x] **PAUSE for review** (per request) -- reviewed 2026-06-27; decisions D1-D4 resolved and the three review fixes
  folded in. Phase 1 starts on the go-ahead to commit this scaffolding and implement.

### Phase 1 -- WS1: configurable upstream operation (D1)

- [x] Add `operation` to `Attribution` (additive, default `"workflow.worker"`); invoker `_emit_worker`/`_emit_codex`
  read it and emit the upstream row only when non-None. Threaded the field (`types.py:39`), then wrapped **only** the
  `record_upstream_operation(...)` call in a new inner `if attribution.operation is None: return` (`claude.py:160-163`,
  `codex.py:246-249`). The shared early-return guard and `emit_codex_usage`/`emit_worker_usage` are untouched.
  **Verified**: gate tests driven on the FAILURE path (success upstream rows are volume-dropped by
  `should_record_upstream_outcome`, so only a failure proves the gate, not the volume policy) --
  `test_operation_none_suppresses_upstream_keeps_usage` (claude + codex) +
  `test_operation_label_threads_to_upstream_row`.
- [x] Codex supervisor sets `operation=None` (`supervisor.py:622`); engine `policy.evaluate` is the arm's only upstream
  row, parity with the claude arm; review workers still emit `workflow.worker` (default field; `test_engine.py` green).
  **Verified**: `test_codex_arm_dispatches_through_invoker` asserts `attribution.operation is None`; suppression proven
  at the invoker level.
- [x] Updated the `supervisor.py` carry-forward comment (now "Upstream-row parity (T5/WS1)", limitation resolved).
  **Verified**: 196 tests green across supervisor/invoker/codex-emit/review; `mypy` clean on the 4 changed source files.

### Phase 2 -- WS2: close the M3 no-emission gaps (D2)

- [x] Checker + Reviewer stages (`policy/workflow/stages.py`): `.ask()` -> `.complete(...)` via a shared
  `_complete_with_usage` helper (so the two stages can't drift). Preserves the system prompt by mirroring `.ask()`'s
  guard (prepend `Message(role="system", ...)` **only when** `system_prompt` is set -- it is `str | None`).
  `emit_direct_llm_usage(command="policy-checker"|"policy-reviewer", session=context.session_name, ...)` on success +
  parse-failure (`status="error"`/`parse_error`) + exception (`_emit_stage_error`, `failure_type="exception"`). Includes
  the tagger/plan-check exact-cost `request_id` join (best-effort; `resolve_client_base_url`/`target_is_forge_proxy` are
  exception-safe). **Verified**: `test_emits_session_tagged_usage_event` + `test_parse_failure_emits_error_event` +
  `test_exception_emits_error_event` (checker + reviewer) in `test_stages.py`.
- [x] Team event tagger (`policy/team/handlers.py:_classify_event`): same switch (no system prompt -- `.ask(prompt)` had
  none); `command="team-tagger"`; `session = os.environ.get("FORGE_SESSION") or None` (no session in the handler args),
  else ambient -- documented at the emit. Emits on success and on exception (`status="error"`). **Verified**:
  `test_emits_team_tagger_usage_event` + `test_exception_emits_error_event` in `test_handlers.py`.
- [x] Confirmed no double-emit (one `emit_direct_llm_usage` per call; `len(events) == 1` asserted) with correct
  `command`/`session`/`provider`/`status` stamps. Migrated all pre-existing stage/tagger tests from `.ask` to
  `.complete` (moved behavior -> updated tests, not skipped). **Verified**: 469 policy tests green; `mypy` clean.

### Phase 3 -- WS3: two read surfaces (D3, D4)

- [x] `forge telemetry activity`: added `runtime`/`billing_mode` to `ModelCallActivity` and a `_rollup_lane_value`
  helper; `_build_model_call_pane` stamps event-backed rows (per-command set -> uniform value or `"mixed"`),
  downstream-only rows stay `None`. Rendered a `Runtime/Billing` column in `cli/activity.py:_render`; `--json` carries
  the fields for free via `asdict(summary.downstream)`. **Verified**: `test_lane_row_carries_runtime_and_billing` /
  `test_lane_mixed_when_command_events_disagree` / `test_lane_none_for_downstream_only_row` (`test_usage_summary.py`)
  and `test_json_carries_runtime_and_billing` / `test_human_render_shows_runtime_billing` (`test_activity.py`).
- [x] `forge policy supervisor status`: added a public `resolve_supervisor_lane(config)` (default claude lane, or codex
  override) and surfaced it in `_supervisor_status_dict` (`supervisor_runtime` + `lane` keys) and the human render
  (`Lane: runtime=... backend=... model=...`); drift fails open to `lane=null`/`(unresolved)`. **Verified**:
  `test_status_json_carries_default_lane` / `test_status_json_carries_codex_lane` / `test_status_displays_codex_lane`
  (`test_policy_supervisor.py`), and the `_SUPERVISOR_JSON_KEYS` set updated for the new keys.
- [x] Status-line / `render_summary_line` lane indicator: **deferred** (Decision D3) -- not in T5. **Verified**:
  `test_status_line.py` green (the additive DTO fields don't change the summary line).

### Phase 4 -- Tests (card acceptance table)

- [x] Implemented every row of the `card.md` acceptance table (folded into each phase); added the previously-missing
  `test_stages.py` usage tests (the file had zero before). New gate tests drive the FAILURE path so suppression is real.
- [x] Existing suites stay green: review fan-out keeps the byte-identical `workflow.worker` upstream label
  (`test_engine.py`/`test_claude_invoker.py`); default supervisor unchanged. **Full unit suite: 7019 passed, 0 failed.**

### Phase 5 -- Docs + closeout

- [x] design_appendix.md §G (codex `operation=None` upstream-parity fix + the two T5 read surfaces + the three closed M3
  gaps) and the per-emitter coverage table (checker/reviewer/team-tagger rows + the activity lane note);
  cli_reference.md `forge telemetry activity` lane columns and a new `forge policy supervisor status` row.
- [x] `make pre-commit` clean; full unit suite 7019 passed. Merged via PR #56 (`4fc705b4`). Relevant integration
  (`test_supervisor_e2e.py`) is Docker/real-Claude release-tier and stays deferred -- the changes are additive telemetry
  (no dispatch/verdict change), so unit coverage is the gate.
- [x] Closeout (2026-06-27, post-merge to `main`): change_log entry added; epic roster + card flipped T5 -> done;
  `git mv doing/lane_observability -> done/`; epic checklist's "Verify the M3 no-emission gaps are actually silent" item
  already ticked. Durable lessons deferred to the epic closeout (epic stays in `doing/` coordinating T1b/T6/T7).

## Acceptance test table

(Authoritative table in `card.md`; Phase 4 implements it.) Fixture-grounded rows cover: codex supervisor single upstream
row, codex downstream usage untouched under `operation=None`, review worker `workflow.worker` label and
`emit_worker_usage` both unchanged, `Attribution.operation` end-to-end, Checker/Reviewer/team-tagger emission,
`forge telemetry activity` runtime/billing render, `forge policy supervisor status` lane render.

## Blockers / deferred

- **T1b** owns the durable consumer-lane binding (`intent` + immutable `confirmed`). T5 adds **no** manifest schema.
- **T0** owns the claude-supervisor billing-inference fix; T5 renders `billing_mode` as recorded (honestly `unknown`
  where inferred).
- No historical ledger backfill (forward-only).
