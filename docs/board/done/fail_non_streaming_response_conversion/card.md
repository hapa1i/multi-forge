# Fail non-streaming response conversion truthfully

**Epic**: [`epic_proxy_conversion_failure_handling`](../epic_proxy_conversion_failure_handling/card.md).

**Lane**: `done/` -- shipped in PR #162 (`31a0832f`) after independent review.

**Finding**: O007 (Wave 5 MEDIUM).

## Goal

Report a translated non-streaming provider response that Forge cannot convert as a server failure, not a successful
assistant turn, while retaining any provider usage/cost evidence present in the response.

## Evidence

Rechecked on merged `main` at `de02b09b`. A provider response whose `id` was a mapping triggered Pydantic validation,
but `convert_openai_to_anthropic` caught it and returned a normal `MessagesResponse` with `stop_reason="end_turn"`, zero
usage, and provider-derived exception text as assistant content. `create_message` then returned HTTP 200 and recorded
cost and metrics with `failed=false` and no error type, leaving its existing `if not anthropic_response` 500 branch
unreachable for this failure.

## Expected Behavior

[`docs/developer/coding_standards.md` §5](../../../developer/coding_standards.md#system-boundaries-external-data)
requires a critical external-response failure to fail clearly. The proxy's documented metrics contract distinguishes
failed requests and failed-token spend; a response that reached the provider but cannot reach the client must retain
observed usage while recording the client outcome as failed.

## Scope

- Replace the non-streaming converter's successful assistant fallback with an explicit failure signal that the route
  handles as a stable provider-data-free HTTP 500 `api_error`.
- Do not rethrow the provider validation exception into the generic server logger; preserve D053's metadata-only
  conversion-failure boundary.
- Apply the same contract to the initial completion and the post-authentication-retry conversion path.
- Record cost and metrics as failed while retaining provider-reported input, output, cached-token, and cost values.
- Preserve the provider-attempt trace when the upstream response arrived; do not relabel a successful provider call as a
  provider transport failure.
- Preserve successful conversion, `ToolCallError` 400 behavior, translated streaming/SSE handling, and raw Anthropic
  passthrough.

## Acceptance Criteria

| Test                        | Fixture                                             | Assertion                                                                 | Test File                                                      |
| --------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Client failure truth        | invalid provider response on the initial completion | stable HTTP 500 `api_error`; no assistant success or client/log plaintext | `tests/regression/test_bug_o007_conversion_failure_success.py` |
| Accounting truth            | invalid response with provider usage/cost metadata  | cost/metrics retain observed amounts and record `failed=true`             | same regression + focused server tests                         |
| Authentication-retry parity | refreshed client returns the same invalid response  | retry path produces the same 500 and failed accounting                    | same regression                                                |
| Provider trace control      | upstream response carries provider metadata         | attempt/lifecycle trace remains recorded without response content         | same regression + focused provider-trace tests                 |
| Healthy controls            | valid initial and post-auth-retry responses         | existing HTTP 200 body, accounting, and trace behavior remain unchanged   | existing converter/server and auth-retry coverage              |

## Compatibility and Exclusions

This intentionally changes one erroneous external outcome from HTTP 200 assistant content to a stable HTTP 500 error. No
config or durable schema changes. Streaming conversion errors retain their existing in-band SSE contract; provider
transport failure traces (O045), task ownership (O041), and unrelated `ToolCallError` handling remain separate.

## Implementation Outcome

- The non-streaming converter now returns an explicit `None` failure signal after D053's metadata-only ERROR record; it
  no longer fabricates an assistant `end_turn` or embeds exception text in client content.
- One terminal route helper handles the initial and authentication-retry paths. It returns the same stable HTTP 500
  `api_error`, records observed input/output/cached tokens and reported cost as failed, retains the completed provider
  attempt trace, and avoids the generic exception logger and duplicate zero-value accounting. Malformed external usage
  shapes or token counts degrade to zero-token accounting without bypassing the reported cost or provider trace.
- Successful conversion, `ToolCallError`, streaming/SSE, and raw Anthropic passthrough paths remain unchanged. The
  operator guide now states the corrected client, failed-spend, trace, and plaintext boundaries.

## Verification

The three original retained O007 tests failed against merged base `8088ceae`: the converter returned a successful
assistant fallback, both route paths returned normally, and the retry path recorded `failed=false`. During review, a
fourth regression failed against the initial implementation because malformed usage reached the generic catch-all and
bypassed reported-cost and provider-trace recording. All four now pass together with D053's three metadata-only
controls. The focused converter, server, accounting, provider-trace, and log-hygiene slice passes 117 tests. The full
unit suite passes 8,954 tests with one skip and 122 deselections, the full regression suite passes 723 tests, and the
hermetic translated-proxy Docker slice passes all three healthy-route cases after rebuilding its images. The first
pre-commit run passed every code, type, and secret-scanning hook before mdformat normalized the edited board Markdown.
An explicit new-file pass then caught and corrected the regression fixture's generator annotation; final all-files and
new-file passes plus board links, stale-lane, change-log size, and diff checks pass. Independent review's
malformed-usage concern is retained by the fourth regression, and all five GitHub checks passed. Shipped in PR #162
(`31a0832f`).
