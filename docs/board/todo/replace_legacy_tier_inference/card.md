# Replace legacy environment-based tier inference

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O051).

**Lane**: `todo/` -- accepted Wave 7 proxy cleanup work.

**Finding**: O051.

## Goal

Remove `_get_tier_for_model` lookup of nonexistent legacy environment variables and make tier provenance explicit at the
routing boundary.

## Evidence and Authority

On `5777192a`, no repository config defines the four queried environment variables. Production server paths already pass
the resolved tier, while a small number of direct tests call auth retry without one. The merged O015 correction requires
retry to preserve the original tier. Authority:
[`docs/design.md` "3.6.12 Subprocess routing resolution"](../../../design.md#3612-subprocess-routing-resolution-normative)
and
[`docs/design_appendix.md` "G. Subprocess Routing Reference"](../../../design_appendix.md#g-subprocess-routing-reference).

## Acceptance Criteria

- Characterize callers, cache keys, hyperparameter selection, and the coupled auth-retry behavior before changing them.
- Callers pass a resolved tier or use one named routing default; logs do not claim auto-detection that did not occur.
- No compatibility environment shim remains unless an independently verified consumer is admitted.
- Run focused client-factory/routing tests and targeted proxy integration coverage.

## Exclusions

Do not change configured model IDs, explicit-backend mapping, provider detection, cache invalidation breadth, or the
authentication retry count.
