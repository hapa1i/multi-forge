# Session and durable-state safety checklist

Current focus: D011 review is complete; merge it before activating O006.

## Activation and sequencing

- [x] Merge the Wave 3 admission record (PR #133, `eef7cee0`).
- [x] Start `fix/preserve-unreadable-json-state-classification` from merged `main`.
- [x] Move this epic and D011 to `doing/`, create their checklists, and repoint inbound links.
- [x] Retain a marked D011 regression that fails on the merged baseline before implementation.
- [x] Implement and verify D011 without activating O006 or D021.
- [x] Review D011 and record the accepted review amendments.
- [ ] Merge D011 before moving O006 from `todo/`.

## Remaining members

- [ ] Ship O006 strict `confirmed` classification.
- [ ] Ship D008 launch-runtime override immutability.
- [ ] Ship D009 missing-worktree liveness and launchability.
- [ ] Ship O003 headless Codex concurrent-delete reconciliation.
- [ ] Ship D021 newer-schema workqueue preservation after D011.
- [ ] Ship D022 transfer-strategy validation.
- [ ] Ship D010 incognito worktree guard parity.

## Closeout

- [ ] Keep the review ledger, member paths, and parent epic cursor current after each merge.
- [ ] Close this epic only after all eight independently reviewed members ship with their required regressions and
  integration coverage.
