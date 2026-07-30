# Runtime-scoped extension modules -- `--runtime` governs every runtime-owned surface

**Lane**: `done/` -- completed on branch `feat/runtime-scoped-extension-modules`; execution record in
[checklist.md](checklist.md). D1 (durable ownership schema) shipped as decided, and the scope-mismatch orphan shipped
separately as [disable_scope_mismatch_orphan](../../done/disable_scope_mismatch_orphan/card.md).

**Type**: ordinary card, not an epic. The board's epic criterion is shared-contract **drift**
([board_contract.md](../../../developer/board_contract.md) "Epics"), not member count. Drift is prevented structurally
here: this card is the sole writer of the ownership schema and lands it whole, and
[extension_disable_runtime](../../doing/extension_disable_runtime/card.md) is a pure reader that cannot start until the
schema ships. There is one contract, one writer, and a strict ordering -- no coordinator needed. Promote a coordinator
if the schema has to land in slices consumed before completion.

**Origin**: user report, 2026-07-29. Codex support is less mature than Claude Code support, so a user must be able to
keep their Codex installation untouched. Today `forge extension enable --scope user --runtime claude` still registers
Forge's Codex hook block in `$CODEX_HOME/config.toml`, because `--runtime` filters only the SKILLS module.

**References**: `docs/design.md` section 5.1; `docs/design_appendix.md` sections C.1-C.6; `docs/cli_reference.md`
(Installation); `docs/developer/coding_standards.md` section 5 (durable state, clean breaks); `docs/board/impl_notes.md`
("Runtime skill packages are compiled artifacts with separate ownership", "Hook runtime ownership and recovery follow
the execution environment").

---

## Problem

`--runtime claude|codex|all` reads as a runtime selector but is implemented as a SKILLS-module filter. Three
consequences:

- **The pristine-Codex case is inexpressible in the flag that names it.** `--runtime claude` still writes the
  `codex-hooks` managed block at user scope. Keeping Codex untouched requires knowing to add `--without codex-hooks`.
- **The Codex-only case needs four flags.** The installer hard-codes the recovery string
  `--profile minimal --with skills --without commands --runtime codex` (`src/forge/cli/extensions.py:152-160`) as a tip
  when Claude Code is absent. A four-flag incantation shipped inside an error message is evidence the axis is wrong.
- **Every doc that mentions the flag has to disclaim it.** `cli_reference.md`, `design.md`, `design_appendix.md`,
  `end-user/skills.md`, `end-user/manual_testing.md`, and `AGENTS.md` all carry a variant of "selects only outputs of
  the SKILLS module". A selector whose name needs correcting wherever it appears is mis-scoped, not under-documented.

`codex-hooks` exists as a separate module only because the runtime axis cannot reach modules. It and `hooks` are already
the same shape: both are `SETTINGS_ONLY_MODULES` (`src/forge/install/models.py:117-123`) and both are omitted at
project/local scope by the same branch (`_scope_omitted_modules`, `src/forge/install/installer.py:199-202`). They are
one module wearing two names, and six user-facing recovery commands have to spell both (see Impact inventory).

## Goal

Make `--runtime` select **every** extension surface owned by that runtime, and derive the effective module set from
profile, scope, explicit module flags, and runtime instead of filtering one module. `--runtime claude` must be unable to
touch `$CODEX_HOME`; `--runtime codex` must be sufficient on its own to mean "Codex only".

Non-goal: changing what any module installs, changing scope semantics, or making narrowing destructive. Removal stays
with `disable` -- see [extension_disable_runtime](../../doing/extension_disable_runtime/card.md).

## Design

### Per-module runtime ownership

| Module        | Owners                 | Change                                    |
| ------------- | ---------------------- | ----------------------------------------- |
| `commands`    | `claude_code`          | ownership declared                        |
| `agents`      | `claude_code`          | ownership declared                        |
| `hooks`       | `claude_code`, `codex` | **absorbs `codex-hooks`**                 |
| `status-line` | `claude_code`          | ownership declared                        |
| `permissions` | `claude_code`          | ownership declared                        |
| `skills`      | `claude_code`, `codex` | ownership declared (behavior unchanged)   |
| `codex-hooks` | --                     | **deleted**; clean break, no hidden alias |

`permissions` is confirmed Claude-owned by source: the built-in preset installs `Write`/`Edit` "required by the memory
writer's `claude -p` subprocess" (`src/forge/install/preset.py:9`).

### Selection rule (explicit provenance included)

Runtime filtering composes **after** the existing module resolution rather than replacing it. Current resolution is
profile, plus `--with`, minus `--without`, then module dependencies, then scope omission
(`src/forge/install/installer.py:836`, `_apply_scope_module_policy`). Runtime becomes a final filter that distinguishes
requested-explicitly from requested-by-profile:

```text
requested       = (profile_modules + with_modules) - without_modules
resolved        = apply_dependencies(requested)
scoped          = resolved - scope_omitted_modules(scope)
effective       = { m in scoped : owners(m) intersects selected_runtimes }
dropped         = scoped - effective
```

- A module in `dropped` that came from the **profile** is a `SKIP` with a reported reason.
- A module in `dropped` that was named in `--with` is a `CONFLICT`. This is what makes `--runtime codex --with commands`
  fail rather than silently do nothing.
- **An explicit runtime selection resolving to an empty `effective` set is a `CONFLICT`**, not a silent no-op. This is
  the `--profile minimal --runtime codex` case (`minimal` is `{commands}`, which is Claude-owned).

Module outcomes carry their own action and reason. Wrong-owner and empty-effective-set outcomes set
`InstallPlan.has_conflicts` directly, which is the execution gate; a module-level non-forceable reason set controls the
recovery tip but is not itself enforcement. `--force` must not adopt these conflicts.

### Behavior matrix (normative)

Auto-detected scope prefers **local** over user inside a git repo (`src/forge/cli/extensions.py:885-907`), so a bare
`enable` in a checkout is a project-family install where hooks are omitted. Every row below is an acceptance target.

| Command                                                  | Effective surfaces                                         | Outcome                          |
| -------------------------------------------------------- | ---------------------------------------------------------- | -------------------------------- |
| `enable --scope user --runtime claude`                   | commands, agents, claude skills, claude hooks, permissions | Codex untouched                  |
| `enable --scope user --runtime codex`                    | codex skills, codex hooks                                  | no Claude surface, no gate       |
| `enable --scope user --runtime all`                      | today's standard-profile user install                      | no-regression golden             |
| `enable --scope project --runtime codex`                 | codex skills only                                          | hooks scope-omitted              |
| `enable --scope project --runtime claude`                | commands, agents, claude skills, status-line, permissions  | hooks scope-omitted              |
| `enable --scope local --runtime codex`                   | --                                                         | CONFLICT (no codex local)        |
| `enable --runtime codex` (auto-detect in repo -> local)  | --                                                         | CONFLICT, names `--scope user`   |
| `enable --profile minimal --runtime codex`               | --                                                         | CONFLICT (empty set)             |
| `enable --runtime codex --with commands`                 | --                                                         | CONFLICT (explicit, wrong owner) |
| `enable --profile minimal --with skills --runtime codex` | codex skills                                               | allowed                          |

**Automatic selection is unchanged**: no flag resolves to Claude plus already-managed runtimes plus detected Codex
(`src/forge/install/skill_planning.py:237-239`).

**Narrowing still preserves.** An explicit selection continues to set `preserved_runtime_ids` and emit
`MANAGED_RUNTIME_PRESERVATION` rows (`skill_planning.py:81-82, 234`; `installer.py:1304`). This card widens what
`--runtime` governs, which widens what a destructive narrowing *would* delete -- so the two must not land together.

### Durable ownership schema (D1 -- decided)

**This is the card's core deliverable and its P0.** Two independent gaps make the current schema insufficient:

1. **No unknown-value guard.** `init_from_existing` and `plan_update` build
   `{InstallModule(m) for m in existing.modules_enabled}` unguarded (`src/forge/install/installer.py:2347, 2364`), so
   deleting the `codex-hooks` enum member makes `forge extension sync` raise `ValueError` on every install that tracked
   it.
2. **No deletion-grade attribution.** `InstalledFile` carries `target_path, source_path, checksum, mode, installed_at`
   and `InstalledSettingsEntry` carries `key_path, value, merge_type, stable_id`
   (`src/forge/install/models.py:129-165`). **Neither has a module or runtime relation.** Only `skill_packages` groups
   by runtime. So "which tracked rows belong to Codex" is currently underivable for every non-skill surface -- which is
   precisely what the sibling card needs.

**Schema v3.** `Installation.module_owners` is a unique list of `{module, runtime}` objects sorted by that pair; it
replaces live-v3 `modules_enabled`. Every `InstalledFile` and `InstalledSettingsEntry` carries a required tagged
`attribution`, exactly one of:

```text
{"module": "hooks", "runtime": "claude_code"}
{"unattributed_reason": "legacy_key_unmapped"}
```

Nullable module/runtime fields are not valid attribution. The exact wire and status shapes, row identities, legacy
mapping, and ordering are frozen in [checklist.md](checklist.md) before implementation starts.

**Ownership records applied state, not requested state.** A blocking module/runtime apply path that completes without
conflict or failure records its pair even if the current package emits no rows. This is applied management intent, not
mere resolution: it preserves sync coverage for today's intentionally empty `commands` and `agents` sources, while a
failed or skipped path records no new pair.

The Codex half of `hooks` is best-effort (`design_appendix.md` section C.6): a missing `codex` binary or config conflict
degrades to a visible skip and does not set `InstallPlan.has_conflicts`. On a first install it writes no
`(hooks, codex)` pair. On re-enable, an inconclusive or omitted Codex outcome preserves a prior pair when
`codex_config_path` still witnesses an on-disk managed block; otherwise disable would lose the only cleanup ownership
record. The Claude half stays blocking.

**Flat `codex-hooks` alone never proves applied ownership.** `modules_enabled` is written from the *resolved* module set
unconditionally (`installer.py:2031`), while `codex_path` is `None` on the skip branch (`installer.py:2003-2012`). A
best-effort skip therefore leaves `codex-hooks` in `modules_enabled` with no block on disk. The applied-state witness is
`codex_config_path` being set -- migration must key on that, never on the module value.

**Derived migration for all recoverable v1/v2 state.** Normalize in memory on read, persist v3 on the next successful
mutation, per the shipped v1 precedent (`design_appendix.md` section C.4). Both historical schemas use complete frozen
DTO graphs, including file and settings rows; they never deserialize through live v3 nested types. No reset is required,
so the schema change is not itself a user-visible break -- unlike the `codex-hooks` module value, which is. That
released value is the only deleted module name normalized; any other unknown module remains corrupted durable state.

| Prior state               | Skills attribution                                                                    | `(hooks, codex)`               | Everything else        |
| ------------------------- | ------------------------------------------------------------------------------------- | ------------------------------ | ---------------------- |
| v2 (`skill_packages` set) | `skill_packages[].runtime`                                                            | iff `codex_config_path` is set | Claude by construction |
| v1 (no `skill_packages`)  | `_legacy_claude_skill_packages` -- path-provable Claude-only (`installer.py:315-334`) | iff `codex_config_path` is set | Claude by construction |

"Claude by construction" determines only the runtime. Legacy module identity is derived from reviewed target roots and
settings keys: command/agent roots, exact v2 skill-package file claims, path-provable v1 Claude skills, `hooks.*`,
`statusLine`, `permissions.allow|deny`, and `env.*`. Anything else is explicitly unattributed. The Claude premise is
sound only because no module other than `skills` and `hooks` has a Codex target today; adding a third Codex-owned module
later requires its own migration step.

**Unrecoverable state is reported, never claimed.** `_legacy_claude_skill_packages` returns only ownership it can prove
from tracked paths under the Claude skills root, and returns nothing when the row has no matching files. A surface whose
ownership cannot be derived receives an explicit `unattributed_reason` tag and is surfaced by `forge extension status`,
rather than defaulted to Claude. Silent attribution is what would let a later `disable --runtime claude` delete a Codex
file.

**v3 invariants** (extending the v2 list in `design_appendix.md` section C.4, all enforced before mutation):

1. Every `(module, runtime)` pair names a module that exists and a runtime that declares that module as an owner.
2. Every `InstalledFile` and `InstalledSettingsEntry` carries exactly one valid attribution form. An attributed pair is
   present in `module_owners`; an unattributed reason is accepted only from a version-specific legacy migration.
3. No file or settings row is claimed by two pairs.
4. Every `skill_packages` row's `(runtime, skill)` has a matching `(skills, runtime)` pair, and the v2 package
   invariants continue to hold unchanged.
5. `(hooks, codex)` exists if and only if `codex_config_path` is set.
6. An unattributed row is readable and reportable but cannot be constructed as a runtime-scoped removal target.

**Status JSON v3.** `managed_runtimes` is the single sorted runtime summary derived from `module_owners`;
`module_owners` exposes the durable relation; `modules` remains a sorted unique compatibility summary; and
`unattributed_surfaces` reports only row identity plus reason, never settings values. The checklist freezes the element
shapes and ordering.

### Decisions (all closed, rationale recorded)

| Id  | Decision                                                                                                                                                                              |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Schema v3: applied `module_owners`, tagged per-row attribution, and derived no-reset migration through complete frozen v1/v2 DTO graphs.                                              |
| D2  | Explicit selection yielding an empty effective module set is a CONFLICT, never a silent no-op.                                                                                        |
| D3  | `permissions` is Claude-owned (`preset.py:9`).                                                                                                                                        |
| D4  | `--runtime` is **not** added to `sync`; its persisted `MANAGED` runtime set stays authoritative (`skill_planning.py:206-212`).                                                        |
| D5  | `--with codex-hooks` fails with Click's native unknown-value error; no tombstone module value.                                                                                        |
| D6  | Resolved elsewhere: the scope-mismatch orphan is a standalone defect, carded as [disable_scope_mismatch_orphan](../../done/disable_scope_mismatch_orphan/card.md). Out of scope here. |

## Constraints (verified against current code)

- `--runtime` is `click.Choice(["claude", "codex", "all"])`, `multiple=True`, and flows only into `skill_runtimes=`
  (`src/forge/cli/extensions.py:78, 127-138, 828-834, 923-932`). Module resolution never sees it.
- `PROFILE_MODULES[STANDARD]` includes `CODEX_HOOKS` (`src/forge/install/models.py:65-77`).
- `_scope_omitted_modules` omits `HOOKS` **and** `CODEX_HOOKS` together at project/local scope (`installer.py:199-202`).
  The merged module inherits this unchanged; Codex hook registration stays user-scope-only.
- Registered hook rows are a byte contract, keyed on `(event, matcher, command, timeout)`
  (`tests/src/install/test_registered_commands_contract.py`). Codex trust hashes the registered command bytes and config
  location (`design_appendix.md` section C.6), and `trusted_hash` is not computable by Forge. The module rename must not
  change rendered bytes, or every existing Codex install is forced through the ceremony for nothing.

**Must not break.** The module *value* `codex-hooks` dies. These are unrelated and must not be renamed: the hook handler
names `codex-session-start` / `codex-policy-check`, and the probe directory `scripts/experiments/codex-hooks/` cited as
evidence by `design_appendix.md` section I.2.

## Impact inventory (verified by grep, 2026-07-29)

**Six user-facing recovery commands spell both modules** and collapse to `--with hooks`: `README.md:127`,
`CONTRIBUTING.md:22`, `docs/end-user/hook.md:97`, `docs/end-user/skills.md:403`, `docs/end-user/README.md:59`,
`src/skills/qa/resources/checklist/6-hook.md:29`.

| Surface                   | Files                                                                                                              |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Normative design          | `design.md:1365,1384`; `design_appendix.md:1028,1033,1225`; `design_workflows.md:355`; `cli_reference.md:116`      |
| End-user                  | `end-user/hook.md:97,114,297,317`; `end-user/skills.md:403`; `end-user/README.md:59`; `end-user/manual_testing.md` |
| Contributor/agent context | `README.md:127`; `CONTRIBUTING.md:22`; `AGENTS.md`                                                                 |
| QA checklists             | `qa/resources/checklist.md:32`; `checklist/2-extension.md:190`; `checklist/6-hook.md:29-30`                        |
| Installer/runtime code    | `install/{models,installer,hook_dispatcher,hook_migration}.py`; `cli/{extensions,runtime}.py`                      |

`checklist/6-hook.md:30` hard-asserts `jq -e '.installations.user.modules_enabled == ["codex-hooks", "hooks"]'` -- a
tracking-shape assertion the migration necessarily changes. Update it with the schema, not afterwards.

## Open Questions

None. The checklist closes the v3 wire shape, status fields, ordering, unattributed representation, row identities,
legacy derivation, and successful zero-output ownership semantics.

## Risks

- **Widened blast radius for any future destructive narrowing.** Once `--runtime` governs all modules, a narrowing that
  removed would delete Claude hooks, commands, agents, status line, and permissions from one flag. This card ships
  additive-only; removal is the sibling card's, with its own confirmation. Do not combine the behaviors in one release.
- **Sync breakage on upgrade** if D1 is not landed whole. Symptom is a `ValueError`, not a clean error.
- **Unnecessary Codex re-trust** if the merge changes rendered command bytes.
- **Silent Codex de-registration** if the best-effort half is planned but not applied and the skip is not visible.

## Acceptance Criteria

- `enable --scope user --runtime claude` writes no `$CODEX_HOME` path and no Codex skill package, asserted by
  target-path inspection.
- `enable --scope user --runtime codex` installs Codex skills plus the Codex hook block and touches no Claude surface --
  no `.claude/`, no `~/.claude/settings.json` write, no Claude version gate. The four-flag tip in
  `extensions.py:152-160` is deleted and its test asserts the one-flag form.
- **Every row of the behavior matrix** is a test, including all four CONFLICT rows and the auto-detect-to-local case.
- `enable --scope user --runtime all` produces **rendered extension targets and a registered-command golden identical to
  today**. This criterion explicitly excludes `installed.json`, which changes shape under D1.
- The `codex-hooks` module value is gone from `InstallModule`; `forge extension sync` succeeds against a pre-migration
  `installed.json` fixture containing `"codex-hooks"` in `modules_enabled`, and the v2 -> v3 derivation is asserted
  field-by-field with no user action. V1 and v2 fixtures parse through complete frozen DTOs, never live v3 row classes.
- A first-install best-effort Codex hook skip writes no `(hooks, codex)` ownership pair and is visibly reported; a
  re-enable with a witnessed prior block preserves its pair and cleanup path.
- Every tracked file and settings row carries exactly one valid tagged attribution sufficient for the sibling card to
  select by runtime without matching unattributed rows.
- A successfully applied zero-output module retains its ownership pair so sync can discover outputs added by a future
  package.
- `forge extension status --json` reports managed runtimes from `managed_runtimes`, exposes `module_owners`, and renders
  unattributed row identities without settings values.
- Rendered hook command bytes are unchanged; no existing Codex install is forced through the trust ceremony.
- Every file in the Impact inventory is updated in the same change, including the six recovery commands and the QA `jq`
  assertion. The changelog records the `codex-hooks` clean break.

**Verification contract** (per `testing_guidelines.md` "When to Run Integration Tests" -- installer changes are named
there): `tests/integration/docker/test_installer.py`, plus a clean-wheel install exercising enable/sync/status/disable
for `--runtime claude`, `codex`, and `all`, plus Codex-hook preservation across a `--runtime claude` re-enable. Unit
tests cannot reach the wheel-install path this card changes.

## Closeout

Shipped on 2026-07-30. `--runtime` now filters all runtime-owned modules, tracking and status use schema v3, and v1/v2
installations migrate without a reset. The clean-wheel lifecycle covers Claude, Codex, and combined selection, including
preservation of Codex ownership and files across a Claude-only re-enable. The tagged attribution contract unblocks
[extension_disable_runtime](../../doing/extension_disable_runtime/card.md).
