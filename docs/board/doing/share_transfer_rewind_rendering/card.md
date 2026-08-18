# Share transfer and rewind rendering primitives

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `doing/` -- implementation and verification complete on `refactor/share-transfer-rewind-rendering` from
`7c925880`; pending independent review.

**Finding**: O059.

## Goal

Move common coercion/list/decision rendering to a shared session module while keeping transfer and rewind envelope,
budget, and citation semantics distinct.

## Evidence and Authority

Reverified on `7c925880`: rewind imports four private transfer helpers but still copies `_coerce_text`,
`_render_str_list`, and decision/change rendering. Earlier Wave 6 work changed rewind citation behavior, demonstrating
why copied rendering logic needs an owned seam. Authority:
[`docs/design_appendix.md` "H. Transfer Context Schema"](../../../design_appendix.md#h-transfer-context-schema) and
[`docs/design.md` "3.9 Session Resume"](../../../design.md#39-session-resume-context-management).

## Acceptance Criteria

- Shared module-level rendering primitives have neutral inputs and explicit empty-label/section options.
- Golden fixtures preserve transfer Markdown and rewind prompt bytes; existing tests retain the current truncation,
  emitted-turn, and citation boundaries.
- Remove the duplicated local rendering helpers without adding a new transfer-to-rewind private import.
- Run transfer/rewind unit, regression, and targeted rewind integration suites.

## Exclusions

Do not unify full-transfer and rewind strategies or change budget/emitted-turn selection. O018's separately gated
rendered-but-truncated citation defect remains outside this behavior-preserving refactor. Existing non-rendering private
imports from `transfer` also remain outside this member; reconsidering their ownership is a follow-up candidate.
