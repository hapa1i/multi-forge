# Extract status-line rendering and remove ineffective process caches

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 structural/deletion work.

**Findings**: O070 plus O092's status-line cache and `render_categories` parameter subsets.

**Depends on**: [`centralize_cli_metric_formatting`](../../done/centralize_cli_metric_formatting/card.md) and
[`extract_statusline_sources`](../extract_statusline_sources/card.md).

## Goal

Move pure segment formatting, ANSI width/truncation/wrapping, and final layout into the `statusline` package, leaving a
thin stdin/discovery/render entrypoint.

## Evidence and Authority

On `5777192a`, formatting/layout accounts for most of the command module, production passes three empty category lists
to `render_categories`, and `_transcript_cache`/`_numstat_cache` cannot help across one-render processes.
`RenderContext` already caches per-render facts. Authority:
[`docs/design_appendix.md` "A.8 Status line guidance"](../../../design_appendix.md#a8-status-line-guidance-3611).

## Acceptance Criteria

- Pure rendering modules own formatting, palette/glyph application, visible width, truncation, wrapping, and the two
  real output buckets with acyclic imports.
- Remove only parameters proven empty and module caches proven ineffective; keep `RenderContext` lazy per-render cache
  and the file-backed throttle.
- Default and configured segment golden fixtures remain byte-identical across wide/narrow, ANSI, Unicode, malformed,
  proxy, direct, and ambient inputs; the entrypoint always exits 0.
- Run all status-line units/regressions and targeted sidecar/status-line integration coverage.

## Exclusions

Do not change default order, colors/glyphs, billing/cap precision, hardening separator, source laziness, or the
file-backed cache-hit throttle.
