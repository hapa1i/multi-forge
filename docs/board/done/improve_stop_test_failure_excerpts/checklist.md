# Improve Stop test-suite failure excerpts checklist

Current focus: complete -- the Stop diagnostic follow-up shipped in Batch 1 PR #225 and the card is closed.

## Phase 1 -- Pin the diagnostic failure

- [x] Recheck current `main`: failure reporting selects `stderr or stdout`, then bounds the start of that stream, so
  warning-only stderr can hide a useful stdout failure summary.
- [x] Add a mixed-stream regression with a long pytest header, a late failing-test identifier on stdout, and unrelated
  stderr noise.
- [x] Pin redaction-before-selection, a 200-character maximum, and byte-identical displayed/persisted error content.

## Phase 2 -- Implement

- [x] Select the most useful bounded failed-test context across both streams without exposing secrets or unbounded text.
- [x] Preserve the fixed `uv run pytest` argv, no-shell execution, incomplete classification, retry limits, timeout
  behavior, and fail-open infrastructure posture.

## Phase 3 -- Verify and publish

- [x] Run focused Stop-verification unit/regression tests and scoped static checks.
- [x] Run the targeted Docker method and `make pre-commit` on the integrated Batch 1 branch.
- [x] Record exact focused verification evidence without mixing another Batch 1 implementation.
- [x] Commit this card without mixing another Batch 1 implementation (`664bb28b`).
- [x] Merge Batch 1 as `fd548c8e`, confirm all five GitHub checks, record the closeout, and move this card to `done/`
  with the other Batch 1 cards.

## Verification evidence

- Fail-first:
  `uv run pytest tests/regression/test_bug_d006_stop_test_suite_contract.py -k prefers_late_stdout_summary_after_redaction -q`
  failed because warning-only stderr displaced the late stdout failure ID.
- Focused:
  `uv run pytest tests/src/cli/test_stop_verification.py tests/regression/test_bug_d006_stop_test_suite_contract.py -q`
  -- `22 passed in 0.39s`.
- PR review fail-first: the captured-log regression failed because `ERROR root:...` records consumed the 200-character
  bound before the later `FAILED <node-id>` summary. The final selector anchors on pytest's short-summary marker and
  prefers `FAILED` over `ERROR` in its markerless fallback; the same coverage also pins an ERROR-only short summary.
- Static: `uv run ruff check` on the four touched Python files and `git diff --check` both passed.
- Targeted Docker:
  `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py::TestStopVerificationDocker::test_fixed_suite_failure_prefers_late_stdout_summary`
  -- `1 passed in 10.37s` with captured ERROR-log noise ahead of the short summary.
- Integrated Batch 1 head after PR review: `make test-unit` -- `9,331 passed, 124 deselected`; `make test-regression` --
  `992 passed`; `make pre-commit` -- passed.

## Acceptance tests

| Boundary          | Fixture                                                    | Assertion                                                                    | Tier            |
| ----------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------- | --------------- |
| Mixed streams     | long stdout ending in failing node ID; warning-only stderr | diagnostic retains the failing node ID and de-prioritizes noise              | regression      |
| Secret boundary   | secret spans the would-be excerpt boundary                 | redaction occurs first; neither persisted nor displayed text leaks it        | regression      |
| Shared diagnostic | one failed fixed-suite run                                 | displayed and persisted excerpt content match and are at most 200 characters | unit/regression |
| Runtime contract  | pass, timeout, launch error, and max-iteration controls    | existing allow/block/fail-open behavior and fixed argv remain unchanged      | unit            |
