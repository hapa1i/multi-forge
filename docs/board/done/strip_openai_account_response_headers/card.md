# Strip OpenAI account response headers

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #218 (`4cd859cb`) on 2026-08-20.

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

## Boundary

The shared relay remains deny-by-name. Adding a provider or wire shape requires re-enumerating its account-identity
response headers; this member closes only the verified OpenAI selectors.

## Verification

Run focused response-header and passthrough tests, full unit/regression suites, targeted Docker proxy routing coverage,
and `make pre-commit`. Sync the response-relay contract in the former consolidated design appendix if its explicit
denylist is named.
