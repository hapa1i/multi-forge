# Characterize explicit-backend model mapping

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O093).

**Lane**: `todo/` -- accepted Wave 7 investigation; not a deletion authorization.

## Goal

Determine whether `map_model_name` can be simplified without breaking the verified explicit-backend routing path.

## Acceptance Criteria

- Characterize Anthropic aliases and explicit OpenRouter/LiteLLM backend IDs across message and token-count routes.
- Prove which branches transform the selected model, pass it through, or only log before proposing code removal.
- Preserve all live behavior unless a subsequent evidence-backed card explicitly authorizes a change.
- Run focused routing invariants and targeted proxy integration tests.
