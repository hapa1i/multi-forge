# Explain or remove type suppressions

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 8 order 18; parked.

**Finding**: narrowed O100 (LOW conformance).

## Goal

Make every production `# type: ignore[...]` either unnecessary or paired with the concrete runtime invariant that makes
the suppression safe.

## Verified Evidence

Current `src/forge` contains 13 suppressions without a reason comment across policy CLI/workflow parsing, status-line
numeric narrowing, session repair, usage summary, installer/runtime removal, semantic plan normalization, and proxy
client construction. Other suppressions already demonstrate the required `# type: ignore[...]  # reason` form.

Authority: [`coding_standards.md` Comments](../../../developer/coding_standards.md#comments).

## Acceptance Criteria

- Prefer explicit narrowing, `cast`, or corrected annotations when it removes a suppression without runtime change.
- Where a checker limitation remains, add a specific invariant/reason on the same line.
- Add a fast source guard requiring a non-empty reason after every production `type: ignore` so the rule cannot drift.
- Preserve runtime behavior and keep mypy, pyright, ruff, and formatting clean.

## Verification

Run the suppression guard, focused touched tests, `make type-check`, full unit/regression suites, and `make pre-commit`.
