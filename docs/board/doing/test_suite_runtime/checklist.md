# Test-suite runtime execution

Started 2026-10-30 from `f9faedd9` on `codex/test-suite-runtime`.

Part A draft: [PR #290](https://github.com/hapa1i/multi-forge/pull/290).

## Current focus

Measure the CI parallel candidate against the completed serial baseline, and finish Part B's integration measurements.
The adopted four-worker default has three consecutive green local runs per suite, both matching Make serial runs pass,
and Part A's build, clean-wheel runtime and full pre-commit checks pass. Follow the card's two-PR split: Part A for
unit/regression parallelism, then Part B for integration trims. Keep the card in `doing/` until its accepted work is
shipped and verified. Measurements and trial failures are recorded in [benchmarks](benchmarks.md).

## Part A -- parallel unit and regression runs

- [x] Record serial wall time, collected/executed counts and failures for both suites on the unchanged test tree.
- [x] Review pytest-xdist and its added dependencies; trial per-test distribution without changing the lock.
- [x] Compare local worker counts and choose automatic workers capped at four, with numeric and serial overrides.
- [ ] Choose the CI default after its own serial/parallel comparison.
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
- [ ] Compare CI serial and parallel wall times before enabling parallelism there.
- [ ] Update CI commands only if the measured comparison supports adoption.

## Part B -- integration trims

- [ ] Record baseline integration wall time and release wheel/image build durations.
- [ ] Map each proposed CLI removal to its unit twin and retained real-process coverage; let coverage determine count.
- [ ] Preserve real-process `proxy validate`, `proxy set` and lifecycle/process checks.
- [ ] Share one release wheel among the three consumers while retaining independent build-policy tests.
- [ ] Share a QA image only if its caller-specific build arguments are immaterial to both tests.
- [ ] Run the affected integration tests and compare full-suite wall time and expected test-count reduction.

## Acceptance evidence

| Check                  | Fixture                                       | Assertion                                             | Evidence                                                                                      |
| ---------------------- | --------------------------------------------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Unit parallelism       | Full host unit suite                          | Same test count; three green runs; wall time improves | 11,234 passed each; walls 89.336 / 78.637 / 79.632 s; median 79.632 s versus 270.954 s serial |
| Regression parallelism | Full host regression suite                    | Per-test distribution; same count; three green runs   | 2,218 passed each; walls 99.525 / 97.558 / 97.849 s; median 97.849 s versus 295.250 s serial  |
| Serial debugging       | Adopted runner with zero workers              | Same suite executes serially                          | Unit: 11,234 passed; regression: 2,218 passed; both with `TEST_WORKERS=0`                     |
| CI adoption            | Same runner class and test tree               | Parallel wall time improves over serial               | Serial baseline passed: unit 288 s, regression 293 s; parallel comparison pending             |
| CLI removals           | Named unit twins and retained container tests | Assertions and real-process command coverage remain   | Pending                                                                                       |
| Shared release wheel   | QA, walkthrough and native-worker consumers   | Same wheel identity; independent build tests retained | Pending                                                                                       |

## Closeout

- [ ] Record benchmark commands, environment, counts, timings and non-passing results.
- [ ] Run applicable unit/regression, integration, build/runtime and pre-commit checks.
- [x] Open Part A draft [PR #290](https://github.com/hapa1i/multi-forge/pull/290); serial CI and pre-commit are green.
- [ ] Review the complete diff and open the authorized PR or PRs with concise validation evidence.
- [ ] After merge, sync completed-work records and move the card to `done/` only when all accepted scope has shipped.
