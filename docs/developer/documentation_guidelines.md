# Documentation Guidelines

Documentation writing and maintenance standards for Multi-Forge.

This file explains how to write and maintain docs. The board workflow itself is defined in
[`board_contract.md`](board_contract.md).

---

## Authority Map

Use one authoritative source per domain:

| Domain                                        | Authority                                                                  |
| --------------------------------------------- | -------------------------------------------------------------------------- |
| Repository overview                           | `README.md`                                                                |
| Shipped architecture and ownership            | `docs/design.md`, its domain design documents, and `docs/cli_reference.md` |
| Documentation writing and maintenance         | This file                                                                  |
| Work-board lanes, cards, checklists, closeout | `docs/developer/board_contract.md`                                         |
| Coding style and durable-state rules          | `docs/developer/coding_standards.md`                                       |
| CLI command shape and recovery output         | `docs/developer/cli_style_guidelines.md`                                   |
| Test policy                                   | `docs/developer/testing_guidelines.md`                                     |
| User-facing behavior                          | `docs/end-user/*`                                                          |

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

Maintain board files according to [`board_contract.md`](board_contract.md).

### Coding Context Documents

Design docs and agent context files are future-session context. They must be accurate, compact enough to load, and
specific enough for agents to act on without guessing.

Update design docs when architecture, file ownership, config ownership, auth resolution, installer behavior,
proxy/session semantics, workflow prerequisites, or end-user behavior changes.

---

## Design Documents

Design docs are normative architecture docs. This section defines writing expectations; card-execution procedure lives
in [`board_contract.md`](board_contract.md#design-doc-sync).

Route architecture changes to the narrowest authority:

| Document                      | Contract domain                                                   |
| ----------------------------- | ----------------------------------------------------------------- |
| `docs/design.md`              | Core architecture, shared state, file ownership, command-core ops |
| `docs/design_sessions.md`     | Sessions, launch, transfer, hooks, queues, Codex, event journals  |
| `docs/design_runtime.md`      | Proxies, backends, models, routing, shared clients, isolation     |
| `docs/design_telemetry.md`    | Status, spend, audit, usage, and provider lifecycle               |
| `docs/design_installation.md` | Configuration, credentials, extensions, registration, test setup  |
| `docs/design_workflows.md`    | Policy, skills, and workflow runners                              |
| `docs/design_memory.md`       | Designated memory, passports, writers, and activation             |
| `docs/cli_reference.md`       | Terminal and direct-command inventory                             |

Retired contracts that still carry useful removal rationale live in `docs/design_history.md`; they are evidence, not
shipped architecture.

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

| What                          | Where                                         | When to update                             |
| ----------------------------- | --------------------------------------------- | ------------------------------------------ |
| Aspirational proposal         | `docs/board/proposed/<slug>/card.md`          | When drafting or revising a proposal       |
| Accepted/scheduled work       | `docs/board/todo/<slug>/card.md`              | When work is accepted but not active       |
| Active execution plan         | `docs/board/doing/<slug>/checklist.md`        | During active card work                    |
| Paused in-progress work       | `docs/board/paused/<slug>/card.md`            | When partially-done work goes on hold      |
| Completed work                | `docs/board/change_log.md` and its archives   | At phase/card closeout                     |
| Durable implementation memory | `docs/board/impl_notes.md` and domain ledgers | After human review                         |
| Normative architecture        | Design map above and `docs/cli_reference.md`  | As code ships                              |
| End-user behavior             | `docs/end-user/*`                             | When user-facing setup or behavior changes |
| Setup/development workflow    | `docs/developer/*`                            | When maintainer workflow changes           |

The board-specific rules for these files live in [`board_contract.md`](board_contract.md).

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

Agents degrade when docs grow too large. The tracked [`.file-size-limits.json`](../../.file-size-limits.json) owns this
repository's limits and ordered counting methods. The standard pre-commit hook reads that file directly; a personal hook
may supply the executable, but it cannot silently replace repository policy.

Resolution is explicit `--config`, then the current Git root's `.file-size-limits.json`, then the checker's own checkout
fallback. A repository policy therefore wins over any personal fallback regardless of which hook installation invokes
the checker.

Markdown counting is Opus-first, with local tiktoken as an explicitly reported fallback:

```bash
./scripts/count-tokens.py docs/design.md
./scripts/count-tokens.py --local docs/design.md
./scripts/check-file-limits.py --dry-run docs/design.md
```

The default command reports both the method and tokenizer family that produced the count. The checker batches a local
pass and probes the provider only after a file reaches its configured local threshold. Each result is compared only with
the threshold for its own tokenizer family; human-readable method wording is never parsed as policy. Multi-Forge's
12,000-token local target and 15,000-token local ceiling are deliberately conservative against the measured near-2x
Opus/tiktoken worst case, so an unavailable provider cannot apply an Opus-denominated number to a local count or
silently approve a near-limit file.

Repository policy:

- Living Markdown targets at most 25,000 Opus tokens and fails above 30,000.
- Newly partitioned design documents should leave additional room and target at most 23,000 Opus tokens.
- Closed card snapshots have a ratified 40,000-token exception because shortening historical evidence would be lossy.
- Avoid files longer than 2,500 lines; many readers and tools truncate before then.
- Partition by domain or archive complete historical blocks before raising a limit. Change a limit only through an
  explicit edit to the tracked policy.

Claude Code's `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS` controls one reader's output, not repository document size, and
Codex has no corresponding repository policy surface used here. Neither setting overrides this gate.

---

## Living Doc Maintenance

For board living-doc size checks and compaction rules, use [`board_contract.md`](board_contract.md#size-checks).
