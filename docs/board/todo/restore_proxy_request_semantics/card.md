# Restore proxy request semantics

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending fail-first regressions.

**Findings**: D030, O008, O015, and O035.

## Goal

Make proxy-owned tier configuration authoritative across initial/auth-retry requests and preserve required request
constraints while translating or force-enabling reasoning.

## Evidence and Authority

On `246aaff1`, undocumented tier environment variables override proxy config, auth retry omits the resolved tier,
reasoning pinning leaves incompatible sampling fields, and Anthropic `tool_choice:any` maps to OpenAI `auto`.
[`docs/design_appendix.md` §A.1](../../../design_appendix.md#a1-proxy-overlay-schema-364--user-edit-surface) defines
proxy precedence and the translated wire contract.

## Acceptance Criteria

- Runtime hyperparameters come from proxy-owned config, not undocumented tier env variables.
- Authentication retry requests the same resolved tier and does not cache a differently shaped client.
- Force-enabled thinking removes incompatible sampling parameters while recording only metadata about the mutation.
- Anthropic `any` maps to OpenAI `required`; `auto`, named-tool, and `none` mappings remain stable.
- Retain converter/intercept/client regressions and run translated-proxy integration tests.

## Compatibility and Exclusions

Do not absorb Wave 7 removal of legacy tier inference, change tier model selection, or expose request content in logs.
