# Cut test-suite wall time

**Lane:** `todo/` -- accepted on 2026-10-29; parked until execution starts.

**Origin:** Owner request on 2026-10-29 to find redundant tests after unit and regression runs reached 4-5 minutes and
integration about 14 minutes. Measurements used commit `eec804c1` on a 10-core macOS host with Docker limited to 6 CPUs
and 6 GB.

**Related:** [Testing guidelines](../../../developer/testing_guidelines.md) own suite boundaries and the regression
mandate. [Dependency security](../../../developer/dependency_security.md) owns adding a development dependency.

## Problem

Redundancy is not the main cost. Unit and regression tests run one at a time, and their time is concentrated in a few
subprocess-heavy tests. Nearly every integration test pays for a container exec and a CLI start, and the suite repeats
some expensive builds.

## Evidence

| Suite       | Tests  | Wall   | Concentration                                                      |
| ----------- | ------ | ------ | ------------------------------------------------------------------ |
| Unit        | 11,234 | 214 s  | 9,077 tests under 10 ms total 50 s; the top 100 are 43% of time    |
| Regression  | 2,218  | 248 s  | two files take 135 s (55%); 1,512 tests under 10 ms total 3.8 s    |
| Integration | 544    | ~830 s | median 0.8 s per test; wheel and image builds lead the slowest set |

The measured integration run took 1,177 s. A checkout replaced the working tree mid-run, and a test that bind-mounts a
checkout fixture then hung for 340 s before passing on rerun. The ~830 s figure excludes that attempt and matches the
usual run.

- **Serial execution.** `pytest-xdist` is not installed. `make test-unit`, `make test-regression` and
  `.github/workflows/test.yaml` run serially. Summed test time (209 s unit, 244 s regression) is within 5 s of wall
  time.
- **Little duplication.** AST and token-shingle comparison across 5,457 substantial tests found 2 exact cross-file
  duplicates and 22 near-duplicate pairs, mostly shared setup. Removing redundant fast tests would save seconds.
- **Integration CLI mirrors.** 25 tests repeat a unit test's setup and assertions through `docker exec`: 17 of 30 in
  `tests/integration/cli/test_proxy_commands_integration.py` and 8 of 48 in
  `tests/integration/cli/test_session_commands_integration.py`. Together they take about 22 s.
- **Repeated release builds.** `build_wheel()` runs separately in `test_qa_release_artifact.py`,
  `test_walkthrough_release_artifact.py` and `test_worker_native_controls.py`. `build_qa_image()` runs in the first and
  last, with different `runtime_track`, Claude and Codex build arguments.
- **Parallel-run hazards.** No unit or regression test binds a real socket. 37 files contain deadline, monotonic-clock
  or lock-contention logic, and 3 call `os.chdir` directly.
- **Floors.** The slowest unit test takes 6.6 s (native reviewer lease). The slowest regression test takes 17.8 s
  (`test_prompt_waits_for_terminal_mode_after_slow_preflight`, which must outlast an 8 s timer). No distribution can
  finish faster.

## Proposal

The two parts are independent and should ship as separate PRs.

### Part A -- parallel unit and regression runs

1. **Trial without changing the lock.** Run each suite with `uv run --locked --with pytest-xdist pytest ... -n auto`
   using per-test distribution. Repeat until results are stable, and record wall time beside the serial baseline on the
   same host.
2. **Fix isolation failures in tests, not product code.** Classify each new failure by cause: shared state, ordering,
   process groups or timing. Prefer widening a margin or injecting a deadline over pinning tests together. Use
   `xdist_group` with `--dist loadgroup` only for a documented residue.
3. **Distribute regression tests individually, not by file.** `test_bug_walkthrough_interrupted_cleanup.py` (111 s, 63
   tests) must spread across workers.
4. **Adopt.** Add `pytest-xdist` to the development group through the dependency-security process. Run `test-unit`,
   `test-regression` and the CI test workflow with `-n auto`, and document `-n 0` for serial debugging in `AGENTS.md`
   and the testing guidelines.

### Part B -- integration trims

1. **Review the 25 CLI mirror candidates.** Remove a candidate only after the checklist names its unit twin and the
   remaining real-process coverage for its command. Confirm that the twin asserts the same exit status and message; move
   any extra assertion to the twin first. Retain real-process coverage for `proxy validate` and `proxy set`, and keep
   tests that need real processes, such as `TestProxyCreateAndStart`. This coverage gate determines the removal count.
   `tests/src/cli/test_output_streams.py` covers stream separation through `CliRunner`; it does not replace
   real-entry-point coverage.
2. **Share one release wheel across the three consumers.** Replace their `build_wheel()` calls with one session-scoped
   fixture. Keep the independent builds in `test_runtime_build_constraints.py`, including its offline, hash-verified
   Forge build. Share one QA image only if neither caller depends on the differing build arguments; otherwise keep two
   images built from the shared wheel. Time `build_wheel()` and `build_qa_image()` before changing them.

| Change              | Expected saving | Basis                                                 |
| ------------------- | --------------- | ----------------------------------------------------- |
| Part A, unit        | unmeasured      | 209 s serial work; 6.6 s floor plus worker start      |
| Part A, regression  | unmeasured      | 244 s serial work; 17.8 s floor                       |
| Part B, CLI mirrors | up to ~22 s     | measured candidate time; depends on retained coverage |
| Part B, release     | est. 10-60 s    | wheel and image build times not yet separated         |

## Non-goals

- Deleting tests for speed alone. The walkthrough cleanup and B3 terminal tests are slow because they exercise the
  behavior they protect.
- Parametrizing groups of tests that differ only in constants. That would remove about 4,500 lines but saves no time.
- Running integration tests in parallel. Shared session containers and the 6-CPU Docker VM need a separate design.
- Changing `--reruns 2` or the regression mandate.
- Replacing the B5 watchdog prototype used by the Codex probe harness, or removing the two exact duplicates in
  `test_bug_d041_o031_o032_o033_cli_failures.py`. Both are small follow-ups.

## Risks

- **Timing flakes under contention.** Parallel workers compete for CPU, so deadline and lock-timeout tests such as
  `test_update_times_out_under_contention` and the watchdog budget tests can fail intermittently. Acceptance needs
  repeated green runs, not one.
- **CI differs from the host.** GitHub runners have fewer cores than the measuring host. Record CI wall time separately,
  and adopt parallel runs in CI only if they also improve there.
- **Lost real-entry-point coverage.** A removed mirror may have been the only real-process check for its command. The
  checklist must name the remaining coverage for each removal.
- **Shared wheel captures one tree.** A session-scoped wheel is built from the checkout once per run. That narrows
  exposure to source changes mid-run, but a test that needs a modified tree must build its own wheel.

## Decisions needed

1. Should CI adopt Part A, or only local runs?
2. How many consecutive green parallel runs per suite count as acceptance evidence?
3. `-n auto` or a fixed worker count, given that Docker and other agents share the host?

## Acceptance sketch

- Part A: serial and parallel wall times recorded for both suites, on the same host and in CI. Collected test counts are
  unchanged, the agreed number of consecutive parallel runs pass, and `-n 0` reproduces serial execution.
- Part B: the integration test count falls by the approved removals, each with a named unit twin and remaining
  real-process coverage for its command. The three release-artifact consumers share one wheel; dedicated build tests
  retain their independent builds. Integration wall time is recorded before and after.
- Docs: the `AGENTS.md` build and test list and the [testing guidelines](../../../developer/testing_guidelines.md).
