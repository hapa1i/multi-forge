# Extract status-line source facts

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 structural refactor work.

**Finding**: O070's source/data subset.

## Goal

Move neutral status-line types and proxy/transcript/session/git source acquisition into the existing `cli/statusline/`
package and invert its current imports away from the monolithic command module.

## Evidence and Authority

On `5777192a`, `status_line.py` remains about 1,808 lines. `statusline.context`, `palette`, and `registry` import the
command module for types, constants, and source helpers, so the existing package has not established a lower layer.
Authority:
[`docs/design_appendix.md` "A.8 Status line guidance"](../../../design_appendix.md#a8-status-line-guidance-3611) and
[`docs/developer/coding_standards.md` "Code Organization"](../../../developer/coding_standards.md#1-code-organization).

## Acceptance Criteria

- Neutral runtime/transcript types and source functions live below the entrypoint; `context`/`registry` no longer import
  `forge.cli.status_line` for source facts.
- Preserve lazy source union: disabled segments trigger no proxy/session/transcript/git work.
- Preserve timeout, malformed-input, missing-file, proxy-authority, and exit-0 fail-open behavior.
- Run status-line source/registry/unit/regression tests plus targeted status-line integration coverage.

## Exclusions

Do not move layout/ANSI rendering yet, change segment names/order, or reintroduce eager source discovery.
