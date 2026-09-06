# worker_native_controls -- disable native delegation and memory in Forge-owned workers

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M0 -- independently shippable worker defaults).

**Lane**: `proposed/`. No dependencies. May join batch A with M1/M2 or ship on its own branch as soon as verified.
Managed-session delegation policy remains M7; session memory choices remain M8a.

## Problem (verified 2026-09-06)

- `src/forge/review/engine.py` builds Claude `-p` requests without an Agent restriction and Codex requests without
  `agents.enabled=false`. Read-only workers can still delegate.
- Other consumers converge on `src/forge/core/reactive/session_runner.py`: memory writer, shadow curation, semantic
  supervisor and team supervisor. Their callers already know they are workers; they need no child binding or hook
  receipt to set launch restrictions.
- `build_claude_env` and `prepare_codex_request` also serve managed root sessions. Unconditional restrictions in these
  helpers would disable the native multiagent behavior this epic intends to support in roots.
- Native memory settings are inherited today. Worker independence should not depend on whether a main session allows
  native memory.

The epic's [runtime evidence appendix](../epic_native_multiagent/card.md#appendix-runtime-evidence) records the
version-sensitive control baseline. Environment switches alone do not remove ordinary Agent admission.

## Design

- Apply an explicit worker profile at known worker call sites, covering review panels and every consumer lane. Shared
  helpers must distinguish workers from managed roots; no blanket root restriction and no child-identity lookup.
- Claude worker requests include `--disallowedTools Agent Workflow SendMessage`,
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0`, `CLAUDE_CODE_FORK_SUBAGENT=0`, `CLAUDE_CODE_DISABLE_WORKFLOWS=1`, and
  `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.
- Codex worker requests include `-c agents.enabled=false`, `-c memories.use_memories=false`, and
  `-c memories.generate_memories=false`.
- Put restrictions in the durable base request used by retries/resumes, after caller environment removal/overrides.
  Cover Claude API-key `--bare`, subscription and proxy paths. A main session's memory allowance cannot relax a worker's
  profile.
- Record emitted controls and runtime-version verification in worker evidence. Do not infer historical absence of
  delegation or memory use from arguments alone. No new session manifest schema is required for this card.
- The pinned-runtime probe must verify native admission paths, including fork-context skills. If the listed switches
  leave a native path available, identify and apply the supported restriction before claiming the worker profile
  verified. This is a worker capability probe, independent of M7's policy-hook enrollment framework.

## Non-goals

No managed-root envelope, policy CLI changes, child capture, session memory inheritance/import, or continuous runtime
monitoring. Native tool controls do not govern arbitrary external processes launched through Bash or MCP.

## Acceptance

| Test                        | Fixture and assertion                                                                                                       | Test file                                                                                                    |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Worker selection            | Review and all consumer-lane callers opt into the profile; ordinary managed roots do not                                    | `tests/src/review/test_engine.py`, `tests/src/core/reactive/test_session_runner.py`                          |
| Claude controls             | Hostile inherited settings cannot erase tool, team, fork, workflow or memory restrictions                                   | `tests/src/core/reactive/test_env.py`, `tests/src/core/invoker/test_claude_invoker.py`                       |
| Codex controls              | Worker overrides present; managed exec/resume requests retain their normal delegation configuration                         | `tests/src/core/invoker/test_codex_invoker.py`, `tests/src/core/ops/test_codex_session.py`                   |
| Retry and environment order | JSON-format retry, resumed worker and late env unsets preserve the same worker restrictions                                 | `tests/src/core/invoker/test_claude_invoker.py`, `tests/src/core/reactive/test_session_runner.py`            |
| Pinned runtime              | Claude/Codex worker probes verify native delegation unavailable, including fork-context skills, and memory controls emitted | Extend `tests/integration/docker/test_policy_hooks.py`, `tests/integration/cli/test_workflow_codex_smoke.py` |
| Clean installation          | Wheel-installed workers exercise both runtime paths; verification names runtime and wheel versions                          | `tests/integration/cli/test_workflow_codex_smoke.py`                                                         |

## Design-doc sync

`docs/design_workflows.md` (worker boundary and verification); `docs/design_memory.md` (worker-native-memory exclusion);
`docs/end-user/workflow.md` and `docs/end-user/memory.md`.
