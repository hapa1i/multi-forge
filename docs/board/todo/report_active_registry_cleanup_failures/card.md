# Report active-registry cleanup failures

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 8 order 9; parked.

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

Run focused GC/CLI tests, full unit/regression suites, and `make pre-commit`.
