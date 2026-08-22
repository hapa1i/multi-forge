# Lock walkthrough and QA state-script parity

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped in PR #188 (`b8e4b32c`) on 2026-08-15.

**Finding**: O073.

## Goal

Keep both installed skills self-contained while making their intentionally shared state machine impossible to drift
silently.

## Evidence and Authority

Rechecked on `3260a6fa`: both 1,190-line scripts still differ only in two skill-identity docstring lines, the 93-test
state-machine suite still imports only the walkthrough copy, and broad mypy still excludes the same-named QA script.
Installed skill packages must remain executable without importing the Forge tool environment, so replacing one copy with
a package import is not a safe simplification. Authority:
[`docs/design_installation.md` "D. Interactive Manual Testing"](../../../design_installation.md#d-interactive-manual-testing)
and
[`docs/developer/testing_guidelines.md` "Interactive Manual Testing"](../../../developer/testing_guidelines.md#interactive-manual-testing-forgesmoke-test-smoke-test-forgewalkthrough-forgeqa).

## Acceptance Criteria

- One checked-in source/generation rule or a normalization parity guard defines the shared executable body.
- The same behavioral test matrix runs against both installed script copies; allowed skill-specific text is explicit.
- Verify runtime skill compilation/list/status/sync/disable paths, build a wheel, and inspect both clean-installed skill
  packages.

## Exclusions

Do not make an installed script depend on `src/forge`, symlinks, the repository checkout, or a non-system Python
environment. Preserve both skills' names and package-local paths.

## Implementation Outcome

Both skills retain executable, package-local state scripts. A source-parity contract pins the two exact identity lines,
compares every other byte including line endings and the final newline, and requires matching owner-executable modes.
The behavioral suite loads each script under a collision-free module name and runs all 93 state-machine tests
independently against both copies. The QA script therefore remains excluded from mypy's colliding broad module map
without becoming an unchecked implementation.

The clean-wheel Docker lifecycle installs the full Claude profile, compares each installed script with its checked-in
source, verifies executable modes, and runs both scripts with system Python before exercising sync, status, and disable.
No production Forge import, generated source, symlink, script CLI, state schema, checklist contract, skill name, or
package path changed.

Verification passed with 188 focused parity/behavior tests, seven compiler/profile/lifecycle unit tests, 9,212 full unit
tests (one expected skip), all 906 regression tests, and one targeted clean-wheel Docker lifecycle test. The wheel and
source distribution build, clean-wheel runtime smoke, runtime-list check, full pre-commit, Markdown, and diff checks
pass. The board audit resolves all 870 local links across 341 Markdown files, confirms the 9-done/1-doing/25-todo Wave 7
graph, and finds no stale order-10 `todo/` target. PR #188 merged as `b8e4b32c` after all five GitHub checks passed; the
final closeout audit resolves the same 870 links and confirms the 10-done/0-doing/25-todo graph. Order 11 remains
parked.
