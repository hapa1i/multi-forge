# OpenRouter Responses execution checklist

The [card](card.md) is implemented and ready for merge review on `codex/openrouter-responses-by-default`.

## Implementation and verification

- [x] Reproduce the translated-proxy refusal and the explicit Responses profile's incorrect Claude audit status.
- [x] Use the same Responses eligibility for saved preflight, configuration, live advertisement and request dispatch.
  Verify legacy snapshots without rewriting them and distinguish a stale listener from a different proxy.
- [x] Report inspection and reasoning per endpoint, label new audit records and disclose the active policy at launch.
- [x] Select exactly one endpoint for each smoke check and include it in human and JSON results.
- [x] Verify endpoint routing, cap recovery and unreported-cost behavior with the loopback upstream.

| Fixture                                                                           | Observable result                                                                                                             |
| --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Saved translated `cyan-coconut` and bundled OpenRouter templates                  | Both clients use one listener, saved bytes and effective Claude tier maps match the originals, Codex continues a tool call    |
| Missing backend, conflicting backend, local Responses source and older live roots | Direct OpenRouter policy and accounting apply only to eligible sources, wrong identity and restart have distinct remedies     |
| Inspect mode on an explicit Responses profile                                     | Claude shows `(lossy)`, Messages audit carries its route, Codex reports the lack of body audit and the saved routing policy   |
| Bare and explicit smoke probes                                                    | A single endpoint receives the expected model and the command identifies which endpoint ran                                   |
| Unpriced Responses and two one-cent generations                                   | Default refusal affects the next Responses create, a saved allow is honored, either endpoint enforces the shared two-cent cap |

## Upgrade evidence

On 2026-11-21 a temporary Forge home ran the tagged 1.1.8 server and launcher with a translated `openrouter-gemini`
instance named `cyan-coconut`. Its launcher refused with `wire_shape=openai_translated`. Against that same listener, the
new launcher named `forge proxy stop cyan-coconut` and `forge proxy start cyan-coconut`. Restarting with the working
tree selected `google/gemini-4-neon` and preserved the original saved bytes. The 1.1.8 launcher still refused the new
listener on the translated profile.

With 1.1.8 serving the explicit Responses profile in inspect mode, its Claude segment rendered `aud:inspect` without
`(lossy)`. The new launcher accepted that running listener and reported the lack of Responses body audit. These checks
stubbed the Codex child after argument construction and sent no inference traffic.

## Client and accounting evidence

- Claude Code 2.1.245 and Codex CLI 0.169.0-alpha.11.1 used one translated `cyan-coconut` in a Docker container with
  external networking disabled. The Claude print command selected Haiku and returned the fixture text through Hydrogen.
  The Codex exec command selected the default Neon model, read a marker from `fixture.txt` and sent the matching tool
  output on the next Responses create. The upstream observed required ZDR.
- The 47 Docker and loopback integration cases passed, including both endpoints charging one cent and then refusing at
  the shared two-cent limit. An unpriced Responses smoke exited nonzero, a subsequent Responses create was blocked
  before dispatch, and a Messages smoke passed. The saved `allow` admitted the unpriced create and disclosed it at
  launch. The template matrix also checks effective Claude defaults, alternatives and overrides for all 11 bundled
  OpenRouter templates. [Integration tests](../../../../tests/integration/proxy/test_codex_openrouter_responses_e2e.py)
  · [Template matrix](../../../../tests/src/config/test_proxy_block_wiring.py)
- The clean-wheel LiteLLM start, health and cleanup check passed.

## Implementation note for human review

The existing [launcher invariant](../../impl_notes/runtime_telemetry.md) needs the direct OpenRouter exception. Verify
the live ID, template, affirmative ingress and direct policy on every OpenRouter profile. Retain the wire-shape gate for
local Responses. Use the actual endpoint for body audit, reasoning preservation and smoke selection. The proposal is
also recorded in the local shadow implementation notes.

## Closeout

- [x] Sync design, CLI, end-user and verification docs, and prepare the durable note correction for human review.
- [x] `make test-unit` passed 12,047 tests. `make test-regression` passed 2,703. The 47 targeted integration cases,
  `make pre-commit`, repository file limits and the Markdown link audit passed. Two tests comparing a watchdog deadline
  and policy-feedback timing failed during concurrent suite runs and passed when the full suites ran separately.
- [x] Record the verified feature in the [change log](../../change_log.md).
- [ ] Move the card to `done/` and update inbound links when the implementation lands on `main`.
