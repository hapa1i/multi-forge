# Align Stop verification validation and failure reporting

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`stop_verification_contract`](../../done/stop_verification_contract/card.md) (DG1; D006, U002–U003).

**Lane**: `todo/` -- accepted Wave 2 implementation work.

## Goal

Make the shipped Stop hook enforce the approved two-type verification schema without silent success, while preserving
the fixed test suite as the only opt-in blocking latency exception.

## Scope

- Reject new unknown `verification.type` and `on_incomplete` values actionably.
- Warn and fail open for recoverable legacy unknown values without recording a pass.
- Run `test_suite` in the resolved session worktree, retain fixed no-shell argv and timeout behavior, and redact bounded
  diagnostics before display or persistence.
- Distinguish incomplete, misconfigured, and infrastructure results; make persistence failure fail open.
- Measure Forge-owned Stop overhead separately from test subprocess wall time and keep it under 100 ms.

## Acceptance Criteria

- Regression tests cover unknown types/modes, missing or multiline promises, missing `uv`, timeout, persistence failure,
  redaction, resolved cwd, and each `on_incomplete` mode.
- Existing iteration/minute escape hatches and `%cancel-verification` remain intact.
- `docs/design.md` and `docs/design_workflows.md` remain synchronized with the implemented behavior.

## Verification

Run focused Stop-hook unit tests, the relevant hook/session integration path, and `make pre-commit`.
