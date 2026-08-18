# Extract session-fork preflight

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped in PR #210 as `85c050e2` after focused, full, regression, targeted fork integration, and
pre-commit verification.

**Finding**: O068's pre-mutation subset.

## Goal

Move fork target, parent, strategy, routing, budget, and launchability checks into a UI-free command-core preflight that
returns a typed plan before durable mutation.

## Evidence and Authority

Reverified on `54188e61`: the 900-line Click callback still interleaves git/target interrogation, parent/session
resolution, transfer/rewind strategy, routing, and later mutation. Its preflight can start routing and supervisor
proxies before the mutation call, while target/session checks are split between the callback and `SessionManager`. Wave
6 already established that launch prerequisites must run before child creation. Authority:
[`docs/design.md` "3.12 Command-core ops"](../../../design.md#312-command-core-ops-shared-implementation),
[`docs/design.md` "3.9 Session Resume"](../../../design.md#39-session-resume-context-management), and
[`docs/developer/cli_style_guidelines.md` "Command Shape"](../../../developer/cli_style_guidelines.md#command-shape).

## Acceptance Criteria

- A typed op resolves target git state, occupancy/collisions, parent launchability, strategy/depth/budget, native
  relocation prerequisites, routing, model, and supervisor inputs without writing files, rows, worktrees, or branches.
- Click owns prompts/rendering/exits and maps each typed op failure to the current stderr and exit behavior, retaining
  any preceding explanatory notice.
- Fail-first/characterization fixtures prove every rejected precondition leaves the index, manifests, git worktrees,
  branches, transfer artifacts, and runtime processes unchanged.
- Run fork/session/routing/regression units and targeted fork/rewind integration coverage.

## Exclusions

Do not otherwise change fork semantics, add rollback to preflight, launch a runtime, or absorb the post-create execution
phase. The inherited `full`-budget reference deliberately closes the fork-side drift from the normative §3.9 rule: the
parent's started proxy ID now precedes its intent template. Moving deterministic checks before runtime resolution may
also change which independent error wins when one request has multiple invalid inputs; each individual failure retains
its established rendering and exit. The execution phase belongs to
[`extract_session_fork_execution`](../../todo/extract_session_fork_execution/card.md).
