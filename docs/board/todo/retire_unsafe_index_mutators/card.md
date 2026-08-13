# Retire unsafe public index mutators

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O050).

**Lane**: `todo/` -- accepted Wave 7 durable-state cleanup work.

**Finding**: O050's public-mutator deletion phase.

**Depends on**: [`replace_unsafe_index_test_fixtures`](../replace_unsafe_index_test_fixtures/card.md).

## Goal

Delete the unsafe public mutators after every caller has moved to transaction-safe state builders.

## Evidence and Authority

On `5777192a`, `add_session`, `add_from_state`, and `remove_session` have no production callers, but approximately 183
test calls across 48 files make immediate deletion an oversized and unsafe fixture rewrite. The authority is
[`docs/design.md` "3.2 Contract files"](../../../design.md#32-contract-files-authoritative-paths) and the row-first
transaction contract in
[`docs/design.md` "3.3 Session file schema"](../../../design.md#33-session-file-schema-forgesessionjson).

## Acceptance Criteria

- Confirm the prerequisite leaves zero callers outside the definitions and lock-local transaction implementation.
- Delete `IndexStore.add_session`, `add_from_state`, and `remove_session` plus direct-only tests.
- Retain only private lock-local primitives required by `create_session_txn` and `delete_session_txn`.
- Preserve row-first creation, in-lock compensation, binding uniqueness, delete ownership, and race fixtures.
- Run focused index/session/regression tests and targeted session integration coverage.

## Exclusions

Do not make `create_session_txn`/`delete_session_txn` public-fixture shortcuts, relax collision checks, or change the
index/manifest lock order.
