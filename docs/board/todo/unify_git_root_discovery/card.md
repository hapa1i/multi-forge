# Unify git-root discovery contracts

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 refactor/deletion work.

**Findings**: O066 and O092's `ProjectRootNotFoundError` subset.

## Goal

Use one git-root walker with explicit optional and strict wrappers, then remove the unused exception type.

## Evidence and Authority

On `5777192a`, `core.paths.find_git_root` returns `None`, the session Claude path helper repeats the walk and raises
`FileNotFoundError`, and `ProjectRootNotFoundError` has no caller. Authority:
[`docs/design.md` "Project identity model"](../../../design.md#project-identity-model) and DG4's internal deletion
rubric.

## Acceptance Criteria

- One low-level walker defines canonical parent traversal and worktree handling.
- Existing optional callers still receive `None`; strict callers retain their current actionable exception contract.
- Remove `ProjectRootNotFoundError` only after a final import/docs/resource search.
- Run core path, session git/Claude path, resume-path, and worktree tests.

## Exclusions

Do not change Forge-root discovery, bare-repository handling, worktree membership, or user-facing error wording outside
the strict wrapper.
