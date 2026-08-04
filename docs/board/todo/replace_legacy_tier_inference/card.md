# Replace legacy environment-based tier inference

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O051).

**Lane**: `todo/` -- accepted Wave 7 proxy cleanup work.

## Goal

Remove `_get_tier_for_model` lookup of nonexistent legacy environment variables and make tier provenance explicit at the
routing boundary.

## Acceptance Criteria

- Characterize callers, cache keys, hyperparameter selection, and the coupled auth-retry behavior before changing them.
- Callers pass a resolved tier or use one named routing default; logs do not claim auto-detection that did not occur.
- No compatibility environment shim remains unless an independently verified consumer is admitted.
- Run focused client-factory/routing tests and targeted proxy integration coverage.
