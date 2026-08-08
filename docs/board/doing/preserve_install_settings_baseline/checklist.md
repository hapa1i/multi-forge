# Preserve the installation settings baseline checklist

Current focus: merge the independently reviewed D012 implementation before D019 activation.

## Activation and reproduction

- [x] Start `fix/preserve-install-settings-baseline` from merged `main` at `37a03209`.
- [x] Close D013/D014 after PR #144 and move this card from `todo/` to `doing/`.
- [x] Add a marked D012 regression with distinct and same-second settings backup generations.
- [x] Confirm the retained regression fails on `37a03209` because the second run rotates tracking and disable selects
  the newest Forge-bearing backup.

## Baseline ownership

- [x] Keep the first successful settings-bearing run's validated backup path as the installation baseline.
- [x] Let later enable and sync attempts create rollback snapshots without replacing or mutating that durable baseline.
- [x] Make whole-installation and runtime-scoped disable read the tracked baseline instead of discovering the newest
  backup.
- [x] Fail before removal when a non-null tracked baseline is missing, unreadable, or outside the settings directory,
  retaining the installation row for recovery.
- [x] Give legacy rows with a null baseline an explicit compatibility path without treating newer history as the
  pre-Forge baseline.
- [x] Preserve user edits, ownership-sidecar selection, partial-runtime survivors, rollback-on-fault behavior, and all
  backup history.

## Acceptance tests

| Test                     | Fixture                                                   | Assertion                                                                          |
| ------------------------ | --------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Repeated enable/sync     | distinct timestamps and same-second runs                  | rollback snapshots may rotate; tracked baseline does not                           |
| Full disable             | two backup generations plus later user edits              | Forge values are removed against the first baseline; user edits and history remain |
| Runtime disable          | Claude-owned settings with a surviving runtime            | the same tracked baseline drives unmerge and surviving ownership stays coherent    |
| Invalid tracked baseline | missing, unreadable, or out-of-bound path                 | removal fails before mutation and tracking remains                                 |
| Legacy null baseline     | valid old installation row without `settings_backup_path` | documented compatibility behavior runs without inventing a newer baseline          |

## Verification and closeout

- [x] Run focused settings, installer, runtime-removal, CLI, and marked regression tests (826 installer/D012 tests with
  one skip after the review amendment; 109 focused CLI/regression tests).
- [x] Run targeted Docker enable/sync/disable installer coverage (1 passed, 21 deselected).
- [x] Build a wheel and run a clean-install lifecycle smoke (1 passed, 21 deselected).
- [x] Run `make test-regression` (682 passed) and final `make pre-commit`.
- [x] Synchronize the normative installer design, end-user hook guidance, review ledger, change log, and epic cursor.
- [x] Obtain independent review and resolve its LOW baseline-deletion race; leave the parked test-only helper and
  acceptable end-user path simplification unchanged.
- [ ] Merge before activating D019.
