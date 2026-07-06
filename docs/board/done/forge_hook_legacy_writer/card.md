# Reconcile the second hook writer (`forge hook enable`/`disable`)

**Epic**: [`docs/board/proposed/epic_global_forge_runtime/card.md`](../../proposed/epic_global_forge_runtime/card.md)

**Lane**: `done/` -- shipped via PR #88, merged to `main` as `0458a5ae` on 2026-07-06.

**Status (2026-07-06 closeout):** DELETE shipped. The standalone `forge hook enable` / `forge hook disable` writer,
duplicate `FORGE_HOOK_CONFIG` registry, and local scope walk were removed. Hook registration now has one mutation path:
the tracked extension installer. The hooks-only replacement is:

```bash
forge extension enable --scope local --profile minimal --with hooks --without commands
```

[`forge_hook_matcher_consolidation`](../forge_hook_matcher_consolidation/card.md) shipped first, so the matcher concern
was already resolved before this writer cleanup landed. The execution record lives in [`checklist.md`](checklist.md).

**Recommended as pre-epic prep (2026-07-06).** Paired with
[`forge_hook_matcher_consolidation`](../../done/forge_hook_matcher_consolidation/card.md), resolving this *before* the
epic starts collapses Seam 1 to **one matcher** unconditionally. The **writer** count then follows this card's decision:
**delete** and **update-by-delegation** (below) both leave a single mutation path (the tracked installer), differing
only in whether `forge hook` survives as a thin CLI entry point; a *standalone* lockstep second writer is the fallback
that keeps two paths. So the precise pre-epic guarantee is "one matcher, and one mutation path unless the
standalone-writer fallback is chosen." The update branch adopts the shared matcher from that card; the delete branch is
epic-independent. Land either first.

## Goal

Decide and execute: **update or delete** the parallel `forge hook enable` / `forge hook disable` writer so it stops
being a second, untracked hook-registration path that writes a bare, PATH-dependent command form no other member emits.

## Why

Before this card, Forge had **two** hook writers, not one:

1. `forge extension enable` -- the tracked installer path (`installer.py` -> `merge_hooks`, `installed.json`), which T2
   and T5 rewrite.
2. `forge hook enable` / `disable` (`cli/hooks/install.py`) -- a separate command that overwrites each hook key
   wholesale with bare `forge hook <name>` entries in `settings.local.json`, with **no `installed.json` tracking**
   (`install.py:131-135`). Its cleanup matcher now delegates to the shared `entry_is_forge_hook` predicate
   (`install.py:140-147`), so only the *writer* remains a drift source.

That second writer is a drift source the epic cannot ignore:

- **It resurrects the legacy state.** It emits bare, PATH-dependent `forge hook <name>` -- exactly the exit-127 form T2
  fixes and T6 cleans. A user who runs it post-migration reintroduces the incident and a double-fire.
- **It clobbers sibling hooks.** `enable` writes `settings["hooks"][key] = value` (`install.py:131-132`), replacing each
  Forge-owned hook key wholesale rather than the tracked path's `merge_hooks` append-and-dedupe
  (`settings_merge.py:505`). A user who keeps their own entry under one of those keys (e.g. `SessionStart`) loses it on
  enable.
- **It is untracked**, so T6's tracked `unmerge` (`settings_merge.py:731`, keyed on `stable_id`) cannot remove its
  entries -- they only fall to T6's value-based fallback.

## Decision (update or delete)

**Decision landed (2026-07-06): DELETE**, conditional on the Phase 0 hooks-only gate (see
[`checklist.md`](checklist.md), D1). The options below are preserved as the decision space -- why delete was chosen over
update-by-delegation, and the standalone-lockstep fallback that was rejected.

- **Delete.** Fold enable/disable into `forge extension enable`, remove the command and `_is_forge_hook_entry`. Clean
  break (`coding_standards` §5): removed Click command errors natively; name the replacement in the changelog.
  Preconditions: migrate `docs/end-user/hook.md`, and decide whether the "hooks-only, `settings.local.json`" affordance
  is preserved via `forge extension enable` flags or dropped.
- **Update.** If the command must stay, **prefer delegating it through the tracked installer path** (`merge_hooks` +
  `installed.json`) so `forge hook enable`/`disable` becomes a thin CLI entry point over the **one** mutation path --
  not a second writer -- inheriting the shipped command form, tracking, and the shared matcher for free. This needs the
  tracked path to support the documented `settings.local.json`-only target (see the open question); if that affordance
  is dropped instead, delete is cleaner. Re-implementing it as a **standalone** writer that merely stays lockstep (its
  own emit + `installed.json` write + adopted matcher) is the fallback of last resort -- it keeps a third code path
  alive at a standing lockstep-maintenance cost.

The epic direction ("one hook source") favored **delete** on the assumption this was an internal leftover. **Exposure is
now verified and cuts against a free delete:** `forge hook enable`/`disable` is a *documented* end-user surface
(`docs/end-user/hook.md:90-96,341,359`; `diagrams.md:230`) with a **deliberate, distinct semantic** -- it always targets
`settings.local.json`, whereas `forge extension enable` uses the scope's main settings file. So delete is a
doc-affecting clean break (migrate `hook.md`, name the replacement, and decide whether the "hooks-only, local-only"
affordance is preserved via `forge extension enable` flags), **not** a trivial removal. Weigh delete-with-doc-migration
against update-via-tracked-path on that basis, not on "leftover" assumptions.

## Scope

**In:** audit callers/exposure of `forge hook enable`/`disable`; execute delete or update; if delete, remove
`_is_forge_hook_entry` and its tests and migrate `hook.md`; if keep, align command form + add tracking + adopt the
shared matcher.

**Out:** the main installer byte change (`forge_hook_absolute_command` / `user_scope_hook_ownership`); the migration
sweep that cleans already-written legacy entries (`forge_hook_migration_cleanup`).

## Grounding (verified 2026-07-02; matcher + line refs refreshed 2026-07-06 post-merge)

- Second writer, bare + untracked: `cli/hooks/install.py:88` (`enable`), `:131-132` (writes `settings["hooks"][key]`
  into `settings.local.json`, no `installed.json`), `:165` (`disable`).
- Matcher already shared (post-`forge_hook_matcher_consolidation`): `_is_forge_hook_entry` `install.py:140-147`
  delegates to `entry_is_forge_hook(entry, require_command_type=True)` -- no separate prefix form remains; only
  `disable` (`:201`) calls it.
- Tracked path it diverges from: `merge_hooks`/`unmerge` `settings_merge.py:505,731`; `installed.json` tracking.
- Documented UX surface with a distinct semantic (verified 2026-07-06): `docs/end-user/hook.md:90-96` (the
  enable/disable commands), `:96` (the "always writes `settings.local.json`" note vs `forge extension enable`),
  `:341,:359` (troubleshooting), `diagrams.md:230`. Group is `hidden=True` but the docstring marks enable/disable
  "user-facing" (`cli/hooks/_group.py:8,15-16`).

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

The active, decision-committed acceptance table lives in [`checklist.md`](checklist.md) (delete path). It supersedes the
earlier update-or-delete draft that sat here: the "prefix matcher" row is gone (the matcher is already shared
post-merge), the clean-break assertion is owned by `tests/src/cli/test_command_tree_invariants.py`, and the hooks-only
replacement is gated by Phase 0.

## Closeout

Shipped via PR #88 and closed out on `main` 2026-07-06.

- D1 landed as **delete**, gated by the tracked hooks-only replacement above.
- The old `--user` local-file target (`~/.claude/settings.local.json`) was intentionally not recreated; tracked user
  scope writes `~/.claude/settings.json`, and tracked local scope writes `.claude/settings.local.json`.
- `forge_hook_migration_cleanup` still owns legacy/manual/untracked entries that may already exist in user settings.
