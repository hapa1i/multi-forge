# Reconcile the second hook writer (`forge hook enable`/`disable`)

**Epic**: [`docs/board/proposed/epic_global_forge_runtime/card.md`](../epic_global_forge_runtime/card.md)

**Lane**: `proposed/`. Cross-cutting -- pairs with `forge_hook_absolute_command` (the byte form it must match) and
`forge_hook_migration_cleanup` (which it can undo). No hard ordering dependency, but the update-or-delete decision must
land **before** `forge_hook_migration_cleanup` finalizes, or this writer resurrects exactly the state cleanup removes.

## Goal

Decide and execute: **update or delete** the parallel `forge hook enable` / `forge hook disable` writer so it stops
being a second, untracked hook-registration path whose command form and matcher are incompatible with every other
member.

## Why

Forge has **two** hook writers, not one:

1. `forge extension enable` -- the tracked installer path (`installer.py` -> `merge_hooks`, `installed.json`), which T2
   and T5 rewrite.
2. `forge hook enable` / `disable` (`cli/hooks/install.py`) -- a separate command that writes bare `forge hook <name>`
   entries straight into `settings.local.json` with **no `installed.json` tracking** (`install.py:130-134`), and cleans
   up with `_is_forge_hook_entry`, a **prefix** match on `cmd.strip().startswith("forge hook ")` (`install.py:139-164`).

That second writer is a drift source the epic cannot ignore:

- **It resurrects the legacy state.** It emits bare, PATH-dependent `forge hook <name>` -- exactly the exit-127 form T2
  fixes and T6 cleans. A user who runs it post-migration reintroduces the incident and a double-fire.
- **Its matcher is a third, incompatible form.** The prefix `startswith("forge hook ")` does **not** match T2's
  `/abs/.../forge hook <name>` and does not match a `forge-hook` dispatcher shim. So it neither detects nor cleans the
  forms the rest of the epic ships (epic shared contract, seam 1).
- **It is untracked**, so T6's tracked `unmerge` (`settings_merge.py:731`, keyed on `stable_id`) cannot remove its
  entries -- they only fall to T6's value-based fallback.

## Decision (update or delete)

- **Delete (likely).** Fold enable/disable into `forge extension enable`, remove the command and `_is_forge_hook_entry`.
  Clean break (`coding_standards` §5): removed Click command errors natively; name the replacement in the changelog.
  Preconditions: audit that nothing (docs, skills, tests, user muscle-memory) depends on `forge hook enable`/`disable`.
- **Update (fallback).** If the command must stay, make it emit the **current** shipped command form (absolute path in
  T2's world, dispatcher form after T5), add `installed.json` tracking, and replace the prefix matcher with the shared
  matcher(s) so it moves in lockstep. This keeps a third code path alive -- a standing lockstep-maintenance cost.

The epic direction ("one hook source") favors **delete**; verify exposure first rather than assuming.

## Scope

**In:** audit callers/exposure of `forge hook enable`/`disable`; execute delete (preferred) or update; if delete, remove
`_is_forge_hook_entry` and its tests; if keep, align command form + add tracking + adopt the shared matcher.

**Out:** the main installer byte change (`forge_hook_absolute_command` / `user_scope_hook_ownership`); the migration
sweep that cleans already-written legacy entries (`forge_hook_migration_cleanup`).

## Grounding (verified 2026-07-02)

- Second writer, bare + untracked: `cli/hooks/install.py:87` (`enable`), `:130-134` (writes `settings["hooks"][key]`
  into `settings.local.json`, no tracking), `:182` (`disable`).
- Prefix matcher, incompatible with absolute/dispatcher forms: `_is_forge_hook_entry` `install.py:139-164`
  (`cmd.strip().startswith("forge hook ")` `:152`).
- Tracked path it diverges from: `merge_hooks`/`unmerge` `settings_merge.py:505,731`; `installed.json` tracking.

## Risks

- **Delete breaks callers** if anything scripts `forge hook enable`/`disable` -- clean break, so audit + changelog first.
- **Keep multiplies matchers** -- a third command form to keep in lockstep with seam 1 forever.
- **Ordering** -- if this lands after T6, T6 must already treat the untracked bare entries as legacy (value-based
  fallback), so the two cards must agree on who owns the leftover entries.

## Open questions

- Is `forge hook enable`/`disable` a supported UX surface anyone relies on, or an internal leftover? (Decides delete vs
  update.)

## Acceptance tests

| Test                          | Fixture                                          | Assertion                                                                     | Test File                                    |
| ----------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------- | -------------------------------------------- |
| Second writer no longer bare  | run the enable path (or its replacement)         | no bare `forge hook <name>` written; entry matches the shipped command form   | `tests/src/cli/test_hooks_install.py`        |
| Prefix matcher gone or aligned| absolute-path / dispatcher entry present         | detection/cleanup recognizes it (matcher deleted, or updated to shared form)  | same                                         |
| Delete is a clean break       | `forge hook enable` after removal                | Click reports "no such command"; changelog names the replacement             | same                                         |
| Tracked if kept               | enable path retained                             | entry is recorded in `installed.json` and removable by tracked `unmerge`      | `tests/src/install/test_installer.py`        |
