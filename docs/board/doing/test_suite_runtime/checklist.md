# Test-suite runtime execution

Started 2026-10-30 from `f9faedd9` on `codex/test-suite-runtime`.

Part A draft: [PR #290](https://github.com/hapa1i/multi-forge/pull/290). Part B draft:
[PR #291](https://github.com/hapa1i/multi-forge/pull/291). The [CLI coverage map](cli_coverage.md) records every
approved removal and retained command check.

## Current focus

Resolve the regression CI wall-time overhead before adopting it, and rerun Part B integration after recovering Docker
disk space. The five cases affected by the bounded parameter IDs pass; the CI recheck is pending. Part B's first
after-change run was interrupted with a full Docker filesystem and cannot supply comparison timings. Unit CI improved
from 288 to 116 seconds; regression passed but took 328 seconds versus 293 serial despite a lower pytest-reported
duration. Local three-run stability, matching serial runs and Part A's build/runtime/pre-commit checks all pass. Keep
the card in `doing/` until both PRs are shipped and verified. Measurements and trial failures are recorded in
[benchmarks](benchmarks.md).

## Part A -- parallel unit and regression runs

- [x] Record serial wall time, collected/executed counts and failures for both suites on the unchanged test tree.
- [x] Review pytest-xdist and its added dependencies; trial per-test distribution without changing the lock.
- [x] Compare local worker counts and choose automatic workers capped at four, with numeric and serial overrides.
- [x] Confirm four-worker unit CI improves wall time with the same exact test IDs.
- [ ] Choose the regression CI default after resolving its first candidate's wall-time overhead.
- [x] Diagnose the parallel-only Rich line-wrap assertion and preserve its phrase check by normalizing whitespace.
- [x] Require three consecutive green parallel runs per suite with unchanged test counts and no retries; all six JUnit
  reports have matching test-case IDs within each suite, no failures and no skips.
- [x] Confirm the 63 walkthrough cleanup regression cases spread across all four workers: 11 / 16 / 23 / 13 cases.
- [x] Add pytest-xdist 3.8.0 and execnet 2.1.2 through the lock; runtime/build exports remain unchanged.
- [x] Update Makefile and test instructions. Apply the four-worker cap only to `auto`/`logical`; numeric
  `TEST_WORKERS=8` and `TEST_WORKERS=0` omit the cap.
- [x] Verify `TEST_WORKERS=8` creates eight workers with a targeted passing smoke.
- [x] Run the matching Make unit suite with `TEST_WORKERS=0`: 11,234 passed in 270.954 seconds.
- [x] Run the matching Make regression suite with `TEST_WORKERS=0`: 2,218 passed in 295.250 seconds; exact JUnit
  test-case IDs match the first adopted parallel report.
- [x] Record the successful CI serial baseline: unit 288 seconds / 11,234 passed; regression 293 seconds / 2,218 passed;
  clean-wheel runtime and pre-commit also passed. Actual suite Python is 3.13.11 despite setup-python installing
  3.11.17.
- [x] Run local `make build`, `./scripts/test-wheel-runtime.sh` and full `make pre-commit` for Part A before the CI
  workflow candidate.
- [x] Compare the first CI parallel candidate with the serial baseline: both suites used four workers and retained exact
  node IDs; all tests, runtime smoke and pre-commit passed.
- [x] Validate the three label-only parameter IDs (`ascii-byte-limit`, `utf8-byte-limit`, `oversized-header`): all five
  affected-function cases passed on four workers in 1.27 seconds (`bounded-ids.log` and `bounded-ids.xml`).
- [x] Pass full pre-commit for the label-only changes.
- [ ] Repeat CI and compare identities using exactly those two unit and one regression name mappings; payloads, order,
  assertions and suite counts remain unchanged.
- [ ] Finalize CI commands only where measured step wall time supports adoption; unit meets the gate, regression remains
  pending.

## Part B -- integration trims

- [x] Record the integration baseline: 543 passed; runner 912.34 seconds; pytest 884.37 seconds; three wheel builds
  total 2.888 seconds and two QA image builds total 97.007 seconds.
- [x] Map the 22 approved removals to unit twins and retained real-process coverage in
  [cli_coverage.md](cli_coverage.md); their baseline test time totals 19.359 seconds.
- [x] Preserve real-process `proxy validate`, `proxy set` and lifecycle/process checks; strengthen two unit twins to
  retain stdout assertions.
- [x] Implement the shared release-wheel fixture while retaining independent build-policy tests.
- [x] Retain separate QA images because caller-specific runtime metadata differs.
- [x] Run full pre-commit for Part B and complete an independent static review with no remaining findings.
- [x] Preserve the interrupted first after-change run: Docker filesystem full; guarded-worker npm build `ENOSPC`;
  sidecar audit container exited with cause unproven by its trace. The incomplete 393 passed / 2 failed / 5 reruns and
  1,028.04-second runner wall time are invalid comparison evidence.
- [x] Reclaim 6.636 GB of unused build cache and remove only two owned, idle fixture containers; Docker has 6.2 GiB
  available. No Part B code changed.
- [x] Pass all three targeted recovery checks without retries: 55.80 seconds on unchanged code; 5.8 GiB remains free.
- [ ] Run the clean full integration suite and compare wall time and expected test-count reduction.

## Acceptance evidence

| Check                  | Fixture                                       | Assertion                                             | Evidence                                                                                                                                                  |
| ---------------------- | --------------------------------------------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit parallelism       | Full host unit suite                          | Same test count; three green runs; wall time improves | 11,234 passed each; walls 89.336 / 78.637 / 79.632 s; median 79.632 s versus 270.954 s serial                                                             |
| Regression parallelism | Full host regression suite                    | Per-test distribution; same count; three green runs   | 2,218 passed each; walls 99.525 / 97.558 / 97.849 s; median 97.849 s versus 295.250 s serial                                                              |
| Serial debugging       | Adopted runner with zero workers              | Same suite executes serially                          | Unit: 11,234 passed; regression: 2,218 passed; both with `TEST_WORKERS=0`                                                                                 |
| CI adoption            | Same runner class and test tree               | Parallel wall time improves over serial               | Four-worker unit 116 s vs 288 s serial; regression 328 s vs 293 s, adoption pending; exact IDs match                                                      |
| CLI removals           | Named unit twins and retained container tests | Assertions and real-process command coverage remain   | Coverage map and static review pass; baseline 543 passed; first after-change run selected 521 but was interrupted by disk exhaustion; clean rerun pending |
| Shared release wheel   | QA, walkthrough and native-worker consumers   | Same wheel identity; independent build tests retained | Baseline three builds total 2.888 s; interrupted run observed one build in 0.636 s with the same SHA-256; complete consumer validation pending            |

## Closeout

- [ ] Record benchmark commands, environment, counts, timings and non-passing results.
- [ ] Run applicable unit/regression, integration, build/runtime and pre-commit checks.
- [x] Open Part A draft [PR #290](https://github.com/hapa1i/multi-forge/pull/290); serial and first parallel CI checks
  are green, with regression wall-time adoption still pending.
- [x] Open Part B draft [PR #291](https://github.com/hapa1i/multi-forge/pull/291); full pre-commit, static review and CI
  pass.
- [ ] Review the complete diff and open the authorized PR or PRs with concise validation evidence.
- [ ] After merge, sync completed-work records and move the card to `done/` only when all accepted scope has shipped.
