# Gemini 4 Neon and Hydrogen execution

Current focus: implementation verified on branch `neon`; awaiting review and merge.

## Implementation

- [x] Confirm provider identities, thinking levels, context, output limits, caching, pricing, and ZDR availability
  against primary sources.
- [x] Add both catalog entries, provider aliases, and routes; move the Gemini defaults to Hydrogen and Neon.
- [x] Move fresh Gemini templates to the new defaults, keep Carbon and Gemini 3.8 Flash selectable, and pin Haiku to
  `low` on the Pro-family templates.
- [x] Add complete local LiteLLM deployments and send native thinking levels, leaving both models outside the Vertex
  unary clamp.
- [x] Add explicit workflow workers for Hydrogen and the prior Carbon default.
- [x] Update runtime design, model-selection, proxy, and workflow guidance, the verification guide, and packaged QA
  expectations.
- [x] Fix the review findings: send a separate system instruction for all four Gemini 4 models, sign unsigned tool
  history on LiteLLM routes, add Flex and Priority rates for Neon and Hydrogen, and correct the migration, effort, and
  policy guidance.

## Verification

| Check                        | Fixture                                              | Assertion                                                                           |
| ---------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Catalog and route resolution | Neon and Hydrogen provider aliases                   | One canonical model each; routes match Carbon and Flash coverage                    |
| Defaults                     | Packaged catalog and fresh template realizations     | Neon serves Sonnet/Opus; Hydrogen serves Haiku and Flash tiers                      |
| Effort resolution            | Explicit, derived, and opted-in client effort        | `xhigh` resolves; an opted-in `max` clamps to `xhigh`; off clamps to `low`          |
| Native request shape         | Recorded LiteLLM streaming and unary requests        | `thinkingConfig` carries all four levels; sampling is filtered                      |
| Vertex output limit          | Recorded `vertex_ai/` unary request at 65,536 tokens | Neither model is clamped; Carbon and Argon still clamp to 32,768                    |
| Gateway metadata             | Packaged LiteLLM map and isolated registration       | Override still needed; prices and `xhigh` passthrough hold                          |
| Upgrade ownership            | Saved Carbon proxy snapshot                          | Saved bytes, tiers, and alternatives remain unchanged                               |
| Policy helpers               | Plan-check and team-tagger defaults                  | Both stay on Gemini 3.8 Flash                                                       |
| Live tool round trip         | OpenRouter with required ZDR routing                 | Streaming and unary tool calls resolve both `google/` model slugs                   |
| System instruction           | Bundled deployments registered on pinned LiteLLM     | Google-bound body carries `system_instruction`; the user turn holds only user text  |
| Foreign tool history         | Unsigned Claude tool call replayed on each route     | LiteLLM routes send a placeholder signature; Google AI and OpenRouter continue live |
| Service-tier cost            | Flex and Priority usage on Neon and Hydrogen         | Reported cost is 0.5 and 1.8 times Standard                                         |

- [x] Record the failing run before implementation.
- [x] Run focused unit and regression checks and targeted Docker integration tests.
- [x] Run aggregate unit and regression suites, pre-commit, build, and clean-wheel checks.
- [x] Record evidence and remaining limitations.

## Closeout

- [x] Review the complete diff and synchronize the changelog when implementation is verified.
- [ ] Merge, record shipped closeout, and move the card to `done/`.

## Evidence and limits

The branch was rebased onto `main` at `819717bd`, then changed again for the review findings. Results are from that
final tree unless a line says otherwise.

- Before implementation, the new catalog and LiteLLM client tests failed 117 of 139 cases and the template tests failed
  5 of 5. The 22 early passes hold vacuously for an uncataloged model.
- Before the review fixes, the request-shape test failed 8 of 8 on the missing system instruction, the unsigned
  tool-history regression failed 24 of 40, and both tier-pricing cases failed with Flex charged at the Standard rate.
  Through Forge's proxy, continuing a Claude tool call failed with HTTP 500 on Google AI for Neon and Hydrogen and
  passed on OpenRouter for both.
- Direct requests through the packaged gateway to Google AI replayed one unsigned tool call. Gemini 3.8 Flash answered.
  Neon, Hydrogen, Carbon, and Argon returned HTTP 400 for a missing `thought_signature`, and all four answered once the
  call carried the placeholder. A parallel batch needs it on the first call only; each later step needs its own. A call
  signed by one Gemini model continued on another in every pairing tried.
- `make test-unit`: 11,950 passed. Before the rebase, two runs each had one failure, both in the slowest runs. One was
  `test_watchdog.py::test_deadline_reports_timeout`, a subprocess-deadline timing test in `core/reactive` that this
  change does not touch; the other run's failing test was not captured.
- `make test-regression`: 2,604 passed. Before the rebase, one run failed
  `test_bug_session_delete_preview_index_mutation.py::test_replacement_during_confirmation_is_preserved` once; it passed
  four isolated reruns and is also outside this change.
- `make test-integration`: 593 passed with no reruns. `main` alone passes 582. This run deselects the slow-marked
  session-routing and default-tier modules, so it is not evidence for live Neon or Hydrogen requests. Its hermetic cases
  prove a unary `vertex_ai/gemini-4-neon` request keeps 65,536 tokens while Carbon keeps its 32,768 cap, and that a
  client `max` on an opted-in launch reaches the wire as `xhigh`.
- `./scripts/test-integration.sh tests/integration/proxy/test_gemini_4_defaults_e2e.py tests/integration/proxy/test_session_routing_e2e.py`:
  17 passed. The seven session-routing cases resolve `gemini/gemini-4-neon` and `gemini/gemini-4-hydrogen` through the
  isolated local LiteLLM to Google AI. The other ten cover streaming and non-streaming tool round trips and `xhigh`
  under required ZDR, and a Claude tool call continued by both models on OpenRouter and on Google AI. The reviewer also
  ran two session-routing cases independently, and both passed.
- `make pre-commit` passed after a token-cache refresh for the runtime design and changelog. The changelog is over its
  25,000-token target and under the 30,000 limit; it needs rotation.
- `make build` produced the wheel and sdist with the fixed backend config, and `./scripts/test-wheel-runtime.sh` exited
  0 after its backend process group stopped. Before the rebase, an isolated wheel install outside the checkout passed
  defaults, aliases, 13 routes per model, all six Gemini templates, backend pricing metadata, worker retention, and CLI
  inventory checks.
- Remote Vertex inference was not exercised; no shared gateway is configured here. Its request shape, thinking levels,
  output limits, and placeholder signature have deterministic coverage. Google's guides state no Vertex rates for either
  model.
- Carbon and Argon still report Standard cost for Flex and Priority requests.
- The policy plan-check and team-tagger defaults were left on Gemini 3.8 Flash by decision, not verified on Hydrogen.
- OpenRouter's metadata reports `medium` as the default effort for both models where Google states `high`. Forge sends
  an explicit effort on every templated tier, so the difference affects only callers that send none.
