# Align LiteLLM streaming cost tests and documentation

**Status**: Done on 2026-10-29. [PR #286](https://github.com/hapa1i/multi-forge/pull/286) merged as `bbb9e269`. See
[merged closeout](checklist.md#merged-closeout) and [verification](verification.md). Accepted on 2026-10-28; recorded on
2026-10-16 from the deferred integration failure in
[prompt-cache correctness](../../done/prompt_cache_correctness/checklist.md#phase-5-verification).

## Problem

`test_local_litellm_streaming_cost_unavailable` in
[`test_cost_visibility_e2e.py`](../../../../tests/integration/proxy/test_cost_visibility_e2e.py) asserted that local
LiteLLM streaming produces no cost, reporter, or available cost provenance. The prompt-cache verification recorded this
failure among 66 passing integrations. Pinned LiteLLM 1.102.0 now stamps a calculated `usage.cost` into streamed usage
through `_stamp_streaming_usage_cost`; Forge's existing
[`LiteLLMClient`](../../../../src/forge/core/llm/clients/litellm.py) already consumes body cost from the final usage
chunk. Neither path was introduced by the prompt-cache change.

The [telemetry cost/cap contract](../../../design_telemetry.md#314-cost-tracking-and-spend-caps) described LiteLLM
streaming dollar caps as no-ops, and the
[usage-provenance contract](../../../design_telemetry.md#a13-usage-attribution-ledger-schema-314) listed streaming
LiteLLM cost as unavailable. These blanket statements needed reconciliation with the pinned gateway's reported fields.

## Scope and acceptance

- Characterize the pinned gateway's final streamed usage and Forge's cost propagation before changing expectations.
  Distinguish gateway-calculated `usage.cost` from provider-reported cost; retain accurate reporter/confidence values.
- Replace the obsolete universal-unavailability assertion with coverage for a stream carrying cost and one carrying no
  cost. Keep tokens observable in both cases. Missing cost remains unknown in amount (`cost_micros=null`,
  `reporter=null`, `confidence=unavailable`); do not invent zero spend or restore catalog estimates.
- Verify that observed streamed cost reaches downstream telemetry and spend-cap accounting once, while absent final
  usage or absent cost retains the existing unavailable fallback. Use injected chunks/transport fixtures for the
  deterministic cases, plus focused proxy integration coverage through the standard runner.
- Update the telemetry design and any affected cost documentation to describe evidence-dependent behavior, including
  older or remote gateways that omit cost. Correct stale client comments if they assume body cost comes only from
  OpenRouter through LiteLLM.

This follow-up owns tests, provenance verification and documentation against the pinned gateway. It does not change
cache-marker placement, model routing, provider pricing or the LiteLLM dependency pin. Planning needs no paid calls;
this card authorizes none. Any later live confirmation requires its own applicable authorization and retained evidence.
