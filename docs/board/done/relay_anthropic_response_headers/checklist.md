# Relay safe Anthropic response headers checklist

Completed in PR #153 (`8f030ef4`).

## Activation and reproduction

- [x] Start `fix/relay-anthropic-response-headers` from merged PR #152 at `983e4470`.
- [x] Close O001, move O004 from `todo/` to `doing/`, and advance the Wave 5 cursors without activating D018.
- [x] Add a marked O004 regression for retry/rate-limit metadata on Anthropic passthrough errors.
- [x] Confirm the retained regression fails on `983e4470` in all four 429/529 × streaming/non-streaming cases because
  the response preserves status/body but omits safe upstream headers.

## Response relay contract

- [x] Share one response-header denylist contract with Responses passthrough instead of maintaining divergent copies.
- [x] Relay safe upstream metadata on non-streaming success and error responses.
- [x] Relay safe upstream metadata on streaming success and pre-stream error responses.
- [x] Strip hop-by-hop framing, authentication challenges, cookies, content length/encoding, and upstream request ids
  case-insensitively; Forge request-id and spend-warning overlays win.
- [x] Preserve response bodies, streaming chunks, accounting callbacks, and stream teardown behavior.

## Acceptance tests

| Test                     | Fixture                                                         | Assertion                                                        |
| ------------------------ | --------------------------------------------------------------- | ---------------------------------------------------------------- |
| Retained O004 regression | 429/529 with retry/rate-limit metadata                          | status/body and safe control headers reach the downstream client |
| Non-streaming matrix     | success and error responses                                     | safe headers relay; denied headers and collisions stay stripped  |
| Streaming matrix         | opened success stream and pre-stream upstream error             | safe headers relay before the first body byte                    |
| Forge overlay            | upstream request id plus caller request-id/spend-warning values | Forge-owned values win case-insensitively                        |
| Byte preservation        | binary/error body and split SSE chunks                          | bytes are unchanged and completion/teardown fires once           |
| Proxy integration        | subprocess proxy plus hermetic Anthropic upstream               | retry/rate-limit metadata crosses the live proxy boundary        |

## Verification and closeout

- [x] Run focused passthrough, Responses-parity, and retained-regression tests: 131 passed; the full proxy unit slice
  passes 787 tests.
- [x] Run targeted Docker proxy integration through `./scripts/test-integration.sh`: 2 passed.
- [x] Synchronize normative design, operator guidance, bundled QA, review ledger, and change log with implemented
  behavior; QA now contains 624 assertions.
- [x] Run the full unit and marked regression suites: 8,921 passed / 1 skipped and 695 passed, respectively; build the
  wheel/sdist, verify the new module and both changed QA resources in the wheel, and pass `make pre-commit`.
- [x] Resolve all 206 relative paths/fragments across 15 changed Markdown files and stale-lane references; the change
  log measures 21,202 tokens / 1,432 physical lines, and diff checks pass.
- [x] Complete independent review with no findings before merge.
- [x] Merge before activating D018 (PR #153, `8f030ef4`).
