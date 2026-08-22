# Checklist: `forge extension disable --runtime`

**Card**: [card.md](card.md) **Branch**: `feat/extension-disable-runtime` **Base**: `main` at `4b9ad0ad`

**Current focus**: Complete -- implementation, documentation, clean-wheel lifecycle coverage, and closeout verification
are recorded below.

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

When the newest ownership sidecar is non-empty, `uninstall()` calls `smart_unmerge(current, backup, added)`
(`installer.py:2428-2430`), a three-way comparison that restores the backup value when `current == added` and **leaves
user modifications alone** (`settings_merge.py:252-272`). The fallback `unmerge` (`:775`) does not compare -- it deletes
tracked env keys outright (`:818-825`) -- and is not safe as the primary partial-removal path.

The three-way inputs come from durable sidecars: `find_backup_files` / `find_added_files` (`installer.py:2398-2399`),
where `added` is the `.forge-added` payload that **enable** rewrites from the surviving entry set on every install
(`entries_to_added_structure(final_entries)` + `save_added_settings`, `installer.py:1863-1864`).

**Consequence.** A partial disable that removes Claude settings entries must smart-unmerge using only the selected
entries, then reconcile `.forge-added` to the surviving entries. If it leaves stale ownership, a later full disable can
remove settings the user reintroduced after the partial disable. If no settings entries survive, there is no remaining
Claude-settings ownership: remove the `.forge-added` sidecars and clear `settings_backup_path` in tracking while keeping
the `.forge-backup` files as untracked history.

### F5 -- Codex marker state, not `CodexRemoveResult` alone, decides safety

`remove_codex_block` returns `removed=False` for a missing file, an existing file with no block, and malformed markers
(`codex_hooks.py:515-539`). `leftover_commands` is also not a discriminator: balanced-block removal can succeed while
manual Forge commands outside the markers remain, and those commands are user-owned, warning-only state
(`CodexRemoveResult`, `:447-457`). Runtime disable therefore needs an explicit pre-mutation marker-state decision and
apply-time revalidation; it cannot infer ownership disposition from `removed` plus file existence.

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

**D-settings-sidecar.** Treat the settings file plus all `.forge-added` files as one reversible subtransaction. Capture
their exact pre-step bytes/modes, smart-unmerge with `entries_to_added_structure(selected_settings_entries)`, then
update ownership from `surviving_settings_entries`. Field transitions:

| Surviving settings entries | `.forge-added`                                      | `settings_backup_path`                          | Tracking rows                  |
| -------------------------- | --------------------------------------------------- | ----------------------------------------------- | ------------------------------ |
| One or more                | newest payload rewritten to exactly those survivors | retained as their pre-Forge comparison baseline | selected settings rows dropped |
| Zero                       | all ownership sidecars removed                      | cleared                                         | all settings rows absent       |
| Settings not selected      | untouched                                           | untouched                                       | untouched                      |

`.forge-backup` files remain as history in every case. If either the settings write or ownership-sidecar update fails,
restore both surfaces exactly. A successful rollback means the settings step did not happen; an incomplete rollback is a
distinct manual-recovery failure that names every divergent path and retains the pre-step settings ownership in
tracking.

**D-codex-outcomes.** Decide from marker state before mutation and revalidate immediately before apply:

| Tracked config state                                      | Action                                                                                                  |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| File absent                                               | Clear stale `(hooks, codex)` ownership and config fields                                                |
| Existing file, no Forge markers                           | Preserve the file; clear the same stale ownership                                                       |
| Exactly one balanced managed block                        | Remove only the block; preserve all outside bytes; clear ownership                                      |
| Partial, duplicate, or otherwise unbalanced Forge markers | **Refuse before mutation**; retain ownership and config path; exit non-zero naming the file             |
| Unreadable file or state changed between plan and apply   | **Refuse**; retain ownership and config path; reconcile any earlier independent removals before exiting |

Forge commands outside managed markers, whether or not a balanced block is present, are manual/user-owned: preserve and
warn, but do not retain ownership of an absent or removed managed block. This intentionally differs from migration's
stricter `plan_codex_remove`, where a manual sibling blocks a cross-scope move.

**D-full-coverage.** Every invocation that spells `--runtime` uses the runtime-scoped removal engine, including
`--runtime all`, a last managed runtime, and repeated flags that collectively cover all runtimes
(`--runtime claude --runtime codex`). Full mode includes unattributed rows and deletes the installation row on success,
while retaining D-codex-outcomes and the failure taxonomy below. It reuses the existing uninstall primitives and
rendering, but does **not** dispatch wholesale to `uninstall()` because that path ignores `removed=False` and does not
reconcile a mid-removal fault. Bare `disable` remains on the existing path. Successful outcome and UI equivalence for
`--runtime all` are acceptance-tested on current sidecar-backed v3 state. Partial failures and legacy/no-sidecar
settings fallback are explicitly excluded: runtime-spelled removal uses the safe three-way comparison instead of bare
disable's blind `unmerge`.

**D-preflight-scoped.** Call `validate_codex_config_scope` only when the removal set includes the Codex managed block. A
Claude-only removal proceeds on an install whose Codex path drifted; nothing it touches depends on that mapping.

**D-autodetect-unchanged.** Unscoped `disable --runtime <r>` keeps nearest-scope resolution. Making disable search for a
runtime-managing scope would let it act on a *farther* scope than unscoped `sync` and `status` (`skills.md:74` documents
the shared resolution), which is a worse surprise than a no-op. When the resolved scope does not manage the runtime, the
no-op message names the resolved scope and points at `--scope`.

**D-all-disposition.** The `--all` summary gains a **DISPOSITION** column (`no-op` / `partial` / `full`), not just a
filtered caption. Counts alone cannot distinguish the three: a hooks-and-settings-only removal shows `0` files and `0`
packages while still mutating config and possibly deleting the row. This supersedes the caption-only approach in this
checklist's first draft. Counts come from each scope's actual removal set: full rows include unattributed surfaces;
partial/no-op rows exclude them and emit a scoped retained-residue note with count and reasons before the prompt.

---

## Failure taxonomy (per durable mutation boundary)

Run every knowable safety check -- tracked file boundaries, settings/sidecar readability and boundaries, Codex scope,
and Codex marker state -- before the first mutation. Apply-time races and I/O failures still need defined behavior:

| Boundary                                    | On failure                                                                                                                                     |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| File removal                                | Stop; reconcile tracking to the files actually removed; exit non-zero naming the retry                                                         |
| Settings + `.forge-added` subtransaction    | Restore both exact pre-step states; keep their tracking rows; reconcile earlier file removals; incomplete rollback names manual-recovery paths |
| Codex apply-time revalidation/block removal | Retain Codex ownership; reconcile earlier independent removals; exit non-zero naming the config                                                |
| Reconciliation write itself                 | See below -- the one case where the truthful new row cannot be guaranteed                                                                      |

**Reconciliation-write failure.** `TrackingStore.write()` is atomic (`tracking.py:679+`), so the file is never malformed
-- but atomicity does not guarantee the *new* row lands. If the reconciliation write fails, the filesystem has been
mutated while tracking still describes the pre-removal state, so tracking over-claims ownership of removed surfaces.

State this honestly rather than promising a guarantee the code cannot make:

- Exit non-zero with an error naming the tracking path and the fact that removal already happened.
- If the settings subtransaction landed, restore its captured settings and ownership-sidecar state before returning so
  the old tracking row never points at a newer, under-claiming sidecar. Report any rollback failure explicitly.
- Do **not** retry-loop or fall back to a partial tracking write. The remaining old-row over-claim for removed files or
  a removed Codex block is recoverable by repairing the tracking path and re-running the same disable; an under-claiming
  row would silently abandon surfaces.
- `forge extension status` is the read-only recovery surface for the old row's missing tracked files/block. If settings
  rollback was incomplete, the error's named paths require inspection before retry.

## Phase 1 -- Removal-set derivation (pure)

No CLI, no filesystem. This is the contract every later phase reads.

- [x] Add a removal-set builder returning the files, settings entries, skill packages, ownership pairs, Codex-block
  flag, and **surviving settings entries** for a given `Installation` plus selected runtime ids. **Assertion**:
  selection is the intersection of `MODULE_RUNTIME_OWNERS` with what tracking claims -- never the ownership map alone.
  Nothing untracked is adopted; `forge clean` still owns proven orphans.
- [x] Select rows via `ownership.attribution_pair` (`ownership.py:83`). **Assertion**: a `None` result (unattributed) is
  never a removal target, asserted directly against a migrated-v1 fixture. Per F3 this is builder policy -- the test
  must fail if the builder includes such a row, because `TrackingStore.write()` will not catch it.
- [x] Return selected and surviving settings entries for the smart-unmerge/sidecar subtransaction (D-settings-sidecar).
  **Assertion**: `entries_to_added_structure` consumes the selected set for smart-unmerge and the survivor set for
  durable ownership, so Phase 2 does not recompute either from a different source.
- [x] Make `--runtime claude` cover all five Claude surfaces plus Claude skill packages. **Assertion**: commands,
  agents, `hooks`, `statusLine`, and `permissions` settings entries, and Claude skill packages -- each asserted
  separately so a missing surface fails its own test. Under-removal is a named card risk.
- [x] Produce a post-removal `Installation` satisfying every v3 invariant. **Assertion**: rows dropped with their pairs
  (inv 2), packages with `(skills, runtime)` (inv 4), `codex_config_path` + `codex_commands` cleared exactly when
  `(hooks, codex)` is dropped (inv 5). Feed the result through `_validate_current_manifest` in the test. Per F2 this
  proves internal coherence only.
- [x] Report retained unattributed rows. **Assertion**: count and reasons, so the CLI can tell a legacy user what
  remains.
- [x] Detect full coverage, including repeated flags (D-full-coverage). **Assertion**: `--runtime all`, last-runtime,
  and `--runtime claude --runtime codex` on a dual install all report full coverage.

## Phase 2 -- Installer removal path

- [x] Add the runtime-scoped removal entry point, reusing `uninstall()`'s boundary validation. **Assertion**:
  `_tracked_file_boundary` + `validate_path_within_boundary` run on the filtered subset, so the `invalid-target` refusal
  for a symlink-replaced package root still applies (`design_installation.md` section C.5).
- [x] Keep every runtime-spelled request on the runtime-scoped engine, including full coverage (D-full-coverage).
  **Assertion**: full mode selects attributed plus unattributed rows, deletes the row on success, and still uses the
  Codex/failure rules below; it does not call `uninstall()` wholesale. Bare disable stays unchanged.
- [x] Smart-unmerge only the selected settings entries and reconcile `.forge-added` (F4, D-settings-sidecar).
  **Assertion**: call `smart_unmerge(current, backup, entries_to_added_structure(selected_entries))` -- **not**
  `settings_merge.unmerge`, which deletes tracked env keys without comparing (`:818-825`). With survivors, the newest
  `.forge-added` contains exactly their ownership and `settings_backup_path` is retained. With zero survivors, all
  ownership sidecars are removed and the field is cleared; backup-history files remain.
- [x] Make settings plus ownership sidecars a reversible subtransaction (D-settings-sidecar). **Assertion**: capture
  exact bytes/modes before either write; failure of the settings write or sidecar update restores both. Successful
  rollback retains all selected settings rows; incomplete rollback exits non-zero naming every divergent path and never
  drops those rows.
- [x] Scope the Codex preflight to the removal set (D-preflight-scoped). **Assertion**: `validate_codex_config_scope`
  runs iff the Codex block is being removed.
- [x] Classify and revalidate Codex marker state (D-codex-outcomes). **Assertion**: absent file or absent block clears
  stale ownership; exactly one balanced block is removed; partial/duplicate markers and unreadable or concurrently
  changed state refuse while retaining ownership. Outside-marker commands are preserved and warning-only. Per F5,
  neither `removed` nor `leftover_commands` alone is the classifier.
- [x] Do not re-render the surviving runtime's hook bytes. **Assertion**:
  `tests/src/install/test_registered_commands_contract.py` passes unchanged. Codex `trusted_hash` covers command bytes
  and config location, so a re-render forces a needless ceremony on the runtime that was kept.
- [x] Preserve Codex config boundaries. **Assertion**: bytes outside the markers survive; a whitespace-only remainder
  deletes the file (`design_installation.md` section C.6).
- [x] Implement the failure taxonomy above, including reconciliation-write failure. **Assertion**: each boundary behaves
  as tabled; mutation precedes the tracking write (F2, application order); reconciliation-write failure restores the
  settings subtransaction, exits non-zero naming the tracking path and any rollback failure, and neither retries nor
  partially writes tracking.

## Phase 3 -- CLI surface

- [x] Add `--runtime` to `disable_cmd` (`extensions.py:1205-1220`), spelled as on `enable`. **Assertion**:
  `click.Choice(["claude", "codex", "all"])`, repeatable, resolved through `_parse_skill_runtimes` (`:139`) so the two
  verbs cannot drift. Composes with `--scope` and `--all`.
- [x] Filter the four existing plan tables (`:1279-1327`) rather than adding a render path. **Assertion**: skill
  packages, files, settings, and the Codex block line each narrow; the confirmation position and `--yes` bypass at
  `:1329` are retained (D-preview). Wording changes only when individual runtime flags imply full removal and in
  runtime-filtered batch mode; an explicit single-scope `--runtime all` keeps the existing prompt golden.
- [x] Show retained unattributed rows in the plan (D-unattributed). **Assertion**: count and reason, so a legacy user is
  not told the runtime is gone while residue remains.
- [x] State the re-trust consequence before the prompt. **Assertion**: shown whenever the Codex block is in the removal
  set; worded as a consequence, never as a claim that trust was verified.
- [x] Add full-uninstall wording when individual runtime flags cover the whole row. **Assertion**: last-runtime and
  repeated `claude` + `codex` selections say this removes the whole installation for that scope; neither may read like a
  partial removal.
- [x] Report the no-op case with the resolved scope (D-autodetect-unchanged). **Assertion**: exit 0, nothing touched,
  message names the resolved scope and points at `--scope` -- because auto-detect picked the nearest install without
  considering runtimes.
- [x] Compose with `--all` and add the DISPOSITION column (D-all-disposition). **Assertion**: each scope row shows
  `no-op` / `partial` / `full`; counts alone cannot distinguish them. The prompt and per-scope/final completion messages
  name the selected runtime operation rather than saying every installation was disabled when rows remain.
  Full-disposition counts include unattributed rows being removed; partial/no-op rows with legacy residue get a scoped
  count-and-reason note before confirmation. `_uninstall_all_installations` (`:695`) still aggregates failures and exits
  non-zero if any scope fails. Bare `scripts/setup.sh --uninstall` passes no runtime filter and retains its
  complete-removal contract.
- [x] Route recovery output through `forge.cli.output`. **Assertion**: no hand-rolled `Tip:` or `[red]Error:[/red]`; the
  two style-guard tests stay green.

## Phase 4 -- Sync and status coherence

- [x] Assert sync does not resurrect. **Assertion**: per F1, `disable --runtime codex --yes` then `sync` leaves Codex
  absent -- asserted on **post-sync target paths**, not tracking contents.
- [x] Assert `status --json` after a partial disable. **Assertion**: the shipped v3 status already emits
  `managed_runtimes`, `module_owners`, `modules`, and `unattributed_surfaces`, so this is assertion work: surviving
  runtime only, no dangling rows, no `skill_packages` row without files, `codex_config_path` cleared, `profile`
  retained.
- [x] Confirm `profile` stays provenance (D-profile). **Assertion**: disable does not rewrite `profile`; replay comes
  from `module_owners` (`installer.py:2348`). Residual: `profile` still gates minimum-profile skill filtering, so a
  partially disabled row keeps its gate.

## Phase 5 -- Docs

- [x] `docs/end-user/skills.md` -- `:55-64` documents `--runtime` selection and ends "Use `forge extension disable` for
  removal", which becomes incomplete once the flag exists. `:74` documents shared unscoped resolution for
  `sync`/`disable`/`status` and must stay true under D-autodetect-unchanged.
- [x] `docs/end-user/hook.md` -- the re-trust consequence of removing the Codex block, next to the scope-mismatch
  paragraph; distinguish stale-absent ownership, unsafe markers, and preserved manual outside-marker commands.
- [x] `docs/cli_reference.md` Installation table -- the flag, last-runtime behavior, `--all` disposition/completion
  contract, and the reconciliation-write exception.
- [x] `docs/design_installation.md` sections C.3-C.6 -- runtime-scoped removal, coherent-row requirements, the
  reversible settings/sidecar subtransaction including zero survivors and the legacy/no-sidecar safety exception,
  unattributed-row retention, and Codex marker outcomes.
- [x] `docs/board/change_log.md` -- feature-completion sized (15-25 lines).
- [x] QA: extend `src/skills/qa/resources/checklist/18-disable.md`; update `<!-- test-count: -->` and
  `<!-- last-updated: -->` in `checklist.md` if the checkbox count changes.

## Acceptance tests

Split by layer: installer tests assert **state**, CLI tests assert **rendering, prompts, and exit codes**. No row
asserts across the boundary.

### Installer state

| Test                                          | Fixture                                                         | Assertion                                                                                               | Test File                                                |
| --------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Codex removal leaves Claude byte-identical    | dual install                                                    | five Claude surfaces + packages byte-unchanged; registered-command golden intact                        | `tests/src/install/test_disable_runtime.py`              |
| Claude removal is symmetric                   | dual install                                                    | five Claude surfaces **and** packages gone; Codex skills + block byte-unchanged                         | `tests/src/install/test_disable_runtime.py`              |
| Success, runtime remains                      | dual install                                                    | row retained; removed runtime's rows, packages, pairs dropped; Codex fields cleared                     | `tests/src/install/test_disable_runtime.py`              |
| Full coverage uses safe full mode             | last-runtime, `--runtime all`, repeated flags                   | all include unattributed rows, enforce Codex preflight, and delete the row on success                   | `tests/src/install/test_disable_runtime.py`              |
| Unselected settings ownership is unchanged    | dual install, remove Codex                                      | settings, `.forge-added`, and `settings_backup_path` remain byte/value-identical                        | `tests/src/install/test_disable_runtime.py`              |
| Zero settings survivors clear ownership       | dual install, remove Claude                                     | all `.forge-added` files removed; `settings_backup_path` cleared; `.forge-backup` history kept          | `tests/src/install/test_disable_runtime.py`              |
| User re-add survives later full disable       | remove Claude, user re-adds a setting, then remove Codex        | re-added setting survives and the Codex-only row causes no Claude-settings rewrite                      | `tests/src/install/test_disable_runtime.py`              |
| User edits survive smart unmerge              | user modified a Forge-set scalar                                | modification preserved, not reverted to backup (`settings_merge.py:252-272`)                            | `tests/src/install/test_settings_merge.py`               |
| Legacy no-sidecar edits survive               | migrated row, no `.forge-added`, modified scalar/env            | `--runtime all` preserves edits while removing tracked state and the row                                | `tests/src/install/test_disable_runtime.py`              |
| Settings-write fault rolls back both surfaces | injected settings write failure                                 | settings and every `.forge-added` file remain byte/mode-identical; settings tracking retained           | `tests/src/install/test_disable_runtime.py`              |
| Sidecar-write fault rolls back both surfaces  | settings write lands, injected sidecar failure                  | same exact rollback; earlier removed files alone are reconciled                                         | `tests/src/install/test_disable_runtime.py`              |
| Incomplete settings rollback is explicit      | injected apply failure plus rollback failure                    | selected settings ownership retained; exception names every divergent settings/sidecar path             | `tests/src/install/test_disable_runtime.py`              |
| Codex stale absence clears ownership          | file absent, then existing file with no markers                 | both cases preserve unrelated bytes and clear `(hooks, codex)` plus config fields                       | `tests/src/install/test_disable_runtime.py`              |
| Codex malformed markers refuse                | partial/duplicate markers on dual and Codex-only installs       | partial and full modes name file; ownership, config path, and all preflighted surfaces remain untouched | `tests/src/install/test_disable_runtime.py`              |
| Manual Codex siblings remain user-owned       | balanced block plus outside-marker Forge commands               | block removed; manual commands preserved and warned; managed ownership cleared                          | `tests/src/install/test_disable_runtime.py`              |
| Preflight refusal preserves everything        | `--runtime codex`, drifted `CODEX_HOME`                         | raises; tracking and files untouched                                                                    | `tests/src/install/test_disable_runtime.py`              |
| Codex leaf symlink refuses                    | tracked config replaced by a symlink                            | symlink, target, files, settings, and tracking remain untouched                                         | `tests/src/install/test_disable_runtime.py`              |
| Claude removal ignores Codex drift            | `--runtime claude`, drifted `CODEX_HOME`                        | succeeds; Codex ownership and config path retained (D-preflight-scoped)                                 | `tests/src/install/test_disable_runtime.py`              |
| Fault after file removal                      | injected file-removal fault                                     | committed row matches files actually removed and passes `_validate_current_manifest`                    | `tests/src/install/test_disable_runtime.py`              |
| Reconciliation-write fault restores settings  | injected tracking failure after files, settings, and Codex work | old row remains atomically; settings/sidecars restored; removed files/block remain safe over-claims     | `tests/src/install/test_disable_runtime.py`              |
| Unattributed rows retained                    | migrated v1 install, `--runtime claude`                         | unattributed rows survive (F3 -- builder policy, so assert the builder output)                          | `tests/src/install/test_disable_runtime.py`              |
| Full removal clears unattributed rows         | same fixture, `--runtime all`                                   | everything removed including unattributed rows; row deleted                                             | `tests/src/install/test_disable_runtime.py`              |
| Codex config boundaries preserved             | config with unrelated content                                   | non-marker bytes survive; whitespace-only remainder deletes the file                                    | `tests/src/install/test_codex_hooks.py`                  |
| Surviving runtime not re-trusted              | `--runtime claude` on a dual install                            | Codex command bytes unchanged, and the reverse case                                                     | `tests/src/install/test_registered_commands_contract.py` |

### CLI rendering and exit

| Test                                      | Fixture                                                | Assertion                                                                    | Test File                                |
| ----------------------------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------- | ---------------------------------------- |
| Codex plan is exact                       | dual install, user scope                               | tables list exactly Codex packages + block; re-trust notice present          | `tests/src/cli/test_extension_enable.py` |
| Implicit-full prompt says full uninstall  | last-runtime and repeated-runtime full coverage        | prompt wording names full removal of the scope                               | `tests/src/cli/test_extension_enable.py` |
| Retained rows shown in plan               | migrated v1 install, `--runtime claude`                | count and reason rendered before the prompt                                  | `tests/src/cli/test_extension_enable.py` |
| No-op names the resolved scope            | Claude-only local install, `--runtime codex`, unscoped | exit 0, message names the scope and `--scope` (D-autodetect-unchanged)       | `tests/src/cli/test_extension_enable.py` |
| Mutation fault exit contract              | injected file fault                                    | exits non-zero and names the retry                                           | `tests/src/cli/test_extension_enable.py` |
| Tracking-write fault is honest            | injected reconciliation failure                        | exits non-zero; names tracking path, prior mutations, and settings rollback  | `tests/src/cli/test_extension_enable.py` |
| Codex refusal names recovery              | malformed marker fixture                               | exits non-zero, names config, leaves tracking and all preflighted state      | `tests/src/cli/test_extension_enable.py` |
| `--all` disposition column                | scopes hitting no-op, partial, and full                | each row's disposition is correct even at `0` files / `0` packages           | `tests/src/cli/test_extension_enable.py` |
| `--all` legacy residue is honest          | migrated rows hitting partial and full                 | partial note retains count/reasons; full counts include unattributed removal | `tests/src/cli/test_extension_enable.py` |
| `--all` completion names selected runtime | same mixed scopes, successful apply                    | no row/final message claims every installation was removed                   | `tests/src/cli/test_extension_enable.py` |
| `--all --runtime codex` aggregates        | two scopes, one failing                                | healthy scope processed, failure named, exit non-zero                        | `tests/src/cli/test_extension_enable.py` |
| `--runtime all` equals today's disable    | sidecar-backed v3 dual install                         | end state, plan tables, prompt wording, and exit code match existing disable | `tests/src/cli/test_extension_enable.py` |
| `status --json` after partial disable     | dual install, `--runtime codex` applied                | surviving runtime only; no dangling rows; `codex_config_path` cleared        | `tests/src/cli/test_extension_enable.py` |

### Integration

| Test                    | Assertion                                                                 | Test File                                    |
| ----------------------- | ------------------------------------------------------------------------- | -------------------------------------------- |
| Sync does not resurrect | `disable --runtime codex --yes` then `sync`: Codex absent on target paths | `tests/integration/docker/test_installer.py` |

**Existing** (extend): `tests/src/cli/test_extension_enable.py` (owns enable *and* disable CLI coverage),
`tests/src/install/test_codex_hooks.py`, `test_installer.py`, `test_settings_merge.py`,
`test_registered_commands_contract.py`, `tests/integration/docker/test_installer.py`. **New**:
`tests/src/install/test_disable_runtime.py`.

`--runtime all` equivalence explicitly **excludes** the tracking representation, partial-failure path, and
legacy/no-sidecar `unmerge` fallback, per the card.

## Verification log

(record each command and its result; do not tick a phase on a green unit run alone)

- [x] `uv run pytest tests/src/install tests/src/cli -q` -- `3369 passed, 1 skipped`.
- [x] `make test-unit` -- `8584 passed, 1 skipped, 117 deselected`.
- [x] `make test-regression` -- `551 passed`.
- [x] `./scripts/test-integration.sh tests/integration/docker/test_installer.py -v` -- `21 passed`.
- [x] Clean-wheel: enable -> partial disable -> status -> sync for each runtime, asserting non-resurrection.
  **Required**: `testing_guidelines.md` names installer changes as an integration trigger.
- [x] `make pre-commit` -- all hooks passed.

## Closeout

- [x] Every box ticked with verification recorded.
- [x] `docs/board/change_log.md` entry added.
- [x] `cli_reference.md`, `design_installation.md` sections C.3-C.6, `end-user/hook.md`, and `end-user/skills.md`
  describe shipped behavior.
- [x] Card moved `doing/` -> `done/` and inbound links repointed from `../../doing/extension_disable_runtime/...`:
  `done/runtime_scoped_extension_modules/card.md` (3), its `checklist.md` (2),
  `done/disable_scope_mismatch_orphan/card.md` (2), its `checklist.md` (1).
- [x] Candidates for `impl_notes.md` after human review: schema validation proves manifest coherence and never
  filesystem truth, so removal correctness needs application order plus filesystem assertions (F2); settings removal is
  a reversible three-way `smart_unmerge` plus ownership-sidecar transition whose zero-survivor state must relinquish
  ownership (F4); and an unprovable ownership row must be retained rather than guessed, which is why a runtime-scoped
  removal is deliberately less complete than a full one (F3). Candidates are recorded here for human review; none were
  promoted automatically during implementation.
