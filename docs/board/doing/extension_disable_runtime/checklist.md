# Checklist: `forge extension disable --runtime`

**Card**: [card.md](card.md) **Branch**: `feat/extension-disable-runtime` **Base**: `main` at `4b9ad0ad`

**Current focus**: Phase 1 -- the removal-set derivation, which is pure, testable without the CLI, and the input every
later phase depends on.

**Authority**: the decisions in this file are **firm**, not provisional. `card.md`'s two stale Constraints have been
reconciled in place and marked RESOLVED with shipping evidence, so there is one execution contract: the card owns intent
and the state-transition table, this checklist owns mechanism and the decisions the card predates.

---

## Planning findings (verified against `main` at `4b9ad0ad`)

`card.md` was written before `disable_scope_mismatch_orphan` (#115) and `runtime_scoped_extension_modules` (#116). Both
hard dependencies are satisfied; the card's Constraints now say so. Re-verified anchors (all drifted):

| Surface                        | Card says                 | Actual                                                  |
| ------------------------------ | ------------------------- | ------------------------------------------------------- |
| `disable_cmd` + options        | `extensions.py:1166-1180` | `:1205-1220`                                            |
| Plan render (single scope)     | `:1236-1284`              | `:1279-1327`                                            |
| Prompt / apply                 | `:1275-1292`              | `:1329-1333`                                            |
| `--all` dispatch               | `:1211-1213`              | `:1245-1251`                                            |
| `--all` summary render         | `:656-690`                | `_uninstall_all_installations` at `:695`                |
| `uninstall()`                  | `installer.py:2389-2464`  | `:2377`, codex preflight at `:2387`                     |
| Sync replay                    | `:2347-2372, 2374-2388`   | `:2342-2357` and `:2362-2375`                           |
| Settings unmerge               | `:2439-2456`              | `:2429`, calling **`smart_unmerge`** (see F4)           |
| Row models                     | `models.py:129-165`       | `:158` and `:181`                                       |
| `MANAGED_RUNTIME_PRESERVATION` | `skill_planning.py:81-82` | `:80`, `preserved_runtime_ids` at `:101`, set at `:232` |

### F1 -- Sync resurrection is structurally closed; the requirement moved

`init_from_existing` / `plan_update` once replayed `_modules_override` from `modules_enabled` **and** derived runtimes
from `skill_packages` -- two fields to keep in step. Both now read one source:
`existing_modules = {InstallModule(m) for m in module_values(existing)}` and
`managed_runtime_ids = owned_runtime_ids(existing)` (`installer.py:2348-2349`, `:2367-2368`), each from `module_owners`.

**Dropping a runtime's ownership pairs is therefore sufficient** to stop sync replanning it. The requirement becomes:
the pairs are the thing that must be dropped. A removal that deletes files but leaves `(skills, codex)` in
`module_owners` is resurrected by the next `sync` -- still the failure a filesystem-only test would pass.

### F2 -- Manifest validation proves internal coherence only, never filesystem truth

`TrackingStore.write()` calls `_validate_current_manifest` before persisting, and four invariants constrain the row:

| Invariant | Constraint on the written row                                                                                  |
| --------- | -------------------------------------------------------------------------------------------------------------- |
| 2         | Every file/settings row's attribution must be in `module_owners` -- dropping a pair requires dropping its rows |
| 3         | Row identities stay unique (`target_path`; `(key_path, stable_id)`)                                            |
| 4         | Every `skill_packages` row needs a matching `(skills, runtime)` pair -- packages and pair drop together        |
| 5         | `(hooks, codex)` **iff** `codex_config_path` is set (`tracking.py:381-386`)                                    |

**These are manifest-internal checks.** Invariant 5 compares the owner pair against `codex_config_path` *within the
manifest*; it cannot observe whether the managed block was actually removed from disk. Writing a coherent row is
necessary but not sufficient for a truthful removal.

Truthfulness comes from two other places, and both need their own assertions:

1. **Application order** -- mutate the filesystem first, then write tracking describing what succeeded.
2. **Filesystem assertions in tests** -- assert on target paths and config bytes, never on the manifest alone.

A pair with **zero** remaining rows is legal (invariant 2 is per-row, not per-pair). That is the slack that makes a
mid-removal fault representable: drop exactly the rows removed, keep the pair.

### F3 -- Unattributed-row retention is removal-builder policy, not a schema guarantee

`_validate_attribution` (`tracking.py:389`) accepts any `UnattributedSurface` whose reason is in
`LEGACY_UNATTRIBUTED_REASONS` (`ownership.py:27-33`). It cannot detect that such a row was *deleted*, so nothing in
`TrackingStore.write()` enforces retention.

**Local definition, used throughout this checklist**: *a row whose `attribution` is `UnattributedSurface` is never a
runtime-scoped removal target.* This is a rule the removal builder must implement and tests must assert directly; it is
not inherited from the sibling card's invariant numbering.

### F4 -- Settings removal is `smart_unmerge` over a sidecar, not `unmerge`

`uninstall()` calls `smart_unmerge(current, backup, added)` (`installer.py:2429`), a three-way comparison that restores
the backup value when `current == added` and **leaves user modifications alone** (`settings_merge.py:252-272`). The
separate `unmerge` (`:775`) is not on this path and does not compare -- it deletes tracked env keys outright
(`:818-825`).

The three-way inputs come from durable sidecars: `find_backup_files` / `find_added_files` (`installer.py:2398-2399`),
where `added` is the `.forge-added` payload that **enable** rewrites from the surviving entry set on every install
(`entries_to_added_structure(final_entries)` + `save_added_settings`, `installer.py:1863-1864`).

**Consequence.** A partial disable that removes Claude settings entries must rewrite `.forge-added` to the surviving
entries, exactly as enable does. If it does not, a later full disable smart-unmerges against stale ownership and can
remove settings the user reintroduced after the partial disable. This is the most likely silent-data-loss path in the
card, and it has no representation in the state-transition table.

### F5 -- `remove_codex_block` conflates "absent" with "malformed"

It returns `removed=False` for a missing config file, and also `removed=False, leftover_commands=...` when the strict
plan rejects the file (`codex_hooks.py:515+`). One signal, two very different situations. Decided below.

### F6 -- Scope auto-detection is not runtime-aware

`find_forge_installation` (`installer.py:702`) returns the **nearest** installation, walking up checking LOCAL then
PROJECT at each level, then USER. It selects a scope before any runtime is considered, so an unscoped
`disable --runtime codex` inside a project with a Claude-only local install resolves to that local row. Decided below.

---

## Decisions (firm)

**D-unattributed.** `--runtime <r>` retains unattributed rows and reports them; only a full removal (`--runtime all`,
bare `disable`, or the last-runtime case) removes them. Guessing that an unattributed row is Claude's is what would
delete a Codex file under `--runtime claude`. Per F3 this is builder policy, so it needs a direct test, not an appeal to
schema validation.

**D-settings-sidecar.** A partial disable rewrites `.forge-added` to the surviving settings entries via the same
`entries_to_added_structure` + `save_added_settings` path enable uses, in the same mutation step that unmerges. Field
transitions:

| Field                  | Partial disable (runtime remains)                                      | Full removal      |
| ---------------------- | ---------------------------------------------------------------------- | ----------------- |
| `.forge-added`         | rewritten to surviving entries                                         | existing behavior |
| `settings_backup_path` | **retained** -- still the pre-Forge baseline for the surviving runtime | existing behavior |
| `settings_entries`     | removed runtime's rows dropped                                         | existing behavior |

`settings_backup_path` is not rewritten: it records the state before Forge touched the file at all, which is still the
correct baseline while any Forge-managed settings survive.

**D-codex-outcomes.** Split F5's single signal by cause:

| `remove_codex_block` outcome           | Action                                                                            |
| -------------------------------------- | --------------------------------------------------------------------------------- |
| Removed the block                      | Drop `(hooks, codex)`, clear `codex_config_path` and `codex_commands`             |
| Config file absent                     | Same -- there is nothing to own; clearing stale ownership is the truthful outcome |
| Malformed / partial markers, leftovers | **Refuse**: retain ownership and config path, exit non-zero, name the file        |

Clearing ownership for an absent file is safe because no block exists; refusing on malformed markers is required because
Forge cannot prove what it would be abandoning.

**D-last-delegates.** When the selection covers every managed runtime -- `--runtime all`, a `--runtime <r>` that is the
last managed runtime, or repeated flags that collectively cover all of them (`--runtime claude --runtime codex`) --
dispatch to the **existing** `uninstall()`. This makes the card's "`--runtime all` matches today's `disable`" criterion
true by construction, keeps unattributed rows removed in the full case, and leaves the last-runtime prompt as the only
new wording.

**D-preflight-scoped.** Call `validate_codex_config_scope` only when the removal set includes the Codex managed block. A
Claude-only removal proceeds on an install whose Codex path drifted; nothing it touches depends on that mapping.

**D-autodetect-unchanged.** Unscoped `disable --runtime <r>` keeps nearest-scope resolution. Making disable search for a
runtime-managing scope would let it act on a *farther* scope than unscoped `sync` and `status` (`skills.md:74` documents
the shared resolution), which is a worse surprise than a no-op. When the resolved scope does not manage the runtime, the
no-op message names the resolved scope and points at `--scope`.

**D-all-disposition.** The `--all` summary gains a **DISPOSITION** column (`no-op` / `partial` / `full`), not just a
filtered caption. Counts alone cannot distinguish the three: a hooks-and-settings-only removal shows `0` files and `0`
packages while still mutating config and possibly deleting the row. This supersedes the caption-only approach in this
checklist's first draft.

---

## Failure taxonomy (per durable mutation boundary)

The card's "failure after partial removal" covers only a file-removal fault. Each boundary needs defined behavior:

| Boundary                                  | On failure                                                                                |
| ----------------------------------------- | ----------------------------------------------------------------------------------------- |
| File removal                              | Stop; reconcile tracking to the files actually removed; exit non-zero naming the retry    |
| Settings unmerge + `.forge-added` rewrite | Stop; sidecar rewrite and settings write must both land or the step is reported as failed |
| Codex block removal                       | Per D-codex-outcomes; on refusal nothing else in the Codex half is cleared                |
| Reconciliation write itself               | See below -- the one case with no clean guarantee                                         |

**Reconciliation-write failure.** `TrackingStore.write()` is atomic (`tracking.py:679+`), so the file is never malformed
-- but atomicity does not guarantee the *new* row lands. If the reconciliation write fails, the filesystem has been
mutated while tracking still describes the pre-removal state, so tracking over-claims ownership of removed surfaces.

State this honestly rather than promising a guarantee the code cannot make:

- Exit non-zero with an error naming the tracking path and the fact that removal already happened.
- Do **not** retry-loop or fall back to a partial write. Over-claiming is recoverable by re-running disable; an
  under-claiming row is not, because it silently abandons surfaces.
- `forge extension status` is the recovery surface: an over-claiming row surfaces as missing tracked files, which status
  already reports.

## Phase 1 -- Removal-set derivation (pure)

No CLI, no filesystem. This is the contract every later phase reads.

- [ ] Add a removal-set builder returning the files, settings entries, skill packages, ownership pairs, Codex-block
  flag, and **surviving settings entries** for a given `Installation` plus selected runtime ids. **Assertion**:
  selection is the intersection of `MODULE_RUNTIME_OWNERS` with what tracking claims -- never the ownership map alone.
  Nothing untracked is adopted; `forge clean` still owns proven orphans.
- [ ] Select rows via `ownership.attribution_pair` (`ownership.py:83`). **Assertion**: a `None` result (unattributed) is
  never a removal target, asserted directly against a migrated-v1 fixture. Per F3 this is builder policy -- the test
  must fail if the builder includes such a row, because `TrackingStore.write()` will not catch it.
- [ ] Return the surviving settings entries for the sidecar rewrite (D-settings-sidecar). **Assertion**: the survivor
  set is what `entries_to_added_structure` consumes, so Phase 2 does not recompute it from a different source.
- [ ] Make `--runtime claude` cover all five Claude surfaces plus Claude skill packages. **Assertion**: commands,
  agents, `hooks`, `statusLine`, and `permissions` settings entries, and Claude skill packages -- each asserted
  separately so a missing surface fails its own test. Under-removal is a named card risk.
- [ ] Produce a post-removal `Installation` satisfying every v3 invariant. **Assertion**: rows dropped with their pairs
  (inv 2), packages with `(skills, runtime)` (inv 4), `codex_config_path` + `codex_commands` cleared exactly when
  `(hooks, codex)` is dropped (inv 5). Feed the result through `_validate_current_manifest` in the test. Per F2 this
  proves internal coherence only.
- [ ] Report retained unattributed rows. **Assertion**: count and reasons, so the CLI can tell a legacy user what
  remains.
- [ ] Detect full coverage, including repeated flags (D-last-delegates). **Assertion**: `--runtime all`, last-runtime,
  and `--runtime claude --runtime codex` on a dual install all report full coverage.

## Phase 2 -- Installer removal path

- [ ] Add the runtime-scoped removal entry point, reusing `uninstall()`'s boundary validation. **Assertion**:
  `_tracked_file_boundary` + `validate_path_within_boundary` run on the filtered subset, so the `invalid-target` refusal
  for a symlink-replaced package root still applies (`design_appendix.md` section C.5).
- [ ] Dispatch full-coverage cases to the existing `uninstall()` (D-last-delegates). **Assertion**: the full path is the
  existing code, not a filtered path that happens to select everything.
- [ ] Use `smart_unmerge(current, backup, added)` and rewrite `.forge-added` (F4, D-settings-sidecar). **Assertion**:
  the same three-way call as `installer.py:2429` -- **not** `settings_merge.unmerge`, which deletes tracked env keys
  without comparing (`:818-825`). After a partial disable, `.forge-added` holds exactly the surviving entries. Assert by
  round-trip: partial disable, user re-adds a setting, full disable, setting survives.
- [ ] Retain `settings_backup_path` on partial removal (D-settings-sidecar). **Assertion**: unchanged; it is the
  pre-Forge baseline and stays correct while any Forge settings survive.
- [ ] Scope the Codex preflight to the removal set (D-preflight-scoped). **Assertion**: `validate_codex_config_scope`
  runs iff the Codex block is being removed.
- [ ] Handle all three `remove_codex_block` outcomes (D-codex-outcomes). **Assertion**: removed and absent both clear
  ownership; malformed/leftover refuses, retains ownership and config path, exits non-zero naming the file. Per F5 these
  share one `removed=False` signal, so the branch must inspect file existence and `leftover_commands`, not just the
  flag.
- [ ] Do not re-render the surviving runtime's hook bytes. **Assertion**:
  `tests/src/install/test_registered_commands_contract.py` passes unchanged. Codex `trusted_hash` covers command bytes
  and config location, so a re-render forces a needless ceremony on the runtime that was kept.
- [ ] Preserve Codex config boundaries. **Assertion**: bytes outside the markers survive; a whitespace-only remainder
  deletes the file (`design_appendix.md` section C.6).
- [ ] Implement the failure taxonomy above, including reconciliation-write failure. **Assertion**: each boundary behaves
  as tabled; mutation precedes the tracking write (F2, application order); reconciliation-write failure exits non-zero
  naming the tracking path and neither retries nor partially writes.

## Phase 3 -- CLI surface

- [ ] Add `--runtime` to `disable_cmd` (`extensions.py:1205-1220`), spelled as on `enable`. **Assertion**:
  `click.Choice(["claude", "codex", "all"])`, repeatable, resolved through `_parse_skill_runtimes` (`:139`) so the two
  verbs cannot drift. Composes with `--scope` and `--all`.
- [ ] Filter the four existing plan tables (`:1279-1327`) rather than adding a render path. **Assertion**: skill
  packages, files, settings, and the Codex block line each narrow; the prompt at `:1329` and its `--yes` bypass are
  untouched (D-preview).
- [ ] Show retained unattributed rows in the plan (D-unattributed). **Assertion**: count and reason, so a legacy user is
  not told the runtime is gone while residue remains.
- [ ] State the re-trust consequence before the prompt. **Assertion**: shown whenever the Codex block is in the removal
  set; worded as a consequence, never as a claim that trust was verified.
- [ ] Add the full-uninstall prompt wording for the last-runtime case. **Assertion**: says this removes the whole
  installation for that scope; must not read like a partial removal.
- [ ] Report the no-op case with the resolved scope (D-autodetect-unchanged). **Assertion**: exit 0, nothing touched,
  message names the resolved scope and points at `--scope` -- because auto-detect picked the nearest install without
  considering runtimes.
- [ ] Compose with `--all` and add the DISPOSITION column (D-all-disposition). **Assertion**: each scope row shows
  `no-op` / `partial` / `full`; counts alone cannot distinguish them. `_uninstall_all_installations` (`:695`) still
  aggregates failures and exits non-zero if any scope fails, and `scripts/setup.sh --uninstall` must not read a
  partial-by-design disable as complete.
- [ ] Route recovery output through `forge.cli.output`. **Assertion**: no hand-rolled `Tip:` or `[red]Error:[/red]`; the
  two style-guard tests stay green.

## Phase 4 -- Sync and status coherence

- [ ] Assert sync does not resurrect. **Assertion**: per F1, `disable --runtime codex --yes` then `sync` leaves Codex
  absent -- asserted on **post-sync target paths**, not tracking contents.
- [ ] Assert `status --json` after a partial disable. **Assertion**: the shipped v3 status already emits
  `managed_runtimes`, `module_owners`, `modules`, and `unattributed_surfaces`, so this is assertion work: surviving
  runtime only, no dangling rows, no `skill_packages` row without files, `codex_config_path` cleared, `profile`
  retained.
- [ ] Confirm `profile` stays provenance (D-profile). **Assertion**: disable does not rewrite `profile`; replay comes
  from `module_owners` (`installer.py:2348`). Residual: `profile` still gates minimum-profile skill filtering, so a
  partially disabled row keeps its gate.

## Phase 5 -- Docs

- [ ] `docs/end-user/skills.md` -- `:55-64` documents `--runtime` selection and ends "Use `forge extension disable` for
  removal", which becomes incomplete once the flag exists. `:74` documents shared unscoped resolution for
  `sync`/`disable`/`status` and must stay true under D-autodetect-unchanged.
- [ ] `docs/end-user/hook.md` -- the re-trust consequence of removing the Codex block, next to the scope-mismatch
  paragraph.
- [ ] `docs/cli_reference.md` Installation table -- the flag, last-runtime behavior, `--all` composition.
- [ ] `docs/design_appendix.md` section C.4 -- runtime-scoped removal, the coherent-row requirement, the `.forge-added`
  rewrite on partial disable, and unattributed-row retention.
- [ ] `docs/board/change_log.md` -- feature-completion sized (15-25 lines).
- [ ] QA: extend `src/skills/qa/resources/checklist/18-disable.md`; update `<!-- test-count: -->` and
  `<!-- last-updated: -->` in `checklist.md` if the checkbox count changes.

## Acceptance tests

Split by layer: installer tests assert **state**, CLI tests assert **rendering, prompts, and exit codes**. No row
asserts across the boundary.

### Installer state

| Test                                       | Fixture                                                    | Assertion                                                                            | Test File                                                |
| ------------------------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------- |
| Codex removal leaves Claude byte-identical | dual install                                               | five Claude surfaces + packages byte-unchanged; registered-command golden intact     | `tests/src/install/test_disable_runtime.py`              |
| Claude removal is symmetric                | dual install                                               | five Claude surfaces **and** packages gone; Codex skills + block byte-unchanged      | `tests/src/install/test_disable_runtime.py`              |
| Success, runtime remains                   | dual install                                               | row retained; removed runtime's rows, packages, pairs dropped; codex fields cleared  | `tests/src/install/test_disable_runtime.py`              |
| Full coverage delegates                    | last-runtime, `--runtime all`, repeated flags              | all three take the `uninstall()` path; row deleted                                   | `tests/src/install/test_disable_runtime.py`              |
| `.forge-added` rewritten                   | partial disable, user re-adds a setting, then full disable | the re-added setting survives the full disable (F4)                                  | `tests/src/install/test_settings_merge.py`               |
| `settings_backup_path` retained            | partial disable                                            | unchanged after partial removal                                                      | `tests/src/install/test_disable_runtime.py`              |
| User edits survive smart unmerge           | user modified a Forge-set scalar                           | modification preserved, not reverted to backup (`settings_merge.py:252-272`)         | `tests/src/install/test_settings_merge.py`               |
| Codex block absent clears ownership        | tracked path, file deleted out of band                     | `(hooks, codex)` and config path cleared; exit 0                                     | `tests/src/install/test_disable_runtime.py`              |
| Codex malformed markers refuse             | partial/leftover markers                                   | ownership and config path retained; non-zero; file named                             | `tests/src/install/test_disable_runtime.py`              |
| Preflight refusal preserves everything     | `--runtime codex`, drifted `CODEX_HOME`                    | refuses; tracking and files untouched                                                | `tests/src/install/test_disable_runtime.py`              |
| Claude removal ignores Codex drift         | `--runtime claude`, drifted `CODEX_HOME`                   | succeeds; Codex ownership and config path retained (D-preflight-scoped)              | `tests/src/install/test_disable_runtime.py`              |
| Fault after file removal                   | injected file-removal fault                                | committed row matches files actually removed and passes `_validate_current_manifest` | `tests/src/install/test_disable_runtime.py`              |
| Fault during reconciliation write          | injected tracking-write failure                            | filesystem mutated, tracking retains pre-removal row, no partial write               | `tests/src/install/test_disable_runtime.py`              |
| Unattributed rows retained                 | migrated v1 install, `--runtime claude`                    | unattributed rows survive (F3 -- builder policy, so assert the builder output)       | `tests/src/install/test_disable_runtime.py`              |
| Full removal clears unattributed rows      | same fixture, `--runtime all`                              | everything removed including unattributed rows; row deleted                          | `tests/src/install/test_disable_runtime.py`              |
| Codex config boundaries preserved          | config with unrelated content                              | non-marker bytes survive; whitespace-only remainder deletes the file                 | `tests/src/install/test_codex_hooks.py`                  |
| Surviving runtime not re-trusted           | `--runtime claude` on a dual install                       | Codex command bytes unchanged, and the reverse case                                  | `tests/src/install/test_registered_commands_contract.py` |

### CLI rendering and exit

| Test                                    | Fixture                                                | Assertion                                                              | Test File                                |
| --------------------------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------- | ---------------------------------------- |
| Codex plan is exact                     | dual install, user scope                               | tables list exactly Codex packages + block; re-trust notice present    | `tests/src/cli/test_extension_enable.py` |
| Last-runtime prompt says full uninstall | single-runtime install                                 | prompt wording names full removal of the scope                         | `tests/src/cli/test_extension_enable.py` |
| Retained rows shown in plan             | migrated v1 install, `--runtime claude`                | count and reason rendered before the prompt                            | `tests/src/cli/test_extension_enable.py` |
| No-op names the resolved scope          | Claude-only local install, `--runtime codex`, unscoped | exit 0, message names the scope and `--scope` (D-autodetect-unchanged) | `tests/src/cli/test_extension_enable.py` |
| Mid-removal fault exit contract         | fault injected                                         | exits non-zero and names the retry                                     | `tests/src/cli/test_extension_enable.py` |
| `--all` disposition column              | scopes hitting no-op, partial, and full                | each row's disposition is correct even at `0` files / `0` packages     | `tests/src/cli/test_extension_enable.py` |
| `--all --runtime codex` aggregates      | two scopes, one failing                                | healthy scope disabled, failure named, exit non-zero                   | `tests/src/cli/test_extension_enable.py` |
| `--runtime all` equals today's disable  | dual install                                           | plan tables, prompt wording, exit code match existing disable tests    | `tests/src/cli/test_extension_enable.py` |
| `status --json` after partial disable   | dual install, `--runtime codex` applied                | surviving runtime only; no dangling rows; `codex_config_path` cleared  | `tests/src/cli/test_extension_enable.py` |

### Integration

| Test                    | Assertion                                                                 | Test File                                    |
| ----------------------- | ------------------------------------------------------------------------- | -------------------------------------------- |
| Sync does not resurrect | `disable --runtime codex --yes` then `sync`: Codex absent on target paths | `tests/integration/docker/test_installer.py` |

**Existing** (extend): `tests/src/cli/test_extension_enable.py` (owns enable *and* disable CLI coverage),
`tests/src/install/test_codex_hooks.py`, `test_installer.py`, `test_settings_merge.py`,
`test_registered_commands_contract.py`, `tests/integration/docker/test_installer.py`. **New**:
`tests/src/install/test_disable_runtime.py`.

`--runtime all` equivalence explicitly **excludes** the tracking representation (v3 shape) and the partial-failure path
(no pre-existing behavior to match), per the card.

## Verification log

(record each command and its result; do not tick a phase on a green unit run alone)

- [ ] `uv run pytest tests/src/install tests/src/cli -q`
- [ ] `make test-unit`
- [ ] `make test-regression`
- [ ] `./scripts/test-integration.sh tests/integration/docker/test_installer.py -v`
- [ ] Clean-wheel: enable -> partial disable -> status -> sync for each runtime, asserting non-resurrection.
  **Required**: `testing_guidelines.md` names installer changes as an integration trigger.
- [ ] `make pre-commit`

## Closeout

- [ ] Every box ticked with verification recorded.
- [ ] `docs/board/change_log.md` entry added.
- [ ] `cli_reference.md`, `design_appendix.md` section C.4, `end-user/hook.md`, and `end-user/skills.md` describe
  shipped behavior.
- [ ] Card moved `doing/` -> `done/` and inbound links repointed from `../../doing/extension_disable_runtime/...`:
  `done/runtime_scoped_extension_modules/card.md` (3), its `checklist.md` (2),
  `done/disable_scope_mismatch_orphan/card.md` (2), its `checklist.md` (1).
- [ ] Candidates for `impl_notes.md` after human review: schema validation proves manifest coherence and never
  filesystem truth, so removal correctness needs application order plus filesystem assertions (F2); settings removal is
  a three-way `smart_unmerge` against a `.forge-added` sidecar that any partial removal must rewrite, or a later full
  disable acts on stale ownership (F4); and an unprovable ownership row must be retained rather than guessed, which is
  why a runtime-scoped removal is deliberately less complete than a full one (F3).
