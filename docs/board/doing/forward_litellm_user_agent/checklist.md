# Forward LiteLLM User-Agent metadata checklist

Current focus: publish the independently reviewed provider-gate repair before activating O004.

## Activation and reproduction

- [x] Start `fix/forward-litellm-user-agent` from merged PR #151 at `efbefce9`.
- [x] Close D017, move O001 from `todo/` to `doing/`, and advance the Wave 5 cursors without activating O004.
- [x] Add a marked O001 regression that drives `create_message` through the translated route with
  `ModelProvider.LITELLM`.
- [x] Confirm the retained regression fails on `efbefce9` with `KeyError: '_user_agent'` because the route omits the
  metadata before the adapter.

## Metadata boundary

- [x] Gate forwarding on the collapsed `ModelProvider` enum instead of backend-instance provider string literals.
- [x] Preserve the inbound User-Agent as internal `_user_agent` metadata for translated LiteLLM and OpenRouter routes.
- [x] Keep a missing User-Agent as a no-op and leave authorization, cookies, API keys, and `X-Forge-*` headers out.
- [x] Keep control-character stripping and the 256-character cap at the existing adapter boundary.
- [x] Leave Anthropic-native and Responses passthrough header allowlists unchanged.

## Acceptance tests

| Test                     | Fixture                                                   | Assertion                                                    |
| ------------------------ | --------------------------------------------------------- | ------------------------------------------------------------ |
| Retained O001 regression | translated LiteLLM request with Claude Code User-Agent    | route hands `_user_agent` to the adapter                     |
| LiteLLM route matrix     | local/remote route labels; streaming/non-streaming        | both collapsed LiteLLM routes carry metadata                 |
| Missing/malicious values | absent header; control characters; overlong value         | absent stays absent; adapter strips controls and caps length |
| OpenRouter parity        | translated OpenRouter request                             | existing User-Agent forwarding remains enabled               |
| Header exclusion         | authorization, cookie, and `X-Forge-*` inputs             | no additional internal metadata or upstream headers appear   |
| Proxy integration        | subprocess proxy plus hermetic OpenAI-compatible upstream | sanitized User-Agent reaches the actual upstream request     |

## Verification and closeout

- [x] Run focused route, conversion, adapter, and retained-regression tests: 49 passed.
- [x] Run targeted Docker proxy integration through `./scripts/test-integration.sh`: 1 passed.
- [x] Synchronize normative design, operator guidance, bundled QA, review ledger, and change log with the implemented
  behavior; QA now contains 623 assertions and the change log measures 21,014 tokens / 1,417 physical lines.
- [x] Run the full unit and marked regression suites: 8,913 passed / 1 skipped and 691 passed, respectively.
- [x] Build the wheel and sdist, verify both changed bundled QA resources in the wheel, and pass `make pre-commit`.
- [x] Resolve all 205 relative paths/fragments across 15 changed Markdown files, stale-lane references, and diff checks.
- [x] Receive independent review and resolve its D017 ledger-closeout and mechanical staging findings before PR
  publication.
- [ ] Merge before activating O004.
