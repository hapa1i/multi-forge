# Wire the transcript reindex guard

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O092
subset).

**Lane**: `todo/` -- accepted Wave 7 maintenance work.

**Finding**: O092's `IndexState.needs_reindex` subset.

## Goal

Use `IndexState.needs_reindex` to avoid re-extracting and rewriting byte-identical transcript snapshots instead of
deleting the unused intended optimization.

## Evidence and Authority

On `5777192a`, `needs_reindex` is definition/test-only while Stop still re-extracts an unchanged snapshot. Its intended
content/mtime guard is covered by `tests/src/search/test_index_state.py`. Authority:
[`docs/design.md` "3.8 Session artifacts"](../../../design.md#38-session-artifacts-plans-transcripts).

## Acceptance Criteria

- Stop/index behavior skips unchanged snapshots and reindexes changed, missing, or invalidated inputs as specified.
- Atomic state updates and failure recovery remain intact.
- Tests cover content/mtime edge cases and repeated Stop invocation; measure the avoided work where practical.

## Compatibility and Test Tier

Index-state schema and atomic recovery remain unchanged. Run search/index unit and regression tests plus the targeted
Stop/artifact integration path because hook behavior changes even though output does not.
