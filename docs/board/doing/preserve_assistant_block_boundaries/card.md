# Preserve assistant block boundaries

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `doing/` -- active Wave 8 order 8; orders 9--19 remain parked.

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

Run focused verification-hook tests, full unit/regression suites, targeted Docker hook/session coverage, and
`make pre-commit`.
