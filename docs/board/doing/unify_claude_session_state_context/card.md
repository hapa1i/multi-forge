# Unify Claude session state-context derivation

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `doing/` -- active on `refactor/unify-claude-session-state-context` from corrected `main` at `52c36e2a`.

**Finding**: O058.

## Goal

Resolve manifest, worktree, Forge root, and `SessionStore` through one typed helper across Claude session operations.

## Evidence and Authority

Reverified on `52c36e2a`: `core/ops/claude_session.py` still derives worktree, Forge root, and `SessionStore` separately
in launch, resume, and fork. Start's three post-create mutation helpers repeat a second root/store family: memory and
subprocess proxy fall straight back to the current directory, while supervisor wiring prefers the recorded worktree. The
manifest's Forge root remains the state anchor; worktree is a launch path, not a competing store owner. Authority:
[`docs/design.md` "Context model: Forge vs Claude Code"](../../../design.md#context-model-forge-vs-claude-code) and
[`docs/design.md` "3.12 Command-core ops"](../../../design.md#312-command-core-ops-shared-implementation).

## Acceptance Criteria

- One typed resolver defines current-manifest, legacy missing-root, relocated worktree, and missing-worktree outcomes.
- Every affected op obtains the same store/root for the same manifest while preserving launchability checks separately.
- Start's memory, subprocess-proxy, and supervisor mutations consume the resolved store/root instead of deriving their
  own fallback.
- Run Claude session op/manifest characterization, resume/fork regressions, and targeted session integration coverage.

## Exclusions

Do not infer Forge root from the current shell when durable state supplies it, recreate missing worktrees, or change
session repair/adoption authority.
