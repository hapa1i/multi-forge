# Exclude interactive usage cost checklist

Current focus: D031 is implemented and verified on `agent/exclude-interactive-usage-cost`; prepare it for independent
review without activating another Wave 6 member.

## Activation

- [x] Close O013/O034 after PR #172 (`366c216a`) and record the bookkeeping on `main` at `7280d177`.
- [x] Start `agent/exclude-interactive-usage-cost` from that merged-main cursor.
- [x] Move only D031 to `doing/` and keep the remaining four Wave 6 members parked.

## Fail-first reproduction

- [x] Prove an all-interactive root contributes no exact cost and does not query the cost plane.
- [x] Prove an excluded interactive run is removed from a mixed shared-root result while its non-interactive sibling
  retains exact total and command attribution.
- [x] Retain controls for an orphan cost record under an included root, explicit inclusion, and activity counts that
  intentionally keep the interactive event (`3 failed, 3 passed` on `7280d177`).

## Implementation

- [x] Derive included roots and excluded run ids from the event plane before querying exact cost.
- [x] Remove excluded run ids from both dollar-bearing and presence-only cost-plane sets.
- [x] Preserve per-subtree snapshot suppression, partial-cost semantics, and raw proxy spend (`223 passed` in the
  focused usage/activity/status-line and adjacent mixed-root slice).

## Verification and closeout

- [x] Run focused usage-summary, activity CLI, status-line cost, and adjacent mixed-root regression tests
  (`223 passed`).
- [x] Run the marked regression (`821 passed`) and unit (`9001 passed, 1 skipped, 122 deselected`) gates.
- [x] Run the affected activity CLI integration slice (`1 passed, 45 deselected`) and full pre-commit (all hooks passed
  after the expected formatter normalization pass).
- [x] Confirm the implementation restores the existing design/end-user contract without changing its text.
- [x] Run board link/lane/size and diff checks (293 Markdown files, 718 relative links and 2 changed-document fragments
  with none missing, Wave 6 at 8 done / 1 doing / 4 todo, the active-checklist size check passed, and clean
  `git diff --check`).
- [x] Open draft PR #173 for independent review before activating another Wave 6 member.

## Acceptance tests

| Test                 | Fixture                                                    | Assertion                                                       | Test file                                                  |
| -------------------- | ---------------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------- |
| All-interactive root | one interactive event plus exact cost record               | no root query and no joined cost                                | `tests/regression/test_bug_d031_interactive_cost_plane.py` |
| Mixed shared root    | interactive and non-interactive runs with exact records    | only non-interactive cost and command attribution remain        | `tests/regression/test_bug_d031_interactive_cost_plane.py` |
| Presence-only record | interactive presence plus non-interactive exact cost       | excluded presence does not make the joined result partial       | `tests/regression/test_bug_d031_interactive_cost_plane.py` |
| Included-root orphan | non-interactive event plus an unobserved child cost record | both exact costs remain joined                                  | `tests/regression/test_bug_d031_interactive_cost_plane.py` |
| Explicit inclusion   | interactive event with exclusion disabled                  | interactive exact cost remains available to intentional callers | `tests/regression/test_bug_d031_interactive_cost_plane.py` |
| Activity counts      | mixed interactive and non-interactive events               | both event-plane call counts remain visible                     | `tests/regression/test_bug_d031_interactive_cost_plane.py` |
