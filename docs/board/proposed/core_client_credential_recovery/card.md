# Recover replaced credentials in the proxy's core clients

**Status**: Proposed. Recorded on 2026-11-24 at the closeout of
[`resolve_proxy_auth_invalidation_scope`](../../done/resolve_proxy_auth_invalidation_scope/card.md), which shipped in PR
#310 and left these gaps unchanged.

## Problem

A running translated proxy picks up a replaced credential only after a core client classifies an upstream failure as
authentication. `LiteLLMClient` and `OpenRouterClient` then invalidate their provider's `CredentialManager` entry and
discard their own HTTP client. [design_runtime.md §3.6.3](../../../design_runtime.md#363-proxy-lifecycle-ux) states this
contract and its limits. Three of those limits can be removed in the core clients:

1. **Revoked OpenRouter keys are not recognized.** Classification matches `authentication` or `unauthorized` in the
   error text and ignores the HTTP status. OpenRouter documents `Invalid API key`, `User not found.`, and
   `API key expired` as its 401 messages for a deleted, disabled, or expired key, and none of them match. In a loopback
   replay of `User not found.`, requests failed as provider errors. The adapter kept sending the old key until the
   factory and credential cache TTLs expired (3600 seconds each by default).
2. **Stale siblings each fail once.** Every other cached adapter sharing the credential keeps its HTTP client and makes
   one rejected upstream request before it recovers. A non-streaming request is retried inside the same proxy request. A
   streaming caller receives an `authentication_error`.
3. **A refresh aborts requests in flight.** `_close_client()` closes the HTTP client that other requests on the same
   adapter are still using. On loopback, a stream already in flight ended after one chunk with `ProxyStreamError` type
   `api_error`.

## Direction to evaluate

- **Classification.** Classify on the SDK's typed 401 at all five sites: `complete()` and `stream()` in `openrouter.py`,
  and `complete()` and both stream paths in `litellm.py`. Decide whether the text match stays as a fallback.
- **Stale siblings.** Let a client notice a credential that another client invalidated, for example with a per-provider
  generation in `CredentialManager` that each client checks before reusing its HTTP client. Compare this with
  provider-wide eviction in `TierClientFactory`, which refreshes the remaining stale siblings whenever a non-streaming
  request fails authentication and does nothing for traffic that only streams. A prototype of that eviction cut rejected
  requests from three to two in mixed traffic.
- **Requests in flight.** Replace the HTTP client without closing it under requests that are still using it.

## Evidence required before implementation

- Confirm the status and message of a real OpenRouter rejection for a revoked key. The current evidence is OpenRouter's
  documentation and a loopback replay.
- Establish whether any supported upstream reports an authentication failure with a status other than 401 before the
  text match is removed. LiteLLM 1.102.2 words gateway rejections as `Authentication Error, ...`.
- Cover streaming and non-streaming requests, a sibling tier, and a second model sharing the credential, as
  `tests/src/proxy/test_client_factory_integration.py` does for LiteLLM.
- Cover concurrent requests on one stale adapter. Two concurrent requests produced two rejections.
- Add a case under `tests/integration/proxy/` that drives a real proxy through an upstream 401. None exists.

## Scope

Core-client recovery only. This must not change credential precedence, the one-retry limit, model routing, or the cache
TTL defaults. A key held in the proxy process's environment still needs a restart.
