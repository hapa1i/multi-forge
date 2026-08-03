# Workspace Scope — `forge workspace` read surface (Slice 2)

**Status**: Doing. Accepted for execution on `feat/workspace-scope-slice2` (2026-08-03). Two precursors shipped on branch
`fix/workspace-scope` (2026-06-07, see change_log): (1) the `--scope repo` → `--scope workspace` rename resolving review
concern #1, and (2) **Slice 1** — `project_root` is now consistently `get_main_repo_root()`-derived, so sessions in
manually-created linked worktrees group under `--scope workspace`. Slice 1 makes the core session-grouping query correct
with no new surface; what remains (this card) is the net-new `forge workspace worktrees` read surface that joins
`git worktree list` with the session index (`status` deferred — see CLI / UX Sketch).

**Re-verified 2026-08-03** against current `main`, then corrected the same day by two adversarial review rounds:
`session list` and `clean` default to `--scope workspace` (`%clean` defaults to `project`); `memory shadows` and
`session memory status` carry the scope; `telemetry activity` still has no `--scope`. Dated adjustments inline: the
index self-heals rows whose worktree vanished (deleted-checkout "history" is git-derived, never index state),
`codex_thread_id` joined the session index (adoption), `forge workspace sessions` is dropped as a duplicate surface,
`workspace status` **and activity aggregation are deferred** behind root-scoped telemetry identity, the derived
`workspace_id` hash key is dropped, worktree availability is point-in-time (`path_exists`, shown as `missing` — git
never marks a locked worktree prunable; probed live), and bare-backed families are render-only (see Proposed
Definition).

**References**: design.md §3 (session/proxy state contracts; §3.2 contract files), §3.9 (resume across path boundaries),
§3.14 (activity/cost planes), cli_reference.md §2 (direct command scope policy), design_appendix.md §G (subprocess
routing), §A.13 (activity read surface)

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
- "What did Forge automation spend across this whole workspace?" — **deferred (2026-08-03)**: activity/ledger queries
  filter by session *name* only, and names are project-scoped (they collide across Forge roots —
  `core/ops/usage_summary.py`'s known-limitation note defers root-scoped ledger identity to a future card). Summing
  per-session summaries would bleed in an out-of-workspace same-named session and double-count same-named workspace
  siblings. Aggregation waits for root-scoped telemetry identity; see Implementation Approach item 5.
- "Which checkouts in this family are live, empty, or gone?" — **partial**: grouping works, but the live-vs-prunable
  distinction needs the git join. (Adjusted 2026-08-03: the index cannot answer deleted-checkout history —
  `IndexStore.list_sessions` self-heals rows whose worktree or manifest is missing, so sessions do not outlive their
  checkout in the index. Git's prunable-worktree metadata is the only durable trace of a deleted checkout.)

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
    primary_root: Path       # main worktree path from git worktree metadata
    common_dir: Path | None  # git common dir; None outside git (single-directory degrade)
    worktrees: tuple[WorkspaceWorktree, ...]

@dataclass(frozen=True)
class WorkspaceWorktree:
    checkout_root: Path
    branch: str | None       # short name; None when detached
    head: str | None
    is_primary: bool         # git's first porcelain record (may be a bare repo)
    is_bare: bool
    is_prunable: bool        # git's annotation; git never marks a locked worktree prunable
    is_locked: bool
    is_detached: bool
    path_exists: bool        # point-in-time availability ("missing", never "gone": a locked worktree
                             # on unmounted portable media is missing by design, not deleted)
```

**Bare-backed families are render-only (2026-08-03).** In a family anchored on a bare repository, git's first porcelain
record is the bare repo itself (`is_bare=True`, no HEAD/branch — probed live); the parser keeps git's
first-record-primary contract. The identity guarantee `primary_root == get_main_repo_root()` is scoped to **non-bare**
families: probed 2026-08-03, `get_main_repo_root()` in a bare family falls back to `get_repo_root(cwd)` (the linked
checkout you stand in), so even Slice-1 `project_root` grouping is per-checkout there. The surface still renders the
full git family; session counts in bare families are per-checkout until Slice-1 grouping is extended.

The global session index keeps using the existing `project_root` field as the workspace grouping key. **Decision (Q2):
do not add persisted `workspace_id` / `workspace_root` fields.** Slice 1 already made `project_root` a reliable
git-common-dir anchor in every entry; a persisted `hash(common-dir)` would duplicate it and go stale when the main
repository itself is relocated (probed 2026-08-03: a linked `git worktree move` leaves the common dir unchanged).
Workspace identity is derived at query time:

```text
workspace identity  resolved common dir + primary root, derived at query time (NOT stored, NOT hashed —
                    2026-08-03: the exported hash key was dropped; pin sha256 later only if a consumer
                    ever needs a stable key, since a path-derived hash is relocation-unstable anyway)
project_root        stored grouping key (= main-repo root; already in the index)
checkout_root       one concrete Git worktree (stored)
forge_root          path-local Forge install inside that checkout (stored)
session_name        Forge session (stored)
claude_session_id   native Claude conversation binding, if launched (stored)
codex_thread_id     native Codex thread binding, if run or adopted (stored; mirrors confirmed.codex.thread_id)
```

## CLI / UX Sketch

Workspace as a scope and read surface (commands marked shipped vs proposed):

```bash
forge session list --scope workspace         # SHIPPED
forge workspace worktrees                    # proposed (Slice 2 — the git-worktree-list join)
forge workspace status                       # DEFERRED — ships with activity aggregation (see below)
forge telemetry activity --scope workspace   # DEFERRED — blocked on root-scoped telemetry identity
```

Two surfaces were cut on 2026-08-03 for one-surface-per-question reasons. `forge workspace sessions` would duplicate the
shipped `forge session list --scope workspace` (`worktrees` carries the per-worktree session counts). `status` is
deferred *with* the activity aggregation: until an Activity block exists it answers nothing `worktrees` does not, so it
ships only when aggregation gives it distinct content. `workspace` is a new top-level group with no alias (D6 alias
policy, `cli_style_guidelines.md`), starting with the single `worktrees` leaf.

Potential `worktrees` output (Slice 2):

```text
Workspace: /repo/main

Worktrees:
  main        /repo/main                    2 sessions, 1 active
  feature-a   /repo/.worktrees/feature-a    1 session
  review-b    /repo/.worktrees/review-b     missing (prunable)
  hotfix-c    /repo/.worktrees/hotfix-c     missing (locked)
```

The deferred `status` is this view plus an Activity block. When it lands, cost keeps activity's reported-or-estimated
semantics (`cost_estimated` / `cost_partial` on the pane — there is no per-event "unavailable count", and reported-only
totals are `forge +$Y` vocabulary, not activity's):

```text
Activity:
  cost: ~$1.42 (reported-or-estimated; partial)
  workflows: 12
```

`forge telemetry costs show --scope workspace` is tempting but needs sharper naming: proxy cost logs are proxy-owned and
global, while workspace activity is session-attributed via the usage ledger. The first implementation should probably
route workspace cost questions through `forge telemetry activity --scope workspace` unless a reliable request/session
attribution join is available.

## Relationship To Existing Concepts

| Concept               | Current meaning                                               | Workspace relationship                                                          |
| --------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Claude Code project   | Native conversation namespace tied to path/CWD                | One workspace can contain many Claude project paths                             |
| Claude native session | Runtime conversation UUID, path-scoped resume lookup          | Bound to a Forge session when launched or adopted                               |
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
   Porcelain parsing becomes single-sourced here: the only in-tree reader today is the two-key scan in
   `session/worktree/create.py::get_worktree_for_branch`, which should be repointed through the new parser. Pinned
   parser rules: `--porcelain -z` (NUL-robust paths), the first entry is the primary worktree (git's contract), `branch`
   stores the short name (the full `refs/heads/…` ref is matched internally), attribute reasons (`locked <reason>`,
   `prunable <reason>`) are ignored in v1, unknown attributes are skipped, and `path_exists` is derived independently of
   git's flags. Failure taxonomy: only not-a-repo degrades (Q3's single-directory workspace); a missing git binary, a
   failing git subprocess, or malformed porcelain fails loud with a clear error — subprocess output is a system boundary
   on this command's critical path.
2. Normalize with resolved absolute paths; do not use path-prefix membership (linked worktrees can live anywhere).
3. Join `git worktree list` (every registered worktree — empty, missing, and prunable included) with the session index
   grouped by `project_root` (Slice 1 made this reliable). Availability is point-in-time and two-fact (re-adjusted
   2026-08-03): `path_exists` says whether the directory is there right now (rendered `missing`), and `is_prunable` is
   git's own annotation — independent facts, since git never marks a locked worktree prunable. Index history contributes
   nothing: the list-time self-heal prunes rows whose worktree/manifest vanished, and `forge session repair` keeps
   `missing-worktree` manifests report-only, so a surviving index row always has an existing checkout. Going through
   `core.ops.session.list_sessions` inherits that prune — read-time repair of the derived global index is already
   compatibility-exempt (design.md §3).
4. Join active session state from `~/.forge/sessions/active.json` for the "N active" counts — via the shipped seams:
   `core.ops.session.list_sessions` already returns `ListSessionsItem.is_active`, wired to `ActiveSessionStore.is_live`.
   No new liveness probing.
5. ~~Activity aggregation~~ **Deferred (2026-08-03) — blocked, not merely separable.** Ledger and upstream activity
   queries filter by session *name* only, and names are project-scoped (`core/ops/usage_summary.py`'s known-limitation
   note defers root-scoped ledger identity to a future card). Summing `build_session_activity_summary(...)` per name
   would bleed in an out-of-workspace same-named session and double-count same-named workspace siblings.
   `forge telemetry activity --scope workspace` and the `status` leaf return as a follow-up once telemetry carries
   root-scoped session identity; that follow-up also owns the `--scope` value vocabulary (workspace-only vs the standard
   `project|workspace|all`) and keeps activity's reported-or-estimated cost semantics.
6. Read-only. No `forge workspace create`, no user-managed membership.

## Design Principles

- **Git owns membership**: `git worktree list` is the source of truth for active worktrees.
- **Forge owns overlays and attribution**: sessions, active-state, artifacts, and usage are Forge state.
- **Workspace is a scope, not a database row**: no persisted membership file until user-owned metadata is needed.
- **Historical artifacts may outlive worktrees; index rows do not** (adjusted 2026-08-03): artifacts, transfer caches,
  and search documents under a surviving `forge_root` can outlive a checkout, but the session index self-heals rows
  whose worktree or manifest is gone. The UI shows two independent point-in-time facts — `missing` (`path_exists` is
  false right now; a locked worktree on unmounted media is missing by design, not deleted) and `prunable` (git's own
  annotation, never set on locked worktrees even after `prune --expire=now` — probed 2026-08-03) — and never fabricates
  session history for a deleted checkout.
- **No path-prefix shortcuts**: worktrees can be outside the primary checkout tree.

## Open Questions

1. Should the current `project_root` field be renamed in docs/code to `workspace_root` or kept as the compatibility
   storage name with user-facing docs saying "workspace"?
   - **Partially resolved (2026-06-07)**: the user-facing `--scope repo` value was renamed to `--scope workspace` (clean
     break, across `session list` / `clean` / `memory` / `%clean` / `%session`; see change_log). Per-the-less-invasive
     option, the durable `project_root` field is **kept** (workspace membership is derived from it, not stored) and the
     internal `resolve_session_repo_wide` symbol is unchanged (`core/ops/resolution.py`). A full field/symbol rename
     remains open and is only worth it alongside Slice 2 (the `forge workspace` resolver), if at all.
2. ~~Should `workspace_id` be persisted in the global session index?~~ **Resolved (2026-06-07): derive at query time, do
   not persist.** Slice 1 made `project_root` a reliable git-common-dir anchor already in every entry; a persisted
   path-hash would duplicate it and go stale when the main repository is relocated (a linked `git worktree move` leaves
   the common dir unchanged — probed 2026-08-03). Consistent with "workspace is a scope, not a database row."
3. ~~How should workspace queries behave outside a Git repository?~~ **Resolved (2026-06-07): ambient single-directory
   workspace (degrade, do not error).** Slice 1's `resolve_project_root()` already degrades to the directory itself for
   non-git paths, and the status line's "no session -> no segment" posture is the house style; a read command erroring
   outside git would be hostile.
4. Should a workspace have optional persisted overlay metadata later (`display_name`, default policy bundles, preferred
   subprocess proxy), and if so where should it live?
5. ~~How much deleted-worktree history should `forge workspace status` show by default?~~ **Resolved (2026-08-03): none
   exists to show.** The index self-heals rows whose worktree or manifest vanished (`session/index.py` list-time prune),
   and `forge session repair` keeps `missing-worktree` manifests report-only — deleted-checkout sessions are not durable
   index state. The read surface shows point-in-time facts only — `prunable` entries (metadata surviving until
   `git worktree prune`) and currently `missing` paths (including locked worktrees, which `prune` skips and git never
   marks prunable) — and stops there.

## Out Of Scope

- Creating or registering workspaces manually.
- Grouping unrelated Git repositories into one workspace.
- Changing Claude Code's native project/session storage.
- Making native resume cross worktree boundaries. Transfer remains Forge's cross-boundary context substrate.
- Workspace-level policy defaults or memory activation. These may become overlay metadata later, but should not be part
  of the first scope/query slice.
- Workspace activity aggregation and `forge workspace status` (deferred 2026-08-03; blocked on root-scoped telemetry
  identity — see Implementation Approach item 5).
- A `%workspace` direct-command mirror. The `%` scope policy (cli_reference.md §2.1) is unchanged by this slice; a
  read-only mirror can follow if in-session demand shows up.
- Renaming the `project_root` field or the `resolve_session_repo_wide` symbol (Q1 deferred). Slice 2 is a read-only
  surface over the existing field.
