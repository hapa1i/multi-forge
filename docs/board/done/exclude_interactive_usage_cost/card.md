# Exclude interactive usage cost on both planes

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #173 (`a55ab218`).

**Finding**: D031.

## Goal

Apply the interactive-route exclusion to both usage events and joined cost-plane records so interactive harness spend
cannot re-enter Forge-added cost through a shared root.

## Evidence and Authority

Rechecked on merged `main` at `7280d177`: `_join_session_cost()` still builds roots and sums `per_run` before filtering
interactive events. A disposable characterization returned 500,000 micro-USD for an all-interactive root and 530,000 for
a mixed root whose only non-interactive cost was 30,000. The two-plane no-blend rule is load-bearing in
[`docs/design_telemetry.md` §A.8](../../../design_telemetry.md#a8-status-line-guidance-3611).

That shape is latent in the shipped system: §A.13 reserves the `claude_interactive` route without a production emitter,
and managed interactive launches do not freshly stamp the proxy correlation headers needed by the root-addressed cost
join; the characterization deliberately fabricates both preconditions, so this member hardens the reserved future route
rather than correcting observed live spend.

The retained final regression artifact collected `3 failed, 3 passed` on that unchanged production cursor. The failures
cover exact interactive re-entry, mixed-root command attribution, and presence-only partial status; controls preserve
included-root orphan cost, explicit inclusion, and activity event counts.

## Acceptance Criteria

- All-interactive roots are excluded from the cost query; excluded run ids are removed from shared-root results.
- Non-interactive siblings under the same root retain exact cost attribution.
- Activity views that intentionally include interactive work remain unchanged.
- Retain mixed-root regression coverage and run telemetry cost/activity unit tests.

## Compatibility and Exclusions

Do not change cost confidence rules, fabricate missing cost, or revive rejected finding O020.

## Implementation Outcome

- The event plane now establishes both the included roots and the run ids proven to belong to the interactive harness.
  All-interactive roots therefore never reach the root-addressed cost query.
- Mixed-root results discard only those proven interactive run ids from exact and presence-only cost records. Exact
  non-interactive siblings and cost-only children without a usage event remain accounted for.
- Activity callers that explicitly include interactive work retain their event counts and exact cost. Per-subtree
  snapshot suppression and partial-cost confidence semantics are unchanged.
- The existing design and end-user documentation already require this two-plane no-blend behavior, so the correction
  restores the documented contract without changing its text.

## Verification

- Focused usage-summary, activity, status-line, and adjacent mixed-root slice: `223 passed`.
- Marked regression gate: `821 passed`.
- Unit gate: `9001 passed, 1 skipped, 122 deselected`.
- Targeted activity CLI integration slice: `1 passed, 45 deselected`.
- Full pre-commit gate: all hooks passed after the expected Black/Markdown normalization pass.
- Board integrity: 293 Markdown files, 718 relative links and 2 changed-document fragments with none missing, and the
  Wave 6 lane graph at 8 done / 1 doing / 4 todo; the active checklist is 787 tokens and `git diff --check` is clean.
