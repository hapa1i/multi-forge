# Extract status-line rendering and remove ineffective process caches

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped in PR #214 as `4c9dee34` after focused, full, regression, targeted status-line Docker,
pre-commit, and CI verification.

**Findings**: O070 plus O092's status-line cache and `render_categories` parameter subsets.

**Depends on**: [`centralize_cli_metric_formatting`](../../done/centralize_cli_metric_formatting/card.md) and
[`extract_statusline_sources`](../../done/extract_statusline_sources/card.md).

## Goal

Move pure segment formatting, ANSI width/truncation/wrapping, and final layout into the `statusline` package, leaving a
thin stdin/discovery/render entrypoint.

## Evidence and Authority

Reverified on `7ea1d1de`, the command remains 1,307 lines with 44 definitions; formatting/layout owns most of the file,
three lower modules import it upward, and 16 source/test files consume the command surface. Production passes three
empty category lists to `render_categories`, while `_transcript_cache`/`_numstat_cache` cannot help across one-render
processes and `RenderContext` already caches per-render facts. Nine test patches target only the entrypoint's terminal
width source, so that seam can remain command-owned while render helpers move cleanly. Authority:
[`docs/design_appendix.md` "A.8 Status line guidance"](../../../design_appendix.md#a8-status-line-guidance-3611).

## Acceptance Criteria

- Pure rendering modules own formatting, palette/glyph application, visible width, truncation, wrapping, and the two
  real output buckets with acyclic imports.
- Remove only parameters proven empty and module caches proven ineffective; keep `RenderContext` lazy per-render cache
  and the file-backed throttle.
- Default and configured segment golden fixtures remain byte-identical across wide/narrow, ANSI, Unicode, malformed,
  proxy, direct, and ambient inputs; the entrypoint always exits 0.
- Run all status-line units/regressions and targeted sidecar/status-line integration coverage.

## Outcome

The command is 130 lines with only `_get_terminal_width` and `status_line`; lower `formatting` and `rendering` modules
own presentation and final output, and no lower status-line module imports the command. The two real render buckets
replace three always-empty parameters. Transcript/numstat process caches are gone, while `RenderContext.cached_property`
and file-backed throttles retain effective reuse.

## Exclusions

Do not change default order, colors/glyphs, billing/cap precision, hardening separator, source laziness, or the
file-backed cache-hit throttle.
