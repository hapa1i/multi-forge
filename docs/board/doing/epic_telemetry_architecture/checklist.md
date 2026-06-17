# Epic: Telemetry Architecture -- Coordination Checklist

Branch: `openrouter_remote_reconciliation`. Card: [card.md](card.md).

## Current Focus

Make telemetry architecture the active planning cursor: align the board process for active epics, pause
`openrouter_remote_reconciliation` after Phase 0, review sibling foundation cards, and choose the next execution card.

## Active Coordination

- [x] Move the telemetry architecture epic to `docs/board/doing/epic_telemetry_architecture/`.
- [x] Pause `openrouter_remote_reconciliation` after Phase 0 instead of starting Phase 1 by inertia.
- [x] Update the board contract and board README so active epics are first-class board citizens.
- [x] Require member cards to link their epic near the top of `card.md`.
- [x] Update member links for `openrouter_remote_reconciliation`, `unified_backend`, and `upstream_downstream_ledgers`.
- [ ] Re-read `unified_backend` as a foundation candidate and record whether it should run before remote reconciliation.
- [ ] Re-read `upstream_downstream_ledgers` as a foundation candidate and record whether it should run before remote
  reconciliation.
- [ ] Decide next execution card: `unified_backend`, `upstream_downstream_ledgers`, or resume
  `openrouter_remote_reconciliation`.
- [ ] Update the chosen member card's status/checklist and move it to `doing/`.

## Sequencing Questions

- Does `openrouter_remote_reconciliation` become cleaner if `backend_id` exists first, or is its first version safely
  OpenRouter-specific?
- Does the two-ledger refactor need to precede remote reconciliation to avoid designing against soon-to-be-replaced
  local planes?
- If both foundation cards are still too large, what narrow slice should run first to unblock reconciliation without
  causing a second `emit.py` refactor?

## Closeout

- [ ] Record the sequencing decision in this checklist and in [card.md](card.md).
- [ ] Move any non-selected active member cards to `todo/` or `paused/` according to their progress.
- [ ] Commit the board-process and lane-state update before starting implementation on the selected member card.
