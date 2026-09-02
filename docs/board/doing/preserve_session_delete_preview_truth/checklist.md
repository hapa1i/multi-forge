# Preserve Session Delete Preview Truth Checklist

Current focus: implement #5 and #6 as the second contiguous batch series.

## Read-Only Preview

- [ ] Cover `delete --all`, cross-worktree name resolution, and stale active entries before cancellation.
- [ ] Route every pre-confirmation session and active lookup through non-pruning snapshots.
- [ ] Prove confirmed deletion still repairs stale derived state.

## Artifact Message

- [ ] Cover nested Forge artifacts inside a removable worktree and artifacts outside it.
- [ ] Print retention only when the cleanup plan preserves the artifact location.
- [ ] Print truthful removal output when the containing worktree is removed.

## Verification

- [ ] Run focused CLI/session unit and regression tests.
- [ ] Run targeted session deletion integration coverage.
- [ ] Record commands and results for batch closeout.

## Acceptance Tests

| Test                    | Fixture                               | Assertion                              | Test File                                                            |
| ----------------------- | ------------------------------------- | -------------------------------------- | -------------------------------------------------------------------- |
| Cancelled batch delete  | unrelated row-only residue            | index bytes remain unchanged           | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Cancelled active lookup | stale active entry                    | active registry remains unchanged      | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Nested artifact preview | artifact root inside removed worktree | preview reports removal, not retention | `tests/src/cli/test_session_start_delete.py`                         |
