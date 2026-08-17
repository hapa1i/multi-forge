# Wire the transcript reindex guard checklist

Current focus: complete -- order 20 shipped in PR #199 (`7b3ac2df`); orders 21--35 remain parked.

## Activation and evidence

- [x] Close order 19 on pushed `main` at `93957659` after PR #198 merged as `7fd701b5` with all five checks passing.
- [x] Create `refactor/wire-transcript-reindex-guard` from that exact closeout and move only order 20 to `doing/`.
- [x] Recheck `needs_reindex`, the startup-queue index handler, Stop artifact copying/enqueueing, full rebuild, cleanup,
  state-store errors, tests, documentation, and history on the execution base.
- [x] Correct the card's byte-identity claim: the version-1 state fingerprint is `mtime` plus size, not content.
- [x] Record the 58-test search-state/startup-queue baseline before implementation.

## Implementation

- [x] Read index state after project/path/file validation and skip extraction plus all three upserts only when readable
  metadata matches.
- [x] Preserve the full metadata, BM25, and content upsert order for new, changed, or invalidated transcripts.
- [x] Treat state-read failure as an unavailable optimization rather than a searchability gate; keep `mark_indexed` last
  and strict so the completed store writes remain searchable while the marker records a retry.
- [x] Make full rebuild replace fresh index state once under lock, repairing corrupt/newer bookkeeping and removing the
  per-transcript read-modify-write loop without making the rebuild incremental.
- [x] Leave Stop copying/enqueueing, the full-replacement contract, index-state schema, and same-size/same-`mtime`
  limitations unchanged.

## Acceptance controls

| Surface            | Fixture                                               | Assertion                                                                         |
| ------------------ | ----------------------------------------------------- | --------------------------------------------------------------------------------- |
| First index        | marker with a new transcript                          | extraction and all three stores run; state is marked last                         |
| Metadata match     | second marker for the unchanged snapshot              | marker succeeds without extraction or store writes                                |
| Changed snapshot   | indexed transcript with changed `mtime` or size       | full upsert path runs and state refreshes                                         |
| Invalidated state  | stores exist but the transcript state entry is absent | full upsert path runs again                                                       |
| State read failure | corrupt/newer/unreadable `state.json`                 | all three stores update; strict final mark leaves state unchanged and retries     |
| Full rebuild       | corrupt/newer `state.json` with valid artifacts       | stores and fresh state replace successfully in one locked state write             |
| Repeated Stop      | same session UUID captured twice                      | latest changed artifact remains searchable; unchanged drain avoids duplicate work |

## Verification and closeout

- [x] Run focused search-state, startup-queue, search CLI, and named regression tests after review fixes (107 passed).
- [x] Run `make test-unit` (9,215 passed, one skipped, 122 deselected), `make test-regression` (915 passed), and
  `make pre-commit`.
- [x] Run the targeted Docker Stop/artifact integration path required for hook/session producer coverage (one passed, 12
  deselected).
- [x] Run diff, design-size, board-link, and Wave 7 lane-count checks without a Forge workflow (354 board documents, 880
  local links, zero missing; 19 done, one doing, 15 todo; normative docs unchanged).
- [x] Open PR #199, merge it as `7b3ac2df` after all five checks pass, and close order 20 without activating order 21.
