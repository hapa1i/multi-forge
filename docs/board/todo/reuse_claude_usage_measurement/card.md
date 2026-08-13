# Reuse Claude usage measurement resolution

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 usage refactor work.

**Finding**: O055.

## Goal

Make verb-usage emission use the shared Claude measurement resolver instead of reimplementing its proxied precedence.

## Evidence and Authority

On `5777192a`, `emit_verb_usage` repeats the proxy measurement branch already owned by `resolve_claude_p_measurement`.
Authority: [`docs/design.md` "3.14 Cost tracking and spend caps"](../../../design.md#314-cost-tracking-and-spend-caps)
and the usage-attribution schema in
[`docs/design_appendix.md` "A.13"](../../../design_appendix.md#a13-usage-attribution-ledger-schema-314).

## Acceptance Criteria

- One resolver owns direct/proxied cost, token, and provenance precedence for Claude verb events.
- Golden event fixtures retain request/run IDs, source, status, nullable cost, token counts, and interactive exclusion.
- Run `tests/src/core/usage/test_emit.py`, measurement/ledger tests, and usage regressions.

## Exclusions

Do not change billing classification, fabricate missing cost, or merge Codex and Claude measurement rules.
