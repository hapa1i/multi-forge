# Implementation Notes

Human-approved memory for details that future Forge sessions should retain.

This file is intentionally selective. The handoff agent should propose additions in a shadow doc; humans promote only
the notes that are worth carrying forward.

## Maintenance

- Updated by humans after reviewing proposed notes, not directly by the handoff agent.
- Source for proposed additions: `.forge/memory/suggested_impl_notes.md`.
- Keep notes durable and actionable. Prefer bullets with links to the source doc, issue, test, or file.
- Remove or rewrite notes when they become obsolete.
- Check size periodically and prune stale notes before appending:

```bash
wc -l docs/status/impl_notes.md
./scripts/count-tokens.py --model <agent-model> docs/status/impl_notes.md
```

## What Belongs Here

- Stable architecture decisions and the rationale behind them.
- Non-obvious invariants, ownership boundaries, and path or state rules.
- Bug causes, fixes, and test patterns likely to recur.
- Operational constraints that future sessions must remember.
- Conventions for executing multi-session work in this repo.

## What Does Not Belong Here

- Raw session summaries.
- Pending tasks or phase plans.
- Detailed command output.
- Unverified hunches.
- Duplicates of `docs/status/change_log.md`.

## Notes
