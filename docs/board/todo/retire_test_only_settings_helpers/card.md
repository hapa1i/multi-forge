# Retire test-only settings helpers

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O092/O096).

**Lane**: `todo/` -- accepted Wave 7 installer cleanup work.

**Findings**: O096 plus O092's `_extract_command_paths` subset.

## Goal

Remove `restore_settings_backup`, `check_scalar_conflict`, and `_extract_command_paths` after preserving coverage on the
live settings merge and conflict paths.

## Evidence and Authority

On `5777192a`, all three helpers have no production caller; the first two are exercised only by direct tests. The live
installer uses rollback-state capture/restore and the actual merge/conflict machinery. Authority:
[`docs/design_appendix.md` "C.3 Settings merge rules"](../../../design_appendix.md#c3-settings-merge-rules) and DG4.

## Acceptance Criteria

- Re-verify no CLI, migration, packaged extension, documentation, or external entry-point contract exposes the helpers.
- Move useful conflict/backup assertions to reachable installer operations; delete direct-only tests with removed code.
- Run focused installer/settings tests and the required targeted installer integration runner.

## Exclusions

Do not remove live rollback-state helpers, change backup permissions, relax scalar conflicts, or alter baseline and
ownership-sidecar restoration.
