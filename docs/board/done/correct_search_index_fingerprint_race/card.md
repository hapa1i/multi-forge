# Stabilize search-index snapshot fingerprints

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `done/` -- corrected directly on `main` as `2bd556e9` after PR #206 closed and before Wave 7 order 28.

**Related shipped member**: [`wire_transcript_reindex_guard`](../../done/wire_transcript_reindex_guard/card.md) (O092
metadata guard).

This is a post-merge correctness edge in shipped order 20, not a reopened or renumbered review-ledger finding. The Wave
7 finding and member counts remain unchanged.

## Goal

Make incremental and bulk search indexing record the fingerprint of the transcript bytes they actually extracted, so a
concurrent artifact refresh cannot make index state describe newer bytes than the search stores contain.

## Evidence and authority

- PR #199 moved the live-path `stat()` to the end of incremental indexing. If the handler extracted snapshot B and a
  later Stop replaced the artifact with C before `mark_indexed()`, all three stores contained B while state recorded C;
  the fresh C marker could then be skipped as unchanged.
- Rebuild had the same mismatch: it extracted B, replaced the stores, and only then fingerprinted the live path while
  constructing fresh state.
- Deterministic pre-fix probes reproduced both outcomes on merged `main`. The incremental probe deleted the marker, and
  the rebuild probe reported success with stale searchable content and a fingerprint for C.
- The pending-work marker lock serializes one marker file; it does not protect the transcript artifact, which Stop
  refreshes before enqueueing the next marker.

Authority comes from the exact-state ordering contract in
[`wire_transcript_reindex_guard`](../../done/wire_transcript_reindex_guard/card.md) and the search artifact boundary in
[`docs/design.md`](../../../design.md#38-session-artifacts-plans--transcripts).

## Acceptance criteria

- Incremental indexing captures the transcript's version-1 `mtime`/size fingerprint before extraction and rejects a
  different fingerprint immediately after extraction.
- After all three stores succeed, index state records that captured fingerprint rather than re-statting the live path. A
  later mutation detected after the state write retains the marker for a clean retry.
- Rebuild records each successfully extracted snapshot's captured fingerprint in its single state replacement and warns
  the operator to rerun when an artifact changes while the stores are being replaced.
- Regression tests mutate the artifact during incremental and bulk store writes, prove that state describes the stored
  bytes, and prove that the next retry/rerun indexes the newer snapshot.
- The state schema and its `mtime`/size comparison remain unchanged.

## Scope boundaries

- Do not add content hashing, change the state or marker schemas, lock transcript artifacts, or change Stop capture and
  enqueue behavior.
- Do not claim detection when content changes while both size and modification time are deliberately preserved; that
  remains the explicit order-20 exclusion.
- Keep Wave 7 order 28 parked until this bounded correction is verified and pushed to `main`.

## Implementation outcome

One path-bound fingerprint value now follows each extracted transcript through the three stores and into index state.
Incremental processing retains its marker when the live artifact drifts during the pipeline; bulk rebuild retains the
exact stored snapshot fingerprint and emits rerun guidance for drift detected after replacement.

Verification passes 109 focused search/startup tests, 9,242 unit tests with one skip and 122 deselected, 923
regressions, one targeted Docker Stop/artifact integration, full pre-commit, and the 363-document/894-link board audit.
No Forge workflow command was used.
