# Preserve unreadable JSON state classification checklist

Current focus: implementation, verification, and review are complete; merge D011 before activating O006.

## Activation and reproduction

- [x] Start `fix/preserve-unreadable-json-state-classification` from `eef7cee0`.
- [x] Move the Wave 3 epic and this member to `doing/` and repoint inbound links.
- [x] Add `tests/regression/test_bug_d011_unreadable_json_state.py` and retain its wrong-exception failure on the base
  (`StateCorruptedError` instead of `StateUnreadableError`).
- [x] Record the five production callers and their intended outcomes: audit/team safe miss, Codex cache miss, visible
  cap rebuild, and non-destructive queue deferral.

## Implementation

- [x] Make `read_json` distinguish initial absence, read `OSError`, malformed JSON, and non-object JSON.
- [x] Keep audit and team caches as intentional safe misses; keep Codex preflight as a safe miss and cap bootstrap as a
  visible rebuild.
- [x] Leave unreadable workqueue markers byte-identical and pending, report the diagnostic, and continue later markers.
- [x] Preserve malformed-marker quarantine, handler retry/poison behavior, and D021 newer-schema behavior unchanged.

## Acceptance tests

| Test            | Fixture                                                   | Assertion                                                 | Test file                                                 |
| --------------- | --------------------------------------------------------- | --------------------------------------------------------- | --------------------------------------------------------- |
| D011 regression | existing JSON object whose open raises `OSError`          | raises `StateUnreadableError`, never corruption           | `tests/regression/test_bug_d011_unreadable_json_state.py` |
| Shared reader   | absent, unreadable, malformed, and non-object paths       | four outcomes retain distinct exception classes           | `tests/src/core/state/test_io.py`                         |
| Caller audit    | all five `read_json` consumers receive an unreadable file | caches miss, cap rebuilds visibly, marker remains pending | focused caller tests                                      |
| Queue progress  | unreadable marker sorts before a readable marker          | first is unchanged; second is processed; no poison count  | `tests/src/core/workqueue/test_queue.py`                  |
| CLI startup     | non-exempt command drains the same mixed queue            | result remains valid and diagnostic is on stderr          | `tests/src/cli/test_startup_queue.py`                     |

## Verification and closeout

- [x] Run all focused reader, caller, workqueue, and CLI startup tests (198 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/cli/test_startup_queue_integration.py` (9 passed).
- [x] Run `make test-regression` (660 passed) and `make test-unit` (8,742 passed, 1 pre-existing platform skip, 118
  deselected).
- [x] Run final `make pre-commit` after Markdown normalization.
- [x] Synchronize the card, review ledger, change log, and normative queue documentation affected by the fix.
- [x] Complete review and record the accepted GC-documentation amendment and separate D046 follow-up.
- [ ] Merge this member before activating O006.
