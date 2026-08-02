# Repair manifest-only session orphans (surface + re-index)

**Lane**: `doing/` -- accepted 2026-08-02, active since 2026-08-02; execution plan in [checklist.md](checklist.md).
Split out of [`session_create_crash_atomicity`](../../done/session_create_crash_atomicity/card.md) D3 on 2026-08-01, per
that card's Phase 0 ratification. That card stops **new** orphans being created; this one handles the ones already on
disk.

**References**: `session_create_crash_atomicity` card.md §"Design decisions owed" item 3 (the paragraph this card is
seeded from) and its Phase 0 decisions block.

## Problem

A session manifest with no index row is invisible to `session list`, still owns its name (`create_exclusive` raises
`SessionExistsError`; `_name_is_taken` consults the manifest), and still owns its conversation binding. Recovery today
is `session delete <name>` from inside the owning project -- and nothing tells the user the orphan exists.

`session_create_crash_atomicity` closes the window that produces these, but does not remove existing ones. Orphans
persist from crashes before that change ships and from older Forge versions.

## Why this is not `add_from_state`

The obvious repair -- read the manifest, call `IndexStore.add_from_state` -- cannot work. `add_from_state`
(`session/index.py:503`) takes the identity fields from its **caller**, and its docstring says why: `project_root`,
`checkout_root`, and `relative_path` are computed from git and filesystem state that a `SessionState` cannot supply. The
manifest retains only `forge_root` and worktree metadata.

Creation derives them like this (`session/manager.py:658-678`):

```python
checkout_root = get_repo_root(Path(worktree_path))          # git --show-toplevel, not CWD
project_root  = manager.resolve_project_root(worktree_path)  # manager.py:436
relative_path = Path(forge_root).relative_to(checkout_root)  # "." when not nested
```

Every one of those needs the worktree to still exist and still be a git checkout. An orphan's worktree may be gone --
which is exactly the state that makes the orphan hard to notice.

## Contract this card owes

1. **Identity reconstruction.** Recompute `project_root` / `checkout_root` / `relative_path` through the same helpers
   creation uses, so a repaired row is indistinguishable from a natively created one. Decide the fallback chain when
   `get_repo_root` fails (creation itself falls back to `worktree_path`, `manager.py:665`).
2. **Missing-worktree behavior.** Repair, report-only, or offer deletion? A row pointing at a missing worktree is pruned
   on the next `list_sessions` (`index.py:197`), so a naive repair would write a row that immediately self-deletes --
   churn that looks like a fix and is not.
3. **UUID / thread collision handling.** The orphan may hold a `claude_session_id` or `codex_thread_id` that a **live**
   row already claims. Re-indexing it would publish a second binding -- the precise outcome `require_uuid_unbound`
   (`index.py:349`) and the fail-closed scans exist to prevent. Repair must refuse, not bind.
4. **Malformed / legacy manifest policy.** A manifest that fails the strict v1 read (`store.py:349` `_validate_data`)
   cannot be repaired into a row. Decide the split against `forge clean`, which already removes corrupt manifests
   (`core/ops/gc.py:702` `_detect_corrupt_state`), so the two must not disagree about ownership.
5. **Discovery surface.** Where does the user learn an orphan exists? Candidates: a `session list` footer note, a
   `forge session doctor`-style command, or a `forge clean` category. Scanning is per-project (`_manifest_dirs`), not
   global, so a global `session list` cannot see orphans outside the current project.

## Constraints

- Non-destructive by default: repair adds a row. It must not delete manifests and must not modify rows for sessions that
  already have one.
- Reuse the existing scan, do not add a second one: `collect_bound_uuids` / `collect_bound_codex_threads`
  (`core/ops/session_context.py:439` / `:502`) already walk every manifest directory under a `forge_root` precisely to
  see orphans. Their read-only, no-prune contract must survive.
- Repair is a creation path, so it takes the `create_session_txn` transaction rather than a bare `add_from_state`.

## Open questions

- Is repair automatic (on `session list`, like the existing prune) or explicit (a command)? Automatic re-indexing of a
  name the user believes is gone is a surprising resurrection; explicit repair leaves the orphan invisible until asked
  about. The discovery surface (item 5) and this question should be decided together.
- Does repair belong to `forge clean`, which already owns "Forge-owned durable state is inconsistent"?
