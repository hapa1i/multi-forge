# Work Board

This directory is Forge's lightweight implementation board. It keeps proposed work, scheduled work, active execution,
completed work, and project memory in one place.

The authoritative board workflow contract lives in
[`docs/developer/work-board-contract.md`](../developer/work-board-contract.md). This README is a directory guide plus
dogfood examples for people inspecting `docs/board/`.

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

Summary only; see the [contract](../developer/work-board-contract.md#lanes) for the full operating rules.

Moving a card across lanes is a workflow event:

1. `proposed -> todo`: accepted or scheduled, but no execution branch yet.
2. `todo -> doing`: execution branch exists and the work is in flight.
3. `doing -> done`: shipped, verified, design docs updated, and closeout recorded.

Parking work means leaving it in `todo/`. `todo/` is not the active cursor; it is accepted work waiting for a branch.

## Handoff Agent Setup

`forge memory track` authors a **project passport** inside the doc (git-tracked, project-lifetime) and is
**sessionless** — run it from any terminal in the checkout, no session required. `forge memory enable` turns the handoff
agent on for the whole checkout (bare) or for one session (`--session <name>`). Per-session-only participation without a
passport uses `forge memory extra add <path> --as <strategy> --session <name>`, which does need a target session
(`--session`, `$FORGE_SESSION`, or an active session). Project/repo-wide *reads* (`forge memory status`,
`forge memory shadows`) do not require a session.

These board docs use three different update models:

| Doc                       | Update model                           | Setup                                       |
| ------------------------- | -------------------------------------- | ------------------------------------------- |
| `change_log.md`           | Handoff agent, direct write at Stop    | `forge memory track ... --as changelog`     |
| `impl_notes.md`           | Handoff agent, shadow proposal at Stop | `forge memory track ... --propose`          |
| card `checklist.md` files | In-session agent, at your direction    | none - the agent edits them as normal files |

For the first run, use `review-only` to inspect the handoff agent's proposed output before allowing writes:

```bash
# Author project passports (sessionless — no session needed)
forge memory track docs/board/change_log.md --as changelog
forge memory track docs/board/impl_notes.md \
  --propose --shadow .forge/memory/suggested_impl_notes.md

# Turn the handoff agent on for the whole checkout, review-only for the first run
forge memory enable --review-only

# Verify: passports are discoverable without a manifest entry
forge memory shadows list
forge memory passport show docs/board/change_log.md
```

The explicit `--shadow` pins the proposal to `.forge/memory/suggested_impl_notes.md` (the source path referenced in
`impl_notes.md` and the scoping table below). Without it, the derived path would encode the parent directory
(`suggested_board_impl_notes.md`). Leave card checklists untracked; direct the coding agent to tick items and add
blockers during the session.

Inspect the proposed output, then switch to augment (write) mode:

```bash
forge session handoff show <name> --latest
forge memory enable
```

After a session, review accumulated shadow proposals before promoting to `impl_notes.md`:

```bash
forge memory shadows review --for docs/board/impl_notes.md --curate --session <name>
forge memory shadows review --for docs/board/impl_notes.md --show-latest --session <name>
```

Passports are project-wide: author them once and every session in the checkout (including `executor` and `reviewer`
forks) sees them via the Stop-time scan once project memory is enabled — no per-session re-tracking. Session-only extras
added with `forge memory extra add` are also carried into forks by default (`--inherit-memory all`).

## Advanced Workflow

Use this when one high-reasoning planner owns the approved plan, one supervised executor implements in an isolated
worktree, and one reviewer enters the executor's worktree with the planner's context.

Compared with the shortest three-command workflow, the dogfood path adds three safeguards:

- Author passports and enable project memory before the first Stop event (passports are sessionless, so this needs no
  running session).
- Run the first handoff-agent pass in `review-only`, inspect it, then switch to `augment`.
- Use `--inline-plan` for worktree forks. `--propose` auto-creates shadow files for the planner; worktree forks inherit
  and materialize them via `--inherit-memory`.

### 1. Planner

Author project passports and enable memory first (sessionless), then start the planning session:

```bash
# Author project passports (sessionless — do this before any session runs)
forge memory track docs/board/change_log.md --as changelog
forge memory track docs/board/impl_notes.md \
  --propose --shadow .forge/memory/suggested_impl_notes.md

# Enable the handoff agent for the checkout (review-only first)
forge memory enable --review-only

forge session start planner --proxy openrouter-openai
```

After the planner exits, inspect the first proposed memory update before allowing writes:

```bash
forge session handoff show planner --latest
forge memory enable
```

### 2. Supervised Executor

Fork the planner into a dedicated worktree. `--supervise` makes the planner the executor's plan supervisor, and
`--inline-plan` carries the approved plan directly in the handoff context.

```bash
forge session fork planner \
  --name executor \
  --worktree \
  --supervise \
  --inline-plan \
  --no-launch

forge session resume executor
```

For this repository, `executor` defaults to the sibling worktree `../multi-forge-executor`. If the repo or session name
changes, use the worktree path printed by `forge session fork`.

### 3. Reviewer

Fork the planner into the executor's existing worktree so the reviewer sees the approved plan plus the executor's file
state:

```bash
forge session fork planner \
  --name reviewer \
  --into ../multi-forge-executor \
  --inline-plan
```

`fork --into` targets an existing non-main worktree, so it uses resume handoff rather than native Claude resume across
the CWD boundary. `fork` does not yet have a review-edit flag; make the review-only intent explicit in the reviewer
session prompt until the runtime-abstraction Phase 1 context commands land.

Use `--strategy full` only when the executor or reviewer needs full transcript detail. The default structured handoff
plus `--inline-plan` keeps context smaller while preserving the approved plan.

## Scoping

These docs intentionally use git-tracked and gitignored locations to define scope:

| Doc                                     | Scope                          | Why                                                                                 |
| --------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------- |
| `docs/board/<lane>/<slug>/checklist.md` | One proposal or feature branch | Lives with the card executing the work                                              |
| `docs/board/change_log.md`              | Project lifetime               | Merged with feature PRs; newest-first merge conflicts are integration signals       |
| `docs/board/impl_notes.md`              | Project lifetime               | Human-promoted durable memory merged with feature PRs                               |
| `.forge/memory/suggested_impl_notes.md` | Per worktree, per machine      | Gitignored shadow proposals; each parallel worktree accumulates its own suggestions |

Sub-branches off a feature branch inherit that feature's card checklist and can tick items independently. Merge
conflicts in `change_log.md` are expected when branches interleave completed work.

## Card Lifecycle

Closeout rules live in the [work-board contract](../developer/work-board-contract.md#closeout). In short: finish the
checklist, record completed work, promote durable lessons after human review, sync design docs, then move
`doing/<slug>/` to `done/<slug>/`.

## End-Of-Session Routine

Use the active card checklist as the in-session scratchpad. Leave transient status there, record completed work in
`change_log.md`, and promote only durable lessons to `impl_notes.md` after human review.

## Size Checks

Use the [work-board contract size checks](../developer/work-board-contract.md#size-checks) when a living board doc
starts to feel bulky.
