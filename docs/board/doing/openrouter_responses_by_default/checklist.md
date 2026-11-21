# OpenRouter Responses execution checklist

Current focus is verifying the [card](card.md) on `codex/openrouter-responses-by-default`.

## Implementation and verification

- [x] Reproduce the translated-proxy refusal and the explicit Responses profile's incorrect Claude audit status.
- [ ] Use the same Responses eligibility for saved preflight, configuration, live advertisement and request dispatch.
  Verify legacy snapshots without rewriting them and distinguish a stale listener from a different proxy.
- [ ] Report inspection and reasoning per endpoint, label new audit records and disclose the active policy at launch.
- [ ] Select exactly one endpoint for each smoke check and include it in human and JSON results.
- [ ] Verify endpoint routing, cap recovery and unreported-cost behavior with the loopback upstream.

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
tree selected `google/gemini-4-neon` and preserved the original saved bytes.

With 1.1.8 serving the explicit Responses profile in inspect mode, its Claude segment rendered `aud:inspect` without
`(lossy)`. The new launcher accepted that running listener and reported the lack of Responses body audit. These checks
stubbed the Codex child after argument construction and sent no inference traffic.

## Closeout

- [ ] Sync design, CLI, end-user and verification docs, and prepare the durable note correction for human review.
- [ ] Record aggregate unit, regression, targeted integration, pre-commit and board/link results.
- [ ] Record verified completion in the change log and move the card to its closing lane.
