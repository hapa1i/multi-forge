# Extract status-line source facts checklist

Current focus: closed -- order 34 shipped in PR #213; order 35 later shipped in PR #214 and closed Wave 7.

- [x] Close order 33 on pushed `main`, create the order-34 branch from that exact commit, and activate only this member.
- [x] Reverify the 1,789-line command module, three upward package imports, 23 importing files, and 32 concentrated
  command-module patch sites.
- [x] Pin the source/import boundary before moving production symbols.
- [x] Move neutral proxy/transcript types and proxy, transcript, session, and Git acquisition below the entrypoint.
- [x] Route the command, render context, and registry through the lower source layer without eager work.
- [x] Preserve every source timeout, malformed-input, missing-file, authority, and fail-open result.
- [x] Keep palette, formatting, ANSI width/layout, final rendering, and process-cache deletion parked for order 35.
- [x] Update architecture ownership documentation without changing user-facing status-line semantics.
- [x] Run focused status-line units/regressions and targeted status-line integration coverage.
- [x] Run `make test-unit`, `make test-regression`, `make pre-commit`, design token checks, board integrity, and
  `git diff --check`.
- [x] Merge PR #213 as `e761d0d1` and close this member without activating order 35.

## Boundary map

| Concern                     | Current owner                    | Order-34 target                             |
| --------------------------- | -------------------------------- | ------------------------------------------- |
| Proxy runtime truth/probe   | `forge.cli.status_line`          | Lower `forge.cli.statusline` source module  |
| Transcript facts/scan/cache | `forge.cli.status_line`          | Lower `forge.cli.statusline` source module  |
| Session discovery           | `forge.cli.status_line`          | Lower `forge.cli.statusline` source module  |
| Git branch/numstat facts    | `forge.cli.status_line`          | Lower `forge.cli.statusline` source module  |
| Pure formatting and layout  | `forge.cli.status_line`          | Unchanged until order 35                    |
| Source planning/rendering   | `statusline.registry`/entrypoint | Same owners, consuming lower source symbols |

Existing source-plan and `RenderContext.cached_property` tests are the characterization boundary: configured segments
must acquire only their declared proxy/session sources once, while transcript and Git derivations remain lazy and cached
per render. No Forge workflow command is authorized for this member.

## Verification

- Focused status-line units/regressions: 348 passed; full units: 9,304 passed, one skipped, 122 deselected.
- Regressions: 925 passed. Targeted Docker status-line integration: 17 passed.
- Full pre-commit passed after expected import, Python, and Markdown normalization. Opus 5 local counts are 29,993 for
  `design.md` and 29,956 for `design_appendix.md`; 894 local links across 370 board documents resolve.
