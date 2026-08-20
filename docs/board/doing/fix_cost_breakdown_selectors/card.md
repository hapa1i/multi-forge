# Fix cost-breakdown selectors and run counts

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `doing/` -- implementation and verification are complete in draft PR #226 on `agent/wave8-batch-2`; close with
the metrics card only after the batch merges.

**Finding**: O084 (LOW correctness).

## Goal

Make cost-view selectors unambiguous and report distinct Forge runs rather than relabeling request rows as runs.

## Verified Evidence

`show_cmd` receives `by_verb` but uses only `by_model`, so passing both silently selects model. The request-to-verb join
emits one record per downstream request, `_aggregate_by_verb` increments `invocations` per record, and the human table
labels that count `run(s)`.

## Acceptance Criteria

- Retain `--by-verb` as the explicit spelling of the default human view and reject `--by-model --by-verb` with a Click
  usage error before telemetry reads.
- Carry the validated `forge_run_id` through the internal verb record and count unique run IDs per verb.
- Keep `request_count` as the downstream request count and preserve reported/unavailable cost precedence.
- Keep the stable JSON envelope containing both model and verb summaries unless a separately reviewed schema change is
  approved.
- Add one-run/many-request, many-run, missing-ledger, and conflicting-selector regressions.

## Verification

Run focused telemetry-cost tests, full unit/regression suites, targeted Docker telemetry/cost integration, and
`make pre-commit`. Sync CLI/end-user cost-view docs if selector or detail wording is explicit there.
