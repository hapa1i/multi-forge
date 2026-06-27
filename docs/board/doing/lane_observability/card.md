# T5 -- Lane observability (surface the chosen lane + billing; close emission gaps)

**Epic**: `docs/board/doing/epic_consumer_lanes/` -- read the epic for the shared lane contract (runtime x backend x
model; resolve once, frozen). T5 is the **observability** member: now that a consumer (the supervisor, T4) can run on a
non-Claude lane, make that choice and its cost *visible and measurable* so a user can see and verify the arbitrage.

**Lane**: `doing/` (opened 2026-06-27 on branch `lane_observability`; promoted from the epic's inline T5 sketch).

**Proves**: you can *see/verify* the lane each consumer ran on and how it was billed -- the supervisor's full resolved
lane `(runtime, backend, model)` via `forge policy supervisor status`, and per-call session-attributed
`runtime`/`billing_mode` in `forge telemetry activity`. Closes the M3 no-emission blind spots so **every** lane is
measurable, and removes the codex supervisor's double upstream-outcome row (the T4 carry-forward).

## Goal

Make the chosen lane and how it was billed *visible and measurable*. **Two honest surfaces**, because the usage ledger
carries no backend/source id (`UsageEvent` has `runtime`/`provider`/`model`/`billing_mode`, not the catalog backend
`chatgpt`): (1) **per-call telemetry** (`forge telemetry activity`) surfaces the recorded `runtime` + `billing_mode`;
(2) the **resolved-lane display** (`forge policy supervisor status`) surfaces the full lane `(runtime, backend, model)`
from the resolved `Lane` + `SupervisorConfig`. Close the three M3 no-emission gaps so every LLM lane emits a
**session-tagged** usage event, and fix the invoker's hardcoded `workflow.worker` upstream label so the codex supervisor
stops double-counting. **Observability only -- no durable consumer-lane binding** (T1b) and **no billing-inference fix**
(T0).

## Why now (the T4 carry-forward)

T4 shipped the codex supervisor lane but left a documented telemetry debt (`supervisor.py:598-604`): the shared
`CodexHeadlessInvoker._emit_codex` writes an **extra** upstream-outcome row (`operation="workflow.worker"`) on top of
the policy engine's `policy.evaluate` row that both supervisor arms already emit -- so a codex check persists **two**
upstream rows (one mis-categorized), while the claude arm persists one. Relabeling needs the *shared* invoker's emit
contract to change (it touches every invoker consumer), which is why T4 deferred it here.

## Scope (three workstreams, grounded in the 2026-06-27 surface map)

### WS1 -- Configurable upstream operation (fix the `workflow.worker` carry-forward)

`_emit_worker` (`core/invoker/claude.py:162`) and `_emit_codex` (`core/invoker/codex.py:249`) both hardcode
`record_upstream_operation(operation="workflow.worker")`. `Attribution` (`core/invoker/types.py:22-38`) carries
`command/workflow/session/runtime/billing_mode` but **no** `operation`; `record_upstream_operation`
(`core/telemetry/upstream.py:108-164`) already accepts `operation: str | None`, and `UpstreamOutcome.operation` is a
first-class field. Thread an optional `operation` through `Attribution` exactly as `billing_mode` was threaded
(`codex.py:211` does `replace(attribution, runtime="codex", billing_mode=...)`). The codex supervisor
(`supervisor.py:620`) suppresses the invoker's upstream emit so codex reaches **parity with the claude arm** (a single
`policy.evaluate` row from the engine). Review fan-out workers keep `workflow.worker` (the invoker's row is their *only*
operation outcome). The downstream usage/cost event (`emit_codex_usage`) is untouched -- only the redundant upstream row
is suppressed.

### WS2 -- Close the M3 no-emission gaps (every lane measurable)

Three LLM calls emit no usage event today (epic "agent-reported, verify" -- **confirmed against code**):

- WorkflowPolicy `CheckerStage.check()` -- `adapter.ask(...)` at `policy/workflow/stages.py:100`, no emit.
- WorkflowPolicy `ReviewerStage.review()` -- `adapter.ask(...)` at `policy/workflow/stages.py:143`, no emit.
- Team event tagger `_classify_event()` -- `SyncAdapter.ask(...)` at `policy/team/handlers.py:157`, no emit.

`.ask()` already builds the system `Message(role="system", ...)` for you (`core/llm/__init__.py:208-210`) -- it does
**not** flatten the system prompt. The reason to switch is narrower: `.ask()` returns only `response.text` and discards
the `CompletionResponse` that carries `.usage`. So each site moves to
`.complete([Message(role="system", ...), Message(role="user", ...)])` to capture `CompletionResponse.usage` -- which
means the caller must now hand-build the system `Message` itself (the system prompt is a thing to **preserve**, not a
bug to fix; omit it and the prompt silently regresses). Then `emit_direct_llm_usage(...)` -- the action tagger is the
reference (`core/reactive/tagger.py:71,77`). Cover the success **and** parse-failure/exception paths with
`status="error"` on failure (plan-check is the reference: `plan_check.py:446,452,471`). **Session attribution is
required, not optional:** `emit_direct_llm_usage` no-ops without an ambient run identity (`emit.py:454-457`), and an
event with no `session=` does not appear in per-session `forge telemetry activity`. Checker + reviewer pass
`session=context.session_name` (`ActionContext.session_name` exists, `policy/types.py:65`). The team tagger has **no**
session in its args (`handle_teammate_idle/_task_completed(data, config, cache)`), so it resolves `session` from
`FORGE_SESSION` best-effort, else emits ambient/global (documented).

### WS3 -- Surface runtime + `billing_mode` (telemetry) and the full lane (supervisor status)

Two surfaces, split by what each can honestly carry:

- **`forge telemetry activity` -- `runtime` + `billing_mode`.** `UsageEvent` carries `runtime` + `billing_mode`
  (`core/usage/ledger.py:110,116-123`) but `_aggregate_ledger` (`core/ops/usage_summary.py:684-725`) never reads them
  and no activity DTO (`CommandUsage`/`ModelCallActivity`/`SessionActivitySummary`) has a lane/billing field. Thread
  `runtime`/`billing_mode` into the rollup DTOs and render in the existing downstream pane (human table + `--json`). The
  event has **no backend/source id**, so per-call telemetry cannot show the catalog backend (`chatgpt`) -- it shows
  `runtime` (`codex`) + `billing_mode` (`subscription_quota`). Adding `UsageEvent.backend_id` is a clean additive option
  but **deferred** (Decision D-backend).
- **`forge policy supervisor status` -- the full resolved lane `(runtime, backend, model)`.**
  `SupervisorConfig.supervisor_runtime` (`session/models.py:163-166`) is stored but never displayed; resolve it to its
  `Lane` (the codex candidate is `(codex, chatgpt, gpt-5-codex)`) and render the full lane (+ `--json`) via the existing
  `_supervisor_status_dict()` helper. This is where "the chosen lane" is shown completely.

Status-line / `render_summary_line` lane indicator is **out of scope** (deferred -- Decision D3).

## Decisions (resolved at review 2026-06-27)

- **D1 -- emit-seam shape = DECIDED.** Add `operation: str | None = "workflow.worker"` to `Attribution`; the invoker
  emits the upstream row only when `operation is not None`; the codex supervisor sets `operation=None` ("emit usage,
  suppress upstream outcome" -- cleaner than a separate boolean), reaching parity with the claude arm's single
  `policy.evaluate`. Codex bridge/session/enrollment **keep** `workflow.worker` in T5 (no relabel); an
  operation-taxonomy pass for them is a possible future card, not this one.
- **D2 -- M3 emission = DECIDED.** Switch the three sites `.ask()` -> `.complete()` capturing exact tokens; preserve the
  system prompt via `Message(role="system", ...)`; emit `command` `policy-checker`/`policy-reviewer`/`team-tagger` with
  explicit `session` tagging (checker/reviewer from `context.session_name`; team tagger from `FORGE_SESSION`
  best-effort, else ambient); `status="error"` on parse-failure/exception.
- **D3 -- read-surface shape = DECIDED.** Additive fields on the existing activity DTOs/pane (no new pane). Status-line
  / summary-line lane indicators are **deferred** -- `forge telemetry activity` + `forge policy supervisor status` are
  T5's surfaces.
- **D4 -- billing/runtime rollup = DECIDED.** Show the uniform `runtime`/`billing_mode` for a row; show `mixed` when the
  row's events hold more than one distinct value; a downstream-only row with no usage-event source renders
  `unknown`/`-`, never `mixed`.
- **D-backend (deferred).** Adding `UsageEvent.backend_id` (additive, like the downstream plane already has) would let
  per-call telemetry show the catalog backend too. Out of scope for T5 -- the full lane is covered by the
  supervisor-status display; revisit with T1b if per-call backend attribution is wanted.

## Acceptance (definition of done)

| Test                                            | Fixture                             | Assertion                                                                                                                                          | Test File                                                                                             |
| ----------------------------------------------- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Codex supervisor emits ONE upstream row         | codex override dispatch             | exactly one upstream outcome (`policy.evaluate`); no `workflow.worker` row                                                                         | `tests/src/policy/semantic/test_supervisor.py`                                                        |
| Review worker keeps `workflow.worker` and usage | review fan-out                      | invoker `workflow.worker` row unchanged (byte-identical) and `emit_worker_usage` still fires                                                       | `tests/src/core/invoker/test_claude_invoker.py` (label) and `tests/src/review/test_engine.py` (usage) |
| `Attribution.operation` threads end-to-end      | invoker request                     | `operation=None` suppresses upstream emit; a set value is used                                                                                     | `tests/src/core/invoker/`                                                                             |
| Codex supervisor keeps downstream usage         | codex invoker run, `operation=None` | exactly one `emit_codex_usage` (downstream) still fires; zero upstream rows -- suppression must not over-reach to usage                            | `tests/src/core/usage/test_codex_emit.py` and `tests/src/core/invoker/test_codex_invoker.py`          |
| Checker emits session-tagged usage              | WorkflowPolicy checker run          | one `emit_direct_llm_usage` (`command="policy-checker"`, `session=context.session_name`); success + parse-fail (`status="error"`)                  | `tests/src/policy/workflow/test_stages.py`                                                            |
| Reviewer emits session-tagged usage             | WorkflowPolicy reviewer run         | one `emit_direct_llm_usage` (`command="policy-reviewer"`, `session` set); success + failure                                                        | `tests/src/policy/workflow/test_stages.py`                                                            |
| Team tagger emits usage                         | team `_classify_event`              | one `emit_direct_llm_usage` (`command="team-tagger"`); `session` from `FORGE_SESSION` when set, else ambient                                       | `tests/src/policy/team/test_handlers.py`                                                              |
| Activity shows runtime + billing                | ledger with codex + claude events   | `forge telemetry activity` renders `runtime`/`billing_mode`; `mixed` on multi-value, `-`/`unknown` on downstream-only; `--json` carries the fields | `tests/src/cli/test_activity.py` / `tests/src/core/ops/test_usage_summary.py`                         |
| Supervisor status shows full lane               | codex-configured session            | `forge policy supervisor status` shows lane `(runtime=codex, backend=chatgpt, model=gpt-5-codex)`; `--json` carries it                             | `tests/src/cli/test_policy_supervisor.py`                                                             |

## Non-goals

- **No durable consumer-lane binding** (`intent`/immutable `confirmed`) -- that is T1b. T5 surfaces what is *already*
  chosen (`supervisor_runtime`) and what was *already* recorded (`UsageEvent.runtime`/`billing_mode`).
- **No billing-inference fix** -- the claude supervisor's `billing_mode` stays inferred (often `unknown`); proving
  `claude -p` rides a Max subscription is **T0**. T5 renders what is recorded, honestly including `unknown`.
- **No historical backfill** of `billing_mode`/`runtime` into old ledger events -- forward-only.
- **No new dynamic routing** -- T5 is a read/measure pass, not a placement change.

## Depends on

T3 (lane-driven supervisor seam) and T4 (codex lane + the documented `workflow.worker` carry-forward) -- both **done**.
