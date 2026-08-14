# Centralize installer path and ownership authority

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 installer refactor work.

**Findings**: O065's exact preserve-the-leaf duplicate and O069's runtime-removal callback inversion.

## Goal

Move pure install target/boundary policy below both installer and runtime removal, and share the two byte-equivalent
package-path canonicalizers.

## Evidence and Authority

On `5777192a`, `skill_planning._absolute_path` and `unmanaged.canonical_package_path` have the same preserve-leaf
algorithm. `RuntimeRemovalExecutor` receives four installer-owned path/ownership callables, making the lower module
depend on higher-layer policy by injection. The CLI extension test file also repeats the canonical current-directory,
parent-directory, and missing-root `find_git_root` cases from `tests/src/core/test_paths.py`; that duplicate block is
test-organization cleanup for this path-ownership pass, not a second discovery contract. Authority:
[`docs/design.md` "3.5 File ownership boundaries"](../../../design.md#35-file-ownership-boundaries-normative) and
[`docs/design_appendix.md` "C. Install Model Reference"](../../../design_appendix.md#c-install-model-reference).

## Acceptance Criteria

- A lower install module owns target-root, path-boundary, tracked-file-boundary, Codex config-scope validation, and
  preserve-leaf package helpers used by both install and runtime removal.
- `RuntimeRemovalExecutor` no longer needs the four installer method/function callbacks for those policies.
- Exact path, symlink, unsafe-boundary, runtime-scope, and untracked-package outcomes remain unchanged.
- Remove the duplicate `TestFindGitRoot` block from `tests/src/cli/test_extension_enable.py`; retain the canonical core
  cases and the extension detector/CLI behavior tests.
- Run installer/unmanaged/runtime-removal units and the required targeted installer integration suite.

## Exclusions

Whole-path project/dispatcher canonicalizers and the standalone bundled hook copy intentionally have different
contracts. Do not merge them, remove `_detect_git_project_root` behavior coverage, relax fail-closed cleanup, or alter
schema-v3 unmanaged-package reporting.
