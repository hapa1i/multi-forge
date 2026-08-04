# Preserve policy intent when enabling bundles

**Epic**: [`epic_policy_supervision_correctness`](../../doing/epic_policy_supervision_correctness/card.md).

**Finding**: D001 (CRITICAL) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `done/` -- implemented and verified on `fix/preserve-policy-intent-on-enable` as the first Wave 1 member.

## Goal

Make terminal `forge policy enable` update bundle enforcement without deleting the session-owned semantic or team
supervisor configuration.

## Evidence

- `src/forge/cli/policy.py:312-317` replaces the entire `PolicyIntent` from the four bundle-related fields.
- `src/forge/session/models.py:206-211` defaults `supervisor` and `team_supervisor` to `None`, so replacement silently
  clears both.
- `forge policy disable` mutates `enabled` in place at `src/forge/cli/policy.py:365-372` and preserves adjacent intent.
- Isolated reproduction: seed both supervisor configs, invoke `forge policy enable --bundle tdd`, and both read back as
  `None` despite exit 0.

## Expected Behavior

Per `docs/design_workflows.md` §1.6, terminal enable updates the existing policy intent's `enabled`, `fail_mode`,
`bundles`, and `bundle_config` fields while preserving `supervisor`, `team_supervisor`, and any future unrelated policy
fields. If no policy intent exists, the command may create one with normal defaults.

## Scope

- Correct the terminal CLI's durable-intent mutation.
- Add a marked `tests/regression/test_bug_d001_policy_enable_supervisor_loss.py` fixture containing non-default
  `SupervisorConfig` and `TeamSupervisorConfig` values.
- Preserve current bundle validation, target compatibility checks, hook-install warning, output, and disable behavior.

## Acceptance Criteria

- Re-enabling a disabled policy preserves both supervisor configurations structurally, including nested non-defaults.
- The requested bundles, fail mode, and TDD permissive config still replace their prior bundle values.
- Enabling a session with no prior policy intent still succeeds.
- A failed target compatibility check remains non-mutating.
- The implementation does not change `%policy enable|disable`, which intentionally targets overrides.

## Compatibility and Exclusions

No manifest migration or CLI surface change is allowed. This is an in-place preservation fix for already serialized
state. O044's command-core refactor is explicitly excluded; terminal intent and direct-command overrides remain distinct
ownership planes.

## Verification

- `uv run pytest -q tests/src/cli/test_policy_enable.py`: 6 passed.
- Focused policy and hook unit suite: 252 passed.
- `make test-regression`: 595 passed, including the dedicated D001 silent-loss reproduction.
- `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py`: 21 passed.
- `make pre-commit`: passed.

## Outcome

Terminal enable now creates a policy intent only when one is absent, then updates the four bundle-owned fields in place.
Existing semantic and team supervisor configuration therefore survives re-enablement. No manifest migration, CLI change,
or `%policy` override change was required.
