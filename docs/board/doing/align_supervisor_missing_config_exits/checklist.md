# Align supervisor missing-config exits checklist

Current focus: active first in Wave 8 Batch 3 on `agent/wave8-batch-3` from pushed closeout `34cbb601`; pin O080's
missing-prerequisite stream and exit matrix before implementation.

## Phase 1 -- Pin enabling failures and idempotent controls

- [x] Recheck current `main`: `supervisor on` and `cascade on` catch `SupervisorNotConfiguredError`, print the setup
  recovery on stdout, and return zero; `reload` already uses stderr and exit 1.
- [ ] Add fail-first regression coverage proving `on` and `cascade on` emit the actionable setup recovery only on stderr
  and exit 1 when no supervisor is configured.
- [ ] Pin `off`, `remove`, and `cascade off` as idempotent exit-0 stdout results, plus configured on/cascade behavior.

## Phase 2 -- Implement

- [ ] Route only enabling-action missing-config failures through the CLI error stream and non-zero exit without changing
  command-core mutation semantics.
- [ ] Preserve compatibility checks, input validation precedence, configured behavior, and all direct `%policy`
  contracts.

## Phase 3 -- Verify and publish

- [ ] Run focused supervisor/output/regression tests and targeted policy integration.
- [ ] Commit this card before starting the other Batch 3 cards.
- [ ] Run the combined unit, regression, pre-commit, documentation, board/link, and diff gates on the integrated Batch 3
  head.
- [ ] Publish all three cards in one Batch 3 PR; close them together only after merge.

## Acceptance tests

| Boundary             | Fixture                          | Assertion                                               | Tier           |
| -------------------- | -------------------------------- | ------------------------------------------------------- | -------------- |
| Resume missing       | valid session without supervisor | stderr recovery, empty stdout, exit 1                   | CLI regression |
| Cascade-on missing   | same session                     | stderr recovery, empty stdout, exit 1                   | CLI regression |
| Idempotent teardown  | off/remove/cascade off           | stdout notice, empty stderr, exit 0                     | CLI regression |
| Configured mutations | suspended or supervised session  | existing resume/cascade state transitions remain intact | existing unit  |
| Compatibility        | incompatible project contract    | refusal still precedes mutation                         | existing unit  |
