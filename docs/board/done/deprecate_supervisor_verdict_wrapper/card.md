# Deprecate the supervisor verdict compatibility wrapper

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4).

**Lane**: `done/` -- shipped in PR #198 (`7fd701b5`) after all five GitHub checks passed; final deletion remains
release-gated.

**Finding**: O092's `parse_supervisor_verdict` subset.

## Goal

Mark the deliberately re-exported legacy wrapper as deprecated while keeping its exact return behavior for one release.

## Evidence and Authority

Reverified on `2745e5ed`: production has one caller and it already uses `parse_supervisor_verdict_with_status`. The
legacy wrapper remains deliberately exported from `forge.policy.semantic`, with direct consumers confined to four unit
and regression test files. Repository-wide source, test, resource, extension, entry-point, documentation, string-target,
and history searches found no other executable consumer. Commit `cff92fb9` introduced the status-bearing parser and
retained this wrapper when shadow auditing needed to distinguish parse failures from genuine low-confidence verdicts.
DG4 therefore requires a warning release rather than immediate deletion.

## Acceptance Criteria

- The wrapper remains importable and returns the same `SupervisorVerdict` while emitting one actionable `FutureWarning`
  with the replacement name.
- Internal tests/callers use the status-bearing API except a focused compatibility-shim test.
- Document the deprecation in the developer/release surface and run verdict, supervisor, and regression tests.

## Exclusions

Do not delete the wrapper/export in the first release carrying this warning, change unknown-verdict fail-open behavior,
or alter cached verdict identity. Final removal requires a new card that cites the released version which first carried
this warning and targets a subsequent release.

## Outcome

The legacy wrapper remains exported and delegates to the status-bearing parser exactly as before. Each call site
receives an actionable `FutureWarning` under Python's default filters; the warning names the fully qualified replacement
and is attributed to the caller with `stacklevel=2`. Internal behavior and regression tests now consume the warning-free
status-bearing API; one parameterized compatibility contract retains package-export, valid/fallback return parity,
warning-count, message, and attribution coverage.

Verification passed with 198 focused verdict/supervisor/regression tests, 272 semantic-policy tests, 9,207 unit tests
(one skip, 122 deselected), 913 regressions, a fresh-process consumer-module warning smoke, full pre-commit, design-size
checks, and board-integrity checks. No Forge workflow command was used.

## Closeout

PR #198 merged as `7fd701b5` with all five GitHub checks passing. Order 20 remains parked for a separate activation from
this closeout; the compatibility wrapper cannot be removed until the release gate above is independently satisfied.
