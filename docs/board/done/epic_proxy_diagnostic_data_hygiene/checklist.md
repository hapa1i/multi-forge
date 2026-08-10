# Proxy diagnostic data hygiene checklist

Current focus: closed after all three members shipped through PR #159 (`de02b09b`).

## Activation and sequencing

- [x] Merge the bounded Wave 5 MEDIUM admission record (PR #156, `46e6a309`).
- [x] Start `fix/remove-proxy-converter-plaintext-logs` from merged `main`.
- [x] Move this epic and O037/O038/O042 to `doing/`, create their checklists, and repoint inbound links.
- [x] Retain a marked O037/O038/O042 regression that fails all five cases on `46e6a309` before implementation.
- [x] Implement and verify O037/O038/O042 without activating D035 or D036.
- [x] Resolve review follow-up and merge O037/O038/O042 before moving D035 from `todo/` (PR #157, `a2fb0638`).
- [x] Start the D035 branch from its merged predecessor, close O037/O038/O042, and activate D035.
- [x] Independently review and merge D035 before moving D036 from `todo/` (PR #158, `ce7eb1ec`).
- [x] Start the D036 branch from its merged predecessor, close D035, and activate D036.
- [x] Independently review and merge D036, then close this child epic (PR #159, `de02b09b`).

## Members

- [x] O037/O038/O042 -- metadata-only, lazy proxy converter logs (PR #157, `a2fb0638`).
- [x] D035 -- metadata-only tool-event diagnostics (PR #158, `ce7eb1ec`).
- [x] D036 -- validated client request IDs (PR #159, `de02b09b`).

## Coordination and closeout

- [x] Keep the review ledger, parent epic cursor, member paths, and change log current after each merge.
- [x] Preserve the explicit raw `stream_chunks` and bounded opt-in `tool_failures` planes across all three members.
- [x] Close the epic only after all three members ship independently with retained regressions, focused tests, targeted
  proxy integration coverage, and full pre-commit verification.
