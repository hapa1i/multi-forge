# Session cleanup CLI verification

The implementation is on `codex/session-bulk-delete-ux`, based on `main` at `3e62973f`.

| Fixture                                    | Expected result                                                                           |
| ------------------------------------------ | ----------------------------------------------------------------------------------------- |
| A held session index lock                  | Listing exits with a retry message on stderr and succeeds once the lock is released       |
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
- [ ] Record the merge and changelog entry and close the card after it ships.
