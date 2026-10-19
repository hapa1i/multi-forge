# A3 identity and accounting handoff

Code inspection at `2672ecf2`, 2026-10-19. This reconciles the identity task in the [checklist](../checklist.md) for the
[offline study](feasibility-plan.md). No provider or native-source calls ran. The existing contracts support offline
preparation; they do not yet provide complete A3 runtime correlation.

## A1: available contract

- [`judge()`](../../../../../src/forge/core/judgments/openrouter.py#L65) accepts an explicit `RunIdentity`; otherwise it
  reads the ambient identity once. It does not mint an evaluation run. Session attribution and optional provider
  grouping still come from the environment, independently of that explicit identity (lines 81–91).
- [`derive_child_run_identity()`](../../../../../src/forge/core/reactive/env.py#L164) mints a child of the supplied
  mapping's current run, preserves its root and ignores a stale parent field. Without a current run, it creates a root.
  Derivation does not mutate the environment. Provider grouping is optional and based on ambient session/root and role;
  it is not an evaluation or request key ([resolver](../../../../../src/forge/core/usage/correlation.py#L82)).
- Every [`_attempt()`](../../../../../src/forge/core/judgments/openrouter.py#L138) gets a fresh request ID and
  downstream event ID and records its terminal evidence in `finally`. Retries share the evaluation run but not physical
  attempt IDs. Pre-dispatch failures can have no attempts. Set `max_attempts=1` for the proposed zero-retry screen; A1's
  default is two (lines 44–62, 94–124).
- The [emitter](../../../../../src/forge/core/judgments/usage.py#L18) writes a downstream attempt and, when identity
  exists, a usage event named `evt_<downstream_event_id>`. Downstream retains run/root; usage retains run/parent/root.
  They describe the same attempt, so they are not two requests. Downstream readers merge repeated event IDs
  ([reader](../../../../../src/forge/core/telemetry/downstream.py#L187)); verb invocation counts use distinct run IDs
  ([aggregation](../../../../../src/forge/cli/proxy_costs.py#L188)).
- Accounting survives invalid answers when fields remain independently valid
  ([partial metadata](../../../../../src/forge/core/judgments/types.py#L186)). Cost is optional floating-point USD,
  converted to integer microdollars with half-up rounding. Missing cost remains unavailable. Emission is best effort and
  cannot invalidate a judgment; it is not a durable dispatch reservation or a complete experiment ledger
  ([usage](../../../../../src/forge/core/judgments/usage.py#L27)).

The existing [offline observability fixture](../../../../../tests/integration/core/judgments/test_observability.py#L26)
checks two evaluation children of one session, four distinct retry requests, unchanged ambient environment, preserved
ancestry and two logical invocations. This note inspected that coverage; it did not rerun tests.

## B1: current checker, frontier and audit relationships

- [`ReviewSource`](../../../../../src/forge/policy/semantic/plan_source.py#L57) shares one plan snapshot between checker
  and frontier for the same `ActionContext`. That binds evidence, not model-run ancestry.
- The [checker](../../../../../src/forge/policy/semantic/plan_check.py#L518) creates a `ReviewAttempt` before cache
  lookup or dispatch. Its model usage still uses ambient identity
  ([emitter](../../../../../src/forge/core/usage/emit.py#L432)); its decision does not attach a model run ID. Thus the
  attempt's `model_run_id` can be null, and multiple checks can share one usage run. A cache hit creates review evidence
  without a new model call ([cache](../../../../../src/forge/policy/semantic/plan_check.py#L588)).
- [`ReviewAttempt`](../../../../../src/forge/policy/semantic/attempts.py#L73) records action/plan identity, stage,
  purpose and ambient root, then copies `decision.telemetry_run_id` on completion (line 153). Its `stage="checker"`
  branch currently resolves the generative checker route (lines 119–125); using it unchanged for Jev would mislabel
  evidence. Review records are not physical HTTP-attempt counts.
- The [frontier wrapper](../../../../../src/forge/policy/semantic/supervisor.py#L809) records a start and dispatches
  under the shared deadline. The actual subprocess result supplies the decision's run/parent/root identity
  ([result mapping](../../../../../src/forge/policy/semantic/supervisor.py#L1094)); its run is a reviewer invocation,
  which can contain several downstream requests. Claude's output-format compatibility retry also reuses the child run
  ([retry](../../../../../src/forge/core/reactive/session_runner.py#L341)). Count physical launches/requests separately;
  a failed or unavailable review is not an alignment judgment.
- Current [shadow capture](../../../../../src/forge/policy/semantic/plan_check.py#L610) samples only fresh checker
  allows, never cache hits. The [candidate schema](../../../../../src/forge/policy/semantic/shadow.py#L50) freezes
  action, plan and route evidence but no originating evaluation/run/attempt ID. A later drain calls the same frontier
  with `command="supervisor-shadow"` and `purpose="shadow"`
  ([drain](../../../../../src/forge/policy/semantic/shadow_runner.py#L164)). Preserve existing single-emitter ownership:
  Claude dispatch emits usage; the Codex invoker owns its own emission
  ([dispatch](../../../../../src/forge/policy/semantic/supervisor.py#L660)). The drain's upstream outcome is another
  view of that work, not another reviewer call. Current replay does not prove original evaluation ancestry.

## Proposed A3 ownership

For the first capture, the experimental orchestrator should own a study root and a distinct evaluation child for each
case/repetition, passed explicitly to A1. Bind these to immutable slot, plan/action, question, model and
decision-setting identities in the journal. All physical attempts for one evaluation retain that run; host rejection
records no model attempt. Use a distinct consumer command so the screen cannot be mistaken for the existing `plan-check`
baseline.

The runner must reserve a slot durably before dispatch and retain unknown outcomes after interruption. A1's internal
request ID becomes available through attempt evidence; it cannot substitute for that prior reservation. Verify the
standard ledger join without emitting the same usage again. Missing telemetry or required cost must stop the approved
screen as specified in the study plan. Any need for exact reported decimal cost requires capture evidence before A1's
float conversion; standard rounded microdollars cannot reconstruct it. Freeze ambient grouping and session behavior as
part of the capture envelope rather than assuming `run_identity` controls provider-visible attribution.

Future runtime orchestration must bind Jev, escalation and audits through an explicit action/evaluation correlation key
while retaining distinct model runs and truthful process ancestry. The frontier is not a child process spawned by an
in-process Jev call. An audit drained later must retain its original evaluation reference separately from the drain's
actual run tree. Define that linkage, checker-route attribution and complete-action ownership before runtime work; do
not mutate global environment variables to make concurrent stages appear related.

No production API or telemetry-schema change is needed for the current offline packet. A paid screen needs fixtures for
durable capture and accounting; runtime joins and failure-inclusive audit sampling belong to later consumer work. Human
labels remain the quality authority; ledger joins, cache hits, review records and hypothetical skips establish neither
correct allows nor avoided Claude calls or subscription savings.
