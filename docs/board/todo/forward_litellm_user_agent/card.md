# Forward LiteLLM User-Agent metadata

**Epic**: [`epic_cli_proxy_runtime_correctness`](../epic_cli_proxy_runtime_correctness/card.md).

**Finding**: O001 (HIGH) in [`review_combined.md`](../../review_combined.md#code-and-maintenance-findings).

**Lane**: `todo/` -- accepted Wave 5 member, parked behind the CLI contract members.

## Goal

Carry the inbound Claude Code User-Agent through the translated LiteLLM route using the existing sanitized adapter
metadata path.

## Design Authority

- [`docs/design_appendix.md` backend provider vocabulary](../../../design_appendix.md#a21-backend-instance-catalog-365--unified-backend-phase-12):
  backend-instance provider values and the collapsed client-factory routing enum are distinct vocabularies.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#5-interface-changes): translate external values at a
  typed boundary rather than comparing incompatible literals.

## Evidence

Rechecked on `3f3a3c6d`: `TierClientFactory.detect_provider_for_model()` returned `ModelProvider.LITELLM` with value
`litellm`, while the translated route's injection gate accepts `litellm_remote`, `litellm_local`, and `openrouter`. The
adapter's `_user_agent` forwarding and control-character sanitization already work once metadata reaches it.

## Expected Behavior

- A translated LiteLLM request carries the inbound User-Agent into `_user_agent` and the adapter's safe extra header.
- Missing User-Agent remains a no-op, and control characters/length continue through the existing sanitizer.
- Existing OpenRouter behavior remains compatible unless implementation evidence supports a separate change.

## Acceptance Criteria

- Add a marked O001 regression at the translated route boundary, not only the adapter helper.
- Cover LiteLLM local/remote model routes, missing/malicious values, streaming/non-streaming, and OpenRouter parity.
- Run focused proxy conversion/adapter tests, targeted proxy integration, and `make pre-commit`.

## Compatibility and Exclusions

- Do not forward authorization, API keys, cookies, or internal `X-Forge-*` correlation headers.
- Do not broaden the Anthropic-native or Responses passthrough request-header allowlists.
