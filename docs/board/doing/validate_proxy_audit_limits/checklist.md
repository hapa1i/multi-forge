# Validate proxy-audit limits checklist

Current focus: pin the O076 command-boundary failures before changing the shared Click type.

## Phase 1 -- Pin invalid and control limits

- [ ] Add fail-first zero and negative regressions for `proxy audit show` and `proxy audit diff`.
- [ ] Prove invalid limits exit 2 before `read_audit_logs` or period-bound calculation runs.
- [ ] Pin explicit limit one and each leaf's default in JSON and human controls, including record order.

## Phase 2 -- Implement and document

- [ ] Define one positive-integer Click contract and use it for both audit leaves.
- [ ] Preserve proxy filtering, periods, JSON shapes, table order, empty results, and redaction behavior.
- [ ] Update the CLI reference and proxy guide only where they describe the limit contract.

## Phase 3 -- Verify and publish

- [ ] Run focused proxy-audit, output-stream, and O076 regression tests.
- [ ] Commit O076 as its own implementation boundary before starting O081.
- [ ] Run the targeted audit/telemetry Docker boundary on the integrated Batch 4 head.
- [ ] Run full unit, regression, pre-commit, documentation, board/link, and diff gates.
- [ ] Publish all three cards in one draft PR; close them together only after merge.

## Acceptance tests

| Boundary          | Fixture                        | Assertion                                         | Tier           |
| ----------------- | ------------------------------ | ------------------------------------------------- | -------------- |
| Show invalid      | zero and negative `--limit`    | usage error, exit 2, no shard or period read      | CLI regression |
| Diff invalid      | zero and negative `--limit`    | identical early rejection                         | CLI regression |
| Explicit minimum  | three ordered source records   | newest one retained in JSON and human output      | CLI regression |
| Default show/diff | more than 20/30 source records | shipped caps and chronological order are retained | CLI regression |
