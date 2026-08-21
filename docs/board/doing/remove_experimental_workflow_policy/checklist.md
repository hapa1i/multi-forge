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

- [ ] Remove the WorkflowPolicy package, registry construction/lookup paths, and behavior-only unit/regression tests.
- [ ] Validate unknown bundle names and unknown `bundle_config` owners before registering any policy; give `workflow` a
  field-specific removal diagnostic.
- [ ] Replace the two obsolete workflow-config Docker checks with one real stale-bundle hook check that proves atomic
  fail-open behavior and traceback-free recovery output.
- [ ] Remove live WorkflowPolicy activation, cost, telemetry, and runner claims from design/end-user docs; update shared
  reactive comments without deleting those primitives.

## Acceptance controls

| Surface | Fixture | Assertion | Test file |
| ------- | ------- | --------- | --------- |
| Registry lookup | unknown and removed bundle names | construction raises; `workflow` names both stale manifest fields | `tests/src/policy/deterministic/test_registry.py` |
| Atomic engine build | valid TDD plus stale workflow config | build fails before returning a partially registered engine | `tests/src/policy/test_engine.py` |
| Claude hook boundary | session manifest with removed workflow bundle/config | exit 0, empty stdout, actionable stderr, no traceback | `tests/integration/docker/test_policy_hooks.py` |
| Compatibility inventory | repository-wide exact-term scan | no live implementation or normative availability claim remains | command evidence in closeout |

## Verification and closeout

- [ ] Run the focused policy unit slice and the affected documentation checks.
- [ ] Run `make test-unit` and `make test-regression`.
- [ ] Run the targeted Docker policy-hook integration test through `./scripts/test-integration.sh`.
- [ ] Run `make pre-commit`, diff checks, board-link validation, and design-document size checks.
- [ ] Commit and push the reviewable changes, then open a draft PR against `main` with exact verification evidence.
- [ ] After merge, add the completed-work change-log entry and move this card to `done/` with final PR/check evidence.
