# Give a session row an identity a deleter can carry into the lock

**Status**: Proposed. Split out of
[`session_create_crash_atomicity`](../../doing/session_create_crash_atomicity/card.md) on 2026-08-01, during that card's
third review round. That card made deletion decline once a replacement owns the name; this one closes the residual case
its ownership signal cannot express.

## Problem

`IndexStore.delete_session_txn` takes `expect_manifest_absent`, a boolean the caller derives from what its delete did:
the manifest was already gone when it started, or it lives inside the worktree being removed. When True, a manifest
found under the index lock can only belong to a creator that reclaimed the name, so the delete declines. When False, the
check is skipped -- correct for a delete whose manifest is still its own, because such a delete never opened a window
for a creator to reclaim the name.

The gap is a **second concurrent delete of the same name**. It sampled its flag while the manifest was still present, so
it arrives with False; but the *first* delete opened the window, a creator reclaimed the name, and the second delete
removes the replacement's row and manifest with the check disabled.

Reproduced 2026-08-01 (`delete_session` for the winner, a `start_session` recreate, then the loser's terminal removal
with its stale flag): `still_ours=True`, replacement row and manifest both destroyed.

The same shape reaches `fork --force`, which frees a stale target through `delete_session` before publishing.

## Why the current signal cannot be fixed in place

`expect_manifest_absent` answers "did *I* destroy the manifest at this name?". Closing the residual needs a different
question: "is the row under this lock the same session I sampled?". No field on `SessionIndexEntry` answers it.

- `created_at` / `last_accessed_at` -- `now_iso()` has second granularity, so a same-second replacement is byte-
  identical. Two forks of one parent produce identical manifests. Already ruled out once during
  `session_create_crash_atomicity`; a first attempt at the delete guard failed for exactly this reason.
- `claude_session_id` / `codex_thread_id` -- a genuine replacement usually carries different conversation identity, but
  both are `None` for a session that has not yet bound one, which is the state a freshly created replacement is in.
  Partial, and a partial guard on a race is worse than a documented one: it makes the residual harder to reason about
  without removing it.
- Whole-entry comparison -- a same-name recreate in the same project reproduces `worktree_path`, `project_root`,
  `forge_root`, `checkout_root`, and `relative_path` exactly.

## Candidate mechanisms

1. **A generation / instance id on the row.** Creation mints an opaque unique id; the deleter samples it at entry and
   `delete_session_txn` declines when the id under the lock differs. Complete and easy to reason about. It is a
   durable-state schema change: `SessionIndex` version bump plus a reset or migration path, per `coding_standards.md` §5
   "Forge-owned durable state".
2. **Manifest file identity (`st_dev`/`st_ino` plus `st_ctime_ns`).** No schema change: `atomic_write_json` publishes
   through `os.replace`, so a replacement always lands on a new inode. Cheaper, but it answers a filesystem question
   about a file rather than an index question about a session, and it needs care where the manifest is legitimately
   absent at sample time.
3. **A per-name lifecycle lock** held from ownership check through both removals. Conceptually cleanest, but it adds a
   third lock to the index -> manifest order and needs its own deadlock audit against the conversation lock.

Leaning: (1), because the identity belongs to the session rather than to one of its files, and because the row is
already the thing every other cross-session uniqueness decision keys on.

## Scope notes

- Both delete entry points must be covered: `SessionManager.delete_session` and `fork_session`'s stale-target cleanup.
- Whatever ships must keep `expect_manifest_absent`'s existing guarantees or replace them outright -- not sit alongside
  them as a second partial signal.
- Regression coverage belongs with the existing schedules in
  `tests/regression/test_bug_session_create_crash_atomicity.py`, which already models delete/create coordination.

## Priority

Low. Reaching it takes two concurrent deletes of one session name plus a recreate landing between them. Recorded so the
next auditor of `delete_session_txn` finds the analysis instead of re-deriving it; the docstring names this card.
