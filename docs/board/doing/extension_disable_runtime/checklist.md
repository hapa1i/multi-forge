# Checklist: `forge extension disable --runtime`

**Card**: [card.md](card.md) **Branch**: `feat/extension-disable-runtime` **Base**: `main` at `4b9ad0ad`

**Current focus**: Phase 1 -- the removal-set derivation, which is pure, testable without the CLI, and the input every
later phase depends on.

---

## Planning findings (verified against `main` at `4b9ad0ad`)

`card.md` was written before `disable_scope_mismatch_orphan` (#115) and `runtime_scoped_extension_modules` (#116). Two
of its Constraints are now **obsolete because they were satisfied**, and both are phrased as blockers:

| Card constraint                                                                | Status now                                                                                                 |
| ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| "No deletion-grade attribution exists today ... **impossible** until D1 lands" | **Satisfied.** `InstalledFile` (`models.py:158`) and `InstalledSettingsEntry` (`:181`) carry `attribution` |
| "Scope mismatch currently warns and orphans"                                   | **Fixed.** `validate_codex_config_scope` refuses the operation and preserves tracking                      |

Re-verified anchors (all drifted):

| Surface                        | Card says                 | Actual                                                   |
| ------------------------------ | ------------------------- | -------------------------------------------------------- |
| `disable_cmd` + options        | `extensions.py:1166-1180` | `:1205-1220`                                             |
| Plan render (single scope)     | `:1236-1284`              | `:1279-1327`                                             |
| Prompt / apply                 | `:1275-1292`              | `:1329-1333`                                             |
| `--all` dispatch               | `:1211-1213`              | `:1245-1251`                                             |
| `--all` summary render         | `:656-690`                | `_uninstall_all_installations` at `:695`                 |
| `uninstall()`                  | `installer.py:2389-2464`  | `:2377`, with the codex preflight at `:2387`             |
| Sync replay                    | `:2347-2372, 2374-2388`   | `:2342-2357` and `:2362-2375`                            |
| Settings unmerge               | `:2439-2456`              | `:2429`, delegating to `settings_merge.unmerge` (`:775`) |
| Row models                     | `models.py:129-165`       | `:158` and `:181`                                        |
| `MANAGED_RUNTIME_PRESERVATION` | `skill_planning.py:81-82` | `:80`, `preserved_runtime_ids` at `:101`, set at `:232`  |

### F1 -- Sync resurrection is structurally closed; the requirement moved

The card calls silent resurrection via sync its sharpest correctness requirement, because `init_from_existing` /
`plan_update` replayed `_modules_override` from `modules_enabled` **and** derived runtimes from `skill_packages` -- two
fields to keep in step.

Both now read one source: `existing_modules = {InstallModule(m) for m in module_values(existing)}` and
`managed_runtime_ids = owned_runtime_ids(existing)` (`installer.py:2348-2349`, `:2367-2368`), each derived from
`module_owners`. **Dropping a runtime's ownership pairs is therefore sufficient** to stop sync replanning it.

The requirement does not disappear -- it becomes: *the ownership pairs are the thing that must be dropped*. A removal
that deletes files but leaves `(skills, codex)` in `module_owners` is resurrected by the next `sync`, and that is still
the failure a filesystem-only test would pass.

### F2 -- The v3 invariants make an incoherent partial write impossible, not just discouraged

`TrackingStore.write()` calls `_validate_current_manifest` before persisting. Four invariants constrain any
runtime-scoped removal:

| Invariant | Constraint on removal                                                                                          |
| --------- | -------------------------------------------------------------------------------------------------------------- |
| 2         | Every file/settings row's attribution must be in `module_owners` -- dropping a pair requires dropping its rows |
| 3         | Row identities stay unique (`target_path`; `(key_path, stable_id)`)                                            |
| 4         | Every `skill_packages` row needs a matching `(skills, runtime)` pair -- packages and pair drop together        |
| 5         | `(hooks, codex)` **iff** `codex_config_path` is set -- pair and config path are an atomic unit                 |

Invariant 5 is the sharp one: the Codex block removal and the tracking fields must both succeed or both be left alone.
Clearing `codex_config_path` while retaining the pair, or vice versa, raises `TrackingCorruptedError` at write.

A pair with **zero** remaining rows is legal (invariant 2 is per-row, not per-pair), which is the slack that makes a
mid-removal fault representable: drop exactly the rows actually removed, keep the pair.

### F3 -- Unattributed rows cannot be runtime-scoped removal targets

Invariant 6: a row carrying `UnattributedSurface` is readable and reportable but is not a valid mutation input for a
runtime-scoped removal. Legacy v1/v2 installs migrate with `legacy_path_unmapped` / `legacy_key_unmapped` /
`legacy_v1_unprovable` rows (`ownership.py:27-33`).

So on a migrated install, `disable --runtime claude` cannot remove unattributed rows, while a bare `disable` removes
everything. The card does not address this asymmetry. Decided below.

### F4 -- The codex scope preflight should gate on the removal set, not the command

`uninstall()` calls `validate_codex_config_scope(existing)` unconditionally at `installer.py:2387`. Under
`--runtime claude` nothing touches `$CODEX_HOME`, so refusing the whole operation because a *Codex* path drifted would
be over-strict -- it would block a Claude-only removal on an unrelated mismatch. Decided below.

---

## Decisions taken here (overridable before Phase 2)

**D-unattributed.** `--runtime <r>` leaves unattributed rows in place and reports them; only a full removal
(`--runtime all`, bare `disable`, or the D-last last-runtime case) removes them. Guessing that an unattributed row is
Claude's is precisely what would delete a Codex file under `--runtime claude`, which is the risk the shipped schema was
built to prevent. The plan output must say how many rows were retained and why, so a legacy user is not told the runtime
is gone when residue remains.

**D-last-delegates.** When the selection covers every managed runtime -- `--runtime all`, or a `--runtime <r>` that is
the last managed runtime -- dispatch to the **existing** `uninstall()` rather than a filtered path. This makes the
card's "`--runtime all` matches today's `disable`" criterion true by construction rather than by assertion, keeps
unattributed rows removed in the full case, and means the D-last prompt is the only new wording needed.

**D-preflight-scoped.** Call `validate_codex_config_scope` only when the removal set includes the Codex managed block
(that is, when `codex` is selected and `codex_config_path` is set). A Claude-only removal proceeds on an install whose
Codex path has drifted; nothing it touches depends on that mapping, and the drifted Codex ownership is retained
untouched.

**D-all-caption.** The `--all` per-scope summary keeps its existing columns and gains a filtered caption naming the
selected runtimes, not a new column. The card left this open; a column would repeat one value on every row.

---

## Phase 1 -- Removal-set derivation (pure)

No CLI, no filesystem. This is the contract every later phase reads.

- [ ] Add a removal-set builder that, given an `Installation` and selected runtime ids, returns the files, settings
  entries, skill packages, ownership pairs, and Codex-block flag to remove. **Assertion**: selection is the intersection
  of `MODULE_RUNTIME_OWNERS` with what tracking claims -- never the ownership map alone. Nothing untracked is adopted;
  `forge clean` still owns proven orphans.
- [ ] Select rows by `attribution`, using `ownership.attribution_pair` (`ownership.py:83`). **Assertion**:
  `attribution_pair` returns `None` for `UnattributedSurface`, and a `None` result is never a removal target
  (F3/invariant 6). Assert directly with a migrated-v1 fixture, not by inference.
- [ ] Make `--runtime claude` cover all five Claude surfaces plus Claude skill packages. **Assertion**: commands,
  agents, `hooks`, `statusLine`, and `permissions` settings entries, and Claude skill packages. The card names
  under-removal ("skills plus hooks") as a named risk -- assert each surface separately so a missing one fails its own
  test.
- [ ] Produce a coherent post-removal `Installation` that satisfies every v3 invariant. **Assertion**: per F2 -- rows
  dropped with their pairs (inv 2), packages dropped with `(skills, runtime)` (inv 4), and `codex_config_path` +
  `codex_commands` cleared exactly when `(hooks, codex)` is dropped (inv 5). Feed the result through
  `_validate_current_manifest` in the test rather than eyeballing the fields.
- [ ] Report retained unattributed rows. **Assertion**: the builder returns a count and reasons so the CLI can state
  what a legacy install kept (D-unattributed).

## Phase 2 -- Installer removal path

- [ ] Add the runtime-scoped removal entry point on `Installer`, reusing `uninstall()`'s boundary validation.
  **Assertion**: `_tracked_file_boundary` + `validate_path_within_boundary` run on the filtered subset, so the
  `invalid-target` refusal for a symlink-replaced package root still applies unchanged (`design_appendix.md` section
  C.5).
- [ ] Dispatch the full-removal cases to the existing `uninstall()` (D-last-delegates). **Assertion**: `--runtime all`,
  and a `--runtime <r>` covering the last managed runtime, take the existing path -- not a filtered one that happens to
  select everything. The `--runtime all` no-regression golden then holds by construction.
- [ ] Scope the Codex preflight to the removal set (D-preflight-scoped). **Assertion**: `validate_codex_config_scope`
  runs iff the Codex block is being removed. A `--runtime claude` removal on an install with a drifted Codex path
  succeeds and leaves Codex ownership intact; a `--runtime codex` removal on the same install still refuses and
  preserves tracking.
- [ ] Remove the Codex managed block without re-rendering the surviving runtime's hook bytes. **Assertion**:
  `tests/src/install/test_registered_commands_contract.py` passes unchanged. Codex `trusted_hash` covers registered
  command bytes and config location and is not computable by Forge, so a re-render forces a needless ceremony on the
  runtime that was *kept*.
- [ ] Preserve boundary behavior for the Codex config. **Assertion**: bytes outside the Forge markers survive; a config
  left whitespace-only is deleted (`design_appendix.md` section C.6). Claude settings use the existing
  `settings_merge.unmerge` (`:775`) matching on `stable_id`, so user edits survive.
- [ ] Commit tracking to reflect what was actually removed on a mid-removal fault. **Assertion**: per F2, the committed
  row keeps pairs whose rows partially survive and drops rows that are gone; the write passes validation. Exit non-zero
  and name the retry. Unlike `enable`, there is no rollback-by-restore -- the reconciled row is the recovery surface.

## Phase 3 -- CLI surface

- [ ] Add `--runtime` to `disable_cmd` (`extensions.py:1205-1220`), spelled as on `enable`. **Assertion**:
  `click.Choice(["claude", "codex", "all"])`, repeatable, resolved through `_parse_skill_runtimes` (`:139`) so both
  verbs cannot drift. Composes with `--scope` and `--all`.
- [ ] Filter the four existing plan tables (`extensions.py:1279-1327`) rather than adding a render path. **Assertion**:
  skill packages, files, settings, and the Codex block line each narrow to the selection; the prompt at `:1329` and its
  `--yes` bypass are untouched. D-preview: no new confirmation shape.
- [ ] State the re-trust consequence in the plan, before the prompt. **Assertion**: shown whenever the Codex block is in
  the removal set; worded as a consequence, never as a claim about whether trust was verified.
- [ ] Add the D-last full-uninstall prompt wording. **Assertion**: when the selection is the last managed runtime, the
  prompt says this removes the whole installation for that scope. The card leaves the exact wording to the checklist; it
  must not read like a partial removal.
- [ ] Report the no-op case. **Assertion**: disabling a runtime the installation does not manage exits 0 with an
  explicit message and touches nothing -- distinct from a silent success.
- [ ] Compose with `--all` (D-all-caption). **Assertion**: `_uninstall_all_installations` (`:695`) filters its per-scope
  counts and gains a caption naming the selected runtimes; it still aggregates failures and exits non-zero if any scope
  fails. `scripts/setup.sh     --uninstall` must not read a partial-by-design disable as complete.
- [ ] Route all recovery output through `forge.cli.output`. **Assertion**: no hand-rolled `Tip:` or `[red]Error:[/red]`;
  `test_cli_rich_tips_go_through_output_helpers` and `test_cli_rich_errors_go_through_print_error` stay green.

## Phase 4 -- Sync and status coherence

- [ ] Assert sync does not resurrect. **Assertion**: per F1, `disable --runtime codex --yes` then `forge extension sync`
  leaves Codex absent -- asserted on **post-sync target paths**, not tracking contents, because tracking-only assertions
  are what let the original failure mode hide.
- [ ] Assert `status --json` after a partial disable. **Assertion**: the shipped v3 status already emits
  `managed_runtimes`, `module_owners`, `modules`, and `unattributed_surfaces`, so this is assertion work, not new
  fields: surviving runtime only, no dangling ledger rows, no `skill_packages` row without files, `codex_config_path`
  cleared, `profile` retained.
- [ ] Confirm `profile` stays provenance (D-profile). **Assertion**: disable does not rewrite `profile`; module replay
  comes from `module_owners` (`installer.py:2348`), not `profile`. Note the residual: `profile` still gates
  minimum-profile skill filtering, so a partially disabled row keeps its original gate.

## Phase 5 -- Docs

- [ ] `docs/cli_reference.md` Installation table -- add the flag, D-last behavior, and `--all` composition.
- [ ] `docs/design_appendix.md` section C.4 -- record runtime-scoped removal, the coherent-row requirement, and that
  unattributed rows are retained by a runtime-scoped removal (D-unattributed).
- [ ] `docs/end-user/hook.md` -- the re-trust consequence of removing the Codex block, next to the existing
  scope-mismatch paragraph.
- [ ] `docs/board/change_log.md` -- feature-completion sized (15-25 lines per `board_contract.md`).
- [ ] QA checklist: add coverage under `src/skills/qa/resources/checklist/18-disable.md`, and update
  `<!-- test-count: -->` and `<!-- last-updated: -->` in `src/skills/qa/resources/checklist.md` if the checkbox count
  changes.

## Acceptance tests

Every state-transition row from the card is a test.

| Test                                       | Fixture                                      | Assertion                                                                                                                                        | Test File                                                |
| ------------------------------------------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------- |
| Codex removal plan is exact                | dual install, user scope                     | plan lists exactly Codex packages + the block, includes the re-trust notice                                                                      | `tests/src/cli/test_extension_enable.py`                 |
| Codex removal leaves Claude byte-identical | dual install                                 | all five Claude surfaces + Claude packages byte-unchanged, registered-command golden intact                                                      | `tests/src/install/test_disable_runtime.py`              |
| Claude removal is symmetric                | dual install                                 | all five Claude surfaces **and** Claude packages gone; Codex skills + block byte-unchanged                                                       | `tests/src/install/test_disable_runtime.py`              |
| Success, runtime remains                   | dual install                                 | row retained; that runtime's rows, packages, and pairs dropped; codex fields cleared                                                             | `tests/src/install/test_disable_runtime.py`              |
| Success, last runtime (D-last)             | single-runtime install                       | delegates to `uninstall()`; row deleted; prompt states full uninstall                                                                            | `tests/src/install/test_disable_runtime.py`              |
| Runtime not managed here                   | Claude-only install, `--runtime codex`       | exit 0, explicit no-op message, filesystem and tracking untouched                                                                                | `tests/src/cli/test_extension_enable.py`                 |
| Preflight refusal preserves everything     | `--runtime codex`, drifted `CODEX_HOME`      | refuses, exits non-zero, tracking and files untouched                                                                                            | `tests/src/install/test_disable_runtime.py`              |
| Claude removal ignores Codex drift         | `--runtime claude`, drifted `CODEX_HOME`     | succeeds; Codex ownership and config path retained untouched (D-preflight-scoped)                                                                | `tests/src/install/test_disable_runtime.py`              |
| Mid-removal fault commits truthfully       | fault injected after partial file removal    | committed row matches what was removed and passes `_validate_current_manifest`; exit non-zero names the retry                                    | `tests/src/install/test_disable_runtime.py`              |
| Sync does not resurrect                    | `disable --runtime codex --yes`, then `sync` | Codex absent on **post-sync target paths**                                                                                                       | `tests/integration/docker/test_installer.py`             |
| Unattributed rows are retained             | migrated v1 install, `--runtime claude`      | unattributed rows survive; count and reason reported (D-unattributed)                                                                            | `tests/src/install/test_disable_runtime.py`              |
| Full removal clears unattributed rows      | same fixture, `--runtime all`                | everything removed, including unattributed rows; row deleted                                                                                     | `tests/src/install/test_disable_runtime.py`              |
| Coherent row after every removal           | each removal case above                      | result passes `_validate_current_manifest`; invariant 5 holds as an iff                                                                          | `tests/src/install/test_disable_runtime.py`              |
| Surviving runtime not re-trusted           | `--runtime claude` on a dual install         | Codex registered-command bytes unchanged, and the reverse case for Claude                                                                        | `tests/src/install/test_registered_commands_contract.py` |
| Codex config boundaries preserved          | config with unrelated content                | non-marker bytes survive byte-for-byte; whitespace-only remainder deletes the file                                                               | `tests/src/install/test_codex_hooks.py`                  |
| `--runtime all` equals today's disable     | dual install                                 | filesystem end state, settings unmerge, block removal, row deletion, plan tables, prompt wording, exit code all match the existing disable tests | `tests/src/cli/test_extension_enable.py`                 |
| `--all --runtime codex` aggregates         | two scopes, one failing                      | healthy scope disabled, failure named, exit non-zero                                                                                             | `tests/src/cli/test_extension_enable.py`                 |
| `status --json` after partial disable      | dual install, `--runtime codex` applied      | surviving runtime only; no dangling rows; `codex_config_path` cleared; `profile` kept                                                            | `tests/src/cli/test_extension_enable.py`                 |

**Existing** (extend): `tests/src/cli/test_extension_enable.py` (owns all enable *and* disable CLI coverage, codex-hooks
class at `:2001`), `tests/src/install/test_codex_hooks.py`, `test_installer.py`, `test_registered_commands_contract.py`,
`tests/integration/docker/test_installer.py`. **New**: `tests/src/install/test_disable_runtime.py`.

`--runtime all` equivalence explicitly **excludes** the tracking representation (v3 shape) and the partial-failure path
(no pre-existing behavior to match), per the card.

## Verification log

(record each command and its result; do not tick a phase on a green unit run alone)

- [ ] `uv run pytest tests/src/install tests/src/cli -q`
- [ ] `make test-unit`
- [ ] `make test-regression`
- [ ] `./scripts/test-integration.sh tests/integration/docker/test_installer.py -v`
- [ ] Clean-wheel: enable -> partial disable -> status -> sync for each runtime, asserting non-resurrection.
  **Required**: `testing_guidelines.md` names installer changes as an integration trigger, and unit tests cannot reach
  the wheel-install path.
- [ ] `make pre-commit`

## Closeout

- [ ] Every box ticked with verification recorded.
- [ ] `docs/board/change_log.md` entry added.
- [ ] `cli_reference.md`, `design_appendix.md` section C.4, and `end-user/hook.md` describe shipped behavior.
- [ ] Card moved `doing/` -> `done/` and inbound links repointed from `../../doing/extension_disable_runtime/...`:
  `done/runtime_scoped_extension_modules/card.md` (3), its `checklist.md` (2), and
  `done/disable_scope_mismatch_orphan/card.md` (2), its `checklist.md` (1).
- [ ] Candidates for `impl_notes.md` after human review: a schema whose invariants make incoherent state unwritable
  converts partial-failure handling from discipline into a checkable contract (F2); deriving replay from one field
  closed the sync-resurrection class without a disable-side guard (F1); and an unprovable ownership row must be retained
  rather than guessed, which is why a runtime-scoped removal is deliberately less complete than a full one (F3).
