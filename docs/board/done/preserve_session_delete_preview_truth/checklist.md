# Preserve Session Delete Preview Truth Checklist

Status: completed 2026-09-06. PR #251 merged as `6f7cb64e` with all five GitHub checks passing. See the
[epic closeout](../epic_1_0_release_hardening/checklist.md#release-disposition).

## Read-Only Preview

- [x] Cover `delete --all`, cross-worktree name resolution, and stale active entries before cancellation.
- [x] Route every pre-confirmation session and active lookup through non-pruning snapshots.
- [x] Prove confirmed deletion still repairs stale derived state.
- [x] Repair a row-only target transactionally and preserve a replacement published while confirmation is open.

## Artifact Message

- [x] Cover nested Forge artifacts inside a removable worktree and artifacts outside it.
- [x] Print retention only when the cleanup plan preserves the artifact location.
- [x] Print truthful removal output when the containing worktree is removed.

## Clean Preview Parity

- [x] Preserve malformed active-registry bytes while matching apply's runtime-registry repair policy.
- [x] Classify fractional ages with the same threshold calculation as apply.
- [x] Report malformed timestamps without rewriting the session index.
- [x] Report a dirty owned worktree as an apply failure unless `--force` is selected.
- [x] Validate manifests even when clean keeps worktrees, and fail closed when the Git dirty probe fails.
- [x] Model shared-worktree deletion order and scope co-resident identity by name plus Forge root.

## Verification

- [x] Run focused CLI/session unit and regression tests.
- [x] Run targeted session deletion integration coverage.
- [x] Record commands, results, and the integrated SHA for batch closeout.

Verified against integrated code SHA `817cb5ca`.

```bash
uv run pytest -q \
  tests/regression/test_bug_session_delete_preview_index_mutation.py \
  tests/src/cli/test_session_start_delete.py \
  tests/src/cli/test_session_extensions.py \
  tests/src/session/test_cleanup.py \
  tests/src/session/test_manager_delete.py \
  tests/src/session/test_manager_integration.py \
  tests/regression/test_bug_session_create_crash_atomicity.py
```

Result: 210 passed in 55.09 seconds.

```bash
./scripts/test-integration.sh \
  tests/integration/cli/test_session_commands_integration.py::TestSessionDelete \
  tests/integration/cli/test_session_resume_proxy_integration.py \
  tests/integration/cli/test_policy_cli_contract_integration.py \
  tests/integration/docker/test_installer.py::TestForgeExtensionEnable::test_full_profile_memory_skill_contracts \
  tests/integration/docker/test_walkthrough_release_artifact.py
```

Result: 11 passed in 60.17 seconds.

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
| Default clean manifest  | corrupt manifest while keeping worktree      | preview reports the same apply failure           | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Named dirty preview     | owned dirty checkout before confirmation     | command refuses before prompting                 | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Shared apply order      | guest then dirty owner in one checkout       | preview and apply agree on delete/fail counts    | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Broken Git metadata     | non-zero `git status`                        | dirty probe fails closed                         | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Replacement race        | creator publishes while prompt is open       | replacement row and manifest survive             | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Same-name co-resident   | root and nested projects share a checkout    | exact target row alone is excluded               | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
