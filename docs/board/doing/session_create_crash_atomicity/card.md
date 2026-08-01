# Crash-atomic session creation (manifest + index)

**Lane**: `doing/` -- accepted 2026-08-01, active since 2026-08-01; execution plan in [checklist.md](checklist.md).
Standalone. Discharges the open debt recorded at closeout of
[`native_session_adoption`](../../done/native_session_adoption/card.md): its
[checklist](../../done/native_session_adoption/checklist.md) carries the fix recommendation under "Open debt -- creation
is still not crash-atomic".

**Origin**: the adoption card's closing review (2026-07-27) proposed the fix shape and verified its deadlock
precondition ("nothing nests manifest->index today"), but declined to execute it there because it restructures
`IndexStore` for all four creation paths. This card ratifies and executes that recommendation.

## Problem

Every path that mints a session performs two durable writes with no shared lock spanning them:

```python
store.create_exclusive(state)          # manifest -- the durable name reservation
self.index_store.add_from_state(...)   # global index row -- what `session list` sees
```

| Path                                   | Pair (session/manager.py) |
| -------------------------------------- | ------------------------- |
| `SessionManager.start_session`         | `:732` / `:735`           |
| `SessionManager._persist_resume_child` | `:1051` / `:1056`         |
| `SessionManager.fork_session`          | `:1625` / `:1631`         |
| `SessionManager.relaunch_session`      | `:1723` / `:1725`         |

A process killed between the two writes leaves a manifest with no index row. The orphan:

- is invisible to `session list` (index-driven; the index prune never sees a manifest with no row);
- still owns its name -- `create_exclusive` raises `SessionExistsError` for a session nothing lists, and
  `_name_is_taken` consults the manifest, so auto-naming skips it too;
- still owns its conversation binding. Adoption is already protected against a double-bind by the fail-closed manifest
  scans (`collect_bound_uuids` / `collect_bound_codex_threads`, `core/ops/session_context.py:439` / `:502`) plus the
  global per-conversation `conversation_lock` (design.md §3.2) -- but those bound the *consequence*; the orphan itself
  persists.

Recovery today is manual and undiscoverable: `session delete <name>` from inside the owning project resolves the
manifest directly, but nothing tells the user the orphan exists.

## Fix shape (proposed by the closing review; ratified here)

One index-lock-spanning transaction, **row first**:

1. Acquire the index write lock (`file_lock_for_target` on `~/.forge/sessions/index.json`).
2. Run the index-side uniqueness checks exactly as `IndexStore.add_session` does today: scoped name key, plus
   `require_uuid_unbound` for adoption.
3. Write the index row.
4. Write the manifest via `SessionStore.create_exclusive` (nested manifest lock).
5. Release. If step 4 raises, remove the row inside the same held lock scope before re-raising (no lock re-acquisition).

Crash residues become:

| Killed          | Residue                | Healing                                                                                       |
| --------------- | ---------------------- | --------------------------------------------------------------------------------------------- |
| before step 3   | nothing                | none needed                                                                                   |
| between 3 and 4 | index row, no manifest | under-lock re-checks prune it; the next same-name creation transaction prunes it and proceeds |
| after step 4    | both present           | none needed                                                                                   |

A manifest-without-row can no longer be produced by creation.

**Invariant, stated precisely.** "Crash-atomic" here means: creation never leaves a durable manifest-only orphan, and
publication is atomic for every reader that takes the index lock. It is deliberately *not* both-or-neither for all
observers: a raw `IndexStore.read()` consumer can observe the row before its manifest (see Constraints), and a kill can
leave a row-only residue that is pruned rather than never seen. Crash-consistent-and-self-healing is the honest name for
the outcome; the slug keeps the change log's recorded phrasing of the debt.

**Retry contract (the stale-row reservation gap, resolved).** A bare row would otherwise still block a direct same-name
retry: `session_exists` is a pure row check (`session/index.py:481`), `start_session` pre-checks it and raises
(`session/manager.py:541`), and `_name_is_taken` (`:1763`) counts row-or-manifest as taken. The transaction closes this
itself: under its held lock, row-present + manifest-absent is not a reservation, so the transaction prunes the stale row
and proceeds. An explicit same-name retry therefore succeeds immediately, with no intervening `session list` or
`session delete`. No pre-check may hard-fail on a row-only state. **Corrected by the review round (finding F6)**: this
paragraph originally claimed that state "can only be crash residue -- a live creator would be holding the same lock".
That is false. An in-flight `delete_session` produces it too, holding no index lock for the duration, so the reclaim is
safe only because deletion now ends in `delete_session_txn`, which declines once a replacement owns the name.
**Corrected by Phase 0 (finding F1)**: there are four such pre-checks, not one -- `:541` (`start_session`), `:831`
(resume child) and `:1696` (`relaunch_session`) all raise `SessionExistsError` off a pure row check, and `:1077`
(`winner_owns`) ORs one with a manifest probe. D1 resolves all four via a new `live_session_exists` (row **and**
manifest), which keeps the cheap fail-fast that avoids building a worktree only to roll it back. `_name_is_taken`'s
conservative answer stays acceptable for auto-naming: skipping a stale name costs a suffix, not an error.

**Why row-first, and why it is safe now.** Manifest-first under the lock fixes nothing: `flock` dies with the process,
so the kill residue would still be today's orphan. Row-first was tried once before (adoption Slice-2 remediation) and
reverted, because a row written ahead of its manifest could be pruned out from under its own creator. Two facts close
that race. Locked readers cannot observe the in-flight state at all: `list_sessions` takes the index lock for its
initial read (`session/index.py:182`) and `get_session` for each of its three phases (`:258`), so both block until the
transaction releases with the manifest already on disk. The residual TOCTOU -- a pruner acting on a pre-transaction
snapshot, since filesystem probes deliberately run unlocked -- deletes only after re-verifying staleness under a
re-acquired lock (`:201` for `list_sessions`, `:274` for `get_session` phase 3); a row republished by a new transaction
has its manifest written before that lock is ever released, so the re-check spares it. That under-lock re-check before
every prune delete is the load-bearing guard; the transaction work must not weaken it.

**Reservation semantics after the change.** The manifest remains the *durable* reservation: a bare row is still
prunable, so a row alone still reserves nothing across a crash -- the argument in `create_exclusive`'s docstring
(`session/store.py:248`) stays true. What changes is the in-flight story: during creation the held index lock is the
reservation, and the manifest write happens inside it. design.md §3.2's reservation paragraph and that docstring must
both gain the second clause, not be contradicted.

## Design decisions owed

1. **Transaction API shape.** A callback- or context-manager-form on `IndexStore` (working name:
   `create_session_txn(state, ..., write_manifest=<callback>)`) used by all four paths. It must not re-acquire the index
   lock for compensation and must keep `add_session`'s exception boundary (`SessionExistsError` index-side,
   `UuidAlreadyBoundError`, `InvalidSessionNameError`) plus surface the callback's own `SessionExistsError`
   (manifest-side, e.g. a pre-existing orphan) unchanged to callers. It also owns the stale-row self-heal from the retry
   contract above and decides the fate of the `start_session:541` pre-check (drop it and let the transaction raise, or
   make it manifest-aware) -- a row-only residue must not surface as `SessionExistsError` from any layer.
2. **`_restore_previous_target_state`** (`session/manager.py:1580`, fork's stale-target restore): route through the
   transaction, or accept its best-effort residue? It restores previously existing state with `write` (a deliberate
   overwrite), not `create_exclusive`, so the transaction callback shape must admit that -- or the restore keeps its
   current two-step form with a recorded known residue. Leaning: convert, since the crash window is identical.
3. **Existing-orphan repair -- default: split.** The transaction prevents new orphans only; pre-existing ones (and any
   from older Forge versions) remain. Repair is non-destructive in principle (add an index row), but it is *not* "just
   `add_from_state`": the identity fields `project_root`, `checkout_root`, and `relative_path` are caller-computed from
   git and filesystem state that a `SessionState` cannot supply (its docstring says exactly this,
   `session/index.py:503`); the manifest retains only `forge_root` and worktree metadata. A real repair contract owes
   identity reconstruction (recompute via the same helpers creation uses), missing-worktree behavior, UUID/thread
   collision handling against live rows, and malformed/legacy-manifest policy. That is its own card: Phase 3 files it in
   `proposed/` seeded from this paragraph, unless Phase 0 explicitly reverses the split. **Ratified 2026-08-01**: split
   confirmed; filed as
   [`proposed/session_orphan_manifest_repair`](../../proposed/session_orphan_manifest_repair/card.md).

## Constraints (must not break)

- `require_uuid_unbound` stays inside the same lock acquisition as the row write (adoption's in-lock re-check).
- `conversation_lock` and the fail-closed manifest scans stay: they cover orphans that already exist on disk, which this
  card does not remove.
- `create_exclusive` keeps its `SessionExistsError` semantics, and `wrote_manifest` stays a meaningful ownership token
  in every rollback block; in-lock compensation removes only the row this transaction wrote.
- Worktree creation and `_rollback_worktree` stay outside the index lock; hold time is the two writes only (no
  LLM/network/worktree work inside the callback).
- Lock order is index -> manifest only. Re-verify the review's "nothing nests manifest->index" claim -- especially the
  four `codex_thread_id` mirror sites and `SessionStore.update` `_mutate` callbacks -- and pin it with a comment on the
  transaction, because a single manifest->index caller would deadlock against it.
- Raw `IndexStore.read()` consumers -- readers that deliberately skip the lock -- can observe the published row before
  its manifest exists. **Corrected by Phase 0 (finding F2)**: the two fail-closed binding scans are *not* symmetric.
  `collect_bound_uuids` (`core/ops/session_context.py:465`) is conservative as assumed -- it records
  `entry.claude_session_id` off the row (`:492`), so the conversation reads as bound while publication completes. But
  `collect_bound_codex_threads` (`:520`) never reads the `codex_thread_id` column; it opens the manifest and returns
  early when it is absent, so an in-flight Codex row would report its thread *free* -- the permissive direction. Phase 1
  adds the row-column read. The other raw-read sites (`core/ops/gc.py:695`, `cli/proxy.py:1036`) tolerate the temporary
  row; the full enumeration and each site's direction of error are recorded in the checklist.
- Existing regressions stay green: `tests/regression/test_bug_start_session_name_race.py`,
  `tests/regression/test_bug_codex_adopt_double_bind.py`, `tests/regression/test_bug_fork_restore_clobbers_winner.py`
  and `tests/regression/test_bug_resume_autoname_context_retry.py` (both exercise contracts adjacent to collision
  detection moving ahead of `create_exclusive`), and the adoption binding/retention regressions.

## Risks

- The four commit blocks are review-hardened (their comments cite reproduced findings); restructuring them is where a
  regression would hide. Every prior touch of this area shipped defects found only by reproduce-before-fix review.
  Mitigation: crash-injection tests per path plus one adversarial review round before merge.
- The global index lock is held across one extra atomic manifest write (fsync). Hold time stays milliseconds, but every
  session-creating command in every project shares this lock; the callback must stay minimal.
- `session/__init__.py`'s docstring example and design.md §3.2 teach the current two-step shape, and
  `collect_bound_uuids`'s docstring justifies its orphan scan with "Session creation writes the manifest first" -- all
  become stale statements under the new order (the orphan scan itself stays; its rationale narrows to pre-existing
  orphans). Stale teaching material is a drift source if not updated in the same change.

## Verification anchors

Two distinct unit families per path -- compensation (injected callback exception) and crash residue (seeded
row-without-manifest, the accepted crash model, because a killed process bypasses compensation) -- plus a direct
same-name-retry test and a stale-snapshot-pruner test; the concurrency regressions above; Docker session lifecycle
integration (`./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py` -- session
start/resume/fork are touched, so the integration tier is mandatory per testing_guidelines "When to Run Integration
Tests"); `make pre-commit`.
