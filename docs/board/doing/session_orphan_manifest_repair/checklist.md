# Checklist -- session_orphan_manifest_repair

**Card**: [card.md](card.md). Branch: `feat/session-orphan-manifest-repair`.

**Current focus**: Phase 0 -- decision ratification. D1-D5 below carry **leanings, not decisions**. Nothing past Phase 0
starts until they are ratified or overridden in review.

## Phase 0 -- Ground and ratify

- [ ] Re-verify card anchors against `main`. Pre-verified 2026-08-02 while drafting this checklist; post-PR-#118 drift
  only: `add_from_state` is `index.py:739` (card cites `:503`), `_validate_data` is `store.py:356` (card cites `:349`),
  `collect_bound_codex_threads` is `session_context.py:503`. Unchanged: `create_session_txn` `index.py:374` with the
  `require_uuid_unbound` kwarg (`:382`), `collect_bound_uuids` `session_context.py:439`, `_manifest_dirs` `:566`,
  `_detect_corrupt_state` `gc.py:702`, `resolve_project_root` `manager.py:436`, identity derivation `manager.py:667`
  (`get_repo_root(Path(worktree_path))`). Restamp card.md if further drift lands before Phase 1.
- [ ] **Verified premise (2026-08-02): the card's self-deleting-row claim holds.** The `list_sessions` prune predicate
  is `not worktree.exists() or not manifest_path.is_file()` (`index.py:198`, re-checked under the re-acquired lock
  before deletion), so a repaired row whose `worktree_path` does not exist is pruned on the next list even though its
  manifest exists. Every repair path must satisfy this predicate or refuse -- see D2.
- [ ] Confirm the transaction's in-lock uniqueness coverage: `require_uuid_unbound` guards `claude_session_id`; verify
  whether an equivalent in-lock check exists for `codex_thread_id` (the adopt path re-checks it under the index lock)
  and whether repair can reuse it or `create_session_txn` needs the codex arm too. Feeds D3.
- [ ] Ratify D1-D5. Record each decision inline with rationale; correct card.md wherever a decision contradicts it.

### Decisions (leanings -- ratify in review)

- [ ] **D1 -- identity reconstruction: derive from where the manifest actually is, not from what it records.** Recompute
  `project_root` / `checkout_root` / `relative_path` with the same helpers creation uses (`get_repo_root`,
  `resolve_project_root`, `relative_to` -- `manager.py:658-678`), anchored at the scanned manifest's on-disk
  `forge_root`. The manifest's recorded worktree metadata is exactly the field that goes stale when a checkout moves, so
  it is a cross-check, never the source. Mirror creation's fallback when `get_repo_root` fails (fall back to the anchor
  path, per `manager.py:665`). Assertion: a repaired row's identity fields equal what `start_session` would derive for a
  new session in the same checkout.
- [ ] **D2 -- missing/stale worktree: repair what re-derivation fixes; report-only what it cannot.** The reachable case
  for a per-project scan is a *stale recorded path* (the checkout moved on disk) -- a truly deleted worktree deletes its
  manifests with it, so that orphan is unreachable by this scan. When D1's re-derivation succeeds at the actual
  location, the repaired row records the current location and survives the prune predicate -- no write-then-self-delete
  churn. When the actual location is not a usable checkout, classify `unrepairable` (report-only; name
  `session delete <name>` as the manual out). Hard assertion either way: repair never writes a row the prune predicate
  immediately deletes.
- [ ] **D3 -- collisions refuse, not bind; the transaction is the enforcement point.** Route repair through
  `create_session_txn(require_uuid_unbound=True)` so conversation uniqueness is re-checked inside the index lock (plus
  the codex-thread arm per the Phase 0 coverage check); a scoped-name collision surfaces as the transaction's index-side
  `SessionExistsError`. Report classification `collision` names both the orphan manifest dir and the live holder; repair
  skips it and continues with other items; exit 1 when any refusal remains (mirrors `forge clean --yes` exit semantics).
- [ ] **D4 -- malformed manifests belong to `forge clean`; repair never deletes.** A manifest failing the strict read
  (`store.py:356`) classifies as `corrupt`, is never repaired or removed, and the report points at `forge clean`
  (`_detect_corrupt_state`, `gc.py:702`, already owns corrupt-manifest removal). Assertion: the two surfaces never
  disagree about ownership -- no manifest is simultaneously clean-removable and repair-repairable.
- [ ] **D5 -- explicit, preview-default surface: `forge session repair`** (bare = report; `--yes` = apply; `--json` on
  both), resolving the card's coupled open questions as *explicit* discovery + *explicit* repair. Rejected leanings,
  recorded because the card asks for them to be weighed: automatic re-index on `session list` (surprising resurrection
  -- the card's own concern -- and orphan classification needs manifest reads that must not make a hot read path
  fragile); a `forge clean` category (clean's verb is *remove*, repair *adds*; coordination with clean lives at D4's
  ownership split instead). No `%` direct-command mirror in v1 (deferred below).

## Phase 1 -- Discovery (read-only)

- [ ] New command-core op `core/ops/session_repair.py`: `scan_repairable_orphans(forge_root)` reusing the
  `_manifest_dirs` walk (`session_context.py:566`) -- the card's constraint: reuse the existing scan shape, do not add a
  second walker. Returns typed per-manifest classifications: `repairable`, `collision`, `corrupt`, `unrepairable`;
  manifest dirs with a live row are healthy sessions and are excluded. Pure op per design.md §3.12: no Click, no
  printing, typed exceptions.
- [ ] The scan mutates nothing: no index write, no prune, no manifest write. Pinned by a test asserting index bytes and
  manifest mtimes are unchanged after a scan over every classification.
- [ ] `collect_bound_uuids` / `collect_bound_codex_threads` are untouched; their read-only, fail-closed, no-prune
  contract survives (existing adoption/binding regressions stay green).
- [ ] CLI leaf `forge session repair` (report mode): renders classifications through `forge.cli.output` helpers,
  `--json` emits the typed result; outside a Forge project it fails through `handle_session_error`. Scope is the current
  `forge_root` only (per-project by design; see deferred).

## Phase 2 -- Repair (apply)

- [ ] `--yes` apply: for each `repairable` orphan, rebuild identity per D1 and re-index through `create_session_txn`.
  The manifest callback **revalidates instead of writing**: the manifest already exists, so the callback re-reads it and
  confirms it is the same manifest the scan classified (same UUID/thread), never `create_exclusive`. A manifest that
  vanished between scan and commit (a concurrent `session delete` resolving the orphan the manual way) fails the
  callback, the transaction compensates the row away, and the item reports as gone -- no bare row survives a lost race.
- [ ] Refusals are per-item: eligible orphans repair; refused items report with their classification; exit 1 if any
  refusal or failure remains. A repaired session is fully live: `session list` shows it, `session show <name>` resolves
  it, and the row survives a subsequent `list_sessions` prune pass.
- [ ] Non-destructive invariants hold: repair never deletes a manifest, never modifies an existing row, never rebinds a
  conversation already bound to a live row.

## Phase 3 -- Docs, verification, closeout

- [ ] design.md §3.2: replace the "Repairing pre-existing orphans is not yet implemented" sentence (`design.md:267`)
  with the shipped repair surface; the binding scans' orphan rationale stays (orphans remain producible by older Forge
  versions until repaired).
- [ ] cli_reference.md §1 session table gains `forge session repair`; `docs/end-user/session.md` gains the recovery
  flow.
- [ ] Targeted integration run -- session lifecycle is touched, so the integration tier is mandatory per
  testing_guidelines: `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py` plus repair
  coverage.
- [ ] `make pre-commit` clean.

## Acceptance tests

| Test                           | Fixture                                                  | Assertion                                                             | Test File                                            |
| ------------------------------ | -------------------------------------------------------- | --------------------------------------------------------------------- | ---------------------------------------------------- |
| Orphan discovered              | seeded manifest-without-row                              | classified `repairable`; nothing mutated                              | `tests/src/core/ops/test_session_repair.py`          |
| Healthy session excluded       | normal session (row + manifest)                          | absent from the report                                                | same                                                 |
| Repair re-indexes              | repairable orphan, derivable identity                    | row added via `create_session_txn`; `session list` shows it           | same                                                 |
| Identity parity                | repaired row vs fresh `start_session` row, same checkout | `project_root`/`checkout_root`/`relative_path` equal                  | same                                                 |
| Prune stability                | repaired row                                             | survives the next `list_sessions` prune pass                          | same                                                 |
| UUID collision refused         | orphan `claude_session_id` held by a live row            | `collision`; no row written; live row untouched                       | same                                                 |
| Codex thread collision refused | orphan `codex_thread_id` held by a live row              | `collision`; no row written                                           | same                                                 |
| Name-taken refused             | live row owns the scoped name                            | transaction `SessionExistsError`; live session untouched              | same                                                 |
| Corrupt manifest deferred      | manifest failing strict read                             | `corrupt`; untouched; report names `forge clean`                      | same                                                 |
| Clean/repair ownership agree   | corrupt + repairable fixtures side by side               | no manifest is both clean-removable and repairable                    | same                                                 |
| Unrepairable reported          | manifest at a non-checkout location, derivation fails    | `unrepairable`; report-only; names `session delete`                   | same                                                 |
| Concurrent delete mid-repair   | manifest removed between scan and transaction callback   | callback fails; compensation removes the row; item reports gone       | same                                                 |
| Scan is read-only              | all classifications seeded                               | index bytes + manifest mtimes unchanged after scan                    | same                                                 |
| CLI report, apply, JSON        | mixed fixtures                                           | preview default; `--yes` applies; `--json` stable; exit 1 on refusals | `tests/src/cli/test_session_repair.py`               |
| Binding scans unchanged        | existing suites                                          | adoption/binding regressions green                                    | existing                                             |
| Lifecycle E2E                  | Docker                                                   | start/fork/resume/delete plus a repair round-trip green               | `tests/integration/docker/test_session_lifecycle.py` |

## Blockers / deferred decisions

No external blockers. Phases 1+ are gated on D1-D5 ratification (this review). Deferred out of this card: a
`%session repair` direct-command mirror (scope-policy call; low value until the terminal surface settles), and
cross-project/global orphan discovery (`_manifest_dirs` is per-`forge_root` by design -- a global sweep is a new
decision, not an extension of this one; the card records the same limit under item 5).

## Closeout

- [ ] Final checklist items ticked with verification recorded.
- [ ] Compact `docs/board/change_log.md` entry (Goal / Key changes / Verification).
- [ ] Durable lessons proposed via `.forge/memory/shadow_impl_notes.md`; human review promotes to
  `docs/board/impl_notes.md`.
- [ ] design.md, cli_reference.md, and end-user docs verified against shipped behavior.
- [ ] Move the card `doing/ -> done/`; repoint inbound links (`design.md:267`'s lane path and the three
  `done/session_create_crash_atomicity` links repointed to `doing/` at activation need the done-lane repoint again).
