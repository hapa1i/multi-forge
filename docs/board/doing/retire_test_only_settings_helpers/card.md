# Retire test-only settings helpers

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O092/O096).

**Lane**: `doing/` -- active on `refactor/retire-test-only-settings-helpers` from the order-20 closeout (`5664258b`).

**Findings**: O096 plus O092's `_extract_command_paths` subset.

## Goal

Remove `restore_settings_backup`, `check_scalar_conflict`, and `_extract_command_paths` after preserving coverage on the
live settings merge and conflict paths.

## Evidence and Authority

Reverified on `5664258b`: all three helpers have no production caller; `restore_settings_backup` and
`check_scalar_conflict` are exercised only by their direct tests, while `_extract_command_paths` has no caller at all.
None is exported, documented as a supported surface, registered as an entry point, or referenced by packaged extension
assets. The live installer uses `backup_settings`, rollback-state capture/restore, `set_scalar`, and the actual
merge/conflict machinery. Authority:
[`docs/design_appendix.md` "C.3 Settings merge rules"](../../../design_appendix.md#c3-settings-merge-rules) and DG4.

The pre-change focused baseline covering settings merge, installer transactions, and runtime-disable rollback is 111
passing tests.

## Acceptance Criteria

- Re-verify no CLI, migration, packaged extension, documentation, or external entry-point contract exposes the helpers.
- Move useful conflict/backup assertions to reachable installer operations; delete direct-only tests with removed code.
- Run focused installer/settings tests and the required targeted installer integration runner.

## Exclusions

Do not remove live rollback-state helpers, change backup permissions, relax scalar conflicts, or alter baseline and
ownership-sidecar restoration.
