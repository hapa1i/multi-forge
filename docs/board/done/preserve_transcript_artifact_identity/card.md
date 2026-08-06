# Preserve transcript artifact identity and schema

**Epic**: [`epic_stop_artifact_correctness`](../epic_stop_artifact_correctness/card.md).

**Findings**: D007 (HIGH) and D024 (MEDIUM) in
[`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `done/` -- shipped in PR #131 (`3e090ef5`) as the second Wave 2 member.

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

Rechecked on the execution-branch base `fee562ab` because the preceding Stop-verification member changed the Stop hook.
The two retained regression modules failed in six cases before implementation: repeated Stop produced duplicate records,
a mapping-valued transcript field was clobbered, new PreCompact polluted the canonical list, native derivation/transfer
lost the canonical tail, and both manager and CLI full-strategy budget preflights were bypassed. Review hardening then
reproduced four additional failures: explicit-null transcript state was clobbered by both the shared writer and Stop, an
incomplete dedicated snapshot was accepted as valid migration state, and manager fork validation ran after Git side
effects. PR review then reproduced two visibility failures: successful write-side migration emitted no diagnostic, and
PreCompact reduced malformed durable state to debug-only logging. A retain-without-refresh characterization already
passed and pinned the intended move-to-tail behavior.

- `src/forge/cli/hooks/commands.py:157-177` appends a new Stop record after every UUID-named artifact refresh.
- `src/forge/cli/hooks/_helpers.py:131-149` has no identity check and replaces a non-list field; the same append/clobber
  implementation is duplicated at `src/forge/session/hooks/session_start.py:481-497`.
- `src/forge/core/ops/session_adopt.py` contains a third canonical writer with the same append/clobber behavior, so
  leaving adoption outside the shared write seam would preserve the durable-state defect.
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
- A malformed dedicated compaction snapshot is surfaced unchanged rather than accepted as a migration target, and
  manager fork validation rejects malformed parent artifact state before creating a branch or worktree.
- Recognized write-side migration emits a compatibility warning. PreCompact remains fail open on malformed artifact
  state but warns instead of reducing the failure to debug-only logging.

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
- Unit coverage proves malformed non-list state is not clobbered, both Stop and rollover share the same identity rules,
  and a retained rollover identity moves behind distinct older records to remain the latest canonical artifact.
- `./scripts/test-integration.sh tests/integration/cli/test_artifact_hooks_integration.py` covers repeated Stop plus
  PreCompact/SessionStart boundaries.
- `make test-regression`, the focused unit suite, the required integration runner, and `make pre-commit` pass.

## Compatibility and Exclusions

- Existing manifests may contain duplicate Stop records and legacy PreCompact-shaped entries; support them on read and
  converge duplicates only at the corresponding write seam rather than requiring an eager migration. Do not silently
  treat unrelated malformed entries as the same legacy shape.
- Older `copied_path`-only records remain read-compatible and diagnostic. They lack the identity needed for safe
  migration, so reconciliation preserves them rather than inventing a `session_id`; new records always carry complete
  identity.
- Preserve artifact files, `captured_at`/reason provenance, forge-root-relative paths, rollover behavior, and shared
  transcript deletion safeguards.
- Sharing the selector is a D024 drift-control requirement that closes only O099's transcript-selector subset; its
  `_FakeResponse` family and final ledger disposition remain Wave 7 work.
- The analogous plan-artifact clobber is tracked separately as D045 in Wave 6. Do not redesign transcript retention or
  resume strategies here; replacing the existing artifact-list lookup in the two budget preflights does not expand them
  to D023's other transcript sources.

## Verification

- The two marked D007/D024 regression modules failed in six cases on `fee562ab`, then passed after implementation.
- Focused session, hook, adoption, transfer, and fork suites passed (333 tests).
- `./scripts/test-integration.sh tests/integration/cli/test_artifact_hooks_integration.py`: 12 passed.
- `make test-regression`: 658 passed.
- `make test-unit`: 8,734 passed, 1 pre-existing platform-conditional skip, 118 deselected.
- `make pre-commit`: passed after Markdown normalization; the final full run was clean.

## Outcome

Stop, SessionStart rollover, and adoption now share one canonical `(session_id, copied_path)` reconciliation seam.
Repeated writes collapse only the matching identity, distinct records survive, and malformed transcript state is
surfaced without being replaced. PreCompact writes only to its dedicated snapshot collection and lazily migrates its
recognized legacy mixed-list shape. Manager derivation, transfer assembly, and both full-strategy budget preflights now
share one strict latest-canonical selector. Malformed dedicated snapshots fail unchanged, and manager fork validates
artifact state before Git side effects. Write-side legacy migration and PreCompact corruption now emit warnings, while
the supervisor UUID and display-only model-history projections remain explicitly tolerant; D023's broader
source-resolution behavior remains deferred.
