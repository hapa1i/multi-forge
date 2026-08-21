# Align supervisor missing-config exits checklist

Current focus: complete -- implementation commit `902f035c` shipped in Batch 3 PR #227 (`f3353042`).

## Phase 1 -- Pin enabling failures and idempotent controls

- [x] Recheck current `main`: `supervisor on` and `cascade on` catch `SupervisorNotConfiguredError`, print the setup
  recovery on stdout, and return zero; `reload` already uses stderr and exit 1.
- [x] Add fail-first regression coverage proving `on` and `cascade on` emit the actionable setup recovery only on stderr
  and exit 1 when no supervisor is configured.
- [x] Pin `off`, `remove`, and `cascade off` as idempotent exit-0 stdout results, plus configured on/cascade behavior.

## Phase 2 -- Implement

- [x] Route only enabling-action missing-config failures through the CLI error stream and non-zero exit without changing
  command-core mutation semantics.
- [x] Preserve compatibility checks, input validation precedence, configured behavior, and all direct `%policy`
  contracts.

## Phase 3 -- Verify and publish

- [x] Run focused supervisor/output/regression tests.
- [x] Run targeted policy integration on the integrated Batch 3 head.
- [x] Commit this card before starting the other Batch 3 cards.
- [x] Run the combined unit, regression, pre-commit, documentation, board/link, and diff gates on the integrated Batch 3
  head.
- [x] Publish all three cards in draft PR #227; close them together only after merge.
- [x] Confirm all five GitHub checks, merge Batch 3 as `f3353042`, and close all three cards together.

## Acceptance tests

| Boundary             | Fixture                          | Assertion                                               | Tier           |
| -------------------- | -------------------------------- | ------------------------------------------------------- | -------------- |
| Resume missing       | valid session without supervisor | stderr recovery, empty stdout, exit 1                   | CLI regression |
| Cascade-on missing   | same session                     | stderr recovery, empty stdout, exit 1                   | CLI regression |
| Idempotent teardown  | off/remove/cascade off           | stdout notice, empty stderr, exit 0                     | CLI regression |
| Configured mutations | suspended or supervised session  | existing resume/cascade state transitions remain intact | existing unit  |
| Compatibility        | incompatible project contract    | refusal still precedes mutation                         | existing unit  |

## Focused evidence (2026-08-21)

- Fail first: `uv run pytest tests/regression/test_bug_o080_supervisor_missing_config_exits.py -q` reported exactly two
  enabling-action failures and three passing idempotent controls (`2 failed, 3 passed`).
- Final: the complete supervisor, O080 regression, and output-stream files passed (`133 passed`).
- Focused Ruff passed for the changed source and test files; repository-pinned format hooks run before the card commit.
- Integrated: the direct container-boundary missing-supervisor matrix passed with the other two Batch 3 contracts
  (`3 passed` total); full unit, regression, and pre-commit gates passed on the combined head.
