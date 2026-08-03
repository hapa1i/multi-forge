# Checklist — Workspace Scope Slice 2 (`forge workspace worktrees`)

Drafted 2026-08-03 while the card sat in `proposed/` (checklist-first review), revised the same day across two
adversarial review rounds. Round 2: activity aggregation and `forge workspace status` deferred as **blocked** (not
merely separable); single `worktrees` leaf; parser and non-Git shapes pinned; `workspace_id` dropped; integration gate
added. Round 3: `missing` is point-in-time availability (never "gone"); bare-backed families are render-only;
incognito/legacy-row counting pinned; integration gates routed through `./scripts/test-integration.sh`; a discriminating
newline-path fixture replaces the space-path one; cross-card ownership repoint added to closeout. Picked up on
`feat/workspace-scope-slice2` and moved to `doing/` on 2026-08-03.

## Current focus

Implementation and verification complete; pending merge and the post-merge lane move.

## Phase 0 — Decisions to confirm at review (no code)

The 2026-08-03 card adjustments encode these; confirming them closes Phase 0.

- [x] D1: `forge workspace sessions` stays dropped — duplicate of the shipped `forge session list --scope workspace`;
  `worktrees` carries per-worktree session counts.
- [x] D2: the slice ships **one leaf**: top-level `workspace` group (no alias, D6 alias policy in
  `cli_style_guidelines.md`) with `worktrees` (`--json`). `forge workspace status` is deferred with the activity
  aggregation — until an Activity block exists it answers nothing `worktrees` does not. The command-tree invariant's
  narrow `forge workspace` exception records this deliberate debt until a distinct second leaf can ship.
- [x] D3: activity aggregation is deferred out of this card as **blocked**: ledger/upstream activity queries filter by
  session *name* only while names are project-scoped (`core/ops/usage_summary.py` defers root-scoped ledger identity to
  a future card), so workspace sums can bleed in an out-of-workspace same-named session and double-count same-named
  siblings. When the follow-up lands, cost keeps activity's reported-or-estimated semantics (`cost_estimated` /
  `cost_partial`); reported-only totals remain `forge +$Y` vocabulary.
- [x] D4: module placement — parser + resolver in `src/forge/session/workspace.py`; UI-agnostic join builder in
  `src/forge/core/ops/workspace.py` (ops contract, design.md §3.12: no Click, no printing, typed errors; precedent:
  op-backed `telemetry trace` with no `%` mirror); CLI leaf in `src/forge/cli/workspace.py`.
- [x] D5: no `workspace_id`. Identity is the resolved common dir + primary root, derived at query time; no exported hash
  key (a path-derived hash goes stale on main-repo relocation — a linked `git worktree move` leaves the common dir
  unchanged, probed 2026-08-03; pin sha256 later only if a consumer needs a stable key).
- [x] D6: availability vocabulary — `path_exists` is **point-in-time**; the UI word is `missing`, never "gone" (git
  documents locking worktrees on portable/network media, so locked+missing can be intentional and implies no deletion).
  `missing` and `prunable` are independent facts, rendered as `missing (locked)` / `missing (prunable)`.
- [x] D7: bare-backed families are **render-only**: the parser keeps git's first-record-primary contract (the bare repo
  itself, `is_bare=True`); the identity assertion `primary_root == get_main_repo_root()` is scoped to non-bare families
  (probed 2026-08-03: in a bare family `get_main_repo_root()` falls back to `get_repo_root(cwd)`, so Slice-1
  `project_root` grouping is per-checkout there — session counts inherit that limit, documented, not silently wrong).
- [x] D8: session counts use `include_incognito=True` — occupancy semantics (an incognito session is a live worktree
  occupant even if listings can filter it); no surface flag in v1.
- [x] D9: legacy index rows — the join's group key is `entry.checkout_root or entry.worktree_path` (the established
  `SessionIndexEntry.root` fallback idiom; supported rows may carry `checkout_root=""` with only `worktree_path`).

## Phase 1 — Git-derived workspace resolver (`session/workspace.py`)

- [x] Frozen dataclasses per the card sketch: `Workspace(primary_root, common_dir: Path | None, worktrees)`;
  `WorkspaceWorktree(checkout_root, branch, head, is_primary, is_bare, is_prunable, is_locked, is_detached, path_exists)`.
- [x] Parser pinned to `git worktree list --porcelain -z` (attributes NUL-terminated; two consecutive NULs separate
  entries): first entry is the primary record (git's contract — a bare repo in bare-backed families); `branch` stores
  the short name (full `refs/heads/…` matched internally); `locked`/`prunable`/`detached`/`bare` recognized with
  attribute reasons ignored in v1; unknown attributes skipped (forward-compatible). Assertion: a repo with primary +
  linked + locked + detached + dir-deleted worktrees parses into exactly those flags.
- [x] Discriminating `-z` fixture: a worktree path containing an **embedded newline** (POSIX-legal; this is the case the
  current line-based scan cannot represent — a space does not discriminate) round-trips through the parser.
- [x] `path_exists` derived independently of git flags (probe-backed contract, 2026-08-03): a **locked** worktree whose
  directory was moved away reports `is_locked=True, is_prunable=False, path_exists=False` — and survives
  `git worktree prune --expire=now`; a plain deleted worktree reports `is_prunable=True, path_exists=False` and is
  removed by that prune. Assertion: both states, before and after prune.
- [x] Failure taxonomy pinned: not-a-repo → single-directory degrade (Q3) and nothing else degrades; missing git binary
  → clear loud error; `git worktree list`/`rev-parse` non-zero or malformed porcelain → clear loud parse error
  (subprocess output is a system boundary on this command's critical path). Assertion per case.
- [x] Workspace identity derived at query time via `rev-parse --path-format=absolute --git-common-dir`. Assertion
  (non-bare families): resolver run from the primary checkout and from a linked worktree returns equal `common_dir` and
  `primary_root`, and `primary_root == get_main_repo_root()` for the same cwd.
- [x] Bare-family fixture (D7): `git init --bare` + linked worktree → no crash; first record
  `is_bare=True, is_primary=True`, no branch/head requirement; linked rows normal. The identity assertion is explicitly
  not applied.
- [x] Non-git degrade pinned (card Q3): `Workspace(primary_root=<resolved dir>, common_dir=None, worktrees=(` one
  member: `checkout_root=<dir>, branch=None, head=None, is_primary=True`, all flags `False`, `path_exists=True))`.
  Assertion: `tmp_path` without git → exactly that shape, nothing raised.
- [x] Path normalization: `Path.resolve()` on existing paths; a missing path keeps git's recorded spelling with
  `path_exists=False`; no path-prefix membership tests. Assertion: a worktree reached through a symlinked path still
  matches its index `checkout_root`.
- [x] Porcelain parsing single-sourced: characterize `session/worktree/create.py::get_worktree_for_branch` (first
  worktree carrying `branch refs/heads/<name>`), then repoint it through the new parser. Assertion: existing
  `tests/src/session/worktree/test_create.py` coverage passes unchanged.
- [x] Extend the CIT for the repointed production path: a branch **checked out in a second real worktree** makes
  `create_worktree` raise `BranchExistsError` carrying that worktree's path (the existing test only asserts the branch
  name; this drives `get_worktree_for_branch` end-to-end through the new parser).
- [x] **Integration gate (required; runner-invoked)**: the repoint touches the session fork/worktree branch-refusal path
  (`get_worktree_for_branch` call in `session/worktree/create.py`), and
  `tests/src/session/worktree/test_create_integration.py` is `integration` + `docker_in` marked — so both gates go
  through the prescribed runner, not direct pytest:
  `./scripts/test-integration.sh tests/src/session/worktree/test_create_integration.py tests/integration/docker/test_session_lifecycle.py -v`
  green before Phase 1 closes.

## Phase 2 — Index/active join + `forge workspace worktrees`

- [x] `core/ops/workspace.py` builder joins resolver output with
  `core.ops.session.list_sessions(scope="workspace", include_incognito=True)` (D8), grouping items by
  `item.entry.checkout_root or item.entry.worktree_path` (D9; each `ListSessionsItem` carries its full
  `SessionIndexEntry`); rows are counted, never merged by name; `active` counts come from the shipped
  `ListSessionsItem.is_active` (`ActiveSessionStore.is_live` underneath). No new liveness probing. Assertion: a worktree
  with zero sessions appears with `sessions=0`; an active-store live entry flips its worktree's active count; a legacy
  row with `checkout_root=""` and populated `worktree_path` lands under the right worktree; an incognito session is
  counted.
- [x] Name-collision honesty (the class that deferred aggregation): two same-named sessions in different Forge roots of
  **one** workspace appear under their own worktrees as two counted rows; a same-named session in a **different**
  workspace is excluded by the `project_root` filter. Assertions for both fixtures.
- [x] Availability facts rendered per D6: after `rm -rf <linked-worktree>` (no `git worktree prune`), the row shows
  `missing (prunable)` with `sessions=0` — the list-time self-heal pruned its index rows — and the builder does not
  error on rows vanishing mid-join; a locked worktree with a missing directory shows `missing (locked)`, not prunable.
- [x] CLI shape: bare `forge workspace` prints help (non-leaf orients); `worktrees` renders through the call-site
  `console`; recovery output only via `forge.cli.output` helpers (the `Tip:` / `[red]Error:[/red]` source guards apply);
  errors on stderr.
- [x] `--json` pinned (single schema; counts, not collections — session names remain
  `forge session list --scope workspace`'s job): top-level `primary_root`, `common_dir` (`null` outside git), and
  `worktrees[]` rows carrying `checkout_root`, `branch`, `head`, `is_primary`, `is_bare`, `is_prunable`, `is_locked`,
  `is_detached`, `path_exists`, `sessions` (count), `active` (count).
- [x] Group registered in `cli/main.py` with no alias; `test_command_tree_invariants.py` extended for the new group.
- [x] No project-compatibility gating added: read-only surface; the embedded list prune is the already-exempt read-time
  repair of the derived global index (design.md §3).

## Phase 3 — Docs, QA, closeout

- [x] cli_reference.md §1: new Workspace command table (`worktrees` only; `status` and the activity `--scope` are not
  documented as available).
- [x] design.md: a sentence in §3.2 "Session command scoping" naming the read surface; §6 directory map gains
  `session/workspace.py`.
- [x] docs/end-user/session.md: short workspace section (what `--scope workspace` groups, what `worktrees` shows,
  `missing`/`prunable` semantics, bare-family boundary).
- [x] QA checklist: new `### N.X` items for `forge workspace worktrees` (`<!-- auto -->` where assertable); bump
  `test-count` / `last-updated` in `src/skills/qa/resources/checklist.md`.
- [x] **Cross-card ownership repoint**: `docs/board/done/forge_cli_cleanup/checklist.md` (D9, ~line 180) says workspace
  telemetry aggregation is owned by this card; since this card defers it, update that line at closeout to point at this
  card's Deferred section — or at the successor card if one is created — so the inbound contract stays true.
- [x] `docs/board/change_log.md` entry (feature size, 15–25 lines); durable lessons proposed via
  `.forge/memory/shadow_impl_notes.md`, not written directly to `impl_notes.md`.
- [x] Closeout records the deferral: the blocked aggregation/`status` work is either left on this card's Deferred
  section or split to a new `proposed/` card at the user's call.
- [ ] Lane move `doing/ → done/` after merge; inbound board links repointed (board-contract closeout).

## Verification record — 2026-08-03

- Focused resolver/join/CLI/session suite: 83 passed.
- Required runner:
  `./scripts/test-integration.sh tests/src/session/worktree/test_create_integration.py tests/integration/docker/test_session_lifecycle.py -v`
  — 37 passed.
- `make test-unit` — 8,682 passed, 1 skipped, 117 integration tests deselected.
- `make pre-commit` — all hooks passed, including ruff, black, isort, mypy, pyright, mdformat, and gitleaks.

## Deferred — activity aggregation + `forge workspace status` (blocked, with anchors)

Not scheduled in this slice; recorded so the blockers are re-checkable:

1. **Identity**: ledger and upstream activity queries filter by session name only; names are project-scoped
   (`src/forge/session/index.py` module docstring), and `src/forge/core/ops/usage_summary.py` explicitly defers
   root-scoped ledger identity to a future card. Until telemetry carries root-scoped session identity, workspace sums
   bleed and double-count.
2. **Cost semantics**: the activity pane exposes `cost_partial`/`cost_estimated` booleans, not an unavailable-event
   count, and deliberately preserves reported-or-estimated totals; a workspace view must keep those semantics rather
   than mint a reported-only vocabulary (that is `forge +$Y`'s contract).
3. The follow-up owns the `--scope` value vocabulary for activity (workspace-only vs `project|workspace|all`) and
   whatever JSON discriminator distinguishes the workspace shape from today's per-session object (which has none).
4. Inbound ownership: `done/forge_cli_cleanup/checklist.md` D9 currently points here; the Phase-3 repoint item keeps
   that link truthful.

## Acceptance tests

| Test                                  | Fixture                                                                                           | Assertion                                                                                                     | Test File                                               |
| ------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| Porcelain parse, full flag set        | tmp git repo + `git worktree add`: linked, locked, detached, dir-deleted                          | exact `is_primary`/`is_bare`/`is_prunable`/`is_locked`/`is_detached`; branch short-name/head populated        | `tests/src/session/test_workspace.py`                   |
| Newline path under `-z`               | worktree path with embedded newline                                                               | path round-trips exactly (discriminates NUL parser from line scan)                                            | `tests/src/session/test_workspace.py`                   |
| Locked-vs-prunable probe contract     | lock one worktree, `mv` its dir; `rm -rf` another; before/after `git worktree prune --expire=now` | locked: `is_prunable=False`, `path_exists=False`, survives prune; plain: `is_prunable=True`, removed by prune | `tests/src/session/test_workspace.py`                   |
| Failure taxonomy                      | no git binary on PATH; corrupted porcelain bytes; failing subprocess                              | loud clear errors; only not-a-repo degrades                                                                   | `tests/src/session/test_workspace.py`                   |
| Bare family render-only               | `git init --bare` + linked worktree                                                               | first record `is_bare=True`/`is_primary=True`; no crash; identity assertion not applied                       | `tests/src/session/test_workspace.py`                   |
| Identity stable across members        | non-bare repo, resolver run from primary and linked cwd                                           | equal `common_dir` + `primary_root`; equals `get_main_repo_root()`                                            | `tests/src/session/test_workspace.py`                   |
| Non-git degrade, exact shape          | `tmp_path`, no git                                                                                | pinned single-member shape (`common_dir=None`, flags false, `path_exists=True`), no raise                     | `tests/src/session/test_workspace.py`                   |
| Symlinked path join                   | symlink to linked worktree; session indexed via real path                                         | worktree row shows the session                                                                                | `tests/src/core/ops/test_workspace.py`                  |
| Empty worktree visible                | linked worktree, no sessions                                                                      | row present, `sessions=0`                                                                                     | `tests/src/core/ops/test_workspace.py`                  |
| Legacy row fallback                   | index row with `checkout_root=""`, `worktree_path` set                                            | counted under the right worktree (D9)                                                                         | `tests/src/core/ops/test_workspace.py`                  |
| Incognito counted                     | incognito session in a worktree                                                                   | included in `sessions`/`active` (D8)                                                                          | `tests/src/core/ops/test_workspace.py`                  |
| Same-name, same workspace             | same session name in two Forge roots of one repo                                                  | two rows, counts separate, no merge                                                                           | `tests/src/core/ops/test_workspace.py`                  |
| Same-name, other workspace            | same session name in a second repo                                                                | excluded by `project_root` filter                                                                             | `tests/src/core/ops/test_workspace.py`                  |
| Missing after deletion                | `rm -rf` linked worktree, no prune                                                                | `missing (prunable)`, `sessions=0`, no error mid-join                                                         | `tests/src/core/ops/test_workspace.py`                  |
| Active counts                         | index rows + seeded `ActiveSessionStore`                                                          | `active` matches `is_active` truth                                                                            | `tests/src/core/ops/test_workspace.py`                  |
| CLI JSON shape                        | CliRunner, seeded index                                                                           | pinned keys for `worktrees --json` (incl. `is_bare`)                                                          | `tests/src/cli/test_workspace_commands.py`              |
| Group shape + no alias                | CliRunner                                                                                         | bare `forge workspace` prints help, exit 2 per CLI group policy; no alias resolves                            | `tests/src/cli/test_command_tree_invariants.py`         |
| `get_worktree_for_branch` unchanged   | existing fixtures                                                                                 | characterized before repoint, green after                                                                     | `tests/src/session/worktree/test_create.py`             |
| Branch checked out in second worktree | real second worktree on the branch                                                                | `BranchExistsError` carries that worktree's path (parser exercised on the production path)                    | `tests/src/session/worktree/test_create_integration.py` |

Unit tests use real tmp git repos (`git init` + `git worktree add`) per the real-over-mock policy — host-only. The
Phase-1 parser repoint touches session fork/worktree machinery, and the component gate file is `integration` +
`docker_in` marked, so both integration gates run through `./scripts/test-integration.sh` (see Phase 1); the rest of the
slice is read-only over the index and needs no additional Docker tier.

## Blockers / deferred (inline)

- Activity aggregation + `status` leaf: blocked (see Deferred section above).
- Q1 (rename `project_root` → `workspace_root`) stays deferred; the slice reads the existing field only.
- Q4 (persisted overlay metadata) deferred; nothing in this slice may write workspace state.
- `%workspace` direct-command mirror deferred (card Out of Scope).
- Bare-family session grouping (Slice-1 `project_root` is per-checkout there) is a documented boundary, not fixed here.

## Verification commands

```bash
uv run pytest tests/src/session/test_workspace.py tests/src/core/ops/test_workspace.py \
  tests/src/cli/test_workspace_commands.py -q
uv run pytest tests/src/cli/test_command_tree_invariants.py tests/src/session/worktree/test_create.py -q
./scripts/test-integration.sh tests/src/session/worktree/test_create_integration.py \
  tests/integration/docker/test_session_lifecycle.py -v
make test-unit
make pre-commit
```
