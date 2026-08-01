# Checklist -- session_create_crash_atomicity

**Card**: [card.md](card.md). Activation: create the execution branch, `git mv` this directory to
`docs/board/doing/session_create_crash_atomicity/`, and update this header per `board_contract.md`.

**Current focus**: not started. Phase 0 ratification comes first -- do not write the transaction before the lock-nesting
audit and the D1/D2 decisions are recorded here.

## Phase 0 -- Ground and ratify

- [ ] Re-verify the four creation pairs and every line anchor cited in card.md against current source. Assertion: the
  card's path table matches `rg -n "create_exclusive\(|add_from_state\(" src/forge/session/manager.py`; drifted anchors
  are corrected in the card before implementation starts.
- [ ] Lock-nesting audit: no call path holds a manifest lock while acquiring the index lock. Sweep every
  `SessionStore.update` / `_mutate` callback and the four `codex_thread_id` mirror write sites
  (`IndexStore.update_codex_thread` callers). Assertion: audit result recorded here with the sites listed; the index ->
  manifest ordering rule is pinned as a comment on the transaction.
- [ ] Raw-reader audit: enumerate every `IndexStore.read()` call site that does not hold the index lock (known: the
  binding scans `collect_bound_uuids` / `collect_bound_codex_threads`, `core/ops/session_context.py:465` / `:520`).
  Assertion: each site's tolerance of an observable row-before-manifest is recorded here with its direction of error
  (the binding scans err conservative -- reports bound); any site that cannot tolerate it is converted to a locked read
  in Phase 1.
- [ ] Decide D1 (transaction API shape: callback vs context manager; exception boundary; fate of the `start_session:541`
  `session_exists` pre-check -- drop vs manifest-aware) and D2 (`_restore_previous_target_state`: convert vs recorded
  best-effort residue). Assertion: decisions recorded inline here with one-line rationale each.
- [ ] Ratify D3's default split (the card leans split: orphan repair needs an identity-reconstruction contract, because
  `add_from_state` cannot derive `project_root` / `checkout_root` / `relative_path` from a manifest). Assertion:
  decision recorded; on split, the follow-up card is filed in `proposed/` seeded from card D3 and linked here.

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
- [ ] Docstrings: `create_exclusive` (`session/store.py:248`) gains the in-flight-lock clause; the transaction documents
  the index -> manifest lock order and the "no work but the two writes inside" constraint.

## Phase 2 -- Convert the four creation paths

- [ ] `start_session` (`session/manager.py:726-769`): two writes -> transaction; drop the `added_to_index` bookkeeping;
  keep `wrote_manifest` meaningful and `_rollback_worktree` outside the lock. Assertions:
  `test_bug_start_session_name_race.py` green unchanged; injected kill leaves no orphan manifest; a failing index-side
  check still triggers worktree rollback.
- [ ] `_persist_resume_child` (`:1051`) and `relaunch_session` (`:1723`): same conversion; relaunch's inline try/except
  rollback collapses into the transaction. Assertion: resume-child and relaunch unit suites plus
  `tests/regression/test_bug_resume_autoname_context_retry.py` green; seeded residue in each path leaves no orphan and a
  direct retry succeeds.
- [ ] `fork_session` (`:1625`): conversion preserving the stale-target replace ordering (delete-then-create sequence
  ahead of the commit) and applying the D2 decision to `_restore_previous_target_state` (`:1580`). Assertion: fork
  suites, `tests/regression/test_bug_fork_restore_clobbers_winner.py`, and the stale `fork --worktree --force`
  regressions green; a mid-commit failure still restores the previous target per the existing contract.
- [ ] Adoption arms unchanged at call level (both flow through `start_session` with `require_uuid_unbound=True`).
  Assertion: `test_bug_codex_adopt_double_bind.py` and the adopt binding/retention regressions green unchanged.

## Phase 3 -- Existing-orphan repair (default: split; gated on D3)

- [ ] Default path: file the follow-up card in `proposed/` seeded from card D3 (identity reconstruction,
  missing-worktree behavior, UUID/thread collision handling, legacy-manifest policy) and link it here. Only if Phase 0
  reverses the split: implement report-only surfacing plus non-destructive re-indexing, with the identity-
  reconstruction contract specified first. Assertion: either the follow-up link exists, or a seeded orphan is reported
  with its path and repaired into a listed, resumable session with no deletes and no changes to rowed sessions.

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
| Orphan repair (only if D3 reversed)          | seeded manifest with no row                                   | reported; re-indexed non-destructively; rowed sessions untouched        | new, Phase 3                                                                            |
| Lifecycle end-to-end                         | Docker session start/fork/resume/delete                       | suite green                                                             | `tests/integration/docker/test_session_lifecycle.py`                                    |

## Blockers / deferred decisions

Recorded inline under Phase 0 (D1, D2, D3). No external blockers known at acceptance.

## Closeout

- [ ] Final checklist items ticked with verification recorded.
- [ ] Compact `docs/board/change_log.md` entry (Goal / Key changes / Verification).
- [ ] Propose durable lessons via `.forge/memory/shadow_impl_notes.md`; human review promotes to
  `docs/board/impl_notes.md`.
- [ ] Verify design.md §3.2 and `session/__init__.py` reflect shipped behavior.
- [ ] Move the card `doing/ -> done/`; repoint inbound links, including a forward link from the
  `native_session_adoption` done checklist's open-debt note to this card's done path.
