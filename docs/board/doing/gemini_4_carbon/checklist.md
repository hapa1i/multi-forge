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
- Native Google AI and remote Vertex inference were not exercised. Their request shape, thinking, limits, capability
  registration, and offline pricing have deterministic coverage; live model evidence is OpenRouter-only.
- The catalog timeout field is not consumed by current clients. This change preserves existing request/workflow
  deadlines; it does not implement long decode or background execution.
