# Wire the transcript reindex guard

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O092
subset).

**Lane**: `done/` -- shipped in PR #199 (`7b3ac2df`) after all five GitHub checks passed.

**Finding**: O092's `IndexState.needs_reindex` subset.

## Goal

Use `IndexState.needs_reindex` to avoid re-extracting and rewriting transcript snapshots whose recorded `mtime` and size
are unchanged instead of deleting the unused intended optimization.

## Evidence and Authority

Reverified on `93957659`: `needs_reindex` is definition/test-only while the startup-queue index handler always extracts,
decomposes, and rewrites all three search stores before marking the transcript indexed. The existing state contract
compares only `mtime` and size; it is not a content hash and cannot distinguish same-size content changes whose `mtime`
is deliberately restored. The focused 58-test search-state/startup-queue baseline passes. Authority:
[`docs/design.md` "3.8 Session artifacts"](../../../design.md#38-session-artifacts-plans--transcripts).

## Acceptance Criteria

- The startup-queue index handler skips extraction and all three search-store writes only when persisted state matches
  the transcript's current `mtime` and size.
- A new transcript, a missing state entry, or changed `mtime`/size still performs the full idempotent upsert sequence;
  the index-state entry is written only after all three stores succeed.
- Missing transcripts retain the marker before indexing. Corrupt, newer, or unreadable index state disables only the
  skip optimization: all three idempotent stores are still written, while the strict final state update retains the
  marker for the existing retry/poison path instead of allowing bookkeeping to gate searchability.
- `search rebuild-index` replaces index state from the successful extraction set in one locked write, so the explicit
  full-rebuild recovery path repairs corrupt/newer bookkeeping without per-document read-modify-writes.
- Tests pin unchanged-snapshot avoidance, changed and invalidated reindexing, state-write ordering, and repeated Stop
  behavior; the measured seam is extraction/store invocation count rather than elapsed time.

## Exclusions

Do not add content hashing, change index-state schema, alter Stop artifact copying or marker enqueueing, make rebuilds
incremental, or claim same-size/same-`mtime` content detection. Those are separate behavior and durability decisions.

## Compatibility and Test Tier

The index-state schema and full-rebuild all-artifacts replacement contract remain unchanged; rebuild now replaces its
bookkeeping consistently with the other three stores. Run search/index and startup-queue unit tests, regressions, and
the targeted Stop/artifact integration path because repeated Stop is the producer path even though the hook itself does
not change.

## Closeout

PR #199 merged as `7b3ac2df` with all five GitHub checks passing. The review follow-up restored fail-open search writes
when optimization state is unavailable and made explicit rebuild repair that state; order 21 remains parked for a
separate activation from this closeout.
