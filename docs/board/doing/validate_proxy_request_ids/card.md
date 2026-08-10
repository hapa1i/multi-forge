# Validate client request IDs at proxy ingress

**Epic**: [`epic_proxy_diagnostic_data_hygiene`](../../doing/epic_proxy_diagnostic_data_hygiene/card.md).

**Lane**: `doing/` -- active on `fix/validate-proxy-request-ids` after PR #158 shipped D035.

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

## Implementation Outcome

- Added a dependency-light request-ID validator with the exact `[A-Za-z0-9._-]{1,128}` contract. It is a
  `TypeGuard[str]`, rejects rather than normalizes, and preserves every accepted value byte-for-byte.
- Applied the validator once in HTTP middleware before request state and downstream event identity are created. Absent
  or invalid values receive the existing `req_`, `tok_`, or `inf_` prefix for their endpoint.
- Replaced every supplied `X-Request-ID` header in the shared ASGI header view with the resolved safe value before
  downstream audit/header consumers run. The middleware materializes the ASGI header iterable before any cached header
  view; duplicate headers are treated as ambiguous and receive a generated ID.
- Pinned the direct `core.llm` minter to the same validator so a future request-ID format change cannot silently dangle
  `source_refs.cost_request_id` joins.
- Kept translated and Anthropic-passthrough routing, upstream response-header filtering, and all four `X-Forge-*`
  validators unchanged. Normative design docs now record the ingress and cross-plane join boundary.

## Verification

On merged base `ce7eb1ec`, the retained module failed five invalid-header assertions because raw values reached request
state, downstream event keys, ordinary logs, and response headers; four conventional-ID controls passed. After
implementation, its ten cases pass, including a full-body audit assertion against a fresh downstream `Request`. A
125-test review-focused slice and two hermetic Docker cases pass; the Docker cases prove translated and passthrough
logs/telemetry use the generated ID and omit the raw canary. Targeted mypy passes; the full unit suite passes 8,954
tests with one skip and 122 deselections, and the full regression suite passes all 716 tests. The first full pre-commit
run passed every code gate and let mdformat rewrite the new evidence; clean reruns, including ones after
downstream-header and independent-review hardening, passed all hooks. Board links, stale-lane, size, and diff checks
pass.
