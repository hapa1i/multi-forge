# Python minimum-version CI execution

Started 2026-10-30 on `codex/python-minimum-ci`, based on main `849de170`.

## Current focus

Make Python 3.11 and 3.13 explicit CI lanes while retaining the local 3.13 pin, locked dependencies and existing
parallel unit/regression runners. Prove the controller and worker interpreters, compare exact selected test identities,
and verify the clean-wheel runtime on each selected version.

## Implementation

- [x] Verify the selection gap and inspect the existing locked runner and wheel-smoke interpreter override.
- [x] Select the matrix interpreter consistently for dependency sync and all `uv` invocations in each test job.
- [x] Refuse mismatched controller/worker interpreters and record their actual versions and executable paths.
- [x] Retain each suite's selected node IDs and compare the two lanes, failing on missing or unequal evidence.
- [x] Run the pinned clean-wheel smoke with an explicit matching interpreter in both lanes.
- [x] Document local reproduction, evidence ownership and unchanged development defaults.

## Acceptance

| Check                | Fixture                                                    | Assertion                                                                           |
| -------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Explicit selection   | `.python-version` remains 3.13; `UV_PYTHON=3.11`           | Locked sync, controller and all xdist workers use 3.11                              |
| Wrong interpreter    | Tiny suite with a deliberately mismatched expected version | Refuse before test execution                                                        |
| Evidence             | Tiny serial/parallel suites with deselected cases          | Record actual selected IDs and process identities; malformed/partial evidence fails |
| Cross-version parity | Complete unit/regression suites on both versions           | Exact selected identity multisets match and every suite passes                      |
| Clean install        | Fresh wheel environment on each version                    | Hash-checked install, backend startup, health and cleanup pass                      |

## Verification and closeout

- [x] Run focused evidence/selection tests and full unit/regression suites under both Python versions.
- [x] Check locked dependencies and run both pinned clean-wheel smoke checks without provider inference.
- [x] Pass full pre-commit, board links and documentation size checks; retain compact acceptance summaries.
- [x] Complete independent review and prepare the PR with retained local evidence.
- [ ] After owner merge, confirm final matrix/comparison CI, verify main, retain CI summaries, record the change log and
  move this card to done.

Dependency compatibility failures, if any, must be resolved through the existing dependency-security workflow. No
dependency, supported-version or test-selection exceptions have been approved or introduced.

## Initial local acceptance (2026-10-30)

Both lanes passed all 11,471 unit tests and 2,257 regressions. Python 3.11.14 took 107.46s / 109.51s and Python 3.13.11
took 98.27s / 98.04s respectively; these are validation timings, not a controlled performance comparison. The
[exact-identity comparison](evidence/local-comparison.json) confirms identical selected test multisets, with each
controller and all four workers on the expected version. Neither suite needed skips, reruns or version-specific cases.

Both pinned clean-wheel smokes passed hash-checked installation, local backend startup/health, process-group exit and
temporary-tree removal. Locked dependency exports and installed dependency graphs passed on both versions without pin
changes. [Check summaries](evidence/local-checks.json) retain input/log hashes and commands; the
[evidence guide](evidence/README.md) describes retention and the failure cases covered.

Full pre-commit passed. Independent review found two evidence issues, both corrected: a nested collection probe now
preserves its parent's report, and failed comparison summaries are uploaded in CI. Matrix/comparison CI remains the PR
merge gate. This card changes test infrastructure and maintainer workflow; product architecture and end-user behavior
are unchanged.

## CI fixture correction

The [first CI attempt](evidence/ci-first-attempt.json) failed 18 identical CLI text assertions in each version after
passing interpreter selection. An 80-column control reproduces the failures with matrix evidence disabled: the old
fixtures changed `COLUMNS` after Rich had captured a fixed width. Scoped fixture changes now set the intended width on
the existing console and restore its exact original value. The shared and rewind session fixtures and one activity table
test are covered; production rendering and assertions are unchanged.

All 217 focused cases from the affected modules and the new regression pass under `COLUMNS=80`. Subsequent concurrent
full-unit runs each had one unrelated failure: an evidence file not yet staged when the Markdown-link test ran, and a
Git probe exceeding its 0.5s deadline under load. Both cases and the new regression passed isolated sequential checks on
each version. Full pre-commit passed, and independent review found no issue with the scoped fixture repair.
[Correction evidence](evidence/local-fixture-correction.json) records all outcomes; final clean CI remains required.

The [second CI attempt](evidence/ci-second-attempt.json) passed all 11,471 unit tests in both lanes. Both regression
lanes then failed one cross-project session assertion because the CI temporary path split `subproject` across lines. The
helper now overrides the existing console width, and the subprocess guard starts narrower than `subproject`. Before this
additional repair, sequential full local regression runs already passed all 2,258 cases on both versions under
`COLUMNS=80` (95.88s on 3.11 and 104.85s on 3.13); the CI failure depended on the temporary path length.
