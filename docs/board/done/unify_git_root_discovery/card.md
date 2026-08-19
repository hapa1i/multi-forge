# Unify git-root discovery contracts

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped independently in PR #181 (`a8cff31f`) from order-3 closeout commit `9817cad3`.

**Findings**: O066 and O092's `ProjectRootNotFoundError` subset.

## Goal

Use `find_git_root` as the canonical optional git-root walker, route the strict caller through it, then remove the
unused exception type.

## Evidence and Authority

Rechecked on `9817cad3`: `core.paths.find_git_root` still returns `None`, the session Claude path helper still repeats
the walk and raises `FileNotFoundError`, and `ProjectRootNotFoundError` remains definition-only. The Git-subprocess
helpers in `session.git` have distinct bare-repository and worktree-membership contracts and remain excluded. The
unchanged path, artifact, resume, guard, and worktree characterization passes 181 tests. Authority:
[`docs/design.md` "Project identity model"](../../../design.md#project-identity-model) and DG4's internal deletion
rubric.

## Acceptance Criteria

- One optional walker defines canonical parent traversal and worktree handling.
- Existing optional callers still receive `None`; strict callers retain their current actionable exception contract.
- Remove `ProjectRootNotFoundError` only after a final import/docs/resource search.
- Run core path, session git/Claude path, resume-path, and worktree tests.

## Implementation Outcome

`core.paths.find_git_root` now owns the only filesystem `.git` parent walk and directly implements it without a
single-caller identity helper. The optional API still returns a resolved checkout root or `None`; the Claude
`find_project_root` adapter delegates to it while retaining the cwd default and exact `FileNotFoundError` contract.
Git-backed checkout/logical-repository discovery remains independently owned by `session.git`.

The definition-only `ProjectRootNotFoundError` is removed. A final production, test, bundled-resource, and non-board
documentation search finds no live reference; historical board and deletion-contract records remain as provenance.
`docs/design.md` now distinguishes filesystem marker discovery from Git-backed identity. No end-user command, error,
configuration, or durable-state contract changed.

Verification passes 182 focused tests and 3 targeted Docker integration tests covering session start, resume, and an
isolated worktree. The full gates pass with 9,065 unit tests and 898 regression tests; one unit test is skipped and 122
integration tests are deselected by the unit target. `make pre-commit` and `git diff --check` pass. The board audit
checks 332 Markdown files and 854 local path links, including 9 changed board documents and 4 changed-document fragment
links; all targets and fragments resolve, all 34 Wave 7 members link back to the epic, and the graph remains 3 done, 1
doing, and 30 todo.

PR #181 merged as `a8cff31f` with all five GitHub checks passing. The post-merge closeout leaves orders 5--34 parked
until the epic explicitly selects the next member. All 854 local path links across 332 board Markdown files and both
fragments from the nine changed board documents resolve; the Wave 7 graph is four `done/`, zero `doing/`, and 30 `todo/`
members with valid epic backlinks.

## Exclusions

Do not change Forge-root discovery, bare-repository handling, worktree membership, or user-facing error wording outside
the strict wrapper.
