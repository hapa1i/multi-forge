# Preserve newer-schema workqueue markers

**Epic**: [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).

**Finding**: D021 (MEDIUM) in
[`review_combined.md`](../../reviews/whole_repo_design_findings.md#design-conformance-findings).

**Lane**: `done/` -- shipped in PR #140 (`ecc79aa2`) on 2026-08-07.

## Goal

Leave a deferred-work marker written by a newer Forge byte-identical and pending, with visible upgrade guidance, instead
of rewriting it as a retry failure and eventually moving it out of the live queue.

## Design Authority

- [`coding_standards.md` §5](../../../developer/coding_standards.md#forge-owned-durable-state): unsupported newer
  schemas require an actionable upgrade error and cannot be silently coerced.
- [`docs/design_sessions.md` §3.13](../../../design_sessions.md#313-async-work-queue) and
  [`docs/design_sessions.md` §B.2](../../../design_sessions.md#b2-processing-contract): retry metadata and poison moves
  describe handler failures, while skipped work remains pending.
- PR #139 (`de8adaac`): bounded windows with resident deferred or skipped work advance `.scan-cursor`; D021 must join
  that outcome so future markers cannot pin later actionable work behind the startup cap.
- Existing telemetry readers provide the repository precedent: newer-schema records are skipped with a one-time warning.

## Evidence

Rechecked on `dc963a7c`: a marker at `MARKER_SCHEMA_VERSION + 1` with an unknown future field was drained five times.
Each pass rewrote `attempt_count`, `last_attempt_at`, and `last_error`; the fifth moved the rewritten marker to
`pending-work/failed/`. `_validate_marker` currently treats every non-current version as an ordinary invalid marker.

Execution rechecked on merged `main` at `de8adaac` after PR #139. The marked D021 regression failed on its first drain:
the future marker was reformatted and retry metadata was written instead of preserving its original bytes. The new scan
cursor does not resolve the version-classification collapse because validation errors do not enter the resident-work
outcome.

## Expected Behavior

- A strictly newer integer schema is a resident deferred outcome: it is skipped, left byte-identical in `pending-work/`,
  and emits upgrade guidance once per process.
- A bounded window containing newer-schema markers advances the existing scan cursor so later current-schema markers
  remain processable without increasing the startup item cap.
- It accrues no attempts, errors, or poison status and is never moved to `failed/` by the older Forge.
- Malformed JSON, missing/non-integer versions, older unsupported schemas, handler failures, and current-schema poison
  markers retain their separately tested outcomes.

## Acceptance Criteria

- Add `tests/regression/test_bug_d021_newer_workqueue_marker_preserved.py` with the required regression marker and a
  docstring naming D021 and the version/validation collapse.
- Unit tests assert byte preservation across repeated drains, one-time warning behavior, bounded-window cursor progress,
  and no attempt, error, or failed count for the newer marker.
- Docker startup-queue coverage proves a non-exempt JSON command leaves the future marker unchanged, processes a later
  current-schema marker, keeps stdout as one valid document, and emits upgrade guidance on stderr.
- Update `docs/design_sessions.md` §B.2 with the shipped newer-schema outcome.
- Run `tests/src/core/workqueue/test_queue.py` and `tests/src/cli/test_startup_queue.py`, then
  `./scripts/test-integration.sh tests/integration/cli/test_startup_queue_integration.py`, `make test-regression`, and
  `make pre-commit`.

## Compatibility and Exclusions

- Depends on D011 so unreadable bytes and readable newer schemas enter distinct branches.
- Do not interpret or execute unknown payloads and do not delete future fields.
- Byte preservation is a consumer-drain guarantee. Producer re-enqueue of the same `marker_id` retains its existing
  atomic-replacement semantics because that ID denotes the current representation of one logical work item.
- Preserve PR #139's bounded rotating-window semantics; the cursor may change independently, but a resident marker's
  bytes may not.
- Do not change handler retry limits, corrupted-marker quarantine, marker IDs, or producer schemas.

## Verification

The marked D021 regression failed on `de8adaac` because the first drain rewrote the future marker's formatting and retry
metadata. The focused workqueue, startup CLI, and regression slice passed (82); the complete Docker startup-queue file
passed (10), proving exact byte retention, later-marker progress, stderr-only guidance, and parseable foreground JSON.
The first Docker attempt exposed a misplaced existing test-body fragment in the new test module; restoring the test
boundary left production unchanged, and the complete file passed on rerun. The regression suite passed (667), and the
unit suite passed (8,804 with one pre-existing platform skip and 118 integration-marked tests deselected). Final
`make pre-commit` passed after Markdown normalization.

## Implementation Outcome

Queue validation now recognizes only a strictly newer integer `schema_version` before legacy-shape cleanup, ordinary
marker validation, or `Marker` construction. That marker becomes resident deferred work: its bytes and unknown fields
remain untouched, no handler runs, no retry/error/poison count accrues, and the older Forge cannot move it to `failed/`.

The first future marker in a process contributes one actionable upgrade diagnostic, rendered by CLI startup on stderr;
later future markers remain silent without changing foreground JSON. Future markers participate in PR #139's bounded
scan cursor, so a window full of unsupported work yields to later current-schema markers. Malformed JSON,
missing/non-integer/older schema versions, lock contention, absent handlers, handler failures, and poison markers retain
their existing outcomes. The normative queue contract is synchronized in `docs/design.md` and the former consolidated
design appendix.
