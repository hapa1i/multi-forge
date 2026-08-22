# Correct fork transfer snapshot rollback

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `done/` -- shipped in PR #215 (`7736d0d0`) before Wave 8 order 1.

**Related shipped member**: [`extract_session_fork_execution`](../../done/extract_session_fork_execution/card.md) (Wave
7 order 32).

This is a post-merge correctness edge in shipped order 32, not a reopened or renumbered review-ledger finding. Wave 7
and Wave 8 finding/member counts remain unchanged.

## Goal

Remove a transfer snapshot created by a failed fork preparation while preserving every snapshot that existed before the
attempt, so a same-name retry cannot silently launch with stale parent context.

## Evidence and authority

- The transfer factory creates `<forge_root>/.forge/prev_sessions/<parent>/children/<child>.md` before prompt
  combination. `_ForkCompensation` currently tracks transcript ownership only, and `SessionManager.delete_session()`
  does not own transfer snapshots.
- A deterministic filesystem control made prompt combination fail after the snapshot write. Rollback removed the child
  manifest and index row but retained the snapshot. After the parent transcript changed, retry regenerated
  `generated.md` and reused the old byte-identical child snapshot because `ensure_child()` deliberately never overwrites
  an existing file.
- The current transfer-failure test raises before its factory writes an artifact, while the rewind regressions cover
  transcript compensation rather than transfer-context ownership.

Authority comes from the explicit pre-launch compensation criterion in
[`extract_session_fork_execution`](../../done/extract_session_fork_execution/card.md), the frozen-snapshot contract in
[`docs/design_sessions.md`](../../../design_sessions.md#39-session-resume-context-management), and the three-file
ownership model in [`docs/design_sessions.md`](../../../design_sessions.md#h3-file-layout-and-overlay).

## Acceptance criteria

- Sample the expected child snapshot before invoking the transfer factory and record only a newly created exact path as
  rollback-owned, including when the factory writes and then raises.
- After successful child/session compensation, remove that owned snapshot. Preserve any snapshot that existed before the
  fork attempt and keep the regeneratable parent cache outside child rollback.
- Surface snapshot cleanup failure with the exact retained path and actionable retry guidance; do not claim complete
  compensation when the file remains.
- A failure-then-retry regression changes the parent transcript and proves the retry receives the new snapshot. Separate
  controls preserve a pre-existing sentinel and cover a factory failure after creation.
- Run focused fork/session tests, full unit and regression suites, targeted Docker session lifecycle coverage, full
  pre-commit, design-size, and board-integrity checks.

## Scope boundaries

- Do not change `ensure_child()` durability, transfer strategy/rendering, launch prompt ordering, or user-notes
  ownership.
- Do not delete pre-existing snapshots, infer ownership from content equality, or turn transfer cleanup into generic
  session deletion behavior.
- Keep every Wave 8 member parked until this correction merges and closes.

## Implementation outcome

Fork preparation now records only an exact child snapshot created by the current transfer attempt, including a factory
that writes and then raises. Successful session compensation removes that owned snapshot; pre-existing snapshots and the
parent cache remain untouched. Cleanup failures name the retained path and the required recovery action.

Verification passed 104 focused fork/session tests, 9,309 unit tests with one skip and 122 deselected, 929 regressions,
six targeted Docker fork-lifecycle checks, full pre-commit, the 29,990-token design limit, and the 393-document/965-link
board audit. No Forge workflow command was used.
