# Reuse transcript-reference scans

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `doing/` -- implementation commit `cff6adc6` and integrated verification are complete on
`agent/wave8-batch-4`; await the shared Batch 4 review and merge.

**Finding**: narrowed O085 (LOW efficiency).

## Goal

Parse the global session index/manifests once when a native-relocate deletion checks both ordinary and relocated
transcript ownership.

## Verified Evidence

Ordinary transcript cleanup calls `_find_shared_transcript_sessions` for the session/artifact IDs. A native-relocate
derivation then calls it again for `relocated_parent_session_id`, causing two O(N) manifest scans only on that delete
path. Other delete modes perform one scan and are not affected by the original claim.

## Acceptance Criteria

- Resolve all candidate transcript IDs in one ownership scan and partition the result for ordinary versus relocated
  cleanup decisions.
- Preserve adopted-source protection, path-resolved sharing, sibling/native-parent safeguards, corruption handling,
  logging, and concurrent-create/delete ownership checks.
- Add a native-relocate regression that counts one scan and still preserves every shared transcript case.

## Verification

Run focused session-delete/shared-transcript regressions, full unit/regression suites, targeted Docker
native-relocate/session lifecycle coverage, and `make pre-commit`.
