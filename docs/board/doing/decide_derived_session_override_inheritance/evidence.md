# Inheritance decision evidence

Initial characterization used `32df0219` on 2026-10-27. Pre-merge review on 2026-10-28 corrected the interpretations
below and added the bounded code fixes listed under [review corrections](#review-corrections). All probes use isolated
fixtures; no real session state was changed.

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
  `_launch_as_child` handles active `--force`. The apparent non-resumable fallback was unreachable and is removed.
- [`session.py`](../../../../src/forge/core/ops/session.py): reset deletes overrides without changing baseline, subject
  to native-source and frozen-supervisor identity checks. [`overrides.py`](../../../../src/forge/session/overrides.py)
  now validates wildcard paths as well as direct writes; [`store.py`](../../../../src/forge/session/store.py) rejects
  unknown override paths on read but does not fully type every scalar in the sparse map.

At the inspected base, the fork section of the [session guide](../../../end-user/session.md) said the session's intent,
overrides and confirmed sections were copied wholesale. That conflicted with the manager and existing lane/authority
tests. This decision package corrects the guide; runtime validation remains in the separate implementation proposal.

## Isolated characterization

Ran 21 local cases: seven fixture variants through same-directory fork, minimal fresh resume and relaunch. Each used a
new canonical temporary Git project, isolated `FORGE_HOME`, and a coherent `publish_session` fixture. Malformed cases
changed only the fixture's persisted override map after publication. The probe inspected the created manifest and ran
the real `reset_session_overrides` command-core operation. No runtime, provider or reviewer was invoked.

The hand-authored baseline had policy enabled, verification bypass disabled, memory enabled with `min_turns=7` and tag
`baseline`, plus both an intended and frozen supervisor lane `(codex, chatgpt, gpt-6.1-sol)`. The live-toggle variant
disabled policy and memory, set memory `min_turns=11` and tag `override`, and enabled verification bypass.

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

These results characterize stored state and reset behavior only. The verification baseline is not producible by shipped
setup commands: `session set verification.*` writes overrides, so actual fork/fresh children lose verification entirely.
The probe did not inspect transfer artifacts, inference or forced fork replacement; absence of a published child does
not establish absence of side effects. It also did not cover malformed supervisors or post-freeze reset refusal.

## Review corrections

- Both shipped supervisor `off` commands call `supervisor_off`, which removes a suspension override and writes baseline
  suspension. All child paths inherit it; reset leaves it suspended. The new public-command inheritance test covers this
  alongside override-only verification setup across fork, fresh and relaunch.
- Fresh transfer assembles and writes context before effective-memory decoding can reject a bad override.
  `fork --worktree --force` deletes the old owned fork before that decoding. Fork/resume CLI routing also precedes
  manager admission. The proposed guard now covers planning/preflight, proxy startup, replacement deletion and transfer
  inference, not just child publication.
- Fresh resume previously paired a historical confirmed proxy template with the current intent URL. The fix copies the
  intent pair together, so an earlier `resume --no-proxy` cannot cause a paired-proxy error. Historical confirmed proxy
  metadata remains intact. The legacy sandboxed-to-sidecar projection remains when launch intent is absent.
- Wildcard `consumer_lanes.*` bypassed protected-key validation. The setter now validates every expanded path before
  mutation. Direct and CLI regressions assert atomic refusal.
- A bad supervisor timeout raised an uncaught dacite error during reset. Reset now reports the invalid configuration and
  applicable recovery, preserving manifest bytes. Regression controls retain native-source and frozen-effort refusal;
  malformed configured supervisors can use the advertised remove command.
- The removed resume branch was private control flow, not a CLI or durable-state surface. Its precondition was
  impossible in a stable snapshot: passing `_has_confirmed_claude_session` implies `_is_resumable_session`. The extra
  transcript probe only allowed a deletion race to select a child. Repository callers, tests, docs and packaged assets
  expose no separate fallback contract; the helper remains for active `--force`. Existing launch-manifest and CLI tests
  retain active force, ordinary reconnect and never-launched behavior.
- Derivation readiness is limited to enabled, active native Codex sources. Sidecar and Claude reviewer admission remain
  at launch. Plan lookup reads the immediate parent live until the child owns a plan; configuration independence does
  not apply to that lookup. Advisory authority alone inherits on every child path, including relaunch.

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

## Initial documentation verification

`make pre-commit-md` and `git diff --cached --check` passed after formatting and the maintainer-approved token-cache
refresh. The session guide counts 26,814 Opus tokens: above the existing 25,000-token target, below the 30,000-token
ceiling. That was the initial documentation-only commit; the reviewed revision has separate code and Docker checks.

## Revision verification

- Focused resume, override, native-identity and new regression/characterization tests: **223 passed**.

- `PYTHON_DOTENV_DISABLED=1 make test-unit`: **11,226 passed**, 120 integration tests deselected.

- `PYTHON_DOTENV_DISABLED=1 make test-regression`: **2,212 passed**.

- Targeted Docker CLI resume, manager resume and lifecycle tests: **42 passed**, including repeated direct resume in
  native and transfer modes. The mock Claude CLI performs no inference:

  ```bash
  PYTHON_DOTENV_DISABLED=1 env -u GEMINI_API_KEY \
    CLAUDE_VERSION=2.1.245 CODEX_VERSION=0.149.1 ./scripts/test-integration.sh \
    tests/integration/cli/test_session_resume_proxy_integration.py \
    tests/src/session/test_resume_integration.py \
    tests/src/session/test_manager_integration.py
  ```

- `make pre-commit`: passed, including mypy, pyright, Markdown links and file-size checks. Final board evidence edits
  receive the Markdown hook subset and staged diff check.

- The approved refreshed session guide count is **27,053 Opus tokens**, above the existing 25,000 target and below the
  30,000 ceiling; the cached hash matches the guide. Repeated inheritance prose was replaced by pointers, while the
  missing suspension, verification, reset and live-plan qualifications are now explicit.
