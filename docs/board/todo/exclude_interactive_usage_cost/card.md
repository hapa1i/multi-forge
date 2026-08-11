# Exclude interactive usage cost on both planes

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending a fail-first regression.

**Finding**: D031.

## Goal

Apply the interactive-route exclusion to both usage events and joined cost-plane records so interactive harness spend
cannot re-enter Forge-added cost through a shared root.

## Evidence and Authority

On `246aaff1`, `_join_session_cost()` builds roots and sums `per_run` before filtering interactive events. The two-plane
no-blend rule is load-bearing in
[`docs/design_appendix.md` §A.8](../../../design_appendix.md#a8-status-line-guidance-3611).

## Acceptance Criteria

- All-interactive roots are excluded from the cost query; excluded run ids are removed from shared-root results.
- Non-interactive siblings under the same root retain exact cost attribution.
- Activity views that intentionally include interactive work remain unchanged.
- Retain mixed-root regression coverage and run telemetry cost/activity unit tests.

## Compatibility and Exclusions

Do not change cost confidence rules, fabricate missing cost, or revive rejected finding O020.
