# Centralize timestamp, period, and relative-time primitives

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 refactor work.

**Findings**: O060, O061, and O094.

## Goal

Use one timezone-aware ISO parser and one local-period calculation primitive while keeping each CLI's documented
presentation and invalid-input policy explicit.

## Evidence and Authority

On `5777192a`, three period helpers implement the same day/week/month boundaries with different `all` sentinels, and
direct `datetime.fromisoformat` calls still disagree about naive timestamps. Session and proxy relative-time functions
also deliberately differ in register and invalid fallback. Authority:
[`docs/developer/coding_standards.md` "System boundaries"](../../../developer/coding_standards.md#system-boundaries-external-data)
and [`docs/design.md` "3.14 Cost tracking and spend caps"](../../../design.md#314-cost-tracking-and-spend-caps).

## Acceptance Criteria

- External timestamps pass through `core.state.timestamps.parse_iso` or a named tolerant wrapper with characterized
  naive/invalid behavior.
- One period primitive computes local today/week/month bounds; callers explicitly select the existing `all` sentinel.
- Relative-time callers share elapsed-time classification but preserve compact proxy and full-word session rendering
  through named styles unless a separate UX decision changes them.
- Run timestamp, trace, audit, cost, session-list, and proxy-list unit tests with DST, `Z`, offset, naive, future, and
  invalid fixtures.

## Exclusions

Do not change telemetry retention ranges, durable timestamp formats, CLI JSON fields, or silently reinterpret naive
durable-state timestamps.
