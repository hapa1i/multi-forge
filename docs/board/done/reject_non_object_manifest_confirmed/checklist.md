# Reject non-object confirmed manifest state checklist

Completed in PR #135 (`00692356`) on 2026-08-06.

## Activation and reproduction

- [x] Close D011 after PR #134 (`6be815bf`) and repoint its inbound board links.
- [x] Start `fix/reject-non-object-manifest-confirmed` from merged `main` at `6be815bf`.
- [x] Move O006 to `doing/`, create this checklist, and repoint inbound links.
- [x] Add `tests/regression/test_bug_o006_non_object_manifest_confirmed.py` and retain its baseline `AttributeError`
  failure at `SessionStore._validate_data`.

## Implementation

- [x] Reject explicitly present non-object `confirmed` values as `ManifestCorruptedError` naming the field and path.
- [x] Preserve missing and empty-object compatibility and leave invalid manifest bytes unchanged.
- [x] Pin repair scanning and non-force delete to the existing typed corruption paths.
- [x] Keep D009 missing-worktree liveness and D011 generic read classification unchanged.

## Verification and closeout

- [x] Run focused store, repair, and delete tests (95 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py` (44 passed).
- [x] Run `make test-regression` (661 passed) and `make test-unit` (8,751 passed, 1 pre-existing platform skip, 118
  deselected).
- [x] Run final `make pre-commit`.
- [x] Synchronize the card, review ledger, change log, and affected design documentation.
- [x] Complete independent review and record the adjacent status-line raw-reader issue as D047.
- [x] Merge O006 before activating D008 (PR #135, `00692356`).
