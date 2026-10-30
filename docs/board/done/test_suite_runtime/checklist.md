# Test-suite runtime execution

Started 2026-10-30 from `f9faedd9` on `codex/test-suite-runtime`.

Part A: [PR #290](https://github.com/hapa1i/multi-forge/pull/290). Part B:
[PR #291](https://github.com/hapa1i/multi-forge/pull/291). The [CLI coverage map](cli_coverage.md) records every
approved removal and retained command check.

The [retained evidence](evidence/README.md) includes stability, identity-comparison, timing and CI outcome summaries.
Raw logs and reports in `/tmp` are temporary local artifacts, not retained evidence.

## Completed scope

Both PRs merged on 2026-10-30: Part B as `ece7bff7`, then Part A as `aa02a4fc`. Unit and regression targets use up to
four workers by default. The integration suite retains 521 cases; its artifact consumers share one release wheel.
Measurements, earlier failures and the integration cache caveat remain in [benchmarks](benchmarks.md).

Part B also shipped the bounded wheel-smoke teardown fix at the user's request. Its
[cleanup record](../../retired/wheel_runtime_cleanup_failure/card.md) is retired as folded into this closeout.

## Part A -- parallel unit and regression runs

- [x] Record serial wall time, collected/executed counts and failures for both suites on the unchanged test tree.
- [x] Review pytest-xdist and its added dependencies; trial per-test distribution without changing the lock.
- [x] Compare local worker counts and choose automatic workers capped at four, with numeric and serial overrides.
- [x] Reconfirm four-worker unit CI after the hook-ordering test fix: all 11,234 tests pass in 84 seconds step wall time
  versus 288 seconds serial.
- [x] Adopt the automatic four-worker cap for regression CI after the bounded-ID candidate improves step wall time from
  293 seconds serial to 121 seconds.
- [x] Diagnose the parallel-only Rich line-wrap assertion and preserve its phrase check by normalizing whitespace.
- [x] Repeat three consecutive complete unit runs after the hook-ordering fix: all 11,234 tests pass without skips or
  retries in 78.757 / 74.711 / 75.868 seconds. Exact multisets match the normalized baseline and accepted local runs.
- [x] Require three consecutive green regression runs with matching identities and all 2,218 tests passing without skips
  or retries; the regression suite is unchanged by the hook-ordering fix.
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
  3.11.17. Track minimum-version coverage separately in the
  [Python CI proposal](../../proposed/python_minimum_ci_coverage/card.md).
- [x] Run local `make build`, `./scripts/test-wheel-runtime.sh` and full `make pre-commit` for Part A before the CI
  workflow candidate.
- [x] Compare the first CI parallel candidate with the serial baseline: both suites used four workers and retained exact
  node IDs; all tests, runtime smoke and pre-commit passed.
- [x] Validate the three label-only parameter IDs (`ascii-byte-limit`, `utf8-byte-limit`, `oversized-header`): all five
  affected-function cases passed on four workers in 1.27 seconds (`bounded-ids.log` and `bounded-ids.xml`).
- [x] Pass full pre-commit for the label-only changes.
- [x] Repeat CI: 11,234 unit and 2,218 regression tests pass with no failures, skips or retries. Identities match both
  earlier runs after exactly two unit and one regression name mappings; payloads, order and assertions are unchanged.
- [x] Record the subsequent CI failure: 11,233 unit tests passed and one failed because hook emission was asserted in
  input order; returned result ordering and stdout passed. Regression/runtime steps were skipped; pre-commit passed.
- [x] Correct both emitted-label assertions to ignore completion order while retaining exact multiplicity, runtime
  pairing, returned-result order and stdout checks.
- [x] Pass all seven grouped-invoker tests on four workers in 0.81 seconds and full pre-commit for the hook-ordering
  fix.
- [x] Revalidate the CI Make commands after the fix: unit 84 seconds and regression 95 seconds, with exact IDs matching
  the bounded-ID candidate, no failures/skips/retries, and runtime/pre-commit passing.

## Part B -- integration trims

- [x] Record the integration baseline: 543 passed; runner 912.34 seconds; pytest 884.37 seconds; three wheel builds
  total 2.888 seconds and two QA image builds total 97.007 seconds.
- [x] Map the 22 approved removals to unit twins and retained real-process coverage in
  [cli_coverage.md](cli_coverage.md); their baseline test time totals 19.359 seconds.
- [x] Preserve real-process `proxy validate`, `proxy set` and lifecycle/process checks; strengthen three unit twins to
  retain stdout assertions.
- [x] Restore the default-direct twin's `Routing: direct` stdout check after review; the focused test and full
  pre-commit pass in Part B commit `5a30b345`. Product code and integration fixtures are unchanged.
- [x] Implement the shared release-wheel fixture while retaining independent build-policy tests.
- [x] Retain separate QA images because caller-specific runtime metadata differs.
- [x] Run full pre-commit for Part B and complete an independent static review with no remaining findings.
- [x] Preserve the interrupted first after-change run: Docker filesystem full; guarded-worker npm build `ENOSPC`;
  sidecar audit container exited with cause unproven by its trace. The incomplete 393 passed / 2 failed / 5 reruns and
  1,028.04-second runner wall time are invalid comparison evidence.
- [x] Reclaim 6.636 GB of unused build cache and remove only two owned, idle fixture containers, restoring 6.2 GiB
  available. No Part B code changed.
- [x] Pass all three targeted recovery checks without retries: 55.80 seconds on unchanged code; 5.8 GiB free afterward.
- [x] Pass the clean full integration suite: 521 passed, 13,613 deselected, no failures, errors, skips or reruns; runner
  842.31 seconds and pytest 833.73 seconds. The exact multiset equals the baseline minus the 22 mapped removals.
- [x] Confirm all four release-consumer cases and both independent build-policy cases pass. Wheel builds fall from three
  to one with the same SHA-256; both distinct QA image builds remain.
- [x] Record the timing limit: directly removed baseline work totals 21.211 seconds; the full 70.03-second runner
  reduction also includes image reuse and cache warming. Docker ends with 5.70 GiB free and no running containers.

## Acceptance evidence

| Check                  | Fixture                                       | Assertion                                             | Evidence                                                                                                                                        |
| ---------------------- | --------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit parallelism       | Full host unit suite                          | Same test count; three green runs; wall time improves | 11,234 passed each; renewed walls 78.757 / 74.711 / 75.868 s; median 75.868 s versus 270.954 s serial                                           |
| Regression parallelism | Full host regression suite                    | Per-test distribution; same count; three green runs   | 2,218 passed each; walls 99.525 / 97.558 / 97.849 s; median 97.849 s versus 295.250 s serial                                                    |
| Serial debugging       | Adopted runner with zero workers              | Same suite executes serially                          | Unit: 11,234 passed; regression: 2,218 passed; both with `TEST_WORKERS=0`                                                                       |
| CI adoption            | Same runner class and test behavior           | Parallel wall time improves over serial               | Measured CI unit 84 s vs 288 s serial; regression 95 s vs 293 s; all 11,234 / 2,218 tests pass with exact IDs matching the bounded-ID candidate |
| CLI removals           | Named unit twins and retained container tests | Assertions and real-process command coverage remain   | Clean run: 521 passed, exactly 543 baseline identities minus the 22 mapped removals; no failures, skips or reruns                               |
| Shared release wheel   | QA, walkthrough and native-worker consumers   | Same wheel identity; independent build tests retained | Three builds / 2.888 s become one / 0.463 s with the same SHA-256; all four consumer and two independent build-policy cases pass                |

## Closeout

- [x] Record benchmark commands, environment, counts, timings and non-passing results.
- [x] Complete the reopened unit stability, targeted, pre-commit and CI checks; unchanged regression and Part B
  integration/build/runtime evidence remain accepted.
- [x] Open Part A [PR #290](https://github.com/hapa1i/multi-forge/pull/290); renewed unit stability and CI pass after
  the hook-ordering fix, and both suites retain their measured improvement over serial.
- [x] Open Part B [PR #291](https://github.com/hapa1i/multi-forge/pull/291); full pre-commit, static review, CI and
  clean integration validation pass.
- [x] Review the implementation diffs and open both authorized PRs with validation evidence.
- [x] Retain the small acceptance summaries and source provenance under [evidence/](evidence/README.md), including the
  exact identity comparisons and the cleanup failure followed by its successful same-commit retry.
- [x] Record the pre-existing Python 3.11 coverage gap in a separate
  [proposed card](../../proposed/python_minimum_ci_coverage/card.md).
- [x] Record the repeated wheel-cleanup failure at Part B head `5a30b345` in a separate
  [cleanup record](../../retired/wheel_runtime_cleanup_failure/card.md). Both suites and runtime health passed, but
  cleanup left that CI job red. The fix at `acdb6503` passed a fresh CI run without retrying the failed attempt.
- [x] Verify the combined merged revision, sync completed-work records and move the card to `done/`.

## Merged closeout

Both accepted parts and the cleanup fix shipped through PRs #290 and #291 on 2026-10-30. On combined main `aa02a4fc`,
`make test-unit` passed all 11,234 cases in 84.19 seconds and `make test-regression` passed all 2,230 cases in 90.01
seconds. The latter includes 12 new cleanup cases; the historical 2,218-case timing and identity comparisons remain
unchanged. `./scripts/test-wheel-runtime.sh` passed installation, backend health, process-group exit and temporary-tree
removal on macOS.

The [combined-main CI run](https://github.com/hapa1i/multi-forge/actions/runs/41041753419) passed on its first attempt:
11,234 unit cases in 84.87 seconds, 2,230 regressions in 92.23 seconds, and wheel installation, health and teardown.
Unit tests emitted eight Python multiprocessing fork deprecation warnings. Together with PR #291 CI, this provides two
successful CI runs after the cleanup fix. Full `make pre-commit`, Markdown links and board lane checks passed after
formatting and the changelog token-cache refresh.

The [closeout summary](evidence/closeout-summary.json) retains combined verification. Testing guidelines document the
worker defaults, immutable shared wheel and bounded smoke teardown. Product architecture and end-user behavior are
unchanged. The [Python minimum-version CI proposal](../../proposed/python_minimum_ci_coverage/card.md) remains open.
