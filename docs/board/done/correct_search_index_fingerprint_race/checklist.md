# Stabilize search-index snapshot fingerprints checklist

Current focus: complete -- the order-20 race was corrected directly on `main` after PR #206 without activating Wave 7
order 28.

## Evidence and implementation

- [x] Challenge the automated finding against marker locking, Stop capture/enqueue ordering, the incremental handler,
  rebuild, and the original order-20 contract.
- [x] Reproduce both stale-state outcomes deterministically before changing production code.
- [x] Carry one path-bound `mtime`/size fingerprint from pre-extraction capture through state persistence.
- [x] Reject incremental or bulk extraction whose live artifact changes before the extracted document is accepted.
- [x] Retain the incremental marker when the artifact changes during store writes.
- [x] Make rebuild state describe the extracted bytes and emit explicit rerun guidance after concurrent drift.
- [x] Preserve the version-1 state schema, skip semantics, and same-size/same-`mtime` exclusion.

## Acceptance tests

| Boundary          | Fixture                                          | Assertion                                                           | Test file                                                    |
| ----------------- | ------------------------------------------------ | ------------------------------------------------------------------- | ------------------------------------------------------------ |
| Incremental race  | artifact becomes C while snapshot B is written   | state describes B; marker remains; retry indexes C                  | `tests/regression/test_bug_search_index_fingerprint_race.py` |
| Bulk rebuild race | artifact becomes C during full store replacement | state describes B; rerun warning is visible; next rebuild indexes C | `tests/regression/test_bug_search_index_fingerprint_race.py` |
| State API         | explicit fingerprint from an earlier snapshot   | exact values persist; a different path is rejected                  | `tests/src/search/test_index_state.py`                       |
| Producer path     | repeated unchanged Stop drain in Docker          | deferred artifact indexing remains operational and idempotent       | `tests/integration/cli/test_artifact_hooks_integration.py`   |

## Verification and closeout

- [x] Run the focused search/index/startup suites (`109 passed`).
- [x] Run `make test-unit` (`9,242 passed, 1 skipped, 122 deselected`) and `make test-regression` (`923 passed`).
- [x] Run the targeted Docker Stop/artifact integration (`1 passed, 12 deselected`).
- [x] Run full `make pre-commit`, diff checks, and board link/lane verification (363 Markdown files, 894 local links,
  none missing; only the two coordinating epics remain active).
- [x] Record the bounded correction in the shipped order-20 card, coordinating epics, review ledger, and change log;
  keep Wave 7 counts unchanged and order 28 parked until the correction reaches `main`.
