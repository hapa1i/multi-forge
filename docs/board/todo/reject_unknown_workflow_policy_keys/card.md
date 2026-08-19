# Reject unknown workflow-policy keys

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 8 order 7; parked.

**Finding**: O083 (LOW external-data correctness).

## Goal

Fail closed and actionably when user-authored workflow-policy configuration contains unknown top-level or nested keys.

## Verified Evidence

`policy.deterministic.registry._build_workflow_policies` calls `dacite.from_dict` without strict configuration. A typo
such as `tagger_promt` is discarded and leaves the default empty `tagger_prompt`, silently changing enforcement.

## Acceptance Criteria

- Deserialize `WorkflowConfig` and nested dataclasses strictly.
- Convert unknown-key/type failures into the existing actionable policy-config error boundary, naming the workflow and
  offending field without a raw traceback.
- Preserve valid/defaulted config, workflow order, lazy imports, and policy evaluation behavior.
- Add top-level and nested typo regressions plus an unchanged valid-config control.

## Verification

Run deterministic/workflow policy tests, full unit/regression suites, targeted policy hook integration, and
`make pre-commit`. Update policy configuration docs if they currently imply tolerant unknown-key handling.
