# Enforce launch-runtime override immutability checklist

Current focus: merge the independently reviewed D008 member before starting D009.

## Activation and reproduction

- [x] Close O006 after PR #135 (`00692356`) and repoint its inbound board links.
- [x] Start `fix/enforce-launch-runtime-override-immutability` from merged `main` at `00692356`.
- [x] Move D008 to `doing/`, create this checklist, and repoint inbound links.
- [x] Add `tests/regression/test_bug_d008_launch_runtime_parent_override.py` and retain the baseline bypass on
  `00692356` (`set_override` returned normally and mutated the override dictionary).

## Implementation

- [x] Reject direct, parent-object, and wildcard attempts to override `launch.runtime` before mutation.
- [x] Keep valid sibling launch overrides, whole-launch null, and nullable sibling clears working.
- [x] Keep `session reset launch` and `session reset launch.runtime` able to remove persisted illegal shapes.
- [x] Preserve raw-intent launcher dispatch, consumer-lane immutability, and runtime creation flags.

## Verification and closeout

- [x] Run focused override unit and CLI tests (113 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py` (45 passed).
- [x] Run `make test-regression` (662 passed) and `make test-unit` (8,771 passed, one pre-existing platform skip, 118
  deselected).
- [x] Run final `make pre-commit`.
- [x] Synchronize the member, epics, review ledger, change log, and affected design/end-user docs.
- [x] Complete independent review and record the adjacent relaunch-inheritance policy gap as D048.
- [ ] Merge D008 before activating D009.
