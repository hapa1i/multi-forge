# Preserve the installation settings baseline

**Epic**: [`epic_installer_transaction_safety`](../../doing/epic_installer_transaction_safety/card.md).

**Finding**: D012 (HIGH) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- second Wave 4 member after Codex install rollback.

## Goal

Keep one authoritative pre-Forge Claude settings baseline across repeated enable/sync operations and use that exact
baseline for whole-installation and runtime-scoped disable.

## Design Authority

- [`docs/design_appendix.md` §C.3](../../../design_appendix.md#c3-settings-merge-rules): disable smart-unmerges tracked
  values against the pre-Forge backup while preserving user changes and backup history.
- [`docs/design_appendix.md` §C.4](../../../design_appendix.md#c4-durable-installproject-files): the installation row
  owns durable settings metadata and all knowable paths are validated before mutation.

## Evidence

Rechecked on `2461e3fa` with two settings-bearing installer runs using distinct timestamps. The second run backed up
Forge-managed settings and replaced the installation's original `settings_backup_path`; full disable then selected the
newest backup independently and retained the Forge `statusLine`. Source inspection found the same newest-backup lookup
in runtime-scoped removal.

## Expected Behavior

- The first successful settings-bearing enable establishes `settings_backup_path`; later enable/sync operations do not
  overwrite that baseline or its file.
- Full and runtime-scoped disable read the validated tracked baseline when it is present, never a newer history file.
- A present but missing, unreadable, or out-of-bound tracked baseline fails closed before removal and retains ownership
  for recovery.
- Legacy rows with no recorded baseline follow an explicit, tested compatibility path rather than silently inventing one
  from a newer backup.

## Acceptance Criteria

- Add a marked D012 regression with two distinct backup generations and a docstring naming baseline rotation plus
  newest-backup selection.
- Tests cover repeated enable, sync, full disable, runtime-scoped disable, same-second execution, missing/unreadable or
  unsafe tracked paths, and a legacy null `settings_backup_path` row.
- Assertions preserve user edits, remove Forge-owned values, retain backup history, and keep per-attempt rollback
  snapshots distinct from the durable pre-Forge baseline.
- Run focused installer/settings/runtime-removal tests, targeted Docker installer enable/sync/disable coverage, a
  clean-wheel lifecycle smoke, the regression suite, and `make pre-commit`.

## Compatibility and Exclusions

- Reuse the existing tracking field unless implementation proves a schema change is necessary; do not migrate backup
  history speculatively.
- Do not delete historical `.forge.backup.*` files or weaken path-boundary validation.
- Preserve ownership-sidecar selection, partial-runtime survivor behavior, and settings rollback on write/tracking
  faults.
- Do not absorb D019's no-sidecar value comparison or Codex config rollback.
