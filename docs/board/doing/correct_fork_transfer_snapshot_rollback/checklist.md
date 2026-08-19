# Correct fork transfer snapshot rollback checklist

Current focus: implement and verify the bounded order-32 correction without activating Wave 8.

- [x] Reproduce manifest/index cleanup with a retained child snapshot and stale same-name retry on merged `main`.
- [x] Create `agent/fix-fork-snapshot-rollback` from `0d8eb81a` and record the correction boundary.
- [x] Track only a transfer snapshot created by the current preparation attempt, including partial factory failure.
- [x] Remove the owned snapshot during rollback and surface an exact-path cleanup failure.
- [x] Add failure/retry, pre-existing-snapshot, and partial-factory regressions.
- [x] Sync the normative fork compensation wording without changing transfer snapshot durability.
- [x] Run 104 focused fork/session tests, `make test-unit` (9,309 passed, 1 skipped, 122 deselected), and
  `make test-regression` (929 passed).
- [x] Run targeted Docker session-lifecycle fork coverage (6 passed, 18 deselected) and `make pre-commit`.
- [x] Verify `docs/design.md` at 29,990 Opus-5 tokens, 965 local board links with none broken, diff hygiene, and a clean
  correction-only branch.
- [x] Prepare the verified correction for an independent draft PR without activating Wave 8 order 1.
- [ ] After merge, close this card and publish the completed-work record directly on `main`.

## Acceptance coverage

| Boundary                 | Fixture                                               | Assertion                                                        | Test tier       |
| ------------------------ | ----------------------------------------------------- | ---------------------------------------------------------------- | --------------- |
| Late preparation failure | real transfer factory; prompt combination raises      | child manifest, index row, and newly created snapshot are absent | regression      |
| Retry freshness          | parent transcript changes after failed attempt        | retry snapshot contains the new context, not the old context     | regression      |
| Existing ownership       | sentinel child snapshot exists before the attempt     | rollback leaves the sentinel byte-identical                      | regression      |
| Partial factory write    | factory creates the expected snapshot and then raises | rollback still removes the owned snapshot                        | unit/regression |
| Cleanup failure          | owned snapshot unlink raises after session rollback   | error names the retained path and removal action                 | unit            |
