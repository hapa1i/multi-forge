# Preserve concurrent deletion during headless Codex turns

**Epic**: [`epic_session_durable_state_safety`](../../doing/epic_session_durable_state_safety/card.md).

**Finding**: O003 (HIGH) in [`review_combined.md`](../../review_combined.md#code-and-maintenance-findings).

**Lane**: `todo/` -- accepted Wave 3 implementation work.

## Goal

Let an explicit session deletion remain terminal when it lands during a long headless Codex start or resume turn,
without losing the completed turn result to a post-run traceback or recreating partial session state.

## Design Authority

- [`docs/design.md` §3.2](../../../design.md#32-contract-files-authoritative-paths): deletion owns terminal manifest and
  index removal, and production updates may not recreate a published session.
- [`docs/design.md` §3.9](../../../design.md#39-session-resume-context-management): headless and interactive Codex
  frontends record the same CLI-owned turn facts after their runtime exits.
- `src/forge/core/ops/codex_interactive.py::_update_manifest_if_present`: the shipped sibling contract treats concurrent
  deletion as a visible post-turn warning and removes only a lock-only directory shell.

## Evidence

Rechecked on `dc963a7c`: deleting a real Codex session manifest from the mocked subprocess-spawn callback during
`continue_codex_session` let the turn finish, then `store.update()` raised `SessionFileNotFoundError`. Lock acquisition
recreated the session directory with only `forge.session.json.lock`. The first-turn path has the same unconditional
post-run update; neither headless path uses the interactive guard.

## Expected Behavior

- Headless start and resume return their runtime result with one actionable warning when explicit deletion wins during
  the turn.
- Post-turn manifest and index reconciliation are skipped for the deleted identity; neither a manifest, index row,
  lock-only directory, staged handoff, nor other partial session shell is recreated.
- The exists/read race after the preflight is covered, while unrelated content in a surviving directory is never deleted
  by the cleanup guard.

## Acceptance Criteria

- Add `tests/regression/test_bug_o003_headless_codex_concurrent_delete.py` with the required regression marker and a
  docstring naming O003 and the unconditional post-turn update root cause.
- Hermetic ops tests exercise both first-turn and resume deletion plus the narrower exists-to-update race, using the
  real store/index stack and mocked Codex subprocess.
- Tests assert the runtime result/warning, absent manifest/index row, absent lock-only shell, and preservation of any
  non-lock directory content.
- Run `tests/src/core/ops/test_codex_session.py` and `tests/src/core/ops/test_codex_interactive.py`, then
  `forge runtime preflight codex`, `./scripts/test-integration.sh tests/integration/core/test_codex_session_start.py`,
  `make test-regression`, and `make pre-commit`.

## Compatibility and Exclusions

- Preserve normal post-turn fact refresh, thread-id drift handling, failed-turn retention, and rollback ownership.
- Do not weaken typed errors for corruption, unreadability, or lock timeout; only confirmed absence means deletion won.
- Do not fold in missing-worktree recovery (D009) or change the public Codex result schema.
