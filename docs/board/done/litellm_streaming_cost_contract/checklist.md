# LiteLLM streaming cost contract checklist

**Status:** Done on 2026-10-29. [PR #286](https://github.com/hapa1i/multi-forge/pull/286) is merged; results are
recorded in [verification](verification.md). Base: `ee71ddd4`. Branch: `codex/litellm-streaming-cost-contract`. No paid
provider inference was authorized or dispatched.

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
- [x] Open a reviewable PR with exact verification and limitations:
  [PR #286](https://github.com/hapa1i/multi-forge/pull/286).
- [x] After merge, record closeout, repoint inbound links and move the card to done.

## Merged closeout

- [PR #286](https://github.com/hapa1i/multi-forge/pull/286) merged as `bbb9e269` on 2026-10-29. The merged tree matches
  reviewed head `890173c4`; all five CI checks passed: test, pre-commit, CodeQL, Analyze (python), and Analyze
  (actions).
- Local verification passed 11,234 unit tests, 2,212 regressions, 89 focused cost tests, eight targeted proxy
  integrations and full pre-commit. The [evidence](verification.md) retains the offline pinned-gateway probe, SDK
  transport cases, telemetry/cap accounting and operator read surfaces. No paid provider inference ran.
- [Telemetry design](../../../design_telemetry.md#314-cost-tracking-and-spend-caps) and
  [end-user cost guidance](../../../end-user/proxy.md#cost-tracking-and-spend-caps) describe gateway-calculated streamed
  cost, unavailable fallback and single cap increments. Final cached counts are 23,461 and 22,489 Opus tokens; content
  hashes match. Production logic and the LiteLLM pin remain unchanged.
- Existing
  [ledger invariants](../../impl_notes/runtime_telemetry.md#upstreamdownstream-telemetry-ledgers-shipped-2026-06-18)
  already cover nullable cost and per-attempt idempotency. The corrected streaming contract is recorded in the design
  and user guides, so no duplicate implementation note is needed. The change log records closeout, and inbound board
  links now point to `done`.
- Closeout validation passed `make pre-commit-md`, cached-content hash checks and `git diff --cached --check`.
