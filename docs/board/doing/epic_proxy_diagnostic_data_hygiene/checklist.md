# Proxy diagnostic data hygiene checklist

Current focus: review and merge O037/O038/O042 before activating D035.

## Activation and sequencing

- [x] Merge the bounded Wave 5 MEDIUM admission record (PR #156, `46e6a309`).
- [x] Start `fix/remove-proxy-converter-plaintext-logs` from merged `main`.
- [x] Move this epic and O037/O038/O042 to `doing/`, create their checklists, and repoint inbound links.
- [x] Retain a marked O037/O038/O042 regression that fails all five cases on `46e6a309` before implementation.
- [x] Implement and verify O037/O038/O042 without activating D035 or D036.
- [ ] Independently review and merge O037/O038/O042 before moving D035 from `todo/`.
- [ ] Start the D035 branch from its merged predecessor, close O037/O038/O042, and activate D035.
- [ ] Independently review and merge D035 before moving D036 from `todo/`.
- [ ] Start the D036 branch from its merged predecessor, close D035, and activate D036.
- [ ] Independently review and merge D036, then close this child epic.

## Members

- [ ] O037/O038/O042 -- metadata-only, lazy proxy converter logs (active).
- [ ] D035 -- metadata-only tool-event diagnostics (parked).
- [ ] D036 -- validated client request IDs (parked).

## Coordination and closeout

- [ ] Keep the review ledger, parent epic cursor, member paths, and change log current after each merge.
- [ ] Preserve the explicit raw `stream_chunks` and bounded opt-in `tool_failures` planes across all three members.
- [ ] Close the epic only after all three members ship independently with retained regressions, focused tests, targeted
  proxy integration coverage, and full pre-commit verification.
