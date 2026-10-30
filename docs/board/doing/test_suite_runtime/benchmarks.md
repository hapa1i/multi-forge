# Test-suite runtime measurements

Local measurements use the same 10-CPU arm64 macOS host, Python 3.13.11, uv 0.9.18 and locked pytest 9.1.1. Initial
trials added pytest-xdist 3.8.0 and execnet 2.1.2 through exact `uv run --with` requirements without changing the lock.
The stability runs use those versions in the reviewed lock and the adopted Make targets. Tests and builds run
sequentially on this host. Source baseline: `f9faedd9`.

## Local results

Initial trial wall time includes uv/pytest startup and is recorded with `/usr/bin/time -p`. Pytest time is its reported
session duration. Unit selection is `tests/src -m 'not integration'`; regression selection is
`tests/regression -m regression`. Both use `-v` and have no retry option.

| Suite                           | Workers | Wall seconds | Pytest seconds | Result                                           |
| ------------------------------- | ------- | ------------ | -------------- | ------------------------------------------------ |
| Unit, initial baseline          | 0       | 287.00       | 283.13         | 11,233 passed; 1 existing link-check failure     |
| Regression, baseline            | 0       | 261.50       | 260.33         | 2,218 passed                                     |
| Unit, four-worker trial         | 4       | 73.56        | 72.44          | 11,233 passed; 1 line-wrapping assertion failure |
| Unit, uncapped auto trial       | 10      | 62.20        | 61.02          | 11,234 passed                                    |
| Regression, four-worker trial   | 4       | 81.60        | 80.93          | 2,218 passed                                     |
| Regression, uncapped auto trial | 10      | 62.48        | 61.83          | 2,218 passed                                     |

The initial unit failure is `test_markdown_link_hook_runs_without_present_markdown_paths`: the completed dependency
follow-up card still linked `dependabot_october_2026` in `doing/`. The target is in `done/`; the link is corrected
before parallel trials. The matching Make serial unit run below passes all 11,234 tests after that correction.

The first four-worker trial exposed a test-only formatting assumption: the longer xdist temporary path made Rich wrap
`enroll last` across two lines in the cleanup-project preview. The assertion now normalizes whitespace and retains the
same phrase check. Product behavior and the test count are unchanged.

## Local stability validation

The adopted Make targets run `--dist=load -n auto --maxprocesses=4`, selecting four workers on this host. Each suite
passed three consecutive complete runs after the final isolation changes. The corresponding serial commands are
`make test-unit TEST_WORKERS=0` and `make test-regression TEST_WORKERS=0`, so both sides include the Make prerequisites.

| Suite      | Parallel wall seconds, in run order | Median wall seconds | Matching Make serial wall seconds | Result per parallel run |
| ---------- | ----------------------------------- | ------------------- | --------------------------------- | ----------------------- |
| Unit       | 89.336 / 78.637 / 79.632            | 79.632              | 270.954                           | 11,234 passed           |
| Regression | 99.525 / 97.558 / 97.849            | 97.849              | 295.250                           | 2,218 passed            |

All six parallel runs have no failures, skips or retries. Exact JUnit test-case IDs and counts match across each suite's
three reports: 11,234 unit tests and 2,218 regression tests. The matching Make serial unit run passes all 11,234 tests.
The matching Make serial regression run passes all 2,218 tests in 295.250 seconds wall time (293.99 seconds reported by
pytest), with exact JUnit test-case IDs matching the first adopted parallel report. The earlier 261.50-second regression
baseline used the direct pytest trial command and remains separate from this comparison.

Against the matching Make serial runs, the parallel medians reduce unit wall time by 70.6% and regression wall time by
66.9% (3.40x and 3.02x faster respectively). Both `TEST_WORKERS=0` runs preserve the suite's complete test set.

The verbose `regression-adopted-1.log` also confirms that all 63 cases in `test_bug_walkthrough_interrupted_cleanup.py`
spread across workers: `gw0=11`, `gw1=16`, `gw2=23`, `gw3=13`.

The Makefile supplies `--maxprocesses=4` only when `TEST_WORKERS` is `auto` or `logical`. Numeric overrides omit the
cap: `TEST_WORKERS=8` requests eight workers, and `TEST_WORKERS=0` runs serially. This conditional is necessary because
the installed xdist implementation also caps numeric worker counts when `--maxprocesses` is present.

The numeric override smoke used
`PYTEST_ADDOPTS='-k test_proxy_relative_time_keeps_compact_compatibility_contract' make test-unit TEST_WORKERS=8`. Its
log reported `created: 8/8 workers` and one passing test in 8.89 seconds.

The CI comparison and Part B integration measurements below are separate from these local results.

## CI serial baseline

The serial baseline for [Part A PR #290](https://github.com/hapa1i/multi-forge/pull/290), head
`9dd4aadd9ac23bc63d0520c8f0755d6af5e41cb0`, completed successfully in
[Tests run 40977896223](https://github.com/hapa1i/multi-forge/actions/runs/40977896223). It used the existing direct
`uv run --locked pytest` commands, with the same suite selections as the local runs and no parallel or retry flags.

The runner image was `ubuntu-26.04`, version `20261025.179.1`, with runner agent `2.338.0`. Although `setup-python`
installed CPython 3.11.17, the pytest session headers confirm that uv ran both suites under Python 3.13.11 and pytest
9.1.1. pytest-xdist 3.8.0 was installed but the suites ran serially.

| Step                        | Wall seconds | Pytest seconds | Result                                          |
| --------------------------- | ------------ | -------------- | ----------------------------------------------- |
| Unit                        | 288          | 283.01         | 11,234 passed; 120 integration tests deselected |
| Regression                  | 293          | 290.92         | 2,218 passed                                    |
| Clean-wheel LiteLLM runtime | 16           | N/A            | Passed                                          |

Step wall times come from the completed job metadata and have one-second resolution. The complete Tests job took 611
seconds, including setup and cleanup. Both suites had no failures, skips or retries; the unit suite reported eight
`multiprocessing` fork deprecation warnings. The verbose log contains 11,234 unique passing unit node IDs and 2,218
unique passing regression node IDs, retained for the parallel comparison.

[Pre-commit run 40977896302](https://github.com/hapa1i/multi-forge/actions/runs/40977896302) also passed, with 143
seconds in its checks step. Completed job metadata, logs and extracted node IDs are saved locally under
`/tmp/forge-test-suite-runtime-20261030/ci-before*`. The local Part A `make build`, clean-wheel runtime smoke and full
`make pre-commit` also passed before the CI workflow candidate was prepared.

## First CI parallel candidate

[Tests run 40979617782](https://github.com/hapa1i/multi-forge/actions/runs/40979617782), head
`8d47d11abb3ad06d7368c1982821cd12ebed9543`, ran the Make targets with four workers for each suite. The image version,
runner agent, Python and pytest versions match the serial baseline. Both suites, dependency checks and the clean-wheel
runtime smoke passed; [pre-commit run 40979617790](https://github.com/hapa1i/multi-forge/actions/runs/40979617790) also
passed.

| Suite      | Serial step wall seconds | Parallel step wall seconds | Serial pytest seconds | Parallel pytest seconds | Result        |
| ---------- | ------------------------ | -------------------------- | --------------------- | ----------------------- | ------------- |
| Unit       | 288                      | 116                        | 283.01                | 112.80                  | 11,234 passed |
| Regression | 293                      | 328                        | 290.92                | 137.57                  | 2,218 passed  |

The exact passing node IDs match the serial baseline for both suites; no tests failed, skipped or retried. The 63
walkthrough cleanup cases also span all four workers: `gw0=9`, `gw1=29`, `gw2=8`, `gw3=17`. The complete Tests job took
473 seconds, including the 16-second successful runtime smoke. Pre-commit's checks step took 88 seconds.

Unit step wall time fell by 59.7%, meeting its CI improvement gate. Regression step wall time increased by 11.9%, so
regression adoption was deferred despite the lower pytest-reported duration. The candidate log prints the 262 KB
generated node ID for the oversized executor-header parameter twice, with long timestamp gaps around those lines. The
same case took 0.004-0.005 seconds in the local stability reports. Output handling was the leading explanation for the
extra wall time, but this trial alone did not establish the cause or justify claiming a regression CI speedup. Logs,
metadata, exact node IDs and comparison data are saved under `/tmp/forge-test-suite-runtime-20261030/ci-after*`.

A follow-up replaces three generated payload IDs with explicit labels:

| Test                                                 | Previous parameter ID                  | New parameter ID   |
| ---------------------------------------------------- | -------------------------------------- | ------------------ |
| `test_serialized_bytes_include_envelope`             | ASCII payload, about 30 KB             | `ascii-byte-limit` |
| `test_serialized_bytes_include_envelope`             | Escaped UTF-8 payload, about 60 KB     | `utf8-byte-limit`  |
| `test_malformed_executor_headers_remain_unavailable` | Oversized header payload, about 262 KB | `oversized-header` |

Only the IDs change: payload values, parameter order, assertions and test counts remain unchanged, including the first
two executor-header IDs. The recorded local three-pass stability evidence still covers that behavior. All five
affected-function cases (two unit and three regression) passed on four workers in 1.27 seconds; evidence is saved in
`/tmp/forge-test-suite-runtime-20261030/bounded-ids.log` and `bounded-ids.xml`. Full pre-commit passed.

## Bounded-ID CI validation and adoption

[Tests run 40982187613](https://github.com/hapa1i/multi-forge/actions/runs/40982187613), head
`b567e2e1d690dc5708c26f4394f2be045d770a9f`, passed on the same Ubuntu 26.04 image version `20261025.179.1`, runner agent
`2.338.0`, Python 3.13.11 and pytest 9.1.1 as the earlier runs. Both Make targets created four workers.

| Suite      | Serial step wall seconds | First parallel step wall seconds | Bounded-ID step wall seconds | Bounded-ID pytest seconds | Result        |
| ---------- | ------------------------ | -------------------------------- | ---------------------------- | ------------------------- | ------------- |
| Unit       | 288                      | 116                              | 122                          | 119.42                    | 11,234 passed |
| Regression | 293                      | 328                              | 121                          | 120.53                    | 2,218 passed  |

Passing test identities match both the serial baseline and first parallel trial after applying exactly the two unit and
one regression name mappings above. There are no other additions or removals, and no failures, skips or retries. The 63
walkthrough cleanup cases span all four workers: `gw0=21`, `gw1=27`, `gw2=8`, `gw3=7`. The complete Tests job took 274
seconds, versus 611 serial and 473 in the first parallel trial. The clean-wheel runtime smoke passed in 16 seconds.
[Pre-commit run 40982187659](https://github.com/hapa1i/multi-forge/actions/runs/40982187659) also passed; its checks
step took 138 seconds.

Adopt the Make targets' automatic four-worker cap for both CI suites: unit step wall time improved by 57.6% and
regression by 58.7% against serial. The bounded-ID candidate meets the regression wall-time gate; this comparison does
not establish output handling as the sole cause of the first trial's overhead. Raw logs, job metadata, passing IDs and
the comparison summary are preserved under `/tmp/forge-test-suite-runtime-20261030/ci-bounded*`.

## Part B integration baseline

[Part B PR #291](https://github.com/hapa1i/multi-forge/pull/291), head `e6248907`, removes the 22 reviewed CLI mirrors
listed in the [coverage map](cli_coverage.md) and shares one release wheel across the three consumers. Two unit twins
now preserve the removed stdout assertions. The full pre-commit check passed, and an independent static review found no
remaining issues. [CI tests](https://github.com/hapa1i/multi-forge/actions/runs/40979801953) passed all 11,234 unit and
2,218 regression cases plus the clean-wheel runtime smoke;
[CI pre-commit](https://github.com/hapa1i/multi-forge/actions/runs/40979801879) also passed. The clean full integration
comparison below completes the runtime validation.

The fixed-checkout integration baseline passed all 543 selected tests in 912.34 seconds runner wall time and 884.37
seconds reported by pytest, with 13,613 deselected and no failures, errors or skips. The 22 approved removals account
for 19.359 seconds of measured test time.

| Builder          | Baseline calls | Total seconds |
| ---------------- | -------------- | ------------- |
| `build_wheel`    | 3              | 2.888         |
| `build_qa_image` | 2              | 97.007        |

All three baseline wheel builds produced the same SHA-256. Both QA image builds remain necessary because their runtime
metadata differs. Raw baseline evidence is in
`/tmp/forge-test-suite-runtime-20261030/integration-part-b-before-summary.json` and
`/tmp/forge-test-suite-runtime-20261030/integration-part-b-before-builds.json`.

The first after-change run selected 521 tests, the expected reduction of 22, but was interrupted after Docker's
filesystem reached 100% usage. The guarded-worker npm build failed with `ENOSPC`; the sidecar audit container also
exited, although its trace alone does not establish the cause. The incomplete result was 393 passed, 2 failed and 5
reruns, with 1,012.34 seconds reported by pytest and 1,028.04 seconds runner wall time. These timings are invalid for
the before/after comparison. Evidence is preserved under
`/tmp/forge-test-suite-runtime-20261030/integration-part-b-after-disk-full.*`.

The interrupted run's build probe recorded one wheel build in 0.636 seconds with the same SHA-256 as the baseline, and
two QA image builds in 76.411 and 18.575 seconds. This confirms the observed build count and identity, but does not
establish that all shared-wheel consumers pass. Cleanup reclaimed 6.636 GB of unused build cache and removed only two
owned, idle fixture containers; Docker then had 6.2 GiB available. No Part B code changed. The three targeted recovery
checks passed in 55.80 seconds with retries disabled, leaving 5.8 GiB available.

## Part B clean integration comparison

The clean full run at `e624890706ff4c68eed2e9a5beaea3c0472fa89f` passed all 521 selected tests, with 13,613 deselected
and no failures, errors, skips or reruns. Its passing test multiset is exactly the baseline's 543 tests minus the 22
mapped removals, with no unexpected identity changes. All four release-consumer cases and both independent build-policy
cases passed.

| Measurement                     | Baseline   | Clean after-change |
| ------------------------------- | ---------- | ------------------ |
| Runner wall seconds             | 912.34     | 842.31             |
| Pytest seconds                  | 884.37     | 833.73             |
| Wheel builds / total seconds    | 3 / 2.888  | 1 / 0.463          |
| QA image builds / total seconds | 2 / 97.007 | 2 / 79.082         |

The shared wheel has the same SHA-256 as every baseline wheel. The two QA image builds remain separate, preserving their
distinct runtime metadata. Docker had 5.70 GiB free at both the start and end of the clean run, with a lowest observed
3.64 GiB free; no containers remained running afterward.

The observed runner reduction is 70.03 seconds (7.7%), but it is not an isolated measurement of the code change. The
baseline built the integration image; the clean retry reused it, and the targeted recovery checks warmed the worker
image build, which fell from 18.856 to 2.010 seconds. The directly removed baseline work totals 21.211 seconds: 19.359
seconds in the 22 removed tests plus 1.852 seconds in the two avoided wheel builds. The intervening disk-full run and
cache cleanup also changed cache state, so the remaining whole-run and image-build variation must not be attributed to
the implementation.

Exact identity, timing, build-count and disk evidence is summarized in
`/tmp/forge-test-suite-runtime-20261030/integration-part-b-comparison.json`; the clean run's log, JUnit report, build
probe and disk samples are preserved under `integration-part-b-after-clean*` in that directory. The interrupted run
remains separate evidence and is excluded from the comparison.

## Dependency review

The trial pins [pytest-xdist 3.8.0](https://pypi.org/project/pytest-xdist/3.8.0/) and
[execnet 2.1.2](https://pypi.org/project/execnet/2.1.2/). The declared Python and pytest requirements admit this
project's supported versions. Upstream advisory pages for
[pytest-xdist](https://github.com/pytest-dev/pytest-xdist/security/advisories) and
[execnet](https://github.com/pytest-dev/execnet/security/advisories) showed no published advisories when checked on
2026-10-30; this is a bounded check, not a guarantee of absence.

The [distribution controls](https://pytest-xdist.readthedocs.io/en/stable/distribution.html) support per-test `load`
distribution, automatic workers capped by `--maxprocesses`, and `-n 0` for serial execution. Four workers and uncapped
`auto` were the local candidates. The default is automatic selection capped at four workers, preserving an explicit
numeric override. Ten workers saved 11 seconds on unit and 19 seconds on regression but used about 65% more CPU time
than four; the cap leaves capacity for other work on shared hosts. Local stability and serial-debugging checks pass.
Both CI suites meet the improvement gate, and Part B's clean integration validation passes.
