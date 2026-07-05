# Test session command fixture and split checklist

## Current focus

**DONE** (2026-07-05). PR #77 (`08e4a787`) split the large session CLI test file into command-oriented files and added a
narrow shared launch stub for successful Claude session starts, without changing CLI behavior or weakening tests.

## Phase 1: Fixture seam

- [x] Add a local CLI test fixture/helper for the common successful `invoke_claude` launch patch.
  - Assertion: tests that only need "Claude launched successfully" can express that intent without repeating the raw
    patch target.
- [x] Migrate one focused command cluster to the helper before broad file moves.
  - Assertion: migrated tests keep their existing behavior assertions and no longer carry identical raw launch patches.

## Phase 2: File split

- [x] Move list/show/show-policy tests to a focused session list/show test file.
  - Assertion: tests collect and pass from their new file without import side effects from the old catch-all file.
- [x] Move start/delete/incognito/main command-group tests to a focused start/delete test file.
  - Assertion: successful-launch tests use the shared helper where appropriate; argument/failure assertions keep local
    patches when they need direct mock inspection.
- [x] Move fork/cross-project/project-scoping tests to a focused fork test file.
  - Assertion: setup remains local unless it is shared by multiple destination files.
- [x] Move resume/native/proxy/supervisor launch tests to a focused resume test file.
  - Assertion: resume-specific launch argument and routing assertions remain explicit.
- [x] Move set/reset/inspect/transactional/cwd guard tests to a focused overrides test file.
  - Assertion: override behavior assertions are unchanged.
- [x] Delete or shrink `tests/src/cli/test_session_commands.py`.
  - Assertion: the old file is no longer a 4,933-line catch-all.

## Acceptance tests

| Test                       | Fixture                               | Assertion                                                   | Test File                                   |
| -------------------------- | ------------------------------------- | ----------------------------------------------------------- | ------------------------------------------- |
| Session CLI split collects | split command files                   | pytest discovers the moved tests                            | `tests/src/cli/test_session_*.py`           |
| Successful launch helper   | shared CLI fixture/helper             | successful-launch-only tests do not repeat raw patch target | `tests/src/cli/conftest.py` and moved files |
| Session CLI behavior       | existing tmp env and command fixtures | moved tests preserve current assertions                     | `tests/src/cli/test_session_*.py`           |

## Verification

- [x] `uv run pytest tests/src/cli/test_session_*.py -q`
- [x] `make pre-commit-md`
- [x] `git diff --check`
- [x] `make pre-commit`

## Closeout

- [x] Record pre-merge verification results.
- [x] Confirm current diff only includes intended board/test files.
- [x] Add a compact final entry to `docs/board/change_log.md` when this work is complete.
- [x] Move `doing/test-session-command-fixture-and-split/` to `done/` after the final merge to `main`.
