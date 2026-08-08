# Preserve user edits during legacy settings removal checklist

Current focus: obtain independent review and merge the verified D019 implementation.

## Activation and reproduction

- [x] Start `fix/preserve-legacy-settings-user-edits` from merged `main` at `f069226f`.
- [x] Close D012 after PR #145 and move this card from `todo/` to `doing/`.
- [x] Add a marked D019 regression whose docstring names unconditional scalar/env deletion in legacy `unmerge`.
- [x] Confirm the retained regression fails on `f069226f` after user edits tracked scalar and environment values.

## Value-aware legacy removal

- [x] Remove a legacy scalar only when its current value equals the tracked Forge value.
- [x] Remove a legacy environment key only when its current value equals the tracked Forge value.
- [x] Treat missing tracked values as no-ops and preserve modified values while removing unchanged owned siblings.
- [x] Keep hook canonical matching, permission stable-id matching, sidecar-backed smart-unmerge, D012 baseline selection,
  runtime survivor behavior, and Codex registration unchanged.

## Acceptance tests

| Test | Fixture | Assertion |
| ---- | ------- | --------- |
| Scalar values | equal, modified, and absent tracked values | only the equal value is removed |
| Environment values | equal, modified, absent, and mixed values | user edits and unrelated keys remain |
| Hooks and permissions | canonical tracked entries plus unrelated values | existing matching behavior is unchanged |
| Full disable | legacy row without a sidecar, with and without a baseline file | real installer preserves edits and clears successful ownership |

## Verification and closeout

- [x] Run focused settings, installer, CLI, and marked D019 regression tests.
- [x] Run targeted Docker installer disable coverage.
- [x] Build a wheel and run a clean-install lifecycle smoke.
- [x] Run `make test-regression` and final `make pre-commit`.
- [x] Synchronize end-user guidance, review ledger, change log, member card, and epic cursors.
- [ ] Obtain independent review and merge before closing the installer transaction epic.
