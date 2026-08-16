# Remove the dead session-context retry checklist

Current focus: complete -- order 17 shipped in PR #196 (`bc4f3a0c`); order 18 remains parked pending activation.

## Activation and evidence

- [x] Close order 16 on pushed `main` at `2ec0f92d` after PR #195 merged as `aca65c7f` with all five checks passing.
- [x] Branch from that exact closeout and move only order 17 to `doing/`.
- [x] Reverify the duplicate lookup's inputs, exception taxonomy, and absence of intervening state change.
- [x] Inventory corruption, unreadable-state, ambiguity, UUID, and stale-index manifest-fallback coverage.

## Implementation

- [x] Add direct characterization for not-found fallback and corruption/unreadable propagation where coverage is weak.
- [x] Delete only the duplicate unscoped `get_session_entry` retry and its stale corruption explanation.
- [x] Preserve scoped-then-unscoped name resolution, ambiguity handling, and UUID/manifest fallback order.

## Verification and closeout

- [x] Run focused session-context and named regression tests (185 passed).
- [x] Run `make test-unit` (9,205 passed, one skip, 122 deselected), `make test-regression` (913 passed), and targeted
  Docker session-lifecycle integration coverage (23 passed).
- [x] Run full pre-commit, diff, design-size, and board-integrity checks: both living design documents remain below 30k
  tokens, all 893 local links across 351 board documents resolve, and Wave 7 is 16 `done` / 1 `doing` / 18 `todo`.
- [x] Open draft PR #196 for order 17.
- [x] Close the member after PR #196 merged as `bc4f3a0c` with all five GitHub checks passing.
- [x] Complete the post-merge audit: all 887 local links across 351 board documents resolve, the Wave 7 graph is 17
  `done` / 0 `doing` / 18 `todo`, and order 18 remains parked.
