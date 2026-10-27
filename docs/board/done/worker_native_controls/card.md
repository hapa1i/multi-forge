# worker_native_controls -- disable native delegation and memory in Forge-owned workers

**Epic**: [epic_native_multiagent](../../proposed/epic_native_multiagent/card.md) (M0 -- independently shippable worker
defaults).

**Lane**: `done/`. Accepted 2026-10-25; [PR #282](https://github.com/hapa1i/multi-forge/pull/282) merged on 2026-10-27
as `ef6a41e1`. See the [merged closeout](checklist.md#merged-closeout). M0 shipped independently; M1 and the broader
epic remain proposed. Managed-session delegation policy remains M7; session memory choices remain M8a.

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

The epic's [runtime evidence appendix](../../proposed/epic_native_multiagent/card.md#appendix-runtime-evidence) records
the version-sensitive control baseline. Environment switches alone do not remove ordinary Agent admission.

## Design

- Apply an explicit worker profile at known worker call sites, covering review panels and every consumer lane. Shared
  helpers must distinguish workers from managed roots; no blanket root restriction and no child-identity lookup.
- Claude worker requests include `--disallowedTools Agent Workflow SendMessage`, `--disable-slash-commands`,
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0`, `CLAUDE_CODE_FORK_SUBAGENT=0`, `CLAUDE_CODE_DISABLE_WORKFLOWS=1`, and
  `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`. The pinned Claude 2.1.245 probe confirmed that a `context: fork` skill can create
  a child with only the originally listed controls; `--disable-slash-commands` closes that admission path. CLI
  `--settings` repeats the four fixed environment values to prevent inherited `settings.env` from re-enabling worker
  capabilities. The launcher composes the complete profile and auth-helper projection into a single settings payload
  before subscription authentication checks; dispatch uses that same configuration.
- Codex worker requests include `--disable multi_agent`, `-c agents.enabled=false`, `-c memories.use_memories=false`,
  and `-c memories.generate_memories=false`.
- Put restrictions in the durable base request used by retries/resumes, after caller environment removal/overrides.
  Cover Claude API-key `--bare`, subscription and proxy paths. A main session's memory allowance cannot relax a worker's
  profile.
- Resumed Claude reviews fork the source with `--fork-session`; parallel workers must leave the source transcript
  unchanged and receive separate native session IDs. Claude launchers require explicit worker selection.
- Record emitted controls and runtime-version verification in worker evidence. Do not infer historical absence of
  delegation or memory use from arguments alone. No new session manifest schema is required for this card.
- The pinned-runtime probe must verify native admission paths, including fork-context skills. If the listed switches
  leave a native path available, identify and apply the supported restriction before claiming the worker profile
  verified. This is a worker capability probe, independent of M7's policy-hook enrollment framework.

## Non-goals

No managed-root envelope, policy CLI changes, child capture, session memory inheritance/import, or continuous runtime
monitoring. Native tool controls do not govern arbitrary external processes launched through Bash or MCP.

## Acceptance

| Test               | Fixture and assertion                                                                            | Test file                                                                                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Worker selection   | All consumer lanes opt in; shared Claude callers must choose explicitly                          | `tests/src/session/test_memory_writer.py`, `tests/src/session/test_shadow_curation.py`, `tests/src/policy/semantic/test_supervisor.py`, `tests/src/policy/team/test_handlers.py` |
| Claude controls    | Hostile settings, overrides, unsets and retries retain the profile                               | `tests/regression/test_bug_worker_native_delegation.py`, `tests/src/core/invoker/test_claude_invoker.py`                                                                         |
| Auth composition   | One settings payload retains the helper and full profile; auth and dispatch snapshots match      | `tests/regression/test_bug_worker_native_delegation.py`, `tests/src/core/reactive/test_supervisor_auth.py`                                                                       |
| Codex controls     | Fresh/resumed workers are restricted; managed exec/resume keep normal configuration              | `tests/src/core/invoker/test_codex_invoker.py`, `tests/src/core/ops/test_codex_session.py`                                                                                       |
| Native admission   | Pinned runtimes reject delegation; an admitted Claude reviewer exercises the guarded helper path | `tests/integration/docker/test_worker_native_controls.py`                                                                                                                        |
| Parallel resume    | Two actual workers fork one source into distinct sessions without changing its bytes             | `tests/integration/docker/test_worker_native_controls.py`                                                                                                                        |
| Clean installation | Native probes use the installed wheel and record runtime and wheel identities                    | `tests/integration/docker/test_worker_native_controls.py`                                                                                                                        |

The pinned-runtime and clean-install assertions are implemented in
`tests/integration/docker/test_worker_native_controls.py` with the reusable local-upstream fixture
`tests/fixtures/worker_native_probe.py`. Native fork composition is covered in
`tests/integration/core/test_codex_fork_supervisor.py`. These replace the proposed extensions to the live-credential
smoke files so the blocking admission probe can run without provider inference. See [verification](verification.md).

## Design-doc sync

`docs/design_workflows.md` (worker boundary and verification); `docs/design_memory.md` (worker-native-memory exclusion);
`docs/end-user/workflow.md` and `docs/end-user/memory.md`.
