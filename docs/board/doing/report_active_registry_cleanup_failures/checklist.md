# Report active-registry cleanup failures checklist

Current focus: active in Wave 8 Batch 1 on `agent/wave8-batch-1`; characterize mixed cleanup results before changing the
result boundary.

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

- [ ] Run focused core GC and CLI tests, the regression suite, full unit tests, and `make pre-commit`.
- [ ] Record exact verification evidence and commit this card without mixing another Batch 1 implementation.

Focused evidence (2026-08-20):

- Fail-first:
  `uv run pytest tests/src/core/ops/test_gc.py::TestRunClean::test_active_cleanup_records_failure_and_continues_scoped_removals -q`
  failed at the missing `CleanResult.failed` assertion (`1 failed`).
- Targeted regression and scope checks: `4 passed`.
- `uv run pytest tests/src/core/ops/test_gc.py tests/src/cli/test_gc.py -q`: `100 passed`.
- Focused Ruff, repository-configured Black, isort hook, and `git diff --check`: passed.

## Acceptance tests

| Boundary      | Fixture                                         | Assertion                                                                    | Tier            |
| ------------- | ----------------------------------------------- | ---------------------------------------------------------------------------- | --------------- |
| Mixed cleanup | two scoped stale entries; one clear raises      | successful item is counted, failure is recorded, later work continues        | unit/regression |
| Human apply   | partial `CleanResult` with active-entry failure | cleaned count and failure render; exit is non-zero                           | CLI unit        |
| JSON apply    | same partial result under `--json`              | stable result includes failed target/error; exit is non-zero                 | CLI unit        |
| Scope safety  | stale entries inside and outside selected root  | only detected targets are passed to the store; no global healing read occurs | unit            |
