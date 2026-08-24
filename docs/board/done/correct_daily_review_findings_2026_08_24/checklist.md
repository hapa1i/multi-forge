# Correct Daily Review Findings 2026-08-24 Checklist

Activation base: `d1fccd21` (`main`, 2026-08-24).

## Transcript Safety

- [x] Add fail-first coverage for a current UUID that aliases the relocated parent while a sibling publishes during
  ordinary cleanup.
- [x] Route the aliased UUID exclusively through the publication-locked final owner scan and unlink.

## Model-Route Replay and Launch

- [x] Share replay-request derivation that preserves a coherent `[1m]` execution modifier across resume and fork.
- [x] Require exact stored template and proven source identity during bare replay.
- [x] Apply neutral `selected_tier` after proxied Claude model-pin validation.
- [x] Stop automatic route selection at the first candidate that passes admission.
- [x] Let explicitly constrained replacement ignore malformed stored routing state.
- [x] Add focused command-core and CLI regressions for every corrected route boundary.

## Repository Boundaries

- [x] Separate lexical Git membership from resolved containment in Markdown link validation.
- [x] Reject non-Claude direct route candidates and non-plain-integer schema versions contextually.
- [x] Add focused script and catalog regressions.

## Verification

- [x] Run focused unit and regression tests for all nine findings.
- [x] Run required targeted session and routing integration slices.
- [x] Run `make test-unit` and `make test-regression`.
- [x] Run `make pre-commit`, board/link checks, and `git diff --check`.

Evidence:

- Focused transcript, route-planning, resume/fork, Claude launch, catalog, and Markdown candidate-state tests passed.
- `./scripts/test-integration.sh tests/integration/docker/test_session_routing.py`: 2 passed.
- `make test-unit`: 9,882 passed, 117 deselected.
- `make test-regression`: 1,069 passed.
- `make pre-commit`: all hooks passed; Markdown, board-link, and diff checks passed at closeout.

## Closeout

- [x] Synchronize normative design wording where the corrected invariant needs clarification.
- [x] Record verification evidence and a compact change-log entry.
- [x] Move the completed card to `done/` and repoint inbound links.

## Acceptance Tests

| Test                           | Fixture                                                      | Assertion                                          | Test File                                                             |
| ------------------------------ | ------------------------------------------------------------ | -------------------------------------------------- | --------------------------------------------------------------------- |
| Aliased relocated cleanup race | native-relocate child and late sibling share one UUID/path   | sibling manifest never survives without transcript | `tests/regression/test_bug_o085_reuse_transcript_reference_scan.py`   |
| `[1m]` replay                  | stored neutral route plus matching `[1m]` direct projection  | resume/fork keep modifier and 1M context           | `tests/src/core/ops/test_session_model_routing.py`, CLI session tests |
| Stored route drift             | persisted template/source differs from registry/config       | bare replay fails without rewriting state          | `tests/src/core/ops/test_session_model_routing.py`                    |
| Explicit recovery              | malformed stored proxy route plus explicit model/proxy       | replacement plan succeeds                          | `tests/src/cli/test_session_resume.py`                                |
| Selected Claude tier           | proxied Claude model served at non-intrinsic tier            | child receives neutral selected tier               | `tests/src/cli/test_session_model_pins.py`                            |
| Automatic first candidate      | first admitted config is incompatible, second is compatible  | first compatibility error propagates               | `tests/src/core/ops/test_session_model_routing.py`                    |
| Deleted symlink                | symlink removed from index, referent remains tracked         | link target is absent from candidate state         | `tests/src/scripts/test_check_markdown_links.py`                      |
| Strict route catalog           | non-Claude direct candidate and invalid schema-version types | contextual catalog error                           | `tests/src/core/models/test_model_routes.py`                          |
