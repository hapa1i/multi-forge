# Wire the transcript reindex guard

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O092
subset).

**Lane**: `todo/` -- accepted Wave 7 maintenance work.

## Goal

Use `IndexState.needs_reindex` to avoid re-extracting and rewriting byte-identical transcript snapshots instead of
deleting the unused intended optimization.

## Acceptance Criteria

- Stop/index behavior skips unchanged snapshots and reindexes changed, missing, or invalidated inputs as specified.
- Atomic state updates and failure recovery remain intact.
- Tests cover content/mtime edge cases and repeated Stop invocation; measure the avoided work where practical.
