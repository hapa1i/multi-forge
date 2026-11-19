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

## Verification

| Check                        | Fixture                                              | Assertion                                                         |
| ---------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------- |
| Catalog and route resolution | Neon and Hydrogen provider aliases                   | One canonical model each; routes match Carbon and Flash coverage  |
| Defaults                     | Packaged catalog and fresh template realizations     | Neon serves Sonnet/Opus; Hydrogen serves Haiku and Flash tiers    |
| Effort resolution            | Explicit, derived, and client effort requests        | `xhigh` resolves; `max` clamps to `xhigh`; off clamps to `low`    |
| Native request shape         | Recorded LiteLLM streaming and unary requests        | `thinkingConfig` carries all four levels; sampling is filtered    |
| Vertex output limit          | Recorded `vertex_ai/` unary request at 65,536 tokens | Neither model is clamped; Carbon and Argon still clamp to 32,768  |
| Gateway metadata             | Packaged LiteLLM map and isolated registration       | Override still needed; prices and `xhigh` passthrough hold        |
| Upgrade ownership            | Saved Carbon proxy snapshot                          | Saved bytes, tiers, and alternatives remain unchanged             |
| Policy helpers               | Plan-check and team-tagger defaults                  | Both stay on Gemini 3.8 Flash                                     |
| Live tool round trip         | OpenRouter with required ZDR routing                 | Streaming and unary tool calls resolve both `google/` model slugs |

- [x] Record the failing run before implementation.
- [x] Run focused unit and regression checks and targeted Docker integration tests.
- [x] Run aggregate unit and regression suites, pre-commit, build, and clean-wheel checks.
- [x] Record evidence and remaining limitations.

## Closeout

- [x] Review the complete diff and synchronize the changelog when implementation is verified.
- [ ] Merge, record shipped closeout, and move the card to `done/`.

## Evidence and limits

The branch was rebased onto `main` at `819717bd`, which adds the dnspython 2.9.2 floor, after the first verification
pass. Results are from the rebased head unless a line says otherwise.

- Before implementation, the new catalog and LiteLLM client tests failed 117 of 139 cases and the template tests failed
  5 of 5. The 22 early passes hold vacuously for an uncataloged model.
- `make test-unit`: 11,942 passed. Before the rebase, two runs each had one failure, both in the slowest runs. One was
  `test_watchdog.py::test_deadline_reports_timeout`, a subprocess-deadline timing test in `core/reactive` that this
  change does not touch; the other run's failing test was not captured.
- `make test-regression`: 2,564 passed. Before the rebase, one run failed
  `test_bug_session_delete_preview_index_mutation.py::test_replacement_during_confirmation_is_preserved` once; it passed
  four isolated reruns and is also outside this change.
- `make test-integration`: 593 passed with no reruns, as it did before the rebase. `main` alone passes 582. The
  session-routing cases send `gemini/gemini-4-neon` and `gemini/gemini-4-hydrogen` requests through the isolated local
  LiteLLM to Google AI, so the native `thinkingConfig` route is exercised live. The hermetic cases prove a unary
  `vertex_ai/gemini-4-neon` request keeps 65,536 tokens while Carbon keeps its 32,768 cap, and that a client `max`
  reaches the wire as `xhigh`.
- `./scripts/test-integration.sh tests/integration/proxy/test_gemini_4_defaults_e2e.py -m slow` plus the Flash-template
  OpenRouter case: 7 passed before the rebase and was not repeated. Both models completed streaming and non-streaming
  tool round trips under required ZDR, and both accepted `xhigh`. The gate ran twice, about 22 small OpenRouter requests
  in total.
- `make pre-commit` passed after a token-cache refresh for the runtime design, proxy guide, and changelog.
- `make build` produced the wheel and sdist, and the packaged catalog, routes, backend source, and six Gemini templates
  match the source tree. `./scripts/test-wheel-runtime.sh` exited 0 with dnspython 2.9.2 after its backend process group
  stopped. Before the rebase, an isolated wheel install outside the checkout passed defaults, aliases, 13 routes per
  model, all six Gemini templates, backend pricing metadata, worker retention, and CLI inventory checks.
- Remote Vertex inference was not exercised; no shared gateway is configured here. Its request shape, thinking levels,
  and output limits have deterministic coverage. Google's guides state no Vertex rates for either model.
- The policy plan-check and team-tagger defaults were left on Gemini 3.8 Flash by decision, not verified on Hydrogen.
- OpenRouter's metadata reports `medium` as the default effort for both models where Google states `high`. Forge sends
  an explicit effort on every templated tier, so the difference affects only callers that send none.
