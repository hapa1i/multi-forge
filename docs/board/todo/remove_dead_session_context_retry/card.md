# Remove the dead session-context retry

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O052).

**Lane**: `todo/` -- accepted Wave 7 session cleanup work.

**Finding**: O052.

## Goal

Delete the duplicate index-only retry that cannot observe the manifest-corruption condition described by its comment.

## Evidence and Authority

On `5777192a`, the exception block repeats `manager.get_session_entry(session)` with the same inputs and no intervening
state change; that lookup cannot read the manifest condition named by the comment. Error authority remains
[`docs/design.md` "3.2 Contract files"](../../../design.md#32-contract-files-authoritative-paths).

## Acceptance Criteria

- Characterization tests prove corruption/unreadable errors still propagate and not-found references still reach UUID
  and manifest fallback resolution.
- Remove the duplicate call and stale explanation without changing ambiguity behavior.
- Run focused session-context and regression tests.

## Exclusions

Do not broaden exception handling, turn corruption into not-found, or change UUID/name/worktree fallback ordering.
