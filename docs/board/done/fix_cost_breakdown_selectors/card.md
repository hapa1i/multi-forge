# Fix cost-breakdown selectors and run counts

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped with the metrics card in Batch 2 PR #226 (`5f02bb0f`) on 2026-08-20.

**Execution**: `agent/wave8-batch-2` from pushed `main` at `0eb68aea`.

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

Focused cost CLI/regression coverage passed 76 tests. The integrated Batch 2 head passed 97 focused tests, 9,331 unit
tests with 124 deselected, 1,005 regressions, targeted Docker cost visibility, full pre-commit, board/link checks, and
all five GitHub checks.
