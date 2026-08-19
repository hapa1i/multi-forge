# Remove the dead session-context retry

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O052).

**Lane**: `done/` -- shipped in PR #196 (`bc4f3a0c`) on 2026-08-16.

**Finding**: O052.

## Goal

Delete the duplicate index-only retry that cannot observe the manifest-corruption condition described by its comment.

## Evidence and Authority

Reverified on `2ec0f92d`: `SessionManager.get_session_entry` delegates directly to the index store. After the first
unscoped lookup raises `ForgeSessionError`, the exception block repeats the same call with the same identifier and no
intervening mutation. It cannot read the manifest condition named by the comment. The adjacent explicit catches already
propagate index corruption and unreadable-state errors. Error authority remains
[`docs/design.md` "3.2 Contract files"](../../../design.md#32-contract-files-authoritative-paths).

## Acceptance Criteria

- Characterization tests prove corruption/unreadable errors still propagate and not-found references still reach UUID
  and manifest fallback resolution.
- Remove the duplicate call and stale explanation without changing ambiguity behavior.
- Run focused session-context and regression tests.

## Exclusions

Do not broaden exception handling, turn corruption into not-found, or change UUID/name/worktree fallback ordering.

## Outcome

Explicit identifiers now perform exactly the intended scoped and unscoped name lookups before UUID-index and stale-
manifest fallback. The duplicate unscoped retry and its incorrect manifest-corruption explanation are gone. Direct
controls pin corruption, unreadable-state, and ambiguity propagation plus both fallback stages.

PR #196 merged as `bc4f3a0c` after 185 focused tests, 9,205 unit tests (one skip, 122 deselected), 913 regressions, 23
targeted Docker session-lifecycle tests, full pre-commit, board/design checks, and all five GitHub checks passed. No
Forge workflow command was used.
