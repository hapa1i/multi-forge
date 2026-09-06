# child_transcript_snapshots -- define the source contract and retain Claude child evidence

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M3a -- common source contract and Claude
capture).

**Lane**: `proposed/`. Depends on M1. Replaces the Claude/shared portion of the former M3 scope.
[Codex source support](../codex_source_adapter/card.md) is M3b and does not gate this card's closeout.

## Problem (verified 2026-09-06)

- Claude subagent records live at `~/.claude/projects/<project>/<session>/subagents/agent-<id>.jsonl`. The review
  recorded metadata fields `agentType`, `description`, `toolUseId` and `spawnDepth`. Native cleanup uses
  `cleanupPeriodDays`, default 30 days. The [epic appendix](../epic_native_multiagent/card.md#appendix-runtime-evidence)
  distinguishes documented behavior from sample observations that need a retained fixture.
- Team config/inboxes under `~/.claude/teams/<team-name>/` are removed at session end; the task directory under
  `~/.claude/tasks/<team-name>/` persists. Their capture opportunity differs from transcript retention.
- `SubagentConfirmed` in `src/forge/session/models.py` and the subagent hooks record counters, the latest transcript
  path and a preview, but no durable per-child artifact inventory.
- Team hooks in `src/forge/cli/hooks/commands.py` return early when supervision is disabled. Capture behind that guard
  would depend on an unrelated feature.
- `src/forge/core/transcript.py` and transfer/search have their own Claude-oriented readers. Downstream consumers need
  one source/coordinate contract before a second runtime adapter is added.

## Common source and reader contract

M3a defines and implements the interface, citation formatter and Claude adapter. M3b implements Codex against this
interface; M4 and M6 can consume it independently without waiting for a Codex rollout.

- **Identity:** stable source id from canonical Forge root, owning session, runtime, source kind and native id. Snapshot
  hash identifies an immutable version, not a new logical source. Encode opaque ids safely and validate path
  containment.
- **Ownership:** M1's hook-owned `confirmed.children[uuid]` identifies Claude conversation children.
  `confirmed.subagents.entries[agent_id]` additionally records the owning conversation UUID and native joins. Other
  runtime adapters supply equivalent source ownership without adopting Claude's manifest-write rules.
- **Metadata:** source identity, runtime/version, native/parent ids, nullable kind/name/type/description, depth and
  spawning join, original path, capture time/hash, completion state, retained/omitted ranges and unavailable reasons.
- **Coordinates:** preserve original zero-based JSONL record indices and byte ranges. Native history ordinals are
  separate coordinates with an explicit mapping to records, never assumed to equal file lines. Optional turn numbers
  retain their original mapping. The interface distinguishes own history from inherited prefix and unresolved coverage.
- **Reader:** expose available messages, tool/function calls and outputs, compaction boundaries, joins and coordinates
  in physical append order. Preserve unknown/encrypted availability as metadata instead of fabricating plaintext.
  Snapshot selection is by source identity/coverage, never whichever file sorts last.
- **Citations:** shared formatter/resolver uses source id plus record/turn coordinate and captured version, for example
  `[source-id:record 37]`. Team JSON uses file/item anchors and Markdown uses lines. M6 owns the search command and
  result schema, not this formatter; M4 has no dependency on M6.
- **Conformance:** synthetic normalized events cover missing joins, unavailable content and inherited-history mappings.
  Claude fixtures exercise the adapter. Actual Codex record shapes and prefix extraction belong to M3b.

Route existing Claude root transfer through this reader while preserving current behavior. That completes the interface
needed by M4; no Codex root transfer is a prerequisite.

## Claude capture and shared retention

- Capture in-process sources at SubagentStop and classified conversation children at their lifecycle boundaries.
  PreCompact/root Stop may refresh known children. Keep existing counters and root artifact selection; a child cannot
  become the root's latest transcript.
- Copy team config, task and inbox files before supervisor enablement, throttling or LLM work. Capture failure is
  isolated from gate decisions, and gate failure does not suppress capture. TeammateIdle/TaskCompleted and the final
  available boundary are opportunities subject to the live cleanup-timing probe.
- Store child versions under `transcripts/children/<safe-source-id>/<sha>.jsonl` with metadata sidecars. Team versions
  use source id and content hash under `team/`. Preserve existing Claude root artifact paths.
- Shared defaults: `transfer.child_snapshot_max_bytes=8388608` (8 MiB per snapshot) and
  `transfer.child_snapshot_total_max_bytes=134217728` (128 MiB of unique child/team payloads per session), both positive
  integers. Deduplicate identical copies; when capacity is exhausted retain bounded omission metadata rather than
  replacing cited versions. Existing root artifact retention remains unchanged.
- Retain only complete JSONL records within a tail budget; never cut UTF-8 or a record. Omit oversized records
  explicitly, keeping original coordinates. Team JSON is a complete retained file or an explicit omission.
- Snapshots share the session artifact lifetime. Atomic capture, hashes and incomplete-final-record detection report
  partial capture and allow later retry. Do not evict frozen/cited versions or promise recovery of unseen abrupt-exit
  evidence.
- Track observed usage coverage independently of retained bytes. Missing usage is unavailable, not zero; exclude
  inherited duplicates where the adapter identifies them. Activity exposes per-child token observations, not inferred
  dollar costs.

## Non-goals

No Codex discovery/receipts/source launch, search command, child strategy renderer, orchestration or worktree lifecycle.
M3b reuses this retention/reader contract rather than creating another one.

## Acceptance

| Test                        | Fixture and assertion                                                                                            | Test file                                                                                                        |
| --------------------------- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Claude reader compatibility | Existing root transfer and child fixture retain available evidence and original append-order coordinates         | `tests/src/session/test_transfer.py`, `tests/src/search/test_extractor.py`                                       |
| Source conformance          | Synthetic unavailable/inherited/partial events preserve typed coverage and source-qualified citations            | `tests/src/session/test_transfer.py`                                                                             |
| Child capture               | Subagent/conversation payloads retain immutable versions, joins and root separation                              | `tests/src/cli/test_artifact_hooks.py`                                                                           |
| Caps and coordinates        | Multibyte text, oversized/partial records and aggregate exhaustion preserve valid JSONL and original coordinates | `tests/src/cli/test_artifact_hooks.py`                                                                           |
| Team independence           | Disabled/throttled/failing supervision does not suppress capture; old versions survive                           | `tests/src/policy/team/test_handlers.py`, `tests/src/cli/hooks/test_team_hook_feedback.py`                       |
| Activity                    | Partial or absent usage remains explicit and cannot become a zero-dollar fact                                    | `tests/src/cli/test_session_activity_summary.py`                                                                 |
| Live capture                | Installed hooks capture a real subagent/team before observed cleanup; record runtime version and capture gaps    | Extend `tests/integration/docker/test_team_hooks.py`, `tests/integration/cli/test_artifact_hooks_integration.py` |

## Design-doc sync

`docs/design.md` (shared source/citation ownership); `docs/design_sessions.md` §3.3 and §3.8 (Claude schema and
artifacts); `docs/design_telemetry.md` (usage coverage); `docs/end-user/hook.md`, `docs/end-user/session.md` and
`docs/end-user/transfer.md`. Describe the shipped Claude adapter; M3b owns later Codex claims.
