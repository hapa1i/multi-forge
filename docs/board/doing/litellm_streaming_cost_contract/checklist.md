# LiteLLM streaming cost contract checklist

**Current focus:** Review and merge the verified contract update, then record closeout. Results are recorded in
[verification](verification.md). Base: `ee71ddd4`. Branch: `codex/litellm-streaming-cost-contract`. No paid provider
calls are authorized.

## Characterization and implementation

- [x] Verify the obsolete integration assertion against pinned LiteLLM 1.102.0 and Forge's stream client.
- [x] Confirm LiteLLM cost maps to `reporter=litellm` / `confidence=gateway_calculated` in proxy accounting.
- [x] Characterize the pinned gateway's final usage with offline inputs; retain evidence of the observed fields.
- [x] Cover streamed body cost, explicit zero, absent cost and absent final usage through the real SDK transport
  boundary.
- [x] Replace the universal-unavailability integration expectation with deterministic cost-present/cost-absent coverage.
- [x] Verify downstream telemetry and spend caps account for one completed stream exactly once, with tokens preserved.
- [x] Keep absent cost unavailable and avoid local price estimates or runtime changes beyond any verified contract
  defect.
- [x] Correct client comments, telemetry design and affected end-user cost guidance.

## Acceptance matrix

| Case                             | Evidence required                                                                 |
| -------------------------------- | --------------------------------------------------------------------------------- |
| Gateway-calculated streamed cost | Final usage carries cost; Forge preserves amount and labels the gateway           |
| Cost omitted                     | Exact usage remains observable; nullable cost/reporter and unavailable confidence |
| Final usage omitted              | Existing token fallback remains; no invented spend                                |
| Duplicate terminal cost surfaces | One downstream attempt and one cap increment despite usage/response-end events    |
| Explicit zero                    | Available zero cost remains distinct from missing cost                            |
| Older/remote gateway             | Behavior follows received fields, not gateway location or an assumed version      |

## Verification and delivery

- [x] Prepare locked dependencies with `make deps`.
- [x] Run focused unit/component tests and relevant regressions.
- [x] Run focused proxy integration coverage with `./scripts/test-integration.sh` and no paid calls.
- [x] Verify cost/metrics read surfaces against isolated telemetry fixtures.
- [x] Run aggregate tests and `make pre-commit`: 11,234 units and 2,212 regressions passed; all pre-commit hooks passed.
- [x] Refresh final documentation token-cache entries and check board links: telemetry 23,461 and proxy 22,489 Claude
  Opus 5 tokens; all cached hashes and board links match.
- [x] Prepare a reviewable PR with exact verification and limitations.
- [ ] After merge, record closeout and move the card to done.
