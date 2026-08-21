# Remove the experimental manifest WorkflowPolicy checklist

Current focus: remove the implementation and pin the stale-manifest compatibility boundary on
`refactor/remove-workflow-policy`.

## Activation and evidence

- [x] Branch from current `main`/`origin/main` at `edb5ada6` and activate this replacement card.
- [x] Retire `graduate_workflow_policy_cli` as invalidated, link both cards, and repoint its historical inbound board
  references.
- [x] Recheck production imports, dynamic/string references, package resources, tests, and normative documentation for
  `forge.policy.workflow`, `WorkflowPolicy`, `build_divergence_config`, `policy-checker`, and `policy-reviewer`.
- [x] Record the compatibility classification: package internals are removable, while the documented manifest fields
  require an actionable stale-state failure.

## Implementation

- [x] Remove the WorkflowPolicy package, registry construction/lookup paths, and behavior-only unit/regression tests.
- [x] Validate unknown bundle names and unknown `bundle_config` owners before registering any policy; give `workflow` a
  field-specific removal diagnostic.
- [x] Replace the two obsolete workflow-config Docker checks with one real stale-bundle hook check that proves atomic
  fail-open behavior and traceback-free recovery output.
- [x] Remove live WorkflowPolicy activation, cost, telemetry, and runner claims from design/end-user docs; update shared
  reactive comments without deleting those primitives.

## Acceptance controls

| Surface                 | Fixture                                              | Assertion                                                        | Test file                                         |
| ----------------------- | ---------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------- |
| Registry lookup         | unknown and removed bundle names                     | construction raises; `workflow` names both stale manifest fields | `tests/src/policy/deterministic/test_registry.py` |
| Atomic engine build     | valid TDD plus stale workflow config                 | build fails before returning a partially registered engine       | `tests/src/policy/test_engine.py`                 |
| Claude hook boundary    | session manifest with removed workflow bundle/config | exit 0, empty stdout, actionable stderr, no traceback            | `tests/integration/docker/test_policy_hooks.py`   |
| Compatibility inventory | repository-wide exact-term scan                      | no live implementation or normative availability claim remains   | command evidence in closeout                      |

## Verification and closeout

- [x] Run the focused policy/reactive/CLI slice (573 passed) and exact-term documentation/source inventory.
- [x] Run `make test-unit` (9,301 passed, 117 deselected) and `make test-regression` (1,053 passed).
- [x] Run the targeted Docker policy-hook integration test through `./scripts/test-integration.sh` (1 passed).
- [x] Run `make pre-commit`, `git diff --check`, board-link validation (424 documents, 1,028 local links, none broken),
  and design-document size checks (`design.md` 29,928; appendix 29,903; workflows 17,929 tokens).
- [ ] Commit and push the reviewable changes, then open a draft PR against `main` with exact verification evidence.
- [ ] After merge, add the completed-work change-log entry and move this card to `done/` with final PR/check evidence.
