# 1.0 Release Hardening Epic Checklist

Activation base: `15cbe45e` (`origin/main`, 2026-09-02).

Status: completed 2026-09-06. [PR #251](https://github.com/hapa1i/multi-forge/pull/251) merged as `6f7cb64e` with all
five GitHub checks passing. The maintainer closed the manual repetition gates by the disposition below.

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
- [x] Resolve final walkthrough repetition: waived by the maintainer for 1.0.0; no new manual run is claimed.
- [x] Resolve pinned QA repetition: waived by the maintainer for 1.0.0; no new manual run is claimed.
- [x] Run board/link checks and `git diff --check`.

## Delivery

- [x] Open one PR containing the three complete card series.
- [x] Confirm all required PR checks pass on merged PR head `4791e46a`.
- [x] Record closeout and move the epic and members to `done/` after merge.

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

`/walkthrough --report --reset` and pinned release QA were not repeated for the final release candidate.

## Release disposition

The maintainer declined another full manual walkthrough and QA run when reviewing 1.0.0 readiness. Release sign-off uses
the saved passing QA run from 2026-09-01 and walkthrough from 2026-09-02 together with later automated and scoped
integration evidence. Those saved runs retain their original wheel identities and are not presented as runs of 1.0.0.

Changes after those manual runs include policy enforcement, deletion, and walkthrough hardening as well as model
updates. This epic records 11 scoped Docker integrations for its changed paths. The final product tree also passed
10,257 unit tests, 1,221 regressions, 13 model/proxy/session integrations, full pre-commit, and installed-wheel checks
as recorded in the [Astra closeout](../gpt_astra_defaults/checklist.md).

This is a maintainer disposition for this release, not a change to future QA verdict or artifact-identity rules.
