# Retain missing-worktree sessions checklist

Current focus: independently review and merge the verified D009 implementation before activating O003.

## Activation and reproduction

- [x] Merge D008 before activating D009 (PR #136, `8ebdb644`).
- [x] Start `fix/retain-missing-worktree-sessions` from merged `main` at `8ebdb644`.
- [x] Move D009 to `doing/`, create this checklist, and repoint inbound board links.
- [x] Add the marked D009 regression and retain its failure on `8ebdb644` (`list_sessions()` returned `[]` and pruned
  the row after `get_session()` accepted the surviving manifest).

## Implementation

- [x] Prune an index row only when its manifest is absent; retain valid manifests with missing recorded worktrees.
- [x] Derive one stable launchability value for terminal and `%session` list/show reads without persisting it.
- [x] Re-index valid missing-worktree orphans without recreating or claiming their checkout.
- [x] Refuse checkout-dependent resume, fork, and launch paths before mutation with the recorded path and recovery.
- [x] Preserve fail-closed corruption, unreadable/newer-schema, collision, binding, delete, and clean behavior.

## Verification and closeout

- [x] Run focused index, session-op, repair, delete, clean, list/show, resume, and fork tests (398 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py` (46 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py` (23 passed).
- [x] Run `make test-regression` (663), `make test-unit` (8,790 passed, one pre-existing skip, 118 deselected), and
  final `make pre-commit`.
- [x] Synchronize design, CLI reference, end-user session docs, member/epic cards, ledger, and change log.
- [x] Verify the review amendment for `%session list` / `%session show` launchability parity (188 focused tests passed).
- [x] Rerun final `make pre-commit` after the review amendment.
- [ ] Complete independent review and merge D009 before activating O003.
