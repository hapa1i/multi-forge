# Documentation Guidelines

Documentation writing and maintenance standards for Multi-Forge.

This file explains how to write and maintain docs. The board workflow itself is defined in
[`board-contract.md`](board-contract.md).

---

## Authority Map

Use one authoritative source per domain:

| Domain                                        | Authority                                                                                        |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Repository overview                           | `README.md`                                                                                      |
| Shipped architecture and ownership            | `docs/design.md`, `docs/design_appendix.md`, `docs/design_workflows.md`, `docs/cli_reference.md` |
| Documentation writing and maintenance         | This file                                                                                        |
| Work-board lanes, cards, checklists, closeout | `docs/developer/board-contract.md`                                                               |
| Coding style and durable-state rules          | `docs/developer/coding-standards.md`                                                             |
| Test policy                                   | `docs/developer/testing-guidelines.md`                                                           |
| User-facing behavior                          | `docs/end-user/*`                                                                                |

`docs/board/README.md` is a directory guide with examples. It is not the normative board contract.

---

## Living vs Static Documents

### Living Documents

Living docs change as work happens:

- active card checklists
- `docs/board/change_log.md`
- `docs/board/impl_notes.md`
- evaluation and manual-test results
- design docs when shipped architecture changes

Maintain board files according to [`board-contract.md`](board-contract.md).

### Coding Context Documents

Design docs and agent context files are future-session context. They must be accurate, compact enough to load, and
specific enough for agents to act on without guessing.

Update design docs when architecture, file ownership, config ownership, auth resolution, installer behavior,
proxy/session semantics, workflow prerequisites, or end-user behavior changes.

---

## Design Documents

Design docs are normative architecture docs. This section defines writing expectations; card-execution procedure lives
in [`board-contract.md` Design Doc Sync](board-contract.md#design-doc-sync).

- Describe shipped behavior, not desired future behavior.
- If a card is mid-execution, document the hybrid shipped state accurately.

Design-doc code blocks should show the gist, not full implementations:

- Show signatures and key logic flow.
- Use `...` for obvious detail.
- Prefer terse examples over long comments.
- Link to full specs or implementation files when precision matters.

Cards may contain aspirational target architecture. Design docs should not.

---

## Where To Document What

| What                          | Where                                                                                            | When to update                             |
| ----------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| Aspirational proposal         | `docs/board/proposed/<slug>/card.md`                                                             | When drafting or revising a proposal       |
| Accepted/scheduled work       | `docs/board/todo/<slug>/card.md`                                                                 | When work is accepted but not active       |
| Active execution plan         | `docs/board/doing/<slug>/checklist.md`                                                           | During active card work                    |
| Paused in-progress work       | `docs/board/paused/<slug>/card.md`                                                               | When partially-done work goes on hold      |
| Completed work                | `docs/board/change_log.md`                                                                       | At phase/card closeout                     |
| Durable implementation memory | `docs/board/impl_notes.md`                                                                       | After human review                         |
| Normative architecture        | `docs/design.md`, `docs/design_appendix.md`, `docs/design_workflows.md`, `docs/cli_reference.md` | As code ships                              |
| End-user behavior             | `docs/end-user/*`                                                                                | When user-facing setup or behavior changes |
| Setup/development workflow    | `docs/developer/*`                                                                               | When maintainer workflow changes           |

The board-specific rules for these files live in [`board-contract.md`](board-contract.md).

---

## Documentation Rules

**Rule 1: One authority per topic.** Link to the authority instead of copying its rules into another doc.

**Rule 2: Cards are context; design docs are contract.** Cards may point forward. Design docs must describe the shipped
system.

**Rule 3: Verbosity has a cost.** Prefer concise, specific docs over exhaustive narration.

**Rule 4: Code is how; docs are what and why.** Avoid listing every file or implementation detail unless the file list
is itself the point.

**Rule 5: Update docs with the change.** Do not leave "docs later" as invisible debt; put it in the checklist if it
cannot happen in the same patch.

---

## Writing Style

Docs are read by humans and AI agents. Be direct and specific.

### Principles

1. **Say the thing.** Say it once; no preambles, repetition, or summary paragraphs on short docs.
2. **Specifics over gestures.** "p99 200ms -> 45ms" beats "improves performance."
3. **Earn every sentence.** If it does not add new information, merge or cut it.
4. **Plain language wins.** Use "use" instead of "utilize."
5. **Structure follows content.** Use bullets for parallel items, prose for arguments, and tables for comparisons.

### Tables

In agent-loaded, design, developer, and board docs, use tables for compact enumerable facts, not prose. Keep cells to
short labels, values, or phrases. If a cell needs a full sentence, examples, caveats, or multiple clauses, use bold-term
bullets or prose below the table instead.

End-user docs may keep wider tables when they are easier to scan in rendered form, especially for command, setting,
credential, and comparison references. Prefer the structure that helps a human answer the question fastest.

### Vocabulary Hygiene

Avoid AI filler words:

- Always cut: delve, tapestry, vibrant, myriad, plethora, utilize, unlock, groundbreaking, revolutionary,
  transformative.
- Check context: robust, seamless, leverage, comprehensive.
- Replace metaphors with concrete names for the work, scale, practice, or criteria.

### Structural Tells To Avoid

- Every section opening with "X is a Y that Z."
- Opening paragraphs that restate the heading.
- Uniform paragraph and section lengths.
- Summary paragraphs on short documents.
- "Furthermore," "Moreover," and "Additionally," as paragraph openers.

---

## Writing For AI Consumption

`CLAUDE.md`, `AGENTS.md`, design docs, and board checklists are AI context. Make them easy to parse:

- Frontload actionable constraints.
- Use exact identifiers, paths, commands, and file names.
- State must/must-not constraints instead of aspirations.
- Prefer `uv run pytest tests/src/foo.py` over "run tests."
- Avoid ambiguous pronouns when a command or file path is available.
- Tag fenced code blocks with a language.
- Keep files under context limits; split or archive bulky docs.

---

## Size Limits

Agents degrade when docs grow too large. Use [`scripts/count-tokens.py`](../../scripts/count-tokens.py) with the
relevant model:

```bash
./scripts/count-tokens.py --model claude-sonnet-4-6 docs/design.md
```

Hard guidance:

- Keep individual agent/context docs below roughly 25k tokens.
- Avoid files longer than 2k lines; many readers and tools truncate around there.
- Split reference details into appendix files when the main doc becomes slow to scan.

---

## Living Doc Maintenance

For board living-doc size checks and compaction rules, use [`board-contract.md`](board-contract.md#size-checks).
