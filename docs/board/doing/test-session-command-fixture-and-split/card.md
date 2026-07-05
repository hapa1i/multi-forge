# Test session command fixture and split

**Status**: Doing. Spun out of the repo-level `refactor-audit` quick scan on 2026-07-05.

**Type**: Behavior-preserving test refactor. This is a single card, not an epic.

## Problem

`tests/src/cli/test_session_commands.py` has become the catch-all home for session CLI behavior. It is currently 4,933
lines, with command concerns already separated by class but still packed into one file. The file is hard to navigate,
and small changes to one command family pull reviewers into a very large unrelated diff context.

The same file also repeats the common "successful Claude launch" patch shape:

```python
patch("forge.core.ops.claude_session.invoke_claude", return_value=0)
```

The quick scan found 106 copies of that exact patch in `test_session_commands.py`, plus nearby copies in other session
CLI tests. There is no `tests/src/cli/conftest.py`, so command tests have no local place to centralize shared CLI
fixtures and launch stubs.

## Evidence

- `wc -l tests/src/cli/test_session_commands.py`: 4,933 lines.
- The file is already naturally segmented by command classes:
  - `TestSessionList`, `TestSessionShow`, `TestSessionShowPlanInfo`, `TestSessionShowPolicy`
  - `TestSessionStart`, `TestSessionDelete`, `TestSessionIncognito`
  - `TestSessionFork`, `TestSessionForkIntoPreflight`
  - `TestSessionResumeExtended`, `TestSessionResume`, `TestResumeNativeMode`
  - `TestProxyDirectFlags`, `TestSupervisorProxyFlags`, `TestSupervisorLaunchControls`
  - override/reset/inspect/transactional/cwd guard groups
- Exact successful launch patches in `tests/src/cli/test_session_commands.py`: 106.
- `tests/src/cli/conftest.py` does not exist.
- `src/forge/core/ops/` does not show Click/Rich/console coupling in the audit probe, so this card should not invent a
  production extraction to solve a test-organization problem.
- `docs/board/doing/` is empty, so this can sit as a clean proposed card until accepted.

## Target shape

Create a local CLI test fixture module and split the mega-file by command family while preserving test names,
assertions, and behavior.

Suggested destination files:

| File                                         | Likely contents                                                     |
| -------------------------------------------- | ------------------------------------------------------------------- |
| `tests/src/cli/conftest.py`                  | Shared CLI fixtures and a successful Claude launch patch helper     |
| `tests/src/cli/test_session_list_show.py`    | list/show/show-plan/show-policy tests                               |
| `tests/src/cli/test_session_start_delete.py` | start/delete/incognito/main command group tests                     |
| `tests/src/cli/test_session_fork.py`         | fork, fork-into, cross-project, and project-scoping tests           |
| `tests/src/cli/test_session_resume.py`       | resume, native-mode, proxy/direct flag, and supervisor launch tests |
| `tests/src/cli/test_session_overrides.py`    | set/reset/inspect override and cwd guard tests                      |

The exact split can change during execution if imports or shared setup show a cleaner boundary, but each new file should
have a command-oriented reason to exist.

## Execution sketch

1. Add `tests/src/cli/conftest.py` with a small successful-launch helper or fixture, then migrate a small cluster of
   tests to prove the helper does not hide meaningful assertions.
2. Move list/show tests into a focused file and verify collection still preserves the same behavioral coverage.
3. Move start/delete/incognito tests, keeping any setup that is genuinely command-local in that destination file.
4. Move fork/resume/proxy/supervisor groups, extracting only duplicated fixture setup that is used by multiple
   destination files.
5. Move override/reset/inspect/cwd guard tests and either delete the old mega-file or leave it only for intentionally
   cross-command smoke coverage.

## Acceptance

- `tests/src/cli/test_session_commands.py` is deleted or reduced to a small cross-command smoke file, not a 4,933-line
  catch-all.
- Repeated direct successful-launch patches are materially reduced in `tests/src/cli/`; tests use the shared helper
  where it describes intent better than an inline patch.
- Test names and assertions remain behavior-preserving. No tests are skipped, deleted, or weakened solely to make the
  split easier.
- Reviewers can reason about a list/show/start/fork/resume/override change by opening one focused test file plus shared
  fixture setup.
- Focused verification passes:

```bash
uv run pytest tests/src/cli/test_session_*.py -q
```

- Before closeout, run the repo-standard unit or pre-commit path appropriate for the final diff.

## Non-goals

- Do not move production session code as part of this card.
- Do not re-open the completed `session_op_layer_extraction` work or remove compatibility shims from that card.
- Do not fold regression tests into this split unless an existing regression file explicitly belongs with the command
  family being moved.
- Do not convert every `invoke_claude` patch in the repository. Start with the CLI session command surface.
- Do not include the separate Codex `HeadlessResult` test factory idea here; that is a possible follow-up card.

## Risks / open questions

- Hidden dependencies between classes may appear once files are split. Prefer moving shared setup into `conftest.py`
  only after the dependency is real and repeated.
- A helper around `invoke_claude` could hide important per-test assertions if it becomes too broad. Keep it narrow:
  "successful launch" should be distinct from tests that assert exact launch arguments or failure behavior.
- Decide during execution whether the launch stub is best as a fixture returning a mock/context manager or as a plain
  helper function imported from `conftest.py`.
- The top-level tests in `test_session_commands.py` should move by behavior, not merely remain at the top of a legacy
  file because they predate the class layout.

## Prediction

After this card, the next three session CLI behavior changes should usually touch one focused test file plus
`tests/src/cli/conftest.py`, rather than a 4,933-line catch-all.
