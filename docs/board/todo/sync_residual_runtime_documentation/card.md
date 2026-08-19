# Sync residual runtime documentation

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 8 order 19; parked.

**Findings**: D042, narrowed D044, and O082 (LOW documentation/comment drift).

## Goal

Make the sidecar mount model, CLI reference, and workflow precedence comment describe current shipped behavior exactly.

## Verified Evidence

- `sidecar/container.py` mounts `~/.forge/config.yaml` read-only, and the appendix names why, but design §7's exhaustive
  global-mount paragraph omits the file.
- `cli_reference.md` now includes config leaves and supervisor cascade, but still omits `forge auth logout`,
  `forge auth profiles`, and `workflow list-models --available`.
- The consensus source comment says `positional > -p > stdin` while the code evaluates `-p` before positional.
- D043 is already resolved: current `design.md` has no `src/forge/status/` component reference.

## Acceptance Criteria

- Add the read-only runtime-config file to design §7 without weakening the narrow global-mount statement.
- Add only the three still-missing CLI surfaces and their existing behavior/options.
- Correct the precedence comment to `-p > positional > stdin`; do not change parsing.
- Keep design/CLI-reference token budgets and local Markdown links within repository limits.

## Verification

Run `make pre-commit-md`, documentation token checks, board/doc link checks, and `git diff --check`.
