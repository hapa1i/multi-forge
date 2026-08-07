# Preserve headless Codex concurrent deletion checklist

Current focus: complete; O003 shipped in PR #138 (`4a601dc2`) before D021 activation.

## Activation and reproduction

- [x] Merge D009 before activating O003 (PR #137, `cce6e8c6`).
- [x] Start `fix/preserve-headless-codex-concurrent-delete` from merged `main` at `cce6e8c6`.
- [x] Move D009 to `done/`, move O003 to `doing/`, create this checklist, and repoint inbound board links.
- [x] Add the marked O003 regression and retain its failure on `cce6e8c6` (`store.update()` raised
  `SessionFileNotFoundError` after the completed resume turn and recreated a lock-only directory).

## Implementation

- [x] Share the interactive post-turn manifest-presence guard with headless Codex operations.
- [x] Preserve completed first-turn and resume results with one warning when explicit deletion wins.
- [x] Skip manifest and index reconciliation for the deleted identity without leaving staged or lock-only state.
- [x] Preserve strict non-absence errors and unrelated directory content.

## Verification and closeout

- [x] Run focused headless and interactive Codex operation tests plus the O003 regression (72 passed).
- [x] Run the complete regression suite (664 passed).
- [x] Run Codex preflight (ready) and the required live Codex-session integration file (1 passed).
- [x] Synchronize design, end-user, member/epic cards, ledger, and change log.
- [x] Complete independent review; remove the stale CLI fixture re-export and record the separate D049 receipt-shell
  race.
- [x] Re-run CLI integration collection (166 collected), focused tests (72 passed), and the final repository gate.
- [x] Merge O003 before activating D021 (PR #138, `4a601dc2`).
