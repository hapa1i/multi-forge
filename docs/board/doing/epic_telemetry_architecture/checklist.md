# Epic: Telemetry Architecture -- Coordination Checklist

Branch: `unified_backend`. Card: [card.md](card.md).

## Current Focus

Keep telemetry architecture as the active planning cursor after `upstream_downstream_ledgers` landed. The epic has
chosen `unified_backend` as the next active member so the downstream source key can land before remote reconciliation
adds more OpenRouter-specific source logic.

## Active Coordination

- [x] Move the telemetry architecture epic to `docs/board/doing/epic_telemetry_architecture/`.
- [x] Pause `openrouter_remote_reconciliation` after Phase 0 instead of starting Phase 1 by inertia.
- [x] Update the board contract and board README so active epics are first-class board citizens.
- [x] Require member cards to link their epic near the top of `card.md`.
- [x] Update member links for `openrouter_remote_reconciliation`, `unified_backend`, and `upstream_downstream_ledgers`.
- [x] Re-read `unified_backend` as a foundation candidate and record whether it should run before remote reconciliation:
  defer it. `backend_id` is the right source key, but the card is a larger config/auth/template/CLI refactor.
- [x] Re-read `upstream_downstream_ledgers` as a foundation candidate and record whether it should run before remote
  reconciliation: run it first. It fixes the telemetry plane shape that remote reconciliation should plug into.
- [x] Decide next execution card: `upstream_downstream_ledgers`.
- [x] Update the chosen member card's status/checklist and move it to `doing/`.
- [x] Close `upstream_downstream_ledgers` after merge and move it to `done/`.
- [x] Update this epic's member table and sequencing text after the ledger foundation landed.
- [x] Choose `unified_backend` as the next active member after the ledger foundation.
- [x] Move `unified_backend` to `doing/` and compose its execution checklist.

## Sequencing Questions

- Does `openrouter_remote_reconciliation` become cleaner if `backend_id` exists first, or is its first version safely
  OpenRouter-specific?
- Does the two-ledger refactor need to precede remote reconciliation to avoid designing against soon-to-be-replaced
  local planes?
- If both foundation cards are still too large, what narrow slice should run first to unblock reconciliation without
  causing a second `emit.py` refactor?

**Decision (2026-06-17):** pause `openrouter_remote_reconciliation` and execute `upstream_downstream_ledgers` first.
Remote reconciliation should return after the upstream/downstream shape exists, so it can generalize around downstream
model-call evidence rather than hardening a second OpenRouter-specific telemetry surface. `unified_backend` remains the
source-key sibling; it can follow as the full model-source refactor or be sliced to a narrow `backend_id` precursor.

**Update (2026-06-18):** `upstream_downstream_ledgers` is done. The epic chooses `unified_backend` next so the source
identity key lands before remote reconciliation resumes.

## Next Coordination

- [ ] Keep `unified_backend` scoped to source identity and downstream attribution; do not fold remote reconciliation
  implementation into this branch.
- [ ] After `unified_backend` lands, decide whether remote reconciliation resumes next or whether another source-key
  follow-up is needed.

## Closeout

- [x] Record the sequencing decision in this checklist and in [card.md](card.md).
- [x] Move any non-selected active member cards to `todo/` or `paused/` according to their progress.
- [x] Commit the board-process and lane-state update before starting implementation on the selected member card.
