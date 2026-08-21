---
description: Audit and clean source-code comments or docstrings without changing executable behavior or inventing intent.
argument-hint: '[target: file, directory, or repository] [--check | --apply]'
allowed-tools: Read, Grep, Glob, Bash, Edit
---

<!-- Keep in sync with .agents/skills/comment-cleanup/SKILL.md (same body; runtime-specific frontmatter and invocation
wording differ). -->

# Comment Cleanup

Audit and improve source-code comments and docstrings without changing executable behavior or inventing author intent.

The goal is useful, accurate, maintainable commentary -- not disguising AI authorship or making prose sound casually
human. A comment is not defective merely because it is grammatical, formal, detailed, or AI-assisted.

## Target and Mode

Read `$ARGUMENTS` as the task input. Strip an optional leading `@` from a file reference, then resolve the target from
the remaining path or instruction. If no target is supplied, use the current working directory.

Choose the mode in this order:

1. Honor an explicit `--check` or `--apply`.
2. Use apply mode when the user explicitly asks to clean, fix, remove, rewrite, or optimize comments.
3. Otherwise use check mode. This includes a bare slash-command invocation or one that supplies only a target, as well
   as requests to inspect, assess, explain, or review comments.

`--check` audits and reports without editing. `--apply` makes high-confidence comment changes. If both flags are
present, or the target does not exist, stop with a concise diagnostic. Do not silently expand a file target to its
parent directory.

## Establish the Local Contract

Before judging comments:

1. Read the applicable repository instructions and language or documentation style guides.
2. Inspect nearby comments to learn the project's terminology, tone, formatting, and expected documentation level.
3. Inspect version-control status and existing diffs. Preserve unrelated user changes.
4. Build the candidate file set:
   - For a file target, inspect exactly that file.
   - In a Git repository, prefer tracked files within the target and include relevant untracked source files without
     traversing ignored directories.
   - Outside Git, use the runtime's file search while honoring ignore files where possible.
   - Exclude dependencies, vendor trees, build output, lock files, minified assets, binary files, and files explicitly
     marked as generated. Report material exclusions.

Focus on source files and code-bearing configuration or templates. Do not turn this into a general prose or design-doc
edit. For a large target, use comment markers and language-aware searches to triage candidates, but inspect each edit in
its syntactic context; never perform blind regular-expression replacement across files.

## Classify Comments by Function

Classify before editing. When a comment spans categories, preserve its useful information.

**Protected commentary -- preserve unless the user explicitly requests otherwise:**

- Copyright, license, attribution, provenance, and generated-file notices
- Shebangs, encoding declarations, compiler directives, pragmas, and tool instructions
- Linter, formatter, type-checker, coverage, security-scanner, and test-runner suppressions
- Documentation-tool syntax whose structure has semantic meaning
- Security, safety, compatibility, concurrency, and data-loss warnings
- Algorithm citations, standards references, and links that establish provenance
- Traceable TODO/FIXME comments that record real unfinished work

**Keep:** commentary that adds information a maintainer cannot recover cheaply from names, types, and control flow, such
as rationale, tradeoffs, invariants, external constraints, business rules, surprising failure modes, or caller-visible
contracts.

**Rewrite:** commentary whose underlying information is useful but which is stale, ambiguous, duplicated, excessively
wordy, misplaced, or inconsistent with established local terminology.

**Remove:** commentary that only narrates syntax, repeats a nearby name or signature, makes generic claims such as
"ensure robustness" without naming a mechanism, duplicates another comment without adding information, leaves empty
section headings, contains assistant-response residue, or is commented-out code or an inert debugging leftover whose
history is already preserved by version control and whose surrounding context gives no reason to retain it.

**Needs human context:** commentary that conflicts with code while the intended behavior cannot be established from
tests, specifications, issues, history, or surrounding implementation; commented-out code that appears deliberately
retained as reference material or a fallback but has no documented purpose; and TODO/FIXME comments with no traceable
issue, owner, or concrete remaining work. Do not guess which side is correct or invent missing issue references.

Do not label a comment as AI-generated. Authorship cannot be established reliably from prose style alone.

## Apply the Readability Test

Evaluate each candidate against all of these questions:

1. **Accurate:** Does it describe the current code and use current identifiers?
2. **Additive:** Does it provide information not already obvious from the code?
3. **Specific:** Does it name the actual constraint, consequence, invariant, or special case?
4. **Appropriate:** Is this the right comment type, audience, and location?
5. **Durable:** Is it about a stable contract or rationale rather than incidental implementation detail?
6. **Local:** Does it preserve the repository's terminology and formatting conventions?

For explanatory comments and docstrings, apply an **ASD-STE100-inspired** clarity pass:

- Keep one idea per sentence.
- Use short, direct sentences.
- Use active voice when the agent is known; do not invent an agent only to avoid passive voice.
- Use one consistent term for each concept.
- Prefer explicit nouns over ambiguous pronouns.

This is a selected readability profile, not formal ASD-STE100 compliance. Technical accuracy, code identifiers, project
terminology, and local style take precedence. Do not apply the profile to licenses, directives, suppressions, quoted
text, or intentional fragments. Do not describe the output as ASD-STE100-compliant; this command does not validate the
full writing rules or controlled dictionary.

Apply the test according to comment type:

- Declaration and API documentation should describe caller-visible behavior, special cases, errors, side effects,
  concurrency guarantees, or complexity only when those facts matter to callers.
- Inline comments should usually explain why, an invariant, or a non-obvious constraint. A concise explanation of what
  is appropriate for intrinsically difficult code such as a regular expression, bit manipulation, or specialized
  algorithm.
- TODO/FIXME comments should state concrete remaining work and follow the project's issue or ownership convention. Treat
  untraceable TODOs as needing human context; never synthesize an issue, owner, deadline, or rationale.
- Docstrings may be observable at runtime or used by doctests, CLIs, schemas, and documentation generators. Treat them
  as behavior-sensitive code rather than ordinary inert comments.

## Audit or Edit

In check mode, do not write files. Complete one pass over the target and report all actionable findings together with
tight file and line references.

In apply mode:

1. Make only high-confidence changes supported by the code or repository evidence.
2. Prefer deletion when a comment adds no information. Prefer a small rewrite when it contains useful information.
3. Preserve domain terminology and the smallest useful explanation; do not add generic polish or tutorial prose.
4. Do not modify executable code, declarations, test behavior, or unrelated formatting. A code refactor may be the
   better long-term fix, but it is outside this command's editing scope; report it instead.
5. Do not remove a decoding comment when the underlying code would remain genuinely difficult to understand. Report the
   refactoring opportunity if safe cleanup depends on changing code.
6. Do not alter string literals or data that merely resemble comments.
7. Do not make prose deliberately informal, uneven, or ungrammatical to make it appear human-written.
8. Treat active debug logging, prints, breakpoints, and other executable debugging code as out of scope. Report them
   separately instead of deleting them as comment cleanup.

If the requested cleanup cannot be completed without choosing undocumented intent, leave that comment unchanged and
report the exact missing context.

## Verify and Report

After edits:

1. Re-read every changed comment with the code it describes and confirm identifiers, control flow, edge cases, and
   terminology.
2. Inspect the final diff and confirm that changes stay within comment/docstring scope and preserve protected text.
3. Run the repository's diff whitespace check when available.
4. Run focused formatting, lint, documentation, doctest, or unit checks when comment syntax, directives, docstrings, or
   generated documentation could affect behavior. Do not run broad expensive suites without a proportional reason.
5. If verification shows that a comment edit introduced a failure, revert only that offending edit and report both the
   failure and the rollback. Never use a broad restore that could discard unrelated user changes. If the failure is
   pre-existing or unrelated, preserve the safe edit and report the evidence.
6. Report exactly which checks ran and any failures or skips.

Lead with the outcome and include:

- Mode and resolved target
- Files inspected and material exclusions
- Comments removed or rewritten, grouped by reason rather than by development chronology
- Unchanged comments that need human context, with file and line references
- Verification performed and any remaining caveats

In check mode, separate incorrect or stale comments from lower-priority noise. Do not report stylistic preferences as
defects unless the repository's own guidance establishes them.
