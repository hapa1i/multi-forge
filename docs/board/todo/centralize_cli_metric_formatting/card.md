# Centralize CLI metric formatting policies

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 refactor work.

**Finding**: O064.

## Goal

Replace ad hoc token and currency helpers with shared primitives that require callers to choose a named presentation
policy.

## Evidence and Authority

On `5777192a`, proxy, cost, activity, and status-line surfaces render equivalent values with different suffix case and
precision. Some differences are intentional (compact status line, detailed cost report), so a single hard-coded format
would create UX drift. Authority: [`docs/developer/cli_style_guidelines.md`](../../../developer/cli_style_guidelines.md)
and [`docs/design_appendix.md` "A.8 Status line guidance"](../../../design_appendix.md#a8-status-line-guidance-3611).

## Acceptance Criteria

- Shared numeric primitives expose explicit compact/detail and precision policies; no caller depends on hidden defaults.
- Golden tests pin every existing human output before helper replacement; JSON numeric fields remain numeric and
  byte-compatible.
- Run proxy, proxy-cost, activity/usage-summary, and status-line unit suites.

## Exclusions

Do not align user-visible strings merely for consistency, rename request counts, or absorb O084's separate CLI behavior
decision.
