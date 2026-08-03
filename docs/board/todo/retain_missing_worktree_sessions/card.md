# Retain sessions whose manifest survives a missing worktree

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`missing_worktree_authority`](../../done/missing_worktree_authority/card.md) (DG2; D009).

**Lane**: `todo/` -- accepted Wave 3 implementation work.

## Goal

Treat a valid manifest as the durable session reservation and worktree presence as launchability, so a vanished checkout
does not silently erase discoverability or conversation-binding ownership.

## Scope

- Align list/get predicates so only a missing manifest makes an index row prunable.
- Expose derived `missing_worktree` launchability in human and JSON reads.
- Re-index valid missing-worktree orphans through `session repair` without recreating or claiming the checkout.
- Preserve fail-closed name/binding scans and make checkout-dependent operations refuse before mutation.
- Keep explicit delete as the removal owner; `forge clean` reports rather than auto-deletes the valid manifest.

## Acceptance Criteria

- Fixtures cover row-only residue, root-level and nested manifests, moved ordinary checkouts, `--into`/shared checkouts,
  reappearing paths, collisions, and concurrent repair/delete/create windows.
- Resume/fork/launch failures name the recorded path and a supported recovery/removal action.
- `docs/design.md`, the end-user session guide, and repair documentation adopt the approved liveness/launchability model
  in the same implementation change.

## Verification

Run focused session/index/repair tests, targeted session integration tests, and `make pre-commit`.
