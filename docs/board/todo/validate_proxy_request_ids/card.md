# Validate client request IDs at proxy ingress

**Epic**: [`epic_proxy_diagnostic_data_hygiene`](../epic_proxy_diagnostic_data_hygiene/card.md).

**Lane**: `todo/` -- accepted and parked behind the two payload-hygiene members.

**Finding**: D036 (Wave 5 MEDIUM).

## Goal

Keep useful client correlation IDs while preventing malformed, control-bearing, or overlong `X-Request-ID` values from
becoming Forge log, telemetry, audit, and response-header identifiers.

## Evidence

Rechecked on merged `main` at `c9c4bc2e`. A request ID containing whitespace and path-like syntax was adopted verbatim
by the middleware, stored on request state, interpolated into the ordinary completion log, and echoed in the response
header. The same state value feeds cost, audit, provider-trace, and request-diagnostic records. Four adjacent
`X-Forge-*` headers already validate before persistence.

## Expected Behavior

Treat `X-Request-ID` as an untrusted optional system-boundary value. Preserve conventional bounded visible-ASCII tokens;
when the value is absent or invalid, mint the endpoint's normal `req_`, `tok_`, or `inf_` identifier. Do not reject an
otherwise valid model request merely because optional correlation metadata is malformed, and do not log the rejected raw
value.

## Scope

- Define one dependency-light request-ID validator with an explicit length and character contract that covers common
  UUID/hex and `req_`/hyphen/dot token shapes.
- Apply it once in middleware before request state, downstream event IDs, logs, telemetry, and response headers diverge.
- Preserve valid client IDs exactly and preserve endpoint-specific generated prefixes for absent/invalid IDs.
- Keep upstream request-ID response-header filtering and Forge-owned response stamping unchanged.

## Acceptance Criteria

| Test                   | Fixture                                            | Assertion                                                                  | Test File                                                  |
| ---------------------- | -------------------------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Valid compatibility    | UUID, hex, `req_`, hyphen, and dot token IDs       | exact value reaches state, response, and one diagnostic/telemetry record   | `tests/src/proxy/test_server_request_id.py`                |
| Invalid fallback       | whitespace, controls, non-token bytes, overlong ID | generated prefix is used everywhere; raw value appears nowhere             | `tests/regression/test_bug_d036_unvalidated_request_id.py` |
| Endpoint prefixes      | messages, count-tokens, and root requests          | invalid/absent input yields `req_`, `tok_`, and `inf_` respectively        | `tests/src/proxy/test_server_request_id.py`                |
| Passthrough parity     | translated and Anthropic-passthrough requests      | both paths share the validated state value and Forge-owned response header | focused unit + targeted Docker proxy integration           |
| Existing Forge headers | valid and spoofed `X-Forge-*` values               | their independent validators and persistence behavior remain unchanged     | existing `test_server_forge_headers.py` coverage           |

## Compatibility and Exclusions

`X-Request-ID` acceptance is not documented as a stable Forge format. This preserves common client-generated tokens and
changes only malformed/overlong values to a Forge-generated correlation ID. No durable schema, CLI JSON, routing,
credential, or upstream-header behavior changes. Request-ID generation remains random rather than derived from rejected
input.

## Verification

Retain a marked D036 regression, run focused middleware/header/telemetry tests, the full regression suite, translated
and passthrough targeted Docker integration, and `make pre-commit`.
