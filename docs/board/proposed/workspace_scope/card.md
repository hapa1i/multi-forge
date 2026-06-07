# Workspace Scope — `forge workspace` read surface (Slice 2)

**Status**: Proposed. Read surface (`forge workspace ...`, Slice 2) not yet accepted. Two precursors shipped on branch
`fix/workspace-scope` (2026-06-07, see change_log): (1) the `--scope repo` → `--scope workspace` rename resolving review
concern #1, and (2) **Slice 1** — `project_root` is now consistently `get_main_repo_root()`-derived, so sessions in
manually-created linked worktrees group under `--scope workspace`. Slice 1 makes the core session-grouping query correct
with no new surface; what remains (this card) is the net-new `forge workspace worktrees|status` read surface that joins
`git worktree list` with the session index.

**References**: design.md §3 (session/proxy state contracts), §3.9 (resume across path boundaries), §3.14 (activity/cost
planes), design_appendix.md §B (direct command scope policy), §L (subprocess routing)

## Summary

**Workspace** is the Forge scoping concept for a Git worktree family:

```text
Forge workspace =
  the primary Git worktree
  plus all linked Git worktrees that share the same git common directory
```

Claude Code has no such concept — native sessions are scoped to a project path/CWD, so a native `--resume <uuid>` lookup
is path-bound. Forge reasons across those paths from higher-level state: session index entries carry `project_root`,
`checkout_root`, `forge_root`, and `relative_path`, and Git tells us which worktrees belong together.

The **named query scope already shipped**: `--scope workspace` (filtering by `project_root`) is live across
`session list` / `clean` / `memory`, and Slice 1 made `project_root` consistent so it groups every worktree of a repo
(including manually-created ones). This card now proposes the remaining piece — a read-only **`forge workspace`
surface** that joins `git worktree list` with the session index. That is the one thing the index alone cannot do: it
only knows worktrees that *have* sessions, not empty or prunable ones. Workspace stays a derived query, never a
user-created persisted entity.

## Motivation

Users think about work at the repository/worktree-family level. Status of each need after the shipped precursors:

- "Which Forge sessions are running in those worktrees?" — **shipped** (`session list --scope workspace`; correct for
  manual worktrees after Slice 1).
- "What active worktrees do I have for this repo?" — **remaining**: the index only knows worktrees that *have* sessions;
  listing empty or prunable worktrees needs the `git worktree list` join.
- "What did Forge automation spend across this whole workspace?" — **partial**: `forge activity` is per-session today;
  `--scope workspace` aggregation is part of this slice.
- "Which sessions exist in this worktree family, including deleted or inactive checkouts?" — **partial**: grouping
  works, but the "live worktree vs historical session" distinction needs the git join.

The cross-worktree umbrella now has a clear user-facing name ("workspace") while `forge_root` stays the path-local
install root. What is missing is a surface that *shows* the worktree family, not just one that filters sessions by it.

## Proposed Definition

Workspace membership is derived from Git, not stored by Forge:

```text
current path
  -> git common dir
  -> git worktree list --porcelain
  -> primary worktree + linked worktrees
```

Suggested runtime shape:

```python
@dataclass(frozen=True)
class Workspace:
    workspace_id: str       # stable derived key, e.g. hash(realpath(git common-dir))
    primary_root: Path      # main worktree path from git worktree metadata
    common_dir: Path        # git common dir, not display-oriented
    worktrees: tuple[WorkspaceWorktree, ...]

@dataclass(frozen=True)
class WorkspaceWorktree:
    checkout_root: Path
    branch: str | None
    head: str | None
    is_primary: bool
    is_prunable: bool
```

The global session index keeps using the existing `project_root` field as the workspace grouping key. **Decision (Q2):
do not add persisted `workspace_id` / `workspace_root` fields.** Slice 1 already made `project_root` a reliable
git-common-dir anchor in every entry; a persisted `hash(common-dir)` would duplicate it and go stale on
`git worktree move`. Workspace identity is derived at query time:

```text
workspace_id        derived at query time from git common-dir (NOT stored)
workspace_root      primary worktree path from git metadata, for display (NOT stored)
project_root        stored grouping key (= main-repo root; already in the index)
checkout_root       one concrete Git worktree (stored)
forge_root          path-local Forge install inside that checkout (stored)
session_name        Forge session (stored)
claude_session_id   native Claude conversation binding, if launched (stored)
```

## CLI / UX Sketch

Workspace as a scope and read surface (commands marked shipped vs proposed):

```bash
forge session list --scope workspace   # SHIPPED
forge activity --scope workspace        # proposed (activity has no --scope today)
forge workspace worktrees               # proposed (Slice 2 — the git-worktree-list join)
forge workspace sessions                # proposed (Slice 2)
forge workspace status                  # proposed (Slice 2)
```

Potential status output:

```text
Workspace: /repo/main

Worktrees:
  main        /repo/main                    2 sessions, 1 active
  feature-a   /repo/.worktrees/feature-a     1 session, inactive
  review-b    /repo/.worktrees/review-b      3 sessions, 2 active

Activity:
  reported cost: $1.42
  unavailable cost events: 8
  workflows: 12
```

`forge proxy costs show --scope workspace` is tempting but needs sharper naming: proxy cost logs are proxy-owned and
global, while workspace activity is session-attributed via the usage ledger. The first implementation should probably
route workspace cost questions through `forge activity --scope workspace` unless a reliable request/session attribution
join is available.

## Relationship To Existing Concepts

| Concept               | Current meaning                                               | Workspace relationship                                                          |
| --------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Claude Code project   | Native conversation namespace tied to path/CWD                | One workspace can contain many Claude project paths                             |
| Claude native session | Runtime conversation UUID, path-scoped resume lookup          | Bound to a Forge session when launched                                          |
| Forge session         | Named, file-backed workflow state under a `forge_root`        | Indexed and queryable across a workspace                                        |
| `checkout_root`       | One Git worktree checkout                                     | Workspace member                                                                |
| `forge_root`          | Path-local `.forge/` + `.claude/` install root                | May appear in one or more workspace members                                     |
| `project_root`        | Logical-repo identity in the session index (= main-repo root) | Stored workspace grouping key; field kept, user-facing name is "workspace" (Q1) |

## Implementation Approach

**Slice 1 — `project_root` consistency (SHIPPED 2026-06-07, see change_log).** `start_session` and the same-directory
`fork` path now derive `project_root` via `resolve_project_root()` (`get_main_repo_root`), so every worktree of a repo —
including manually-created ones — shares one grouping key. Regression:
`tests/regression/test_bug_workspace_scope_manual_worktree.py`. This made the existing `--scope workspace` filter
correct and is the foundation the read surface builds on.

**Slice 2 — the `forge workspace` read surface (proposed):**

1. Add a Git-derived resolver (`forge.session.workspace`) that shells out to Git: `rev-parse --git-common-dir`,
   `worktree list --porcelain`, `rev-parse --show-toplevel`. Returns the `Workspace` / `WorkspaceWorktree` shapes above.
2. Normalize with resolved absolute paths; do not use path-prefix membership (linked worktrees can live anywhere).
3. Join `git worktree list` (live worktrees, including empty/prunable) with the session index grouped by `project_root`
   (Slice 1 made this reliable). Distinguish live worktrees from historical sessions whose checkout is gone.
4. Join active session state from `~/.forge/sessions/active.json` for the "N active" counts.
5. For `forge activity --scope workspace`, aggregate usage-ledger events for sessions resolved into the workspace;
   surface coverage caveats when emitters lack session attribution (inherits the documented `cost_partial` /
   `session_tagging_partial` limits).
6. Read-only. No `forge workspace create`, no user-managed membership.

## Design Principles

- **Git owns membership**: `git worktree list` is the source of truth for active worktrees.
- **Forge owns overlays and attribution**: sessions, active-state, artifacts, and usage are Forge state.
- **Workspace is a scope, not a database row**: no persisted membership file until user-owned metadata is needed.
- **Historical state is allowed to outlive worktrees**: a deleted checkout may still have indexed Forge sessions or
  artifacts; the UI should distinguish "live worktree" from "historical session."
- **No path-prefix shortcuts**: worktrees can be outside the primary checkout tree.

## Open Questions

1. Should the current `project_root` field be renamed in docs/code to `workspace_root` or kept as the compatibility
   storage name with user-facing docs saying "workspace"?
   - **Partially resolved (2026-06-07)**: the user-facing `--scope repo` value was renamed to `--scope workspace` (clean
     break, across `session list` / `clean` / `memory` / `%clean` / `%session`; see change_log). Per-the-less-invasive
     option, the durable `project_root` field is **kept** (workspace membership is derived from it, not stored) and the
     internal `resolve_session_repo_wide` symbol is unchanged. A full field/symbol rename remains open and is only worth
     it alongside Slice 2 (the `forge workspace` resolver), if at all.
2. ~~Should `workspace_id` be persisted in the global session index?~~ **Resolved (2026-06-07): derive at query time, do
   not persist.** Slice 1 made `project_root` a reliable git-common-dir anchor already in every entry; a persisted
   path-hash would duplicate it and go stale on `git worktree move`. Consistent with "workspace is a scope, not a
   database row."
3. ~~How should workspace queries behave outside a Git repository?~~ **Resolved (2026-06-07): ambient single-directory
   workspace (degrade, do not error).** Slice 1's `resolve_project_root()` already degrades to the directory itself for
   non-git paths, and the status line's "no session -> no segment" posture is the house style; a read command erroring
   outside git would be hostile.
4. Should a workspace have optional persisted overlay metadata later (`display_name`, default policy bundles, preferred
   subprocess proxy), and if so where should it live?
5. How much deleted-worktree history should `forge workspace status` show by default?

## Out Of Scope

- Creating or registering workspaces manually.
- Grouping unrelated Git repositories into one workspace.
- Changing Claude Code's native project/session storage.
- Making native resume cross worktree boundaries. Transfer remains Forge's cross-boundary context substrate.
- Workspace-level policy defaults or memory activation. These may become overlay metadata later, but should not be part
  of the first scope/query slice.
- Renaming the `project_root` field or the `resolve_session_repo_wide` symbol (Q1 deferred). Slice 2 is a read-only
  surface over the existing field.
