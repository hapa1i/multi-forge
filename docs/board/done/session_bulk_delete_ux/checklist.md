# Session cleanup CLI verification

Merged into `main` on 2026-11-23 as `3e88e270`. Its tree matches the tested PR head `1745b04f`.
[PR #305](https://github.com/hapa1i/multi-forge/pull/305)

| Fixture                                    | Expected result                                                                           |
| ------------------------------------------ | ----------------------------------------------------------------------------------------- |
| A held session index lock                  | Listing succeeds with confirmed sessions and a snapshot hint on stderr                    |
| Several sessions and one unrelated QA copy | Bulk confirmation identifies the selected sessions and offers full paths with `--verbose` |
| One session with a worker lease            | Its name and reason appear before confirmation, and only admitted sessions are removed    |

- [x] Reproduce the failures and add regression coverage. Both the plain list and the age-filtered JSON list raised an
  uncaught index lock timeout. The original bulk preview buried refusals in each session's inventory.
- [x] Verify listing, cancellation, partial success, and detailed previews. On an isolated project with 105 sessions,
  nine unrelated QA transcripts and 13 live leases, the compact preview printed 31 stdout lines at 100 columns. The
  verbose preview printed 1,693, including 945 exclusions. Apply deleted 92 sessions and reported all 13 refusals. A
  separate process held the real index lock through the five-second timeout. The next list returned all 105 sessions
  after release, before deletion.
- [x] Run the affected session CLI and Docker integration checks and synchronize the session guide. The focused suite
  passed 162 cases. The Docker list, delete and purge suites passed all eight cases. An interactive terminal confirmed
  three targets, displayed progress during deletion and printed one final count.
- [x] Run the full suites. All 12,056 unit tests and 2,714 regressions passed. `make pre-commit` passed.
- [x] Verify cleanup recovery before and after saving its inventory. A file edited during confirmation survived and
  required a fresh preview. A saved retry command with a long, quoted project path ran directly from stderr after the
  index lock was released.
- [x] Verify compact purge, verbose text and JSON with an adopted Claude transcript and an absent Codex rollout. In
  linked Git worktrees, the workspace list showed four sessions and the sibling purge removed its two. A worktree
  without a Forge project refused both bulk commands. The terminal displayed purge progress and the final count.
- [x] Verify the review fixes. All 12,058 unit tests, 2,715 regressions and eight targeted Docker integration cases
  passed.
- [x] Verify listing during a delete in another repository. With session work queued, a separate CLI process returned
  both scoped sessions as JSON in 0.71 seconds while apply held the global index lock. The snapshot hint appeared once
  on stderr and cleared after release. Regressions cover age filtering, in-chat output, provisional rows, legacy
  ownership and name reuse.
- [x] Verify that listing with queued session work respects the startup processor's 50 ms admission timeout. The pending
  marker stayed intact while the index was busy and the next uncontended listing processed it.
- [x] Verify the final changes. All 12,058 unit tests, 2,720 regressions and 18 targeted Docker integration cases
  passed. `make pre-commit` passed.
- [x] Reproduce an abandoned launch in Docker with its native child still running. Ordinary delete refused. The forced
  preview named the lease, cancellation preserved it, and confirmation removed the session and its lease. The native
  transcript survived delete. Purge identified the live child and refused.
- [x] Cover explicit force on delete, purge and age-based clean, changed or replaced leases, sidecar liveness, and
  partial retries. Automatic cleanup preserves abandoned leases. An older worktree-only inventory cannot acquire one
  during retry.
- [x] Verify forced cleanup with 12,060 unit tests, 2,732 regressions, nine targeted Docker cases and `make pre-commit`.
  All passed.
- [x] Reproduce the CI failure at 40 columns. Delete, purge and age-based clean now print each refused lease path and
  its `--force` hint on one copyable line.
- [x] Verify the merged change. Python 3.11 and 3.13 each passed 12,060 unit tests and the same 2,732 regressions. All
  636 standard integration tests passed locally.
  [CI run](https://github.com/hapa1i/multi-forge/actions/runs/45132880620)
- [x] Move the card to `done` and record the outcome in the
  [change log](../../change_log.md#keep-session-listings-available-during-bulk-cleanup).
