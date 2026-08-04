# Preserve policy intent on enable checklist

Current focus: complete; D001 is implemented and verified without starting either remaining Wave 1 member.

## Evidence and Regression

- [x] Confirm `forge policy enable` replaces `PolicyIntent` while `disable` mutates it in place.
- [x] Reproduce loss of both `supervisor` and `team_supervisor` after a successful enable.
- [x] Add a dedicated D001 file under `tests/regression/` with the required marker and root-cause docstring.
- [x] Add a regression with non-default nested values in both supervisor configurations.
- [x] Assert requested bundle, fail-mode, and permissive values still replace their prior values.
- [x] Add coverage for enabling when the stored policy intent is absent.

## Implementation

- [x] Update only the terminal enable mutation to preserve unrelated policy-intent fields.
- [x] Keep bundle validation, compatibility guards, output, and hook-install diagnostics unchanged.
- [x] Keep `%policy enable|disable` override ownership and implementation unchanged.
- [x] Confirm no manifest migration or user-facing documentation change is required.

## Acceptance Tests

| Test                             | Fixture                                                    | Assertion                                                              | Test file                                                         |
| -------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Re-enable preserves supervision  | Disabled policy with non-default semantic and team configs | Both nested configs are structurally unchanged after successful enable | `tests/regression/test_bug_d001_policy_enable_supervisor_loss.py` |
| Bundle fields still update       | Existing different bundles, fail mode, and TDD config      | Requested terminal options replace only bundle-owned fields            | `tests/src/cli/test_policy_enable.py`                             |
| Missing policy intent is created | Session manifest with `intent.policy = null`               | Enable succeeds and creates the requested policy configuration         | `tests/src/cli/test_policy_enable.py`                             |
| Hook enforcement remains healthy | Docker policy-hook fixture                                 | Configured deterministic policy still evaluates through installed hook | `tests/integration/docker/test_policy_hooks.py`                   |

## Verification and Closeout

- [x] Run focused policy CLI/session tests (252 passed).
- [x] Run `make test-regression` (595 passed).
- [x] Run `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py` (21 passed).
- [x] Run `make pre-commit`.
- [x] Record the completed fix in `docs/board/change_log.md` and update finding disposition links.
- [x] Move the card to `done/`, repoint inbound links, and record final verification.
