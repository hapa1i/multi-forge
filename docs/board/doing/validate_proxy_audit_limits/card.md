# Validate proxy-audit limits

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `doing/` -- implementation commit `51f3b60a` and integrated verification are complete on
`agent/wave8-batch-4`; await the shared Batch 4 review and merge.

**Finding**: O076 (LOW correctness).

## Goal

Reject zero and negative audit limits instead of letting Python slice semantics expand or invert the requested result.

## Verified Evidence

Both `proxy audit show` and `proxy audit diff` accept an unrestricted integer and apply `records[-limit:]`. `limit=0`
becomes `[-0:]` and returns every record; negative values drop a prefix rather than representing a maximum.

## Acceptance Criteria

- Use one positive-integer Click contract (`min=1`) for both audit leaves.
- Invalid values exit 2 before reading shards; positive/default limits preserve record order and JSON/human rendering.
- Add zero, negative, one, and default regressions for both commands.

## Verification

Run focused proxy-audit tests, full unit/regression suites, targeted telemetry integration, and `make pre-commit`.
