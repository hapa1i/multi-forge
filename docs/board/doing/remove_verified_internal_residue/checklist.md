# Remove verified internal residue checklist

Current focus: remove only the O098/session-summary/cap-guard residue on
`refactor/remove-verified-internal-residue` from order-6 closeout commit `4f167379`; keep orders 8--35 parked.

## Phase 1 -- Recheck compatibility and activate

- [x] Close order 6 on `main` at `4f167379`, branch from that exact commit, and activate only order 7.
- [x] Recheck repository imports, patch targets, CLI entry points, bundled resources, docs, and history: no consumer
  reads the lifecycle/management `__all__` lists or calls `_print_session_summary`; PR #69 removed the parent wildcard
  re-exports but left this metadata behind.
- [x] Recheck rewind-helper ownership: `session_rewind` defines both helpers, direct tests already import from it, and
  only `session_fork` reaches `_prepare_rewind_launch_artifacts` indirectly through `session_lifecycle`.
- [x] Recheck the cap-state contract: `core.state.read_json` rejects every non-object value with
  `StateCorruptedError`, before `load_cap_state` can reach its repeated non-dict branch.
- [x] Retain O084, converter/Gemini candidates, release-gated deletions, O092's unnamed tail, command registration,
  session output, cap schema checks, and tolerant-reader policy outside this member.

## Phase 2 -- Remove the verified residue

- [x] Replace the three stale session docstring claims with accurate registration/ownership language.
- [x] Delete both obsolete `__all__` lists and `_print_session_summary`; make `session_fork` import its rewind helper
  directly from `session_rewind`.
- [x] Delete only the repeated cap-state non-dict guard and add a regression that pins non-object rejection at the
  shared state-reader boundary.

## Phase 3 -- Verify and close

- [x] Run focused session and telemetry/cap tests (508 passed) plus CLI import/help smoke coverage.
- [x] Run the required targeted Docker session-lifecycle integration suite (23 passed).
- [x] Run `make test-unit` (9,113 passed, one skipped, 122 deselected), `make test-regression` (898 passed), and
  `make pre-commit`.
- [x] Resolve all 859 relative links across 336 board Markdown files and changed-file fragments; verify the
  6-done/1-doing/28-parked Wave 7 graph and run `git diff --check`.
- [ ] After review and merge, record the shipped outcome, move this member to `done/`, and leave order 8 parked until
  the closeout lands.
