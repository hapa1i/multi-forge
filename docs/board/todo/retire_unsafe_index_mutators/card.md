# Retire unsafe public index mutators

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O050).

**Lane**: `todo/` -- accepted Wave 7 durable-state cleanup work.

## Goal

Prevent test and future production callers from publishing or deleting index rows outside the row/manifest transaction
contracts.

## Acceptance Criteria

- Replace `IndexStore.add_session`, `add_from_state`, and `remove_session` callers with transaction-safe production or
  fixture builders.
- Retain only private lock-local primitives required by `create_session_txn` and `delete_session_txn`.
- Preserve row-first creation, in-lock compensation, binding uniqueness, delete ownership, and race fixtures.
- Run focused index/session/regression tests and targeted session integration coverage.
