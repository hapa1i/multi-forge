# `forge extension disable --runtime` -- remove one runtime's extension surfaces

**Lane**: `done/` -- completed on branch `feat/extension-disable-runtime`; execution record in
[checklist.md](checklist.md). Both hard dependencies have shipped:

1. [runtime_scoped_extension_modules](../../done/runtime_scoped_extension_modules/card.md) -- shipped D1 schema v3
   supplies the tagged per-row attribution this card needs for runtime-scoped selection (see Constraints).
2. [disable_scope_mismatch_orphan](../../done/disable_scope_mismatch_orphan/card.md) -- the shipped refusal behavior
   means the refusal-preserves-tracking row in the state table below is inherited rather than invented here.

No decisions or dependencies remain open. This card owns intent and state transitions; the checklist owns the firm
mechanism decisions and acceptance mapping.

**Type**: ordinary card. See the sibling card's Type note for the drift argument.

**Origin**: user report, 2026-07-29. The reported ask was that `enable --runtime claude` should *remove* previously
managed Codex packages. That is declined in `enable` (see Rejected alternative) and reframed here: removal is real and
wanted, but it belongs on the verb that already owns removal.

**References**: `docs/design_installation.md` sections C.3-C.6; `docs/developer/cli_style_guidelines.md` (destructive
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
  (`design_installation.md` section C.4). Removal needs the settings/ownership-sidecar path, Codex managed-block removal
  with boundary preservation, and the re-trust notice -- states `impl_notes.md` calls an "honest hooks-off recovery
  state", acceptable to reach from a command the user knew was destructive, not from an install.

If a declarative reconcile is wanted later, the shape is an explicit opt-in (`enable --runtime claude --prune`), not a
change to bare narrowing.

## Design

### Confirmation shape: inherit disable's, do not invent one

`disable` today renders a removal plan (files table, settings unmerge table, Codex block line) and then calls
`click.confirm("Proceed with disable?")`; `--yes` bypasses the prompt (`src/forge/cli/extensions.py:1275-1292`). That is
**prompt-then-apply**, and it is sanctioned: `cli_style_guidelines.md` mandates preview-only-by-default for `clean`
verbs specifically, while "a `delete` or `reset` verb may act after a prompt" provided the prompt and its `--yes` bypass
are explicit.

`--runtime` therefore **filters the existing plan tables and reuses the existing confirmation flow**. Last-runtime and
batch wording must describe the actual full/partial disposition, but there is no new confirmation shape. For a
single-scope `--runtime all`, the existing prompt remains the equivalence golden.

### Removal set

Derived from the sibling card's ownership map intersected with what tracking claims is managed. For `--runtime claude`
that is the full Claude surface, not just skills:

| Runtime  | Surfaces removed                                                                                          |
| -------- | --------------------------------------------------------------------------------------------------------- |
| `codex`  | Codex skill packages; the Codex managed block (`codex_config_path` / `codex_commands`)                    |
| `claude` | Claude skill packages; command and agent files; `hooks`, `statusLine`, and `permissions` settings entries |
| `all`    | Everything -- same managed-surface end state as today's `disable` for that scope (see equivalence below)  |

Nothing is removed that tracking does not claim. Untracked and unmanaged same-name packages are never adopted or
deleted; `forge clean` owns proven orphans.

### State transitions (normative)

| Situation                                                          | Filesystem                          | Tracking                                                                                                                          | Exit                                       |
| ------------------------------------------------------------------ | ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Success, runtime remains                                           | selected runtime's surfaces removed | row retained; that runtime's file/settings/package/ownership rows dropped; `codex_config_path`/`codex_commands` cleared for codex | 0                                          |
| Success, last managed runtime (D-last)                             | as above                            | row **deleted** (same managed-surface end state as full `disable` for that scope)                                                 | 0                                          |
| Runtime not managed here                                           | untouched                           | untouched                                                                                                                         | 0 with explicit no-op message              |
| Preflight refusal (`invalid-target`, scope mismatch, unsafe block) | untouched                           | untouched                                                                                                                         | non-zero                                   |
| Mutation failure; reconciliation succeeds                          | partially removed                   | committed to reflect **what was actually removed**; surviving rows stay coherent                                                  | non-zero, names the retry                  |
| Reconciliation write itself fails                                  | partially removed                   | atomic pre-removal row remains and may over-claim removed surfaces                                                                | non-zero, names tracking path and recovery |

The mutation-failure row is the sharp case: when tracking remains writable, it must not claim ownership of a file
already deleted or drop ownership of one still present. The irreducible exception is failure of the reconciliation write
itself: atomicity preserves the old row, but cannot make the new row land. That safe over-claim is recoverable after
repairing the tracking path; the command must not pretend reconciliation succeeded. The checklist defines the
settings-sidecar rollback needed to keep that retry safe.

### Plan granularity (D-all)

`--runtime` composes with `--all`; it is not rejected. Granularity is preserved **by mode**, matching the two render
paths that already exist:

| Mode         | Current render                                                                                                                            | With `--runtime`                                                                                                           |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Single scope | Profile/Mode header plus exact tables -- per-package RUNTIME/SKILL/TARGET, per-settings KEY, Codex block path (`extensions.py:1236-1284`) | Same tables, filtered to the runtime                                                                                       |
| `--all`      | One per-scope summary table: SCOPE / PROJECT PATH / PROFILE / FILES / SKILL PACKAGES counts (`extensions.py:656-690`)                     | Actual-removal counts plus DISPOSITION (`no-op` / `partial` / `full`); scoped notes disclose retained unattributed residue |

`--all` dispatches to `_uninstall_all_installations` and returns before the single-scope render
(`extensions.py:1211-1213`), so these are already separate code paths. Removal proof stays path-exact where a human can
act on it, and stays a countable summary where a per-path list across every scope would be unreadable in one prompt.

### Sync must not resurrect what disable removed

`init_from_existing`/`plan_update` derive both `_modules_override` and managed runtimes from `module_owners`
(`src/forge/install/installer.py:2342-2375`). A partial disable that updates only the filesystem, or removes rows while
leaving the selected runtime's owner pairs, is undone by the next `sync`. This is the card's sharpest correctness
requirement and the reason the shipped sibling schema remains load-bearing.

### Other rules

- **Selection**: `--runtime claude|codex|all`, repeatable, matching `enable`'s spelling (`_SKILL_RUNTIME_IDS`,
  `src/forge/cli/extensions.py:78`). Composes with `--scope` and `--all`.
- **`profile` is historical provenance after a partial disable.** Module replay already comes from `module_owners`, not
  `profile`, so disable does **not** rewrite it. Status must label it as the installed profile, not the current surface
  set. Residual risk: `profile` still gates minimum-profile skill filtering (`qa` requires `full`), so a partially
  disabled row keeps its original gate.
- **Codex ceremony honesty**: removing the Codex managed block changes the config bytes, so a later re-enable requires
  the one-time interactive trust ceremony. Say so in the plan, before the prompt, and never claim trust was verified.
- **Removing one runtime's hooks must not re-render the other's command bytes** -- otherwise the surviving runtime is
  forced through a needless re-trust.
- **Preserved boundaries**: unrelated `config.toml` bytes survive and a whitespace-only remainder deletes the file
  (`design_installation.md` section C.6); Claude settings use the existing smart unmerge that removes Forge additions
  and keeps user changes (`installer.py:2439-2456`).

### Decisions

| Id         | Decision                                                                                                                                                                                                                                                                                                                                                            |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D-last     | **Decided**: removing the last managed runtime deletes the row and matches full `disable` on managed-surface outcome and UI. Runtime-spelled safety differs for failures and for legacy/no-sidecar user edits, as defined by the checklist. A zero-runtime row has no meaning for status or sync. The prompt must state that this is a full uninstall of the scope. |
| D-preview  | Inherit disable's existing plan-then-prompt with `--yes`; introduce no new confirmation shape.                                                                                                                                                                                                                                                                      |
| D-profile  | Retain `profile` unchanged as provenance; it is not authoritative for module replay.                                                                                                                                                                                                                                                                                |
| D-all      | **Decided**: `--runtime` **composes** with `--all` rather than being rejected. Granularity is preserved per mode -- exact paths for a single scope, filtered counts plus a per-scope disposition for `--all` (see Plan granularity).                                                                                                                                |
| D-mismatch | **Decided**: split to [disable_scope_mismatch_orphan](../../done/disable_scope_mismatch_orphan/card.md), which ships first. The defect is not runtime-specific, so its fix belongs to bare `disable` and this card inherits it.                                                                                                                                     |

## Constraints

Written against pre-dependency code. Line references and the two **RESOLVED** entries below were re-verified against
`main` at `4b9ad0ad`; see [checklist.md](checklist.md) "Planning findings" for the current anchor table.

- **RESOLVED (was the hard dependency): deletion-grade attribution now exists.** This card originally recorded that
  `InstalledFile` and `InstalledSettingsEntry` carried no module or runtime relation, making runtime-scoped selection of
  Claude command/agent/settings rows impossible. Schema v3 shipped with
  [runtime_scoped_extension_modules](../../done/runtime_scoped_extension_modules/card.md): both rows now carry a tagged
  `attribution` (`models.py:158`, `:181`). The dependency is satisfied; the selection mechanism is
  `ownership.attribution_pair`.
- `uninstall()` has no subset notion: it iterates `existing.files` wholesale, removes all tracked settings state,
  removes the Codex block, then deletes the tracking row (`installer.py:2389-2464`). Per-runtime removal is new
  machinery on the same boundary validation, not a parameter on the existing loop.
- **RESOLVED: scope mismatch refuses the operation and preserves tracking.** This card originally recorded that
  `_remove_codex_registration` warned and returned while `uninstall` removed the tracking row anyway, orphaning the
  managed block. That defect shipped fixed as
  [disable_scope_mismatch_orphan](../../done/disable_scope_mismatch_orphan/card.md):
  `Installer.validate_codex_config_scope` raises `CodexConfigScopeMismatchError` before any removal work. This card
  inherits the refusal rather than inventing it. The checklist scopes the preflight to removals that actually touch the
  Codex config (D-preflight-scoped).
- `disable --all --yes` attempts every tracked scope, aggregates failures, and exits non-zero if any remain
  (`design_installation.md` section C.4). `--runtime` must compose without weakening that aggregate exit contract.
- `scripts/setup.sh --uninstall` deletes `$FORGE_HOME` only after a fully successful disable and preserves tracking on
  failure. It passes no runtime filter, so it remains on the complete-removal path.
- Disable refuses to traverse a package root or descendant replaced by a symlink (`invalid-target`, section C.5 of the
  former consolidated design appendix). That refusal applies unchanged.
- Codex trust covers registered command bytes and config location, and `trusted_hash` is not computable by Forge
  (sections C.6, I.2). Re-trust cost is a fact to disclose, never a state to check.

## Open Questions

None. The checklist fixes the D-last wording contract and the `--all` disposition shape.

## Risks

- **Silent resurrection via sync** if tracking is updated incompletely. Highest-severity failure mode, and the one most
  likely to pass a filesystem-only test.
- **Over-removal on a dual install** if the ownership map is consulted without intersecting against tracking.
- **Under-removal for `--runtime claude`** if the removal set is taken as "skills plus hooks", omitting commands,
  agents, status line, and permissions.
- **Unnecessary re-trust** if the surviving runtime's hook bytes are re-rendered.
- **Stale settings ownership** if a partial unmerge does not update `.forge-added`, or if a failed settings/sidecar
  transition under-claims entries that remain on disk.
- **Misreported batch success** if runtime-filtered `--all` claims installations were removed when some rows only lost
  one runtime or were no-ops. Bare `setup.sh --uninstall` remains an unfiltered complete removal.

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
- **Every row of the state-transition table** is a test, including no-op, preflight refusal, last-runtime, a mutation
  fault whose committed tracking matches what was actually removed, and a reconciliation-write failure that leaves the
  atomic pre-removal row with honest recovery output.
- `forge extension status --json` after a partial disable reports the surviving runtime only, with a coherent row: no
  dangling ledger entries, no `skill_packages` row without files, `codex_config_path` cleared, `profile` retained and
  labeled as provenance.
- On a current sidecar-backed v3 install, `--runtime all` matches today's `disable` for that scope on successful-removal
  outcome (filesystem end state, settings unmerge result, Codex block removal, tracking row deleted) and UI behavior
  (plan tables, prompt wording, exit code). Equivalence excludes the tracking representation, partial-failure behavior,
  and legacy/no-sidecar settings fallback: the runtime-spelled path must preserve a user-modified scalar/env value
  rather than reproduce bare disable's blind `unmerge`.
- `disable --all --runtime codex --yes` shows each scope's `no-op` / `partial` / `full` disposition, reports completion
  in terms of the selected runtime rather than claiming every installation was removed, aggregates failures across
  scopes, discloses retained unattributed residue per scope, and exits non-zero if any scope fails.
- Disabling a runtime the installation does not manage exits 0 with an explicit no-op message.
- A missing Codex managed block clears stale ownership; partial/duplicate markers and a leaf symlink refuse before
  mutation; a balanced block is removed while outside-marker manual commands remain user-owned and warning-only.
- `cli_reference.md` Installation table, `design_installation.md` sections C.3-C.6, `docs/end-user/hook.md`,
  `docs/end-user/skills.md`, and the changelog record the flag, the D-last behavior, and the re-trust consequence.

**Verification contract** (`testing_guidelines.md` names installer changes):
`tests/integration/docker/test_installer.py` plus a clean-wheel install exercising enable -> partial disable -> status
-> sync for each runtime, asserting non-resurrection. Unit tests cannot reach the wheel-install path.

## Closeout

Shipped on 2026-07-31. Runtime-scoped disable now removes the selected runtime's attributed surfaces, preserves the
other runtime byte-for-byte, and updates tracking so sync cannot resurrect removed ownership. The clean-wheel lifecycle
covers both removal directions through status and sync; failure-path tests cover preflight refusal, partial
reconciliation, settings/sidecar rollback, unsafe Codex config targets, and tracking-write failure.
