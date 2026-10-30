# Wheel-runtime cleanup execution

## Current focus

Review the verified fix in [PR #291](https://github.com/hapa1i/multi-forge/pull/291). The user explicitly requested this
fix in the existing Part B PR. Its execution branch is `codex/test-suite-runtime-integration`;
`codex/test-suite-runtime` owns the shared board documentation. The smoke helper is implemented; all 16 focused tests
and real macOS/Linux smokes pass. Final full pre-commit and CI passed on the first attempt; the card stays in `doing/`
until merged. [Retained evidence](evidence/validation-summary.json) includes log hashes and distinguishes the controlled
regression from the unknown historical writer.

## Implementation and verification

- [x] Confirm that backend stop signals the detached group and removes its registry entry before all members exit.
- [x] Preserve both historical cleanup failures; their logs do not identify the writer.
- [x] Capture the isolated smoke backend's verified group before stop removes its record.
- [x] Bound backend stop and the live-group wait to ten seconds each; inspect children after the leader exits and ignore
  zombie-only groups, which cannot write. Product backend code and signals are unchanged.
- [x] Preserve stop diagnostics and retain the temporary tree when teardown cannot be verified.
- [x] Preserve an earlier failure's exit status, and fail a successful smoke if cleanup fails.
- [x] Demonstrate that the controlled delayed writer fails against the old shell with exit 17 and the diagnostic
  `removal raced the backend writer`; the final control has one expected failure in 0.59 seconds and no finalizer error.
- [x] Demonstrate that the delayed-writer regression passes with the fix.
- [x] Pass all 16 final focused cases in 4.59 seconds, including stop failure, timeout, zombie handling and
  original-status preservation, with no failures, errors, skips or reruns.
- [x] Run the real clean-wheel smoke on macOS and Linux Python 3.13.11. The first Linux image launch failed with exit
  125 before the smoke; the retry using existing image `981f02144006` passed.
- [x] Pass full `make pre-commit` after the final test revisions.
- [x] Push cleanup commit `acdb6503` to PR #291.
- [x] Verify PR #291 on `acdb6503`: 11,234 unit and 2,230 regression cases passed, including 12 new cleanup cases; wheel
  start/health/cleanup and pre-commit also passed on the first attempt. See the [CI summary](evidence/ci-summary.json).

## Acceptance evidence

| Check            | Fixture                                                        | Required observation                                        | Current evidence                                  |
| ---------------- | -------------------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------- |
| Delayed teardown | Detached group with a child that writes after its leader exits | Deletion waits for the child's exit                         | Old shell fails with exit 17; fixed script passes |
| Failure handling | Stop failure or shutdown deadline exceeded                     | Temporary tree and diagnostics retained; nonzero status     | Final 16-case focused suite passes                |
| Original error   | Earlier failed smoke and failed cleanup                        | Original smoke status preserved                             | Final 16-case focused suite passes                |
| Real runtime     | Clean wheel on macOS/Linux and PR CI                           | Backend health succeeds; teardown completes before deletion | macOS/Linux local smokes and PR CI pass           |

## Closeout

- [x] Record implementation and validation results. The historical writer remains unknown; the controlled regression
  proves the ordering gap.
- [ ] After merge, fold the completed cleanup work into the test-suite runtime closeout and reconcile both cards.
