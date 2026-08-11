# Harden command and state boundaries

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending fail-first regressions.

**Findings**: D034, D037, D038, and O027.

## Goal

Keep direct-command no-ops silent and reject malformed/reserved durable state at the shared validation chokepoints
rather than allowing internal output or raw type errors downstream.

## Evidence and Authority

On `246aaff1`, five direct-command no-session paths emit an internal third JSON shape; passport updates omit the
reserved path guard; search stores treat wrong top-level shapes as empty; and `unwrap_optional(list[str])` incorrectly
returns `str`. The two-outcome hook and strict-read contracts are in
[`docs/design.md` §3.11](../../../design.md#311-direct-commands-userpromptsubmit-dispatcher) and the developer coding
standards.

## Acceptance Criteria

- No-session direct-command paths emit nothing and exit 0; block outcomes remain unchanged.
- Every passport create/update path applies the same reserved-basename guard before writing.
- Wrong search container/element types raise the store-specific corruption error with rebuild guidance.
- `unwrap_optional` unwraps only real `Union[T, None]` types and leaves generic containers intact.
- Retain hook/passport/search/override regressions and run targeted search integration tests.

## Compatibility and Exclusions

Do not change valid passport frontmatter, search schema versions, override merge semantics, or hook block payloads.
