# Preserve Session Delete Preview Truth Checklist

Current focus: post-review clean-preview parity is implemented; focused and integrated reruns remain pending.

## Read-Only Preview

- [x] Cover `delete --all`, cross-worktree name resolution, and stale active entries before cancellation.
- [x] Route every pre-confirmation session and active lookup through non-pruning snapshots.
- [x] Prove confirmed deletion still repairs stale derived state.

## Artifact Message

- [x] Cover nested Forge artifacts inside a removable worktree and artifacts outside it.
- [x] Print retention only when the cleanup plan preserves the artifact location.
- [x] Print truthful removal output when the containing worktree is removed.

## Clean Preview Parity

- [x] Preserve malformed active-registry bytes while matching apply's runtime-registry repair policy.
- [x] Classify fractional ages with the same threshold calculation as apply.
- [x] Report malformed timestamps without rewriting the session index.
- [x] Report a dirty owned worktree as an apply failure unless `--force` is selected.

## Verification

- [ ] Run focused CLI/session unit and regression tests.
- [ ] Run targeted session deletion integration coverage.
- [ ] Record commands, results, and the integrated SHA for batch closeout.

Current-head evidence is pending the integrated final SHA.

## Acceptance Tests

| Test                    | Fixture                                      | Assertion                                        | Test File                                                            |
| ----------------------- | -------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------- |
| Cancelled batch delete  | unrelated row-only residue                   | index bytes remain unchanged                     | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Cancelled target delete | requested row-only residue                   | target index bytes remain unchanged              | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Cross-worktree delete   | sibling target plus row-only residue         | Tier 2 leaves index bytes unchanged              | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Cancelled active lookup | stale active entry                           | active registry remains unchanged                | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Confirmed delete        | stale index and active state                 | derived state is repaired                        | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Nested artifact preview | artifact root inside removed worktree        | preview reports removal, not retention           | `tests/src/cli/test_session_start_delete.py`                         |
| External artifact root  | artifact root outside removed worktree       | preview reports retention                        | `tests/src/cli/test_session_start_delete.py`                         |
| Malformed active state  | invalid runtime-registry bytes               | preview preserves bytes and matches apply policy | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Fractional age          | session age between whole-day boundaries     | preview and apply select the same target         | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Malformed timestamp     | invalid indexed access time                  | both paths skip the target without deleting it   | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Dirty worktree          | owned dirty checkout with deletion requested | preview reports the apply failure                | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
