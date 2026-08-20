# Eliminate runtime test skips checklist

Current focus: implementation and branch quality gates are complete; retain the member in `doing/` until its independent
ship/merge boundary.

## Phase 1 -- Characterize and activate

- [x] Activate only Wave 8 order 6 from pushed `main` at `3c0a3002` on `agent/eliminate-runtime-test-skips`; keep orders
  7--19 parked.
- [x] Recheck the credential-template loop, both symlink guards, and all three host-filesystem case guards against the
  testing policy and current implementation.
- [x] Capture fail-first evidence: the three-file baseline reported 114 passed and one skip, and the structural
  regression identified exactly the six admitted runtime skip locations before implementation.

## Phase 2 -- Implement

- [x] Parameterize credential-template expectations so a missing template fails its own case without aborting later
  mappings.
- [x] Replace symlink availability skips with one shared fixture whose inability to create a directory symlink is an
  actionable test failure.
- [x] Exercise same-file aliases and distinct roots deterministically, independent of host filesystem case behavior, for
  both the project registry and generated hook dispatcher.
- [x] Remove all six admitted `pytest.skip()` calls without changing production behavior; retain an AST regression guard
  against runtime skip calls and decorators anywhere under `tests/`.

## Phase 3 -- Verify and close

| Boundary                 | Fixture                                                 | Assertion                                                             | Tier |
| ------------------------ | ------------------------------------------------------- | --------------------------------------------------------------------- | ---- |
| Credential templates     | each expected local template as its own parameter       | every mapping runs and names its expected credential                  | unit |
| Project symlink identity | real directory plus shared symlink fixture              | enrollment stores the canonical target and descendant lookup succeeds | unit |
| Registry case identity   | injected same-file and distinct-file outcomes           | aliases unify; distinct roots remain isolated                         | unit |
| Dispatcher parity        | rendered dispatcher helper under both identity outcomes | embedded gate matches registry semantics                              | unit |
| Repository skip policy   | source scan plus full unit run                          | no runtime skips remain; unit summary reports zero skips              | unit |

- [x] Run the three focused files plus the O072 regression: 119 passed with zero skips; run `make test-regression`: 961
  passed.
- [x] Run `make test-unit`: 9,326 passed, 124 deselected, and zero skipped in 153.68 seconds.
- [x] Run `make pre-commit` after Markdown normalization plus an explicit new-file pass; verify all 972 local links
  across 400 board documents, the 5-done/1-doing/13-todo Wave 8 graph, the 59,979-token living design-doc size, and diff
  hygiene.
- [ ] Add the completed-work change-log entry, synchronize final board evidence, and move the member to `done/` after
  its independent ship/merge boundary.
