# Checklist -- session_create_crash_atomicity

**Card**: [card.md](card.md). Branch: `fix/session-create-crash-atomicity`.

**Current focus**: Phase 1 -- transaction primitive. Phase 0 is complete; its audits and the D1/D2/D3 decisions are
recorded below and are binding on Phases 1-2.

## Phase 0 -- Ground and ratify (complete 2026-08-01)

- [x] Re-verify the four creation pairs and every line anchor cited in card.md against current source. **Verified, no
  drift**: `rg -n "create_exclusive\(|add_from_state\(" src/forge/session/manager.py` returns exactly `732/735`,
  `1051/1056`, `1625/1631`, `1723/1725`, plus `1580` (`_restore_previous_target_state`). Also confirmed: `store.py:248`
  (`create_exclusive`), `index.py:182`/`:201` (`list_sessions` lock + prune re-check), `index.py:258`/ `:274`
  (`get_session` phase 1 + phase 3 re-check), `index.py:342`/`:349` (`add_session` lock + in-lock
  `require_uuid_unbound`), `index.py:481` (`session_exists`), `index.py:503` (`add_from_state`), `manager.py:541`
  (pre-check), `manager.py:1763` (`_name_is_taken`), `session_context.py:439`/`:465` and `:502`/`:520` (binding scans).
  Three card corrections are recorded under "Phase 0 findings" below.
- [x] Lock-nesting audit: **clean -- no manifest -> index nesting exists.** The manifest lock is acquired in exactly
  three places (`SessionStore.write:245`, `create_exclusive:269`, `update:343`); `write`/`create_exclusive` call only
  `_write_unlocked`, so `update`'s `mutate` callback is the sole place user code runs under a manifest lock. Every index
  call in an `update`-adjacent site is **sequential after** the lock releases, not nested: `manager.py:395`->`398`,
  `cli/session_fork.py:1049`->`1050`, `core/ops/claude_session.py:1006`->`1010`, `cli/hooks/commands.py:193`->`197`, and
  all four `codex_thread_id` mirror sites (`codex_interactive.py:347`->`348` and `:471`->`:472`;
  `codex_session.py:385`->`386` and `:524`->`:525`, all via `_sync_codex_thread_to_index`, which takes no manifest
  lock). No `mutate` callback references `IndexStore`. Sweep basis: every file containing both `mutate=` and an index
  symbol. Adjacent locks are on distinct lock files and do not participate: `session/active.py` locks
  `~/.forge/active/active.json`, and `session_adopt.py:132` holds the global per-conversation `adopt-<uuid>.lock`
  **outermost** (order: conversation -> index -> manifest). The index -> manifest rule is pinned as a comment on the
  transaction in Phase 1.
- [x] Raw-reader audit: four real unlocked `IndexStore.read()` sites, all tolerant.
  - `core/ops/session_context.py:465` (`collect_bound_uuids`): **conservative.** Records `entry.claude_session_id`
    straight off the row (`:492`) before touching the manifest, so an in-flight row reads as *bound*. Its manifest read
    (`_read_manifest_uuid:485`) guards on `store.exists()`, so an absent manifest is skipped rather than raising
    `BindingLookupError` -- the in-flight window cannot fail-closed a concurrent adopt.
  - `core/ops/session_context.py:520` (`collect_bound_codex_threads`): **permissive -- must change in Phase 1.** It
    never reads the `codex_thread_id` column; `_record:529` opens the manifest and returns early when `store.exists()`
    is False (`:534`). Under row-first, a row published with a `codex_thread_id` whose manifest has not landed reports
    the thread as *free*. See finding F2.
  - `core/ops/gc.py:695`: parse-only corruption probe for `forge clean`; row/manifest correspondence is irrelevant.
  - `cli/proxy.py:1036`: iterates rows to warn about sessions bound to a proxy, and already skips rows whose manifest is
    missing (`:1040-1041`). A mid-creation session is not yet bound to the proxy, so omitting it is correct.
  - Not a session-index reader: `cli/search.py:621` is `IndexStateStore` (search index). `claude_session.py:1010` and
    `session_fork.py:1050` are `SessionStore.read()` (manifest), not index reads.
- [x] Decide D1 and D2 -- recorded under "Decisions" below.
- [x] Ratify D3's default split -- **split confirmed**; follow-up card filed at
  [`proposed/session_orphan_manifest_repair`](../../proposed/session_orphan_manifest_repair/card.md).

### Phase 0 findings (card corrections)

- **F1 -- the pre-check gap (widens D1).** The card scopes D1's pre-check question to `start_session:541`, but three
  sites hard-fail identically on a pure row check: `:541` (`start_session`), `:831` (resume child), `:1696`
  (`relaunch_session`). A fourth, `:1077` (`winner_owns`), ORs the row check with `child_store.exists()`. Phase 2's
  assertion that a *direct retry succeeds* for resume-child and relaunch cannot pass while `:831` and `:1696` reject a
  prunable residue, so D1 must cover all four.
- **F2 -- the binding scans are asymmetric.** The card states both scans "err conservative -- reports bound". True for
  `collect_bound_uuids` (reads the row column at `:492`); false for `collect_bound_codex_threads`, which consults only
  manifests. Phase 1 adds the row-column read so the Codex scan matches. This is not a latent bug today -- under
  manifest-first, any row carrying a `codex_thread_id` already has its manifest -- so it is a change the reordering
  requires, not a pre-existing defect.
- **F3 -- `file_lock_for_target` is not reentrant.** `file_lock:74` calls `os.open()` per acquisition, and `flock`
  scopes locks to the open file description, so a nested acquisition of the same lock file in one process is denied by
  its own outer lock and spins to `FileLockTimeoutError`. Compensation therefore **cannot** call `remove_session` (which
  locks at `index.py:470`); it must mutate the in-memory index and call `self.write(index)`. Corollary: the index ->
  manifest order is safe by construction (distinct lock files), and the only deadlock shape is a true ABBA, which the
  lock-nesting audit rules out.

### Decisions

- **D1 -- transaction API shape.** Callback form on `IndexStore`:

  ```python
  def create_session_txn(
      self, state: SessionState, project_root: str, *,
      checkout_root: str | None = None, forge_root: str | None = None,
      relative_path: str | None = None, require_uuid_unbound: bool = False,
      write_manifest: Callable[[], None],
  ) -> SessionIndexEntry: ...
  ```

  Rationale: a callback makes the "no work but the two writes inside the lock" constraint reviewable at each call site
  and lets tests assert ordering with a spy, where a context manager invites arbitrary work in the `with` body. The
  transaction stays manifest-agnostic -- it invokes an opaque callable -- so a caller needing overwrite semantics can
  pass `write` instead of `create_exclusive` without the transaction knowing (this is what makes D2 cheap).

  - **Exception boundary**: `InvalidSessionNameError`, index-side `SessionExistsError`, and `UuidAlreadyBoundError`
    raise *before* the callback runs; the callback's own exception propagates unchanged after in-lock compensation.
  - **Compensation**: delete the row from the in-memory index and `self.write(index)` inside the already-held lock --
    never `remove_session` (F3).
  - **Stale-row self-heal**: under the held lock, row-present + manifest-absent is pruned and creation proceeds. Probe
    exactly as `list_sessions` does (`get_manifest_path(entry.forge_root or entry.worktree_path, display_name)`), but on
    **manifest absence only** -- not `list_sessions`' `worktree.exists()` clause. Narrower is correct: the manifest is
    the durable reservation, so a live manifest whose worktree vanished must still collide.
  - **Pre-checks (resolves F1)**: add `IndexStore.live_session_exists(name, forge_root)` -- row **and** manifest present
    -- and use it at `:541`, `:831`, `:1696`. Keeps the cheap fail-fast that avoids creating a worktree only to roll it
    back, while letting a prunable residue reach the transaction. `session_exists` keeps its pure-row semantics for
    `_name_is_taken:1763`, where the conservative answer costs an auto-name suffix rather than an error (card's retry
    contract). `:1077`'s `winner_owns` also moves to `live_session_exists`: a bare residue row is not a live owner, and
    treating it as one would suppress the transfer-snapshot reclaim.

- **D2 -- `_restore_previous_target_state`: convert.** Route the `write`+`add_from_state` pair (`:1572`/`:1580`) through
  the transaction. Rationale: its crash window is identical, and the guard it relies on today (`:1564`
  `not wrote_manifest or target_store.exists()`) is an unlocked TOCTOU probe that the index lock enforces properly -- if
  a new creator won the name, the transaction's own uniqueness check raises and the restore declines, which is the
  existing intent made atomic. The callback keeps `write` (the card's deliberate-overwrite reading) rather than
  `create_exclusive`, so the conversion cannot change restore semantics; D1's opaque-callable shape admits it. The site
  stays best-effort: wrap the transaction call and log a warning on failure, matching `:1574`/`:1588`.

- **D3 -- existing-orphan repair: split (ratified).** Confirmed by `index.py:503`'s own docstring: `add_from_state`
  cannot derive `project_root` / `checkout_root` / `relative_path` from a `SessionState`, so repair owes an identity-
  reconstruction contract that does not belong in this card. Filed as
  [`proposed/session_orphan_manifest_repair`](../../proposed/session_orphan_manifest_repair/card.md).

## Phase 1 -- Transaction primitive (`IndexStore`)

- [ ] Implement the transaction: lock -> uniqueness checks -> row write -> manifest callback -> in-lock compensation on
  callback failure. Assertions:
  - a callback failure (injected `SessionExistsError` from a pre-existing orphan manifest) leaves no index row and
    re-raises the callback's exception unchanged;
  - compensation runs inside the already-held lock -- `file_lock_for_target` is acquired exactly once per transaction
    (assert via call spy);
  - index-side `SessionExistsError` and `UuidAlreadyBoundError` raise before the manifest callback ever runs;
  - stale-row self-heal (card's retry contract): row present + manifest absent under the held lock is pruned and
    creation proceeds.
- [ ] Crash-residue family, kept distinct from compensation: seed a row-without-manifest residue (write the row, skip
  the callback, release via a test seam). This is the accepted crash model -- an injected exception exercises
  compensation, which a killed process bypasses, so both families are required and neither substitutes for the other.
  Assertions: `list_sessions` and `get_session` each prune the residue; a direct same-name `start_session` retry
  succeeds with no intervening `session list` or `session delete`.
- [ ] Stale-snapshot pruner spares a republished row: a pruner that flagged name K from a pre-transaction snapshot must
  re-verify under the re-acquired lock (`list_sessions` prune pass, `get_session` phase 3) and spare K once a new
  transaction has published row + manifest. Assertions: with the under-lock re-check bypassed the test fails (proves the
  guard is load-bearing); locked readers block for the duration of the transaction and never observe
  row-without-manifest.
- [ ] `IndexStore.live_session_exists(name, forge_root)` (per D1/F1): row **and** manifest present, strict resolution
  like `session_exists`. Assertions: returns False for a seeded row-without-manifest; returns True for a healthy
  session; raises `AmbiguousSessionError` on an unscoped duplicate name exactly as `session_exists` does.
- [ ] `collect_bound_codex_threads` records `entry.codex_thread_id` from the row before reading the manifest (per F2),
  mirroring `collect_bound_uuids:492`. Assertions: a seeded row carrying a `codex_thread_id` with no manifest reports
  the thread as **bound**; `collect_bound_uuids` behavior is unchanged; the fail-closed manifest-read contract still
  raises `BindingLookupError` on an unreadable (as opposed to absent) manifest.
- [ ] Docstrings: `create_exclusive` (`session/store.py:248`) gains the in-flight-lock clause; the transaction documents
  the index -> manifest lock order, the non-reentrancy of `file_lock_for_target` (F3) and the resulting "compensate
  in-memory, never `remove_session`" rule, and the "no work but the two writes inside" constraint.

## Phase 2 -- Convert the four creation paths

- [ ] `start_session` (`session/manager.py:726-769`): two writes -> transaction; drop the `added_to_index` bookkeeping;
  keep `wrote_manifest` meaningful and `_rollback_worktree` outside the lock. Convert the `:541` pre-check to
  `live_session_exists` (D1/F1). Assertions: `test_bug_start_session_name_race.py` green unchanged; injected kill leaves
  no orphan manifest; a failing index-side check still triggers worktree rollback; a seeded residue does **not** cause
  the pre-check to reject before a worktree is created.
- [ ] `_persist_resume_child` (`:1051`) and `relaunch_session` (`:1723`): same conversion; relaunch's inline try/except
  rollback collapses into the transaction. Convert the `:831` and `:1696` pre-checks and `:1077`'s `winner_owns` to
  `live_session_exists` (D1/F1) -- without this the direct-retry assertion below cannot pass. Assertion: resume-child
  and relaunch unit suites plus `tests/regression/test_bug_resume_autoname_context_retry.py` green; seeded residue in
  each path leaves no orphan and a direct **explicit-name** retry succeeds; the auto-name retry loop still consumes at
  most one retry (both claims continue to feed one collision path).
- [ ] `fork_session` (`:1625`): conversion preserving the stale-target replace ordering (delete-then-create sequence
  ahead of the commit) and converting `_restore_previous_target_state` (`:1580`) per D2 -- transaction with a `write`
  callback, still best-effort with a logged warning. Assertion: fork suites,
  `tests/regression/test_bug_fork_restore_clobbers_winner.py`, and the stale `fork --worktree --force` regressions
  green; a mid-commit failure still restores the previous target per the existing contract; a restore that races a new
  owner of the name declines via the transaction's uniqueness check rather than the `:1564` probe.
- [ ] Adoption arms unchanged at call level (both flow through `start_session` with `require_uuid_unbound=True`).
  Assertion: `test_bug_codex_adopt_double_bind.py` and the adopt binding/retention regressions green unchanged.

## Phase 3 -- Existing-orphan repair (default: split; gated on D3)

- [x] Default path taken (Phase 0 ratified the split). Follow-up card filed at
  [`proposed/session_orphan_manifest_repair`](../../proposed/session_orphan_manifest_repair/card.md), seeded from card
  D3: identity reconstruction, missing-worktree behavior, UUID/thread collision handling, legacy-manifest policy, plus a
  discovery-surface question the card D3 paragraph did not name. No repair code ships in this card.

## Phase 4 -- Docs sync and verification

- [ ] design.md §3.2: rewrite the reservation paragraph (manifest = durable reservation; held index lock = in-flight
  reservation; the crash-residue table; the direct-retry contract) and drop the "killed between the two leaves a
  manifest with no index row" clause. Update the `session/__init__.py` docstring example, and the `collect_bound_uuids`
  / `collect_bound_codex_threads` docstrings, whose orphan-scan rationale ("Session creation writes the manifest first")
  narrows to pre-existing orphans.
- [ ] Integration tier (mandatory -- session start/resume/fork touched):
  `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py`; include the adoption Docker gates
  (`test_adopt_binding_contract.py`, `test_adopt_native_conversation.py`) if the environment is already warm.
- [ ] `make test-unit`, `make test-regression`, `make pre-commit`.
- [ ] One adversarial review round; reproduce every finding before fixing it (house rule for this code area).

## Acceptance tests

| Test                                         | Fixture                                                       | Assertion                                                               | Test File                                                                               |
| -------------------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Crash residue self-heals                     | seeded row-without-manifest (accepted crash model)            | `list_sessions` and `get_session` each prune it                         | `tests/regression/test_bug_session_create_crash_atomicity.py`                           |
| Direct same-name retry                       | seeded residue, then `start_session` with the same name       | retry succeeds with no prior `session list` / `session delete`          | same                                                                                    |
| Compensation on callback failure             | pre-seeded orphan manifest raises `SessionExistsError`        | no row persisted; exception surfaced unchanged; single lock acquisition | same                                                                                    |
| Stale-snapshot pruner spares republished row | pruner snapshot pre-transaction; transaction republishes name | under-lock re-check spares the row; test fails if re-check bypassed     | same                                                                                    |
| Same-name concurrent create                  | barrier-gated double `start_session`                          | one winner; loser `SessionExistsError`; loser leaves no orphan          | `tests/regression/test_bug_start_session_name_race.py`                                  |
| Adoption double-bind unchanged               | interleaved adopts of one thread                              | one binding, one `UuidAlreadyBoundError`                                | `tests/regression/test_bug_codex_adopt_double_bind.py`                                  |
| Fork-restore and autoname contracts          | existing fixtures                                             | green unchanged                                                         | `test_bug_fork_restore_clobbers_winner.py`, `test_bug_resume_autoname_context_retry.py` |
| Per-path residue + compensation              | both families in each of the four paths                       | no orphan from any path; path-specific rollback still fires             | new unit tests beside each path's suite                                                 |
| `live_session_exists` ignores a bare row     | seeded row-without-manifest                                   | False for the residue; True for a healthy session                       | `tests/src/session/test_index.py`                                                       |
| Codex scan stays conservative in-flight      | seeded row with `codex_thread_id`, manifest absent            | thread reports **bound**, not free (F2)                                 | `tests/src/core/ops/test_session_context.py`                                            |
| Explicit-name retry on resume and relaunch   | seeded residue, then same explicit `child_name`               | retry succeeds; pre-check does not reject the residue (F1)              | `tests/regression/test_bug_session_create_crash_atomicity.py`                           |
| Fork restore declines to a live winner       | restore races a new owner of the name                         | transaction uniqueness check declines; winner's manifest untouched      | `tests/regression/test_bug_fork_restore_clobbers_winner.py`                             |
| Lifecycle end-to-end                         | Docker session start/fork/resume/delete                       | suite green                                                             | `tests/integration/docker/test_session_lifecycle.py`                                    |

## Blockers / deferred decisions

D1, D2, and D3 are decided -- see "Decisions" under Phase 0. No external blockers. Deferred out of this card: existing-
orphan repair (D3 split, filed as `proposed/session_orphan_manifest_repair`). Carried into Phase 1 from Phase 0:
findings F1 (four pre-check sites, not one), F2 (`collect_bound_codex_threads` needs the row-column read), and F3
(`file_lock_for_target` is not reentrant, so compensation must not call `remove_session`).

## Closeout

- [ ] Final checklist items ticked with verification recorded.
- [ ] Compact `docs/board/change_log.md` entry (Goal / Key changes / Verification).
- [ ] Propose durable lessons via `.forge/memory/shadow_impl_notes.md`; human review promotes to
  `docs/board/impl_notes.md`.
- [ ] Verify design.md §3.2 and `session/__init__.py` reflect shipped behavior.
- [ ] Move the card `doing/ -> done/`; repoint inbound links, including a forward link from the
  `native_session_adoption` done checklist's open-debt note to this card's done path.
