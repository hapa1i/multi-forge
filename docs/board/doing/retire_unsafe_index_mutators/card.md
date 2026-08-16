# Retire unsafe public index mutators

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O050).

**Lane**: `doing/` -- active on `refactor/retire-unsafe-index-mutators` from `0e8e1cbb`.

**Finding**: O050's public-mutator deletion phase.

**Depends on**: [`replace_unsafe_index_test_fixtures`](../../done/replace_unsafe_index_test_fixtures/card.md).

## Goal

Delete the unsafe public mutators after every caller has moved to transaction-safe state builders.

## Evidence and Authority

Reverified on `0e8e1cbb`: `add_session`, `add_from_state`, and `remove_session` have no external production callers.
Only `add_from_state` calls another member internally; 18 executable calls remain in direct API contracts in
`tests/src/session/test_index.py`, plus one stale non-call test assignment to `add_from_state`. Order 14 moved every
ordinary fixture to transaction-safe builders. The authority is
[`docs/design.md` "3.2 Contract files"](../../../design.md#32-contract-files-authoritative-paths) and the row-first
transaction contract in
[`docs/design.md` "3.3 Session file schema"](../../../design.md#33-session-file-schema-forgesessionjson).

## Acceptance Criteria

- Confirm the prerequisite leaves zero callers outside the definitions and lock-local transaction implementation.
- Delete `IndexStore.add_session`, `add_from_state`, and `remove_session` plus direct-only tests.
- Retain only private lock-local primitives required by `create_session_txn` and `delete_session_txn`.
- Convert the fixture drift guard from a direct-contract allowlist to a zero-reference invariant.
- Remove stale live-code, test, and developer-guide references without rewriting historical completed-work records.
- Preserve row-first creation, in-lock compensation, binding uniqueness, delete ownership, and race fixtures.
- Run focused index/session/regression tests and targeted session integration coverage.

## Exclusions

Do not make `create_session_txn`/`delete_session_txn` public-fixture shortcuts, relax collision checks, or change the
index/manifest lock order.
