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

CI serial/parallel comparison and integration timings remain pending. These local results do not establish CI
performance or complete the card's acceptance gates.

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

The CI parallel candidate and adoption decision remain pending. Integration baseline and after-change measurements
belong to Part B and are still pending.

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
than four; the cap leaves capacity for other work on shared hosts. Local stability and serial-debugging checks pass; CI
comparison and integration timings remain pending.
