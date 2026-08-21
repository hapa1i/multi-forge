# Correct daily-review regressions

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #229 (`da34bcb3`) on 2026-08-21 with all five GitHub checks passing.

**Related shipped work**:

- [`correct_wave8_merged_regressions`](../../done/correct_wave8_merged_regressions/card.md) (provider dispatch seam)
- [`reject_unknown_workflow_policy_keys`](../../done/reject_unknown_workflow_policy_keys/card.md) (workflow config
  types)
- [`improve_stop_test_failure_excerpts`](../../done/improve_stop_test_failure_excerpts/card.md) (pytest diagnostics)

These are post-merge edge cases in PRs #222, #223, and #225. They do not reopen or change the finding credit of the
shipped Wave 8 members.

## Goal

Close three independently reproduced daily-review defects: keep local LLM setup failures out of provider traces, reject
booleans in manifest integer controls, and retain colored pytest failure identifiers in Stop diagnostics.

## Verified failures

| Boundary          | Reproduction                                                               | Incorrect result                                                          |
| ----------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Provider dispatch | real lazy LiteLLM/OpenRouter client with deterministic missing credentials | one incomplete provider trace despite no SDK client or request            |
| Workflow config   | `filter.max_content_length: false` on a matching reviewed branch           | config builds and the write is allowed without a reviewer call            |
| Stop diagnostic   | real failing pytest run with `PY_COLORS=1` and warning-only stderr         | selector returns unrelated stderr instead of the colored `FAILED` node id |

## Scope

- Carry an optional dispatch signal through the core LLM protocol and fire it only immediately before an SDK generation
  request, after credential resolution, client construction, and local request shaping.
- Reject `bool` for manifest-backed `max_content_length`, `throttle_seconds`, and `max_cache_entries` while preserving
  actionable workflow-entry and field context.
- Remove terminal control sequences after decoding and before redaction, pytest-summary selection, and bounding.

## Constraints

- Preserve one downstream lifecycle record per Forge request, provider capability gating, cost joins, auth retry,
  streaming response shape, and direct non-proxy core LLM callers.
- Preserve the fixed `uv run pytest` argv, inherited session environment, redaction-before-boundary rule, 200-character
  limit, result classification, and fail-open infrastructure posture.
- Keep Wave 8 Batch 5 parked; this independent correction is not a batch member or new Wave 8 finding.

## Acceptance criteria

- LiteLLM and OpenRouter missing-credential/client-construction failures remain trace-free in streaming and
  non-streaming modes; a request that reaches the SDK and fails still writes exactly one incomplete trace.
- Boolean values for all three integer controls fail workflow construction with the workflow entry and field named;
  valid integers and `max_content_length: null` retain their existing behavior.
- Forced-color mixed-stream pytest output retains the failing node id, strips terminal controls, redacts secrets before
  truncation, and persists/displays the same bounded diagnostic.
- Focused unit/regression tests, required proxy and policy-hook integration tests, full unit/regression suites,
  pre-commit, board/link, and diff checks pass before publication.
