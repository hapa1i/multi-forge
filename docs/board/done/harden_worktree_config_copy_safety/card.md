# Harden worktree config-copy safety

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #219 (`43a3b29c`) on 2026-08-20.

**Findings**: O089 and O090 (LOW safety/correctness).

## Goal

Make worktree config copying and dirty-worktree cleanup operate on verified untracked files, never an allowlisted
directory whose contents can include tracked or excluded trees.

## Verified Evidence

`config_copy._copy_single` handles directories before the tracked-file guard, `get_copied_config_files` returns matching
directories unconditionally, and cleanup removes those roots with `shutil.rmtree`. `_resolve_glob` is an unfiltered
`Path.glob` even though the public docstring promises `.git`/`node_modules` exclusion.

## Acceptance Criteria

- Resolve directory allowlist entries to per-file copy decisions; skip every tracked descendant.
- Cleanup only files independently proven untracked at cleanup time, and prune empty directories without recursively
  deleting a possibly tracked root.
- Reject symlinked directory components during copy discovery, destination writes, cleanup rechecks, and empty-parent
  pruning.
- Exclude `.git` and `node_modules` at every depth from glob results and prune them from directory traversal.
- Preserve exact-file allowlist behavior, destination-exists protection, metadata-preserving copies, failure reporting,
  and dirty-worktree retry order.
- Regressions must prove a tracked descendant survives cleanup and nested excluded matches are neither copied nor
  removed.

## Exclusions

- Replacing `Path.glob` with a pruning glob engine. Result filtering closes O090 without changing general glob
  semantics; traversal optimization remains future performance work.
- Batching Git tracked-file probes. Directory entries are bounded today, and the second cleanup-time check is an
  intentional mutation-boundary guard.

## Verification

Run config-copy/cleanup unit and integration suites, full unit/regression suites, targeted Docker session fork/worktree
cleanup coverage, and `make pre-commit`. Update worktree-copy ownership docs if the recorded cleanup unit changes from
directory to file.
