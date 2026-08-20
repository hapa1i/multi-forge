# Harden worktree config-copy safety checklist

Current focus: prove O089/O090 at the per-file copy and cleanup boundary while preserving exact-file behavior and dirty
retry order.

## Phase 1 -- Characterize and activate

- [x] Activate only Wave 8 order 4 from pushed closeout `3f50012c` on `agent/harden-worktree-config-copy-safety`; keep
  orders 5--19 parked.
- [x] Add fail-first regressions proving cleanup preserves a tracked descendant and glob/directory discovery excludes
  nested `.git` and `node_modules` matches; both failed on execution base `3f50012c`.
- [x] Add review-driven fail-first regressions proving symlinked directory leaves/ancestors cannot delete or write
  outside the worktree; all four failed on initial PR head `f7027368`.
- [x] Recheck exact-file copy, destination-exists, metadata, failure-reporting, and dirty-retry contracts before
  changing the shared helpers.

## Phase 2 -- Implement

- [x] Resolve allowlisted directories into per-file candidates and apply destination/tracked checks to every file.
- [x] Return only independently verified untracked files to cleanup; unlink files individually and prune only empty
  directories.
- [x] Exclude `.git` and `node_modules` components from glob matches and directory descent at every depth.
- [x] Reject symlinked directory components at discovery and copy destinations, recheck parent components before unlink,
  contain empty-parent pruning locally, and log best-effort walk failures.
- [x] Synchronize normative worktree config-copy and cleanup ownership documentation.

## Phase 3 -- Verify and publish

| Boundary            | Fixture                                            | Assertion                                                 | Tier              |
| ------------------- | -------------------------------------------------- | --------------------------------------------------------- | ----------------- |
| Directory copy      | tracked and untracked descendants                  | tracked target survives; missing untracked file is copied | unit/Docker       |
| Dirty cleanup       | tracked and untracked descendants                  | only untracked file is removed; tracked content survives  | regression/Docker |
| Symlink boundary    | leaf, ancestor, tracked, and external targets      | no traversal, write, unlink, or prune follows the symlink | unit/regression   |
| Excluded traversal  | nested `.git` and `node_modules` matches           | excluded files are neither copied nor removed             | unit/regression   |
| Exact-file behavior | missing, existing, tracked, and copy-failure cases | existing result and metadata contracts remain             | unit              |
| Retry ordering      | first removal reports dirty                        | cleanup runs only after dirty failure, then retries once  | regression        |

- [x] Run focused config-copy/cleanup unit/regression checks (39 passed), Docker worktree suites (34 passed), and the
  session worktree-create path (one passed, 23 deselected).
- [x] Run `make test-unit` (9,318 passed, one skip), `make test-regression` (955 passed), targeted Docker session
  fork/worktree cleanup coverage, and `make pre-commit`.
- [x] Verify documentation size (`design.md` 29,991; appendix 29,988 Opus-5 tokens), all 970 local board links,
  stale-lane references, and diff hygiene.
- [x] Commit, push, and open independent draft PR #219.
- [x] Ship order 4 in PR #219 (`43a3b29c`) and close it before activating order 5.
