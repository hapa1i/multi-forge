# Align the incognito worktree root guard

**Epic**: [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).

**Finding**: D010 (MEDIUM) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted as the final Wave 3 implementation member.

## Goal

Apply the same main-checkout precondition to `session incognito --worktree` that already governs every other command
creating a new Git worktree.

## Design Authority

- [`docs/design.md` project identity and worktree rules](../../../design.md#project-identity-model): `--worktree`
  creates an isolated checkout from the main repository, while non-worktree sessions may launch from a valid repo root.
- [`cli_style_guidelines.md` § Tips and Recovery Output](../../../developer/cli_style_guidelines.md#tips-and-recovery-output):
  the refusal must use the shared error helpers and give an actionable recovery command on stderr.

## Evidence

Rechecked on `dc963a7c`: observing both guards during `forge session incognito guard-drift --worktree --no-proxy` showed
an unconditional `require_repo_root()` call and no `require_main_repo_root()` call. `session start`, `session fork`, and
Codex start already branch on `--worktree` and require the main checkout.

## Expected Behavior

- `session incognito --worktree` rejects invocation from a linked worktree with the same actionable main-checkout
  diagnostic as `session start --worktree` and `session fork --worktree`.
- Incognito without `--worktree` keeps its existing valid-repository behavior.
- Rejection occurs before session, branch, worktree, extension, or launch mutation.

## Acceptance Criteria

- Add `tests/regression/test_bug_d010_incognito_worktree_root_guard.py` with the required regression marker and a
  docstring naming D010 and the unconditional weaker guard.
- CLI unit tests pin linked-worktree rejection, main-checkout acceptance, and ordinary incognito behavior.
- Run focused incognito/start/fork CLI tests, then
  `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py`, `make test-regression`, and
  `make pre-commit`.

## Compatibility and Exclusions

- This aligns an existing option with sibling behavior; it does not remove `--worktree` or change branch naming.
- Do not change `--into`, same-directory sessions, worktree ownership, or incognito cleanup semantics.
