# Preserve concurrent deletion during headless Codex turns

**Epic**: [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).

**Finding**: O003 (HIGH) in
[`review_combined.md`](../../reviews/whole_repo_maintenance_findings.md#code-and-maintenance-findings).

**Lane**: `done/` -- shipped in PR #138 (`4a601dc2`) on 2026-08-07.

## Goal

Let an explicit session deletion remain terminal when it lands during a long headless Codex start or resume turn,
without losing the completed turn result to a post-run traceback or recreating partial session state.

## Design Authority

- [`docs/design.md` §3.2](../../../design.md#32-contract-files-authoritative-paths): deletion owns terminal manifest and
  index removal, and production updates may not recreate a published session.
- [`docs/design_sessions.md` §3.9](../../../design_sessions.md#39-session-resume-context-management): headless and
  interactive Codex frontends record the same CLI-owned turn facts after their runtime exits.
- `src/forge/core/ops/codex_session.py::_update_manifest_if_present`: the shared Codex frontend contract treats
  concurrent deletion as a visible post-turn warning and removes only an empty or lock-only directory shell.

## Evidence

Admission rechecked on `dc963a7c`: deleting a real Codex session manifest from the mocked subprocess-spawn callback
during `continue_codex_session` let the turn finish, then `store.update()` raised `SessionFileNotFoundError`. Lock
acquisition recreated the session directory with only `forge.session.json.lock`. The first-turn path has the same
unconditional post-run update; neither headless path uses the interactive guard.

The execution branch retained the marked failure on merged `main` at `cce6e8c6`: the completed resume result was lost to
the same `SessionFileNotFoundError`, and the manifest lock recreated the deleted session directory.

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

## Verification

Focused headless/interactive ops and the O003 regression passed (72). `forge runtime preflight codex` reported ready;
the required live two-turn Codex start/resume integration passed (1), and `make test-regression` passed (664). Its first
integration run exposed that the existing host-auth fixture was scoped only to `tests/integration/session/`, so the core
test saw the autouse empty `CODEX_HOME` and failed before launch. Hoisting the same non-autouse fixture to the
integration root made the promised real-host-auth path available to both suites; the rerun passed without a skip or
API-key fallback. Independent review then caught the CLI conftest's stale import of the fixture's old module path; that
re-export was removed because pytest now discovers the fixtures from the integration-root conftest. The same review
runtime-reproduced a distinct SessionStart observation-receipt race and admitted it as D049 instead of widening O003's
post-turn reconciliation boundary. Post-amendment CLI integration collection passed (166), all five cross-directory
fixture consumers collected, the focused suite passed again (72), and final `make pre-commit` passed.

## Implementation Outcome

- Headless first-turn and resume reconciliation now use the interactive frontend's established manifest-presence guard;
  interactive callers import the same helper, leaving one absence/race contract.
- Explicit deletion returns the completed runtime result with one warning and suppresses both manifest and index fact
  updates. The narrower race removes only the lock-created shell and preserves unrelated directory content.
- Corrupt, unreadable, and lock-timeout updates still propagate. Normal fact refresh, thread drift, failed-turn
  retention, rollback ownership, and the public result shapes are unchanged.
