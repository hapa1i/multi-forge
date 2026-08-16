# Remove verified dead session helpers checklist

Current focus: PR #197 open. Orders 19--35 remain parked.

## Activation and evidence

- [x] Close order 17 on pushed `main` at `f2fcc688` after PR #196 merged as `bc4f3a0c` with all five checks passing.
- [x] Branch from that exact closeout and move only order 18 to `doing/`.
- [x] Recheck every source, test, resource, extension, documentation, export, and string patch-target reference to the
  three admitted symbols.
- [x] Prove every production shadow collector call supplies no effective session filter and identify the direct-only
  filtered behavior test.
- [x] Prove `_print_session_tip` has no caller and `_generate_relaunch_name.parent_name` does not affect name generation
  or project-scoped collision handling.
- [x] Record the related, unreachable curation session-name merge as excluded O092-tail evidence without changing it.

## Implementation

- [x] Remove the shadow collector's dead filter parameter and private CLI pass-through while retaining live discovery,
  scope, deduplication, and passport scanning.
- [x] Delete the uncalled session-tip no-op and any import made unused by its removal.
- [x] Remove `_generate_relaunch_name.parent_name` and update its sole caller without changing relaunch lineage or
  project-scoped uniqueness.
- [x] Remove only tests for unreachable behavior; retain or strengthen live shadow collection and relaunch collision
  coverage.

## Acceptance controls

| Surface                 | Fixture                                      | Assertion                                                                             |
| ----------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------- |
| Shadow discovery        | project and workspace shadow passports       | Live callers still collect and deduplicate the same entries and roots                 |
| Session-end hook helper | repository-wide symbol and patch-target scan | No executable caller, export, resource, or compatibility consumer remains             |
| Relaunch naming         | sessions in separate Forge roots             | Generated names receive only target-root collisions; parent lineage remains unchanged |

## Verification and closeout

- [x] Run focused shadow-curation, memory CLI, session manager/relaunch, hooks, and resume tests (552 passed).
- [x] Run `make test-unit` (9,205 passed, one skip, 122 deselected), `make test-regression` (913 passed), and targeted
  Docker session-lifecycle integration coverage (23 passed).
- [x] Run full pre-commit, diff, design-size, and board-integrity checks: both living design documents remain below 30k
  tokens, all 893 local links across 352 board documents resolve, and Wave 7 is 17 `done` / 1 `doing` / 17 `todo`. No
  Forge workflow command was used.
- [x] Open PR #197 for order 18.
- [ ] After merge, close order 18 before selecting order 19.
