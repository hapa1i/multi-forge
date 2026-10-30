# Fix intermittent clean-wheel runtime cleanup failures

## Problem

The clean-wheel CI smoke can install the wheel, start LiteLLM and pass its health check, then fail while removing the
temporary virtual environment. Two independent PR heads hit `site-packages: Directory not empty`. A successful retry
does not establish that teardown is reliable.

This follow-up was proposed after recurrence during [test-suite runtime review](../../doing/test_suite_runtime/card.md).
It is separate from parallel test scheduling and the integration coverage trims.

## Evidence

- At `7bd19ebb`, [Tests attempt 1](https://github.com/hapa1i/multi-forge/actions/runs/40985566400/attempts/1) passed
  unit, regression and wheel start/health checks before temporary-venv removal failed. One same-commit job retry passed.
  The [retained summary](../../doing/test_suite_runtime/evidence/ci-final-evidence-summary.json) records the failure.
- At `5a30b345`, [Tests attempt 1](https://github.com/hapa1i/multi-forge/actions/runs/41034722366/attempts/1) passed
  11,234 unit and 2,218 regression tests, then printed the wheel smoke success message. One second later, `rm` failed
  removing the temporary venv's `lib/python3.13/site-packages` directory. The
  [recurrence summary](../../doing/test_suite_runtime/evidence/ci-review-part-b-cleanup-summary.json) records the
  result.
- [test-wheel-runtime.sh](../../../../scripts/test-wheel-runtime.sh) suppresses backend-stop output and ignores its exit
  status before immediately deleting the temporary root.
- [LiteLLMAdapter.stop](../../../../src/forge/backend/adapters/litellm.py) sends `SIGTERM` to the owned process group
  without waiting for it to exit. This permits overlap with deletion but does not identify the writer or prove the cause
  of either failure.
- The wheel environment is created after the unit and regression steps finish. The second failure occurred in Part B's
  serial CI, so a causal claim about xdist is unsupported.

## Proposal

1. Capture enough teardown diagnostics to establish whether backend stop succeeded and identify any process still
   writing into the temporary environment. Preserve useful diagnostics when cleanup itself fails after a successful
   smoke.
2. Reproduce the identified ordering problem with an isolated, controlled process. Correct cleanup synchronization at
   the narrowest owner; any wait must be bounded and apply only to processes owned by this smoke run.
3. Preserve the temporary-root path guard and meaningful exit status. A stop or cleanup failure must remain actionable;
   repeated deletion attempts or a CI rerun must not be the only correctness mechanism.

## Acceptance

- A regression test exercises the confirmed failure mechanism and fails before the fix.
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
