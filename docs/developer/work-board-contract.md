# Work Board Contract

Authoritative contract for maintaining `docs/board/`.

`docs/board/README.md` is a directory guide with examples. This file defines the workflow semantics. When the two
disagree, update the README to match this contract.

## Purpose

The work board is Forge's lightweight implementation-memory system for multi-session work. It separates:

- proposed ideas
- accepted but parked work
- active execution
- completed snapshots
- project lifetime memory

Cards may be aspirational. Design docs are normative and describe shipped code.

## Lanes

| Path                                 | Meaning                                               | Required action                                   |
| ------------------------------------ | ----------------------------------------------------- | ------------------------------------------------- |
| `docs/board/proposed/<slug>/card.md` | Idea or design sketch not yet accepted for execution  | Move to `todo/` when accepted or scheduled        |
| `docs/board/todo/<slug>/card.md`     | Accepted work parked until an execution branch exists | Move to `doing/` when execution starts            |
| `docs/board/doing/<slug>/card.md`    | Work currently in flight                              | Keep `checklist.md` current during implementation |
| `docs/board/done/<slug>/card.md`     | Completed work snapshot                               | Keep paired `checklist.md` when one existed       |

`todo/` is not the active cursor. It means the work is accepted, but no execution branch is active for it.

When the user says to work on a `todo/` card, the operating contract is:

1. Create or switch to the execution branch for that card.
2. Move the card directory from `todo/<slug>/` to `doing/<slug>/`.
3. Create or update `doing/<slug>/checklist.md`.
4. Start implementation from the checklist, updating it as assertions are satisfied.

Use `git mv` for lane moves when possible so history stays readable.

## Cards

Every work item is a card directory.

- `card.md`: durable problem framing, motivation, design context, risks, and open questions.
- `checklist.md`: active execution plan for the branch/session.

Move cards between lanes instead of copying proposal/checklist snapshots. A completed `done/<slug>/` card is historical
context; after completion, design docs and code are normative.

## Checklist Contract

Add `checklist.md` when a card needs an execution plan.

Each active checklist should include:

- current focus
- phases or slices
- concrete assertions for each task
- acceptance test table for risky or multi-file changes
- blockers or deferred decisions inline under the relevant phase
- closeout items

Tick a checkbox only when its assertion is satisfied and verification is recorded. Do not tick items merely because work
started or because intent is clear.

Acceptance tables should be fixture-grounded:

```markdown
| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Stop hook enqueues handoff | project memory enabled, session silent | handoff marker exists | `tests/src/cli/test_artifact_hooks.py` |
```

Avoid vague assertions like "works correctly." Name the observable behavior.

## Design Doc Sync

Design docs are normative architecture. Cards can describe target architecture, but design docs must describe shipped
behavior.

During card execution:

- Add design-doc update tasks to any phase that changes architecture, file ownership, CLI contracts, config ownership,
  auth resolution, installer behavior, proxy/session semantics, workflow prerequisites, or user-facing docs.
- Update design docs per phase as code ships.
- If design docs fall behind shipped code, record explicit checklist debt.
- Update relevant `docs/end-user/*` guides when wheel-installed users need different Day 1 behavior.

## Board Memory Files

| File                                    | Role                                         | Maintenance contract                                                                         |
| --------------------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `docs/board/change_log.md`              | Completed-work record                        | Newest first, compact, includes goal/key changes/verification                                |
| `docs/board/impl_notes.md`              | Human-approved durable implementation memory | Promote only stable decisions, invariants, recurring bug causes, and operational constraints |
| `.forge/memory/suggested_impl_notes.md` | Shadow proposals for `impl_notes.md`         | Handoff agent may append; humans review and promote                                          |

Card checklists are edited directly during implementation. Do not track card checklists as handoff-agent memory docs.

## Change Log Policy

Add entries for completed work only. Pending tasks belong in the active checklist.

Each entry must include:

1. **Goal**: one sentence objective.
2. **Key changes**: compact bullets describing what changed.
3. **Verification**: tests, checks, or manual verification performed.

Use newest-first order:

```markdown
## YYYY-MM-DD

### Phase X.Y: Short Title

**Goal**: One sentence describing the objective.

**Key changes**:

- What changed and why it matters.

**Verification**: Focused test suite passes; `make type-check` clean.
```

Keep entries proportional:

| Entry type            | Target size     |
| --------------------- | --------------- |
| Bug fix               | 5-10 lines      |
| Feature completion    | 15-25 lines     |
| Phase completion      | 25-40 lines     |
| Architecture refactor | 40-60 lines max |

If more than 10 files changed, summarize by package instead of listing every file.

## Implementation Notes Policy

`impl_notes.md` is not a session diary. It stores durable memory that should influence future decisions.

Promote only:

- stable architecture decisions and rationale
- non-obvious invariants, ownership boundaries, and path/state rules
- recurring bug causes, fixes, and test patterns
- operational constraints future sessions must remember

Do not promote:

- raw session summaries
- pending tasks
- unverified hunches
- duplicates of the change log
- transient implementation status

## Closeout

When a card is fully executed:

1. Tick or close final checklist items with verification.
2. Add a compact final entry to `docs/board/change_log.md`.
3. Promote durable lessons to `docs/board/impl_notes.md` after human review.
4. Verify relevant design docs and end-user docs reflect shipped behavior.
5. Move the card directory from `doing/<slug>/` to `done/<slug>/`.

If the card is merged before the lane move, perform the move immediately after the final merge to `main`.

## Size Checks

Run these when living board docs start to feel bulky:

```bash
wc -l docs/board/*.md docs/board/*/*/*.md
./scripts/count-tokens.py --model <agent-model> docs/board/change_log.md
./scripts/count-tokens.py --model <agent-model> docs/board/impl_notes.md
./scripts/count-tokens.py --model <agent-model> docs/board/doing/<slug>/checklist.md
```

Compact `change_log.md` by summarizing the oldest tail entries first. Preserve dates, goals, decisions, verification,
and deferred items.

Prune obsolete or duplicated `impl_notes.md` entries instead of appending forever. If a note is not useful for a future
session's decisions, it belongs in the change log or nowhere.
