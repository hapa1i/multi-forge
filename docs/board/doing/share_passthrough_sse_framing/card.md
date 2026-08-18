# Share passthrough SSE framing

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `doing/` -- active on `refactor/share-passthrough-sse-framing` from `1d02b0cb`; orders 31--35 remain parked.

**Finding**: O067, promoted from unverified during Wave 7 admission.

## Goal

Use one tolerant incremental SSE data-line framer in Anthropic and Responses usage accumulators while retaining their
different event merge rules.

## Evidence and Authority

Reverified on `1d02b0cb`: both `feed` methods retain the same byte-buffer, newline, `data:`, `[DONE]`, and
JSON-tolerance loop; their `_merge` methods intentionally parse different protocols. Both complete passthrough unit
files pass (126 tests), including the split-chunk and garbage fixtures. Authority: provider wire compatibility under
[`docs/developer/coding_standards.md` "System boundaries"](../../../developer/coding_standards.md#system-boundaries-external-data).

## Acceptance Criteria

- One incremental framer owns chunk buffering and tolerant JSON event delivery.
- Each transport retains its own first/final-event and usage merge semantics; framing errors remain fail-open.
- Run both full passthrough unit files, conversion/accounting regressions, and targeted streaming integration tests.

## Exclusions

Do not merge `_merge`, normalize provider events, buffer complete streams, change forwarding chunks, or alter completion
callback timing.
