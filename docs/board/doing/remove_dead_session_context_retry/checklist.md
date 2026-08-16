# Remove the dead session-context retry checklist

Current focus: implementation and verification complete; draft PR pending. Orders 18--35 remain parked.

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
- [ ] Open a draft PR for order 17 and record its final proof before closeout.
