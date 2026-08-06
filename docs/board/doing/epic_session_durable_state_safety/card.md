# Epic: Session and durable-state safety

**Parent epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `doing/` -- D011, O006, and D008 shipped in PRs #134--#136; D009 is implementation-verified from merged `main`
at `8ebdb644` and pending independent review, and the remaining four members stay parked in sequence.

## Goal

Make session identity, lifecycle mutations, and shared durable-state readers preserve one observable truth across
validation, failure, recovery, and concurrent deletion without combining eight independently reviewable fixes.

## Design Authority

- [`docs/design.md` §3.2](../../../design.md#32-contract-files-authoritative-paths): the manifest is the durable session
  reservation, the global index is its discovery cache, and deletion must remain terminal.
- [`docs/design.md` §3.3](../../../design.md#33-session-file-schema-forgesessionjson): session manifests are strict
  durable workflow records with field-owned intent, overrides, and confirmed facts.
- [`docs/design.md` §3.9](../../../design.md#39-session-resume-context-management): `intent.launch.runtime` is immutable
  dispatch identity, and transfer strategies describe what actually ran.
- [`docs/design.md` §3.13](../../../design.md#313-async-work-queue) and
  [`docs/design_appendix.md` §B](../../../design_appendix.md#b-work-queue-internals): deferred markers are versioned
  durable work with explicit success, retry, skip, and poison outcomes.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#5-interface-changes): malformed, unreadable, and
  newer-schema state are distinct outcomes; internal inputs are rejected rather than silently defaulted.
- [`missing_worktree_authority`](../../done/missing_worktree_authority/card.md) (DG2): a valid manifest remains a live,
  degraded reservation when its recorded worktree is absent.

## Reproduction Record

All eight findings were rechecked on merged `main` at `dc963a7c`. One disposable pytest module passed eight assertions
of the documented broken behavior and was removed after the evidence was recorded.

| Finding | Fixture                                                                         | Observed result                                                                                  |
| ------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| D011    | existing JSON file whose `open()` raises `OSError`                              | `read_json` raised `StateCorruptedError`, not the existing `StateUnreadableError`                |
| O006    | valid v1 manifest with `"confirmed": null`                                      | `SessionStore.read()` leaked raw `AttributeError`                                                |
| D008    | parent `launch` override containing `runtime="codex"` over Claude intent        | validation accepted it; effective runtime became Codex while raw launch intent stayed Claude     |
| D009    | valid manifest under an existing Forge root with a missing recorded worktree    | `get_session` returned the row; `list_sessions` returned nothing and deleted it                  |
| O003    | delete a real Codex session manifest while a mocked headless resume turn runs   | post-turn update raised `SessionFileNotFoundError` and left a lock-only session directory        |
| D021    | marker with `schema_version=current+1`, a future field, and five drain attempts | every drain rewrote retry metadata; the fifth moved the marker to `failed/`                      |
| D022    | `SessionManager.resume_session(..., strategy="not-a-strategy")`                 | structured context ran, while the child persisted the unknown literal as its derivation strategy |
| D010    | `session incognito --worktree` with both repository guards observed             | the command called `require_repo_root`, unlike the other worktree-creating commands              |

## Members and Sequence

| Order | Finding | Member                                                                                                              | Review boundary                                                          |
| ----- | ------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 1     | D011    | [`preserve_unreadable_json_state_classification`](../../done/preserve_unreadable_json_state_classification/card.md) | Generic read errors and caller-specific safe outcomes                    |
| 2     | O006    | [`reject_non_object_manifest_confirmed`](../../done/reject_non_object_manifest_confirmed/card.md)                   | Strict manifest shape and repair/delete classification                   |
| 3     | D008    | [`enforce_launch_runtime_override_immutability`](../../done/enforce_launch_runtime_override_immutability/card.md)   | Parent-object override validation without freezing sibling launch fields |
| 4     | D009    | [`retain_missing_worktree_sessions`](../retain_missing_worktree_sessions/card.md)                                   | Manifest liveness, derived launchability, repair, and binding ownership  |
| 5     | O003    | [`preserve_headless_codex_concurrent_delete`](../../todo/preserve_headless_codex_concurrent_delete/card.md)         | Post-turn reconciliation when explicit deletion wins                     |
| 6     | D021    | [`preserve_newer_workqueue_markers`](../../todo/preserve_newer_workqueue_markers/card.md)                           | Forward-schema preservation distinct from retryable handler failure      |
| 7     | D022    | [`reject_unknown_resume_strategy`](../../todo/reject_unknown_resume_strategy/card.md)                               | Transfer-strategy validation before artifacts or child state             |
| 8     | D010    | [`align_incognito_worktree_guard`](../../todo/align_incognito_worktree_guard/card.md)                               | CLI root-guard parity for worktree creation                              |

D011 goes first because its exception contract is consumed by the queue and other state readers. O006 then pins strict
manifest classification before D009 changes index/repair behavior. D008 is a bounded immutable-identity fix. D009 ships
the approved DG2 authority model before O003 reconciles a concurrent terminal delete against it. The three MEDIUM
members follow the HIGH-severity set; D021 explicitly depends on D011's unreadable-state distinction.

## Drift Constraints

- Keep row-first creation, index-to-manifest lock ordering, and fact-derived delete declines unchanged.
- Do not make a missing worktree equivalent to a missing, corrupt, unreadable, or newer-schema manifest.
- Do not let effective overrides choose runtime dispatch; launchers continue to trust raw immutable intent.
- Preserve explicit deletion as terminal: post-run reconciliation may report the lost destination but cannot recreate
  it.
- Do not treat unreadable bytes, malformed content, handler failure, and newer schema as the same queue outcome.
- Keep `core/ops` UI-free and preserve existing CLI stdout/stderr/JSON contracts.
- Every bug member must add a dedicated marked regression module and run the integration tier required by
  [`testing_guidelines.md`](../../../developer/testing_guidelines.md#regression-test-mandate).
- Each member must retain and run its target regression failing on that member's merged-`main` base before implementing
  the fix; this admission characterization does not replace execution-branch reproduction.

## Closeout

Close this epic only after all eight members ship independently, the review ledger records each outcome, the approved
DG2 liveness model is reflected in normative and end-user docs, and all durable-state compatibility behavior is covered
by regression tests.
