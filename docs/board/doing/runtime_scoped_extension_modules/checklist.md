# Checklist: `--runtime` governs every runtime-owned surface

**Card**: [card.md](card.md) **Branch**: `feat/runtime-scoped-extension-modules` **Base**: `main` at `0066de5d`

**Current focus**: Phase 1 -- ownership vocabulary and read-path hardening. Phase 1 is the only additive, independently
merge-safe phase; Phase 2 lands the schema and the module merge together because both change persisted shape.

---

## Planning findings (verified against `main` at `0066de5d`)

`card.md` line references predate the `disable_scope_mismatch_orphan` merge. Re-verified anchors:

| Surface                                 | Card says        | Actual                                                                          |
| --------------------------------------- | ---------------- | ------------------------------------------------------------------------------- |
| Unguarded `InstallModule(...)` coercion | `2347, 2364`     | `installer.py:2348` and `:2365` (two sites, both still unguarded)               |
| `modules_enabled` write                 | `2031`           | `installer.py:2032`                                                             |
| Codex skip branch                       | `2003-2012`      | `installer.py:2002-2013`                                                        |
| `_scope_omitted_modules`                | `199-202`        | `installer.py:200`, applied at `:219` via `_apply_scope_module_policy`          |
| `_legacy_claude_skill_packages`         | `315-334`        | `installer.py:316`, called at `:1142` and `:2383`                               |
| `_apply_scope_module_policy` callers    | `836`            | `installer.py:943` and `:1748`                                                  |
| `end-user/hook.md` `codex-hooks` rows   | `97,114,297,317` | `97, 118, 301, 321` -- drifted +4 when the shipped bug card inserted `:114-116` |

### F1 -- The runtime vocabulary already exists and is not the CLI's

`AGENT_RUNTIME_IDS = ("claude_code", "codex")` lives at `src/forge/core/runtime_vocab.py:23`. The only current mapping
is CLI-private (`_SKILL_RUNTIME_IDS`, `cli/extensions.py:78`). Durable ownership keys on `runtime_vocab`, never on a CLI
module -- otherwise `forge.install` imports its schema vocabulary from `forge.cli`, inverting the dependency direction.

### F2 -- Two independently versioned surfaces, not one

- `TRACKING_VERSION = 2` (`install/models.py:268`), gated by `tracking.py:113-118`.
- `"schema_version": 2` emitted by `extension status --json` (`cli/extensions.py:1509`), whose `"modules"` key at
  `:1483` is `list(inst.modules_enabled)` and therefore changes shape under D1.

Both bump to 3 in the same change.

### F3 -- "`codex_path` is `None` on the skip branch" is only true for a first install

Verified at `installer.py:2002-2013`: the `None` assignment is in the `else` branch reached only when
`existing is None`. On a **re-enable** with the Codex half skipped, `:2005-2011` deliberately preserves the prior
`codex_config_path`, commented "the previously written managed block may still be on disk and disable must keep knowing
to remove it." `test_module_dropped_preserves_tracking` (`tests/src/install/test_installer.py`) pins it.

**Consequence for invariant 5.** `(hooks, codex)` iff `codex_config_path` is set is correct, but it reflects *on-disk
state, not this run's outcome*. An implementer who makes the skip branch write no pair strands a live block with no
owner -- the orphan from [disable_scope_mismatch_orphan](../../done/disable_scope_mismatch_orphan/card.md), reached from
the enable side.

### F4 -- Accepting version 2 is not the same as being able to parse it

`TrackingStore.read()` (`tracking.py:280-285`) routes v1 through the **frozen** `_LegacyInstalledManifest` (`:58`) plus
`_upgrade_legacy_manifest` (`:209`), and sends **every other accepted version** into
`_deserialize_manifest(path, InstalledManifest, data)` -- the live model, with `dacite.Config(strict=True)` (`:126`).

So extending the accepted set to `{1, 2, 3}` does **not** migrate v2. The moment the v3 dataclasses change, v2 files
fail strict deserialization against them. v3 needs a frozen `_V2InstalledManifest` plus `_upgrade_v2_manifest`,
mirroring the v1 path that is already in the file as a worked example.

### F5 -- `_NON_FORCEABLE_SKILL_CONFLICT_REASONS` does not enforce anything

At `cli/extensions.py:634-637` that set only computes `has_policy_conflicts` to choose a **recovery tip**, and it
iterates `plan.skill_packages` only. Execution is blocked by `plan.has_conflicts` at `:944-947`. A wrong-owner
`commands` module is not a skill package, and `InstallPlan` (`models.py:377-408`) has `modules: list[str]` with **no
per-module action or reason** -- so profile `SKIP`s and explicit-module `CONFLICT`s have no structured home today.

### F6 -- Sync derives managed runtimes from skills alone

`_managed_skill_runtime_ids` (`installer.py:2375`) returns `None` when `SKILLS not in modules` (`:2379-2380`) and
otherwise reads only `skill_packages`. A Codex-hooks-only installation therefore has no authoritative Codex selection to
preserve across `sync`. Since this card makes hooks runtime-owned, sync must derive from the ownership pair set.

### Decision: D1 lands whole; the A1/A2 split is withdrawn

Rejected on the card's own invariants: invariant 2 requires every file and settings row to carry attribution, so a first
slice shipping v3 without it violates its own invariant by construction. Avoiding that needs two version bumps and two
user migrations to save one intermediate release. The card's "land D1 whole" is correct.

Only **Phase 1** is independently merge-safe. An earlier draft of this checklist claimed Phases 1-2 both were; that was
wrong, because the module merge and the schema both change persisted shape and must land together.

---

## Frozen v3 shapes (decided here; overridable before Phase 2 starts)

The card leaves the serialized shape open, and invariants 2 and 6 cannot both be implemented until it is fixed. Decided:

**Row attribution is a required tagged object, not nullable fields.**

```text
InstalledFile / InstalledSettingsEntry:
  attribution: {"module": "hooks", "runtime": "codex"}      # attributed
             | {"unattributed_reason": "legacy_v1_unprovable"}  # explicitly not attributed
```

Exactly one form, validated on read and before write. Nullable `module`/`runtime` fields are rejected as the
representation: a removal filter that forgets to exclude nulls would match them by omission, whereas an explicitly
tagged alternative form cannot be matched by a filter that only understands pairs. That is what makes invariant 6
structural rather than a filtering discipline.

**Invariant 2 restated** to end the contradiction with invariant 6: every row carries a *valid attribution*, where
"unattributed with a reason" is valid. Invariant 6 then reads: an unattributed attribution is readable and reportable
and is not constructible as a runtime-scoped removal target.

**Row identity for invariant 3** ("no row claimed by two pairs"): `InstalledFile` identity is `target_path`;
`InstalledSettingsEntry` identity is `(key_path, stable_id)`, matching the canonical key `settings_merge.py:538` already
computes. Assert the identity choice directly, since "the same row" is otherwise undefined.

**`status --json` v3** (closes the card's Open Question):

- `schema_version: 3`
- `managed_runtimes: [...]` -- sorted subset of `AGENT_RUNTIME_IDS`, derived from the ownership pair set only, never
  recomputed from `codex_config_path` or `skill_packages`. This is the single documented field the acceptance criterion
  names.
- `module_owners: [{module, runtime}, ...]` -- mirrors the `skill_packages` list-of-objects idiom at `:1485-1498`.
- `modules: [...]` -- retained as a sorted unique module-value list so existing readers keep parsing.
- `unattributed_surfaces: [...]` -- invariant 6's reportable form.

**Legacy per-row module derivation.** "Claude by construction" fixes the *runtime*, not the *module*. Derive the module
for a legacy `InstalledFile` from its tracked target path against the module's install root (`commands/`, `agents/`,
skills roots, and the settings-only modules which have no files). A row whose path matches no module root becomes
`{"unattributed_reason": "legacy_path_unmapped"}` -- never a guess. Settings rows derive from `key_path` where the
mapping is unambiguous and are unattributed otherwise.

---

## Phase 1 -- Ownership vocabulary and read-path hardening

Additive, no persisted-shape change, independently merge-safe.

- [ ] Add `MODULE_RUNTIME_OWNERS: dict[InstallModule, frozenset[str]]` to `src/forge/install/models.py`, declaring
  ownership for the enum **as it exists today** -- including `CODEX_HOOKS -> {codex}`. **Assertion**: `codex-hooks` is
  genuinely Codex-owned pre-merge, so this is accurate rather than transitional scaffolding; the table collapses to the
  card's six-row form in Phase 2 when the member is deleted. Owner strings come from `AGENT_RUNTIME_IDS`
  (`core/runtime_vocab.py:23`).
- [ ] Add the structural invariant test. **Assertion**: every `InstallModule` member has >=1 owner and every owner is in
  `AGENT_RUNTIME_IDS` -- and the test passes **at this commit**, which is why `CODEX_HOOKS` is declared here rather than
  in Phase 2. No `forge.install` module imports from `forge.cli`.
- [ ] Harden both `InstallModule(...)` state-reading coercion sites (`installer.py:2348`, `:2365`) against values this
  Forge does not define. **Assertion**: an unknown module value in `modules_enabled` normalizes instead of raising
  `ValueError`. Exercise it with a value that is genuinely unknown *now* (a synthetic one), because `"codex-hooks"` is
  still a valid enum member at this phase and would pass vacuously. The `"codex-hooks"` fixture belongs to Phase 2.
- [ ] Classify the other two coercion sites. **Assertion**: `cli/extensions.py:124` parses `--with`/`--without` *user
  input* and must keep failing on unknown values -- that is D5's native Click error, not a bug. `:207` reads
  `plan.modules`, which this Forge produced, so it cannot see an unknown value. Record the input-validating vs
  state-reading split in a comment at each site.

## Phase 2 -- Schema v3 and the module merge (the card's P0, lands whole)

Both change persisted shape, so they land together. Order within the phase matters: the frozen v2 reader must exist
before the live model changes.

- [ ] Add a frozen `_V2InstalledManifest` plus `_upgrade_v2_manifest` to `tracking.py`, mirroring
  `_LegacyInstalledManifest` (`:58`) and `_upgrade_legacy_manifest` (`:209`). **Assertion**: per F4, `read()` dispatches
  v1 -> legacy type, v2 -> frozen v2 type, v3 -> live model. A v2 fixture never reaches
  `_deserialize_manifest(..., InstalledManifest, ...)`, whose `dacite.Config(strict=True)` (`:126`) would reject it once
  the live dataclasses change.
- [ ] Bump `TRACKING_VERSION` to `3` (`models.py:268`) and extend the accepted set at `tracking.py:116` to `{1, 2, 3}`.
  **Assertion**: a `version: 4` file still hits `_handle_tracking_version_mismatch` with the "written by newer Forge"
  message. No `strict=False`, no silent entry skipping (`coding_standards.md` section 5).
- [ ] Replace flat `modules_enabled` with `(module, runtime)` ownership pairs on `Installation`. **Assertion**: written
  from *applied* state. `modules_enabled` today is written unconditionally from the resolved set (`installer.py:2032`);
  the pair set must not be.
- [ ] Add the tagged `attribution` field to `InstalledFile` (`models.py:130`) and `InstalledSettingsEntry` (`:151`) per
  the frozen shape above. **Assertion**: exactly one form present, validated on read and before write. This is the
  contract the sibling card consumes -- assert the field directly, not via behavior.
- [ ] Propagate provenance at every construction site. **Assertion**: `settings_merge.py:538` builds
  `InstalledSettingsEntry` and must receive attribution from its caller rather than defaulting; grep for every
  `InstalledFile(` and `InstalledSettingsEntry(` construction and confirm none can produce a row without a valid
  attribution.
- [ ] Delete `InstallModule.CODEX_HOOKS` (`models.py:62`) and its entries in `PROFILE_MODULES` (`:75`) and
  `SETTINGS_ONLY_MODULES` (`:122`); `hooks` absorbs it. **Assertion**: clean break, no hidden alias (D5).
  `_scope_omitted_modules` (`installer.py:200`) omits the merged `hooks` at project/local exactly as it omitted both, so
  Codex hook registration stays user-scope-only.
- [ ] Update every production consumer of the deleted enum and the flat field. A literal `codex-hooks` grep **misses all
  of these** -- they use the `CODEX_HOOKS` identifier, so both forms must be searched. **Assertion**: all sites
  migrated, enumerated here so none is discovered mid-phase: - `hook_migration.py` -- **seven** sites, not one: `:192`,
  `:441`, `:690`, `:822` all test `InstallModule.CODEX_HOOKS.value in installation.modules_enabled`; `:607` and `:765`
  add it to a module set; `:831` filters it out. It also writes `Installation` directly, so it both consumes and
  produces v3. - `installer.py:177` -- `_RUNTIME_HOOK_MODULES = {HOOKS, CODEX_HOOKS}`, returned wholesale by
  `_scope_omitted_modules` at `:203`; collapses to `{HOOKS}`. - `installer.py:1411` -- the Codex planning gate; see the
  dedicated Phase 3 item. - `extensions.py:436` -- another `modules_enabled` reader. - `hook_dispatcher.py:653` -- reads
  `modules_enabled` via `any(module != "skills" ...)`; needs the pair set, and its `except Exception` fallback must keep
  degrading to the sync advice rather than starting to raise. - `models.py:117` -- the `SETTINGS_ONLY_MODULES` comment
  naming `CODEX_HOOKS`. - Tests: `test_hook_migration.py` (3), `test_models.py` (1).
- [ ] Implement the derived v1/v2 -> v3 migration: normalize in memory on read, persist on the next successful mutation.
  **Assertion**: no user action, no reset. v2 skills attribution from `skill_packages[].runtime`; v1 from
  `_legacy_claude_skill_packages` (`installer.py:316`); per-row module from the path mapping in the frozen-shape
  section; unmapped rows explicitly unattributed. Assert field-by-field against checked-in v1 and v2 fixtures.
- [ ] Key the `(hooks, codex)` pair on `codex_config_path`, never on the module value. **Assertion**: per F3, a
  re-enable that skips the Codex half but preserves `codex_config_path` still writes the pair;
  `test_module_dropped_preserves_tracking` passes unchanged. A *first* install that skips Codex writes neither.
- [ ] Derive sync's managed runtime set from ownership pairs. **Assertion**: per F6, `_managed_skill_runtime_ids`
  (`installer.py:2375`) returns `None` when `SKILLS` is absent, so a hooks-only install currently loses its Codex
  selection across `sync`. Rename/rework it to read the pair set, and keep D4 intact -- `--runtime` is still not a
  `sync` flag; the persisted set stays authoritative.
- [ ] Enforce all six v3 invariants before mutation, with invariant 2 restated per the frozen-shape section.
  **Assertion**: each invariant has a test that violates it and observes a specific rejection. Invariant 3 uses the
  declared row identities (`target_path`; `(key_path, stable_id)`).
- [ ] Record the load-bearing premises in `design_appendix.md` section C.4. **Assertion**: documents the F3 reading of
  invariant 5, and that "Claude by construction" breaks the moment a third Codex-owned module appears -- such a module
  must ship its own migration step.

## Phase 3 -- Selection rule and module planning outcomes

- [ ] Add per-module planning outcomes to `InstallPlan` (`models.py:377`). **Assertion**: per F5, `InstallPlan.modules`
  is a bare `list[str]` with no action or reason, so profile `SKIP`s and explicit-module `CONFLICT`s have nowhere to
  live. Add a `module_outcomes` list carrying `(module, action, reason)`, shaped like the existing `SkillPackagePlan`.
- [ ] Implement the selection rule as a final filter after existing resolution (`_apply_scope_module_policy`,
  `installer.py:206`, called at `:943` and `:1748`). **Assertion**: implements the card's formula with provenance --
  profile-sourced drops are `SKIP` with a reason, `--with`-named drops are `CONFLICT`, and an explicit runtime selection
  resolving to an empty effective set is a `CONFLICT` (D2), never a silent no-op.
- [ ] Make module conflicts actually block. **Assertion**: they set `plan.has_conflicts = True` and append to
  `plan.conflicts`, because the gate is `extensions.py:944-947` -- **not** membership in
  `_NON_FORCEABLE_SKILL_CONFLICT_REASONS`, which at `:634-637` only selects a recovery tip and only iterates
  `plan.skill_packages`. Add an analogous module-level reason set for tip selection, and assert `--force` cannot proceed
  past a wrong-owner module.
- [ ] Give `_plan_codex` a runtime input (`installer.py:1409-1411`). **This is the seam the card's goal turns on.**
  **Assertion**: it currently gates entirely on `if InstallModule.CODEX_HOOKS not in modules: return None`, taking only
  `modules: set[InstallModule]` and no runtime. After the merge `modules` contains `HOOKS` for both runtimes, so without
  a runtime parameter `--runtime claude` would still plan the Codex block -- exactly today's bug. The gate becomes
  "`hooks` is effective **and** `codex` is in the selected runtimes", and the signature changes accordingly. Assert
  `--runtime claude` yields `plan.codex is None`, distinct from the `action="unavailable"` skip at `:1418`.
- [ ] Wire `--runtime` into module resolution, not just `skill_runtimes=` (`cli/extensions.py:932`, `:957`).
  **Assertion**: stays `click.Choice(["claude", "codex", "all"])`, `multiple=True`, and is not added to `sync` (D4).
- [ ] Delete the four-flag recovery tip (`cli/extensions.py:152-160`). **Assertion**: its test asserts the one-flag
  `--runtime codex` form. The tip is the card's evidence that the axis was wrong, so deleting it is an acceptance
  criterion, not cleanup.
- [ ] Preserve rendered hook command bytes. **Assertion**: `tests/src/install/test_registered_commands_contract.py`
  passes unchanged on the `(event, matcher, command, timeout)` contract. Codex `trusted_hash` covers registered command
  bytes plus config location and is not computable by Forge, so any byte change forces existing installs through the
  trust ceremony.
- [ ] Confirm narrowing still preserves. **Assertion**: explicit selection still sets `preserved_runtime_ids`
  (`skill_planning.py:103`, `:234`) and emits `MANAGED_RUNTIME_PRESERVATION` (`:82`). Additive-only; removal belongs to
  [extension_disable_runtime](../../proposed/extension_disable_runtime/card.md) and must not land together.

## Phase 4 -- Status reporting

- [ ] Implement the frozen `status --json` v3 shape from the section above, bumping `schema_version` to `3`
  (`cli/extensions.py:1509`). **Assertion**: `managed_runtimes` derives from the ownership pair set only -- one source
  of truth, not recomputed from `codex_config_path` or `skill_packages`.
- [ ] Render unattributed surfaces. **Assertion**: a v1 row whose ownership is not path-provable appears in
  `unattributed_surfaces` and is never silently defaulted to Claude; silent attribution is what would let a later
  `disable --runtime claude` delete a Codex file.

## Phase 5 -- Impact inventory (same change, per the card)

- [ ] Collapse the six recovery commands that spell both modules to `--with hooks`: `README.md:127`,
  `CONTRIBUTING.md:22`, `docs/end-user/hook.md:97`, `docs/end-user/skills.md:403`, `docs/end-user/README.md:59`,
  `src/skills/qa/resources/checklist/6-hook.md:29`. All six verified at these lines.
- [ ] Update the QA `jq` tracking assertions **and** the index metadata. **Assertion**: `checklist/6-hook.md:30`
  hard-asserts `.installations.user.modules_enabled == ["codex-hooks", "hooks"]` and moves to the v3 shape;
  `checklist/2-extension.md:20,27,93,96` also read `modules_enabled` (the card's inventory names only `:190`, the
  section heading). Per `testing_guidelines.md` "Updating the QA checklist" step 3, also update
  `<!-- test-count: ~N -->` and `<!-- last-updated: YYYY-MM-DD -->` in `src/skills/qa/resources/checklist.md`.
- [ ] Update normative design docs: `design.md:1365,1384`; `design_appendix.md:1028,1033,1225`;
  `design_workflows.md:355`; `cli_reference.md:116`. **Assertion**: every "selects only outputs of the SKILLS module"
  disclaimer is gone -- its spread across six docs is the card's third piece of evidence that the axis was mis-scoped.
- [ ] Update end-user and agent-context docs: `end-user/hook.md:97,118,301,321`; `end-user/skills.md:403`;
  `end-user/README.md:59`; `end-user/manual_testing.md`; `AGENTS.md`. **Assertion**: keep the scope-mismatch paragraph
  at `hook.md:114-116` intact while updating module names around it.
- [ ] Do **not** rename the unrelated identifiers. **Assertion**: hook handler names `codex-session-start` /
  `codex-policy-check` and the probe directory `scripts/experiments/codex-hooks/` (evidence for `design_appendix.md`
  section I.2) are unchanged. Only the module *value* dies.
- [ ] Add the `docs/board/change_log.md` entry. **Assertion**: phase-completion sized (25-40 lines per
  `board_contract.md`); records the `codex-hooks` clean break, both version bumps, and that no reset is required.

## Acceptance tests

Scope is named in every row because auto-detect prefers LOCAL in a git repo (`cli/extensions.py:899`).

| Test                                              | Fixture                                            | Assertion                                                                                            | Test File                                                |
| ------------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `--scope user --runtime claude`                   | clean user scope, codex binary available           | no `$CODEX_HOME` path written, no Codex skill package -- by target-path inspection                   | `tests/src/install/test_runtime_scoped_modules.py`       |
| `--scope user --runtime codex`                    | clean user scope, **codex binary available**       | Codex skills + hook block; no `.claude/` write, no `~/.claude/settings.json`, no Claude version gate | `tests/src/install/test_runtime_scoped_modules.py`       |
| `--scope user --runtime all`                      | clean user scope, codex available                  | rendered targets and registered-command golden identical to today; excludes `installed.json`         | `tests/src/install/test_registered_commands_contract.py` |
| `--scope project --runtime codex`                 | project scope, codex available                     | codex skills only; hooks scope-omitted                                                               | `tests/src/install/test_runtime_scoped_modules.py`       |
| `--scope project --runtime claude`                | project scope                                      | commands, agents, claude skills, status-line, permissions; hooks scope-omitted                       | `tests/src/install/test_runtime_scoped_modules.py`       |
| `--scope local --runtime codex`                   | local scope                                        | CONFLICT via `plan.has_conflicts`, not a silent no-op                                                | `tests/src/cli/test_extension_enable.py`                 |
| bare `--runtime codex` in a repo                  | git checkout, no `--scope`                         | CONFLICT naming `--scope user`, because auto-detect resolves LOCAL                                   | `tests/src/cli/test_extension_enable.py`                 |
| `--profile minimal --runtime codex`               | any scope                                          | CONFLICT (empty effective set); `minimal` is `{commands}`, Claude-owned                              | `tests/src/cli/test_extension_enable.py`                 |
| `--runtime codex --with commands`                 | any scope                                          | CONFLICT (explicit, wrong owner) -- distinguishes explicit from profile provenance                   | `tests/src/cli/test_extension_enable.py`                 |
| `--profile minimal --with skills --runtime codex` | any scope, codex available                         | allowed; installs codex skills                                                                       | `tests/src/cli/test_extension_enable.py`                 |
| `--force` cannot adopt module conflicts           | wrong-owner `--with commands` plus a file conflict | exits non-zero; `--force` does not proceed past the module conflict                                  | `tests/src/cli/test_extension_enable.py`                 |
| Profile-sourced drop is a SKIP, not a conflict    | `--scope user --runtime codex`, standard profile   | Claude modules appear as `module_outcomes` SKIP rows with reasons; exit 0                            | `tests/src/install/test_runtime_scoped_modules.py`       |
| Sync survives the deleted enum                    | checked-in `installed.json` with `"codex-hooks"`   | `sync` succeeds; no `ValueError`                                                                     | `tests/regression/test_bug_sync_deleted_module_value.py` |
| Hooks-only install keeps Codex across sync        | v3 install with `(hooks, codex)` and no skills     | managed set still includes `codex` after `sync` (F6)                                                 | `tests/src/install/test_runtime_scoped_modules.py`       |
| v2 -> v3 migration                                | checked-in v2 fixture                              | parsed through the frozen v2 reader, never the live model; asserted field-by-field                   | `tests/src/install/test_tracking_migration.py`           |
| v1 -> v3 migration                                | checked-in v1 fixture, no `skill_packages`         | path-provable Claude skills only; unmapped rows tagged `legacy_path_unmapped`                        | `tests/src/install/test_tracking_migration.py`           |
| v4 still rejected                                 | `version: 4`                                       | `_handle_tracking_version_mismatch` names the upgrade path                                           | `tests/src/install/test_tracking.py`                     |
| Unattributed row is not a removal target          | v1-derived install with an unmapped row            | row is readable and reported; not constructible as a runtime-scoped removal target (invariant 6)     | `tests/src/install/test_tracking_migration.py`           |
| Duplicate-pair rejection uses declared identity   | two pairs claiming one `target_path`               | rejected before mutation (invariant 3)                                                               | `tests/src/install/test_tracking_migration.py`           |
| Codex skip, first install                         | codex binary unavailable, no prior install         | no `(hooks, codex)` pair, no `codex_config_path`, skip visibly reported                              | `tests/src/install/test_codex_hooks.py`                  |
| Codex skip, re-enable                             | prior install with block, codex unavailable        | `(hooks, codex)` pair and `codex_config_path` both preserved (F3)                                    | `tests/src/install/test_codex_hooks.py`                  |
| Attribution is complete                           | fresh install, all modules                         | every file and settings row carries a valid attribution                                              | `tests/src/install/test_tracking_migration.py`           |
| Ownership declared for every module               | `InstallModule` enum                               | each member has >=1 owner, all owners in `AGENT_RUNTIME_IDS`                                         | `tests/src/install/test_models.py`                       |
| `status --json` v3 shape                          | user install managing both runtimes                | `schema_version == 3`; `managed_runtimes` sorted; `module_owners` present                            | `tests/src/cli/test_extension_enable.py`                 |
| Codex re-trust not forced                         | existing Codex install, re-enable                  | rendered command bytes byte-identical                                                                | `tests/src/install/test_registered_commands_contract.py` |
| Hook dispatcher diagnosis survives v3             | v3 install, then a corrupt tracking file           | reads the pair set; corrupt file still degrades to sync advice, never raises                         | `tests/src/install/test_hook_dispatcher.py`              |

**Existing** (extend, do not replace): `tests/src/install/test_models.py`, `test_tracking.py`,
`test_registered_commands_contract.py`, `test_codex_hooks.py`, `test_installer.py`, `test_hook_dispatcher.py`, and
`tests/src/cli/test_extension_enable.py` -- which owns all enable *and* disable CLI coverage today, including the
codex-hooks class at `:2001`. **New**: `tests/src/install/test_runtime_scoped_modules.py`, `test_tracking_migration.py`,
`tests/regression/test_bug_sync_deleted_module_value.py`. `tests/src/cli/test_extension_status.py` does not exist -- add
status cases to `test_extension_enable.py` unless the surface grows enough to justify a split, and record the choice.

## Verification log

(record each command and its result; do not tick a phase box on a green unit run alone)

- [ ] `uv run pytest tests/src/install tests/src/cli -q`
- [ ] `make test-unit`
- [ ] `make test-regression`
- [ ] `./scripts/test-integration.sh tests/integration/docker/test_installer.py -v`
- [ ] Clean-wheel install exercising `enable`/`sync`/`status`/`disable` for `--runtime claude`, `codex`, and `all`, plus
  Codex-hook preservation across a `--runtime claude` re-enable. **Required, not optional**: the card names it, and unit
  tests cannot reach the wheel-install path this card changes.
- [ ] `make pre-commit`

## Closeout

- [ ] Every box ticked with verification recorded; no phase ticked on unit tests alone.
- [ ] `docs/board/change_log.md` entry added, recording the clean break and both version bumps.
- [ ] Design docs describe shipped behavior, including the F3 reading of invariant 5 and the load-bearing "Claude by
  construction" premise in `design_appendix.md` section C.4.
- [ ] Both scoped greps are clean. A repo-wide grep cannot pass -- this checklist, `card.md`, and historical board
  entries intentionally contain the term -- and a literal-string grep alone misses every `CODEX_HOOKS` identifier site.
  Run both:
  `bash     rg -n 'codex-hooks' src/forge src/skills docs/design_appendix.md docs/design.md docs/design_workflows.md \       docs/cli_reference.md docs/end-user README.md CONTRIBUTING.md AGENTS.md     rg -n 'CODEX_HOOKS' src/forge tests/     `
  **Allowlist** (verified as probe-directory or historical references, none of which name the module value):
  `cli/hooks/codex_transfer.py:37`, `core/runtime/registry.py:198`, `cli/runtime.py:140`,
  `core/ops/codex_enrollment.py:279`, `core/runtime/codex_preflight.py:74` -- all citing
  `scripts/experiments/codex-hooks/` -- plus the dated history line at `src/skills/qa/resources/checklist.md:32`. The
  hook handler names `codex-session-start` / `codex-policy-check` contain `codex-` but not `codex-hooks`.
- [ ] Card moved `doing/` -> `done/` and inbound links repointed:
  `docs/board/proposed/extension_disable_runtime/card.md:5`, `docs/board/done/disable_scope_mismatch_orphan/card.md:12`,
  `docs/board/done/disable_scope_mismatch_orphan/checklist.md:183`.
- [ ] Unblock the sibling: [extension_disable_runtime](../../proposed/extension_disable_runtime/card.md) gates on D1
  shipping. Confirm the tagged attribution is sufficient for its removal selection -- specifically that it can build a
  removal set without ever matching an unattributed row.
- [ ] Candidates for `impl_notes.md` after human review: accepting a schema version is not the same as being able to
  parse it, and only a frozen-type read path pins a historical shape (F4); a conflict-reason set that feeds a recovery
  tip is not an enforcement mechanism (F5); the runtime vocabulary belongs in `core/runtime_vocab`, not the CLI (F1);
  and preserve-on-skip makes on-disk witnesses, not run outcomes, the basis of applied ownership (F3).
