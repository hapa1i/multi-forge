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

## 2026-05-22

### Phase 0: Branch and Baseline (Memory Enhancement)

**Goal**: Map the existing `forge session memory` surface, stop-time update path, handoff report surface, old UX
references, and helper reuse decisions before any code changes.

**Key changes**:

- Mapped CLI surface (session_memory.py, 3 commands, 13 tests), data model (DesignatedDoc, MemoryIntent, HandoffConfig),
  and the read-effective/write-override persistence split.
- Mapped the full stop-time chain: stop hook, work queue, fire-and-forget CLI startup handler, CLI runner, handoff agent
  core. Documented that detached failures are not retried by the queue.
- Mapped the handoff report/show surface (session_handoff.py) separately from the update agent.
- Inventoried 15 entries (8 UPDATE, 2 REMOVE, 5 KEEP) across docs, tests, and skills for old `forge session memory` and
  old-model `designated_docs[]` references.
- Decided 8 helpers + 2 patterns reuse privately behind new `forge memory` CLI; VALID_STRATEGIES moves to shared
  location in Phase 1; old commands become a non-executing tombstone diagnostic path.
- Recorded all maps and decisions in `docs/status/impl_notes.md`.

**Verification**: All six Phase 0 checklist tasks checked with verification notes.
