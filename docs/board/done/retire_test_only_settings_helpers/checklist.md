# Retire test-only settings helpers checklist

Current focus: complete -- order 21 shipped in PR #200 (`63ae0f74`); orders 22--35 remain parked.

## Activation and evidence

- [x] Close order 20 on pushed `main` at `5664258b`, create the execution branch from that exact commit, and move only
  this member to `doing/`.
- [x] Re-run source, caller, export, documentation, entry-point, and packaged-extension searches for
  `restore_settings_backup`, `check_scalar_conflict`, and `_extract_command_paths`.
- [x] Confirm the first two symbols have only direct test callers, `_extract_command_paths` has no caller, and none is a
  supported or packaged surface.
- [x] Confirm live backup, rollback, scalar-conflict, and forced-merge behavior remains covered through reachable
  installer/settings operations.
- [x] Record the pre-change focused baseline: 111 settings-merge, installer-transaction, and runtime-disable tests pass.

## Implementation

- [x] Delete the three unused helpers and only the direct tests belonging to their removed behavior.
- [x] Preserve assertions on `backup_settings`, `set_scalar`, full merge conflict/force handling, installer backups, and
  rollback-state restoration.
- [x] Keep backup permissions, scalar-conflict behavior, baseline restoration, and ownership-sidecar restoration
  unchanged.

## Verification and closeout

- [x] Run the focused installer/settings test set after deletion (106 passed).
- [x] Run the full unit suite (9,210 passed, one skipped, 122 deselected) and regression suite (915 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/docker/test_installer.py` (23 passed).
- [x] Run the clean-wheel runtime smoke because installer code changed.
- [x] Run full pre-commit, diff, design-size, board-link, and Wave 7 lane-count checks without a Forge workflow: both
  living design documents remain below 30k tokens, all 880 local links across 355 board documents resolve, and Wave 7 is
  20 `done` / one `doing` / 14 `todo`.
- [x] Open PR #200, merge it as `63ae0f74` after all five checks pass, and close order 21 without activating order 22.
