# Checklist: forge_hook_legacy_writer

**Card**: [card.md](card.md) · **Branch**: `refactor/hook-legacy-writer`

**Status**: **reviewed; D1 ratified as DELETE, gated by Phase 0.** Nothing implemented yet; all boxes below are
unchecked by design. If Phase 0 cannot produce a tested public hooks-only replacement at acceptable blast radius, the D1
escape valve reopens.

**Current focus**: Reconcile the parallel `forge hook enable` / `forge hook disable` writer (`cli/hooks/install.py`) now
that the shared matcher already shipped. Pre-epic prep for
[`epic_global_forge_runtime`](../../proposed/epic_global_forge_runtime/card.md) Seam 1: end with **one** hook mutation
path so the epic's later byte change (T2/T5) lands in one place.

---

## Context: what the merged matcher card already did (do NOT re-do)

`forge_hook_matcher_consolidation` (merged, `#87`) already made `cli/hooks/install.py::_is_forge_hook_entry` delegate to
the shared `entry_is_forge_hook(entry, require_command_type=True)`. **The matcher is already unified** — this card does
**not** touch matcher logic.

Remaining second-writer drift, verified on `main` (`cli/hooks/install.py`):

- **Bare command bytes.** `enable` writes `FORGE_HOOK_CONFIG["hooks"]` = `get_builtin_preset()["hooks"]` verbatim — bare
  `forge hook <name>` (`:131-132`). PATH-dependent; the exact exit-127 form the epic (T2) fixes.
- **Untracked.** Writes `settings.local.json` directly (`:135`), no `installed.json` / `TrackingStore`. The tracked
  `unmerge` (`settings_merge.py:731`, by `stable_id`) can't remove these entries.
- **Wholesale key-overwrite (latent data-loss bug).** `settings["hooks"][key] = value` (`:131-132`) replaces the entire
  event-key array, so running `forge hook enable` over a settings file that already has a **user's own** `PreToolUse`
  entry destroys it. The tracked `merge_hooks` appends + dedupes instead.
- **Duplicate scope walk.** `_find_hooks_target` (`:23-64`) reimplements scope detection separate from the installer.
- **Duplicate registry.** `FORGE_HOOK_CONFIG` (`:20`) is a second copy of the hook set, kept in sync with the preset
  only by a regression test (`tests/regression/test_bug_hook_registry_drift.py`). Consumers are **tests only**
  (`test_read_hygiene.py:174`, `test_handlers.py:495,502`); no production code outside `install.py` reads it.

---

## Decision ratified (reviewer)

- [x] **D1 — DELETE, ratified 2026-07-06, conditional on a hardened Phase 0.** Reviewer agrees delete is the right
  direction **only after the tracked hooks-only replacement is made real and tested** — Phase 0 is now a hard gate, not
  a docs-wording choice. Rationale, grounded on `main`:
  - **The one merge reason evaporated.** "Update to adopt the shared matcher" is already done (context above). What's
    left is a bare-form, untracked, sibling-clobbering, duplicate-registry writer.
  - **Delete removes the most drift in one stroke** and carries the least code forward: the second mutation path, the
    untracked-ness, the bare form, the overwrite-clobber bug, the duplicate `FORGE_HOOK_CONFIG` registry, **and** the
    reason `test_bug_hook_registry_drift.py` exists (two registries can't drift if there's one). Aligns with the epic
    end-state — under user-scope-only hooks (T5), a per-project `forge hook enable --local` is the anti-pattern the epic
    removes, so update-by-delegation would preserve a soon-obsolete affordance.
  - **Correction (reviewer Medium-1, verified):** the earlier premise that "hooks-only is already reproducible via the
    tracked path" was **wrong**. The settings merge is **not** module-gated for hooks/permissions — `installer.py:882`
    passes only `include_statusline=<gated>` and leaves `include_hooks`/`include_permissions` at their `True` defaults
    (`settings_merge.py:677-679`), so **every** `forge extension enable` writes hooks + permissions regardless of
    `--with`/`--without` (the flags are `--with`/`--without`, not `--with-modules`; `extensions.py:500`). Env is also
    ungated (`settings_merge.py:725`). **There is no tracked hooks-only path today.** Delete must therefore *build* one
    (Phase 0) before removing the command.
  - **What delete costs**, now that Phase 0 is real work: the Phase-0 replacement build, plus — unless that build also
    targets `settings.local.json` at user scope — the exact `forge hook enable --user` → `~/.claude/settings.local.json`
    target (tracked `--scope user` → `settings.json`, `installer.py:329`).
  - **Escape valve:** if Phase 0 shows the replacement can't be built at acceptable blast radius, the fallbacks are (a)
    drop the hooks-only affordance entirely and point users to full `forge extension enable`, or (b) reopen D1 toward
    update-by-delegation. **Do not delete the command until Phase 0 lands a tested public replacement.**

The phases below assume **delete**. If Phase 0's escape valve fires toward update, swap Phases 1-2 for the
**Alternative** section; Phase 0/3 are shared.

---

## Phase 0 — HARD GATE: make the tracked hooks-only path real and tested (before removing anything)

There is **no** tracked hooks-only path today (D1 correction: the settings merge writes hooks + permissions
unconditionally). Do **not** proceed to Phase 1/2 until a **public** command produces hooks-only settings and is covered
by a test. This is the load-bearing gate — if it can't be met at acceptable blast radius, the D1 escape valve fires.

- [ ] Choose and implement one:
  - **Option A — module-gate the settings merge.** At `installer.py:882`, pass
    `include_hooks=InstallModule.HOOKS in modules`, `include_permissions=InstallModule.PERMISSIONS in modules`, and a
    new `include_env` gate (tied to `PERMISSIONS` unless a separate env module exists later). Today only
    `include_statusline` is gated. Then a hooks-only module set yields hooks-only settings. **Blast radius (must audit +
    test):** this changes non-standard profiles that currently receive hooks + permissions/env unconditionally — e.g.
    `--profile minimal` today writes both. Find existing installer/settings tests asserting the ungated behavior and
    update them with recorded rationale. The **standard** profile includes both modules, so its output is unchanged
    (assert this explicitly — it is the no-regression anchor).
  - **Option B — dedicated ergonomic surface.** Add a narrow hooks-only path (a flag or small command) that runs the
    gated merge without changing the general `merge()` defaults. Smaller blast radius; new CLI surface to name.
- [ ] Fix the flag facts in this checklist/docs while here: the real flags are `--with` / `--without`
  (`extensions.py:500`), not `--with-modules`/`--without-modules`.
- [ ] Test the **actual public command** (not an internal helper) at local scope: it installs the hook entries and
  **nothing else** — asserts `.claude/settings.local.json` gets exactly the golden 16 hook entries
  (`tests/src/install/test_registered_commands_contract.py`, don't re-pin), **no `permissions`/`env` writes**, **no**
  command/agent/skill files, and the run is recorded in `installed.json` (removable by tracked `unmerge`).
- [ ] Record the exact replacement command string. It is what Phase 2 puts in `hook.md`/QA and what Phase 1 uses to fix
  the shared docker fixture.
- [ ] D1 sub-gate: decide whether the built path must also cover `--user` → `~/.claude/settings.local.json`, or the
  reviewer accepts dropping that exact target (the one capability with no tracked equivalent).

## Phase 1 — Clean-break delete of the second writer

- [ ] Delete `src/forge/cli/hooks/install.py` in full (all of it is second-writer-only: `enable`, `disable`,
  `_is_forge_hook_entry`, `_find_hooks_target`, `FORGE_HOOK_CONFIG`, `SETTINGS_FILENAME`).
- [ ] `cli/hooks/__init__.py`: drop the `.install` import (`:20`), the two `add_command(enable/disable)` (`:27-28`), and
  the `FORGE_HOOK_CONFIG`/`SETTINGS_FILENAME` `__all__` entries. Confirm no other module imports from
  `forge.cli.hooks.install`.
- [ ] `cli/hooks/_group.py`: update the group docstring (`:15-16`) that advertises `enable`/`disable` as user-facing.
- [ ] Repoint the 3 test consumers of `FORGE_HOOK_CONFIG` to the canonical `get_builtin_preset()["hooks"]`:
  `test_read_hygiene.py:174`, `test_handlers.py:495,502`.
- [ ] `test_bug_hook_registry_drift.py`: its premise (two registries drifting) is gone. Delete it, or narrow it to the
  surviving preset-vs-installer coverage — record the rationale (`testing_guidelines`: removed behavior → delete/adjust,
  never skip). Note the matcher card's `test_registered_commands_contract.py` already guards preset entry bytes.
- [ ] Delete the second-writer test surfaces (feature removed → delete tests, `testing_guidelines`):
  - `tests/integration/cli/test_hooks_integration.py` — the **entire file** exercises `forge hook enable`/`disable`
    (`:36-167`).
  - `tests/src/install/test_version.py::TestVersionGateOnHookEnable` (`:189`) — the tracked installer keeps its own
    version gate (`test_version.py:151,165`), so the hook-enable-specific gate test is redundant once the command is
    gone.
  - the `enable`/`disable` behavior cases in `tests/src/cli/test_hooks.py`. **Keep** the predicate/detection tests there
    and in `tests/src/install/test_hooks.py` — those cover `install/hooks.py`, unaffected.
- [ ] **Shared fixture (blocking, reviewer Medium-2):** `tests/integration/docker/conftest.py:81` runs
  `forge hook enable` in the real-Claude setup used across the whole Docker integration tier — deleting the command
  breaks **every** real-Claude test. Repoint it to the Phase-0 replacement command (it only needs hooks *present*, not
  hooks-only). This is a concrete reason Phase 0 must land first.
- [ ] **Clean-break assertion:** `forge hook enable` and `forge hook disable` exit 2 with Click "No such command".
  Follow the established home/pattern (`test_command_tree_invariants.py::test_removed_aliases_are_clean_breaks`; assert
  on `result.output`).

## Phase 2 — Migrate docs / QA / diagram + changelog

- [ ] `docs/end-user/hook.md`: remove the "Advanced: install hooks only" block (`:87-98`), the settings.local.json note
  (`:96-98`), the `:341` usage, and the troubleshooting row (`:359`); replace with the tracked hooks-only invocation
  from Phase 0.
- [ ] `docs/diagrams.md:230`: drop `or forge hook enable` from the installer node.
- [ ] `src/skills/qa/resources/checklist/6-hook.md` (`:5,:15,:32-33`) and `18-disable.md:20`: rewrite these **runnable**
  QA steps to the tracked invocation (they are executed by `/forge:qa`, so they must be a working command). Bump the
  checklist index `last-updated` if required by the QA-checklist update rule.
- [ ] `docs/board/change_log.md`: entry (Goal / Key changes / Verification) naming the removal, the replacement command,
  and the one dropped capability (`--user` local-file target).

## Phase 3 — Verify + close

- [ ] Focused suites green: `tests/src/cli/test_hooks.py`, `tests/src/install/test_hooks.py`,
  `tests/src/install/test_registered_commands_contract.py`, `tests/src/cli/test_read_hygiene.py`,
  `tests/src/policy/team/test_handlers.py`, and the reworked/removed drift regression.
- [ ] `make test-unit` green (no unrelated breakage).
- [ ] Integration (CLI surface + installer path, per `testing_guidelines`): run the reworked installer integration
  target that covers the Phase-0 replacement and the Docker installer path. Do not include
  `tests/integration/cli/test_hooks_integration.py` after Phase 1 if that file is deleted.
- [ ] Grep sweep clean: no `forge hook enable`/`forge hook disable` outside `docs/board/**` + the changelog entry; no
  `FORGE_HOOK_CONFIG` or `from forge.cli.hooks.install` remaining.
- [ ] Scoped pre-commit clean on changed files (ruff/black/isort/mypy/pyright/mdformat).
- [ ] Design/end-user doc sync recorded: `hook.md`/`diagrams.md`/QA updated; no other doc references the command.
- [ ] `impl_notes.md` candidate (after human review): "one hook mutation path — the tracked installer. The standalone
  `forge hook enable/disable` writer + its duplicate `FORGE_HOOK_CONFIG` registry were deleted (clean break); hooks-only
  installs go through `forge extension enable` (hooks module). Removing the second registry also removed the reason
  `test_bug_hook_registry_drift.py` existed."
- [ ] Move card `doing/ -> done/` after merge to `main`.

---

## Alternative: update-by-delegation (only if review rejects delete)

Keep `forge hook enable`/`disable` as **thin CLI wrappers** over the tracked installer (Installer + hooks module +
`merge_hooks` + `TrackingStore`), replacing the hand-rolled writer. This preserves the command surface while fixing
tracking, the bare form (inherits the shipped form), and the overwrite-clobber (merge, not overwrite), and it still
drops the duplicate `FORGE_HOOK_CONFIG` (delegation reads the preset via the installer).

- Blocker to resolve first: to preserve the documented `--user` → `~/.claude/settings.local.json` target, the installer
  needs a "user-dir + local-file" mode that does not exist today. Either add it, or accept `--user` now writes
  `settings.json` (a documented behavior change). This extra capability is the reason delete is recommended over update.
- Phases 1-2 become: wrapper wiring + the installer target mode (or the documented `--user` change) +
  tracking-round-trip tests; docs stay (command preserved) except the `--user` note if the target changes. Phase 0/3
  unchanged.

## Acceptance tests (delete path)

| Test                                          | Fixture                                              | Assertion                                                                                                                                                                                               | Test File                                                        |
| --------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Removed command is a clean break              | invoke `forge hook enable` / `disable` after removal | Click "No such command", exit 2                                                                                                                                                                         | `tests/src/cli/test_command_tree_invariants.py`                  |
| Hooks-only tracked replacement (Phase 0 gate) | the built public hooks-only command at local scope   | `.claude/settings.local.json` gets exactly the golden 16 hook entries — **no `permissions`/`env` writes, no command/agent/skill files**; tracked in `installed.json`; standard-profile output unchanged | `tests/src/install/test_installer.py`                            |
| Duplicate registry gone                       | import surface                                       | `FORGE_HOOK_CONFIG` removed; former consumers read `get_builtin_preset()["hooks"]`                                                                                                                      | `tests/src/policy/team/test_handlers.py`, `test_read_hygiene.py` |
| Predicate/detection unaffected                | existing hook-detection fixtures                     | `install/hooks.py` predicate + `has_forge_hook` tests still green                                                                                                                                       | `tests/src/install/test_hooks.py`                                |
| Docs/QA reference the replacement             | grep `forge hook enable`/`disable`                   | zero hits outside `docs/board/**` + changelog; QA checklists run the tracked command                                                                                                                    | (grep sweep in Phase 3)                                          |

## Blockers / deferred

- **D1 is ratified as delete, gated by Phase 0.** If the Phase-0 replacement cannot land safely, reopen D1; update swaps
  Phases 1-2.
- The second writer's fate is exactly what this card decides; the **epic** (T5/T6) then assumes one mutation path. If
  this lands after T6 instead of before, T6 must treat any already-written bare entries as legacy (value-based cleanup)
  — out of scope here.

## Closeout

(pending — implementation begins after D1 is ratified in review)
