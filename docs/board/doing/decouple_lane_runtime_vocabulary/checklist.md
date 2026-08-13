# Decouple lane runtime vocabulary checklist

Current focus: the import-boundary implementation and branch gates are complete. Keep the card in `doing/` until the
branch is reviewed and merged.

## Phase 1 -- Characterize and activate

- [x] Recheck O043 on preparation commit `095d8eeb`: `runtime_execution` uses `RUNTIMES` only as an agent-ID set.
- [x] Confirm `AGENT_RUNTIME_IDS` is already parity-guarded against `RUNTIMES` in `tests/src/core/test_lanes.py`.
- [x] Measure the current fresh-process edge: importing `forge.core.lanes` initializes `forge.core.runtime` and takes
  approximately 317 ms cumulatively versus approximately 20 ms for `forge.core.runtime_vocab`.
- [x] Activate only this member on `refactor/decouple-lane-runtime-vocabulary` and leave the other 33 Wave 7 members
  parked.

## Phase 2 -- Implement

- [x] Make `runtime_execution` test membership in `AGENT_RUNTIME_IDS`; update its docstring without changing accepted
  runtime IDs or execution kinds.
- [x] Add a fresh-process regression proving `import forge.core.lanes` does not initialize `forge.core.runtime` or its
  registry.
- [x] Preserve the existing exact registry/vocabulary parity test as the drift guard for deliberate ID duplication.

## Phase 3 -- Verify and close

| Test                   | Fixture                               | Assertion                                                | Test file / command                        |
| ---------------------- | ------------------------------------- | -------------------------------------------------------- | ------------------------------------------ |
| Runtime classification | core LLM, Claude, Codex, unknown IDs  | existing execution kinds/errors are unchanged            | `tests/src/core/test_lanes.py`             |
| Registry parity        | neutral vocabulary plus live registry | agent IDs remain exactly equal                           | `tests/src/core/test_lanes.py`             |
| Import boundary        | fresh Python process imports lanes    | runtime, LLM, and auth modules absent from `sys.modules` | `tests/src/core/test_lanes.py`             |
| Lane consumers         | configured consumer lanes             | defaults, overrides, and reachability remain unchanged   | `tests/src/session/test_consumer_lanes.py` |

- [x] Run the focused lane and consumer-lane files: 49 focused assertions and 568 broader lane-consumer assertions
  passed.
- [x] Recheck the fresh-process boundary: no `forge.core.runtime`, `forge.core.llm`, or `forge.core.auth` modules
  initialized; the measured cumulative lanes import fell from approximately 317 ms at activation to approximately 55 ms
  on this branch.
- [x] Run `make test-unit` (9,005 passed, 1 skipped, 122 deselected) and `make test-regression` (898 passed).
- [x] Run `make pre-commit` after the final branch edits.
- [x] Resolve branch-local board links/fragments and run `git diff --check`: 852 local targets and all 55 fragments in
  44 changed board documents resolve; the 34-member lane/backlink graph is exact.
- [ ] After review and merge, update the epic, parent, review ledger, and change log with the shipped outcome; move this
  member to `done/` and repoint inbound links without activating order 2.
