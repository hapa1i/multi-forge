# Share transfer and rewind rendering primitives checklist

Current focus: active -- order 29 only; orders 30--35 remain parked.

## Activation and evidence

- [x] Close order 28 on pushed `main` at `7c925880`, create the execution branch from that exact commit, and move only
  this member to `doing/`.
- [x] Re-run source, caller, import, and test searches for transfer and rewind text, list, and cited-item rendering.
- [x] Confirm the common renderers are byte-equivalent while envelopes, input budgets, emitted-turn tracking, and
  citation validation remain strategy-owned.
- [x] Confirm O018's pre-existing truncated-turn citation defect remains separately gated; do not move or pin that
  behavior as part of O059.
- [x] Record the focused transfer/rewind baseline before implementation (188 passed).

## Implementation

- [x] Add neutral shared module-level session rendering primitives with explicit section-title, empty-state, and
  citation-label inputs.
- [x] Route transfer and rewind rendering through the shared primitives and remove the duplicate local helpers.
- [x] Add byte-level transfer-document, rewind-document, and rewind-prompt fixtures plus direct shared-helper coverage.
- [x] Record shared rendering ownership in the normative transfer-context design section.

## Acceptance tests

| Boundary           | Fixture                                           | Assertion                                                           | Test file                                     |
| ------------------ | ------------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------- |
| Text coercion      | strings, whitespace, and non-strings              | only trimmed non-empty strings survive                              | `tests/src/session/test_context_rendering.py` |
| Plain lists        | mixed list and non-list input                     | stable bullets and caller-selected empty line                       | `tests/src/session/test_context_rendering.py` |
| Cited items        | mappings, strings, blank values, and citations    | stable citation suffix and caller-selected label/empty line         | `tests/src/session/test_context_rendering.py` |
| Transfer document  | full curated payload                              | complete Markdown bytes, section order, and citations are unchanged | `tests/src/session/test_transfer.py`          |
| Rewind code delta  | full curated payload and dropped-window source    | complete Markdown bytes and distinct empty-state wording are stable | `tests/src/session/test_rewind_strategy.py`   |
| Source preparation | oversized and sparsely renderable transcript data | truncation and emitted-turn citation anchors remain strategy-owned  | existing transfer and rewind tests            |

## Verification and closeout

- [x] Run focused transfer/rewind unit and relevant regression tests (198 passed).
- [x] Run `make test-unit` (9,259 passed, one skipped, 122 deselected) and `make test-regression` (923 passed).
- [x] Run the real-Claude targeted Docker rewind integration suite (one passed).
- [x] Run full `make pre-commit`, diff checks, design-size checks (29,989 / 29,937; change log 29,922), and the board
  audit (365 documents, 894 local links, zero missing; 14 proposed / nine todo / three doing / 163 done / four retired)
  without a Forge workflow.
- [ ] Open the order-29 PR and close this member after merge without activating order 30.
