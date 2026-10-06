# Epic: Codex supervisor

Status: active coordination, 2026-10-06. B1 is selected for execution planning on `feat/plan-file-supervision`, based on
`main` at `6e0d1f4c`. Product implementation has not started. See the [coordination checklist](checklist.md) and
[B1 execution checklist](../plan_file_supervision/checklist.md). B2-B5 remain proposed and use separate execution
branches when selected.

## Problem and outcome

The maintainer codes in Codex and checks the work by hand. Everyday supervision must avoid API spend and use spare
Claude subscription quota; complex projects may use a paid route. Support supervision of those Codex sessions without
requiring a Claude planning conversation, then add visible feedback, review at turn completion, and optional native
Codex planning context.

Forge already has Codex policy hooks and a Codex supervisor execution lane. The missing contract is independent
selection of the plan source and reviewer: configuration still requires a Claude-backed planning target. The
[research](research.md) records the verified code, installed runtime, local usage measurement, and external
documentation.

## Members and dependencies

| ID  | Card                                                                               | Independently shippable outcome                                                      | Depends on                 |
| --- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------- |
| B1  | [Plan-file supervision with a fresh `claude -p`](../plan_file_supervision/card.md) | Supervise a Codex executor from a plan file; also test the fresh Codex reviewer      | None; first product card   |
| B2  | [Codex 0.160.1 test round](../../proposed/codex_0160_validation/card.md)           | Probe evidence for current hooks and native fork contracts                           | None; can run alongside B1 |
| B3  | [Warnings Codex can see](../../proposed/codex_policy_warnings/card.md)             | Deliver allowed-action feedback to the model and distinguish operator UI warnings    | B2                         |
| B4  | [Once-per-turn Stop review](../../proposed/codex_stop_review/card.md)              | Review accumulated work with a bounded number of supervisor calls                    | B1, B2                     |
| B5  | [Codex fork supervisor](../../proposed/codex_fork_supervisor/card.md)              | Review using native Codex context, recording reduced independence for shared sources | B1, B2                     |

B1 owns the shared supervisor configuration, model selection, plan-source contract, Claude isolation and subscription
auth checks, and whole-hook deadline/outcome handling. B2 supplies runtime evidence. B3 owns allowed-action feedback. B4
owns the review trigger and turn accounting. B5 owns native Codex context acquisition. Cards use separate execution
branches when activated.

## Shared contract

- Distinguish the executor runtime, plan source, supervisor runtime/model, and billing route. An explicit plan file must
  not require a dummy conversation ID. B1 supports fresh plan-only Claude and Codex reviewers. Existing Claude-target
  supervision remains supported under the new isolation requirements. B1 explicitly covers host Claude and Codex
  executors; plan-file supervision in a sidecar is refused until container plan/auth delivery is designed.
- Everyday use explicitly opts into the user's CLI-managed Claude subscription login with no automatic paid fallback.
  This is a separate supervisor auth policy: existing `claude-max` bindings retain inherited auth and the resolvable-key
  billing rule, as do the other three consumers. B1 isolates the opted-in child's environment/settings and rejects
  ambiguous auth, managed settings or gateways before inference. The user must keep account usage credits disabled;
  Forge cannot verify that condition or guarantee future vendor billing. Quota exhaustion produces an unavailable
  review, not an API retry or a claim that the work passed.
- Run the published Claude binary under the user's own login. Forge must not read, collect, or intermediate Claude login
  tokens. Describe runtime support without advertising access to subscription limits.
- Plan-file and native-fork supervision inspect the action's checkout read-only. B1 adds an enforced Claude tool
  restriction to fresh and existing resumed supervisors; `--restricted` alone does not prevent file edits. Evidence,
  plan version, actual reviewer, execution outcome and billing posture remain attributable. Model selection must affect
  both dispatch and recorded identity. Resumed B1 review retains planner-CWD history lookup but adds the action checkout
  explicitly, uses absolute action paths, and proves write prevention in both directories.
- Preserve existing deterministic policy decisions and supervisor failure behavior. Missing or failed review remains
  visible; an execution failure is not an alignment verdict. Before B3, B1 exposes review state/reason/time in
  `forge policy supervisor status [--json]` and unavailable/incomplete attempts in `forge telemetry activity [session]`.
  B3 distinguishes model context from operator UI warnings and respects `policy_summary_feedback` for model injection.
- Fit all per-file checks, retries and any cascade into a shared hook deadline with time reserved for cancellation and
  recording. Probe both executors' timeout behavior and bound reviewer lifetime even if only the hook is killed. Persist
  attempts so a killed hook leaves detectable incomplete work. Both policy-hook presets use 60 seconds; changing Codex's
  timeout or matcher requires re-enrollment. B4 chooses its Stop timeout explicitly.
- Keep the option for source-only feedback: verified plan passages and fixed Forge diagnostics, with Claude's generated
  wording retained out of the executor's context. This addresses the user's watermark concern without claiming a
  measured watermark property.
- Stop review evaluates work after edits have occurred. It cannot substitute for a pre-edit deny or undo an edit.
- B5 permits the executor thread as a fork source only with an approved plan file taking precedence. Record reduced
  independence: the fork can inherit implementation reasoning, and 0.160.1 offers no earlier-turn fork selector.

## Boundaries and sequencing

The [Jev epic](../../proposed/epic_jev_support/card.md) is separate. Its A2 uses B3 for Codex-visible warnings; A3 uses
B1 for the Claude escalation target. Jev is a paid API route and is not enabled by everyday subscription-only
supervision. Plan-file Claude supervision is B1, not a third epic. Team supervision remains with
[team supervisor plan context](../../proposed/team_supervisor_plan_context/card.md).

B1 can ship using the already established `apply_patch` deny path, with its own current-version end-to-end, isolation
and deadline tests plus host Claude Write/Edit coverage. It does not wait for the broader B2 experiment. Before B1's
first normative documentation update, complete the separately branched
[session partition](../../todo/partition_session_design/card.md) and
[runtime partition](../../todo/partition_runtime_design/card.md). B1 must not silently change the shared `LaneRecord`
format or other consumers' allowed-lane semantics; such work needs its own member card and dependency decision. B3–B5
consume only the contracts B2 actually verifies. Update normative design and end-user docs as each card ships; these
member plans do not change current product guarantees.

## Completion evidence

Every member must ship or receive an explicit board disposition. The integrated result must demonstrate a Codex action
reviewed from a plan file, model-visible allowed-action feedback, bounded Stop review, and a separately opted-in native
fork review. Verify the no-API everyday route, quota/error behavior, existing Claude supervision, and actual checkout
selection. Keep probe captures sanitized and retain the commands, versions, and outcomes used for each conclusion.
