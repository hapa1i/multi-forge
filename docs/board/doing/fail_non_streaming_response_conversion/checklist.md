# Fail non-streaming response conversion checklist

Current focus: obtain independent review and merge without weakening D053.

- [x] Close D053 after independent review and merge in PR #161 (`8088ceae`).
- [x] Activate O007 from merged `main` on `fix/fail-non-streaming-response-conversion`.
- [x] Retain an initial-response regression for the current HTTP 200 assistant fallback and `failed=false` accounting.
- [x] Retain authentication-retry parity coverage for the same conversion failure.
- [x] Preserve provider usage, reported cost, and provider-attempt trace evidence on conversion failure.
- [x] Degrade malformed usage shapes and token counts to zero without bypassing reported cost, trace, or failure
  accounting.
- [x] Return a stable provider-data-free HTTP 500 `api_error` without rethrowing into the generic exception logger.
- [x] Preserve successful conversion, `ToolCallError`, streaming/SSE, and raw Anthropic passthrough behavior.
- [x] Verify whether the existing proxy operator guide states the corrected client/accounting contract and update it if
  needed.
- [x] Run focused converter, server, accounting, provider-trace, and D053 log-hygiene tests (117 passed).
- [x] Run the full unit and regression suites plus targeted translated-proxy Docker integration (8,954 unit, 723
  regression, and three Docker cases passed; one unit skip and 122 deselections).
- [x] Run `make pre-commit`, board-link checks, change-log size, and `git diff --check`.
- [x] Record implementation outcome, verification, and deferred boundaries without closing the child epic before merge.
