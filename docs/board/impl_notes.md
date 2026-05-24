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
wc -l docs/board/impl_notes.md
./scripts/count-tokens.py --model <agent-model> docs/board/impl_notes.md
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
- Duplicates of `docs/board/change_log.md`.

## Notes

### Memory System Architecture (shipped)

The `forge memory` CLI (PR #1) replaced `forge session memory`. Key architecture decisions for future sessions:

- **Passport-authoritative ownership**: memory-doc passports (`forge_memory` YAML frontmatter) are the source of truth
  for strategy, writers, intent, and inheritance. Session manifests store only participation and auto-update runtime
  state. Stop-time handoff re-reads passports, so editing a passport between sessions takes effect without re-tracking.
- **Tombstone for old CLI**: `forge session memory` is a hidden tombstone group that errors with replacement guidance.
  It must not execute old behavior. Registration path unchanged in `session.py:_register_subgroups()`.
- **Stop-time update chain**: stop hook -> work queue marker -> fire-and-forget `forge handoff run` via detached Popen
  -> handoff agent reads passports, filters by writer access, builds prompt, calls `run_claude_session()`. Detached
  failures are not retried.
- **Shadow path encoding**: `derive_shadow_path()` encodes the immediate parent directory to avoid collisions
  (`docs/board/notes.md` -> `.forge/memory/suggested_board_notes.md`). `check_shadow_path_collision()` catches remaining
  edge cases.
- **Memory inheritance on fork**: `--inherit-memory all|none|shadowed`. Default `all` preserves existing behavior.
  Override-loss bug fixed: docs tracked via `forge memory track` (stored in overrides) were silently lost on fork
  because only `intent.memory` was deep-copied.
- **Curation artifacts**: `curation-` prefix (distinct from handoff `review-` reports) at
  `.forge/artifacts/<session>/memory/curation-{slug}-{hash}-{ts}.md`. Curation never mutates official docs.
