# Strip OpenAI account response headers

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 8 order 3; parked.

**Finding**: O074 (LOW security).

## Goal

Prevent upstream OpenAI organization/project identity from being relayed to the child after Forge has already stripped
the child's account-selection headers from the request.

## Verified Evidence

Responses request construction forwards only `openai-beta`, explicitly excluding `OpenAI-Organization` and
`OpenAI-Project`. The shared response relay denylist does not exclude either account header, so an upstream value can be
returned through both supported proxy transports.

## Acceptance Criteria

- Drop `OpenAI-Organization` and `OpenAI-Project` response headers case-insensitively in the shared relay policy.
- Retain safe provider metadata, rate-limit/retry headers, connection-token filtering, and Forge's canonical request ID.
- Pin both Messages and Responses relays and mixed-case header spellings.

## Verification

Run focused response-header and passthrough tests, full unit/regression suites, targeted Docker proxy routing coverage,
and `make pre-commit`. Sync the response-relay contract in `docs/design_appendix.md` if its explicit denylist is named.
