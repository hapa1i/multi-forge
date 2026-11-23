# Resolve proxy authentication invalidation scope

**Status**: In progress on `refactor/proxy-auth-invalidation-scope`. Option 2 was chosen on 2026-11-23; see
[Decision](#decision) and the [checklist](checklist.md). Recorded on 2026-08-16 from review of Wave 7 order 16,
[`replace_legacy_tier_inference`](../../done/replace_legacy_tier_inference/card.md), which shipped in PR #195.

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
  authentication, in `complete()` and in `stream()`. A stale sibling makes one rejected upstream request. A
  non-streaming request is then retried once inside the same proxy request. A streaming request returns the error, and
  the adapter recovers on its next request.
- **What eviction does.** It is not what recovers the failed request. With the eviction removed, a retry on the same
  adapter still succeeds, because the core client has already dropped the rejected key. Eviction only guarantees a newly
  built adapter.
- **Why not option 1.** Wider eviction would spare each sibling its rejected request only when the first failure arrives
  on the non-streaming Messages path, the factory's only caller. A streaming authentication failure reaches the caller
  as an `authentication_error` chunk without a retry or a factory call, so siblings would still fail one by one after
  it. Each cache entry would also have to record its credential provider, which the collapsed `ModelProvider` value does
  not identify.
- **Residual cost.** Each stale sibling still makes one rejected upstream request, and a streaming caller sees that
  error. Removing it on both paths would need the core clients to detect a credential that another client invalidated.
  That is outside this card.
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
