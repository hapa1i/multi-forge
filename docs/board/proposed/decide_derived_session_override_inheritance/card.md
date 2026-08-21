# Decide derived-session override inheritance

**Origin**: D040 residual admission recheck on merged `main` at `bad273ef` (2026-08-19).

**Lane**: `proposed/` -- design decision required; not accepted for implementation.

**Parent epic**: [`epic_repo_maintenance_round`](../../done/epic_repo_maintenance_round/card.md) (completed provenance).

## Question

When fork, fresh resume, and relaunch derive a child, should live parent overrides be copied as overrides, baked into
the child's baseline intent, or omitted except for explicitly inheritable fields?

## Verified Evidence

- `_inherit_intent_fields` deep-copies raw baseline intent for fork, fresh resume, and relaunch.
- `apply_memory_inheritance` then deliberately reads effective parent memory and bakes only `auto_update` into the
  child; this matches the shipped memory-specific inheritance contract.
- Fresh resume and fork do not copy the generic `overrides` map, so an effective `%policy disable` can disappear while
  an effective memory toggle is retained. Relaunch copies the entire override map and therefore behaves differently.
- Design §3.3 defines overrides as live toggles but does not say whether those toggles cross a derivation boundary.
  Existing docs explicitly promise memory activation and selected lane/intent inheritance, not generic override
  propagation.

The asymmetry is real, but D040's proposed correction is not grounded enough to execute: making every child inherit
effective state could unexpectedly propagate temporary policy suspension, while dropping memory's effective value would
break an explicit contract.

## Decision Required

Choose and document behavior separately for fork, fresh resume, and relaunch:

1. copy raw intent plus selected explicit inheritance only;
2. copy raw intent and the parent's generic overrides; or
3. materialize effective values into a fresh child baseline and clear inherited overrides.

The decision must address transient policy suspension, consumer lanes, immutable launch/runtime keys, malformed legacy
overrides, reset semantics, and whether relaunch should remain distinct. Only then create an implementation card with
fixture-grounded acceptance tests.
