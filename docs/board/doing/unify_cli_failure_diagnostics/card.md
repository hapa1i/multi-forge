# Unify CLI failure diagnostics

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `doing/` -- active on `agent/unify-cli-failure-diagnostics` from pushed closeout `2da22c2a`.

**Findings**: D056 (MEDIUM) and the verified failure-stream subset of O097 (LOW).

## Goal

Send every line of one non-zero CLI diagnostic -- header, details, and recovery -- to stderr.

## Verified Evidence

Workflow preflight prints its `Error:` header through the stderr helper, then writes bullets and tips through the stdout
console. Current extension version/compatibility/enable/sync failure arms and supervisor input errors repeat the same
split or print red failure text on stdout. JSON workflow failure already uses stderr and is out of scope.

Authority: [`cli_style_guidelines.md` Output Streams](../../../developer/cli_style_guidelines.md) and
`tests/src/cli/test_output_streams.py`.

The style guide already defines the shipped result/diagnostic stream contract. This member restores implementation
conformance without changing command shapes, human wording, or JSON schemas, so no new end-user or design semantics are
required.

## Acceptance Criteria

- Route the verified workflow, extension, and policy failure details/tips through `err_console` or one shared
  error-with-tip helper.
- Keep stdout empty on those non-zero paths; preserve exact exit codes and actionable text.
- Keep successful results, warnings that continue execution, prompts, and JSON payload shapes unchanged.
- Extend the output-stream guard with representative workflow, extension, and policy cases.

## Exclusions

Do not use this card to rename successful output, replace every `click.secho`, change `hint`/`tip` JSON schemas, or
normalize raw paths unrelated to a failure stream.

## Verification

Run focused CLI/output tests, full unit/regression suites, targeted workflow-worker and extension/installer Docker
coverage, clean-wheel verification for touched installer-loaded surfaces when required, and `make pre-commit`.
