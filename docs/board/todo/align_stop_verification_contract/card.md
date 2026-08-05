# Align Stop verification validation and failure reporting

**Epic**: [`epic_stop_artifact_correctness`](../epic_stop_artifact_correctness/card.md).

**Decision**: [`stop_verification_contract`](../../done/stop_verification_contract/card.md) (DG1; D006, U002–U003).

**Findings**: D006 (HIGH), U002 (MEDIUM), and U003 (LOW) in
[`review_combined.md`](../../review_combined.md#design-conformance-findings).

**Lane**: `todo/` -- accepted Wave 2 implementation work, parked.

## Goal

Make the shipped Stop hook enforce the approved two-type verification schema without silent success, while preserving
the fixed test suite as the only opt-in blocking latency exception.

## Evidence

Rechecked on merged `main` at `86fa53da`:

- `src/forge/cli/hooks/verification.py:56-63` calls fixed `uv run pytest` synchronously from the Stop decision path, and
  `src/forge/session/models.py:246` supplies a 300-second default timeout. An executable characterization injected a
  150-ms subprocess delay; `_check_test_suite` returned after 155 ms and forwarded the fixed argv and 300-second
  timeout.
- `VerificationConfig.type` and `on_incomplete` remain unconstrained strings. The unknown-type branch at
  `verification.py:130-132` silently allows Stop, while an unknown mode falls through to block at `:193`.
- DG1 removed the stale arbitrary-command and `re_inject` documentation promises, but strict authoring, legacy
  diagnostics, result classification, worktree resolution, and redaction remain implementation work.

## Expected Behavior

- New configuration accepts exactly `completion_promise | test_suite` and `block | warn | allow`; invalid authoring is
  rejected actionably.
- Legacy unknown values warn on stderr, fail open, and never persist a passing verification result.
- Fixed `test_suite` remains synchronous and bounded, runs without a shell in the resolved session worktree, and is the
  only named exception to the ordinary Stop latency contract.
- Outcomes distinguish passed, incomplete, misconfigured, and infrastructure error without turning execution or
  persistence failures into an incomplete goal or a false pass.

## Scope

- Reject new unknown `verification.type` and `on_incomplete` values actionably.
- Warn and fail open for recoverable legacy unknown values without recording a pass.
- Run `test_suite` in the resolved session worktree, retain fixed no-shell argv and timeout behavior, and redact bounded
  diagnostics before display or persistence.
- Distinguish incomplete, misconfigured, and infrastructure results; make persistence failure fail open.
- Measure Forge-owned Stop overhead separately from test subprocess wall time and keep it under 100 ms.

## Acceptance Criteria

- `tests/regression/test_bug_d006_stop_test_suite_contract.py` covers the synchronous fixed-command exception, resolved
  worktree, timeout, bounded redacted diagnostics, and infrastructure fail-open behavior.
- `tests/regression/test_bug_u002_unknown_verification_type.py` and
  `tests/regression/test_bug_u003_unknown_on_incomplete_mode.py` prove legacy unknowns are visible, fail open, and are
  never recorded as passed.
- Each regression module has `pytestmark = pytest.mark.regression` and a module docstring naming its finding and root
  cause, per the Regression Test Mandate.
- Unit tests cover missing or multiline promises, missing `uv`, persistence failure, and each valid `on_incomplete`
  mode.
- Existing iteration/minute escape hatches and `%cancel-verification` remain intact.
- `docs/design.md` and `docs/design_workflows.md` remain synchronized with the implemented behavior.

## Compatibility and Exclusions

- Preserve existing valid `completion_promise` and `test_suite` manifests plus their iteration, duration, and bypass
  state. Unknown values already stored by an older or hand-edited manifest must remain readable enough to fail open with
  a diagnostic.
- Do not add `custom_command`, a shell path, asynchronous test execution, or a general hook-job runner.
- Do not include D007/D024 artifact reconciliation or D039 sidecar shadow routing in this member.

## Verification

Run the focused Stop-hook unit suite, `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py`,
`make test-regression`, and `make pre-commit`.
