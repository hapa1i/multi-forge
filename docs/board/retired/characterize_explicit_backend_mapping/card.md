# Characterize explicit-backend model mapping (retired)

> **RETIRED -- REFERENCE ONLY. DO NOT IMPLEMENT.**

**Outcome**: `invalidated`

**Retired**: 2026-08-13

**Epic**: [`epic_wave7_refactor_and_deletion`](../../done/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O093).

**Lane**: `retired/`. The investigation completed during Wave 7 admission and contradicted the deletion premise. No
replacement exists: `map_model_name` remains live behavior guarded by routing tests.

## Historical Goal

Determine whether `map_model_name` can be simplified without breaking the verified explicit-backend routing path.

## Outcome Evidence

On `5777192a`, request handling consumes the mapped value for explicit backends. Fresh-config tests prove mapping occurs
at call time; OpenRouter fixtures prove slash-ID pass-through and Anthropic alias translation. The admission's focused
mapping/SSE slice passed 23 tests. There is no evidence-backed simplification to execute, so this card is not a live
Wave 7 member and must not be counted as shipped work.

## Historical Investigation Criteria

- Characterize Anthropic aliases and explicit OpenRouter/LiteLLM backend IDs across message and token-count routes.
- Prove which branches transform the selected model, pass it through, or only log before proposing code removal.
- Preserve all live behavior unless a new proposed card supplies contrary executable evidence.
- Run focused routing invariants and targeted proxy integration tests.
