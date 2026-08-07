# Session and durable-state safety checklist

Current focus: independently review and merge D009 without starting O003.

## Activation and sequencing

- [x] Merge the Wave 3 admission record (PR #133, `eef7cee0`).
- [x] Start `fix/preserve-unreadable-json-state-classification` from merged `main`.
- [x] Move this epic and D011 to `doing/`, create their checklists, and repoint inbound links.
- [x] Retain a marked D011 regression that fails on the merged baseline before implementation.
- [x] Implement and verify D011 without activating O006 or D021.
- [x] Review D011 and record the accepted review amendments.
- [x] Merge D011 before moving O006 from `todo/` (PR #134, `6be815bf`).
- [x] Start O006 from merged `main`, move it to `doing/`, and retain its baseline regression failure.
- [x] Implement and behaviorally verify O006 without changing D009 liveness or D011 read classification.
- [x] Review O006 and record its separate D047 status-line raw-reader follow-up.
- [x] Merge O006 before moving D008 from `todo/` (PR #135, `00692356`).
- [x] Start D008 from merged `main`, move it to `doing/`, and create its execution checklist.
- [x] Implement and behaviorally verify D008 without changing raw-intent dispatch or sibling launch overrides.
- [x] Review D008 and record its separate D048 relaunch-inheritance policy follow-up.
- [x] Merge D008 before moving D009 from `todo/` (PR #136, `8ebdb644`).
- [x] Start D009 from merged `main`, move it to `doing/`, and create its execution checklist.
- [x] Implement and behaviorally verify D009 without changing terminal-delete or strict-state classification.
- [ ] Independently review and merge D009 before moving O003 from `todo/`.

## Remaining members

- [x] Ship O006 strict `confirmed` classification (PR #135, `00692356`).
- [x] Ship D008 launch-runtime override immutability (PR #136, `8ebdb644`).
- [ ] Ship D009 missing-worktree liveness and launchability.
- [ ] Ship O003 headless Codex concurrent-delete reconciliation.
- [ ] Ship D021 newer-schema workqueue preservation after D011.
- [ ] Ship D022 transfer-strategy validation.
- [ ] Ship D010 incognito worktree guard parity.

## Closeout

- [ ] Keep the review ledger, member paths, and parent epic cursor current after each merge.
- [ ] Close this epic only after all eight independently reviewed members ship with their required regressions and
  integration coverage.
