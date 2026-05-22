# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the handoff agent with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in `docs/status/checklist.md`.
- Follow `docs/developer/documentation-guidelines.md`: each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/status/change_log.md
./scripts/count-tokens.py --model <agent-model> docs/status/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/documentation-guidelines.md` "Change Log Policy" for
> the full spec.
