# Work Board Contract

Authoritative contract for maintaining `docs/board/`.

`docs/board/README.md` is a directory guide with examples. This file defines the workflow semantics. When the two
disagree, update the README to match this contract.

## Purpose

The work board is Forge's lightweight implementation-memory system for multi-session work. It separates:

- proposed ideas
- accepted but parked work
- active execution
- active epic coordination and sequencing
- paused partially-done work
- completed snapshots
- project lifetime memory

Cards may be aspirational. Design docs are normative and describe shipped code.

## Lanes

| Path                                 | Meaning                                                             | Required action                                              |
| ------------------------------------ | ------------------------------------------------------------------- | ------------------------------------------------------------ |
| `docs/board/proposed/<slug>/card.md` | Idea, design sketch, or epic not yet accepted for execution         | Move to `todo/` when accepted or scheduled                   |
| `docs/board/todo/<slug>/card.md`     | Accepted work or epic parked until an execution/coordination branch | Move to `doing/` when active work starts                     |
| `docs/board/doing/<slug>/card.md`    | Work currently in flight, or an active coordinating epic            | Keep `checklist.md` current during execution or coordination |
| `docs/board/paused/<slug>/card.md`   | Partially-done work on hold                                         | Move back to `doing/` when work resumes                      |
| `docs/board/done/<slug>/card.md`     | Completed work snapshot                                             | Keep paired `checklist.md` when one existed                  |

`todo/` is not the active cursor. It means the work is accepted, but no execution branch is active for it.

`paused/` is for partially-done work that is temporarily on hold. Unlike `todo/`, a paused card already has a
`checklist.md` with progress. Move back to `doing/` when work resumes; the checklist picks up where it left off.

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

## Epics

An epic is a coordinating card for several independently shippable member cards. It owns the shared contract,
sequencing, and drift control between the members; the member cards remain the implementation units.

Create an epic when two or more independently shippable cards share a contract, sequencing decision, or code seam that
would otherwise drift through plain cross-links.

Epic directory slugs must start with `epic_`, for example `docs/board/doing/epic_telemetry_architecture/`. The top of
the epic card should identify it as an epic, and each member card must link its epic near the top of `card.md` using the
epic's current board path.

Epic lane semantics mirror ordinary card lanes with one addition: an epic moves to `doing/` when its coordination is the
active cursor, or when a member card is active/paused specifically because the epic is deciding sequencing. Active epics
must carry a lightweight `checklist.md` for coordination tasks such as member review, dependency decisions, link
updates, and sequencing outcomes. They do not replace member checklists.

If implementation on a member card stops so the team can revisit the epic or sibling cards, move that member card to
`paused/` and record the pause reason in its checklist. When the epic chooses the next member to execute, move that
member to `doing/` and update both sides of the link.

An epic closes to `done/` when every live member card is `done/`, or when the shared contract is no longer load-bearing
because the work was cancelled, superseded, or folded into normative design docs. Until then, keep the epic in `doing/`
as the living coordinator.

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
| Stop hook enqueues memory-writer work | project memory enabled, session silent | handoff marker exists | `tests/src/cli/test_artifact_hooks.py` |
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

| File                                 | Role                                         | Maintenance contract                                                                         |
| ------------------------------------ | -------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `docs/board/change_log.md`           | Completed-work record                        | Newest first, compact, includes goal/key changes/verification                                |
| `docs/board/impl_notes.md`           | Human-approved durable implementation memory | Promote only stable decisions, invariants, recurring bug causes, and operational constraints |
| `.forge/memory/shadow_impl_notes.md` | Shadow proposals for `impl_notes.md`         | Memory writer may append; humans review and promote                                          |

Card checklists are edited directly during implementation. Do not track card checklists as memory-writer memory docs.

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

**Verification**: Focused test suite passes; `make pre-commit` clean.
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
6. Repoint inbound board links to the card's new lane path: any card or checklist that links the moved card must use its
   new lane path, and no broken relative link may remain (a lane move breaks every inbound `../<lane>/<slug>/...` link
   that pointed at the old lane).

If the card is merged before the lane move, perform the move immediately after the final merge to `main`.

## Size Checks

Run these when living board docs start to feel bulky:

```bash
wc -l docs/board/*.md docs/board/*/*/*.md
./scripts/count-tokens.py docs/board/change_log.md
./scripts/count-tokens.py docs/board/impl_notes.md
./scripts/count-tokens.py docs/board/doing/<slug>/checklist.md
```

Compact `change_log.md` by summarizing the oldest tail entries first. Preserve dates, goals, decisions, verification,
and deferred items.

Prune obsolete or duplicated `impl_notes.md` entries instead of appending forever. If a note is not useful for a future
session's decisions, it belongs in the change log or nowhere.
