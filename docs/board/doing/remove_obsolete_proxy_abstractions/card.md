# Remove obsolete proxy abstractions

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O047–O048).

**Lane**: `doing/` -- active on `refactor/remove-obsolete-proxy-abstractions` from `cc03a4e6`.

**Findings**: O047, O048, and the `TierClientFactory.get_cache_status` / `clear_cache` subset of O092.

## Goal

Remove the test-only model-spec module, unused abstract client, and unreachable ToolCallError handling without losing
coverage of live model detection, adapter behavior, or failure metrics.

## Evidence and Authority

Rechecked on `cc03a4e6`: `forge.proxy.model_spec` has no source, resource, entry-point, extension, or documentation
importer; `AbstractLLMClient` has no implementer; no production path raises `ToolCallError`; and both factory diagnostic
methods have zero callers. The synthetic ToolCallError metrics test is the only live behavior worth moving.
Compatibility is governed by
[`docs/developer/coding_standards.md` "Compatibility evidence before deletion"](../../../developer/coding_standards.md#compatibility-evidence-before-deletion)
and [`docs/design_appendix.md` "E. Shared LLM Client"](../../../design_appendix.md#e-shared-llm-client-srcforgecorellm).

## Acceptance Criteria

- Re-verify repository, entry-point, resource, extension, and documentation consumers before deletion.
- Move synthesized ToolCallError metric assertions to a reachable error path before deleting the exception and handlers.
- Delete obsolete self-only tests; retain characterization of live model detection and the actual client adapter
  protocol.
- Update stale comments/imports. Run `tests/src/proxy/test_model_spec.py`, client-factory/server/metrics tests, the full
  proxy unit slice, and targeted proxy integration coverage.

## Compatibility and Exclusions

This card removes internal, unsupported surfaces only. It must not change provider request/response conversion,
`map_model_name`, cache keys, error wire shapes, or the metrics schema. O051 owns tier inference separately.

## Implementation Outcome

The unused abstract client, unproduced tool-call exception and handlers, test-only model-spec module, self-only tests,
and two zero-caller factory diagnostics are gone. The live `ProxyStreamError`, concrete `CoreLLMClientAdapter`, model
resolution, cache lifecycle, conversion paths, error wire shapes, and metrics schema remain in place.

The former synthetic `ToolCallError` metric test now drives an ordinary client failure through the reachable generic
API-error path and pins its sanitized 500 response plus total, error-type, tier, and model counters. Verification passes
with 829 pre-deletion proxy characterization tests; 67 focused unit, 46 focused regression, and 808 post-deletion proxy
tests; 9,193 full unit tests with one expected skip; all 907 regression tests; four hermetic Docker OpenAI-routing proxy
tests; and the full pre-commit gate.
