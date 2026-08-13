# Extract session-fork preflight

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 structural refactor work.

**Finding**: O068's pre-mutation subset.

## Goal

Move fork target, parent, strategy, routing, budget, and launchability checks into a UI-free command-core preflight that
returns a typed plan before durable mutation.

## Evidence and Authority

On `5777192a`, the Click callback spans roughly 900 lines and interleaves git/target interrogation, parent/session
resolution, transfer/rewind strategy, routing, and later mutation. Wave 6 already established that launch prerequisites
must run before child creation. Authority:
[`docs/design.md` "3.12 Command-core ops"](../../../design.md#312-command-core-ops-shared-implementation),
[`docs/design.md` "3.9 Session Resume"](../../../design.md#39-session-resume-context-management), and
[`docs/developer/cli_style_guidelines.md` "Command Shape"](../../../developer/cli_style_guidelines.md#command-shape).

## Acceptance Criteria

- A typed op resolves target git state, occupancy/collisions, parent launchability, strategy/depth/budget, native
  relocation prerequisites, routing, model, and supervisor inputs without writing files, rows, worktrees, or branches.
- Click owns prompts/rendering/exits and maps typed op failures to the exact current stderr and exit behavior.
- Fail-first/characterization fixtures prove every rejected precondition leaves the index, manifests, git worktrees,
  branches, transfer artifacts, and runtime processes unchanged.
- Run fork/session/routing/regression units and targeted fork/rewind integration coverage.

## Exclusions

Do not change fork semantics, add rollback to preflight, launch a runtime, or absorb the post-create execution phase.
That phase belongs to [`extract_session_fork_execution`](../extract_session_fork_execution/card.md).
