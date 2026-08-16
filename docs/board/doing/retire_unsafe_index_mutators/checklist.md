# Retire unsafe public index mutators checklist

Current focus: Wave 7 order 15 is active from `0e8e1cbb`; keep orders 16--35 parked.

## Activation and evidence

- [x] Close order 14 on pushed `main` at `0e8e1cbb` after PR #193 merged as `56dfc27b` with all five checks passing.
- [x] Branch from that exact closeout and move only order 15 to `doing/`.
- [x] Reverify the deletion set: three public definitions, one internal `add_from_state` to `add_session` call, 18
  direct-contract test calls in one file, one stale non-call test assignment, and no external production callers.
- [x] Inventory source comments/docstrings, live test prose, the testing guide, and the review ledger separately from
  immutable historical board records.

## Implementation

- [x] Delete `IndexStore.add_session`, `add_from_state`, and `remove_session`.
- [x] Delete only their direct API contracts; retain transaction, identity, collision, compensation, ownership, and race
  coverage.
- [x] Remove the stale `add_from_state` test assignment and retarget live comments/docstrings to the transaction seam.
- [x] Turn the fixture drift guard into a zero-attribute-reference invariant across `src/` and `tests/`.
- [x] Recheck that `create_session_txn` and `delete_session_txn` retain their private entry/binding and lock-local
  implementation seams with no retired-symbol residue.

## Verification and closeout

- [x] Run focused index, fixture-contract, session-operation, and named regression tests (217 passed, including the
  post-review scoped-delete transaction regression).
- [x] Run `make test-unit` (9,199 passed, 1 skipped, 122 deselected) and `make test-regression` (913 passed).
- [x] Run targeted Docker session lifecycle and CLI integration coverage (69 passed).
- [x] Run full pre-commit, diff, design-size, and board-integrity checks: both living design documents remain below 30k
  tokens, all 885 local links across 348 board documents resolve, and the Wave 7 graph is 14 `done` / 1 `doing` / 20
  `todo`.
- [x] Open draft PR #194 for order 15.
- [ ] After merge, close this member before selecting order 16.
