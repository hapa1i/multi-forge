# Preserve transcript artifact identity and schema

**Epic**: [`epic_stop_artifact_correctness`](../../doing/epic_stop_artifact_correctness/card.md).

**Findings**: D007 (HIGH) and D024 (MEDIUM) in
[`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted Wave 2 implementation work, parked.

## Goal

Keep repeated Stop capture bounded to one canonical manifest record per transcript identity, preserve malformed durable
state instead of clobbering it, and prevent PreCompact snapshots from hiding the latest resumable transcript artifact.

## Design Authority

- [`docs/design.md` §3.8](../../../design.md#38-session-artifacts-plans--transcripts): transcript records carry
  `session_id` and `copied_path`, and UUID-named transcript destinations are idempotent.
- [`docs/design.md` §3.10](../../../design.md#310-hook-handlers): repeated Stop invocation must be safe and artifact
  capture is idempotent by UUID.
- [`coding_standards.md` §5](../../../developer/coding_standards.md#forge-owned-durable-state): malformed manifest state
  is not silently defaulted or skipped; known legacy state is explicitly detected and migrated or surfaced.

## Evidence

Rechecked on merged `main` at `86fa53da`:

- `src/forge/cli/hooks/commands.py:157-177` appends a new Stop record after every UUID-named artifact refresh.
- `src/forge/cli/hooks/_helpers.py:131-149` has no identity check and replaces a non-list field; the same append/clobber
  implementation is duplicated at `src/forge/session/hooks/session_start.py:481-497`.
- An executable characterization appended one identical `session_id`/`copied_path` record twice and observed two equal
  entries; a mapping-valued `transcripts` field was discarded and replaced by the new entry.
- `src/forge/cli/hooks/commands.py:870-880` writes `snapshot_path`-only PreCompact records into `transcripts`, while
  `src/forge/session/manager.py:303-312,893-900` and `src/forge/session/transfer.py:1114-1122` inspect the last entry
  for `copied_path`. A canonical record followed by a snapshot-shaped entry made the shared latest-artifact helper
  return `None`.
- `src/forge/cli/session_fork.py:643-649` contains a fourth copy of the same tail-entry selection for full-strategy
  context-budget preflight, so fixing only the three evidence-ledger sites would leave the D024 failure shape live in
  the fork twin.

## Expected Behavior

- A canonical transcript record has unambiguous stable identity, including `session_id` and forge-root-relative
  `copied_path`; repeated Stop capture for that identity refreshes/reconciles it without growing the list.
- `confirmed.compaction.transcript_snapshots` owns PreCompact's snapshot-shaped records. New PreCompact writes do not
  add that incompatible shape to `confirmed.artifacts.transcripts`.
- Readers select the newest valid canonical transcript record even when a legacy manifest contains duplicate Stop
  records or trailing PreCompact-shaped entries.
- Known legacy PreCompact entries are recognized explicitly and either migrated or surfaced with a compatibility
  diagnostic; unrelated malformed entries are not silently filtered out.
- A non-list `confirmed.artifacts.transcripts` value is surfaced as malformed state and is never overwritten merely to
  append a new record. Hook failure behavior remains fail open as defined for each caller.

## Scope

- Put canonical transcript record validation/reconciliation in one session-layer helper used by Stop and SessionStart
  rollover instead of retaining duplicated hook-local append logic.
- Put canonical latest-transcript selection in one session-layer helper used by manager derivation, manager
  full-strategy preflight, transfer assembly, and CLI fork full-strategy preflight. Do not leave call-site-local
  `transcripts[-1]` schema interpretation at those seams.
- Reconcile existing duplicates for the same identity when that identity is next written, without deleting distinct
  session artifacts.
- Keep PreCompact snapshot metadata in its dedicated compaction collection and harden latest-transcript selection for
  the recognized legacy mixed shape without adding a generic skip-invalid-record path.
- Synchronize `docs/design.md` and any manifest-schema documentation with the implemented write and compatibility rules.

## Acceptance Criteria

- `tests/regression/test_bug_d007_stop_artifact_idempotency.py` invokes repeated Stop capture for one UUID and asserts
  one canonical manifest record, refreshed artifact content, and no loss of distinct records.
- `tests/regression/test_bug_d024_precompact_artifact_schema.py` covers new PreCompact writes and a legacy mixed-shape
  manifest; manager derivation, transfer assembly, and both full-strategy budget preflights resolve the same latest
  canonical copied artifact and assert the chosen migration or diagnostic behavior.
- Both regression modules have `pytestmark = pytest.mark.regression` and module docstrings naming the finding and root
  cause, per the Regression Test Mandate.
- Unit coverage proves malformed non-list state is not clobbered and both Stop and rollover share the same identity
  rules.
- `./scripts/test-integration.sh tests/integration/cli/test_artifact_hooks_integration.py` covers repeated Stop plus
  PreCompact/SessionStart boundaries.
- `make test-regression`, the focused unit suite, the required integration runner, and `make pre-commit` pass.

## Compatibility and Exclusions

- Existing manifests may contain duplicate Stop records and legacy PreCompact-shaped entries; support them on read and
  converge duplicates only at the corresponding write seam rather than requiring an eager migration. Do not silently
  treat unrelated malformed entries as the same legacy shape.
- Preserve artifact files, `captured_at`/reason provenance, forge-root-relative paths, rollover behavior, and shared
  transcript deletion safeguards.
- Sharing the selector is a D024 drift-control requirement, not an independent admission or disposition of compound
  O099; its `_FakeResponse` family and final ledger disposition remain Wave 7 work.
- Do not redesign plan artifacts, transcript retention, or resume strategies. In particular, replacing the existing
  artifact-list lookup in the two budget preflights does not expand them to D023's other transcript sources; D023
  remains a separate finding.
