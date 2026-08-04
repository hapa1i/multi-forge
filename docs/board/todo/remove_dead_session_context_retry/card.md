# Remove the dead session-context retry

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O052).

**Lane**: `todo/` -- accepted Wave 7 session cleanup work.

## Goal

Delete the duplicate index-only retry that cannot observe the manifest-corruption condition described by its comment.

## Acceptance Criteria

- Characterization tests prove corruption/unreadable errors still propagate and not-found references still reach UUID
  and manifest fallback resolution.
- Remove the duplicate call and stale explanation without changing ambiguity behavior.
- Run focused session-context and regression tests.
