# Remove verified dead session helpers

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4).

**Lane**: `todo/` -- accepted Wave 7 session cleanup work.

**Finding**: O092's `collect_shadow_entries.session_filter`, `_print_session_tip`, and
`_generate_relaunch_name.parent_name` subsets.

## Goal

Remove individually verified, internal-only session parameters/behavior that no production caller can exercise.

## Evidence and Authority

On `5777192a`, production passes no non-`None` shadow session filter, `_print_session_tip` is an uncalled no-op, and
`_generate_relaunch_name` derives only from `forge_root`. DG4 and
[`docs/developer/coding_standards.md` "Internal surface"](../../../developer/coding_standards.md#internal-surface-module-to-module-private-apis)
govern the deletion.

## Acceptance Criteria

- Recheck source, resource, extension, docs, and export callers for each exact symbol immediately before removal.
- Remove direct-only filtered/no-op/unused-argument tests while retaining live shadow collection and project-scoped
  relaunch collision coverage.
- Run shadow-curation, session manager/resume, and related regression tests plus targeted session integration coverage.

## Exclusions

Do not remove active session selection, change shadow ordering, or base relaunch uniqueness on the parent name.
