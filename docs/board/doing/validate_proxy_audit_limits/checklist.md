# Validate proxy-audit limits checklist

Current focus: implementation commit `51f3b60a` and all local gates are complete; publish the shared Batch 4 review.

## Phase 1 -- Pin invalid and control limits

- [x] Add fail-first zero and negative regressions for `proxy audit show` and `proxy audit diff`.
- [x] Prove invalid limits exit 2 before `read_audit_logs` or period-bound calculation runs.
- [x] Pin explicit limit one and each leaf's default in JSON and human controls, including record order.

## Phase 2 -- Implement and document

- [x] Define one positive-integer Click contract and use it for both audit leaves.
- [x] Preserve proxy filtering, periods, JSON shapes, table order, empty results, and redaction behavior.
- [x] Confirm the CLI reference and proxy guide do not describe `--limit`; no prose change is required.

## Phase 3 -- Verify and publish

- [x] Run focused proxy-audit, output-stream, and O076 regression tests.
- [x] Commit O076 as its own implementation boundary before starting O081.
- [x] Run the targeted audit/telemetry Docker boundary on the integrated Batch 4 head.
- [x] Run full unit, regression, pre-commit, documentation, board/link, and diff gates.
- [ ] Publish all three cards in one draft PR; close them together only after merge.

## Acceptance tests

| Boundary          | Fixture                        | Assertion                                         | Tier           |
| ----------------- | ------------------------------ | ------------------------------------------------- | -------------- |
| Show invalid      | zero and negative `--limit`    | usage error, exit 2, no shard or period read      | CLI regression |
| Diff invalid      | zero and negative `--limit`    | identical early rejection                         | CLI regression |
| Explicit minimum  | three ordered source records   | newest one retained in JSON and human output      | CLI regression |
| Default show/diff | more than 20/30 source records | shipped caps and chronological order are retained | CLI regression |

## Focused evidence (2026-08-21)

- Fail first: the new O076 regression produced four intended failures because zero and negative limits entered both
  callbacks and attempted period-bound reads; all eight positive/default controls passed (`4 failed, 8 passed`).
- Final: the proxy-audit, O076 regression, and output-stream slice passed (`65 passed`).
- Repository-pinned Ruff, isort, Black, mypy, Pyright, secret, and hygiene hooks passed for both changed Python files.
- Integrated: the real sidecar wrote audit telemetry and the host `proxy audit show` read it back; the 165-test combined
  slice, 9,331 unit tests, 1,035 regressions, and full pre-commit gate passed.
