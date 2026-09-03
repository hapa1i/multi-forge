# Preserve Session Delete Preview Truth

**Lane**: `doing/`

**Epic**: [`1.0 Release Hardening`](../epic_1_0_release_hardening/card.md)

## Goal

Make every session deletion preview non-mutating and truthful about artifact survival before the user confirms.

## Scope

- Condition artifact-retention output on whether the containing worktree will be removed (#5).
- Use non-repairing index and active-state reads throughout every pre-confirmation delete path (#6).
- Keep `session clean` preview classification aligned with apply for malformed runtime state, fractional ages, and dirty
  owned worktrees.

## Constraints

- Confirmed deletion retains intentional self-healing of derived session and active indexes.
- Cancellation must not change unrelated index or active-registry bytes.
- Preview wording must describe the planned action without promising retention outside the surviving tree.
- A clean preview must not rewrite state and must identify targets that apply would refuse.
