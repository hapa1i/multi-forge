# Fix cost-breakdown selectors and run counts checklist

Current focus: active in Wave 8 Batch 2 on `agent/wave8-batch-2` from pushed closeout `0eb68aea`; pin O084 before
implementation.

## Phase 1 -- Pin selector and attribution failures

- [x] Recheck current `main`: `show_cmd` accepts both selectors, reads telemetry before resolving them, and silently
  chooses `--by-model`; the request-to-verb join drops `forge_run_id`, so `_aggregate_by_verb` counts request rows as
  invocations.
- [x] Add fail-first coverage proving conflicting selectors raise a Click usage error before any telemetry read.
- [x] Add one-run/many-request, many-run, missing-ledger, and reported/unavailable cost-evidence regressions that keep
  request counts distinct from run counts.

## Phase 2 -- Implement and document

- [x] Reject `--by-model --by-verb` before telemetry reads while retaining explicit `--by-verb` as the default human
  view and leaving the stable JSON envelope selector-independent.
- [x] Carry validated `forge_run_id` through verb records and count unique run IDs per verb without changing downstream
  request counts or reported-cost precedence.
- [x] Reconcile the cost-view wording in `docs/cli_reference.md` and `docs/end-user/proxy.md` at the Batch 2 integration
  boundary.

## Phase 3 -- Verify and publish

- [x] Run focused cost CLI/regression tests and targeted Docker telemetry/cost integration.
- [x] Commit this card without mixing the proxy-metrics implementation (`424be3c2`).
- [x] Run the combined unit, regression, pre-commit, documentation, board/link, and diff gates on the integrated Batch 2
  head.
- [ ] Publish with the metrics card in one Batch 2 PR; close both cards together only after merge.

Focused evidence (2026-08-20):

- Fail-first: the new O084 regression file produced four intended failures -- invalid selectors reached the cost reader,
  and one-run/many-request fixtures reported two or three invocations instead of unique run counts; two controls passed.
- `uv run pytest tests/src/cli/test_proxy_costs.py tests/regression/test_bug_o084_cost_breakdown_selectors.py tests/src/cli/test_output_streams.py -q`:
  `76 passed`.
- `./scripts/test-integration.sh tests/integration/proxy/test_cost_visibility_e2e.py::test_panel_with_subprocess_proxy_records_verb_cost -q`:
  `1 passed`.
- Repository hooks on the card's source, regression, and checklist plus `git diff --check`: passed.
- Integrated Batch 2 head: `97` focused, `9,331` unit with `124` deselected, and `1,005` regression tests passed; both
  targeted Docker boundaries and final `make pre-commit` passed.

## Acceptance tests

| Boundary               | Fixture                                      | Assertion                                                              | Tier            |
| ---------------------- | -------------------------------------------- | ---------------------------------------------------------------------- | --------------- |
| Selector conflict      | both human breakdown flags                   | Click usage error occurs before the cost reader runs                   | CLI regression  |
| Explicit default       | `--by-verb` and no selector                  | both choose the verb table; JSON retains both summaries                | CLI unit        |
| One run, many requests | two attributed requests with one run ID      | one invocation and two requests with summed reported cost              | unit/regression |
| Many runs              | distinct run IDs mapped to one verb          | invocation count equals unique runs, not request rows                  | unit/regression |
| Missing ledger         | request run ID has no matching usage event   | request remains in totals but is absent from attributed verb summaries | unit            |
| Cost evidence          | reported, free, and unavailable request rows | reported precedence and unavailable counts remain unchanged            | unit/regression |
