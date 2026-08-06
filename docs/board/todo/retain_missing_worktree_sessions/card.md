# Retain sessions whose manifest survives a missing worktree

**Epic**: [`epic_session_durable_state_safety`](../../doing/epic_session_durable_state_safety/card.md).

**Decision**: [`missing_worktree_authority`](../../done/missing_worktree_authority/card.md) (DG2; D009).

**Lane**: `todo/` -- accepted Wave 3 implementation work.

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

Rechecked on merged `main` at `dc963a7c`: a valid manifest stored under an existing Forge root named a missing recorded
worktree. `IndexStore.get_session` returned its row because the manifest exists, while `list_sessions` returned no
session and deleted the row because the worktree does not. The existing repair scanner still classifies the same shape
as `missing-worktree` report-only because republishing it would immediately trigger that prune.

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

Run focused session/index/repair/delete/clean tests, then
`./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py` and
`./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py`, plus `make test-regression` and
`make pre-commit`.

## Compatibility and Exclusions

- Preserve fail-closed handling for corrupt, unreadable, newer-schema, and identity-conflicting manifests.
- Do not recreate, claim, or auto-delete a missing checkout; explicit `session delete` remains the removal owner.
- Do not change row-first creation or make the index authoritative over a surviving manifest.
- Treat the JSON launchability field as an additive public read-surface change and preserve existing fields and exit
  status.
