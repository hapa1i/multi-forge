# Exercise the minimum supported Python version in CI

**Status:** Done. [PR #293](https://github.com/hapa1i/multi-forge/pull/293) merged on 2026-10-30 as `7ed8b5e9`, with a
tree identical to tested head `af2c1990`. See the [merged closeout](checklist.md#merged-closeout).

## Problem

The project declares Python `>=3.11,<3.14` and targets Python 3.11, but the unit and regression CI suites run under
Python 3.13. Installing Python 3.11 in the workflow does not establish that the tests use it. A change that breaks the
declared minimum version can therefore pass the current CI gate.

This gap predates the [test-suite runtime work](../../done/test_suite_runtime/card.md) and is separate from adopting
parallel workers.

## Evidence

- [pyproject.toml](../../../../pyproject.toml) declares `requires-python = ">=3.11,<3.14"`.
- [.python-version](../../../../.python-version) selects `3.13` for the project.
- [The Tests workflow](../../../../.github/workflows/test.yaml) installs `python-version: '3.11'`, then uses
  `uv sync --locked` and Make targets whose `uv` commands do not explicitly select that interpreter.
- The [serial CI baseline](https://github.com/hapa1i/multi-forge/actions/runs/40977896223) installed Python 3.11.17, but
  both pytest session headers report Python 3.13.11. The subsequent parallel CI runs report the same interpreter.

## Proposal

1. Add an explicit Python 3.11 test lane while retaining the existing Python 3.13 coverage.
2. Select the intended interpreter consistently for dependency installation and every `uv` command behind the unit and
   regression Make targets. Do not rely only on `actions/setup-python` or silently change the local development pin.
3. Fail early if the project environment's interpreter differs from the lane's selected version, and record the actual
   pytest interpreter in the job output, including worker processes when using xdist.
4. Check locked development and runtime dependencies on both versions. Resolve any minimum-version incompatibilities
   through the dependency-security process rather than relaxing the declared floor as part of CI wiring.
5. Run the pinned clean-wheel smoke on Python 3.11 using its `FORGE_WHEEL_SMOKE_PYTHON` override. Keep its interpreter
   explicit if the smoke also runs in the 3.13 lane; packaging checks complement the full unit and regression suites.

The CI matrix exposed an existing cold-start limit in the LiteLLM adapter after both complete suites passed. A fresh
Linux wheel can become healthy after the old 10-second deadline. Execution includes a bounded 30-second readiness budget
and delayed-start/timeout regressions so both supported-version smoke checks exercise an unmodified cold install. The
separate wheel-cleanup ownership policy remains unchanged.

## Acceptance

- CI runs the complete unit and regression suites on Python 3.11 and 3.13, with matching selected test identities except
  for documented version-specific cases.
- Each lane proves that its `uv` environment and pytest workers use the selected version, even with `.python-version`
  still set to `3.13`.
- The pinned clean-wheel install, backend start, health check and cleanup pass under Python 3.11.
- The reviewed lock remains enforced; dependency changes, if required, receive their normal review and validation.
- The testing guidelines describe the supported-version checks and how to reproduce either lane locally.

## Non-goals

- Changing the supported Python range or the local development default.
- Parallelizing integration tests or changing retry policy.
- Repairing the separately observed clean-wheel temporary-directory cleanup failure.
