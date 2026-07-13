# Hook migration + legacy cleanup

**Epic**: [`docs/board/done/epic_global_forge_runtime/card.md`](../../done/epic_global_forge_runtime/card.md)

**Lane**: `done/`. Shipped via PR #96 on 2026-07-11. Depends on `user_scope_hook_ownership` (the target model exists to
migrate to). This closes the user-scope-model critical path.

## Goal

Migrate selected existing installs to the user-dispatcher model, detect and clean legacy project-local Forge hook
registrations, and warn explicitly about the Codex re-trust requirement. A successful per-root cleanup must end with one
active Forge hook source; unresolved registrations in other roots remain visible without blocking the user's own
dispatcher installation.

## Why

A partially migrated project could run **both** a legacy bare/absolute `forge hook` and the new dispatcher. A completed
cleanup for that project must be single-source; the **transient** window is unavoidable (the project hook and the user
dispatcher live in different files and cannot be updated atomically together), so the migration picks the least-harmful
order and reports the assumption rather than claiming an impossible atomic swap.

## Cleanup is two different mechanisms (2026-07-02 finding)

Codex and Claude registrations are removed by **different** mechanisms; the cleanup command must branch, not treat them
uniformly:

- **Codex -> marker-block removal.** The managed block is delimited by byte-stable markers (`CODEX_BLOCK_BEGIN`/`END`,
  `codex_hooks.py:56`); removal deletes exactly the Forge block, and a whitespace-only remainder deletes the file.
  Robust even for manually-placed blocks, as long as the markers are intact.
- **Claude -> tracked, full-entry unmerge.** Claude settings are merged per hook entry and removed via
  `unmerge(settings, tracking_entries)` by canonical equality against each tracked `entry.value` (value-based, not
  index-based). Hook `stable_id` stores the same canonical JSON identity but is not independently consulted by the hook
  removal branch (`settings_merge.py`), and tracking is reconciled against `~/.forge/installed.json`.
- **Legacy / manual installs (the hard case).** A hand-added Claude hook, an install whose tracking entries were lost,
  or entries created by the removed second writer have **no `stable_id` to unmerge against**. Cleanup then needs a
  value-based fallback: normalize the command form, require an otherwise exact match to a frozen known-released legacy
  shape, and remove it after backup. T2 `forge_hook_absolute_command` was skipped, so no Forge-shipped T2
  absolute-command state is expected; the shared token predicate still recognizes that form if it is encountered. Report
  anything ambiguous rather than guessing.

## Scope

**In:**

- **Explicit per-root sequenced migration** (least-harmful order): two files cannot be swapped atomically, so choose the
  order whose *transient* failure is safest -- prefer **removing the failing legacy hook first** (a brief hooks-off gap:
  tools run, no enforcement) over install-first (a brief double-fire / exit-127). Where a single file owns both entries,
  stage it atomically (write-temp + rename). Report the window; do not claim there is none.
- **Discover projects to migrate from `installed.json` without enrolling them.** `installed.json` keys tracked installs
  by root (`local:` / `project:<abs>`, `install/models.py`); user-scope lifecycle commands may enumerate those roots and
  report exact cleanup commands, but must leave `projects.json` unchanged.
- User-scope `enable`/`sync`: consolidate safe legacy siblings in user settings, ensure the user dispatcher, and report
  tracked roots needing cleanup. These commands never edit project/local files or enroll another root.
- `forge extension cleanup-project`: preview one selected root and, only with `--yes`, perform Codex marker removal plus
  Claude tracked/value-based removal (above), ensure the user dispatcher, then enroll that root as the final ambient
  activation step.
- `doctor`/status-line detection for legacy project hooks that could **not** be auto-cleaned (report, do not silently
  pass). `forge extension status` remains the installation/tracking surface and gains no migration-state contract.
- **Codex re-trust notice**: changing the command string invalidates Codex enrollment; any enable/sync/cleanup operation
  that changes it must print the re-trust requirement. Forge cannot verify the user completed the trust ceremony.

**Out:** the user-scope registration change itself (`user_scope_hook_ownership`); the dispatcher
(`forge_hook_dispatcher`); any new migration diagnostics in `forge extension status`.

## Grounding (verified 2026-07-02; refreshed 2026-07-10)

- Codex managed block markers are byte-stable and detection keys on them: `codex_hooks.py:54-57`.
- Claude merge/`unmerge` is tracked + `stable_id` value-based: `settings_merge.py:702,731`.
- Codex trust is pinned to command bytes and the installer **cannot compute** `trusted_hash` (`codex_hooks.py:13-19`) --
  so the re-trust notice is mandatory, not optional.
- Project-scope `.claude/settings.json` is team-shared and checked in. User-scope enable/sync therefore has no implied
  authority to edit it, especially in another checkout.
- The known released legacy writer history has one observed structural hook generation, but the migration inventory must
  be frozen and additive so later current-preset changes do not strand genuine old output.
- `has_forge_hook_double_fire()` requires duplicate `(event, matcher, handler)` registrations; cleanup-required is a
  separate diagnostic state, not a broader interpretation of `HOOKx2`.
- `_should_dispatch()` runs when `FORGE_SESSION` is set or the current root is enrolled. Registry enrollment therefore
  changes hook behavior in that checkout; it is not inert discovery metadata and must occur only after selected-root
  legacy cleanup and user-dispatcher installation succeed.

## Risks

- **Unresolved roots after user enable.** In an unenrolled ambient root, the user dispatcher no-ops and the legacy hook
  remains the single active source; `FORGE_SESSION` already bypasses that gate. User enable/sync must report cleanup
  candidates without enrolling them or widening double-fire to ambient sessions. Already-enrolled legacy roots remain an
  existing risk surfaced by doctor and the status line.
- **Non-atomic remove-then-install (the chosen order).** Scope picks remove-legacy-first, so the transient window is a
  brief **hooks-off gap** -- a session launching between removing the legacy hook and completing user registration plus
  final enrollment may run with no Forge hooks (tools run, no enforcement), **not** a double-fire. This is deliberately
  the least-harmful failure: a momentary enforcement gap is preferable to the install-first hazard (double-fire /
  exit-127 that blocks the tool outright). Where a single file owns both entries, stage it atomically (write-temp +
  rename); across files, report the window rather than claim an impossible atomic swap.
- **Codex trust reset** -- unavoidable when the command bytes change; make it explicit, never silent.
- **Un-cleanable legacy** (manual edits, lost tracking, broken markers) -- must be reported, not passed over.

## Implemented decisions

- Freeze known released legacy direct-hook shapes as an additive migration inventory; exact known shapes may be removed
  after command normalization, while hand-edited or otherwise ambiguous entries remain report-only.
- Reserve project/local mutation for an explicit previewed `cleanup-project --root ... --yes`; ordinary user-scope
  enable/sync may report tracked roots but must not dirty repository checkouts or enroll them. Successful cleanup
  enrolls its selected root only after legacy removal and user-dispatcher installation.

## Acceptance tests

| Test                      | Fixture                                                             | Assertion                                                                               | Test File                                              |
| ------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| No persistent double-fire | selected legacy project hook + new user hook                        | successful cleanup ends with one active Forge source; the transient window is reported  | `tests/src/cli/test_extension_enable.py`               |
| Candidate discovery       | existing `installed.json` roots, empty `projects.json`              | roots receive cleanup guidance while the registry and checkouts remain unchanged        | `tests/src/cli/test_extension_enable.py`               |
| Cross-repo behavior       | two legacy roots + user-scope enable                                | dispatcher still no-ops for ambient events in both roots; no enrollment is added        | `tests/src/install/test_hook_dispatcher.py`            |
| Final activation ordering | unenrolled legacy root + installed user dispatcher                  | cleanup removes legacy, verifies user registration, then enrolls the selected root last | `tests/src/cli/test_extension_enable.py`               |
| Historical shape          | known released legacy shape + changed current inventory             | the released shape remains removable; an unknown shape remains report-only              | `tests/src/install/test_hook_migration.py`             |
| Codex marker cleanup      | project `.codex/config.toml` with a Forge block + unrelated entries | only the marker-delimited Forge block is removed                                        | `tests/src/install/test_codex_hooks.py`                |
| Claude tracked unmerge    | project `.claude/settings.json` with tracked Forge hooks            | full-entry unmerge removes only tracked Forge entries; unrelated entries kept           | `tests/src/install/test_installer.py`                  |
| Claude legacy fallback    | Claude hook present with no tracking entry                          | value-based match removes it (or reports it if ambiguous)                               | `tests/src/install/test_hook_migration.py`             |
| Doctor cleanup state      | lone legacy source, then a genuine duplicate                        | cleanup-required and actual double-fire remain independent                              | `tests/src/install/test_doctor.py`                     |
| Status-line distinction   | lone legacy source, then a genuine duplicate                        | lone legacy is not shown as `HOOKx2`; a genuine duplicate still is                      | `tests/src/cli/statusline/test_statusline_registry.py` |
| Codex re-trust notice     | legacy bare hook -> dispatcher hook                                 | the command-changing operation prints the re-trust requirement                          | `tests/src/install/test_codex_hooks.py`                |
