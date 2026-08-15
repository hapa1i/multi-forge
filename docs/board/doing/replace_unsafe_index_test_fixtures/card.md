# Replace unsafe index test fixtures

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `doing/` -- active on `refactor/replace-unsafe-index-test-fixtures` from `74b364d2`.

**Finding**: O050's caller-migration phase.

## Goal

Provide transaction-safe test builders and migrate direct public-index mutator calls before those APIs are deleted.

## Evidence and Authority

Reverified on `74b364d2`: 180 executable invocations across 48 test files use `add_session`, `add_from_state`, or
`remove_session` to construct states that production cannot create safely (179 Python AST calls plus one embedded
integration script; the raw textual count of 183 also includes three test docstrings). Authority:
[`docs/design.md` "3.2 Contract files"](../../../design.md#32-contract-files-authoritative-paths) and
[`docs/developer/testing_guidelines.md` "Real Over Mock"](../../../developer/testing_guidelines.md#testing-philosophy-real-over-mock).

## Acceptance Criteria

- Shared fixtures create/delete coherent index row plus manifest state through production transaction contracts or
  narrowly scoped fixture builders that enforce the same invariants.
- Migrate callers without weakening deliberate corrupt/orphan/race fixtures; those fixtures construct invalid state
  explicitly and document why.
- Preserve row-first creation, compensation, binding uniqueness, lock order, and ownership-aware deletion assertions.
- Run the full session/index unit and regression slices plus targeted session integration tests.

## Exclusions

This card does not delete the public methods. That occurs only in
[`retire_unsafe_index_mutators`](../../todo/retire_unsafe_index_mutators/card.md) after a zero-caller recheck.
