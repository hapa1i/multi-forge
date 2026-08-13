# Deprecate the supervisor verdict compatibility wrapper

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4).

**Lane**: `todo/` -- accepted Wave 7 deprecation work; final deletion is release-gated.

**Finding**: O092's `parse_supervisor_verdict` subset.

## Goal

Mark the deliberately re-exported legacy wrapper as deprecated while keeping its exact return behavior for one release.

## Evidence and Authority

On `5777192a`, production uses `parse_supervisor_verdict_with_status`, but the wrapper remains intentionally exported
and has direct consumers in the test suite. DG4 requires a retained shim or deprecation window for such a surface.

## Acceptance Criteria

- The wrapper remains importable and returns the same parsed tuple while emitting one actionable `DeprecationWarning`
  with the replacement name.
- Internal tests/callers use the status-bearing API except a focused compatibility-shim test.
- Document the deprecation in the developer/release surface and run verdict, supervisor, and regression tests.

## Exclusions

Do not delete the wrapper/export in version 0.9.4, change unknown-verdict fail-open behavior, or alter cached verdict
identity. Final removal requires a new later-release card.
