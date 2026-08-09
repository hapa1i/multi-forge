# Relay safe Anthropic response headers

**Epic**: [`epic_cli_proxy_runtime_correctness`](../epic_cli_proxy_runtime_correctness/card.md).

**Finding**: O004 (HIGH) in [`review_combined.md`](../../review_combined.md#code-and-maintenance-findings).

**Lane**: `done/` -- shipped in PR #153 (`8f030ef4`).

## Goal

Relay safe Anthropic upstream response metadata, including retry/rate-limit guidance, without forwarding hop-by-hop or
security-sensitive headers.

## Design Authority

- [`responses_passthrough.py` header relay contract](../../../../src/forge/proxy/responses_passthrough.py): the sibling
  passthrough forwards all response headers except an explicit hop-by-hop/security/proxy-owned denylist.
- [`docs/design.md` §7 audit passthrough contract](../../../design.md#7-isolation-and-proxy-modes): Anthropic
  passthrough preserves its upstream wire result while Forge adds only its own correlation/accounting behavior.

## Evidence

Rechecked on merged `main` at `983e4470` with upstream 429 and 529 responses carrying `retry-after` and
`anthropic-ratelimit-requests-remaining`. All four streaming/non-streaming cases preserved status and body but returned
neither header because the Anthropic paths construct responses from Forge-owned headers only. The Responses sibling
already applies a denylist relay.

## Expected Behavior

- Non-streaming, streaming success, and streaming error responses relay safe upstream headers.
- Hop-by-hop framing, credentials/auth challenges, cookies, content length/encoding, and upstream `x-request-id` remain
  stripped; Forge's request id and spend-warning headers win.
- Response bodies and streaming chunks remain byte-for-byte unchanged.

## Acceptance Criteria

- Add a marked O004 regression for retry/rate-limit relay on 429/529.
- Cover success/error and streaming/non-streaming paths, case-insensitive denylist collisions, and Forge header overlay.
- Share or pin denylist parity with Responses passthrough; run focused relay/server tests, targeted proxy integration,
  and `make pre-commit`.

## Compatibility and Exclusions

- Do not forward upstream authentication/cookie fields or hop-by-hop framing.
- Do not change request-header allowlists, passthrough body mutation rules, accounting callbacks, or stream teardown.
