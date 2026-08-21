# Improve Stop test-suite failure excerpts

**Origin**: Post-implementation review of
[`align_stop_verification_contract`](../../done/align_stop_verification_contract/card.md).

**Batch coordinator**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md) (execution/review
association only; not Wave 8 finding credit).

**Lane**: `done/` -- shipped in Batch 1 PR #225 (`fd548c8e`) on 2026-08-20.

**Execution**: `agent/wave8-batch-1` from pushed `main` at `2bc3b56b`.

## Goal

Make a failed fixed `test_suite` check surface the most useful bounded pytest context when stdout contains the failure
summary and stderr contains only plugin or warning noise.

## Evidence

- `src/forge/cli/hooks/verification.py` currently selects `result.stderr or result.stdout`, so any non-empty stderr
  suppresses stdout even when stdout owns the failing-test summary.
- Reversing the preference is insufficient: the first 200 stdout characters commonly contain pytest session headers, not
  the short failure summary near the end.
- The shipped contract is otherwise satisfied: diagnostics are bounded and redacted, the fixed argv is unchanged, and a
  non-zero exit remains `incomplete`.

## Acceptance Criteria

- A mixed-stream fixture retains a useful failing-test identifier while de-prioritizing unrelated stderr noise.
- Redaction happens before any excerpt boundary is selected, so truncation cannot expose a partial secret.
- Displayed and persisted diagnostics remain at most 200 characters and use the same content.
- The fixed `uv run pytest` argv, no-shell execution, result classification, and fail-open infrastructure posture do not
  change.
- Focused Stop-verification coverage passed 22 tests and the strengthened Docker boundary passed once. The integrated
  Batch 1 head passed 9,331 unit tests with 124 deselected, 992 regressions, full pre-commit, board/link checks, and all
  five GitHub checks.
