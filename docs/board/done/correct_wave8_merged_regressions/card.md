# Correct Wave 8 merged regressions

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #222 (`02e0ced9`) on 2026-08-20.

**Execution**: `agent/fix-automated-review-regressions` from pushed `main` at `113b5670713a0338d97aa5b24259e9d8d14a33b8`
on 2026-08-20.

## Goal

Repair three independently reproduced regressions found by the post-merge automated review without broadening the
original provider-trace, worktree-copy, or CLI output contracts.

## Verified Failures

| Origin  | Boundary                              | Reproduction                                                                                                                        |
| ------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| PR #216 | translated Messages provider dispatch | `temperature=3.0` fails adapter validation before upstream I/O but writes a false provider trace; streaming has the same root cause |
| PR #219 | worktree runtime-config destination   | replacing a destination parent with a symlink during the Git tracked-file probe creates and writes outside the worktree             |
| PR #220 | `extension enable --dry-run` output   | a conflict routes the complete preview to stderr even though dry-run previews are stdout results                                    |

## Scope

- Signal provider dispatch from the client adapter only after request shaping and hyperparameter validation, and gate
  both streaming and non-streaming failure traces on that signal.
- Recheck destination symlink and no-overwrite invariants after Git I/O and immediately before copying.
- Keep conflict-bearing dry-run plans on stdout while emitting only the terminating failure diagnostic on stderr.
- Retain regression coverage at the three original ownership seams.

## Constraints

- Preserve provider capability gating, cost/metrics accounting, response shapes, and auth-retry trace behavior.
- Preserve per-file tracked-content decisions and the existing recheck-based path-safety model; prevent copied file
  content from escaping through a destination symlink.
- Do not change non-dry-run conflict diagnostics or successful dry-run output.
- Do not activate Wave 8 order 7 as part of this correction.

## Acceptance

- Invalid translated hyperparameters await no provider call and write no provider trace in either request mode.
- A provider call that fails after dispatch still writes exactly one incomplete trace.
- A destination-parent swap during the tracked-file probe copies nothing and creates nothing outside the worktree.
- A conflicting dry-run exits non-zero with the preview on stdout and only its failure diagnostic on stderr.
- Focused, unit, regression, required integration, pre-commit, board-link, and diff checks pass.

## Verification

The 72-test direct regression slice, 57-test adjacent proxy-routing/auth slice, four targeted Docker integration tests,
9,328 unit tests, and 964 regression tests passed. Pre-commit, the 59,979-token living design-doc check, the
402-document/975-link board check, and diff checks passed. PR #222 merged as `02e0ced9` with all five GitHub checks
passing.
