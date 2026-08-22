# Correct Recent Daily-Review Regressions

**Lane**: `doing/` -- implementation verified in [PR #239](https://github.com/hapa1i/multi-forge/pull/239), awaiting
review and merge.

## Goal

Close five independently verified defects reported against recent merged work: preserve a newly shared relocated
transcript during deletion, prevent terminal-control redaction bypasses, make authority-report active-state failures
actionable, keep installed skill metadata synchronized after every relevant config mutation, and limit historical
context-size exceptions to their two ratified snapshots.

## Verified failures

| Boundary                | Reproduction                                                                        | Incorrect result                                                                                                   |
| ----------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Session deletion        | Publish a native-relocate sibling while ordinary transcript cleanup is running      | The sibling manifest survives but the cached ownership result lets deletion unlink its shared relocated transcript |
| Stop diagnostics        | Insert a printable byte plus backspace inside a configured environment secret       | Plain-text replacement misses the secret while terminal rendering reconstructs and displays it                     |
| Authority report        | Truncate the runtime-only `sessions/active.json`, then run `session authority show` | A raw `JSONDecodeError` escapes the CLI instead of an actionable Forge diagnostic                                  |
| Skill invocation config | Change `skills.invocation` through `config edit` or clear it through `config reset` | Installed Claude/Codex packages remain stale without the existing `extension sync` reminder                        |
| Context-size policy     | Resolve an unrelated completed-card Markdown path                                   | The wildcard grants the unrelated file the 40,000-token historical exception reserved for two checklists           |

## Scope

- Rescan relocated-transcript ownership at its destructive boundary after ordinary transcript cleanup can interleave
  with session publication.
- Normalize rendered backspaces before secret replacement and remove unsafe residual C0/C1 terminal controls before
  diagnostics cross persistence or display boundaries.
- Translate strict, non-repairing active-registry read failures at the authority operation boundary without mutating
  runtime state.
- Detect changed skill-invocation overrides after successful config edit/reset operations and print the established
  `forge extension sync` recovery tip only for those changes.
- Replace the completed-card wildcard with exact rules for `runtime_abstraction/checklist.md` and
  `session_op_layer_extraction/checklist.md`, including a negative path test.

## Constraints

- Preserve shared/adopted transcript ownership safeguards and ordinary transcript cleanup behavior.
- Preserve diagnostic text needed for pytest failure selection, redaction-before-bounding, and the 200-character limit.
- Keep `authority show` read-only; it must neither prune nor recreate `active.json`.
- Do not emit skill-package sync guidance for unrelated config edits/resets or no-op resets.
- Preserve the ratified 40,000-token limits for exactly the two historical checklist snapshots.

## Acceptance criteria

1. Each verified failure has a regression test that fails on the activation base and passes with the fix.
2. A sibling published during ordinary cleanup protects the relocated transcript when deletion reaches unlink.
3. No unsafe terminal control reaches persisted/displayed diagnostics, and a backspace-obfuscated environment secret is
   redacted after applying its rendered text semantics.
4. Malformed active runtime state produces an actionable command error while the file's bytes and mtime remain intact.
5. Config edit/reset prints sync guidance exactly when the stored skill-invocation overrides change.
6. Unrelated completed-card Markdown receives the ordinary Markdown limits; both named snapshots retain their exception.
7. Focused tests, required session/hook/installer integration slices, full unit/regression suites, pre-commit,
   board/link, and diff checks pass before publication.
