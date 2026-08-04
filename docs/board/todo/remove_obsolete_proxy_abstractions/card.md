# Remove obsolete proxy abstractions

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O047–O048).

**Lane**: `todo/` -- accepted Wave 7 cleanup work.

## Goal

Remove the test-only model-spec module, unused abstract client, and unreachable ToolCallError handling without losing
coverage of live model detection, adapter behavior, or failure metrics.

## Acceptance Criteria

- Re-verify repository, entry-point, resource, extension, and documentation consumers before deletion.
- Move synthesized ToolCallError metric assertions to a reachable error path before deleting the exception and handlers.
- Delete obsolete self-only tests; retain characterization of live model detection and the actual client adapter
  protocol.
- Update stale comments/imports and run focused proxy unit and integration tests.
