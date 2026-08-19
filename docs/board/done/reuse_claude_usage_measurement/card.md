# Reuse Claude usage measurement resolution

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped in PR #204 (`356ea665`) after all five GitHub checks passed.

**Finding**: O055.

## Goal

Make verb-usage emission use the shared Claude measurement resolver instead of reimplementing its proxied precedence.

## Evidence and Authority

Reverified on `5eb39d15`: `emit_verb_usage` still repeats the proxied `caller="verb"` cost, token, reporter, confidence,
and measurement-source branch already owned by `resolve_claude_p_measurement`. Its four production callers are the
panel, analyze, debate, and consensus aggregates; the session-result and worker emitters already use the shared
resolver. The focused usage/ledger regression baseline is 116 passing tests. Authority:
[`docs/design.md` "3.14 Cost tracking and spend caps"](../../../design.md#314-cost-tracking-and-spend-caps) and the
usage-attribution schema in
[`docs/design_appendix.md` "A.13"](../../../design_appendix.md#a13-usage-attribution-ledger-schema-314).

## Acceptance Criteria

- One resolver owns direct/proxied cost, token, and provenance precedence for Claude verb events.
- Golden event fixtures retain request/run IDs, source, status, nullable cost, token counts, and interactive exclusion.
- Run `tests/src/core/usage/test_emit.py`, measurement/ledger tests, and usage regressions.

## Exclusions

Do not change billing classification, fabricate missing cost, or merge Codex and Claude measurement rules.

## Closeout

PR #204 merged as `356ea665` with all five GitHub checks passing. Workflow verb aggregates now use
`resolve_claude_p_measurement`; the shared resolver also treats an inconsistent synthetic cost flag as unmeasured while
leaving the production tracker invariant unchanged. Order 26 remains parked for separate activation from this closeout.
