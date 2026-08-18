# Extract session-fork execution checklist

Current focus: closed -- order 32 shipped in PR #211; orders 33--35 remain parked.

- [x] Close order 31 on pushed `main` at `1897b547`, create `refactor/extract-session-fork-execution`, and activate only
  order 32.
- [x] Reverify O068/O096 against the merged typed preflight, manager mutation, artifact, rollback, routing, and launch
  seams.
- [x] Add characterization for every pre-launch mutation failure and its durable/Git compensation.
- [x] Move child creation, native relocation, transfer/rewind artifacts, extension preparation, and launch-plan assembly
  behind one command-core execution op.
- [x] Remove the unreachable routing re-resolution and consolidate duplicated replacement/supervisor decisions.
- [x] Replace mock-manager planner fallbacks with concrete state/store coverage.
- [x] Keep Click responsible for input, prompts, rendering, and process handoff without output, task, or argv drift.
- [x] Update command-core ownership documentation without changing fork strategy, identity, extension, or post-launch
  semantics.
- [x] Run focused fork/resume/session units and regressions.
- [x] Run targeted Docker worktree, native-relocate, rewind, and Codex fork coverage.
- [x] Run `make test-unit`, `make test-regression`, `make pre-commit`, design token checks, and board integrity.
- [x] Record verification without activating order 33.
- [x] Close review findings: compensate ready rewind fallbacks and partial factory writes, delete the dead model-pin
  module, preserve warning styling without a production assert, and share pure launch-preference/prompt resolution.
- [x] Record the remaining start/fork extension-preparation duplication without expanding order 32 into installer
  ownership.
- [x] Re-run 206 focused, 9,299 unit, 925 regression, and seven targeted Docker fork/rewind checks after review fixes.
- [x] Merge PR #211 as `e4a62d1b` and close this member without activating order 33.

## Acceptance coverage

| Boundary                | Proof                                                                                                                                         |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Mutation transaction    | Tests pin manifest/index/worktree/branch cleanup, ready-fallback and partial-factory transcript ownership, and failed-rollback recovery.      |
| Routing and launch plan | Direct, inherited, explicit proxy, supervisor, native, transfer, rewind, sidecar, and Codex-refusal paths retain their characterized results. |
| Adapter boundary        | Existing CLI output, confirmation, task-delivery, and runtime-argv tests pass with Click limited to realization, rendering, and handoff.      |
| Temporary seams         | Planner tests use concrete stores; replacement identity and supervisor proxy planning share production decisions.                             |

## Verification record

- Baseline: 207 focused fork/resume/session tests passed on `1897b547`.
- Final: 236 expanded fork tests plus three strict-planner migration cases passed; review hardening reran 206 focused
  tests; `make test-unit` passed 9,299 with one skip and 122 deselected; `make test-regression` passed 925.
- Docker: five worktree/same-directory/branch/`--into` cases, one Codex-parent refusal, one real native-relocate
  contract, and one real rewind contract passed. The first lifecycle invocation used two stale class selectors and
  collected no tests; the corrected selectors passed.
- Quality: the first `make pre-commit` applied formatters and exposed two read-only protocol annotations; the clean
  rerun passed. CI's Python 3.11 isort then expanded two import groups that the local Python 3.13 hook left compact; the
  portable form and all replacement checks passed. Final Opus 5 counts are 29,993 for `design.md` and 29,966 for
  `design_appendix.md`; the board audit found 368 documents, 894 local links, and no missing target. Wave 7 is 32 done
  and three todo.
- No Forge workflow command was used.
