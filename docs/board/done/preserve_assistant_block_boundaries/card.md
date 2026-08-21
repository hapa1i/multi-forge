# Preserve assistant block boundaries

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #224 (`4727deaa`) on 2026-08-20.

**Execution**: `agent/preserve-assistant-block-boundaries` from pushed `main` at
`d196b86665c5df047f7395bfc03f8af3d3fed0f3` on 2026-08-20.

**Finding**: O087 (LOW correctness).

## Goal

Recognize a standalone completion promise when it starts in a later assistant text block and the prior block has no
trailing newline.

## Verified Evidence

Both supported transcript projections collect assistant text blocks and concatenate them with `""`. The promise guard
then checks `splitlines()` for an exact standalone line, so adjacent blocks can collapse into one non-matching line and
reinject verification instructions.

## Acceptance Criteria

- Preserve a line boundary between adjacent assistant text blocks for both transcript shapes.
- Keep single-block, already-newline-terminated, malformed, and non-assistant handling unchanged.
- Add regressions for the collapsed-boundary case in both projections and negative substring controls.

## Verification

The focused helper/Stop slice passed 77 tests, including all 14 O087 regressions, and two targeted Docker Stop-hook
checks passed. The 9,328-test unit suite reported zero skips and 124 deselected; 983 regressions, full pre-commit,
documentation-size, board-link, and diff checks passed. All five GitHub checks passed on PR #224.
