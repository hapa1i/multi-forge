# Complete proxy instance config wiring

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending fail-first regressions.

**Findings**: D029 and O025.

## Goal

Preserve template-declared tool-ignore and prompt-cache settings through the template-to-instance-to-runtime pipeline.

## Evidence and Authority

On `246aaff1`, `tool_prefixes_to_ignore` exists only on `ProxyConfig`, while `create_proxy_file()` omits it and also
lets `prompt_caching`/`auto_cache_min_tokens` fall back to instance defaults.
[`docs/design_appendix.md` §A.1](../../../design_appendix.md#a1-proxy-overlay-schema-364--user-edit-surface) assigns
proxy overlay ownership and precedence.

## Acceptance Criteria

- All four fields survive template load, instance serialization/reload, and runtime config projection.
- Existing instance files without the fields retain current defaults.
- Extend the structural wiring guard so future shared-field additions cannot silently skip a hop.
- Retain regression/config round-trip tests and run proxy creation integration coverage.

## Compatibility and Exclusions

No migration rewrite is required for absent optional fields. Do not change model mapping, provider credentials, or
unrelated proxy block ownership.
