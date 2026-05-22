# Status Docs

This directory holds living implementation context for Forge.

## Files

| File            | Role                                      | Update path                                                                |
| --------------- | ----------------------------------------- | -------------------------------------------------------------------------- |
| `change_log.md` | Completed-work record                     | Handoff agent may update with `strategy=changelog`; humans keep it compact |
| `impl_notes.md` | Approved memory for future sessions       | Human-approved only; handoff agent proposes to a shadow doc                |
| `checklist.md`  | Current milestone/proposal execution plan | Manual living checklist updated during and at the end of coding sessions   |
| `archive/`      | Completed milestone/proposal checklists   | Move finished checklists here after the proposal is fully executed         |

## Handoff Agent Setup

Seed the shadow doc before adding it to a session:

```bash
mkdir -p .forge/memory
touch .forge/memory/suggested_impl_notes.md
```

For the first run, use `review-only` if you want to inspect the handoff agent's proposed output before allowing writes:

```bash
forge session set memory.auto_update.enabled true
forge session set memory.auto_update.mode review-only
forge session memory add-doc docs/status/change_log.md --strategy changelog
forge session memory add-doc .forge/memory/suggested_impl_notes.md \
  --strategy suggested \
  --shadows docs/status/impl_notes.md
forge session memory list-docs --json
```

After the first review-only run completes, inspect the agent's proposed output:

```bash
forge session handoff show --latest
```

If the report looks good, switch to the normal augment mode:

```bash
forge session set memory.auto_update.mode augment
```

For established sessions, configure augment mode explicitly:

```bash
forge session set memory.auto_update.enabled true
forge session set memory.auto_update.mode augment
forge session memory add-doc docs/status/change_log.md --strategy changelog
forge session memory add-doc .forge/memory/suggested_impl_notes.md \
  --strategy suggested \
  --shadows docs/status/impl_notes.md
forge session memory list-docs --json
```

`forge session memory add-doc` is not idempotent. If re-running setup, check `forge session memory list-docs --json`
first, or run `forge session memory remove-doc <path>` before adding the same path again.

Keep `docs/status/checklist.md` manual until the runtime-abstraction plan stabilizes. If it becomes useful to let the
handoff agent mark checklist items at Stop time, add it explicitly:

```bash
forge session memory add-doc docs/status/checklist.md --strategy checklist
```

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
3. After the final merge to `main`, move the completed checklist to `docs/status/archive/<proposal-or-milestone>.md`.
4. Start a fresh `docs/status/checklist.md` for the next active milestone/proposal.

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
