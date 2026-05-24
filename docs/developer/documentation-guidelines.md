# Documentation Guidelines

Documentation standards for Multi-Forge.

---

## Living vs Static Documents

### Living Documents (update regularly)

- **Implementation checklists** - Current tasks
- **Change logs** - Completed work record
- **Evaluation results** - Update after evals/tests

### Status Docs (`docs/status/`)

`docs/status/` is the living implementation-memory surface for active multi-session work. See
[`docs/status/README.md`](../status/README.md) for the current repo-specific contract.

| File                        | Purpose                                      | Maintenance rule                                                                             |
| --------------------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `docs/status/checklist.md`  | One active milestone/proposal execution plan | Update during sessions; archive when the proposal is fully executed                          |
| `docs/status/change_log.md` | Completed-work record                        | Keep compact; newest first; compact old tail entries before the file grows too large         |
| `docs/status/impl_notes.md` | Human-approved durable memory                | Promote only stable decisions, invariants, recurring bug causes, and operational constraints |
| `docs/status/archive/`      | Completed proposal + checklist archives      | Store final proposal/checklist snapshots as `<name>/proposal.md` + `<name>/checklist.md`     |

Checklist files are per milestone/proposal, not permanent catch-all plans. When a checklist is complete, add the final
change-log entry, promote durable notes, then archive on `main` after the final proposal merge unless the final feature
PR is explicitly the closeout. Copy final proposal and checklist snapshots to `docs/status/archive/`, then start a fresh
active checklist.

### Coding Context Documents

- **Design docs** - Aggregated coding reference
  - Architecture context
  - Consolidates key contracts, file locations, patterns
  - **Maintenance Rule**: Update FIRST on refactors/moves
  - Must stay accurate; it's future-session context

### Proposals (`docs/proposals/`)

- Forward-looking design sketches for features not yet implemented or scheduled
- May reference aspirational architecture, upstream capabilities, or research prototypes
- No update cadence — refresh when the topic becomes active work
- When a proposal becomes active, it drives a checklist; when execution completes, both are archived together

### Proposal Lifecycle

Proposals drive the implementation cycle. The full lifecycle:

```text
1. Propose  — write docs/proposals/<name>.md (aspirational design)
2. Activate — create docs/status/checklist.md from the proposal
3. Execute  — implement per-phase; update design docs per-phase as code ships
4. Archive  — copy final proposal + checklist snapshots to docs/status/archive/<name>/
```

**Design doc updates during execution.** Proposals are aspirational; design docs are normative (describe shipped code).
During proposal execution, each checklist phase that changes normative architecture should include a design-doc update
task. Design docs should reflect what's built, not the proposal's target state. A mid-proposal design doc may describe a
hybrid state (old + new) — that's accurate and preferred over aspirational docs describing unbuilt features.

**Archival.** When a proposal is fully executed, archive both the proposal and its checklist together under
`docs/status/archive/<name>/` (with `proposal.md` and `checklist.md`). The source proposal may remain in
`docs/proposals/` for discoverability, but the archived copy freezes the completed proposal state. After archival,
design docs are the normative source; the archived proposal is historical context.

### Design Documents (normative architecture)

- Describe **shipped system** (what's built and how it works)
- Must stay accurate — updated per-phase during proposal execution, not after
- When a proposal changes architecture, the relevant design doc sections are updated as each phase ships
- If design docs fall behind shipped code, track the gap as explicit checklist debt

---

## Documentation Rules

**Rule 1**: Proposals = aspirational design; checklist = active execution plan; change log = completed work;
implementation notes = human-approved durable memory; design docs = normative shipped architecture; AutoMem = evolving
state

**Rule 2**: Verbosity has a cost; balance with clarity and intent.

**Rule 3**: Design-doc code blocks show the **gist**, not full implementations:

- Show signatures + key logic flow
- Use `...` for obvious details
- Prefer terse one-liners over long comments
- Link to full specs
- Goal: convey architecture, not copy-paste code

---

## Where to Document What

| What                          | Where                         | When to Update                                           |
| ----------------------------- | ----------------------------- | -------------------------------------------------------- |
| Aspirational design           | `docs/proposals/`             | Refresh when topic becomes active; archive when complete |
| Active execution plan         | `docs/status/checklist.md`    | During active milestone/proposal work                    |
| Completed work                | `docs/status/change_log.md`   | At session/phase closeout                                |
| Durable implementation memory | `docs/status/impl_notes.md`   | After human review                                       |
| Normative architecture        | Design docs                   | Per-phase as code ships during proposal execution        |
| Archived proposals+checklists | `docs/status/archive/<name>/` | After proposal is fully executed                         |
| Current metrics               | AutoMem                       | On evolving facts                                        |

---

## Checklist Policy

### TDD-First Acceptance Criteria

Each phase SHOULD define acceptance criteria:

1. **Testable**: Verified by a specific test
2. **Measurable**: Numeric thresholds or boolean outcomes
3. **Fixture-grounded**: References fixtures when relevant

**Acceptance test table**:

```markdown
| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Policy blocks write | git_repo | PreToolUse returns deny | `test_guard.py` |
| Stop hook fast | mock | Execution < 100ms | `test_stop_hook.py` |
```

**Anti-patterns**:

| Avoid                  | Instead                                                 |
| ---------------------- | ------------------------------------------------------- |
| "Hook works correctly" | "Stop hook completes in \<100ms with transcript copied" |
| "Tests pass"           | "58 guard tests pass; mypy clean"                       |

### Checklist Lifecycle

1. **Start**: Create checklist from proposal with `[ ]` + acceptance test tables
2. **During**: Update checkboxes; note blockers; update design docs per-phase as code ships
3. **Complete**: Move completed-work details to `change_log`; promote durable memory to `impl_notes`; verify design docs
   reflect all shipped changes; archive both proposal and checklist under `docs/status/archive/<name>/` after the final
   merge to `main`; create the next active checklist

---

## Change Log Policy

### Entry Structure (Required)

Each entry MUST include:

1. **Goal** (1 sentence): Objective
2. **Key Changes** (bullets): Added/modified/deleted
3. **Verification** (1 line): How validated

Each entry MAY include (when relevant):

- **Design decisions**: Key choices + rationale
- **Files created/modified**: Only for major refactors (>10 files) — summarize by package
- **Deferred items**: Explicitly not done

### Entry Format

```markdown
## YYYY-MM-DD

### Phase X.Y: Short Title

**Goal**: One sentence describing the objective.

**Key changes**:

- Bullets: WHAT changed (code shows HOW)
- New files
- Key decisions

**Verification**: How validated (e.g., "58 tests pass; mypy clean")

**Deferred**: Items postponed (optional)
```

### Detail Level Guidelines

| Entry Type            | Target Lines | Content                                    |
| --------------------- | ------------ | ------------------------------------------ |
| Bug fix               | 5-10         | Goal + fix + verification                  |
| Feature completion    | 15-25        | Goal + key changes + tests added           |
| Phase completion      | 25-40        | Goal + major changes + acceptance criteria |
| Architecture refactor | 40-60 max    | Include package summaries, migration notes |

**Consistency matters**: Similar work should have similar detail. If one bug fix is 5 lines, another shouldn't be 50.

**Anti-pattern**: Listing every file modified. If >10 files, summarize by package (e.g., "Updated 14 files in
`src/guard/` and `tests/src/guard/`").

**Rule of thumb**: If it can't be summarized in 40 lines, it's too detailed. Code is HOW; docs are WHAT/WHY.

---

## Writing Style

Docs are read by humans and AI agents; be direct and specific.

### Principles

1. **Say the thing.** Say it once; no preambles, repetition, or summaries.
2. **Specifics over gestures.** "Improves performance" is vague; "p99 200ms→45ms" isn't. If you don't have the number,
   say so.
3. **Earn every sentence.** If it doesn't add new info, merge or cut.
4. **Plain language wins.** "Use" not "utilize." Prefer plain meaning over fancy synonyms.
5. **Structure follows content.** Bullets for parallel items. Prose for arguments. Tables for comparisons.

### Vocabulary Hygiene

Avoid AI filler words:

- **Always cut**: delve, tapestry, vibrant, myriad, plethora, utilize, unlock, groundbreaking, revolutionary,
  transformative
- **Check context**: robust (ML/stats), seamless (failover), leverage (existing infra), comprehensive (test suite)
- **Replace metaphors with specifics**: name the work/scale/practice/criteria

### Structural Tells to Avoid

- Every section opening with "X is a Y that Z" (definition → elaboration)
- Opening paragraphs that restate the heading (echo effect)
- Uniform paragraph/section lengths — vary with importance
- Summary paragraphs on short documents — the reader remembers
- "Furthermore," / "Moreover," / "Additionally," as paragraph openers (filler transitions)

### When Writing for AI Consumption

CLAUDE.md files and design docs are AI context. Write for machine parsability too:

- **Be specific over general.** "Run `uv run pytest tests/src -v`" beats "run the tests."
- **State constraints, not aspirations.** "Never skip tests" beats "we value testing". Include must-NOT constraints.
- **Frontload actionable content.** Put important rules first.
- **Use exact identifiers.** Say `forge session start`, not "the session command." Avoid "it"/"this" when ambiguous.
- **Tag code blocks with language.** Agents parse tagged blocks more reliably.
- **Keep files within context limits.** A 25K-token doc degrades performance; split or archive.

---

## Size Limits

### Maximum Document Size (Hard Limits)

Agents: ~25k tokens; Read truncates >2k lines. Keep docs under these limits; use
[count-tokens.py](../../scripts/count-tokens.py) with `--model` matching the coding agent's model for accurate counts
(the agent knows its own model ID):

```bash
./scripts/count-tokens.py --model claude-sonnet-4-6 docs/design.md
25,677 tokens | 99,378 chars | 1,924 lines
  method: anthropic API (claude-sonnet-4-6)
```

### Living Doc Maintenance

Run token/line checks before living docs become hard to load:

```bash
wc -l docs/status/*.md
./scripts/count-tokens.py --model <agent-model> docs/status/change_log.md
```

For `docs/status/change_log.md`, compact the oldest tail entries first. Preserve dates, goals, decisions, verification,
and deferred items; remove verbose blow-by-blow details. If compaction is still not enough, move old detailed sections
to an archive file and leave a dated summary in the active change log.

For `docs/status/impl_notes.md`, prune obsolete or duplicated notes instead of appending forever. If a note is not
useful for a future session's decisions, it probably belongs in the change log or nowhere.
