# Align the incognito worktree root guard checklist

Current focus: complete final quality checks and independent review.

## Activation and reproduction

- [x] Merge D022 before activating D010 (PR #141, `d2ed2349`).
- [x] Start `fix/align-incognito-worktree-guard` from merged `main` at `d2ed2349`.
- [x] Move D022 to `done/`, move D010 to `doing/`, create this checklist, and repoint inbound board links.
- [x] Add the marked D010 regression and retain the linked-worktree guard failure on `d2ed2349` (exit code 0).

## Implementation

- [x] Require the main checkout for `session incognito --worktree` before mutation.
- [x] Preserve `require_repo_root()` for ordinary incognito launches.
- [x] Preserve branch naming, worktree ownership, extensions, launch, and cleanup behavior.

## Acceptance coverage

| Test                      | Fixture                           | Assertion                                                                         | Test File                                                         |
| ------------------------- | --------------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Linked-worktree rejection | Real linked Git worktree          | `incognito --worktree` emits the sibling main-checkout diagnostic before mutation | `tests/regression/test_bug_d010_incognito_worktree_root_guard.py` |
| Main-checkout acceptance  | Main checkout with guarded launch | Worktree incognito passes the main-root guard and reaches creation                | `tests/src/cli/test_session_start_delete.py`                      |
| Ordinary incognito        | Valid repository root             | Non-worktree command retains the ordinary repository guard                        | `tests/src/cli/test_session_start_delete.py`                      |

## Verification and closeout

- [x] Run focused incognito/start/fork CLI and D010 regression tests (12 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py` (23 passed).
- [x] Run the complete regression suite (669 passed).
- [x] Confirm the existing design contract and synchronize member/epic cards, review ledger, and change log.
- [x] Run final `make pre-commit`.
- [ ] Complete independent review and merge D010 before closing Wave 3.
