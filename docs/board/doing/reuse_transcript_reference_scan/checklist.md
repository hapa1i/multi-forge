# Reuse transcript-reference scans checklist

Current focus: pin O085's two-scan native-relocate delete and all sharing safeguards before changing deletion flow.

## Phase 1 -- Pin the scan and ownership matrix

- [ ] Add a fail-first native-relocate regression that counts one global index/manifest ownership scan.
- [ ] Cover a launched child with ordinary/artifact and relocated-parent transcript IDs in the same scan.
- [ ] Preserve an unlaunched child whose relocated-parent ID is its only cleanup candidate.
- [ ] Retain adopted-source, same-path parent, co-resident sibling, corrupt-manifest, and concurrent replacement guards.

## Phase 2 -- Implement

- [ ] Build the complete deduplicated candidate-ID set before scanning ownership.
- [ ] Run `_find_shared_transcript_sessions` once and partition its mapping between ordinary and relocated cleanup.
- [ ] Preserve path-resolved identity, cleanup order, warnings, and fail-closed state handling.

## Phase 3 -- Verify and publish

- [ ] Run focused session delete, fork/native-relocate, shared-transcript, and O085 regression tests.
- [ ] Commit O085 as its own implementation boundary after O081.
- [ ] Run targeted native-relocate/session-lifecycle Docker coverage on the integrated Batch 4 head.
- [ ] Run full unit, regression, pre-commit, documentation, board/link, and diff gates.
- [ ] Publish all three cards in one draft PR; close them together only after merge.

## Acceptance tests

| Boundary               | Fixture                                      | Assertion                                      | Tier                |
| ---------------------- | -------------------------------------------- | ---------------------------------------------- | ------------------- |
| Combined scan          | ordinary, artifact, and relocated parent IDs | one index traversal and one manifest read each | regression          |
| Partial launch         | no child UUID; relocated parent present      | relocated copy still receives one guarded scan | regression          |
| Shared native source   | parent or sibling resolves to same path      | shared relocated transcript survives           | existing regression |
| Corrupt/shared state   | raw fallback and adopted source              | ownership remains protected and observable     | existing regression |
| Concurrent replacement | replacement appears during cleanup           | replacement manifest/index ownership survives  | existing regression |
