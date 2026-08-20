# Report active-registry cleanup failures checklist

Current focus: complete -- O088 shipped in Batch 1 PR #225 and the card is closed.

## Phase 1 -- Pin the failure

- [x] Recheck current `main`: `_clean_active_entries` catches and discards every exception, and `run_clean` does not
  pass its `CleanResult` into that cleaner.
- [x] Add fail-first coverage for one successful and one failed scoped active-entry removal, including the exact failed
  target and sanitized error.
- [x] Pin the human and JSON apply surfaces: partial cleanup remains visible and any recorded failure exits non-zero.

## Phase 2 -- Implement

- [x] Route the shared `CleanResult` into active-entry cleanup and append each failed target/error while continuing.
- [x] Count only confirmed removals and preserve project scoping plus the no-global-self-healing-read rule.

## Phase 3 -- Verify and publish

- [x] Run focused core GC and CLI tests, the regression suite, full unit tests, and `make pre-commit`.
- [x] Record exact verification evidence and commit this card without mixing another Batch 1 implementation
  (`17126b65`).
- [x] Merge Batch 1 as `fd548c8e`, confirm all five GitHub checks, record the closeout, and move this card to `done/`.

Focused evidence (2026-08-20):

- Fail-first:
  `uv run pytest tests/src/core/ops/test_gc.py::TestRunClean::test_active_cleanup_records_failure_and_continues_scoped_removals -q`
  failed at the missing `CleanResult.failed` assertion (`1 failed`).
- Targeted regression and scope checks: `4 passed`.
- `uv run pytest tests/src/core/ops/test_gc.py tests/src/cli/test_gc.py -q`: `101 passed`, including the restored
  zero-progress JSON failure pin requested in PR review.
- Focused Ruff, repository-configured Black, isort hook, and `git diff --check`: passed.
- Integrated Batch 1 head after PR review: `make test-unit` -- `9,331 passed, 124 deselected`; `make test-regression` --
  `992 passed`; `make pre-commit` -- passed.

## Acceptance tests

| Boundary      | Fixture                                         | Assertion                                                                    | Tier            |
| ------------- | ----------------------------------------------- | ---------------------------------------------------------------------------- | --------------- |
| Mixed cleanup | two scoped stale entries; one clear raises      | successful item is counted, failure is recorded, later work continues        | unit/regression |
| Human apply   | partial `CleanResult` with active-entry failure | cleaned count and failure render; exit is non-zero                           | CLI unit        |
| JSON apply    | same partial result under `--json`              | stable result includes failed target/error; exit is non-zero                 | CLI unit        |
| Scope safety  | stale entries inside and outside selected root  | only detected targets are passed to the store; no global healing read occurs | unit            |
