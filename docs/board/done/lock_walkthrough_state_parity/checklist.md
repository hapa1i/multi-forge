# Lock walkthrough and QA state-script parity checklist

Current focus: complete -- order 10 shipped in PR #188 (`b8e4b32c`); orders 11--35 remain parked.

## Activation and evidence

- [x] Close order 9 on pushed `main`, create `refactor/lock-walkthrough-state-parity` from `3260a6fa`, and move only
  order 10 to `doing/`.
- [x] Recheck both 1,190-line scripts: their executable bodies are identical and only two skill-identity docstring lines
  differ.
- [x] Run the existing walkthrough-owned behavioral matrix (93 passed) and confirm the QA copy is excluded from broad
  mypy solely because both standalone files map to the same module name.
- [x] Select a normalization parity guard plus dual-copy behavioral parametrization; retain two physical installed
  scripts and no runtime import or generation dependency.

## Implementation

- [x] Make the two allowed skill-identity lines explicit, reject every other source difference, and require matching
  owner-executable modes.
- [x] Run the complete state-machine test matrix against both installed source copies.
- [x] Correct the script, type-check configuration, design appendix, and testing-guide ownership language to describe
  parity-locked self-contained copies.
- [x] Preserve both package-local paths, skill names, script CLI behavior, state schema, and checklist semantics.

## Acceptance tests

| Boundary          | Fixture                                      | Assertion                                                      |
| ----------------- | -------------------------------------------- | -------------------------------------------------------------- |
| Source parity     | both checked-in `walkthrough-state.py` files | only two identity lines differ; modes match and are executable |
| Behavioral parity | complete state-machine test matrix           | every test passes independently for walkthrough and QA         |
| Installed package | compiled and clean-installed skill packages  | each contains its own executable script with the guarded body  |
| Runtime lifecycle | runtime list/enable/status/sync/disable      | skill selection and tracked package ownership remain unchanged |

## Verification and closeout

- [x] Run focused parity and dual-copy tests (188 passed), full unit (9,212 passed, one expected skip), regression (906
  passed), and full pre-commit.
- [x] Run the targeted clean-wheel Docker installer/runtime-skill lifecycle (one passed).
- [x] Build the wheel/sdist, run the clean-wheel runtime smoke, and inspect both skill packages from an isolated
  install.
- [x] Run Markdown, 341-file/870-link board-integrity, 9-done/1-doing/25-todo lane, document-size, and diff checks;
  record the outcome without activating order 11.
- [x] Open draft PR #188 without activating order 11.
- [x] After PR #188 merged as `b8e4b32c`, add the change-log entry, move the card to `done/`, and keep order 11 parked.
