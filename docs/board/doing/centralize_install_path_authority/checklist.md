# Centralize installer path and ownership authority checklist

Current focus: move pure path/ownership policy below installer and runtime removal on
`refactor/centralize-install-path-authority` from order-4 closeout commit `56d32945`; keep orders 6--34 parked.

## Phase 1 -- Characterize and activate

- [x] Close order 4 on `main` at `56d32945`, branch from that exact commit, and activate only order-5 O065/O069.
- [x] Recheck the preserve-leaf canonicalizers: `skill_planning._absolute_path` and
  `unmanaged.canonical_package_path` remain byte-equivalent.
- [x] Recheck the inversion: `RuntimeRemovalExecutor` still receives target-root, generic boundary, tracked-file
  boundary, and Codex config-scope policy from `Installer` through four callables.
- [x] Retain whole-path project/dispatcher canonicalizers, the standalone bundled hook copy, fail-closed cleanup,
  schema-v3 unmanaged-package reporting, and `_detect_git_project_root` behavior coverage outside this member.
- [x] Run the unchanged installer, runtime-removal, unmanaged-package, skill-planning, and extension characterization:
  348 passed.

## Phase 2 -- Move path policy below both consumers

- [x] Give a lower install module the preserve-leaf canonicalizer, target-root mapping, generic boundary validation,
  tracked skill-package boundary validation, and Codex config-scope validation.
- [x] Route installer, skill planning, unmanaged-package discovery, and runtime removal through that authority while
  retaining current public imports where compatibility requires them.
- [x] Remove all four policy callbacks from `RuntimeRemovalExecutor` without changing planning, preflight, mutation,
  rollback, or tracking-reconciliation order.
- [x] Remove the duplicate CLI `TestFindGitRoot` block while retaining canonical core cases and extension detector/CLI
  coverage.
- [x] Update normative design ownership and verify no end-user command, error, configuration, or durable-state contract
  changes.

## Phase 3 -- Verify and close

- [x] Run focused installer/path/runtime-removal tests (347 passed) and the targeted Docker installer file (23 passed).
- [x] Build the wheel and verify project enable/status/sync plus Codex runtime-disable from an isolated wheel install;
  post-disable status retained only `claude_code` packages and reported no unmanaged packages.
- [x] Run `make test-unit` (9,064 passed, one skipped), `make test-regression` (898 passed), and `make pre-commit`.
- [x] Resolve board links/fragments, verify the 4-done/1-doing/29-parked Wave 7 graph, and run `git diff --check`.
- [ ] After review and merge, record the shipped outcome, move this member to `done/`, and leave order 6 parked until
  the closeout lands.
