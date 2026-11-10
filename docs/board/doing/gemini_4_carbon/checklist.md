# Gemini 4 Carbon execution

Implementation and verification complete on `feat/gemini-4-carbon`; merge remains pending.

## Implementation

- [x] Confirm provider identities, thinking levels, context and ordinary output limits against primary sources.
- [x] Add catalog/routes and promote Gemini defaults while retaining explicit historical models.
- [x] Add complete local LiteLLM deployments and adapt native thinking/unary limits where needed.
- [x] Update workflow selection, design, migration guidance, and packaged QA expectations.

## Verification

| Check                        | Fixture                                                  | Assertion                                                             |
| ---------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------- |
| Catalog and route resolution | Carbon provider aliases and isolated credentials         | One canonical model; each admitted route serves it                    |
| Request compatibility        | Recorded OpenRouter/LiteLLM streaming and unary requests | Supported thinking, filtered sampling, correct token limits and tools |
| Gateway metadata             | Packaged LiteLLM map and isolated registration           | Required capability and price overrides are complete                  |
| Upgrade ownership            | Fresh realization and saved Argon snapshots              | Fresh defaults use Carbon; saved bytes remain unchanged               |
| Packaging                    | Clean installed wheel                                    | Carbon resources and local backend load outside the checkout          |

- [x] Run focused unit/regression checks and targeted Docker integration tests.
- [x] Run aggregate unit/regression suites, pre-commit, build, and clean-wheel checks.
- [x] Record evidence and remaining limitations.

## Closeout

- [x] Review the complete diff and synchronize the changelog when implementation is verified.
- [ ] Merge and record shipped closeout before moving the card to `done/`.

## Evidence and limits

- Carbon catalog tests failed before implementation (22 failures); focused verification passed 733 tests.
- Initial integrations passed 27 cases; one new remote-proxy snapshot fixture omitted its upstream URL. The corrected
  snapshot file and Docker workflow suite passed 16 cases. Across both runs and the live gate, 43 distinct cases pass.
- `./scripts/test-integration.sh tests/integration/proxy/test_gemini_carbon_e2e.py -m slow` passed both streaming and
  non-streaming tool round trips through OpenRouter with required ZDR routing (four provider requests).
- `make test-unit`: 11,651 passed. The earlier run passed 11,650 with one stale documentation token-cache failure;
  refreshing the formatted runtime design's provider count resolved it.
- `make test-regression`: 2,524 passed.
- `make pre-commit`: passed after formatter changes and token-cache refresh. Final documentation hash and
  model-reference tests passed (two tests). Repository Markdown links and staged diff checks passed.
- `make build` produced wheel/sdist artifacts. `./scripts/test-wheel-runtime.sh` passed with exit 0 after confirming the
  backend process group exited. An isolated wheel install outside the checkout passed Carbon aliases, 13 routes, fresh
  templates, backend metadata, historical worker retention, and CLI inventory checks. The first inventory assertion
  incorrectly expected unavailable workers in `--available`; the corrected check verifies both views.
- Native tool round trips and remote Vertex inference were not exercised. Their request shape, thinking, limits,
  capability registration, and offline pricing have deterministic coverage; the review follow-up adds only short native
  Google AI routing requests.

### Review follow-up (after `d7d157f8`)

- Review found two integration files outside the targeted set still asserting the Argon tier default:
  `test_finish_reason_e2e.py` (not slow, so it would fail the default integration run) and
  `test_session_routing_e2e.py`. Both now expect Carbon; together they passed 11 cases. Of the seven session-routing
  cases, two send `gemini/gemini-4-carbon` generation requests through the isolated local LiteLLM to Google AI
  (`max_tokens: 10`); the others check runtime metadata, Flash routing and local token estimation.
- Strengthened snapshot preservation to compare saved alternatives exactly on both tiers. Added Carbon cases for the
  pre-Carbon snapshot refusal, non-Vertex unary limits and cache-marker stripping; removed a duplicate defaults test.
- Verified Argon's 4,096-token cache minimum on both Google AI and Vertex; restored its December 1 price doubling,
  pricing sources and bundled backend provenance. Carbon's Google AI rates matched Google's Carbon page on November 10;
  that page and the Vertex guide state no Vertex rates, so the guide asks operators to confirm them. The Vertex guide
  confirms the 4,096-token cache minimum and the 65,536 streaming/32,768 unary limits.
- After the fixes: `make test-unit` 11,652 passed; `make test-regression` 2,527 passed; full pre-commit on changed files
  and the Markdown hook subset passed after a runtime-design token-cache refresh. Build and clean-wheel checks were not
  rerun; the only packaged change is a backend YAML comment.
- The catalog timeout field is not consumed by current clients. This change preserves existing request/workflow
  deadlines; it does not implement long decode or background execution.
