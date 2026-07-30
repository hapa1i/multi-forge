# `forge extension disable --runtime` -- remove one runtime's extension surfaces

**Lane**: `proposed/` -- not accepted. Two hard dependencies, in order:

1. [runtime_scoped_extension_modules](../runtime_scoped_extension_modules/card.md) -- D1 schema v3 must **ship**, not
   just be decided: this card selects tracked rows by runtime, and that attribution does not exist today (see
   Constraints).
2. [disable_scope_mismatch_orphan](../../doing/disable_scope_mismatch_orphan/card.md) -- ships **before** this card, so
   the refusal-preserves-tracking row in the state table below is inherited rather than invented here.

No decisions remain open; D-last and D-mismatch are closed below.

**Type**: ordinary card. See the sibling card's Type note for the drift argument.

**Origin**: user report, 2026-07-29. The reported ask was that `enable --runtime claude` should *remove* previously
managed Codex packages. That is declined in `enable` (see Rejected alternative) and reframed here: removal is real and
wanted, but it belongs on the verb that already owns removal.

**References**: `docs/design_appendix.md` sections C.4-C.6; `docs/developer/cli_style_guidelines.md` (destructive
verbs); `docs/developer/testing_guidelines.md` (integration triggers); `docs/board/impl_notes.md` ("Runtime skill
packages are compiled artifacts with separate ownership").

---

## Problem

After the sibling card, `--runtime` decides what an install *covers*, but there is no way to give a runtime back.
`forge extension disable` is all-or-nothing per scope (`--scope`, `--all`, `--yes` --
`src/forge/cli/extensions.py:1166-1180`), so a user who wants to stop managing Codex must disable the whole installation
and re-enable with `--runtime claude`. That round trip rewrites Claude hook bytes and, for the Codex half, discards a
trust enrollment the user must redo by hand.

The narrowing-preserves behavior in `enable` is deliberate and correct, but it leaves a real gap: preserved packages are
reported (`MANAGED_RUNTIME_PRESERVATION`, `src/forge/install/skill_planning.py:81-82`) yet unrefreshable and unremovable
short of a full disable.

## Goal

`forge extension disable --runtime <r>` removes exactly that runtime's managed surfaces from the selected scope,
preserves the other runtime's surfaces and all unrelated user content, and leaves a coherent installation row that a
later `forge extension sync` will not silently undo.

## Rejected alternative (recorded, not open)

Making `enable --runtime <r>` remove the omitted runtimes was rejected on three grounds:

- **Blast radius under the sibling card.** Once `--runtime` governs all modules, `enable --runtime codex` on a dual
  install would delete Claude hooks, commands, agents, status line, and permissions. A user refreshing Codex would lose
  their Claude setup from a verb named `enable`.
- **Axis consistency.** `--profile minimal` after a `standard` install does not remove agents or skills, and
  `--without commands` does not delete previously installed commands. A destructive runtime axis inside an otherwise
  additive verb trades one inconsistency for an unrecoverable one.
- **Failure model.** Enable writes files and commits tracking last, with rollback restoring what it created
  (`design_appendix.md` section C.4). Removal needs the settings unmerge path, Codex managed-block removal with backups,
  and the re-trust notice -- states `impl_notes.md` calls an "honest hooks-off recovery state", acceptable to reach from
  a command the user knew was destructive, not from an install.

If a declarative reconcile is wanted later, the shape is an explicit opt-in (`enable --runtime claude --prune`), not a
change to bare narrowing.

## Design

### Confirmation shape: inherit disable's, do not invent one

`disable` today renders a removal plan (files table, settings unmerge table, Codex block line) and then calls
`click.confirm("Proceed with disable?")`; `--yes` bypasses the prompt (`src/forge/cli/extensions.py:1275-1292`). That is
**prompt-then-apply**, and it is sanctioned: `cli_style_guidelines.md` mandates preview-only-by-default for `clean`
verbs specifically, while "a `delete` or `reset` verb may act after a prompt" provided the prompt and its `--yes` bypass
are explicit.

`--runtime` therefore **filters the existing plan tables and reuses the existing prompt**. It introduces no new
confirmation shape, which is what keeps `--runtime all` genuinely equivalent to today's `disable`.

### Removal set

Derived from the sibling card's ownership map intersected with what tracking claims is managed. For `--runtime claude`
that is the full Claude surface, not just skills:

| Runtime  | Surfaces removed                                                                                          |
| -------- | --------------------------------------------------------------------------------------------------------- |
| `codex`  | Codex skill packages; the Codex managed block (`codex_config_path` / `codex_commands`)                    |
| `claude` | Claude skill packages; command and agent files; `hooks`, `statusLine`, and `permissions` settings entries |
| `all`    | Everything -- equivalent to today's `disable` for that scope (see the equivalence scope below)            |

Nothing is removed that tracking does not claim. Untracked and unmanaged same-name packages are never adopted or
deleted; `forge clean` owns proven orphans.

### State transitions (normative)

| Situation                                            | Filesystem                          | Tracking                                                                                                                          | Exit                          |
| ---------------------------------------------------- | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| Success, runtime remains                             | selected runtime's surfaces removed | row retained; that runtime's file/settings/package/ownership rows dropped; `codex_config_path`/`codex_commands` cleared for codex | 0                             |
| Success, last managed runtime (D-last)               | as above                            | row **deleted** (equivalent to full `disable` for that scope)                                                                     | 0                             |
| Runtime not managed here                             | untouched                           | untouched                                                                                                                         | 0 with explicit no-op message |
| Preflight refusal (`invalid-target`, scope mismatch) | untouched                           | untouched                                                                                                                         | non-zero                      |
| Failure after partial removal                        | partially removed                   | committed to reflect **what was actually removed**; surviving rows stay coherent                                                  | non-zero, names the retry     |

The partial-failure row is the sharp case: tracking must not claim ownership of a file already deleted, nor drop
ownership of one still present. Commit ordering follows the existing non-transactional discipline (`cli_reference.md`,
Installation) -- but unlike `enable`, a partial removal cannot be rolled back by restoring created files, so the
reconciled row is the recovery surface and `forge extension status` must render it accurately.

### Plan granularity (D-all)

`--runtime` composes with `--all`; it is not rejected. Granularity is preserved **by mode**, matching the two render
paths that already exist:

| Mode         | Current render                                                                                                                            | With `--runtime`                             |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| Single scope | Profile/Mode header plus exact tables -- per-package RUNTIME/SKILL/TARGET, per-settings KEY, Codex block path (`extensions.py:1236-1284`) | Same tables, filtered to the runtime         |
| `--all`      | One per-scope summary table: SCOPE / PROJECT PATH / PROFILE / FILES / SKILL PACKAGES counts (`extensions.py:656-690`)                     | Same summary, counts filtered to the runtime |

`--all` dispatches to `_uninstall_all_installations` and returns before the single-scope render
(`extensions.py:1211-1213`), so these are already separate code paths. Removal proof stays path-exact where a human can
act on it, and stays a countable summary where a per-path list across every scope would be unreadable in one prompt.

### Sync must not resurrect what disable removed

`init_from_existing`/`plan_update` replay `_modules_override` from `modules_enabled` and derive runtimes from
`skill_packages` (`src/forge/install/installer.py:2347-2372, 2374-2388`). A partial disable that updates only the
filesystem, or only some tracking fields, is undone by the next `sync`. This is the card's sharpest correctness
requirement and the reason it cannot ship before the sibling card's schema.

### Other rules

- **Selection**: `--runtime claude|codex|all`, repeatable, matching `enable`'s spelling (`_SKILL_RUNTIME_IDS`,
  `src/forge/cli/extensions.py:78`). Composes with `--scope` and `--all`.
- **`profile` is historical provenance after a partial disable.** Module replay already comes from `modules_enabled`,
  not `profile`, so disable does **not** rewrite it. Status must label it as the installed profile, not the current
  surface set. Residual risk: `profile` still gates minimum-profile skill filtering (`qa` requires `full`), so a
  partially disabled row keeps its original gate.
- **Codex ceremony honesty**: removing the Codex managed block changes the config bytes, so a later re-enable requires
  the one-time interactive trust ceremony. Say so in the plan, before the prompt, and never claim trust was verified.
- **Removing one runtime's hooks must not re-render the other's command bytes** -- otherwise the surviving runtime is
  forced through a needless re-trust.
- **Preserved boundaries**: unrelated `config.toml` bytes survive and a whitespace-only remainder deletes the file
  (`design_appendix.md` section C.6); Claude settings use the existing smart unmerge that removes Forge additions and
  keeps user changes (`installer.py:2439-2456`).

### Decisions

| Id         | Decision                                                                                                                                                                                                                                   |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| D-last     | **Decided**: removing the last managed runtime deletes the row and is equivalent to full `disable` for that scope. A zero-runtime row has no meaning for status or sync. The prompt must state that this is a full uninstall of the scope. |
| D-preview  | Inherit disable's existing plan-then-prompt with `--yes`; introduce no new confirmation shape.                                                                                                                                             |
| D-profile  | Retain `profile` unchanged as provenance; it is not authoritative for module replay.                                                                                                                                                       |
| D-all      | **Decided**: `--runtime` **composes** with `--all` rather than being rejected. Granularity is preserved per mode -- exact paths for a single scope, filtered per-scope summaries for `--all` (see Plan granularity).                       |
| D-mismatch | **Decided**: split to [disable_scope_mismatch_orphan](../../doing/disable_scope_mismatch_orphan/card.md), which ships first. The defect is not runtime-specific, so its fix belongs to bare `disable` and this card inherits it.           |

## Constraints (verified against current code)

- **No deletion-grade attribution exists today.** `InstalledFile` carries
  `target_path, source_path, checksum, mode, installed_at`; `InstalledSettingsEntry` carries
  `key_path, value, merge_type, stable_id` (`src/forge/install/models.py:129-165`). Neither relates to a module or
  runtime. Only `skill_packages` groups by runtime. Selecting Claude command/agent/settings rows by runtime is therefore
  **impossible** until the sibling card's D1 lands. This is the hard dependency.
- `uninstall()` has no subset notion: it iterates `existing.files` wholesale, unmerges all settings entries, removes the
  Codex block, then deletes the tracking row (`installer.py:2389-2464`). Per-runtime removal is new machinery on the
  same boundary validation, not a parameter on the existing loop.
- **Scope mismatch currently warns and orphans.** `_remove_codex_registration` logs "tracked Codex config ... does not
  match the scope mapping ...; not modifying it" and **returns** (`installer.py:2466-2481`); `uninstall` then removes
  the tracking row unconditionally at `installer.py:2464`. So the managed block is left on disk with no tracking that
  owns it. `design_appendix.md` section C.6's "disable refuses a tracked path that no longer matches the scope mapping"
  describes refusing to *edit that file*, not refusing the operation. Any claim that this card "preserves existing
  refusal semantics" would be false. Preserving tracking on mismatch is a **new requirement**, owned by
  [disable_scope_mismatch_orphan](../../doing/disable_scope_mismatch_orphan/card.md) and inherited here once that ships.
- `disable --all --yes` attempts every tracked scope, aggregates failures, and exits non-zero if any remain
  (`design_appendix.md` section C.4). `--runtime` must compose without weakening that aggregate exit contract.
- `scripts/setup.sh --uninstall` deletes `$FORGE_HOME` only after a fully successful disable and preserves tracking on
  failure. A partial-by-design disable must not read as success to that caller.
- Disable refuses to traverse a package root or descendant replaced by a symlink (`invalid-target`, `design_appendix.md`
  section C.5). That refusal applies unchanged.
- Codex trust covers registered command bytes and config location, and `trusted_hash` is not computable by Forge
  (sections C.6, I.2). Re-trust cost is a fact to disclose, never a state to check.

## Open Questions

None promotion-blocking. Remaining detail is checklist-level: the exact wording of the D-last full-uninstall prompt, and
whether the `--all` per-scope summary gains a runtime column or a filtered caption.

## Risks

- **Silent resurrection via sync** if tracking is updated incompletely. Highest-severity failure mode, and the one most
  likely to pass a filesystem-only test.
- **Over-removal on a dual install** if the ownership map is consulted without intersecting against tracking.
- **Under-removal for `--runtime claude`** if the removal set is taken as "skills plus hooks", omitting commands,
  agents, status line, and permissions.
- **Unnecessary re-trust** if the surviving runtime's hook bytes are re-rendered.
- **Misreported success to `setup.sh --uninstall`** if a partial disable exits 0 in a way the caller reads as complete.

## Acceptance Criteria

- `disable --scope user --runtime codex` renders a plan containing exactly the Codex skill packages and the Codex
  managed block, including the re-trust notice, and applies only after the prompt or `--yes`.
- After applying, Codex packages and the managed block are gone; Claude commands, agents, hooks, status line,
  permissions, and skill packages are byte-unchanged, including the registered-command golden.
- `disable --scope user --runtime claude` removes **all five** Claude surfaces plus Claude skill packages, and leaves
  Codex skills and the Codex block byte-unchanged. Tested symmetrically with the Codex case -- not Codex-only.
- Unrelated `$CODEX_HOME/config.toml` content outside the Forge markers is preserved byte-for-byte; a config left with
  only whitespace is deleted.
- **Sync does not undo it**: `disable --runtime codex --yes` followed by `forge extension sync` leaves Codex absent,
  asserted on post-sync target paths, not tracking contents.
- **Every row of the state-transition table** is a test, including no-op, preflight refusal, last-runtime, and a fault
  injected mid-removal whose committed tracking matches what was actually removed.
- `forge extension status --json` after a partial disable reports the surviving runtime only, with a coherent row: no
  dangling ledger entries, no `skill_packages` row without files, `codex_config_path` cleared, `profile` retained and
  labeled as provenance.
- `--runtime all` matches today's `disable` for that scope on **successful-removal outcome** (filesystem end state,
  settings unmerge result, Codex block removal, tracking row deleted) and on **UI behavior** (plan tables, prompt
  wording, exit code), asserted against the existing disable tests as the no-regression golden. Equivalence explicitly
  **excludes** the tracking representation, which changes shape under the sibling card's schema v3, and excludes the
  partial-failure path, which has no pre-existing behavior to match.
- `disable --all --runtime codex --yes` aggregates failures across scopes and exits non-zero if any scope fails.
- Disabling a runtime the installation does not manage exits 0 with an explicit no-op message.
- `cli_reference.md` Installation table, `design_appendix.md` section C.4, `docs/end-user/hook.md`, and the changelog
  record the flag, the D-last behavior, and the re-trust consequence.

**Verification contract** (`testing_guidelines.md` names installer changes):
`tests/integration/docker/test_installer.py` plus a clean-wheel install exercising enable -> partial disable -> status
-> sync for each runtime, asserting non-resurrection. Unit tests cannot reach the wheel-install path.

## Closeout

(pending)
