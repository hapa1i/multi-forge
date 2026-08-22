# Correct Recent Daily-Review Regressions Checklist

Activation base: `5d9fadc4` (`main`, 2026-08-22).

Current focus: complete -- [PR #239](https://github.com/hapa1i/multi-forge/pull/239) merged as `60af6b66` on 2026-08-22
with all five GitHub checks passing, and the card is closed in `done/`.

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

## PR #239 review follow-up

- [x] Reproduce the carriage-return leak on PR head and confirm that `main` redacts the same raw secret.
- [x] Benchmark a 1.01 MB control-free diagnostic on `main` (28.3 ms) and PR head (144.8 ms median).
- [x] Add fail-first direct and persistence/display regressions for destructive carriage-return rendering.
- [x] Redact both before and after rendering, skipping the second pass when rendering leaves text unchanged.
- [x] Keep control-free diagnostics on C-speed C0/DEL translation (29.5 ms median after the final fix).
- [x] Confirm DEL is discarded rather than emulated as backspace: its extra printable `X` remains visible, so the
  configured secret is not rendered and does not cross the diagnostic boundary.
- [x] Resolve the targeted Docker run's follow-on partial token-prefix match by deferring control-terminated heuristic
  fragments to post-render redaction; rerun the boundary successfully.
- [x] Run 66 focused Stop/hook tests, the targeted Docker hook boundary, 1,067 regressions, 9,588 unit tests with 117
  deselected, and full pre-commit.
- [x] Commit and push the follow-up, update the PR description, and confirm all five GitHub checks pass again.

## Verification and closeout

- [x] Run focused unit and regression tests (171 passed).
- [x] Run targeted session, policy-hook, and installer integration tests required by repository policy (4 passed).
- [x] Run full unit (9,588 passed, 117 deselected) and regression (1,061 passed) suites.
- [x] Run full pre-commit, including type, board/link, file-size, formatting, and secret checks; run the final diff
  check.
- [x] Review the final diff and synchronize the session design and end-user authority guidance.
- [x] Commit, push, and open [PR #239](https://github.com/hapa1i/multi-forge/pull/239).
- [x] After merge, record the completed work in `change_log.md` and move the card to `done/`.
