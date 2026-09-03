# 1.0 Release Hardening Epic Checklist

Activation base: `15cbe45e` (`origin/main`, 2026-09-02).

Current focus: post-review fixes and automated verification are complete; refreshed PR CI and the two manual
release-candidate gates remain.

## Coordination

- [x] Record fixed membership, order, branch base, parallel boundaries, and integration ownership.
- [x] Freeze walkthrough missing-prefix behavior to require complete verified-prefix evidence.
- [x] Map every accepted final-audit correction to a member acceptance row and focused regression.
- [x] Record all final evidence against one integrated SHA.
- [x] Review every member's focused evidence and contiguous commit series.
- [x] Reconcile shared documentation, board links, and final diff.

## Integrated Verification

- [x] Run focused tests for every finding on the integrated head.
- [x] Run targeted policy, session deletion/routing, walkthrough, installer, and Docker integration tests.
- [x] Run `make test-unit`, `make test-regression`, and `make pre-commit`.
- [x] Build the wheel and verify the packaged walkthrough from a clean install boundary.
- [ ] Run `/walkthrough --report --reset` against the final candidate.
- [ ] Run pinned release QA against the same final wheel and SHA.
- [x] Run board/link checks and `git diff --check`.

## Delivery

- [x] Open one PR containing the three complete card series.
- [ ] Confirm all required PR checks pass without a post-evidence code change.
- [ ] Record closeout and move the epic and members to `done/` after merge.

## Evidence

Automated evidence targets integrated code SHA `817cb5ca`; the member checklists record their exact focused and
integration commands.

- Focused slices: 246 core/CLI, 210 session, and 346 walkthrough tests passed.
- `make test-unit`: 10,110 passed and 117 deselected in 245.13 seconds.
- `make test-regression`: 1,177 passed in 201.45 seconds.
- `make pre-commit`: all hooks passed, including lint, formatting, mypy, Pyright, file-size limits, and Markdown links.
- `make build`: built `dist/multi_forge-0.9.4.tar.gz` and `dist/multi_forge-0.9.4-py3-none-any.whl`.
- The combined targeted integration selection: 11 passed in 60.17 seconds, including exact-wheel walkthrough coverage.
- `bash -n` for the changed walkthrough shell scripts and `git diff --check` passed. The QA and walkthrough state
  engines differ only in their two documented skill-identity lines.

`/walkthrough --report --reset` and pinned release QA are intentionally not claimed here. They remain manual gates for
the final release candidate after PR review and CI.
