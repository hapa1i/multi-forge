# Align supervisor missing-config exits

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `doing/` -- implemented and locally verified in draft PR #227; await the shared Batch 3 merge before closeout.

**Finding**: narrowed O080 (LOW correctness).

## Goal

Fail non-zero when a supervisor command requests an enabling action that cannot run because no supervisor is configured.

## Verified Evidence

`supervisor on` and `supervisor cascade on` catch `SupervisorNotConfiguredError`, print a setup instruction, and return
zero. `reload` correctly treats the same missing prerequisite as an error. The CLI style authority requires leaves with
missing required input/state and no sensible default to fail loudly.

## Acceptance Criteria

- `supervisor on` and `supervisor cascade on` report the missing configuration on stderr and exit non-zero with the
  existing actionable `set` recovery.
- Preserve idempotent success for `off`, `remove`, and `cascade off` when nothing is configured.
- Preserve configured mutation behavior, compatibility guards, and all `%policy` contracts.
- Pin stdout/stderr and exit status for every missing-config verb.

## Verification

Run focused supervisor/output tests, full unit/regression suites, targeted policy integration, and `make pre-commit`.
Update CLI docs only if they state missing-config exit semantics.
