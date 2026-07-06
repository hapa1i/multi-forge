# Reconcile the second hook writer (`forge hook enable`/`disable`)

**Epic**: [`docs/board/proposed/epic_global_forge_runtime/card.md`](../epic_global_forge_runtime/card.md)

**Lane**: `proposed/`. Cross-cutting -- pairs with `forge_hook_absolute_command` (the byte form it must match) and
`forge_hook_migration_cleanup` (which it can undo). No hard ordering dependency, but the update-or-delete decision must
land **before** `forge_hook_migration_cleanup` finalizes, or this writer resurrects exactly the state cleanup removes.

**Recommended as pre-epic prep (2026-07-06).** Paired with
[`forge_hook_matcher_consolidation`](../forge_hook_matcher_consolidation/card.md), resolving this *before* the epic
starts collapses Seam 1 to **one matcher** unconditionally. The **writer** count then follows this card's decision:
**delete** and **update-by-delegation** (below) both leave a single mutation path (the tracked installer), differing only
in whether `forge hook` survives as a thin CLI entry point; a *standalone* lockstep second writer is the fallback that
keeps two paths. So the precise pre-epic guarantee is "one matcher, and one mutation path unless the standalone-writer
fallback is chosen." The update branch adopts the shared matcher from that card; the delete branch is epic-independent.
Land either first.

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

- **Delete.** Fold enable/disable into `forge extension enable`, remove the command and `_is_forge_hook_entry`.
  Clean break (`coding_standards` §5): removed Click command errors natively; name the replacement in the changelog.
  Preconditions: migrate `docs/end-user/hook.md`, and decide whether the "hooks-only, `settings.local.json`" affordance
  is preserved via `forge extension enable` flags or dropped.
- **Update.** If the command must stay, **prefer delegating it through the tracked installer path** (`merge_hooks` +
  `installed.json`) so `forge hook enable`/`disable` becomes a thin CLI entry point over the **one** mutation path -- not
  a second writer -- inheriting the shipped command form, tracking, and the shared matcher for free. This needs the
  tracked path to support the documented `settings.local.json`-only target (see the open question); if that affordance is
  dropped instead, delete is cleaner. Re-implementing it as a **standalone** writer that merely stays lockstep (its own
  emit + `installed.json` write + adopted matcher) is the fallback of last resort -- it keeps a third code path alive at a
  standing lockstep-maintenance cost.

The epic direction ("one hook source") favored **delete** on the assumption this was an internal leftover. **Exposure is
now verified and cuts against a free delete:** `forge hook enable`/`disable` is a *documented* end-user surface
(`docs/end-user/hook.md:90-96,341,359`; `diagrams.md:230`) with a **deliberate, distinct semantic** -- it always targets
`settings.local.json`, whereas `forge extension enable` uses the scope's main settings file. So delete is a
doc-affecting clean break (migrate `hook.md`, name the replacement, and decide whether the "hooks-only, local-only"
affordance is preserved via `forge extension enable` flags), **not** a trivial removal. Weigh delete-with-doc-migration
against update-via-tracked-path on that basis, not on "leftover" assumptions.

## Scope

**In:** audit callers/exposure of `forge hook enable`/`disable`; execute delete or update; if delete, remove
`_is_forge_hook_entry` and its tests and migrate `hook.md`; if keep, align command form + add tracking + adopt the shared
matcher.

**Out:** the main installer byte change (`forge_hook_absolute_command` / `user_scope_hook_ownership`); the migration
sweep that cleans already-written legacy entries (`forge_hook_migration_cleanup`).

## Grounding (verified 2026-07-02)

- Second writer, bare + untracked: `cli/hooks/install.py:87` (`enable`), `:130-134` (writes `settings["hooks"][key]`
  into `settings.local.json`, no tracking), `:182` (`disable`).
- Prefix matcher, incompatible with absolute/dispatcher forms: `_is_forge_hook_entry` `install.py:139-164`
  (`cmd.strip().startswith("forge hook ")` `:152`).
- Tracked path it diverges from: `merge_hooks`/`unmerge` `settings_merge.py:505,731`; `installed.json` tracking.
- Documented UX surface with a distinct semantic (verified 2026-07-06): `docs/end-user/hook.md:90-96` (the enable/disable
  commands), `:96` (the "always writes `settings.local.json`" note vs `forge extension enable`), `:341,:359`
  (troubleshooting), `diagrams.md:230`. Group is `hidden=True` but the docstring marks enable/disable "user-facing"
  (`cli/hooks/_group.py:8,15-16`).

## Risks

- **Delete breaks callers** if anything scripts `forge hook enable`/`disable` -- clean break, so audit + changelog
  first.
- **Standalone-lockstep fallback multiplies matchers** -- only if update is done as a *separate* writer rather than by
  delegation: a third command form + matcher to keep in lockstep with seam 1 forever. Delegation (the preferred update
  path) avoids this by reusing the tracked path's form + matcher.
- **Ordering** -- if this lands after T6, T6 must already treat the untracked bare entries as legacy (value-based
  fallback), so the two cards must agree on who owns the leftover entries.

## Open questions

- ~~Is `forge hook enable`/`disable` a supported UX surface anyone relies on, or an internal leftover?~~ **Resolved
  (2026-07-06): a documented UX surface** (`docs/end-user/hook.md`) with a deliberate `settings.local.json`-only
  semantic. The live decision is now delete-with-doc-migration (and whether to preserve the "hooks-only, local-only"
  affordance elsewhere) vs update-via-tracked-path -- not delete-because-leftover.
- If delete: does `forge extension enable` need a hooks-only / `settings.local.json` mode to preserve the affordance, or
  is that affordance itself obsolete under the epic's user-scope model?

## Acceptance tests

| Test                           | Fixture                                  | Assertion                                                                    | Test File                             |
| ------------------------------ | ---------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------- |
| Second writer no longer bare   | run the enable path (or its replacement) | no bare `forge hook <name>` written; entry matches the shipped command form  | `tests/src/cli/test_hooks_install.py` |
| Prefix matcher gone or aligned | absolute-path / dispatcher entry present | detection/cleanup recognizes it (matcher deleted, or updated to shared form) | same                                  |
| Delete is a clean break        | `forge hook enable` after removal        | Click reports "no such command"; changelog names the replacement             | same                                  |
| Tracked if kept                | enable path retained                     | entry is recorded in `installed.json` and removable by tracked `unmerge`     | `tests/src/install/test_installer.py` |
