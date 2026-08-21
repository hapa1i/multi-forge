# Reuse transcript-reference scans checklist

Current focus: implementation commit `cff6adc6` and all local gates are complete; publish the shared Batch 4 review.

## Phase 1 -- Pin the scan and ownership matrix

- [x] Add a fail-first native-relocate regression that counts one global index/manifest ownership scan.
- [x] Cover a launched child with ordinary/artifact and relocated-parent transcript IDs in the same scan.
- [x] Preserve an unlaunched child whose relocated-parent ID is its only cleanup candidate.
- [x] Retain adopted-source, same-path parent, co-resident sibling, corrupt-manifest, and concurrent replacement guards.

## Phase 2 -- Implement

- [x] Build the complete deduplicated candidate-ID set before scanning ownership.
- [x] Run `_find_shared_transcript_sessions` once and partition its mapping between ordinary and relocated cleanup.
- [x] Preserve path-resolved identity, cleanup order, warnings, and fail-closed state handling.

## Phase 3 -- Verify and publish

- [x] Run focused session delete, fork/native-relocate, shared-transcript, and O085 regression tests.
- [x] Commit O085 as its own implementation boundary after O081.
- [x] Run targeted native-relocate/session-lifecycle Docker coverage on the integrated Batch 4 head.
- [x] Run full unit, regression, pre-commit, documentation, board/link, and diff gates.
- [ ] Publish all three cards in one draft PR; close them together only after merge.

## Acceptance tests

| Boundary               | Fixture                                      | Assertion                                      | Tier                |
| ---------------------- | -------------------------------------------- | ---------------------------------------------- | ------------------- |
| Combined scan          | ordinary, artifact, and relocated parent IDs | one index traversal and one manifest read each | regression          |
| Partial launch         | no child UUID; relocated parent present      | relocated copy still receives one guarded scan | regression          |
| Shared native source   | parent or sibling resolves to same path      | shared relocated transcript survives           | existing regression |
| Corrupt/shared state   | raw fallback and adopted source              | ownership remains protected and observable     | existing regression |
| Concurrent replacement | replacement appears during cleanup           | replacement manifest/index ownership survives  | existing regression |

## Focused evidence (2026-08-21)

- Fail first: the O085 regression produced one intended failure because a launched native-relocate child issued separate
  ordinary/artifact and relocated-parent scans; the partial-launch one-scan control passed (`1 failed, 1 passed`).
- Final: 80 manager-delete, fork/native-relocate, shared/adopted/corrupt transcript, concurrent-replacement, and O085
  tests passed.
- The combined regression observes one helper call containing all three candidate IDs and exactly one manifest read for
  the target and each peer, while all shared transcripts survive.
- The first file-scoped static run found one `str | None` narrowing error at the reused cleanup root; an explicit
  invariant assertion corrected it, and repository-pinned Ruff, isort, Black, mypy, Pyright, secret, and hygiene hooks
  then passed.
- Integrated: real-Claude native relocation/resume and containerized worktree deletion each passed; the 165-test
  combined slice, 9,331 unit tests, 1,035 regressions, and full pre-commit gate passed.
