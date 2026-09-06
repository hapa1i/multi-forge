# lineage_search_retrofit -- retrieve retained evidence across the receiving session's lineage

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M6 -- lookup over carry).

**Lane**: `proposed/`. Depends on M3a. May run alongside M4 and M3b; ships before M5 emits its lookup command. Owns the
result schema and invocation, consuming M3a's source/citation contract. Standalone acceptance covers Claude, team and
handoff sources; the epic owner verifies Codex parity at P3 after M3b.

## Problem (verified 2026-09-06)

- `src/forge/cli/search.py` scans canonical transcript artifacts and selects the current Forge root's index. Child
  snapshots, team versions and handoffs are not complete index inputs.
- `src/forge/search/extractor.py` supports Claude tool blocks, including non-string results, but not Codex rollout
  semantics. M3a supplies a runtime-neutral reader with Claude support; M3b later provides the Codex adapter.
- Transfer/worktree creation in `src/forge/cli/session.py` and session derivation retain parent source roots while the
  child runs from another Forge root. A CWD-only `--lineage child` lookup cannot find those ancestor artifacts.
- Current search lacks a lineage closure and citations that distinguish identical turn numbers in different sources.
  Dedupe by session/turn would collapse unrelated child records.

## Design

### Sources and index identity

Index M3a's Claude root/child snapshots, retained team records and handoffs under `prev_sessions/`, including frozen
child snapshots and M9's reviewed-artifact shape when present. Mark generated, frozen and reviewed handoffs as distinct
versions. Fixtures can exercise that documented shape before M9 ships; M6 does not create or select reviewed artifacts.

Use M3a source ids and original record identities to deduplicate overlapping transcript snapshots. A source's native
record id, or original record coordinate plus content identity, determines overlap; unrelated children never collide.
Exclude inherited records through the shared source mapping before indexing. Index available plaintext only, with
coverage metadata for encrypted, truncated, unresolved or missing sources. Handoff prose remains a separate source, not
transcript evidence.

Extend rebuild and queued marker draining to these source kinds. Marker payloads carry owning root/session and source
identity. An ordinary query reads indexes without repairing manifests or mutating lineage state.

### Lineage and invocation

`--lineage <session>` selects that session, its ancestors, and each selected session's recorded descendants.
`--lineage-root <absolute-forge-root>` selects the starting root and requires `--lineage`; omitted root defaults to the
current root. These scope options apply to query and rebuild-index. Default project search is unchanged.

M6 owns this command template:

```bash
forge search query "<terms>" --lineage <session> --lineage-root <absolute-forge-root> --json
```

M5 renders shell-quoted source-session and source-root values. A handoff names its immediate parent as the starting
session so a frozen parent-generated transfer stays independent of the receiving child's name and CWD. That closure
includes the parent, its ancestors, and their recorded native children.

Resolve each parent using its stored derivation source root and identity, traversing only explicit lineage links. Track
visited root/identity pairs; handle cycles, missing roots, corrupt records and duplicate session names. Pin the parent's
native/source identity when writing new derivations so a deleted and reused name cannot substitute an unrelated session.
Legacy unpinned edges that cannot be verified report incomplete coverage rather than guessing. Do not expand to all
workspace or project roots.

Missing/stale indexes and inaccessible ancestors return available matches plus structured incomplete-coverage reasons
and an actionable root-qualified rebuild command. JSON results stay on stdout; diagnostics go to stderr and incomplete
coverage exits non-zero. Search must not report an exhaustive negative result when a source could not be searched.

### Results and citations

Stable JSON contains matches and coverage. Each match carries source id/kind, owning root/session, runtime/native id,
snapshot hash/path, typed anchor and snippet. Human output includes source-qualified citations, such as
`[source-id:record 37]` or a mapped `[source-id:turn 12]`; team JSON uses file/item anchors and Markdown uses lines. A
citation resolves to the retained version even after later capture. Use M3a's formatter, also consumed by M4/M5.

## Non-goals

No embeddings, native-memory-directory indexing, or general cross-project search expansion. Explicit derivation
traversal is the only new cross-root scope. Imports in a selected handoff are searchable as that handoff's content.

Codex search uses the same reader/index interface after M3b. Actual rollout, prefix and cross-root Codex assertions
belong to P3 in the [epic parity table](../epic_native_multiagent/card.md#codex-parity-closeout), not unfinished rows on
this card. Advertise the installed adapter coverage accurately until that gate passes.

## Acceptance

| Test                           | Fixture and assertion                                                                                                 | Test file                                                                                 |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Supported source kinds         | Claude roots/children, team JSON and generated/frozen/reviewed-shape handoff fixtures produce typed hits              | `tests/src/cli/test_search.py`, `tests/src/search/test_extractor.py`                      |
| Overlapping snapshots          | Repeated pre-compact/root copies dedupe; different children with equal turn numbers remain distinct                   | `tests/src/search/test_engine.py`                                                         |
| Source conformance             | Synthetic normalized inherited/unavailable records are excluded through the shared mapping; coverage remains explicit | `tests/src/search/test_extractor.py`                                                      |
| Cross-root lineage             | Worktree child finds parent/grandparent evidence and their native children, excluding unrelated sessions              | `tests/src/cli/test_search.py`, `tests/regression/test_bug_prev_sessions_parent_scope.py` |
| Missing/cyclic/reused ancestry | No name-only substitution, recursion loop, mutation or silent exhaustive result; JSON reports coverage                | `tests/src/cli/test_search.py`                                                            |
| Command contract               | Rendered source-root command executes from the child CWD, including paths/names requiring shell quoting               | `tests/integration/cli/test_search_workflow_integration.py`                               |
| Coordinate resolution          | Record/turn, team item and handoff line anchors resolve to the cited snapshot version                                 | `tests/src/search/test_engine.py`                                                         |
| Index refresh                  | Child markers update the correct root index; scoped rebuild includes explicit ancestor roots only                     | `tests/integration/cli/test_search_workflow_integration.py`                               |

## Design-doc sync

`docs/design.md` (index inputs and source identity); `docs/design_sessions.md` (pinned derivation source and cross-root
retrieval); `docs/end-user/search.md` (scope, coverage, citations and invocation); `docs/end-user/transfer.md` (lookup
from a child worktree); `docs/cli_reference.md`.
