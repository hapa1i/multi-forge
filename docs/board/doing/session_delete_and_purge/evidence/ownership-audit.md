# Delete and purge ownership audit

Read-only source audit and isolated reproductions, 2026-10-20, at `a33c4d24`. This records current behavior and
implementation gates, not a claim that purge is implemented or that native layouts have been verified.

## Confirmed current behavior

`SessionManager.delete_session` removes the session record and optionally a worktree and Claude transcript files. It
does not coordinate removal of Forge artifacts, transfers, search documents or queued work. Codex rollouts are not part
of its native cleanup. See [manager.py](../../../../../src/forge/session/manager.py#L2122) and the
[current artifact contract](../../../../design_session_context.md).

Two synthetic reproductions exercised the actual cleanup paths using `.venv/bin/python`, temporary project/home
directories and coherent session publication through `tests.fixtures.session_state`. They read no real conversations,
made no native-client or provider call, and removed their temporary trees afterwards:

- **Incognito:** publish `is_incognito=True`, create a synthetic native transcript, call `_capture_transcript_artifact`,
  then `_run_incognito_cleanup`. Capture reported `copied=true` and `manifest_updated=true`; cleanup reported success
  without a warning. The manifest, index row and native transcript were absent afterwards. The Forge transcript artifact
  still existed with identical bytes.
- **Name reuse:** publish a session, append authority and routing events, call real manager deletion with native and
  worktree cleanup disabled, then publish a same-name replacement with a different creation timestamp and no authority.
  The replacement read both predecessor event IDs; its review identity was different.

The source paths agree with these observations:

- [Transcript capture](../../../../../src/forge/cli/hooks/commands.py#L139) copies before manifest mutation and has no
  incognito guard. [Incognito exit](../../../../../src/forge/core/ops/claude_session.py#L1365) calls ordinary delete.
- [Journal paths](../../../../../src/forge/session/events.py#L350) bind authority/routing to root and name; review alone
  adds a per-instance owner. [Routing reads](../../../../../src/forge/session/routing.py#L124) do not filter by creation
  time.

These establish bugs under the new cleanup contract. Regression tests still need to be committed with the fixes.
Existing [retention unit tests](../../../../../tests/src/session/test_authority_retention.py#L127) and
[incognito integration](../../../../../tests/integration/docker/test_session_lifecycle.py#L144) intentionally assert the
old journal-survival contract and must change explicitly.

## Content inventory

Paths below are ownership candidates, not permission to remove everything beneath them.

| Location                                     | Content                            | Ownership/reference evidence                  |
| -------------------------------------------- | ---------------------------------- | --------------------------------------------- |
| `.forge/sessions/<name>/`                    | Manifest and runtime state         | Index, active registry, instance owner        |
| `.forge/artifacts/<name>/transcripts/`       | Transcript and compaction copies   | `confirmed.artifacts`, `confirmed.compaction` |
| Artifact `plans/`                            | Approved snapshots                 | Plan records, supervisor paths                |
| Artifact `authority/`, `routing/`, `review/` | Event journals                     | Name; review adds owner                       |
| Artifact `handoff/`, `memory/`, `shadow/`    | Reports and candidates             | Session and source paths                      |
| `.forge/prev_sessions/<parent>/`             | Transfers and notes                | `derivation.context_file`                     |
| `.forge/search-index/`                       | Search text and indexes            | Absolute source transcript paths              |
| `$FORGE_HOME/pending-work/`, `failed/`       | Deferred job payloads              | UUID, name, roots and source paths            |
| `$FORGE_HOME/manual-testing/…/runs/`         | QA/walkthrough transcript copies   | Pending marker, optional UUID                 |
| `$FORGE_HOME/reviewers/codex/`               | Reviewer transcript prefixes/index | Native sources and reviewer lease             |

**Artifacts and transfers.** [Artifact helpers](../../../../../src/forge/session/artifacts.py) own transcript, rollover,
PreCompact and approved-plan copies. [Memory reports](../../../../../src/forge/session/memory_writer.py#L735),
[curation reports](../../../../../src/forge/session/shadow_curation.py#L231) and
[shadow candidates](../../../../../src/forge/policy/semantic/shadow.py#L290) contain session-derived material.
[Transfer storage](../../../../../src/forge/session/prev_sessions.py#L32) includes generated context, child snapshots
and user-authored `.notes.md` overlays; the preview must disclose the latter. Existing
[transfer GC](../../../../../src/forge/core/ops/gc.py#L315) provides cross-root reference and unreadable-manifest
precedent.

**Search and jobs.** [Index dispatch](../../../../../src/forge/cli/main.py#L236) stores transcript documents without
checking session liveness. Removal must coordinate `documents.json`, `bm25_index.json`, `content.json` and `state.json`;
deleting source files alone leaves searchable text.
[Queue payloads](../../../../../src/forge/core/workqueue/queue.py#L178) do not carry a session-generation identity.
Deleting markers alone cannot revoke already-dispatched work.

**Copies outside project artifacts.** [Pending-run capture](../../../../../src/forge/cli/hooks/commands.py#L1787) can
write full transcripts into QA/walkthrough run directories; its optional UUID check and consumed marker do not provide a
durable reverse ownership inventory. Legacy copies require a supported attribution rule or an explicit
unreachable/unknown result.
[Codex reviewer preparation](../../../../../src/forge/core/reactive/codex_reviewer_home.py#L365) stages source/ancestor
prefixes. Subscription reviewer copies persist after ordinary completion; temporary API homes normally do not. Cleanup
must coordinate the reviewer lease and preserve unrelated inputs.

Project memory documents edited by the memory writer, shared curation documents, telemetry and git history remain
outside session cleanup. A path under a Forge home is not by itself sufficient ownership evidence.

## Dependencies and concurrency

**Owner decision:** both verbs refuse while dependent sessions exist. This includes inactive existing sessions.
Retaining artifact bytes without their parent manifest would not preserve:

- inherited plan resolution, which reads that manifest in
  [plan_resolution.py](../../../../../src/forge/session/plan_resolution.py#L85);
- deeper lineage, which stops on a missing manifest in
  [transfer.py](../../../../../src/forge/session/transfer.py#L1055);
- managed supervisor sources, read again by the
  [Claude supervisor](../../../../../src/forge/policy/semantic/supervisor.py#L424) and
  [Codex source validator](../../../../../src/forge/core/runtime/codex_review_source.py#L233).

The scan must cover parent/derivation names and roots, parent transcript/context paths, supervisor plans and source
bindings, shared native identities, and containing worktrees. Native Codex
[history-base/fork ancestry](../../../../../src/forge/core/runtime/codex_review_source.py#L162) adds references outside
Forge derivation records. Whether unmanaged native descendants can be completely inventoried remains a native-probe
question; do not silently claim they are covered.

The [generation-token proposal](../../../proposed/session_delete_generation_token/card.md) documents the existing
two-deleter/recreate race. Extending removal to name-scoped content requires ownership protection before each mutation,
not only the final index transaction.

Late writes need equivalent protection. The memory writer checks a name at startup but can
[create report directories after its run](../../../../../src/forge/session/memory_writer.py#L758).
[Shadow dispatch](../../../../../src/forge/policy/semantic/shadow_runner.py#L259) is also root/name based. Hooks can
copy and enqueue after a manifest update fails, and
[unmanaged Stop capture](../../../../../src/forge/cli/hooks/commands.py#L526) can still satisfy pending-run markers. The
identity contract must cover those paths before success can mean that cleanup will stay complete.

Root CLI startup currently [drains pending work](../../../../../src/forge/cli/main.py#L457) before session leaf
handlers. Preview purity therefore needs a startup change as well as a read-only planner.

## Retry and native evidence gates

The card's original “record last, as delete does today” premise was incorrect.
[Worktree cleanup](../../../../../src/forge/session/manager.py#L2235) can destroy the containing Forge root and manifest
before native deletion. [Native cleanup](../../../../../src/forge/session/claude/cleanup.py#L64) collects unlink errors
that the manager does not propagate as incomplete deletion; relocated/rewind failures can also be logged and ignored.
Purge requires durable retry inventory and explicit stage results.

Native identity needs provenance-specific checks:

- Claude directory encoding is lossy; [adoption](../../../../../src/forge/core/ops/session_adopt.py#L562) also checks
  recorded CWD. Native-relocate preserves source bytes and their original CWD.
- Rewind intentionally uses a fresh filename UUID while preserving embedded parent IDs, as recorded by the
  [rewind contract test](../../../../../tests/integration/docker/test_rewind_native_contract.py#L3). Unconditional
  filename/header equality would reject legitimate rewind copies.
- Codex adoption discovery is more permissive than deletion authority. The bounded, no-symlink
  [native-source reader](../../../../../src/forge/core/runtime/codex_review_source.py#L77) is relevant precedent, but
  does not establish exhaustive runtime-file ownership.
- Forge's active registry cannot establish that an adopted conversation has no separately running native writer.
  Inactivity and races with native resume must be addressed before admitting purge.

Native evidence must use disposable conversations and isolated stores on recorded client versions. Existing
[host Codex integration setup](../../../../../tests/integration/conftest.py#L22) restores the real `CODEX_HOME`; do not
reuse it for destructive tests. Offline fixtures can verify byte preservation, exact targets, dependencies, races and
failure recovery. They cannot establish undocumented current runtime layout or the absence of additional native copies.

No native probe or paid call ran during this audit.
