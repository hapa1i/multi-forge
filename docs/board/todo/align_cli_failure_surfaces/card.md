# Align CLI failure surfaces

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending fail-first regressions.

**Findings**: D032, D041, O005, O031, O032, and O033.

## Goal

Make high-frequency CLI/read surfaces fail predictably: status-line stays fail-open, missing/invalid command context
exits non-zero, diagnostics stay on stderr, and every `$EDITOR` surface honors shell-style argv.

## Evidence and Authority

On `246aaff1`, status-line assumes object-shaped JSON/workspace and lets malformed URLs raise; bare `forge` and
selectorless `session show` exit 0; cross-project and workflow preflight failures split to stdout; four editor paths
pass the whole `$EDITOR` string as argv[0]. The authority is
[`docs/developer/cli_style_guidelines.md`](../../../developer/cli_style_guidelines.md) plus
[`docs/design_appendix.md` §A.8](../../../design_appendix.md#a8-status-line-guidance-3611).

## Acceptance Criteria

- Status-line emits a bounded error/fallback and exits 0 for JSON scalars, null/wrong-typed workspace, and malformed
  URL.
- Bare root help and missing human `session show` context follow the documented non-zero no-args/missing-selector shape.
- Cross-project tips and JSON workflow preflight errors are entirely on stderr.
- Proxy, template, runtime-config, and Claude-preset edit use the shared `shlex.split` launcher and preserve validation.
- Extend `tests/src/cli/test_output_streams.py`; retain marked regressions and status-line integration coverage.

## Compatibility and Exclusions

Do not change successful stdout payloads, status-line configured segments, editor validation/temporary-file recovery, or
interactive selection cancellation semantics.
