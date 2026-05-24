# Status Docs

This directory holds living implementation context for Forge.

## Files

| File            | Role                                      | Update path                                                                |
| --------------- | ----------------------------------------- | -------------------------------------------------------------------------- |
| `change_log.md` | Completed-work record                     | Handoff agent may update with `strategy=changelog`; humans keep it compact |
| `impl_notes.md` | Approved memory for future sessions       | Human-approved only; handoff agent proposes to a shadow doc                |
| `checklist.md`  | Current milestone/proposal execution plan | Manual living checklist updated during and at the end of coding sessions   |
| `archive/`      | Completed proposal + checklist archives   | Store final `<name>/proposal.md` + `<name>/checklist.md` snapshots here    |

## Handoff Agent Setup

For the first run, use `review-only` to inspect the handoff agent's proposed output before allowing writes:

```bash
forge memory enable --review-only
forge memory track docs/status/change_log.md --as changelog
forge memory track docs/status/impl_notes.md \
  --propose --shadow .forge/memory/suggested_impl_notes.md
forge memory list --json
```

After the first review-only run completes, inspect the agent's proposed output:

```bash
forge session handoff show --latest
```

If the report looks good, switch to the normal augment mode:

```bash
forge memory enable
```

For established sessions, augment mode is the default:

```bash
forge memory enable
forge memory track docs/status/change_log.md --as changelog
forge memory track docs/status/impl_notes.md \
  --propose --shadow .forge/memory/suggested_impl_notes.md
forge memory list --json
```

`forge memory track` is idempotent. Re-running with different flags updates the existing entry.

Optionally let the handoff agent mark checklist items at Stop time:

```bash
forge memory track docs/status/checklist.md --as checklist
```

After a session, review accumulated shadow proposals before promoting to `impl_notes.md`:

```bash
forge memory shadows review --for docs/status/impl_notes.md --curate
forge memory shadows review --for docs/status/impl_notes.md --show-latest
```

## Advanced Workflow

Use this when one high-reasoning planner owns the approved plan, one supervised executor implements in an isolated
worktree, and one reviewer enters the executor's worktree with the planner's context.

Compared with the shortest three-command workflow, the dogfood path adds three safeguards:

- Create the planner with `--no-launch` so memory docs are attached before the first Stop event.
- Run the first handoff-agent pass in `review-only`, inspect it, then switch to `augment`.
- Use `--inline-plan` for worktree forks. `--propose` auto-creates shadow files for the planner; worktree forks inherit
  and materialize them via `--inherit-memory`.

### 1. Planner

Create the planner without launching, attach memory docs, then start the planning session:

```bash
forge session start planner --proxy openrouter-openai --no-launch

forge memory enable --review-only --session planner
forge memory track docs/status/change_log.md --as changelog --session planner
forge memory track docs/status/impl_notes.md \
  --propose --shadow .forge/memory/suggested_impl_notes.md --session planner
forge memory list --json --session planner

forge session resume planner
```

After the planner exits, inspect the first proposed memory update before allowing writes:

```bash
forge session handoff show planner --latest
forge memory enable --session planner
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
| `docs/status/checklist.md`              | One proposal or feature branch | Lives on the branch executing the proposal; archived at proposal completion         |
| `docs/status/change_log.md`             | Project lifetime               | Merged with feature PRs; newest-first merge conflicts are integration signals       |
| `docs/status/impl_notes.md`             | Project lifetime               | Human-promoted durable memory merged with feature PRs                               |
| `.forge/memory/suggested_impl_notes.md` | Per worktree, per machine      | Gitignored shadow proposals; each parallel worktree accumulates its own suggestions |

Sub-branches off a feature branch inherit that feature's `checklist.md` and can tick items independently. Merge
conflicts in `change_log.md` are expected when branches interleave completed work.

## Checklist Lifecycle

`docs/status/checklist.md` tracks one active milestone or proposal at a time. When the proposal is fully executed:

1. Add a final compact entry to `docs/status/change_log.md`.
2. Promote durable lessons to `docs/status/impl_notes.md`.
3. Verify design docs reflect all shipped changes (update any sections that fell behind).
4. After the final merge to `main`, copy final proposal and checklist snapshots to
   `docs/status/archive/<name>/proposal.md` + `docs/status/archive/<name>/checklist.md`.
5. Start a fresh `docs/status/checklist.md` for the next active milestone/proposal.

Archive on `main` after the final proposal merge unless there is a clear reason to include the archive move in the final
feature PR. This keeps proposal completion explicit and avoids guessing which sub-branch is truly last.

## End-Of-Session Routine

1. Tick completed checklist items only when their assertion is satisfied.
2. Add one compact change-log entry with verification.
3. Promote only durable lessons from `.forge/memory/suggested_impl_notes.md` into `impl_notes.md`.
4. Leave transient status in the checklist, not in implementation notes.

## Size Checks

Use these when a living status doc starts to feel bulky:

```bash
wc -l docs/status/*.md
./scripts/count-tokens.py --model <agent-model> docs/status/change_log.md
./scripts/count-tokens.py --model <agent-model> docs/status/impl_notes.md
./scripts/count-tokens.py --model <agent-model> docs/status/checklist.md
```
