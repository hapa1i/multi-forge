# Remove the experimental manifest WorkflowPolicy

**Lane**: `done/` -- shipped in PR #233 (`4f95d88d`) on 2026-08-21.

**Execution**: `refactor/remove-workflow-policy` from `main` at `edb5ada6` on 2026-08-21.

**Replaces**: retired [`graduate_workflow_policy_cli`](../../retired/graduate_workflow_policy_cli/card.md).
Reconsideration of an automatic semantic architecture guard requires a new proposal with an explicit authority corpus;
it must not reactivate the retired CLI-wiring card.

## Goal

Remove the experimental, manifest-only WorkflowPolicy pipeline and its declarative configuration path while preserving
the shared reactive library. Existing manifests that still name the removed bundle or retain its bundle configuration
must receive an actionable engine-construction diagnostic instead of silently evaluating no policies.

## Evidence and authority

Repository-wide source, test, resource, documentation, package, and string-target searches found one production entry
into `forge.policy.workflow`: the deterministic registry's lazy `_build_workflow_policies` path. The only caller of
`build_divergence_config` is test code. The implementation remains documented as experimental and manifest-only, but
that documentation makes `policy.bundles: ["workflow"]` and `policy.bundle_config.workflow` user-authored compatibility
surfaces rather than internal-only code.

The concrete divergence preset asks stateless checker/reviewer calls to judge established project patterns from a
truncated action alone. It supplies no repository, approved plan, design document, or other normative authority, yet a
high-confidence response with any non-empty citation can deny. Graduation would therefore expose a checker that cannot
substantiate its own blocking contract. The current workflow design instead specifies shared Python primitives, explicit
policy classes, and deliberate `forge workflow ... --check` gates -- library, not a declarative workflow framework.

## Scope

- Remove `src/forge/policy/workflow/`, its registry special case, dynamic policy lookup, and tests that characterize
  only the removed behavior.
- Reject unknown bundle names before policy registration. Preserve a specific recovery diagnostic for the removed
  `workflow` bundle, including when only `bundle_config.workflow` remains beside another active bundle.
- Keep `core/reactive` utilities and their tests. Update only stale comments that present WorkflowPolicy as a live
  consumer.
- Remove the experimental end-user activation instructions and obsolete cost/telemetry design claims. Retain a compact
  compatibility note naming the stale fields and recovery path.

## Compatibility decision

This is a research-preview clean break, not a deprecation shim. Importability below `forge.policy.workflow` was not a
declared stable Python API, but the documented manifest shape is user-authored state. The package and behavior tests are
deleted; the registry continues to recognize the removed bundle name only to reject it with reset guidance. Arbitrary
unknown bundle names also fail engine construction rather than disappearing into an empty policy set.

## Deliberate keeps and follow-up boundary

`tag_action` remains an intentional shared-library primitive: `design_workflows.md` presents the tagger protocol and
helper as the supported Python composition seam even though no production policy currently calls it. `compute_cache_key`
also has no production caller after this removal, but this card retains it under the explicit shared-reactive exclusion;
a future reactive-library audit should decide whether that API has earned its keep. The caller-less `POLICY_TO_BUNDLE`
map and `get_bundle_for_policy()` helper are not reactive primitives and are removed here.

## Acceptance criteria

- No production, test, package, or normative-document reference treats WorkflowPolicy as available behavior.
- `get_bundle_policies()` and `build_engine()` reject unknown bundles; the removed `workflow` name identifies both stale
  manifest fields in its recovery message.
- A stale `bundle_config.workflow` key fails before any otherwise valid policy is registered.
- The real Claude policy-hook boundary remains atomic and fail-open: it reports the removal without a traceback and does
  not evaluate a partial bundle set.
- Shared tagger, throttle, structured-output, supervisor, team-policy, and workflow-CLI behavior remain in place.

## Exclusions

- Do not design or ship a replacement semantic architecture guard in this card.
- Do not generalize `policy.guards` into user-defined policies-as-data.
- Do not remove shared reactive helpers merely because WorkflowPolicy was one historical consumer.
