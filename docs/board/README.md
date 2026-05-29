# Work Board

This directory is Forge's lightweight implementation board. It keeps proposed work, scheduled work, active execution,
completed work, and project memory in one place.

The authoritative board workflow contract lives in [`docs/developer/board-contract.md`](../developer/board-contract.md).
This README is a directory guide plus dogfood examples for people inspecting `docs/board/`.

## Layout

| Path                      | Role                                                  | Next move                                                                  |
| ------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------- |
| `proposed/<slug>/card.md` | Idea or design sketch not yet scheduled               | Move to `todo/` when accepted for execution                                |
| `todo/<slug>/card.md`     | Accepted work parked until an execution branch exists | Move to `doing/` when the branch is created                                |
| `doing/<slug>/card.md`    | Work currently in flight                              | Add or update `checklist.md` during implementation                         |
| `done/<slug>/card.md`     | Completed work snapshot                               | Keep paired `checklist.md` when one existed                                |
| `change_log.md`           | Completed-work record                                 | Handoff agent may update with `strategy=changelog`; humans keep it compact |
| `impl_notes.md`           | Approved memory for future sessions                   | Human-approved only; handoff agent proposes to a shadow doc                |

Every work item is a card directory. `card.md` holds the durable problem framing and design. `checklist.md` is added
when the card needs an execution plan; it is the in-session scratchpad for phases, assertions, blockers, and
verification.

## Lane Semantics

Summary only; see the [contract](../developer/board-contract.md#lanes) for the full operating rules.

Moving a card across lanes is a workflow event:

1. `proposed -> todo`: accepted or scheduled, but no execution branch yet.
2. `todo -> doing`: execution branch exists and the work is in flight.
3. `doing -> done`: shipped, verified, design docs updated, and closeout recorded.

Parking work means leaving it in `todo/`. `todo/` is not the active cursor; it is accepted work waiting for a branch.

## Project Memory

Forge memory has two primitives: **passports** select which docs the memory writer updates, and **session activation**
decides whether it runs.

| Doc                       | Update model                           | How it is maintained                      |
| ------------------------- | -------------------------------------- | ----------------------------------------- |
| `change_log.md`           | Memory writer, direct write at Stop    | Passported as `changelog`                 |
| `impl_notes.md`           | Memory writer, shadow proposal at Stop | Passported as `generic`, shadow mode      |
| card `checklist.md` files | In-session agent, at your direction    | Edited as normal files during the session |

| Command                        | Writes           | Meaning                                           |
| ------------------------------ | ---------------- | ------------------------------------------------- |
| `forge memory track <doc>`     | The markdown doc | Adds or updates the doc's `forge_memory` passport |
| `forge memory passport remove` | The markdown doc | Removes the passport; stops project discovery     |
| `forge memory enable`          | Session manifest | Enables the memory writer for a session           |
| `forge memory disable`         | Session manifest | Disables the memory writer for a session          |

Forge discovers docs by scanning hardcoded roots (`docs/` plus `.forge/memory/`) for passports at Stop time.

### Setup

Passport your docs once (sessionless). Then enable memory per session:

```bash
forge memory track docs/board/change_log.md --strategy changelog
forge memory track docs/board/impl_notes.md --propose --shadow-path .forge/memory/shadow_impl_notes.md

# Start a session with memory on:
forge session start planner --memory on

# Or enable for an existing session:
forge memory enable --session planner
```

After the first session, inspect the output:

```bash
forge session handoff show planner --latest
```

Review and curate implementation-note proposals before promoting anything into `impl_notes.md`:

```bash
forge memory shadows review --for docs/board/impl_notes.md --curate --session planner
```

To stop a board doc from being project memory, remove its passport:

```bash
forge memory passport remove docs/board/change_log.md
```

One-off doc updates that don't need a passport are ordinary agent instructions.

## Dogfood Workflow: Planner, Supervised Executor, Reviewer

Use this flow when a planner owns the approved plan, an executor implements in an isolated worktree under supervisor
policy, and a reviewer inspects the executor's worktree with the planner's context.

The important memory behavior:

- Passports are git-tracked, so worktree forks see the same board memory contract.
- Children inherit the parent's memory activation by default (`--memory on|off` overrides).
- The executor can update `change_log.md` and shadow `impl_notes.md` at Stop without per-session `track`.

### 1. Planner

Prepare memory, then start a planning session:

```bash
forge memory track docs/board/change_log.md --strategy changelog
forge memory track docs/board/impl_notes.md --propose --shadow-path .forge/memory/shadow_impl_notes.md

forge session start planner --memory on --proxy openrouter-openai
```

Have the planner produce and approve the plan. After the planner stops, inspect the handoff report:

```bash
forge session handoff show planner --latest
```

### 2. Supervised Executor

Fork the planner into a dedicated worktree. `--supervise` makes the planner session the executor's plan supervisor, and
`--inline-plan` embeds the approved plan into the executor handoff file.

```bash
forge session fork planner \
  --name executor \
  --worktree \
  --supervise \
  --inline-plan \
  --no-launch

forge session resume executor
```

For this repository, the default executor worktree is usually `../multi-forge-executor`. Use the worktree path printed
by `forge session fork` if the repo or session name differs.

While the executor runs, the supervisor checks file edits against the planner's approved plan. If the plan changes
during implementation, use the supervisor reload flow instead of removing supervision:

```text
%policy supervise off
%policy supervise reload
%policy supervise on
```

When the executor stops, the memory writer runs in the executor checkout. The executor inherited memory activation from
the planner, and git carried the passports, so it can update `docs/board/change_log.md` and write proposals to its own
`.forge/memory/shadow_impl_notes.md`.

### 3. Reviewer

Fork the planner into the executor's existing worktree so the reviewer sees both the approved plan and the executor's
file state:

```bash
forge session fork planner \
  --name reviewer \
  --into ../multi-forge-executor \
  --inline-plan
```

`--into` uses resume handoff because native Claude resume is scoped to the original CWD. The reviewer session inherits
the planner's memory activation. Make the reviewer prompt explicitly review-oriented until the runtime-abstraction
context commands land.

Use `--strategy full` only when the executor or reviewer needs complete transcript detail. The default structured
handoff plus `--inline-plan` keeps context smaller while preserving the approved plan.

## Scoping

These docs intentionally use git-tracked and gitignored locations to define scope:

| Path                                    | Scope                          | Why                                                                                 |
| --------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------- |
| `docs/board/<lane>/<slug>/checklist.md` | One proposal or feature branch | Lives with the card executing the work                                              |
| `docs/board/change_log.md`              | Project lifetime               | Merged with feature PRs; newest-first merge conflicts are integration signals       |
| `docs/board/impl_notes.md`              | Project lifetime               | Human-promoted durable memory merged with feature PRs                               |
| `.forge/memory/shadow_impl_notes.md`    | Per worktree, per machine      | Gitignored shadow proposals; each parallel worktree accumulates its own suggestions |

Sub-branches off a feature branch inherit that feature's card checklist and can tick items independently. Merge
conflicts in `change_log.md` are expected when branches interleave completed work.

## Card Lifecycle

Closeout rules live in the [work-board contract](../developer/board-contract.md#closeout). In short: finish the
checklist, record completed work, promote durable lessons after human review, sync design docs, then move
`doing/<slug>/` to `done/<slug>/`.

## End-Of-Session Routine

Use the active card checklist as the in-session scratchpad. Leave transient status there, record completed work in
`change_log.md`, and promote only durable lessons to `impl_notes.md` after human review.

## Size Checks

Use the [work-board contract size checks](../developer/board-contract.md#size-checks) when a living board doc starts to
feel bulky.
