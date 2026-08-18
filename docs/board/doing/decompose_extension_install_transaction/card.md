# Decompose the extension install transaction

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `doing/` -- active on `refactor/decompose-extension-install-transaction` from `b72fab14`.

**Finding**: O069's `Installer.init` subset.

**Depends on**: [`centralize_install_path_authority`](../../done/centralize_install_path_authority/card.md).

## Goal

Extract named install-apply phases from `Installer.init` while preserving the exact mutation order, rollback coverage,
and tracking commit boundary established by Wave 4.

## Evidence and Authority

Reverified on `b72fab14`, `init()` remains 425 lines spanning compiled-skill materialization, dispatcher/files, Claude
settings/ownership, stale-file cleanup, Codex registration, and final tracking. These phases have different failure and
rollback semantics; “split the method” is unsafe unless the existing fault matrix remains explicit. Authority:
[`docs/design_appendix.md` "C. Install Model Reference"](../../../design_appendix.md#c-install-model-reference) and
[`docs/design.md` "5.1 Extensions install model"](../../../design.md#51-extensions-install-model).

Order-5 review also found 21 patches of the installer module's `get_target_root` binding across eight test files. The
component integration helper caused 11 failures once planning reached lower path policy and was repaired on order 5 by
configuring its isolated `CLAUDE_HOME` source instead. Twenty installer-binding patches remain across seven files;
nineteen patch only that binding, while the QA2 stale-symlink regression already needs a second patch at the lower
path-policy binding. Runtime removal holds a third binding. The execution-base recheck still finds 20 installer-binding
patches across seven files, including that one dual patch. The repeated setup therefore meets the shared-fixture
threshold in the
[`testing_guidelines.md` monkeypatch policy](../../../developer/testing_guidelines.md#monkeypatch-policy).

## Acceptance Criteria

- Extract typed phase inputs/results for file application, settings ownership, stale reconciliation, Codex apply, and
  final installation assembly without reordering their side effects.
- Before extracting phases, replace repeated direct target-root patches with a shared fixture that configures one
  isolated environment-backed Claude target; migrate the existing sites and prove installer, path-policy legacy-row
  fallback, and runtime-removal execution all resolve that same root without namespace-specific patches.
- Every existing injected failure retains its exact filesystem, sidecar, Codex config, and tracking outcome; add a
  phase-order/fault table to the execution checklist before code changes.
- Planning remains side-effect free; conflicts still stop before materialization; tracking commits last.
- Run full installer units/regressions, targeted Docker installer tests, runtime-skill lifecycle checks, build, and
  clean-wheel enable/disable verification.

## Exclusions

Do not redesign the install transaction, collapse distinct rollback policies, broaden auto-deletion, or change
runtime-scoped preservation/disable semantics under cover of extraction.
