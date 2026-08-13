# Decompose the extension install transaction

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 structural refactor work.

**Finding**: O069's `Installer.init` subset.

**Depends on**: [`centralize_install_path_authority`](../centralize_install_path_authority/card.md).

## Goal

Extract named install-apply phases from `Installer.init` while preserving the exact mutation order, rollback coverage,
and tracking commit boundary established by Wave 4.

## Evidence and Authority

On `5777192a`, `init()` remains about 418 lines spanning compiled-skill materialization, dispatcher/files, Claude
settings/ownership, stale-file cleanup, Codex registration, and final tracking. These phases have different failure and
rollback semantics; “split the method” is unsafe unless the existing fault matrix remains explicit. Authority:
[`docs/design_appendix.md` "C. Install Model Reference"](../../../design_appendix.md#c-install-model-reference) and
[`docs/design.md` "5.1 Extensions install model"](../../../design.md#51-extensions-install-model).

## Acceptance Criteria

- Extract typed phase inputs/results for file application, settings ownership, stale reconciliation, Codex apply, and
  final installation assembly without reordering their side effects.
- Every existing injected failure retains its exact filesystem, sidecar, Codex config, and tracking outcome; add a
  phase-order/fault table to the execution checklist before code changes.
- Planning remains side-effect free; conflicts still stop before materialization; tracking commits last.
- Run full installer units/regressions, targeted Docker installer tests, runtime-skill lifecycle checks, build, and
  clean-wheel enable/disable verification.

## Exclusions

Do not redesign the install transaction, collapse distinct rollback policies, broaden auto-deletion, or change
runtime-scoped preservation/disable semantics under cover of extraction.
