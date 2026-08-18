# Unify Claude session state-context derivation checklist

Current focus: active on `refactor/unify-claude-session-state-context` from corrected `main` at `52c36e2a`; only Wave 7
order 28 is active.

## Reverification and contract

- [x] Recheck O058's cited launch, resume, fork, and post-create mutation sites on the execution base.
- [x] Confirm the durable manifest Forge root must win over a relocated worktree and the current shell.
- [x] Confirm missing recorded worktrees remain a launchability error owned by `require_session_worktree`, while legacy
  manifests without a worktree retain their current-directory fallback.
- [x] Confirm no public API, schema, repair, adoption, or worktree-recreation change is required.

## Implementation

- [x] Add one typed manifest-to-worktree/root/store resolver with an explicit current-directory fallback.
- [x] Route launch, resume, fork, and start's three post-create mutations through the resolved context.
- [x] Route the CLI fork's native-relocate, rewind, transfer-prompt, and transfer-store seams through that context.
- [x] Preserve relocated-worktree state ownership and run the missing-worktree guard before launch callbacks.
- [x] Make the cross-module resolver non-private and record the intentionally distinct legacy hook-environment rule.
- [x] Add direct context cases and structural drift coverage for every affected operation.
- [x] Synchronize the command-core ownership sentence in normative design documentation within its token ceiling.

## Acceptance tests

| Boundary               | Fixture                                     | Assertion                                                         | Test file                                                    |
| ---------------------- | ------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------ |
| Current manifest       | recorded Forge root and checkout            | root/store/worktree derive from durable fields                    | `tests/src/core/ops/test_claude_session.py`                  |
| Legacy missing root    | no `forge_root`, recorded checkout          | checkout anchors both root and store                              | `tests/src/core/ops/test_claude_session.py`                  |
| Relocated worktree     | Forge root differs from recorded checkout   | store stays under Forge root; checkout remains launch path        | `tests/src/core/ops/test_claude_session.py`                  |
| Missing worktree       | recorded checkout absent on disk            | context remains derivable; launch guard fails before callbacks    | `tests/src/core/ops/test_claude_session.py`                  |
| Post-create mutations  | durable root differs from current directory | memory, subprocess proxy, and supervisor persist in durable store | Claude manifest characterization and focused op tests        |
| Legacy post-create     | no root; worktree differs from current dir  | memory and subprocess proxy persist under the worktree            | `tests/src/core/ops/test_claude_session.py`                  |
| User-facing operations | start, resume, and fork through Docker      | launch/state behavior remains unchanged                           | `tests/integration/cli/test_session_commands_integration.py` |

## Verification and closeout

- [x] Run focused Claude op, manifest-characterization, resume, fork, and relevant regression tests (223 passed).
- [x] Run `make test-unit` (9,249 passed, one skipped, 122 deselected) and `make test-regression` (923 passed).
- [x] Run targeted Docker session start/resume/fork integration coverage (69 passed).
- [x] Run full `make pre-commit`, diff checks, design token counts (29,989 and 29,990), and the board audit (364
  documents, 896 local links, zero missing; 14 proposed / 10 todo / three doing / 162 done / four retired).
- [ ] Open a draft PR; after merge, close order 28 before activating order 29.
