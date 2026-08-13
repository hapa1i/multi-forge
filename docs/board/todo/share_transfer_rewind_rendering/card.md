# Share transfer and rewind rendering primitives

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 session refactor work.

**Finding**: O059.

## Goal

Move common coercion/list/decision rendering to a shared session module while keeping transfer and rewind envelope,
budget, and citation semantics distinct.

## Evidence and Authority

On `5777192a`, rewind imports four private transfer helpers but still copies `_coerce_text`, `_render_str_list`, and
decision/change rendering. Earlier Wave 6 work changed rewind citation behavior, demonstrating why copied rendering
logic needs an owned seam. Authority:
[`docs/design_appendix.md` "H. Transfer Context Schema"](../../../design_appendix.md#h-transfer-context-schema) and
[`docs/design.md` "3.9 Session Resume"](../../../design.md#39-session-resume-context-management).

## Acceptance Criteria

- Public/shared rendering primitives have neutral inputs and explicit empty-label/section options.
- Golden fixtures preserve transfer markdown, rewind prompt bytes, truncation, emitted-turn tracking, and citations.
- Remove cross-module private imports where the shared helper replaces them.
- Run transfer/rewind unit, regression, and targeted rewind integration suites.

## Exclusions

Do not unify full-transfer and rewind strategies, change budget selection, or let rendered-but-truncated turns count as
emitted.
