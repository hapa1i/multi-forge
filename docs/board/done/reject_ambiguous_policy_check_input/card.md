# Reject ambiguous policy-check input

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in Batch 3 PR #227 (`f3353042`).

**Finding**: O077 (LOW correctness).

## Goal

Require exactly one content source for `forge policy check` instead of silently preferring stdin diff over an explicit
file.

## Verified Evidence

The command rejects neither `--file PATH --diff` nor its short-form equivalent. Its `if use_diff` branch ignores the
file bytes while `tool_args.file_path` still records that ignored path, producing misleading evaluation context.

## Acceptance Criteria

- Reject both selectors together with a Click-style exit 2 diagnostic before reading stdin or the file.
- Continue requiring one selector and preserve file-only/diff-only target extraction, fail mode, JSON, and policy
  evaluation.
- Pin no-read side effects for the conflicting case.

## Verification

Run focused policy-check and output-stream tests, full unit/regression suites, targeted policy integration, and
`make pre-commit`.
