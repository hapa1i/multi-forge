# Lock walkthrough and QA state-script parity

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 bundled-skill maintenance work.

**Finding**: O073.

## Goal

Keep both installed skills self-contained while making their intentionally shared state machine impossible to drift
silently.

## Evidence and Authority

On `5777192a`, both 1,190-line scripts differ only in two ownership/docstring lines, but only the walkthrough copy runs
through its state-machine suite. Installed skill packages must remain executable without importing the Forge tool
environment, so replacing one copy with a package import is not a safe simplification. Authority:
[`docs/design_appendix.md` "D. Interactive Manual Testing"](../../../design_appendix.md#d-interactive-manual-testing)
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
