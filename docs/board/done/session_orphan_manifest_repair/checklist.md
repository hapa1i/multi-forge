# Checklist -- session_orphan_manifest_repair

**Card**: [card.md](card.md). Branch: `feat/session-orphan-manifest-repair`.

**Current focus**: Phases 1-3 implemented; review round 3 findings F7-F11 fixed and verified 2026-08-02. Awaiting
re-review/merge, then closeout. D1-D6 ratified 2026-08-02 (review round 2: D2 confirmed as-is, no overrides). Phase 0
history: the reviewer declined to ratify the original D1-D5; every correction was verified against source (findings
F1-F6 below) and the decision set is rewritten: D1/D2 now follow the per-shape worktree-placement model, D3 is resolved,
D4 splits corrupt from unreadable, D6 is new.

## Phase 0 -- Ground and ratify

- [x] Re-verify card anchors against `main` at Phase 0 close and restamp card.md on drift. Verified 2026-08-02 (no
  further drift since the pre-verification below; card restamp not needed -- the F2/F4 corrections were applied
  directly). Pre-verified 2026-08-02: post-PR-#118 drift only -- `add_from_state` is `index.py:739` (card cites `:503`),
  `_validate_data` is `store.py:356` (card cites `:349`), `collect_bound_codex_threads` is `session_context.py:503`.
  Unchanged: `create_session_txn` `index.py:374`, `collect_bound_uuids` `session_context.py:439`, `_manifest_dirs`
  `:566`, `_detect_corrupt_state` `gc.py:702`, `resolve_project_root` `manager.py:436`, identity derivation
  `manager.py:664-692`.
- [x] **Verified premise (2026-08-02): the card's self-deleting-row claim holds.** The `list_sessions` prune predicate
  is `not worktree.exists() or not manifest_path.is_file()` (`index.py:198`, re-checked under the re-acquired lock
  before deletion), so a repaired row whose `worktree_path` does not exist is pruned on the next list even though its
  manifest exists. Every repair path must satisfy this predicate or refuse -- see D2. This predicate is also an active
  orphan *producer* -- see F2.
- [x] Confirm the transaction's in-lock uniqueness coverage. **Resolved 2026-08-02 (F5)**: no work owed --
  `create_session_txn(require_uuid_unbound=True)` already re-checks both `claude_session_id` and `codex_thread_id` via
  `_require_conversation_unbound` inside the index lock (`index.py:453-460`).
- [x] Ratify D1-D6 (review round 2). **Ratified 2026-08-02**: D2 confirmed as-is by the reviewer; no overrides to the
  revised set. Card.md corrections from F2/F4 were applied in this commit.

### Phase 0 findings (review round 1, 2026-08-02 -- each verified against source before recording)

- **F1 -- the original D1/D2 leaning rested on a false premise.** `Worktree.path` is the checkout root, not the Forge
  root (`models.py:34-42` docstring), and a **root-level** worktree session deliberately keeps its manifest under the
  *main* checkout's `.forge/` while recording the linked worktree separately (`manager.py:627-641`: "Root-level projects
  (forge_root == repo root) keep the original forge_root so manifests stay under the main .forge/"). Consequences:
  deleting a worktree does not necessarily delete its manifest; the manifest's location cannot always reconstruct the
  session checkout; and deriving identity from the scanned location would silently repoint a root-level worktree session
  at the main checkout. D1/D2 are rewritten per session shape.
- **F2 -- orphans are still produced today; this card is not historical-only cleanup.** The `list_sessions` prune drops
  any row whose recorded worktree vanished even when the manifest is durable (`index.py:198`); the creation
  transaction's residue reclaim is deliberately narrower ("the manifest is the durable reservation",
  `index.py:448-450`). Deleting a root-level session's linked worktree therefore orphans its main-checkout manifest on
  the next `session list`. The card's Problem section is corrected in this commit; whether the prune itself should stop
  dropping manifest-backed rows is deliberately out of scope (see deferred).
- **F3 -- `forge clean` removes corruption only, never unreadability.** `_detect_corrupt_state` counts only
  `StateCorruptedError`; transient read errors are deliberately ignored "so forge clean never deletes a file it merely
  failed to open" (`gc.py:714-716`, branch split at `:732-739`). The original D4's "any strict-read failure is corrupt"
  would make repair and clean disagree about ownership. D4 now splits `corrupt` from `unreadable`.
- **F4 -- manual orphan deletion is cwd-exact.** The orphan-directory branch of `session delete` resolves
  `SessionStore(str(Path.cwd()), name)` (`cli/session_manage.py:390`), so it works only from the owning Forge root
  itself, not from a descendant directory. The card's recovery wording is corrected in this commit; repair-report
  guidance must say "run from the Forge project root".
- **F5 -- D3's open question was already closed by the transaction.** Both conversation ids are re-checked in-lock
  (`index.py:453-460`); no Codex transaction arm is owed.
- **F6 -- conversation ids cannot identify a manifest at apply time.** A manifest may legitimately carry neither
  `claude_session_id` nor `codex_thread_id` (a Codex-runtime session records no thread id before its first turn), so an
  id comparison cannot prove the manifest seen during apply is the one scanned during preview. New D6 supplies a total
  rule.

### Decisions (revised after review round 1 -- ratify in round 2)

- [x] **D1 -- identity source is the recorded worktree metadata, applied per session shape; the manifest's location
  supplies only `forge_root`.** Four shapes exist (F1): *ordinary* (manifest inside its own checkout), *nested-project
  worktree* (forge_root remapped into the linked worktree, manifest inside it), *root-level worktree* (manifest under
  the main checkout, `worktree.path` records the linked worktree), and *`--into` guest* (manifest at the target
  worktree's forge_root, `owns_worktree=False` preserved from the manifest). Rule: when the recorded `worktree.path`
  exists and resolves, recompute `project_root` / `checkout_root` / `relative_path` **from the recorded path** with
  creation's own helpers (`resolve_project_root` `manager.py:436`, `get_repo_root` + fallback-to-path
  `manager.py:664-669`, `relative_to`-else-`"."` `:678-692`); `forge_root` is the scanned manifest's location.
  Assertion: a repaired row's identity fields equal what creation derives for that shape -- pinned per-shape, including
  that a root-level worktree repair records the *linked* worktree, never the main checkout.
- [x] **D2 -- a missing recorded worktree is report-only for worktree-backed shapes; location re-derivation is allowed
  only for the ordinary shape.** When the recorded `worktree.path` does not exist: `is_worktree=True` (root-level,
  nested, or guest) classifies `missing-worktree`, report-only -- a repaired row would be re-pruned immediately
  (`index.py:198`) and no trustworthy relocation exists; the report names both outs (recreate the worktree, or
  `session delete <name>` run from the owning Forge root, per F4). `is_worktree=False` (an ordinary session whose
  checkout moved carrying its manifest) may re-derive from the manifest's actual location, which for that shape is
  inside the session's own checkout by construction. Hard assertion either way: repair never writes a row the prune
  predicate immediately deletes.
- [x] **D3 -- collisions refuse, not bind; the transaction is the enforcement point. RESOLVED (F5).** Repair routes
  through `create_session_txn(require_uuid_unbound=True)`, which re-checks `claude_session_id` **and** `codex_thread_id`
  under the index lock (`index.py:453-460`); a scoped-name collision surfaces as the transaction's index-side
  `SessionExistsError`. Report classification `collision` names both the orphan manifest dir and the live holder; repair
  skips the item and continues; exit 1 when any refusal remains (mirrors `forge clean --yes` exit semantics).
- [x] **D4 -- corrupt belongs to `forge clean`; unreadable belongs to neither; repair never deletes.** Three-way split:
  `corrupt` (`StateCorruptedError` on strict read) is never repaired or removed by repair, and the report points at
  `forge clean` (`_detect_corrupt_state`, `gc.py:702`, removes exactly this class). `unreadable` (transient read errors
  -- the `StateUnreadableError`/`OSError` family) is report-only with check-permissions/retry guidance and is **not**
  pointed at clean, which deliberately ignores it (F3). Assertion: the two surfaces never disagree -- no manifest is
  both clean-removable and repairable, and no unreadable manifest is claimed by either.
- [x] **D5 -- explicit, preview-default surface: `forge session repair`** (bare = report; `--yes` = apply; `--json` on
  both), resolving the card's coupled open questions as *explicit* discovery + *explicit* repair. The command is a
  project-state mutator, so it applies the project-compatibility contract: `--yes` fails closed via
  `enforce_project_compatibility` before side effects; the bare report still runs and marks what apply would refuse
  (mirrors `forge clean` preview semantics per the impl_notes posture rules). Rejected leanings, recorded because the
  card asks for them to be weighed: automatic re-index on `session list` (surprising resurrection -- the card's own
  concern -- and classification needs manifest reads that must not make a hot read path fragile); a `forge clean`
  category (clean's verb is *remove*, repair *adds*; coordination lives at D4's ownership split instead). No `%`
  direct-command mirror in v1 (deferred below).
- [x] **D6 -- apply-time identity is a content hash, not conversation ids (F6).** The scan records each classified
  manifest's SHA-256; the transaction callback re-reads the manifest and compares bytes instead of writing
  (`create_exclusive` is never called -- the manifest already exists). Any mismatch -- vanished (a concurrent
  `session delete` resolved the orphan) or rewritten -- fails the callback, compensation removes the row, and the item
  reports `changed`/gone. Total over every manifest shape, including id-less Codex manifests.

## Phase 1 -- Discovery (read-only)

- [x] New command-core op `core/ops/session_repair.py`: `scan_repairable_orphans(forge_root)` reusing the
  `_manifest_dirs` walk (`session_context.py:566`) -- the card's constraint: reuse the existing scan shape, do not add a
  second walker. Returns typed per-manifest classifications: `repairable`, `missing-worktree`, `collision`, `corrupt`,
  `unreadable`, plus residual `unrepairable` for anything the D1/D2 rules cannot place (e.g. a manifest with no worktree
  block); manifest dirs with a live row are healthy sessions and are excluded. Each `repairable` entry carries its D6
  content hash and the D1-derived identity fields. Pure op per design.md §3.12: no Click, no printing, typed exceptions.
  *Shipped 2026-08-02: `_manifest_dirs` renamed public (`manifest_dirs`); scan tests in
  `tests/src/core/ops/test_session_repair.py` cover all six classifications and all four shapes. Round 3 (F7) replaced
  the column-only holder maps with the three-source binding scans.*
- [x] The scan mutates nothing: no index write, no prune, no manifest write. Pinned by a test asserting index bytes and
  manifest mtimes are unchanged after a scan over every classification. *`test_scan_is_read_only` seeds every
  classification and asserts index bytes + manifest `st_mtime_ns` unchanged.*
- [x] `collect_bound_uuids` / `collect_bound_codex_threads` are untouched; their read-only, fail-closed, no-prune
  contract survives (existing adoption/binding regressions stay green). *Full unit suite green (8,626 passed); the only
  session_context.py change is the `manifest_dirs` rename with both callers updated.*
- [x] CLI leaf `forge session repair` (report mode): renders classifications through `forge.cli.output` helpers,
  `--json` emits the typed result; outside a Forge project it fails through `handle_session_error`; an incompatible
  project pin is marked in the report as apply-refused (D5). Scope is the current `forge_root` only (per-project by
  design; see deferred). *`cli/session_repair.py`, registered from `cli/session.py`. Deviation from the letter of this
  item, matching sibling commands: outside-a-project is not a session error, so it fails through `print_error_with_tip`
  on `err_console` (exit 1), while scan-level index/listing failures route through `handle_session_error`/`print_error`.
  A malformed pin raises from `check_project_compatibility`; preview catches it and reports the reason instead of dying
  (apply stays fail-closed via `enforce_project_compatibility`).*

## Phase 2 -- Repair (apply)

- [x] `--yes` enforces project compatibility fail-closed before any write (`enforce_project_compatibility` on the
  scanned `forge_root`), per the impl_notes posture: explicit CLI mutations fail closed before side effects.
  *`repair_orphans` calls it before touching any record; `test_incompatible_pin_fails_closed` +
  `test_incompatible_pin_preview_warns_apply_fails`.*
- [x] Apply: for each `repairable` orphan, re-index through `create_session_txn` with the D1 identity fields and the D6
  revalidating callback. A hash mismatch or vanished manifest fails the callback, the transaction compensates the row
  away, and the item reports without aborting the batch -- no bare row survives a lost race. *The callback is
  `SessionStore.update_if_unchanged` (new; hash-verify under the manifest lock, optional D2 path correction).
  Compensation pinned by `test_changed_manifest_compensates_row`; the pre-txn hash/read re-check refusals by
  `test_tampered_manifest_refused_before_txn` and `test_manifest_deleted_between_scan_and_apply_refused`.*
- [x] Refusals are per-item: eligible orphans repair; refused items report with their classification; exit 1 if any
  refusal or failure remains. A repaired session is fully live: `session list` shows it, `session show <name>` resolves
  it, and the row survives a subsequent `list_sessions` prune pass. *Prune survival asserted in
  `test_repair_publishes_row`; exit semantics in the CLI tests; end-to-end list round-trip in the Docker test.*
- [x] Non-destructive invariants hold: repair never deletes a manifest, never modifies an existing row, never rebinds a
  conversation already bound to a live row. *Collision/uuid-race/name-claimed tests assert no row written and the live
  holder untouched; the only manifest write is the hash-gated D2 path correction.*

## Phase 2.5 -- Review round 3 fixes (2026-08-02, all verified against source before fixing)

- [x] **F7 (critical) -- collision detection was column-only; D3's no-double-binding invariant was violated.** A live
  manifest binding not yet reconciled into its row column (`index.py:807` syncs lazily; `collect_bound_uuids` documents
  that rows "can lag a manifest -- and ... can also lead one") let an orphan sharing that conversation classify
  `repairable` and publish a second binding. Fix: the scan now builds holders from `collect_bound_uuids()` /
  `collect_bound_codex_threads()` called **without** a `forge_root` -- rows plus the manifest behind each row,
  fail-closed, and no per-root orphan walk so the manifests under classification are not counted as live holders.
  Sibling orphans sharing one conversation resolve deterministically (directory-order first stays repairable, later ones
  classify `collision`). The in-lock column check remains the final race arbiter. Tests:
  `test_collision_when_row_column_lags_live_manifest`, `test_collision_when_thread_lives_only_on_live_manifest`,
  `test_sibling_orphans_sharing_conversation`.
- [x] **F8 -- moved ordinary repair left `state.forge_root` stale; `confirmed.claude_project_root` semantics were
  undefined.** Resume consumes both (`claude_session.py:408`). Fix: the D6 mutation now also relocates `forge_root` (and
  the in-memory copy the row is built from); `claude_project_root` is **deliberately preserved** -- per
  `models.py:645-649` it records Claude Code's conversation namespace (`~/.claude/projects/<encoded-cwd>/`), which a
  checkout move does not relocate. The moved-ordinary identity now records the derived `checkout_root` as
  `worktree.path` (the field's contract), not the forge root. Test:
  `test_moved_repair_relocates_forge_root_not_claude_namespace` (manager-shaped fixture: `forge_root` wired, launch CWD
  recorded).
- [x] **F9 -- a manifest naming a different session than its directory produced a false repair.** The scan named records
  from the directory but apply indexed `state.name`, publishing a row whose manifest path does not exist (the next list
  prunes it -- exactly D2's forbidden outcome). Fix at the invariant's owner: `SessionStore.read()` now raises
  `ManifestCorruptedError` on directory/name mismatch (write already enforced it; store.py:14 "The directory name IS the
  session name"), so repair classifies it `corrupt` and `forge clean` removes it -- shared D4 ownership. Tests:
  `test_dir_name_mismatch_is_corrupt`, `test_read_rejects_directory_name_mismatch`, ownership-disjoint test extended.
  Fallout: two store tests seeded `name: "test"` under `test-session/`; fixture data corrected.
- [x] **F10 -- valid JSON with a non-object top level (`[]`) crashed the scan with a raw `AttributeError`.**
  `SessionStore.read()` assumed a mapping before validation. Fix: explicit `isinstance(data, dict)` check raising
  `ManifestCorruptedError`, so the scan classifies `corrupt` and `forge clean` gains the same detection. Tests:
  `test_non_dict_manifest_is_corrupt`, `test_read_rejects_non_dict_json`.
- [x] **F11 -- typed scan/apply errors routed to stdout.** `handle_session_error(e, console=console)` forwarded the
  stdout console into the corrupt/unreadable handlers, so `repair --json` with a corrupt index emitted Rich error text
  on stdout. Fix: bare `handle_session_error(e)` (defaults to the stderr console), matching `session_manage`. Repair
  added to the stream-contract guard: `test_session_repair_json_on_stdout_with_clean_stderr`,
  `test_session_repair_json_failure_keeps_stdout_clean` in `tests/src/cli/test_output_streams.py`.
- [x] Coverage claims corrected: `test_scan_is_read_only` now seeds `unreadable` too (previously claimed "every
  classification" while omitting it), and the D6 acceptance fixture (id-less Codex orphan replaced between scan and
  apply) now runs through the full `repair_orphans` path (`test_idless_codex_orphan_replaced_between_scan_and_apply`) in
  addition to the direct txn-compensation test.

## Phase 3 -- Docs, verification, closeout

- [x] design.md §3.2: replace the "Repairing pre-existing orphans is not yet implemented" sentence (`design.md:267`)
  with the shipped repair surface, including the F2 producer (worktree-vanished prune) so the orphan population is
  described as live, not only historical. *The F2 producer paragraph was already added to §3.2 at activation; the
  replacement paragraph now describes classifications, D1 identity, and the D6 callback.*
- [x] cli_reference.md §1 session table gains `forge session repair`; `docs/end-user/session.md` gains the recovery flow
  (naming the run-from-forge-root requirement, F4). *End-user section "Repairing invisible sessions" + cheat-sheet
  entry; report guidance names the Forge root for `session delete` (F4).*
- [x] Targeted integration run -- session lifecycle is touched, so the integration tier is mandatory per
  testing_guidelines: `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py` plus repair
  coverage. *22 passed 2026-08-02, including the new `test_repair_reindexes_orphaned_manifest` round-trip (drop row,
  preview classifies, `--yes` re-indexes, `session list` shows it).*
- [x] `make pre-commit` clean. *Clean 2026-08-02 (second run after formatter re-stage, per repo convention).*

## Acceptance tests

| Test                           | Fixture                                                           | Assertion                                                               | Test File                                            |
| ------------------------------ | ----------------------------------------------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------- |
| Orphan discovered              | seeded manifest-without-row, live recorded worktree               | classified `repairable`; nothing mutated                                | `tests/src/core/ops/test_session_repair.py`          |
| Healthy session excluded       | normal session (row + manifest)                                   | absent from the report                                                  | same                                                 |
| Repair re-indexes              | repairable orphan                                                 | row added via `create_session_txn`; `session list` shows it             | same                                                 |
| Identity parity per shape      | ordinary, nested-worktree, root-level-worktree, `--into` fixtures | repaired row fields equal creation-derived values for that shape        | same                                                 |
| Root-level placement preserved | root-level worktree orphan, linked worktree alive                 | repaired row records the linked worktree, not the main checkout         | same                                                 |
| Missing worktree report-only   | root-level worktree orphan, linked worktree deleted (F2 state)    | `missing-worktree`; no row written; guidance names both outs            | same                                                 |
| Moved ordinary checkout        | `is_worktree=False` orphan, checkout relocated with manifest      | repaired from actual location; row survives the prune                   | same                                                 |
| Prune stability                | every repaired row                                                | survives the next `list_sessions` prune pass                            | same                                                 |
| UUID collision refused         | orphan `claude_session_id` held by a live row                     | `collision`; no row written; live row untouched                         | same                                                 |
| Codex thread collision refused | orphan `codex_thread_id` held by a live row                       | `collision`; no row written                                             | same                                                 |
| Name-taken refused             | live row owns the scoped name                                     | transaction `SessionExistsError`; live session untouched                | same                                                 |
| Corrupt manifest deferred      | manifest raising `StateCorruptedError`                            | `corrupt`; untouched; report names `forge clean`                        | same                                                 |
| Unreadable is not corrupt      | manifest raising a transient read error                           | `unreadable`; untouched; check/retry guidance; clean not named          | same                                                 |
| Clean/repair ownership agree   | corrupt + unreadable + repairable fixtures side by side           | clean removes only the corrupt one; repair claims only the repairable   | same                                                 |
| Unrepairable residual          | manifest the D1/D2 rules cannot place (no worktree block)         | `unrepairable`; report-only; names `session delete` from the Forge root | same                                                 |
| Apply-time identity (D6)       | id-less Codex orphan replaced between scan and apply              | hash mismatch fails callback; compensation removes row; item reports    | same                                                 |
| Concurrent delete mid-repair   | manifest removed between scan and transaction callback            | callback fails; compensation removes the row; item reports gone         | same                                                 |
| Scan is read-only              | all classifications seeded                                        | index bytes + manifest mtimes unchanged after scan                      | same                                                 |
| Compatibility pin refusal      | incompatible `.forge/project.toml`                                | `--yes` fails closed before any write; bare report marks apply-refused  | same                                                 |
| CLI report, apply, JSON        | mixed fixtures                                                    | preview default; `--yes` applies; `--json` stable; exit 1 on refusals   | `tests/src/cli/test_session_repair.py`               |
| Binding scans unchanged        | existing suites                                                   | adoption/binding regressions green                                      | existing                                             |
| Lifecycle E2E                  | Docker                                                            | start/fork/resume/delete plus a repair round-trip green                 | `tests/integration/docker/test_session_lifecycle.py` |

## Blockers / deferred decisions

No external blockers. Phases 1+ are gated on ratifying the revised D1-D6 (review round 2). Deferred out of this card: a
`%session repair` direct-command mirror (scope-policy call; low value until the terminal surface settles);
cross-project/global orphan discovery (`_manifest_dirs` is per-`forge_root` by design -- a global sweep is a new
decision, not an extension of this one; the card records the same limit under item 5); and whether the `list_sessions`
prune should stop dropping manifest-backed rows whose worktree vanished (F2's producer) -- that would close the producer
at the source but changes a deliberate prune contract (`index.py:448-450` documents the asymmetry), so it is a separate
design call; repair handles the state either way.

## Closeout

Shipped in PR #120, merged to `main` 2026-08-02 as `2fe4848a`.

- [x] Final checklist items ticked with verification recorded. *Phases 0-3 plus review-round-3 fixes F7-F11, each with
  its verifying test named inline.*
- [x] Compact `docs/board/change_log.md` entry (Goal / Key changes / Verification). *Added at closeout, newest-first.*
- [x] Durable lessons proposed via `.forge/memory/shadow_impl_notes.md`; human review promotes to
  `docs/board/impl_notes.md`. *Five proposals appended at closeout.*
- [x] design.md, cli_reference.md, and end-user docs verified against shipped behavior. *design.md §3.2 describes the
  shipped scan/apply semantics (including round-3 collision and relocation rules), cli_reference.md session table has
  the command, end-user session.md has "Repairing invisible sessions".*
- [x] Move the card `doing/ -> done/`; repoint inbound links. *`git mv` at closeout; the four
  `done/session_create_crash_atomicity` links (card.md:122, checklist.md:48/:229/:289) repointed to `../../done/`.
  design.md no longer links the card path -- the activation-era pointer was replaced by the shipped-surface paragraph in
  Phase 3, so no design.md repoint is owed.*

Verification at closeout: `uv run pytest tests/src -m "not integration"` (8,640 deselection-side green earlier same day:
8,639 passed), `uv run pytest tests/src -m integration` (117 passed -- the CIT tier `-m "not integration"` deselects;
run per impl_notes), `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py` (22 passed,
includes the end-to-end repair round-trip), `make pre-commit` clean.
