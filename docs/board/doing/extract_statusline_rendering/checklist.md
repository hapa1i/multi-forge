# Extract status-line rendering checklist

Current focus: order 35 is active on `refactor/extract-statusline-rendering` from pushed `main` at `7ea1d1de`; it is the
final Wave 7 member.

- [x] Close order 34 on pushed `main`, create the order-35 branch from that exact commit, and activate only this member.
- [x] Reverify the 1,307-line command, 44 definitions, three upward package imports, 16 importing files, nine
  terminal-width patch sites, and one production render call with three empty lists.
- [x] Pin default/configured output bytes, fail-open behavior, and the target import/cache boundary before moving code.
- [x] Move presentation constants and pure segment formatting into a lower status-line rendering module.
- [x] Move ANSI width, truncation, wrapping, palette application, hardening, and final two-bucket layout below the
  entrypoint.
- [x] Route context, palette, registry, command, and tests through public lower helpers under unambiguous `fmt` aliases,
  without re-exports.
- [x] Remove only `_transcript_cache` and `_numstat_cache`; preserve `RenderContext`'s per-render cache and the
  file-backed cache-hit/cost/health throttles.
- [x] Replace `render_categories`' three proven-empty parameters with the real `where` and `stream` buckets.
- [x] Preserve default order, colors/glyphs, precision, separator, source laziness, and exit-0 behavior.
- [x] Update architecture and durable ownership documentation without changing user-facing status-line semantics.
- [x] Run all status-line units/regressions plus targeted sidecar/status-line Docker integration coverage.
- [x] Run `make test-unit`, `make test-regression`, `make pre-commit`, design token checks, board integrity, and
  `git diff --check`.
- [ ] Publish order 35 independently, then close Wave 7 in a later direct-`main` commit.

## Target boundary

| Concern                           | Current owner                    | Order-35 target                              |
| --------------------------------- | -------------------------------- | -------------------------------------------- |
| Presentation constants/formatters | `forge.cli.status_line`          | Lower `forge.cli.statusline` formatting      |
| ANSI width/truncate/wrap/layout   | `forge.cli.status_line`          | Lower `forge.cli.statusline` final rendering |
| Palette and glyph selection       | `statusline.palette` via command | Lower modules only; no upward import         |
| Source acquisition                | `statusline.sources`             | Unchanged                                    |
| Render-plan source laziness       | `statusline.registry`/context    | Unchanged                                    |
| Terminal-width acquisition        | `forge.cli.status_line`          | Unchanged entrypoint input                   |
| Process-local source caches       | `statusline.sources`             | Deleted; per-render/file throttles retained  |

The byte-level registry/status-line goldens and malformed-input/failing-producer regressions are the characterization
boundary. No Forge workflow command is authorized for this member.

## Verification

- Focused status-line units/regressions: 357 passed; full units: 9,309 passed, one skipped, 122 deselected.
- Regressions: 925 passed. Targeted Docker status-line integration: 17 passed.
- Full pre-commit passed after expected import/Markdown normalization. Opus 5 local counts are 29,993 for `design.md`,
  29,970 for `design_appendix.md`, and 29,993 for `change_log.md`; 894 local links across 371 board documents resolve.
