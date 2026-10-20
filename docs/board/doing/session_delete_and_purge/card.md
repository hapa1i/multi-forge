# Split session delete from purge

**Status**: Implementation and final verification, 2026-10-20, on `codex/session-delete-and-purge` from `a33c4d24`.
Proposed 2026-10-19 from an owner decision: normal delete removes Forge data only; a separate purge removes the
session's identified local content within its declared scope. The [checklist](checklist.md) orders the implementation
gates. Related: [`session_delete_generation_token`](../../proposed/session_delete_generation_token/card.md), the
proposed instance-identity prerequisite. The [source audit](evidence/ownership-audit.md) records the earlier behavior;
[verification](evidence/verification.md) and [native evidence](evidence/README.md) record the implementation checks.

## Problem

Observed at `ad8b8245`, `forge session delete <name>` mixes two intents and serves neither:

| Data                                                                    | Today                                 |
| ----------------------------------------------------------------------- | ------------------------------------- |
| Session record: `.forge/sessions/<name>/`, index row, active entry      | Removed                               |
| Claude transcript and subagent logs in `~/.claude/projects/`            | Removed unless `--keep-transcripts`   |
| Codex rollout in `$CODEX_HOME/sessions/`                                | Never removed                         |
| `.forge/artifacts/<name>/`: transcript copies, plans, journals, reports | Kept unless inside a removed worktree |
| Search index documents                                                  | Kept and searchable                   |
| Transfer snapshots in `.forge/prev_sessions/`                           | Kept; `forge clean` removes orphans   |
| Owned, unshared worktree / branch                                       | Removed / kept                        |

At the audited base, adopted conversations and transcript UUIDs referenced by another session were exempt from
transcript removal
([`SessionManager.delete_session`](https://github.com/hapa1i/multi-forge/blob/a33c4d244d323728b55a94beac4f66010b9c0e15/src/forge/session/manager.py#L2122)).

- A user who only wants Forge to forget the session loses the native Claude conversation, which would otherwise stay
  resumable from its original directory and re-adoptable with `forge session adopt`.
- A user who wants the conversation gone keeps Forge's own copy, still found by `forge search query`. Nothing but
  worktree removal deletes `.forge/artifacts/<name>/`.
- Claude and Codex differ: Forge-launched Claude transcripts are deleted, Forge-launched Codex rollouts never are. The
  [session guide](../../../end-user/session.md) documents only the Claude half.
- `forge session clean`, `session_retention_days` auto-cleanup and incognito exit inherit the same mix.

Two gaps were reproduced with synthetic state on 2026-10-20:

- **Incognito leftovers.** Stop copies the transcript into `.forge/artifacts/<name>/transcripts/`
  ([`_capture_transcript_artifact`](https://github.com/hapa1i/multi-forge/blob/a33c4d244d323728b55a94beac4f66010b9c0e15/src/forge/cli/hooks/commands.py#L139)).
  No incognito guard was found on that path, and incognito exit runs an ordinary delete, which keeps artifacts. The
  reproduction removed the native transcript and session record but retained a byte-identical Forge transcript copy.
- **Name reuse.** Artifacts are keyed by session name. The review journal is scoped to a per-instance owner, but the
  authority and routing journals (`.forge/artifacts/<name>/{authority,routing}/events.jsonl`) showed no instance
  binding. After real manager deletion and same-name publication, the reproduction read both predecessor event IDs from
  the replacement session; its review identity was distinct.

## Proposed contract

Ownership defines the split: **delete** removes what Forge owns for the session; **purge** also removes identified
native conversation files. Both preserve the worktree/branch choices and dirty-worktree guard. Purge additionally
requires verified native identity and inactivity; `--force` cannot override these or dependency refusals.

| Data                                                                        | `delete`        | `purge`         |
| --------------------------------------------------------------------------- | --------------- | --------------- |
| Session record                                                              | Remove          | Remove          |
| Forge content (artifacts, own transfer snapshots, search docs, queued work) | Remove          | Remove          |
| Native conversation (Claude transcript and subagent logs, Codex rollout)    | Keep            | Remove          |
| Target referenced by another existing session                               | Refuse and list | Refuse and list |
| Global telemetry                                                            | Keep            | Keep            |

**Delete.** The native conversation becomes an ordinary runtime conversation. When delete also removes the worktree, the
preview must say that the kept conversation's directory is going away, so it cannot be resumed or adopted there. **Owner
decision, 2026-10-20:** refuse while dependent sessions exist. Keeping artifact files alone cannot preserve lineage,
inherited plan lookup, or a supervisor binding that still reads the parent manifest. The first version does not
introduce a separate ancestor archive or silently break those references. "Existing" includes inactive sessions, across
Forge roots; it does not mean only a running process. Queued and already-running handoff, index and shadow work must not
recreate content after a successful delete.

**Purge.** Erases the local copies Forge can identify for the session:

- Refuse an active session with no `--force` override; a running runtime keeps writing the files being removed.
- Build the inventory from recorded evidence: current and rollover Claude UUIDs, relocated and rewind copies, the Codex
  thread and rollout path. Re-verify containment and provenance-specific identity before unlinking. Original, relocated
  and rewind Claude files need distinct checks; Codex requires exact supported thread/header metadata. Adoption lookup
  alone is not deletion authority. The native-layout gate must establish the admitted forms. Never delete by glob.
- Include an adopted session's native conversation, labelled in the preview as created outside Forge.
- Refuse when another existing session shares a native UUID (for example a native-relocate copy) or holds content
  derived from this one, naming those sessions. No implicit cascade.
- Preserve a durable cleanup inventory until every planned removal succeeds. Current delete can remove a worktree
  containing its manifest before native cleanup, and some native errors are only logged; that path cannot provide this
  guarantee unchanged. A partial failure must exit non-zero, list what remains, and retain enough verified identity for
  the same command to retry without claiming a replacement session's files.
- State what purge cannot reach: provider-side copies of requests already sent, project memory docs the memory writer
  edited, git history, telemetry, and runtime-internal state not pinned by probes (for example
  `~/.claude/file-history/`, `~/.claude/history.jsonl` and Codex indexes).

## CLI shape

- `forge session delete <name>...`: delete semantics. Remove `--keep-transcripts` from `delete` and `clean` as a clean
  break, and update the recovery hints that print it (`_rollback_created_session` in
  [`session_lifecycle.py`](../../../../src/forge/cli/session_lifecycle.py) and
  [`session_fork_execution.py`](../../../../src/forge/core/ops/session_fork_execution.py)).
- `forge session purge <name>...` or `forge session purge --all`: new leaf verb. Preview by default, `--yes` to apply,
  `--json` for the preview. The preview lists absolute paths grouped by owner (Forge project, Claude store, Codex store)
  plus the out-of-reach list. A separate verb keeps the irreversible scope visible in help and shell history; appending
  one flag to a habitual `delete --yes` must not reach it.
- **Owner addition, 2026-10-20:** `purge --all` selects sessions in the current Forge project, including incognito, like
  `delete --all`. It requires a Forge project and cannot be combined with explicit names. Preview lists eligible targets
  and per-session refusals; apply processes only the initially admitted set and exits non-zero if any target is refused
  or fails. An empty project succeeds without changes. Bulk selection does not bypass activity, identity or dependency
  guards, including dependencies between selected sessions. New or replacement sessions cannot silently enter an
  already-approved batch, and processing order cannot admit an initially refused target.
- `forge session clean`, `delete --all` and `session_retention_days` auto-cleanup keep delete semantics. Bulk purge
  requires an explicit `purge --all` invocation.
- Incognito exit is the explicit automatic-purge exception, authorized by starting the ephemeral session. It runs only
  after the runtime exits, obeys the same identity/dependency guards, and reports incomplete cleanup with a retry path.
- A `forge clean` category for artifact trees with no session lets users reclaim trees left by earlier deletes.

## Discovery and implementation gates

1. Inventory every location that receives session content: artifact transcripts, compaction snapshots, pending-run
   copies (`_copy_transcript_to_pending_runs`), plans, memory and curation reports, shadow candidates, transfer
   snapshots, the search index and work-queue payloads. Record each location's owner and referencing fields.
2. Convert the incognito and name-reuse reproductions into regression tests; account for existing tests that
   deliberately assert journal retention under the old contract.
3. Probe which native files belong to one Claude conversation and one Codex thread on the pinned client versions. These
   layouts are undocumented third-party details, so pin them the way the Codex hook probes are pinned.
4. Enumerate cross-session references: supervisor plan paths, derivation transcript and context files, native-relocate
   and rewind copies, and lineage traversal ([`resolve_lineage`](../../../../src/forge/session/transfer.py#L1026) walks
   ancestor manifests).
5. Settle session-instance ownership and writer exclusion before adding new destructive paths. A terminal index-row
   guard alone cannot prevent an already-running worker or stale deleter from recreating or deleting artifacts.

## Acceptance

- Delete leaves Claude transcripts, subagent logs and Codex rollouts byte-identical; removes the Forge record and its
  unreferenced Forge content; and refuses named dependencies before mutation.
- Purge removes exactly the previewed set; preview and apply agree on targets and refusals.
- `purge --all` respects the same project boundary as `delete --all`; explicit-name conflicts, outside-project
  invocation, an empty project, mixed eligible/refused targets and changed batch membership are covered.
- Purge refuses active sessions, shared native UUIDs and dependent sessions by name; a partial failure retries cleanly.
- A recreated session name starts without predecessor content or journal history.
- Queued work for a deleted or purged session recreates nothing.
- Regression tests cover each confirmed gap. Targeted Docker integration exercises delete and purge against real Claude
  and Codex files, per the session-lifecycle integration rule.
- Update the [session guide](../../../end-user/session.md), [CLI reference](../../../cli_reference.md),
  [session design](../../../design_sessions.md) (adoption transcript ownership),
  [session context design](../../../design_session_context.md) (journal survival) and the session-deletion paragraph in
  [`AGENTS.md`](../../../../AGENTS.md).

## Implementation direction and remaining decisions

1. Follow the proposed separate `forge session purge` verb and removal of all session journals. An artifact-retention
   option is outside the first version.
2. Both verbs refuse dependencies; there is no implicit cascade or acknowledged partial purge.
3. Instance identity is a prerequisite, not an optional cleanup improvement. The
   [generation-token proposal](../../proposed/session_delete_generation_token/card.md) is folded into this card's
   implementation and PR: its row guard alone cannot authorize content removal without the same writer and retry fences.
   The branch starts at `a33c4d24`; identity lands before cleanup integration, and this card owns the combined tests,
   review and closeout. The proposal will retire as absorbed when this implementation ships, with no separate shipped
   credit. The existing per-creation review owner becomes the session instance; index v1 is read without mutation and
   confirmed operations explicitly bind legacy rows before destructive work.
4. Native inactivity, relocated/rewind identity, corrupt or missing inventories, and recovery when the Forge root itself
   is removed remain gated by the checklist. Do not present current adoption lookup or the Forge active registry alone
   as proof of safe native deletion.
