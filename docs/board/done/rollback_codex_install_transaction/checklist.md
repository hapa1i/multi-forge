# Roll back Codex install transactions checklist

Current focus: shipped in PR #144 (`37a03209`); D012 is now active.

## Activation and reproduction

- [x] Start `fix/rollback-codex-install-transaction` from `afde43bf`.
- [x] Move the Wave 4 epic and this member to `doing/` and repoint inbound links.
- [x] Add a marked D013/D014 regression and retain both failures on the merged baseline.
- [x] Cover missing and pre-existing Codex config files at the post-write read-back and final tracking fault points.

## Implementation

- [x] Capture the exact pre-mutation Codex config state before an install or update writes the managed block.
- [x] Restore pre-existing bytes and mode, or remove a config created by the failed attempt.
- [x] Include Codex restoration in failures from registration read-back and the final tracking commit.
- [x] Report every rollback failure without claiming that all changed surfaces were restored.
- [x] Preserve unavailable, conflict, manual-registration, existing-block, and successful install/update behavior.

## Acceptance tests

| Test                 | Fixture                                              | Assertion                                                     |
| -------------------- | ---------------------------------------------------- | ------------------------------------------------------------- |
| D014 read-back       | missing and pre-existing config; read-back `OSError` | typed install error; config/files/settings/tracking restored  |
| D013 tracking commit | missing and pre-existing config; tracking `OSError`  | config bytes/mode and every earlier surface restored          |
| Rollback failure     | Codex restoration itself raises                      | error names the incomplete Codex surface; ownership is honest |
| Compatibility        | unavailable/conflict/manual/existing/success paths   | existing visible and best-effort outcomes remain unchanged    |

## Verification and closeout

- [x] Run the focused installer, Codex-hook, CLI extension, and marked regression tests.
- [x] Run the relevant Docker installer Codex lifecycle slice.
- [x] Build a wheel and run a clean-install enable/disable smoke.
- [x] Run `make test-regression` and final `make pre-commit`.
- [x] Synchronize the card, review ledger, change log, and normative installer documentation affected by the fix.
- [x] Complete independent review (2026-08-08; no design violations).
- [x] Merge before activating D012 (PR #144, `37a03209`, 2026-08-08).
