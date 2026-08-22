# Centralize CLI metric formatting policies

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped independently in PR #183 (`cd3e50e8`) from order-5 closeout commit `62055bab`.

**Finding**: O064.

## Goal

Replace ad hoc token and currency helpers with shared primitives that require callers to choose a named presentation
policy.

## Evidence and Authority

Rechecked on `62055bab`: proxy metrics, cost tables, and status-line tokens still use uppercase suffixes with tenths,
while the activity summary intentionally rounds thousands to lowercase `k`. Currency still has six reviewed policies:
adaptive two-to-six-decimal cost detail, four-decimal sub-cent activity detail, fixed-cent session summaries, whole- or
fractional-cent status metrics, and four-decimal tiny-cap precision. Collapsing these into one hard-coded format would
create UX drift. The unchanged proxy, cost, activity, and status-line characterization passes 600 tests. Authority:
[`docs/developer/cli_style_guidelines.md`](../../../developer/cli_style_guidelines.md) and
[`docs/design_telemetry.md` "A.8 Status line guidance"](../../../design_telemetry.md#a8-status-line-guidance-3611).

## Acceptance Criteria

- Shared numeric primitives expose explicit compact/detail and precision policies; no caller depends on hidden defaults.
- Golden tests pin every existing human output before helper replacement; JSON numeric fields remain numeric and
  byte-compatible.
- Run proxy, proxy-cost, activity/usage-summary, and status-line unit suites.

PR #183 merged as `cd3e50e8`. Focused coverage passed 648 tests, targeted Docker status-line coverage passed 17 tests,
the full unit suite passed 9,109 tests with one skip and 122 deselections, and all 898 regressions plus pre-commit and
board-integrity gates passed. The post-merge closeout admits one independently verified residue member as the new order
7; the Wave 7 graph is six `done/`, zero member `doing/`, and 29 `todo/` cards.

## Exclusions

Do not align user-visible strings merely for consistency, rename request counts, or absorb O084's separate CLI behavior
decision.
