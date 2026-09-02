# 1.0 Release Hardening Epic Checklist

Activation base: `15cbe45e` (`origin/main`, 2026-09-02).

Current focus: implement the fixed three-card batch on `fix/1-0-release-hardening`.

## Coordination

- [x] Record fixed membership, order, branch base, parallel boundaries, and integration ownership.
- [x] Freeze walkthrough missing-prefix behavior to require complete verified-prefix evidence.
- [ ] Review every member's focused evidence and contiguous commit series.
- [ ] Reconcile shared documentation, board links, and final diff.

## Integrated Verification

- [ ] Run focused tests for every finding on the integrated head.
- [ ] Run targeted policy, session deletion/routing, walkthrough, installer, and Docker integration tests.
- [ ] Run `make test-unit`, `make test-regression`, and `make pre-commit`.
- [ ] Build the wheel and verify the packaged walkthrough from a clean install boundary.
- [ ] Run `/walkthrough --report --reset` against the final candidate.
- [ ] Run pinned release QA against the same final wheel and SHA.
- [ ] Run board/link checks and `git diff --check`.

## Delivery

- [ ] Open one PR containing the three complete card series.
- [ ] Confirm all required PR checks pass without a post-evidence code change.
- [ ] Record closeout and move the epic and members to `done/` after merge.
