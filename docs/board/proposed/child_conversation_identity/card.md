# child_conversation_identity -- preserve the lead while recording child conversations

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M1 -- the forcing hazard; ships first).

**Lane**: `proposed/`. No dependencies. M3a, M5, M6 and M7 consume the ownership decision made here.

## Problem (code verified 2026-09-06; live reproduction pending)

- `resolve_session_name` in `src/forge/session/hooks/session_start.py` resolves `FORGE_FORK_NAME`, then `FORGE_SESSION`,
  then the UUID index. A descendant inheriting that environment resolves to the lead manifest.
- A differing startup UUID logs `SessionStart: pre-seeded UUID mismatch` before the handler writes
  `confirmed.claude_session_id` and `transcript_path`. The path can overwrite the lead if the caller is a descendant.
- `_capture_transcript_artifact` in `src/forge/cli/hooks/commands.py` also reconciles the root binding. Stop and
  StopFailure reach it; PreCompact and downstream index, memory and verification work must use the same ownership
  decision. Fixing only SessionStart leaves later writers able to undo the fix.
- Reconciliation also serves legitimate native forks. `tests/regression/test_bug_supervisor_fork_uuid_drift.py` covers
  parent UUID at SessionStart and child UUID at Stop. `test_bug_21x_fork_launch_handoff.py` covers launch handoff, not
  that complete UUID transition.
- The proposed `task_name` drift fix was unsupported. The current
  [TaskCompleted contract](https://code.claude.com/docs/en/hooks#taskcompleted-input) still names `task_subject`,
  matching `src/forge/policy/team/handlers.py`; `team_name` is deprecated. Retain `task_subject`, tolerate absent
  `team_name`, and add compatibility aliases only if an actual versioned payload demonstrates them.

## Blocking identity probe

Before choosing the classifier, run an interactive managed Claude session with a real teammate and agent-view background
copy. Record runtime version, event, process origin, native id, transcript path, and available ancestry metadata. Cover
startup, resume, compact, clear, PreCompact, Stop, StopFailure, and a deliberately missed SessionStart (lock timeout or
absent hook). Probe native fork root rollover in the same harness.

The implementation must pin positive evidence distinguishing a descendant from a legitimate root transition even when
SessionStart was missed. `FORGE_SESSION`, `source=startup`, a UUID mismatch, or a launch token inherited by every child
cannot establish that distinction. Team membership can establish a teammate only when the native identity join is
verified; absence from a team file does not prove a root or background copy. If the runtime exposes no reliable
discriminator for a path, record that limitation and keep the affected launch mode unsupported until resolved.

`tests/integration/docker/test_team_hooks.py` currently exercises constructed payloads. Extend it with an actual
interactive/PTY team probe (or a separately named integration file); Claude `-p` cannot reproduce a native team.

## Design

One classifier runs under the existing manifest lock before any lifecycle binding write or root side effect. Its result
is root, evidenced root transition, descendant, or unresolved, together with the evidence used.

| Incoming evidence                                                                                 | Binding and side effects                                                                                                            |
| ------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Current root id or established root alias                                                         | Preserve root ownership; perform that event's existing root work                                                                    |
| Validated initial/root launch identity, including native-fork transition                          | Establish or advance the root binding using the probed transition rule; retain root aliases needed by later hooks                   |
| Positively identified descendant, including one whose SessionStart was missed                     | Record/update child ownership; never write root binding, root transcript pointer or root UUID index                                 |
| Different id without sufficient origin evidence, including a null binding without launch evidence | Preserve the root and indexes; record an unresolved event for diagnosis/reconciliation; perform no root verification or memory work |
| Lock timeout                                                                                      | Leave binding and derived indexes untouched; existing fail-open hook behavior with diagnostic                                       |

Apply this table to every SessionStart source, PreCompact, Stop and StopFailure. A child's compact/clear/resume
transition stays in the child's identity lineage; it cannot become the lead through a different event name. Index
publication, active-session routing, transcript capture, memory handoff markers and Stop verification consume the same
result. Unresolved events must not enqueue work labeled as root.

- **Schema.** Hook-owned `confirmed.children[<native-conversation-uuid>]` records kind, nullable name/type, owning
  parent id, classification evidence, first/last seen, last stop, and observed transcript location. Unknown kind is
  valid after descendant ownership is proven; unknown ownership is not a child binding. Root aliases and child
  transitions have explicit ownership, not precedence guesses.
- **Child handling.** Child Stop skips root memory and Stop verification. Capture/index requests carry child identity;
  M3a supplies the immutable snapshot and metadata contract. M1 must preserve the observed child path and any existing
  child artifact without promoting either to the root transcript pointer.
- **Read surfaces.** `forge session show --json` exposes children and unresolved identity events separately.
  `forge telemetry activity` attributes child stops separately from root stops.
- **Concurrency.** Classification, state mutation and index intent are coherent under the lock. Repeated events are
  idempotent; delayed root/child events cannot roll a newer binding backward.

## Non-goals

No orchestration, child resume command, worktree lifecycle, or per-role policy. M3a captures Claude in-process sources;
M3b owns Codex sources. The root/child distinction must preserve existing native-fork behavior.

## Acceptance

Rows below specify required additions or preservation checks, not evidence already collected.

| Test                                      | Fixture and assertion                                                                                            | Test file                                                                               |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Complete lifecycle classification         | Probe-derived root, child and unresolved payloads for every event/source; only evidenced root transitions rebind | `tests/src/session/hooks/test_session_start.py`, `tests/src/cli/test_artifact_hooks.py` |
| Native fork UUID drift                    | Parent id at SessionStart, child id at Stop remains a root transition                                            | `tests/regression/test_bug_supervisor_fork_uuid_drift.py`                               |
| Native fork launch handoff                | Existing launch/adoption and transcript selection remain correct                                                 | `tests/regression/test_bug_21x_fork_launch_handoff.py`                                  |
| Missed start, compact/clear and late Stop | Descendant evidence prevents all root writes/markers; ambiguous evidence preserves root and reports unresolved   | New `tests/regression/test_bug_child_hook_overwrites_lead.py`                           |
| Concurrent/repeated events                | Lock loss and interleaved root/child events preserve bindings, active/UUID indexes and marker ownership          | `tests/src/cli/test_artifact_hooks.py`                                                  |
| Team payload compatibility                | Official `task_subject` payload works without `team_name`; no invented `task_name` requirement                   | `tests/src/policy/team/test_handlers.py`                                                |
| Read surfaces                             | Child and unresolved events have distinct JSON/activity attribution                                              | `tests/src/cli/test_session_activity_summary.py`                                        |
| Live managed team and background copy     | Interactive Docker/PTY probe, including missed start and native fork; lead resumes its own conversation          | Extend `tests/integration/docker/test_team_hooks.py`; retain payload-only coverage      |

## Design-doc sync

`docs/design.md` §3.5 (ownership); `docs/design_sessions.md` §3.3 and hook lifecycle sections (schema, transitions,
aliases, unresolved handling and index routing); `docs/design_workflows.md` §1.2 (payload compatibility only);
`docs/end-user/session.md` and `docs/end-user/hook.md` (supported modes, child visibility and recovery). Do not describe
teams as safe under Forge until the live acceptance gate passes.
