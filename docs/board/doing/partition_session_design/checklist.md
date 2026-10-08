# Session-design partition checklist

Card: [Partition the Session Design](card.md). Branch: `docs/partition-session-design` from `c8bbc72c`.

## Current focus

Partition the shipped contracts before B1's normative updates. The entry point retains durable session state;
`design_session_context.md` owns artifacts/resume/transfer, and `design_session_execution.md` owns
hooks/queues/Codex/event journals. No runtime behavior changes.

## Execution

- [x] Activate the card on its own branch and identify cohesive section boundaries.
- [x] Move complete sections and repoint repository links plus Claude/Codex gather-context routing.
- [x] Verify lossless reconstruction after normalizing only link destinations and formatting whitespace.
- [x] Record exact-content Claude Opus 5 counts at or below 23,000 for every partition.
- [x] Run Markdown formatting, size/link checks, and working-tree/staged diff checks.
- [ ] Commit and open the prerequisite PR; integrate its tested tree into B1.

## Closeout

- [ ] Verify merge/check results, record closeout, move to `done/`, and repoint links.

## Evidence

Source SHA-256: `7c77266a02c14cf4a9efe5b91e9be5c99048f9d9ec35dd02a50f37a0ed5e575b`. Moved §3.8/§3.9/§H to context;
§3.10/§3.13/§B/§I/§J to execution. §3.3 remains in the entry point.

2026-10-07: reconstructed all original sections in order, normalizing only rewritten link targets/labels and whitespace;
the complete source content matches. Exact Opus 5 counts: entry point 4,706; context 10,816; execution 10,541.
`make pre-commit-md` passes; link audit covers 639 Markdown sources; both diff checks pass. Existing historical-card
target warnings are unchanged debt, not warnings in the partitioned living designs.
