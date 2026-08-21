# Explain or remove type suppressions

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `doing/` -- active as Wave 8 Batch 5 order 18 on `agent/wave8-batch-5`, based on pushed `main` at `1e0e664c`.

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

Run the suppression guard, focused touched tests, the configured mypy and pyright commands, full unit/regression suites,
and `make pre-commit`.
