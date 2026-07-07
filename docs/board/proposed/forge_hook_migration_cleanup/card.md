# Hook migration + legacy cleanup

**Epic**: [`docs/board/doing/epic_global_forge_runtime/card.md`](../../doing/epic_global_forge_runtime/card.md)

**Lane**: `proposed/`. Depends on `user_scope_hook_ownership` (the target model exists to migrate to). End of the
user-scope-model critical path.

## Goal

Migrate existing installs to the user-dispatcher model with **no persistent double-fire state**, detect and clean legacy
project-local Forge hook registrations, and warn explicitly about the Codex re-trust requirement.

## Why

A partially migrated project could run **both** a legacy bare/absolute `forge hook` and the new dispatcher. The end
state must be single-source; the **transient** window is unavoidable (the project hook and the user dispatcher live in
different files and cannot be updated atomically together), so the migration picks the least-harmful order and reports
the assumption rather than claiming an impossible atomic swap.

## Cleanup is two different mechanisms (2026-07-02 finding)

Codex and Claude registrations are removed by **different** mechanisms; the cleanup command must branch, not treat them
uniformly:

- **Codex -> marker-block removal.** The managed block is delimited by byte-stable markers (`CODEX_BLOCK_BEGIN`/`END`,
  `codex_hooks.py:56`); removal deletes exactly the Forge block, and a whitespace-only remainder deletes the file.
  Robust even for manually-placed blocks, as long as the markers are intact.
- **Claude -> tracked, value-based unmerge.** Claude settings are merged per hook entry and removed via
  `unmerge(settings, tracking_entries)` using each entry's `stable_id` (value-based, not index-based)
  (`settings_merge.py:702,731`), reconciled against `~/.forge/installed.json`.
- **Legacy / manual installs (the hard case).** A hand-added Claude hook, an install whose tracking entries were lost,
  or entries created by the removed second writer have **no `stable_id` to unmerge against**. Cleanup then needs a
  value-based fallback: match a hook entry by its command form (bare `forge hook <name>`, the absolute-path form from
  `forge_hook_absolute_command`, or the dispatcher form) and remove it, backing up first. Report anything ambiguous
  rather than guessing.

## Scope

**In:**

- **Sequenced migration** (least-harmful order): two files cannot be swapped atomically, so choose the order whose
  *transient* failure is safest -- prefer **removing the failing legacy hook first** (a brief hooks-off gap: tools run,
  no enforcement) over install-first (a brief double-fire / exit-127). Where a single file owns both entries, stage it
  atomically (write-temp + rename). Report the window; do not claim there is none.
- **Discover projects to migrate via `installed.json` backfill.** `installed.json` keys tracked installs by root
  (`local:` / `project:<abs>`, `install/models.py`); enumerate those roots to enroll existing projects into
  `projects.toml` (`forge_project_registry`), so migration finds installs without a manual per-project step.
- `forge extension cleanup-project`: Codex marker removal + Claude tracked/value-based removal (above).
- `doctor`/`status` detection for legacy project hooks that could **not** be auto-cleaned (report, do not silently
  pass).
- **Codex re-trust notice**: changing the command string invalidates Codex enrollment; enable/sync must print the
  re-trust requirement. Forge cannot verify the user completed the trust ceremony.

**Out:** the user-scope registration change itself (`user_scope_hook_ownership`); the dispatcher
(`forge_hook_dispatcher`).

## Grounding (verified 2026-07-02)

- Codex managed block markers are byte-stable and detection keys on them: `codex_hooks.py:54-57`.
- Claude merge/`unmerge` is tracked + `stable_id` value-based: `settings_merge.py:702,731`.
- Codex trust is pinned to command bytes and the installer **cannot compute** `trusted_hash` (`codex_hooks.py:13-19`) --
  so the re-trust notice is mandatory, not optional.

## Risks

- **Migration window** with both a failing/duplicate bare hook and the dispatcher active (the core hazard).
- **Non-atomic remove-then-install (the chosen order).** Scope picks remove-legacy-first, so the transient window is a
  brief **hooks-off gap** -- a session launching between removing the legacy hook and installing the dispatcher runs
  with no Forge hooks (tools run, no enforcement), **not** a double-fire. This is deliberately the least-harmful
  failure: a momentary enforcement gap is preferable to the install-first hazard (double-fire / exit-127 that blocks the
  tool outright). Where a single file owns both entries, stage it atomically (write-temp + rename); across two files,
  report the window rather than claim an impossible atomic swap.
- **Codex trust reset** -- unavoidable when the command bytes change; make it explicit, never silent.
- **Un-cleanable legacy** (manual edits, lost tracking, broken markers) -- must be reported, not passed over.

## Open questions

- How aggressive should the Claude value-based fallback be when there is no tracking entry and the command was
  hand-edited (auto-remove vs report-only)?

## Acceptance tests

| Test                      | Fixture                                                             | Assertion                                                                                                       | Test File                                |
| ------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| No persistent double-fire | legacy project hook + new user hook                                 | end state has exactly one active Forge hook source; the transient window is reported, not silently assumed away | `tests/src/cli/test_extension_enable.py` |
| Backfill from installed   | existing `installed.json` roots, empty `projects.toml`              | migration enrolls those roots into the registry without manual steps (moved from `forge_project_registry`)      | `tests/src/cli/test_extension_enable.py` |
| Codex marker cleanup      | project `.codex/config.toml` with a Forge block + unrelated entries | only the marker-delimited Forge block is removed                                                                | `tests/src/install/test_codex_hooks.py`  |
| Claude tracked unmerge    | project `.claude/settings.json` with tracked Forge hooks            | `unmerge` removes only Forge entries by `stable_id`; unrelated entries kept                                     | `tests/src/install/test_installer.py`    |
| Claude legacy fallback    | Claude hook present with no tracking entry                          | value-based match removes it (or reports it if ambiguous)                                                       | same                                     |
| Codex re-trust notice     | legacy bare hook -> dispatcher hook                                 | enable/sync prints the re-trust requirement                                                                     | `tests/src/install/test_codex_hooks.py`  |
