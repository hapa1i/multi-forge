# Replace legacy environment-based tier inference

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O051).

**Lane**: `doing/` on `refactor/replace-legacy-tier-inference`, branched from the order-15 closeout at `358b39d6`.

**Finding**: O051.

## Goal

Remove `_get_tier_for_model` lookup of nonexistent legacy environment variables and make tier provenance explicit at the
routing boundary.

## Evidence and Authority

Reverified on `358b39d6`: no repository config defines any queried `_MODEL` environment variable. Every production
`get_client` call already passes the tier resolved by the request boundary, and the authentication retry passes that
same tier. The only omitted-tier call is a regression that directly exercises all-tier invalidation; one earlier
regression is the sole direct consumer of `_get_tier_for_model`. Cache keys and tier hyperparameters both use the tier
argument. Authority: [`docs/design.md` "3.6.1 Definitions"](../../../design.md#361-definitions-normative) and the
user-owned [`proxy.default_tier`](../../../end-user/proxy.md#proxy-file-format-user-edit-surface).

## Acceptance Criteria

- Characterize callers, cache keys, hyperparameter selection, and the coupled auth-retry behavior before changing them.
- Callers pass a resolved tier or use one named routing default; logs do not claim auto-detection that did not occur.
- No compatibility environment shim remains unless an independently verified consumer is admitted.
- Run focused client-factory/routing tests and targeted proxy integration coverage.

## Exclusions

Do not change configured model IDs, explicit-backend mapping, provider detection, cache invalidation breadth, or the
authentication retry count.

## Outcome

`get_client` now requires the caller's resolved tier, so cache identity and tier hyperparameters cannot fall through to
an environment guess. The nonexistent `_MODEL` lookup and false auto-detection log are gone. The internal all-tier retry
retains its original invalidation breadth and rebuilds `proxy.default_tier`; production authentication retry continues
to rebuild the exact tier that failed. Model selection, provider detection, retry count, and wire behavior are
unchanged.

## Deferred follow-up

Post-PR review confirmed that the `tier=None` branch is test-only and that the production auth-failure path evicts only
the failed `(model, tier)` adapter. The underlying credential cache is provider-scoped, so the intended invalidation
domain may be wider than either one tier or all tiers for one model. The proposed
[`resolve_proxy_auth_invalidation_scope`](../../proposed/resolve_proxy_auth_invalidation_scope/card.md) card owns the
explicit decision; this card does not broaden invalidation or change retry hyperparameters.
