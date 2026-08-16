# Replace unsafe index test fixtures checklist

Current focus: Wave 7 order 14 is active from `74b364d2`; keep orders 15--35 parked.

## Activation and evidence

- [x] Close order 13 on pushed `main` at `74b364d2` and branch from that exact commit.
- [x] Reverify 180 executable `add_session`, `add_from_state`, and `remove_session` test calls across 48 files (179
  Python AST calls plus one embedded integration script; three additional textual matches are docstrings).
- [x] Move only this member to `doing/`, repair inbound links, and keep order 15 parked.
- [x] Classify each caller as ordinary coherent setup, direct mutator-contract coverage, or an intentional
  corrupt/orphan/race fixture.

## Implementation

- [x] Add shared builders that publish and delete coherent row-plus-manifest state through the production transaction
  contracts without exposing raw callbacks at call sites.
- [x] Migrate ordinary fixture setup to the shared builders.
- [x] Replace intentional invalid-state setup with narrowly named raw builders and comments that state the violated
  invariant.
- [x] Preserve direct-only mutator contract tests for order 15, without deleting the public methods in this member.
- [x] Recheck the residue: 18 executable calls remain in one file, all inside direct mutator contract tests owned by
  order 15; ordinary fixture callers are zero.

## Verification and closeout

- [x] Run the shared-helper contract tests and the full session/index unit slice: 7 helper contracts passed; the broad
  session/core-ops slice passed 1,775 tests with 87 integration tests deselected; all 69 direct index contracts passed.
- [x] Run the full unit and regression suites: 9,211 unit tests passed with one skip and 122 integration tests
  deselected; all 913 regression tests passed.
- [x] Run targeted Docker session lifecycle coverage: 69 lifecycle and CLI integration tests passed.
- [x] Run full pre-commit, diff, design-size, and board-integrity checks: all hooks passed; `git diff --check` was
  clean; the combined design corpus remained under budget at 59,973 tokens; 347 board files contained 885 valid local
  links with none missing; the Wave 7 lane remained 13 done, one doing, and 21 parked.
- [x] Open draft PR #193 for order 14.
- [ ] After merge, close this member before selecting order 15.
