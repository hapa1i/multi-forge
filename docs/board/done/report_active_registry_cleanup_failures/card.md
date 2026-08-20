# Report active-registry cleanup failures

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in Batch 1 PR #225 (`fd548c8e`) on 2026-08-20.

**Execution**: `agent/wave8-batch-1` from pushed `main` at `2bc3b56b`.

**Finding**: O088 (LOW correctness).

## Goal

Keep best-effort cleanup moving while making a failed stale active-session removal visible in `CleanResult` and the CLI
exit status.

## Verified Evidence

`core.ops.gc._clean_active_entries` catches every exception and discards it, unlike sibling cleaners that append
`(target, error)` to `result.failed`. `run_clean` therefore exits successfully while the stale entry remains.

## Acceptance Criteria

- Record each failed active-entry target and sanitized exception in `result.failed` and continue remaining entries.
- Count only confirmed removals in `categories_cleaned`.
- Preserve project scoping and the rule that cleanup does not trigger a global self-healing read.
- Pin mixed success/failure behavior and the human/JSON non-zero result surfaces.

## Verification

Focused GC/CLI coverage passed 101 tests. The integrated Batch 1 head passed 9,331 unit tests with 124 deselected, 992
regressions, full pre-commit, board/link checks, and all five GitHub checks.
