# Remove the unreachable fork routing branch

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O096).

**Lane**: `todo/` -- accepted Wave 7 session cleanup work.

## Goal

Remove `session_fork`'s second `elif proxy_name` resolution after characterizing the precondition that every proxy name
already produces `_preflight_routing`.

## Acceptance Criteria

- Tests prove proxy, inherited, and direct modes choose the same effective template, URL, and proxy ID after deletion.
- Routing resolution still occurs once before mutation and retains current error output.
- Run focused fork/routing tests and targeted session integration coverage.
