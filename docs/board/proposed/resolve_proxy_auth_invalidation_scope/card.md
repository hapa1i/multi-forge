# Resolve proxy authentication invalidation scope

**Status**: Proposed. Recorded on 2026-08-16 from review of Wave 7 order 16,
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
