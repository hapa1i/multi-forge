# Align CLI failure surfaces

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #174 (`095fcd90`).

**Findings**: D032, D041, O005, O031, O032, and O033.

## Goal

Make high-frequency CLI/read surfaces fail predictably: status-line stays fail-open, missing/invalid command context
exits non-zero, diagnostics stay on stderr, and every `$EDITOR` surface honors shell-style argv.

## Evidence and Authority

Rechecked on merged `main` at `13ecef87`: status-line still assumes object-shaped JSON/workspace and lets malformed URLs
raise; bare `forge` and selectorless `session show` still exit 0; cross-project and workflow preflight failures still
split to stdout; four editor paths still pass the whole `$EDITOR` string as argv[0]. Disposable CLI probes observed
empty-output exit 1 for JSON scalars and `workspace: null`, a raw `ValueError` for malformed IPv6 syntax, exit 0 for
both missing-command cases, and the two split-stream failures. The authority is
[`docs/developer/cli_style_guidelines.md`](../../../developer/cli_style_guidelines.md) plus
[`docs/design_telemetry.md` §A.8](../../../design_telemetry.md#a8-status-line-guidance-3611).

The retained final regression artifact collected `19 failed, 4 passed` on that unchanged production cursor. Ten failures
cover top-level/workspace input shapes and malformed proxy URL syntax, five cover root/show exit and diagnostic streams,
and four cover the editor surfaces. Controls preserve valid status input, explicit root help, ambient JSON session
context, and one-token editor invocation.

## Acceptance Criteria

- Status-line emits a bounded error/fallback and exits 0 for JSON scalars, null/wrong-typed workspace, and malformed
  URL.
- Bare root help and missing human `session show` context follow the documented non-zero no-args/missing-selector shape.
- Cross-project tips and JSON workflow preflight errors are entirely on stderr.
- Proxy, template, runtime-config, and Claude-preset edit use the shared `shlex.split` launcher and preserve validation.
- Extend `tests/src/cli/test_output_streams.py`; retain marked regressions and status-line integration coverage.

## Compatibility and Exclusions

Do not change successful stdout payloads, status-line configured segments, editor validation/temporary-file recovery, or
interactive selection cancellation semantics. Human workflow preflight still splits its header from its details and
tips; that human-mode sibling is recorded as D056 and requires its own execution gate.

## Implementation Outcome

- Status-line now rejects non-object JSON with a bounded exit-0 status error, normalizes a wrong-typed workspace to
  missing input, and treats malformed proxy URL syntax as an unconfigured proxy.
- The root group uses Click's standard no-args help contract; selectorless human `session show`, cross-project hints,
  and workflow preflight JSON now use non-zero/stderr failure shapes without changing successful JSON output.
- One shared helper parses and validates shell-style `$EDITOR` argv. Proxy, template, runtime-config, and Claude-preset
  editors preserve their existing validation, temporary-file recovery, and editor-exit handling. The shared boundary
  also gives transfer edit and resume `--review` clean malformed-`$EDITOR` failures.
- Bundled workflow QA now captures JSON preflight failures from stderr without masking their nonzero exit. Existing
  design and end-user docs already specify the normative contracts, so they require no change.

## Verification

- Retained regressions: `23 passed` after producing `19 failed, 4 passed` on `13ecef87`.
- Focused status-line, command-tree, session, workflow, output-stream, and editor slice: `809 passed`.
- Marked regression gate: `844 passed`.
- Unit gate: `9005 passed, 1 skipped, 122 deselected`.
- Targeted Docker integration: `17 passed` for status-line and `2 passed` for session show.
- Bundled QA compatibility: `81 passed` for the content guard; the built wheel contains both stderr captures and the
  updated QA index.
- Full pre-commit: all hooks passed after the expected Markdown normalization pass.
- Board integrity: 295 Markdown files, 723 relative links and 2 changed-document fragments with none missing; the Wave 6
  lane graph is 9 done / 1 doing / 3 todo, the active checklist is 805 tokens, the change log is 22,792 tokens, and
  `git diff --check` is clean.
