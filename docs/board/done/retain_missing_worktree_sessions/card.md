# Retain sessions whose manifest survives a missing worktree

**Epic**: [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).

**Decision**: [`missing_worktree_authority`](../../done/missing_worktree_authority/card.md) (DG2; D009).

**Lane**: `done/` -- shipped in PR #137 (`cce6e8c6`).

## Goal

Treat a valid manifest as the durable session reservation and worktree presence as launchability, so a vanished checkout
does not silently erase discoverability or conversation-binding ownership.

## Design Authority

- [`missing_worktree_authority`](../../done/missing_worktree_authority/card.md) (DG2) defines the approved operation and
  session-shape matrix.
- [`docs/design.md` §3.2](../../../design.md#32-contract-files-authoritative-paths) defines the manifest as the durable
  reservation and the global index as its derived publication layer.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#forge-owned-durable-state) requires corrupt,
  unreadable, newer-schema, and absent state to remain distinguishable.

## Evidence

The admission recheck on merged `main` at `dc963a7c` showed that a valid manifest under an existing Forge root could
name a missing recorded worktree: `IndexStore.get_session` returned the row, while `list_sessions` returned no session
and deleted the row. The execution branch retained a marked regression against `8ebdb644`; it failed with the same
`list_sessions() == []` result and row deletion before the implementation changed.

## Expected Behavior

- A valid manifest remains live and discoverable with derived `launchability=missing_worktree`; only an absent manifest
  makes its index row prunable.
- Read-only, binding, repair, delete, and clean behavior follows the approved DG2 matrix; checkout-dependent actions
  refuse before mutation with the recorded path and recovery/removal guidance.
- A worktree that reappears at the same validated path becomes launchable without a durable-state migration.
- Human list/show output gives recovery guidance, and JSON read surfaces add one stable derived launchability field
  without changing stored manifest or index schemas.

## Scope

- Align list/get predicates so only a missing manifest makes an index row prunable.
- Expose derived `missing_worktree` launchability in human and JSON reads.
- Re-index valid missing-worktree orphans through `session repair` without recreating or claiming the checkout.
- Preserve fail-closed name/binding scans and make checkout-dependent operations refuse before mutation.
- Keep explicit delete as the removal owner; `forge clean` reports rather than auto-deletes the valid manifest.

## Acceptance Criteria

- Add `tests/regression/test_bug_d009_missing_worktree_session_visibility.py` with `pytestmark = pytest.mark.regression`
  and a module docstring naming D009 and the divergent list/get predicates.
- Fixtures cover row-only residue, root-level and nested manifests, moved ordinary checkouts, `--into`/shared checkouts,
  reappearing paths, collisions, and concurrent repair/delete/create windows.
- Resume/fork/launch failures name the recorded path and a supported recovery/removal action.
- `docs/design.md`, `docs/cli_reference.md`, and `docs/end-user/session.md` adopt the approved liveness/launchability
  and repair model in the same implementation change.

## Verification

Focused index, lifecycle, launcher, repair, clean, and list/show tests passed (398). The complete required Docker files
passed: session-command integration (46) and session lifecycle (23). `make test-regression` passed (663), and
`make test-unit` passed (8,790 with one pre-existing platform skip and 118 deselected). Final `make pre-commit` passed.
The review amendment adding launchability parity to `%session list` and `%session show` has dedicated focused coverage:
the expanded list/show, hook-dispatcher, session-context, and D009 regression slice passed (188), and final
`make pre-commit` passed.

## Implementation Outcome

- Index listing now prunes only a row whose manifest is absent. Valid manifests retain their name and conversation
  bindings while terminal and `%session` list/show reads derive `launchable`, `missing_worktree`, or `unknown` without
  changing durable schemas.
- `session repair --yes` republishes valid missing-worktree orphans through the existing collision, binding, and
  unchanged-manifest transaction. It preserves manifest bytes and shared-checkout ownership and never creates a path.
- Claude and Codex resume, fork, relaunch, and shared launcher seams reject a missing recorded directory before state,
  preflight, callback, or child creation. Recreating the same directory restores launchability automatically.
- `forge clean` reports valid degraded sessions in an additive report-only category and excludes them from cleanable
  totals and apply; explicit `session delete` remains the removal owner.

## Compatibility and Exclusions

- Preserve fail-closed handling for corrupt, unreadable, newer-schema, and identity-conflicting manifests.
- Do not recreate, claim, or auto-delete a missing checkout; explicit `session delete` remains the removal owner.
- Do not change row-first creation or make the index authoritative over a surviving manifest.
- Treat the JSON launchability field as an additive public read-surface change and preserve existing fields and exit
  status.
