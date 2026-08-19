# Log `forge info` probe degradation

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 8 order 16; parked.

**Finding**: O081 (LOW conformance/diagnostics).

## Goal

Keep the global dashboard best-effort while leaving debug evidence when optional version, proxy, or session probes
degrade to unknown/empty data.

## Verified Evidence

`cli.info._gather_info_data` silently catches broad exceptions around package version, `uv`, proxy registry, and session
reads. Coding standards permit a best-effort fallback but require warning or debug logging rather than silent loss.

## Acceptance Criteria

- Log each recoverable external/state probe failure at debug level with enough probe identity to diagnose it.
- Remove impossible exception scaffolding where a direct standard-library value cannot fail.
- Preserve human/JSON shapes, the special actionable tracking-store error, best-effort continuation, and secret-safe
  output.
- Add caplog controls for each fallback without emitting ordinary stderr noise.

## Verification

Run focused info/output tests, full unit/regression suites, and `make pre-commit`.
