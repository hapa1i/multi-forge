# Preserve newer-schema workqueue markers

**Epic**: [`epic_session_durable_state_safety`](../../doing/epic_session_durable_state_safety/card.md).

**Finding**: D021 (MEDIUM) in [`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted Wave 3 implementation work after the HIGH-severity members.

## Goal

Leave a deferred-work marker written by a newer Forge byte-identical and pending, with visible upgrade guidance, instead
of rewriting it as a retry failure and eventually moving it out of the live queue.

## Design Authority

- [`coding_standards.md` §5](../../../developer/coding_standards.md#forge-owned-durable-state): unsupported newer
  schemas require an actionable upgrade error and cannot be silently coerced.
- [`docs/design.md` §3.13](../../../design.md#313-async-work-queue) and
  [`docs/design_appendix.md` §B.2](../../../design_appendix.md#b2-processing-contract): retry metadata and poison moves
  describe handler failures, while skipped work remains pending.
- Existing telemetry readers provide the repository precedent: newer-schema records are skipped with a one-time warning.

## Evidence

Rechecked on `dc963a7c`: a marker at `MARKER_SCHEMA_VERSION + 1` with an unknown future field was drained five times.
Each pass rewrote `attempt_count`, `last_attempt_at`, and `last_error`; the fifth moved the rewritten marker to
`pending-work/failed/`. `_validate_marker` currently treats every non-current version as an ordinary invalid marker.

## Expected Behavior

- A strictly newer integer schema is skipped, left byte-identical in `pending-work/`, and emits upgrade guidance once
  per process while later current-schema markers remain processable.
- It accrues no attempts, errors, or poison status and is never moved to `failed/` by the older Forge.
- Malformed JSON, missing/non-integer versions, older unsupported schemas, handler failures, and current-schema poison
  markers retain their separately tested outcomes.

## Acceptance Criteria

- Add `tests/regression/test_bug_d021_newer_workqueue_marker_preserved.py` with the required regression marker and a
  docstring naming D021 and the version/validation collapse.
- Unit tests assert byte preservation across repeated drains, one-time warning behavior, later-marker progress, and no
  attempt or failed count for the newer marker.
- Docker startup-queue coverage proves a non-exempt JSON command leaves the future marker unchanged, processes a later
  current-schema marker, keeps stdout as one valid document, and emits upgrade guidance on stderr.
- Update `docs/design_appendix.md` §B.2 with the shipped newer-schema outcome.
- Run `tests/src/core/workqueue/test_queue.py` and `tests/src/cli/test_startup_queue.py`, then
  `./scripts/test-integration.sh tests/integration/cli/test_startup_queue_integration.py`, `make test-regression`, and
  `make pre-commit`.

## Compatibility and Exclusions

- Depends on D011 so unreadable bytes and readable newer schemas enter distinct branches.
- Do not deserialize or execute unknown payloads and do not delete future fields.
- Do not change handler retry limits, corrupted-marker quarantine, marker IDs, or producer schemas.
