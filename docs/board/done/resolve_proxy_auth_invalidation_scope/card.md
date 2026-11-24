# Resolve proxy authentication invalidation scope

**Status**: Done. Merged into `main` on 2026-11-24 as `701b74d5` (PR #310). Option 2 was chosen on 2026-11-23; see
[Decision](#decision) and the [completed checklist](checklist.md). Recorded on 2026-08-16 from review of Wave 7 order
16, [`replace_legacy_tier_inference`](../replace_legacy_tier_inference/card.md), which shipped in PR #195.

## Problem

`TierClientFactory` caches adapters by `(model_name, tier)`, while each adapter's core client uses the global
`CredentialManager`, whose cache is keyed by underlying credential provider. On a non-streaming authentication failure,
the failed core client invalidates that provider's credential entry and discards its own HTTP client. The proxy then
calls `TierClientFactory.invalidate_and_retry` with the failed request's tier, which evicts and rebuilds only that one
adapter.

Sibling adapters can therefore retain HTTP clients constructed with the expired key. This includes other tiers for the
same model and can include other model IDs routed through the same `litellm_remote`, `litellm_local`, or `openrouter`
credential entry. Each sibling can recover when it fails independently, but it may make one avoidable rejected upstream
request before doing so or remain stale until the factory TTL expires.

The existing `tier=None` branch does not settle the contract. It has no production caller, evicts only other tiers of
one model, and rebuilds `proxy.default_tier` rather than the tier of the failed request. A test-only caller proves its
behavior, not that this is the supported invalidation interface.

## Decision required

Choose and document one coherent contract:

1. Evict every cached adapter sharing the invalidated credential provider, then rebuild the failed request's exact tier;
   or
2. retain exact-entry lazy recovery deliberately and delete the unused all-tier branch.

The decision must treat eviction scope and retry-tier selection as separate inputs. Wiring the current `tier=None`
branch directly would preserve neither the full credential-sharing boundary nor the failed request's tier-specific
hyperparameters.

## Decision

Option 2, chosen on 2026-11-23. `TierClientFactory.invalidate_and_retry` evicts and rebuilds only the failed
`(model, tier)` entry. Its `tier` argument is required and the all-tier branch is deleted.

- **Eviction scope.** Sibling adapters recover at the core-client layer. `LiteLLMClient` and `OpenRouterClient`
  invalidate their credential-provider entry and discard their own HTTP client whenever they classify a failure as
  authentication, in `complete()` and in `stream()`. With sequential requests and a valid replacement credential, a
  stale sibling makes one rejected upstream request. A non-streaming request is then retried once inside the same proxy
  request. A streaming request returns the error, and the adapter recovers on its next request. Requests already in
  flight on the stale HTTP client are each rejected or aborted.
- **What eviction does.** It is not what recovers the failed request. With the eviction removed, a retry on the same
  adapter still succeeds, because the core client has already dropped the rejected key. Eviction only guarantees a newly
  built adapter.
- **What option 1 would buy.** Provider-wide eviction would refresh every still-stale sibling whenever a non-streaming
  request fails authentication. It is cheap, because each cached adapter already holds its credential provider. With
  three stale adapters, a stream on the first and non-streaming requests on the other two, a prototype cut rejected
  upstream requests from three to two. It does nothing for traffic that only streams, because a streaming failure never
  calls the factory.
- **Classification gap.** Recovery starts only when a core client classifies a failure as authentication. It decides
  that from the error text (`authentication` or `unauthorized`), not the HTTP status. LiteLLM gateway rejections match.
  OpenRouter's documented messages for a deleted, disabled, or expired key (`Invalid API key`, `User not found.`,
  `API key expired`) do not. In a loopback replay of `User not found.`, requests failed as provider errors and kept
  sending the old key. The classifier predates this card.
- **Why option 2 anyway.** Stale siblings, the classification gap, and the in-flight abort all sit in the core clients.
  A fix there would apply to streaming and non-streaming traffic alike: classify on the SDK's typed 401, and let a
  client notice a credential that another client invalidated. That would leave factory eviction with nothing to add, so
  this card keeps reachable behavior unchanged and records the gaps. The proposed
  [`core_client_credential_recovery`](../../proposed/core_client_credential_recovery/card.md) card holds that work. If
  it is not taken up, option 1 is a worthwhile partial improvement.
- **Retry tier.** The rebuild uses the failed request's resolved tier, with no default-tier fallback. Another tier would
  apply that tier's hyperparameters to the retry (finding O015 in the
  [whole-repo maintenance findings](../../reviews/whole_repo_maintenance_findings.md)) and can return a cached adapter
  that still holds the rejected key.
- **Closing adapters.** The factory does not close an evicted adapter. `CoreLLMClientAdapter.aclose()` is a placeholder
  with no caller, and the failing core client has already closed its HTTP client. That close aborts other requests in
  flight on the same adapter, so provider-wide eviction with closing would extend the abort to every adapter sharing the
  credential.

## Evidence required before implementation

- Reverify production, test, dynamic, documentation, and supported-surface callers of `invalidate_and_retry`.
- Characterize cache identity at all three layers: factory `(model, tier)`, adapter HTTP client, and provider-scoped
  credentials.
- Cover a sibling tier for one model and a second model sharing the same credential provider.
- Preserve the one-retry limit and exact failed-request hyperparameters.
- Decide whether evicted adapters must be closed, including concurrent and in-flight request behavior.
- Run focused auth/cache tests and targeted Docker proxy integration coverage.

## Scope

This is a correctness and lifecycle decision, not part of O051's removal of nonexistent environment-based tier
inference. It must not change model routing, provider detection, credential precedence, or retry count incidentally.
