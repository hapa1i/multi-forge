# Correct Recent Daily-Review Regressions Checklist

Activation base: `5d9fadc4` (`main`, 2026-08-22).

Current focus: implementation and required verification are complete; publish the review branch and keep post-merge
closeout in this lane until the fix ships on `main`.

## Verification and design mapping

- [x] Verify all five supplied claims against current source, tests, shipped cards, and design contracts.
- [x] Confirm the file-limit report is stale only about merge status: the broad wildcard is now on `main`.
- [x] Identify the two ratified snapshots from repository evidence and provider counts:
  `runtime_abstraction/checklist.md` (37,015 Opus tokens) and `session_op_layer_extraction/checklist.md` (31,694).

## Regression tests

- [x] Reproduce native-relocate sibling publication during ordinary cleanup.
- [x] Reproduce backspace-based secret reconstruction and residual unsafe C0 controls.
- [x] Reproduce malformed active-registry authority-report failure without repair.
- [x] Reproduce missing sync guidance for changed invocation overrides through config edit/reset.
- [x] Prove unrelated completed-card Markdown does not receive the historical exception.

## Implementation

- [x] Recheck a cached relocated-transcript ownership absence immediately before its unlink decision.
- [x] Normalize rendered terminal text before redaction and neutralize remaining unsafe controls.
- [x] Wrap strict active-registry inspection failures as actionable operation errors.
- [x] Share conditional skill-invocation sync guidance across config mutation paths.
- [x] Narrow the repository policy to the two exact historical paths.

## Verification and closeout

- [x] Run focused unit and regression tests (171 passed).
- [x] Run targeted session, policy-hook, and installer integration tests required by repository policy (4 passed).
- [x] Run full unit (9,588 passed, 117 deselected) and regression (1,061 passed) suites.
- [x] Run full pre-commit, including type, board/link, file-size, formatting, and secret checks; run the final diff
  check.
- [x] Review the final diff and synchronize the session design and end-user authority guidance.
- [ ] Commit, push, and open the bugfix PR.
- [ ] After merge, record the completed work in `change_log.md` and move the card to `done/`.
