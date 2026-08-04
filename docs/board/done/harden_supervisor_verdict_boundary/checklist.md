# Harden supervisor verdict boundary checklist

Current focus: review feedback and verification are complete; the active epic owns review and merge before D005 starts.

## Evidence and Regression

- [x] Verify PR #125 merged and the D001 review/merge gate is satisfied.
- [x] Add `test_bug_d002_supervisor_confidence_fail_open.py` with malformed and valid numeric confidence controls.
- [x] Add `test_bug_d003_supervisor_violation_shape.py` for non-mapping violation elements under both engine fail modes.
- [x] Add `test_bug_d004_supervisor_citation_normalization.py` for invalid citation shapes.
- [x] Add `test_bug_o028_supervisor_unknown_verdict.py` for parse visibility, cache eligibility, and shadow outcome.
- [x] Record the expected pre-fix failures for all four finding files (`24 failed, 10 passed`).

## Implementation

- [x] Reject booleans and non-finite values as confidence while preserving finite numeric clamping.
- [x] Normalize malformed violation containers and elements without raising into engine fail-mode handling.
- [x] Use normalized citations for both stored violations and the semantic block predicate.
- [x] Preserve unknown and case-mismatched verdicts as visible parse failures through enforcement, cache, telemetry, and
  shadow classification.
- [x] Treat restored cache entries outside the clean aligned/`1.0` write shape as misses that re-evaluate.
- [x] Preserve valid aligned, cited divergent, uncited divergent, and mixed-violation decisions.
- [x] Keep workflow/team schemas, the confidence threshold, and deterministic policy semantics unchanged.

## Acceptance Tests

| Finding | Failure fixture                                                           | Required outcome                                                                 | Regression file                                                       |
| ------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| D002    | Missing, null, bool, string, NaN, infinity, and finite numeric confidence | Malformed values cannot deny; finite numbers retain clamp and threshold behavior | `tests/regression/test_bug_d002_supervisor_confidence_fail_open.py`   |
| D003    | Non-list violation container and non-mapping list entries                 | No exception or fail-closed deny under either engine mode                        | `tests/regression/test_bug_d003_supervisor_violation_shape.py`        |
| D004    | Divergent violation with string or otherwise invalid citations            | Invalid citations cannot satisfy the block requirement                           | `tests/regression/test_bug_d004_supervisor_citation_normalization.py` |
| O028    | Unknown and case-mismatched verdict literals                              | Visible fail-open parse error; no aligned cache entry or shadow agreement        | `tests/regression/test_bug_o028_supervisor_unknown_verdict.py`        |

## Verification and Closeout

- [x] Run focused semantic verdict, engine, supervisor, shadow, workflow-stage, and team-handler tests (`321 passed`).
- [x] Run Claude and Codex policy-hook adapter tests (`47 passed`).
- [x] Run the existing D001 marked regression directly (`1 passed`).
- [x] Run `make test-regression` (`632 passed`).
- [x] Run `make test-unit` (`8,702 passed, 1 skipped, 118 deselected`).
- [x] Run `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py` (`21 passed`).
- [x] Run `make pre-commit` after review follow-up.
- [x] Confirm the implementation restores the existing design contract without a normative or end-user doc change.
- [x] Record the outcome in the review ledger and `docs/board/change_log.md`.
- [x] Move the member to `done/`, repoint inbound links, and record final verification.
