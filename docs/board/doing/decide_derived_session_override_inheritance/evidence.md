# Inheritance decision evidence

Rechecked on `32df0219`, 2026-10-27. No production code or real session state was changed.

## Current ownership

- [`manager.py`](../../../../src/forge/session/manager.py): `_inherit_intent_fields` copies selected raw intent; fork
  and `_create_resume_child` then apply memory inheritance. `relaunch_session` copies raw overrides instead.
- [`memory_inheritance.py`](../../../../src/forge/session/memory_inheritance.py): only effective `auto_update` becomes
  fork/fresh memory intent, with explicit on/off handling.
- [`consumer_lanes.py`](../../../../src/forge/session/consumer_lanes.py): dispatch is confirmed-first, then intent;
  clearing requested intent preserves the parent's frozen binding. New children copy intent only.
- [`identity.py`](../../../../src/forge/policy/semantic/identity.py): `validate_inherited_claude_trigger` already
  distinguishes relaunch via `preserve_overrides=True` and checks the child lane separately from the parent's binding.
- [`session_lifecycle.py`](../../../../src/forge/cli/session_lifecycle.py): ordinary inactive resume reattaches;
  `_launch_as_child` handles active `--force` and the confirmed-but-not-resumable fallback.
- [`session.py`](../../../../src/forge/core/ops/session.py): reset deletes overrides without changing baseline.
  [`overrides.py`](../../../../src/forge/session/overrides.py) rejects new lifecycle-owned override writes;
  [`store.py`](../../../../src/forge/session/store.py) rejects unknown override paths on read but does not fully type
  every scalar in the sparse map.

At the inspected base, the fork section of the [session guide](../../../end-user/session.md) said the session's intent,
overrides and confirmed sections were copied wholesale. That conflicted with the manager and existing lane/authority
tests. This decision package corrects the guide; runtime validation remains in the separate implementation proposal.

## Isolated characterization

Ran 21 local cases: seven fixture variants through same-directory fork, minimal fresh resume and relaunch. Each used a
new canonical temporary Git project, isolated `FORGE_HOME`, and a coherent `publish_session` fixture. Malformed cases
changed only the fixture's persisted override map after publication. The probe inspected the created manifest and ran
the real `reset_session_overrides` command-core operation. No runtime, provider or reviewer was invoked.

The baseline had policy enabled, verification bypass disabled, memory enabled with `min_turns=7` and tag `baseline`,
plus both an intended and frozen supervisor lane `(codex, chatgpt, gpt-6.1-sol)`. The live-toggle variant disabled
policy and memory, set memory `min_turns=11` and tag `override`, and enabled verification bypass.

| Observation                       | Fork / fresh        | Relaunch                              |
| --------------------------------- | ------------------- | ------------------------------------- |
| Policy / verification bypass      | Enabled / false     | Disabled / true                       |
| Memory activation / minimum turns | Disabled / 11       | Disabled / 11                         |
| Memory tags                       | Empty               | `override`                            |
| Generic overrides                 | Empty               | Parent map copied                     |
| Intended / frozen lane            | Copied / absent     | Copied / absent                       |
| Reset policy / bypass             | Unchanged           | Restores enabled / false              |
| Reset memory                      | Still disabled / 11 | Restores enabled / 7 and baseline tag |

All 21 cases preserved parent manifest bytes. Additional variants showed:

- `memory: null`: fork/fresh keep memory absent after reset; relaunch restores baseline memory on reset.
- `policy: null`: fork/fresh inherit enabled baseline policy; relaunch keeps policy absent until reset.
- Unknown override key: all three refuse before publishing a child.
- `verification.bypass: "bad"`: fork/fresh refuse during effective-memory evaluation. Relaunch publishes a child;
  evaluating that child's effective configuration then fails. This is missing pre-publication validation, not a new
  requirement to inherit effective policy.
- Legacy `launch.runtime: codex` over a Claude baseline: fork/fresh omit it. Relaunch copies it, producing effective
  runtime `codex` while `session_runtime(child)` remains `claude_code`; reset removes the mismatch.
- Legacy `consumer_lanes: null`: fork/fresh omit it; relaunch copies an override that the lane reader ignores. All
  retain intended lanes and omit frozen bindings.

These results characterize stored state and reset behavior. They do not assert real runtime dispatch or cover every
malformed value. The separate acceptance matrix must add protected route/authority/source keys and all consumer slots.

## Existing tests

`make deps` completed; the following command passed **157 tests in 1.82 seconds**:

```bash
PYTHON_DOTENV_DISABLED=1 uv run --locked pytest \
  tests/src/session/test_memory_inheritance.py \
  tests/src/session/test_subprocess_proxy_inheritance.py \
  tests/src/session/test_authority_inheritance.py \
  tests/src/session/test_overrides.py \
  tests/src/session/test_effective.py \
  tests/regression/test_bug_consumer_lane_fork_resume_inherit.py \
  tests/regression/test_bug_disabled_inherited_supervisor.py \
  tests/regression/test_bug_disabled_native_policy_relaunch.py \
  tests/regression/test_bug_d008_launch_runtime_parent_override.py -q
```

The disabled-native-policy relaunch regression explicitly requires a disabled child without reviewer preflight. The
consumer-lane regression requires inherited intent and fresh confirmed bindings across all three paths. These tests
support preserving the distinction, while the malformed fixtures identify bounded follow-up work.

## Documentation verification

`make pre-commit-md` and `git diff --cached --check` passed after formatting and the maintainer-approved token-cache
refresh. The session guide counts 26,814 Opus tokens: above the existing 25,000-token target, below the 30,000-token
ceiling. The tracked cache matches the final document hash. No production code changed, so this package adds no claim of
new runtime or Docker coverage.
