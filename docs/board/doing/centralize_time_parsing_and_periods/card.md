# Centralize timestamp, period, and relative-time primitives

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `doing/` -- active on `refactor/centralize-time-parsing-and-periods` from O044 closeout commit `ef9c27c1`.

**Findings**: O060, O061, and O094.

## Goal

Use one timezone-aware ISO parser and one local-period calculation primitive while keeping each CLI's documented
presentation and invalid-input policy explicit.

## Evidence and Authority

Rechecked on `ef9c27c1`: the three admitted telemetry period helpers still duplicate day/week/month bounds, and the
newer activity surface has a fourth lower-bound-only copy. Thirteen production sites outside the shared parser still
call `datetime.fromisoformat` directly with divergent offset, naive, and invalid-input behavior. Session and proxy
relative-time functions still deliberately differ in register and invalid fallback. The unchanged characterization slice
passes 679 tests. Authority:
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

## Implementation Outcome

`core.state.timestamps` now owns strict UTC-normalizing ISO parsing, an explicitly tolerant wrapper, transition-aware
local period bounds, and named compact/full-word relative-time styles. All 13 former direct production
`datetime.fromisoformat` readers now select their naive and invalid-input policies through that boundary. The four
period callers retain their existing `all` sentinels, and the session and proxy surfaces retain their distinct relative
output registers.

Durable readers that historically accepted naive timestamps opt into naive-as-UTC compatibility. Session display,
throttle state, and team policy state remain strict; status-line reset parsing becomes strict, and valid non-UTC offsets
normalize to UTC. No retention range, stored timestamp, CLI JSON field, or end-user command contract changed.

Verification on the branch covers 721 focused tests, 7 targeted Docker proxy integrations, 9,064 unit tests (one skip,
122 deselected), and 898 regressions. `docs/design.md` records the shared timestamp boundary; end-user documentation
needs no edit because command syntax, output contracts, and durable formats remain unchanged. The targeted integration
gate also repaired one stale test invocation of the removed `forge proxy costs show` path to use the authoritative
`forge telemetry costs show` command.

Full pre-commit passes after import and Markdown normalization. The board audit resolves all 854 local path links across
331 board Markdown files and all five fragment links from the eight changed board documents. The Wave 7 graph is two
`done/`, one `doing/`, and 31 `todo/` members with valid epic backlinks; `git diff --check` passes.

## Exclusions

Do not change telemetry retention ranges, durable timestamp formats, CLI JSON fields, or silently reinterpret naive
durable-state timestamps.
