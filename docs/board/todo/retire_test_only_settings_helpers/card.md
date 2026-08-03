# Retire test-only settings helpers

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O092/O096).

**Lane**: `todo/` -- accepted Wave 7 installer cleanup work.

## Goal

Remove `restore_settings_backup`, `check_scalar_conflict`, and `_extract_command_paths` after preserving coverage on the
live settings merge and conflict paths.

## Acceptance Criteria

- Re-verify no CLI, migration, packaged extension, documentation, or external entry-point contract exposes the helpers.
- Move useful conflict/backup assertions to reachable installer operations; delete direct-only tests with removed code.
- Run focused installer/settings tests and the required targeted installer integration runner.
