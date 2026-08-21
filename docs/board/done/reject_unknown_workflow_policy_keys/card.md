# Reject unknown workflow-policy keys

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #223 (`92d71a6d`) on 2026-08-20.

**Execution**: `agent/reject-unknown-workflow-policy-keys` from pushed `main` at
`071cfd920f3af9852e06f72fb5cbb1668737e0c5` on 2026-08-20.

**Finding**: O083 (LOW external-data correctness).

## Goal

Reject user-authored workflow-policy configuration actionably when it contains unknown top-level or nested keys.

## Verified Evidence

`policy.deterministic.registry._build_workflow_policies` calls `dacite.from_dict` without strict configuration. A typo
such as `tagger_promt` is discarded and leaves the default empty `tagger_prompt`, silently changing enforcement.

## Acceptance Criteria

- Deserialize `WorkflowConfig` and nested dataclasses strictly.
- Convert unknown-key/type failures into the existing actionable policy-config error boundary, naming the workflow and
  offending field without a raw traceback.
- Preserve valid/defaulted config, workflow order, lazy imports, and policy evaluation behavior.
- Preserve the existing atomic hook-build posture: a construction error runs no partial policy set, emits a diagnostic,
  and allows before engine-owned `fail_mode` applies.
- Add top-level and nested typo regressions plus an unchanged valid-config control.

## Verification

The deterministic/workflow slice passed 128 tests, the focused review slice passed 25, and two targeted Docker policy
hook checks passed. The 9,328-test unit suite, 969 regressions, full pre-commit, documentation-size, board-link, and
diff checks passed. All five GitHub checks passed on PR #223.
