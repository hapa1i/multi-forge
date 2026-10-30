# Fix intermittent clean-wheel runtime cleanup failures

**Status:** Retired. **Outcome:** folded into
[test-suite runtime](../../done/test_suite_runtime/checklist.md#merged-closeout) on 2026-10-30. The fix shipped in
[PR #291](https://github.com/hapa1i/multi-forge/pull/291), merged as `ece7bff7`; the combined parent work includes
[PR #290](https://github.com/hapa1i/multi-forge/pull/290), merged as `aa02a4fc`. This card did not ship independently
and receives no separate completion credit. Its checklist and evidence remain here as the implementation record.

Accepted for execution on 2026-10-30. The user requested the fix in
[PR #291](https://github.com/hapa1i/multi-forge/pull/291), on `codex/test-suite-runtime-integration`; the test-suite
runtime branch owns the shared board evidence. This explicit request authorizes including the cleanup fix in the
existing PR as an exception to the separate-PR default.

## Problem

The clean-wheel CI smoke can install the wheel, start LiteLLM and pass its health check, then fail while removing the
temporary virtual environment. Two independent PR heads hit `site-packages: Directory not empty`. A successful retry
does not establish that teardown is reliable.

This follow-up was proposed after recurrence during [test-suite runtime review](../../done/test_suite_runtime/card.md).
It is separate from parallel test scheduling and the integration coverage trims.

## Evidence

- At `7bd19ebb`, [Tests attempt 1](https://github.com/hapa1i/multi-forge/actions/runs/40985566400/attempts/1) passed
  unit, regression and wheel start/health checks before temporary-venv removal failed. One same-commit job retry passed.
  The [retained summary](../../done/test_suite_runtime/evidence/ci-final-evidence-summary.json) records the failure.
- At `5a30b345`, [Tests attempt 1](https://github.com/hapa1i/multi-forge/actions/runs/41034722366/attempts/1) passed
  11,234 unit and 2,218 regression tests, then printed the wheel smoke success message. One second later, `rm` failed
  removing the temporary venv's `lib/python3.13/site-packages` directory. The
  [recurrence summary](../../done/test_suite_runtime/evidence/ci-review-part-b-cleanup-summary.json) records the result.
- At both failing heads, [test-wheel-runtime.sh](../../../../scripts/test-wheel-runtime.sh) suppressed backend-stop
  output and ignored its exit status before immediately deleting the temporary root.
- [LiteLLMAdapter.stop](../../../../src/forge/backend/adapters/litellm.py) sends `SIGTERM` to the owned process group
  without waiting for it to exit. This permits overlap with deletion but does not identify the writer or prove the cause
  of either failure.
- The wheel environment is created after the unit and regression steps finish. The second failure occurred in Part B's
  serial CI, so a causal claim about xdist is unsupported.
- The [validation summary](evidence/validation-summary.json) retains local smoke results, controlled-regression
  evidence, remaining closeout and hashes of the checked logs. Raw logs remain ephemeral local files and are not
  committed.

## Implementation

The smoke runner calls `scripts/wheel-smoke-cleanup.py` before deleting its temporary root. The helper validates the
isolated backend registry and captures its process group before backend stop removes the record. Stop has a ten-second
timeout, followed by a ten-second deadline for live members of that group to exit. `ps` inspection includes children
after the leader exits and excludes zombies, which cannot write into the virtual environment.

Stop and process-inspection diagnostics remain visible. If stop or shutdown cannot be verified, cleanup retains the
temporary tree for inspection. Deletion failures remain nonzero, and an earlier smoke failure keeps its original exit
status. The temporary-root path guard remains in place. Product backend behavior is unchanged and the helper adds no
signals.

Real clean-wheel smokes passed on macOS and Linux with Python 3.13.11, including the reported group exit. An initial
Linux container launch failed before the smoke because its requested image tag was unavailable; the successful run used
existing image `981f02144006`. All 16 final focused cases passed in 4.59 seconds. The controlled delayed-writer
regression fails the old shell with exit status 17 and no finalizer error. Full pre-commit after the test revisions and
PR #291 CI passed on `acdb6503`, including runtime cleanup. The controlled reproduction does not identify the writer
responsible for the historical failures.

## Acceptance

- A regression test exercises the cleanup ordering gap with a controlled delayed writer and fails before the fix.
- The pinned clean-wheel smoke completes install, backend start, health and teardown on Linux CI and macOS without
  leftover owned processes or temporary files.
- Delayed shutdown, failed stop and failed deletion produce bounded behavior and useful diagnostics; an earlier smoke
  failure remains visible even if cleanup also fails.
- Cleanup never removes paths outside its verified temporary root or signals unrelated processes.
- Repeated CI runs provide stability evidence after the fix; both historical failures remain recorded.

## Non-goals

- Changing test selections, xdist scheduling or test retry policy.
- Treating a successful job rerun as a teardown fix.
- Broad changes to backend lifecycle semantics without evidence that they are required.
