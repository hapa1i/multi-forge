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

## Review verification

- A translated OpenRouter Messages smoke received a 503, reread the live route and passed after the second POST. A
  direct Responses smoke sent one create after a successful discovery, including when the first discovery needed a
  retry. Human smoke output appeared before the upstream request. JSON output contained only the creation result.
- Saved preflight, the Codex launcher and `proxy set` identified the HTTPS requirement on a remote HTTP base. The failed
  edit preserved the saved bytes. New Messages audit records use the same `messages` value as smoke JSON.
- Promoted the reviewed source and identity rules and the JSON-value preservation contract to the
  [launcher implementation note](../../impl_notes/runtime_telemetry.md#sessionless-codex-proxy-launcher).
- With `priority` saved in a disposable Codex home, Codex 0.171.0 completed two turns on the translated Gemini proxy
  without either the service-tier or shared-server warning. The loopback upstream saw the saved Neon slug and no
  `service_tier` on all four requests. An explicit `-c 'service_tier="flex"'` sent `flex` on all four. Codex 0.141.0
  completed the same default launch. The pinned 0.170.0 TUI self-test also passed both models' read and follow-up edit.

## Closeout

- [x] Sync design, CLI, end-user and verification docs and record the reviewed launcher invariant.
- [x] `make test-unit` passed 12,055 tests and `make test-regression` passed 2,708. All 47 targeted integration cases,
  `make pre-commit`, repository file limits and the 810-file Markdown link audit passed.
- [x] Record the verified feature in the [change log](../../change_log.md).
- [ ] Move the card to `done/` and update inbound links when the implementation lands on `main`.
