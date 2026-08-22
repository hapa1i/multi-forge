# Repository-Owned Context Limits

**Lane**: `done/`

## Goal

Make Multi-Forge's context-file limits visible and enforceable from the repository, count near-limit Markdown with
Claude Opus 5, and split oversized living documents without losing their contracts or historical evidence.

## Decisions

- The tracked root `.file-size-limits.json` is the repository authority; `.worktreeinclude` is unrelated because tracked
  policy already follows worktrees.
- Markdown targets 25,000 Opus tokens and fails above 30,000. Newly split design documents land at or below 23,000.
- The two already-closed oversized checklists use a 40,000-token historical-snapshot exception.
- `design.md` and the former consolidated design appendix become one core document plus four domain documents. The
  retired appendix path is deleted and all inbound links are rewritten.
- Migration is semantically lossless. Unique requirements, schemas, examples, caveats, rationale, and failure semantics
  must remain; exact duplicates may be integrated into a named canonical passage.
- Bare `scripts/count-tokens.py` becomes Opus-first with a local fallback. Results identify both the method and
  tokenizer family that ran, and the repository policy supplies thresholds for every reachable family.

## Acceptance

1. The repository owns and documents its file-size policy, and standard pre-commit execution enforces it.
2. Provider counting is explicit in repository config; fallback results cannot silently decide a near-limit file.
3. Five canonical shipped-design documents contain all active content formerly owned by `design.md` and the consolidated
   appendix; the removed WorkflowPolicy record remains verbatim in architecture history, with no reference to the
   retired path.
4. `design_workflows.md`, living board memory, and the combined review ledger are below their limits after lossless
   partitioning.
5. Every local Markdown path and fragment resolves, and the migration checklist maps every original design heading.
6. All living/context documents are below 25,000 Opus tokens; migrated canonical design documents are at or below
   23,000; only the ratified done-card exception may exceed 30,000.

## Non-goals

- Do not change Claude Code's `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS` or add a Codex project output limit.
- Do not change Forge runtime behavior.
- Do not rewrite historical evidence for brevity.
