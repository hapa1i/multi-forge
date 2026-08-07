# Preserve newer-schema workqueue markers checklist

Current focus: complete; D021 shipped in PR #140 (`ecc79aa2`) before D022 activation.

## Activation and reproduction

- [x] Merge O003 before activating D021 (PR #138, `4a601dc2`).
- [x] Start `fix/preserve-newer-workqueue-markers` from merged `main` at `de8adaac`, after PR #139.
- [x] Move O003 to `done/`, move D021 to `doing/`, create this checklist, and repoint inbound board links.
- [x] Add the marked D021 regression and retain its baseline failure: the first drain rewrote the future marker's bytes.

## Implementation

- [x] Classify only strictly newer integer marker schemas as resident deferred work before ordinary validation.
- [x] Preserve future marker bytes and fields across repeated drains without attempts, errors, poison status, or handler
  dispatch.
- [x] Emit actionable upgrade guidance once per process while keeping foreground JSON stdout clean.
- [x] Advance PR #139's bounded scan cursor when future markers occupy a window so later actionable work gets a turn.
- [x] Preserve malformed, older/invalid, handler-failure, lock-contention, and current-schema poison outcomes.

## Verification and closeout

- [x] Run focused workqueue, startup CLI, and D021 regression tests (82 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/cli/test_startup_queue_integration.py` (10 passed).
- [x] Run the complete regression suite (667 passed).
- [x] Run the complete unit suite (8,804 passed, one pre-existing platform skip, 118 deselected).
- [x] Synchronize design, member/epic cards, ledger, and change log.
- [x] Run final `make pre-commit` after Markdown normalization.
- [x] Complete independent review and merge D021 before activating D022 (PR #140, `ecc79aa2`).
