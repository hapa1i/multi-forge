# Close CLI Enforcement and Recovery Gaps Checklist

Status: completed 2026-09-06. PR #251 merged as `6f7cb64e` with all five GitHub checks passing. See the
[epic closeout](../epic_1_0_release_hardening/checklist.md#release-disposition).

## Policy Diff Enforcement

- [x] Add quoted-path fixtures that place the quoted file first, last, and beside an unquoted file.
- [x] Decode Git C-quoted headers and preserve one chunk per file.
- [x] Prove non-ASCII Python violations cannot bypass terminal per-file policy evaluation.

## Targeted Recovery

- [x] Add an explicit-root local Codex recovery regression and bind the disable command to that root.
- [x] Add durable model-route replay health-failure coverage for restart and explicit reroute commands.
- [x] Reuse the persisted-proxy recovery renderer without changing route refusal semantics.

## Post-review Hardening

- [x] Preserve unquoted paths with spaces for pure rename, copy, mode-only, and binary diffs.
- [x] Prefer `+++`, `rename to`, and `copy to` destination metadata before deterministic header fallback.
- [x] Include the replay-equivalent `--model`, and `--model-tier` only when needed, in durable reroute commands.
- [x] Route planning-stage replay failures through the shared refusal renderer without mutation or launch.
- [x] Render recovery commands literally so Rich-like bracketed roots and `[1m]` model suffixes remain exact.
- [x] Recognize headerless file boundaries only outside counted hunks so header-shaped added content stays enforced.
- [x] Fail closed when any headered or headerless non-deletion chunk cannot be attributed without conflating deletions.
- [x] Preserve the resolved child name and every explicit fork option in inherited-route recovery commands.

## Verification

- [x] Run focused policy, extension CLI, model-route, resume, and regression tests.
- [x] Run required targeted session integration coverage.
- [x] Record commands, results, and the integrated SHA for batch closeout.

## Acceptance Tests

| Test                    | Fixture                               | Assertion                                | Test File                                                                  |
| ----------------------- | ------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------- |
| Quoted diff boundary    | adjacent C-quoted and ordinary paths  | each file is evaluated independently     | `tests/src/policy/test_diff.py`                                            |
| Root-bound recovery     | local Codex enable with explicit root | recovery targets the same project        | `tests/src/cli/test_extension_enable.py`                                   |
| Durable route recovery  | unavailable persisted proxy route     | restart and reroute commands are printed | `tests/src/cli/test_session_model_pins.py`                                 |
| Combined-diff boundary  | ordinary plus combined diff headers   | each patch remains a separate file       | `tests/src/policy/test_diff.py`                                            |
| Replay planning refusal | stored route fails during planning    | shared recovery; no mutation or launch   | `tests/src/cli/test_session_model_pins.py`                                 |
| Intent-based replay     | stale confirmation and valid intent   | recovery follows durable route intent    | `tests/src/cli/test_session_model_pins.py`                                 |
| Identity mismatch       | wrong process answers stored endpoint | restart is not offered as sufficient     | `tests/src/cli/test_session_model_pins.py`                                 |
| Invalid route request   | malformed stored model projection     | replacement guidance remains actionable  | `tests/src/cli/test_session_model_pins.py`                                 |
| Full route projection   | recorded `[1m]` model request         | model and tier survive command rendering | `tests/src/cli/test_session_model_pins.py`                                 |
| Literal recovery output | bracketed root and `[1m]` model       | copyable command text remains exact      | `tests/src/cli/test_output.py`                                             |
| Header-shaped content   | hunk adds `+++ /dev/null` and `+++ b` | later violations remain in the file      | `tests/src/policy/test_diff.py`                                            |
| Partial attribution     | no-prefix rename plus modified file   | both policy-check surfaces refuse        | `tests/regression/test_bug_20260831_policy_check_multifile_path_bypass.py` |
| Fork route recovery     | inherited route plus explicit options | exact intended fork remains copyable     | `tests/src/cli/test_session_model_pins.py`                                 |

## Evidence

Verified against integrated code SHA `817cb5ca`.

```bash
uv run pytest -q \
  tests/src/policy/test_diff.py \
  tests/src/cli/test_extension_enable.py \
  tests/src/cli/test_output.py \
  tests/src/cli/test_session_model_pins.py \
  tests/src/cli/test_session_fork.py \
  tests/regression/test_bug_20260831_policy_check_multifile_path_bypass.py \
  tests/regression/test_bug_resume_dead_persisted_proxy.py
```

Result: 246 passed in 32.22 seconds.

```bash
./scripts/test-integration.sh \
  tests/integration/cli/test_session_commands_integration.py::TestSessionDelete \
  tests/integration/cli/test_session_resume_proxy_integration.py \
  tests/integration/cli/test_policy_cli_contract_integration.py \
  tests/integration/docker/test_installer.py::TestForgeExtensionEnable::test_full_profile_memory_skill_contracts \
  tests/integration/docker/test_walkthrough_release_artifact.py
```

Result: 11 passed in 60.17 seconds.
