# Checklist: `--runtime` governs every runtime-owned surface

**Card**: [card.md](card.md) **Branch**: `feat/runtime-scoped-extension-modules` **Base**: `main` at `0066de5d`

**Current focus**: Phase 1 -- land the ownership vocabulary and read-path hardening, which are additive and make every
later phase safe to sequence.

---

## Planning findings (verified against `main` at `0066de5d`)

Line references in `card.md` predate the `disable_scope_mismatch_orphan` merge and have drifted. Re-verified anchors:

| Surface                                 | Card says    | Actual                                                                 |
| --------------------------------------- | ------------ | ---------------------------------------------------------------------- |
| Unguarded `InstallModule(...)` coercion | `2347, 2364` | `installer.py:2348` and `:2365` (two sites, both still unguarded)      |
| `modules_enabled` write                 | `2031`       | `installer.py:2032`                                                    |
| Codex skip branch                       | `2003-2012`  | `installer.py:2002-2013`                                               |
| `_scope_omitted_modules`                | `199-202`    | `installer.py:200`, applied at `:219` via `_apply_scope_module_policy` |
| `_legacy_claude_skill_packages`         | `315-334`    | `installer.py:316`, called at `:1142` and `:2383`                      |
| `_apply_scope_module_policy` callers    | `836`        | `installer.py:943` and `:1748`                                         |

Three findings change the work, not just the line numbers.

### F1 -- The runtime vocabulary already exists and is not the CLI's

`AGENT_RUNTIME_IDS = ("claude_code", "codex")` lives at `src/forge/core/runtime_vocab.py:23`, with `LANE_RUNTIME_IDS`
layered above it. The card's ownership table uses those exact ids, but the only current mapping is CLI-private
(`_SKILL_RUNTIME_IDS` at `cli/extensions.py:78`). Durable ownership must key on `runtime_vocab`, not on a CLI module --
otherwise `forge.install` imports its schema vocabulary from `forge.cli`, inverting the dependency direction.

### F2 -- There are two independently versioned surfaces, not one

- `TRACKING_VERSION = 2` (`install/models.py:268`), read by `tracking.py:113-118`, which accepts exactly
  `{LEGACY_TRACKING_VERSION=1, TRACKING_VERSION=2}` and calls `_handle_tracking_version_mismatch` for anything else.
- `"schema_version": 2` emitted by `extension status --json` (`cli/extensions.py:1509`), whose `"modules"` key at
  `:1483` is `list(inst.modules_enabled)` and therefore changes shape under D1.

The card's Open Question covers the status *field shape* but never notes that `status --json` carries its own version.
Both must bump to 3 in the same change, and the tracking reader's accepted set must become `{1, 2, 3}`.

### F3 -- "`codex_path` is `None` on the skip branch" is only true for a first install

The card uses this to argue the applied-ownership witness. Verified at `installer.py:2002-2013`: the `None` assignment
is in the `else` branch that only runs when `existing is None`. On a **re-enable** with the Codex half skipped,
`:2005-2011` deliberately preserves the prior `codex_config_path`, commented "the previously written managed block may
still be on disk and disable must keep knowing to remove it."

That preservation is the enable-side guard against exactly the orphan class
[disable_scope_mismatch_orphan](../../done/disable_scope_mismatch_orphan/card.md) just fixed, and
`test_module_dropped_preserves_tracking` (`tests/src/install/test_installer.py`) pins it.

**Consequence for v3 invariant 5.** The invariant is correctly stated -- `(hooks, codex)` iff `codex_config_path` is set
-- but it must be read as *reflecting on-disk state, not this run's outcome*. An implementer who follows the card's
supporting sentence and makes the skip branch write no pair would strand a real on-disk block with no ownership row,
re-creating the orphan from the enable side. Record this in `design_appendix.md` section C.4 alongside the invariant.

### Decision: D1 lands whole; the A1/A2 split considered earlier is withdrawn

An earlier suggestion was to split this card into ownership-plus-selection (no schema bump) and per-row attribution
(folded into the sibling card). Rejected on the card's own invariants:

- v3 invariant 2 requires every `InstalledFile` and `InstalledSettingsEntry` to carry a `(module, runtime)` pair. A
  first slice that ships v3 without per-row attribution violates its own invariant by construction.
- Avoiding that means two version bumps (v3 then v4) and two migrations for users, to save one intermediate release.

The card's risk note ("Sync breakage on upgrade if D1 is not landed whole") is therefore correct as written. The
independently valuable part of the split -- getting pristine-Codex early -- is preserved by phase ordering instead:
Phases 1-2 are individually merge-safe, so the branch can land incrementally without slicing the schema.

---

## Phase 1 -- Ownership vocabulary and read-path hardening

Additive only. No user-visible behavior change; makes Phase 3's enum deletion safe.

- [ ] Add `MODULE_RUNTIME_OWNERS: dict[InstallModule, frozenset[str]]` to `src/forge/install/models.py`, keyed on
  `AGENT_RUNTIME_IDS` values from `core/runtime_vocab.py`. **Assertion**: matches the card's ownership table exactly --
  `commands`/`agents`/`status-line`/`permissions` -> `{claude_code}`; `hooks`/`skills` -> `{claude_code, codex}`.
  `permissions` is Claude-owned per `preset.py:9`.
- [ ] Add a structural invariant test. **Assertion**: every `InstallModule` member has at least one owner, every owner
  string is in `AGENT_RUNTIME_IDS`, and the test fails if a new module is added without declaring ownership. No
  `forge.install` module imports from `forge.cli`.
- [ ] Harden both `InstallModule(...)` coercion sites (`installer.py:2348`, `:2365`) against values this Forge no longer
  defines. **Assertion**: an `installed.json` whose `modules_enabled` contains `"codex-hooks"` normalizes rather than
  raising `ValueError`. Assert against a checked-in fixture, not a constructed dict, so the file shape is pinned.
- [ ] Audit the other two coercion sites for the same exposure: `cli/extensions.py:124` (`--with`/`--without` parsing)
  and `:207` (`plan.modules`). **Assertion**: `:124` parses *user input*, so an unknown value must keep failing -- that
  is D5's native Click error, not a bug. Record which sites are input-validating and which are state-reading; only the
  latter normalize.

## Phase 2 -- Schema v3 (the card's P0)

- [ ] Bump `TRACKING_VERSION` to `3` (`models.py:268`) and extend the accepted set in `tracking.py:116` to `{1, 2, 3}`.
  **Assertion**: a v4 file still hits `_handle_tracking_version_mismatch` with the "written by newer Forge" message; v1
  and v2 files still read. No `strict=False` and no silent entry skipping (`coding_standards.md` section 5).
- [ ] Add `(module, runtime)` ownership pairs to `Installation`, replacing flat `modules_enabled`. **Assertion**: the
  pair set is written from *applied* state. `modules_enabled` today is written unconditionally from the resolved set
  (`installer.py:2032`); the v3 pair set must not be.
- [ ] Add `module` and `runtime` attribution to `InstalledFile` (`models.py:130`) and `InstalledSettingsEntry`
  (`models.py:151`). **Assertion**: every row written by a fresh install carries a pair present in the ownership set
  (invariant 2). This is the field the sibling card consumes; assert it directly rather than inferring it from behavior.
- [ ] Implement the derived v1/v2 -> v3 migration: normalize in memory on read, persist on the next successful mutation.
  **Assertion**: no user action and no reset. v2 skills attribution comes from `skill_packages[].runtime`; v1 from
  `_legacy_claude_skill_packages` (`installer.py:316`) which returns only path-provable ownership; everything else is
  Claude by construction. Assert field-by-field against checked-in v1 and v2 fixtures.
- [ ] Key the `(hooks, codex)` pair on `codex_config_path`, never on the module value. **Assertion**: per F3, a
  re-enable that skips the Codex half but preserves `codex_config_path` still writes the pair.
  `test_module_dropped_preserves_tracking` passes unchanged, and a new test asserts the pair survives that path. A
  *first* install that skips Codex writes no pair and no `codex_config_path`.
- [ ] Enforce all six v3 invariants before mutation. **Assertion**: each invariant has a test that violates it and
  observes a specific rejection -- especially 3 (no row claimed by two pairs) and 6 (an unattributed row is readable and
  reportable but is not valid input to a runtime-scoped removal).
- [ ] Record the "Claude by construction" premise as load-bearing in `design_appendix.md` section C.4. **Assertion**:
  the text states that adding a third Codex-owned module invalidates the derivation for rows written before it, so a
  future module must ship its own migration step.

## Phase 3 -- Module merge and the selection rule

- [ ] `hooks` absorbs `codex-hooks`; delete `InstallModule.CODEX_HOOKS` (`models.py:62`) and its entries in
  `PROFILE_MODULES` (`:75`) and `SETTINGS_ONLY_MODULES` (`:122`). **Assertion**: clean break, no hidden alias (D5).
  `_scope_omitted_modules` (`installer.py:200`) omits the merged `hooks` at project/local exactly as it omitted both
  before -- Codex hook registration stays user-scope-only.
- [ ] Preserve rendered hook command bytes. **Assertion**: `tests/src/install/test_registered_commands_contract.py`
  passes unchanged on the `(event, matcher, command, timeout)` byte contract. Codex `trusted_hash` covers registered
  command bytes plus config location and is not computable by Forge, so any byte change forces every existing Codex
  install through the trust ceremony for nothing.
- [ ] Implement the selection rule as a final filter after existing resolution (`_apply_scope_module_policy`,
  `installer.py:206`, called at `:943` and `:1748`). **Assertion**: implements the card's formula with provenance -- a
  dropped module from the profile is a `SKIP` with a reported reason; a dropped module named in `--with` is a
  `CONFLICT`; an explicit runtime selection resolving to an empty effective set is a `CONFLICT` (D2), never a silent
  no-op.
- [ ] Wire `--runtime` into module resolution, not just `skill_runtimes=` (`cli/extensions.py:932`, `:957`).
  **Assertion**: `--runtime` remains `click.Choice(["claude", "codex", "all"])` and `multiple=True`; it is **not** added
  to `sync` (D4), whose persisted `MANAGED` runtime set stays authoritative (`skill_planning.py:222`, `:234`).
- [ ] Add the new conflict reasons to `_NON_FORCEABLE_SKILL_CONFLICT_REASONS` (`cli/extensions.py:79`). **Assertion**:
  `--force` cannot adopt them; verified through the check at `cli/extensions.py:635`.
- [ ] Delete the four-flag recovery tip (`cli/extensions.py:152-160`). **Assertion**: its test asserts the one-flag
  `--runtime codex` form. The tip's existence is the card's evidence that the axis was wrong, so its deletion is an
  acceptance criterion, not cleanup.
- [ ] Confirm narrowing still preserves. **Assertion**: an explicit selection continues to set `preserved_runtime_ids`
  (`skill_planning.py:103`, `:234`) and emit `MANAGED_RUNTIME_PRESERVATION` rows (`:82`). This card is additive-only;
  removal belongs to [extension_disable_runtime](../../proposed/extension_disable_runtime/card.md) and the two must not
  land together.

## Phase 4 -- Status reporting (closes the card's Open Question)

Proposed resolution, to confirm during implementation rather than before it:

- [ ] Bump the `status --json` `schema_version` to `3` (`cli/extensions.py:1509`). **Assertion**: the version bump ships
  with the shape change, per F2.
- [ ] Add `managed_runtimes` as the single documented field for "which runtimes does this installation manage".
  **Assertion**: sorted subset of `AGENT_RUNTIME_IDS`, derived from the ownership pair set -- not recomputed from
  `codex_config_path` or `skill_packages`, which would give two sources of truth. This is the field the acceptance
  criterion names and the sibling card reads.
- [ ] Add `module_owners` (list of `{module, runtime}`) and keep `modules` as a sorted unique module list.
  **Assertion**: `modules` stays a flat list of module values so existing readers keep parsing; `module_owners` carries
  the new relation. Mirrors the existing `skill_packages` list-of-objects idiom at `:1485-1498`.
- [ ] Render unattributed surfaces (invariant 6). **Assertion**: a v1 row whose ownership is not path-provable appears
  in a named field as unattributed, and is not silently defaulted to Claude -- silent attribution is what would let a
  later `disable --runtime claude` delete a Codex file.

## Phase 5 -- Impact inventory (same change, per the card)

- [ ] Collapse the six recovery commands that spell both modules to `--with hooks`: `README.md:127`,
  `CONTRIBUTING.md:22`, `docs/end-user/hook.md:97`, `docs/end-user/skills.md:403`, `docs/end-user/README.md:59`,
  `src/skills/qa/resources/checklist/6-hook.md:29`. **Assertion**: `rg -n 'codex-hooks'` returns only the intentional
  survivors below.
- [ ] Update the QA `jq` tracking assertions. **Assertion**: `checklist/6-hook.md:30` hard-asserts
  `.installations.user.modules_enabled == ["codex-hooks", "hooks"]` and must move to the v3 shape.
  `checklist/2-extension.md:20,27,93,96` also read `modules_enabled` -- the card's inventory names only
  `2-extension.md:190` (the section heading), so these four lines are additional and easy to miss.
- [ ] Update normative design docs: `design.md:1365,1384`; `design_appendix.md:1028,1033,1225`;
  `design_workflows.md:355`; `cli_reference.md:116`. **Assertion**: each describes shipped behavior, and every "selects
  only outputs of the SKILLS module" disclaimer is gone -- that disclaimer's spread across six docs is the card's third
  piece of evidence.
- [ ] Update end-user and agent-context docs: `end-user/hook.md:97,118,301,321`; `end-user/skills.md:403`;
  `end-user/README.md:59`; `end-user/manual_testing.md`; `AGENTS.md`. **Assertion**: the card's inventory says
  `hook.md:97,114,297,317`, which drifted +4 when
  [disable_scope_mismatch_orphan](../../done/disable_scope_mismatch_orphan/card.md) inserted the scope-mismatch
  paragraph at `:114-116`. Re-verified positions are 97, 118, 301, 321. Keep that inserted paragraph intact while
  updating module names around it. The other five recovery-command references verified unchanged.
- [ ] Do **not** rename the unrelated identifiers. **Assertion**: hook handler names `codex-session-start` /
  `codex-policy-check` and the probe directory `scripts/experiments/codex-hooks/` (cited as evidence by
  `design_appendix.md` section I.2) are unchanged. Only the module *value* dies.
- [ ] Add the `docs/board/change_log.md` entry. **Assertion**: phase-completion sized (25-40 lines per
  `board_contract.md`); records the `codex-hooks` clean break, the two version bumps, and that no reset is required.

## Acceptance tests

Every behavior-matrix row is a test, per the card. Scope is named in each row because auto-detect prefers LOCAL in a git
repo (`cli/extensions.py:899`).

| Test                                              | Fixture                                          | Assertion                                                                                            | Test File                                                |
| ------------------------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `--scope user --runtime claude`                   | clean user scope, codex available                | no `$CODEX_HOME` path written, no Codex skill package -- by target-path inspection                   | `tests/src/install/test_runtime_scoped_modules.py`       |
| `--scope user --runtime codex`                    | clean user scope                                 | Codex skills + hook block; no `.claude/` write, no `~/.claude/settings.json`, no Claude version gate | `tests/src/install/test_runtime_scoped_modules.py`       |
| `--scope user --runtime all`                      | clean user scope                                 | rendered targets and registered-command golden identical to today; excludes `installed.json`         | `tests/src/install/test_registered_commands_contract.py` |
| `--scope project --runtime codex`                 | project scope                                    | codex skills only; hooks scope-omitted                                                               | `tests/src/install/test_runtime_scoped_modules.py`       |
| `--scope project --runtime claude`                | project scope                                    | commands, agents, claude skills, status-line, permissions; hooks scope-omitted                       | `tests/src/install/test_runtime_scoped_modules.py`       |
| `--scope local --runtime codex`                   | local scope                                      | CONFLICT, not a silent no-op                                                                         | `tests/src/cli/test_extension_enable.py`                 |
| bare `--runtime codex` in a repo                  | git checkout, no `--scope`                       | CONFLICT naming `--scope user`, because auto-detect resolves LOCAL                                   | `tests/src/cli/test_extension_enable.py`                 |
| `--profile minimal --runtime codex`               | any scope                                        | CONFLICT (empty effective set); `minimal` is `{commands}`, Claude-owned                              | `tests/src/cli/test_extension_enable.py`                 |
| `--runtime codex --with commands`                 | any scope                                        | CONFLICT (explicit, wrong owner) -- distinguishes explicit from profile provenance                   | `tests/src/cli/test_extension_enable.py`                 |
| `--profile minimal --with skills --runtime codex` | any scope                                        | allowed; installs codex skills                                                                       | `tests/src/cli/test_extension_enable.py`                 |
| `--force` cannot adopt new reasons                | each new conflict reason                         | still CONFLICT under `--force`                                                                       | `tests/src/cli/test_extension_enable.py`                 |
| Sync survives the deleted enum                    | checked-in `installed.json` with `"codex-hooks"` | `sync` succeeds; no `ValueError`                                                                     | `tests/regression/test_bug_sync_deleted_module_value.py` |
| v2 -> v3 derivation                               | checked-in v2 fixture                            | asserted field-by-field; no user action                                                              | `tests/src/install/test_tracking_migration.py`           |
| v1 -> v3 derivation                               | checked-in v1 fixture, no `skill_packages`       | path-provable Claude skills only; unprovable rows unattributed, not defaulted                        | `tests/src/install/test_tracking_migration.py`           |
| v4 still rejected                                 | `version: 4`                                     | `_handle_tracking_version_mismatch` message names the upgrade path                                   | `tests/src/install/test_tracking.py`                     |
| Best-effort Codex skip, first install             | codex binary unavailable, no prior install       | no `(hooks, codex)` pair, no `codex_config_path`, skip visibly reported                              | `tests/src/install/test_codex_hooks.py`                  |
| Best-effort Codex skip, re-enable                 | prior install with block, codex unavailable      | `(hooks, codex)` pair and `codex_config_path` both preserved (F3)                                    | `tests/src/install/test_codex_hooks.py`                  |
| Per-row attribution is complete                   | fresh install, all modules                       | every `InstalledFile` and `InstalledSettingsEntry` carries a valid pair                              | `tests/src/install/test_tracking_migration.py`           |
| Ownership declared for every module               | `InstallModule` enum                             | each member has >=1 owner, all owners in `AGENT_RUNTIME_IDS`                                         | `tests/src/install/test_models.py`                       |
| `status --json` v3 shape                          | user install managing both runtimes              | `schema_version == 3`; `managed_runtimes` sorted; `module_owners` present                            | `tests/src/cli/test_extension_status.py`                 |
| Codex re-trust not forced                         | existing Codex install, re-enable                | rendered command bytes byte-identical                                                                | `tests/src/install/test_registered_commands_contract.py` |

File status verified on this branch. **Existing** (extend, do not replace): `tests/src/install/test_models.py`,
`test_tracking.py`, `test_registered_commands_contract.py`, `test_codex_hooks.py`, `test_installer.py`, and
`tests/src/cli/test_extension_enable.py` -- which owns all enable *and* disable CLI coverage today, including the
codex-hooks class at `:2001`. **New files** to create: `tests/src/install/test_runtime_scoped_modules.py`,
`test_tracking_migration.py`, and `tests/regression/test_bug_sync_deleted_module_value.py`. `test_extension_status.py`
does not exist -- add the `status --json` cases to `test_extension_enable.py` unless the status surface grows enough to
justify splitting it, and record which choice was made.

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
- [ ] Design docs describe shipped behavior, including the F3 invariant-5 reading and the load-bearing "Claude by
  construction" premise in `design_appendix.md` section C.4.
- [ ] `rg -n 'codex-hooks'` returns only the intentional survivors (hook handler names, probe directory, changelog
  history).
- [ ] Card moved `doing/` -> `done/` and inbound links repointed. Current inbound links to repoint:
  `docs/board/proposed/extension_disable_runtime/card.md:5`, `docs/board/done/disable_scope_mismatch_orphan/card.md:12`,
  and `docs/board/done/disable_scope_mismatch_orphan/checklist.md:183`.
- [ ] Unblock the sibling: [extension_disable_runtime](../../proposed/extension_disable_runtime/card.md) gates on D1
  shipping. Confirm its stated dependency is satisfied and that per-row attribution is sufficient for its removal
  selection before promoting it.
- [ ] Candidates for `impl_notes.md` after human review: the runtime vocabulary belongs in `core/runtime_vocab`, not the
  CLI (F1); a versioned surface can exist outside the tracking manifest (F2); and preserve-on-skip is deliberate, so an
  "applied ownership" rule must key on on-disk witnesses rather than this run's outcome (F3).
