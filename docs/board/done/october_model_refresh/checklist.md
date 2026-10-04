# October model refresh checklist

Completed October 4, 2026. PR #256 merged as `1ba9584c`, whose tree matches verified head `ffc1489f`. The card is
closed; Gemini 4 remains deferred pending public API access. Release 1.0.2 uses the candidate evidence below.

- [x] Restrict context-estimator model pins to translated routes and cover saved passthrough launches.

- [x] Correct Sonnet 5.5 upgrade steps and the general model-upgrade overview.

- [x] Reject unsupported forced tool choices for Sonnet/Opus 5.5 before translated dispatch.

- [x] Reject incompatible native `between_tools` effort floors atomically with an actionable response.

- [x] Verify regressions, required integrations, and packaging for the review corrections.

- [x] Verify GPT-6.1 Sol public IDs, request constraints, pricing, and OpenRouter ZDR availability.

- [x] Add 6.1 Sol catalog/routes, template alternatives, worker, and offline metadata; preserve explicit GPT-6 Sol.

- [x] Move `sol` and `gpt-sol` to 6.1 while preserving Astra defaults and saved configuration bytes.

- [x] Verify Responses tool calling, streaming, reasoning constraints, sampling, and cache/tier pricing.

- [x] Update user guidance, packaged QA, and the PR scope for both model additions.

- [x] Run focused/live tests, aggregate unit/regression suites, pre-commit, and clean-wheel checks on the integrated
  head.

- [x] Verify public release, provider IDs, capabilities, prices, and Gemini availability.

- [x] Add Sonnet 5.5 capabilities, aliases, route, and workflow selection; preserve explicit Sonnet 5.

- [x] Promote direct Claude and fresh proxy Sonnet defaults without changing saved snapshots or Gemini defaults.

- [x] Supply and validate offline LiteLLM metadata, effort translation, and cache pricing.

- [x] Verify thinking modes, tool choices, signed-block preservation, and sampling constraints.

- [x] Synchronize runtime design, end-user upgrade guidance, and packaged QA expectations.

- [x] Run focused and required targeted integration checks, aggregate unit/regression suites, and pre-commit.

- [x] Build and verify the clean wheel, fresh realization, and saved snapshot preservation.

- [x] Review the complete diff and record validation and any remaining limitations.

- [x] Record closeout after shipment.

Closeout: the merged tree passed the recorded unit, regression, integration, clean-wheel, and live-worker checks. All
four GitHub checks passed: tests (including clean-wheel runtime), pre-commit, and both CodeQL analyses. Runtime design
and end-user docs match the shipped routing and control behavior; the change log links this completed card.

| Test                  | Fixture                                        | Assertion                                                                             |
| --------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------- |
| Default adoption      | Packaged catalogs and fresh templates          | Sonnet aliases and tiers choose 5.5; explicit 5 and Gemini defaults remain            |
| Saved configuration   | Existing Sonnet 5 proxy/backend snapshots      | Upgrade reads preserve choices and bytes                                              |
| Native metadata       | Offline LiteLLM process                        | Supported efforts and token/cache costs match the public contract                     |
| Request compatibility | Adaptive and between-tools requests with tools | Valid controls survive; invalid controls fail accurately; signed history is preserved |
| Packaging             | Clean wheel installation                       | Catalogs load and the packaged backend starts, reports healthy, and stops             |

Review correction verification on October 3, 2026:

- `make test-unit`: 10,396 passed, 117 deselected. `make test-regression`: 1,315 passed. Both retain the existing
  Starlette/AnyIO deprecation warning. Documentation token evidence was refreshed before the passing aggregate run.
- `test_sonnet_55_e2e.py`: all 36 integration cases passed, including translated Sonnet/Opus forced-tool refusals and
  native `between_tools` floors, with and without streaming. The combined run exposed an invalid field in the new Docker
  fixture; the corrected `test_session_routing.py` rerun passed all three tests. Saved passthrough launches preserve
  native selection across bare launch, start, resume, fork, and incognito; model show/history and snapshot bytes agree.
- The final focused launch/conversion/override run passed 100 tests. Responses-capable proxies retain estimator pins for
  their translated Messages ingress. Adaptive effort levels and older-model forced tool choices remain supported.
- The live blind `claude-sonnet` panel used `claude-sonnet-5-5` directly and completed a read-only tool call.
- `make build` and clean-wheel verification passed: nine fresh templates, ten unchanged saved snapshots, backend
  start/health/stop, and the installed routing/conversion/override fixes.

Integrated verification on October 2, 2026:

- `make test-unit`: 10,396 passed, 117 integration-marked tests deselected. `make test-regression`: 1,278 passed. Both
  retain the existing Starlette/AnyIO deprecation warning. Catalog conformance caught the missing strict OpenAI
  allowlist entry; the final suites pass with it included.
- The three-file integration run covering local LiteLLM, Sonnet 5.5, and Docker session routing passed all 34 tests. The
  final `test_proxy_local_litellm_e2e.py -k gpt6` run passed 12, with 6 deselected. GPT-6.1 Sol tool calls work through
  native Responses and OpenRouter with and without streaming; offline metadata produces nonzero live costs.
- Offline pricing checks cover cache reads/writes, the 272K boundary, and Standard/Flex/Fast rates. Explicit `none` and
  `minimal` efforts are rejected for 6.1; derived thinking-off requests clamp to `low`. Prior GPT-6 Sol keeps its
  controls.
- Workflow availability lists `gpt-6.1-sol` as ready. Its live blind panel completed a read-only tool call using
  `openai/gpt-6.1-sol` through an existing OpenRouter proxy. Codex preflight and blind `codex` and `claude-opus,codex`
  panels passed. Preflight reports the installed Codex version ahead of the empirically pinned hook version; readiness
  remains affirmative.
- `make pre-commit` and `make build` passed. The final wheel installed outside the checkout with dependencies resolved
  independently of `uv.lock`; `uv pip check` passed. Nine fresh templates expose the intended defaults/alternatives;
  nine saved proxy files and the 1.0.1 backend snapshot retain exact bytes. The fresh offline LiteLLM backend passed
  start/health/stop.

Initial Sonnet verification on October 1, 2026:

- `make test-unit`: 10,384 passed, 117 integration-marked tests deselected.
- `make test-regression`: 1,274 passed. Both suites reported the existing Starlette/AnyIO deprecation warning.
- `./scripts/test-integration.sh tests/integration/proxy/test_sonnet_55_e2e.py tests/integration/docker/test_session_routing.py -q --tb=short`:
  16 passed. Native valid/invalid thinking controls, forced-tool refusals, both translated providers with streaming and
  sampling overrides, signed-history passthrough, and Docker session routing passed.
- `forge workflow list-models --available --json` reports the new Sonnet workers ready. Codex preflight passed, and
  blind panels with `codex`, `claude-opus,codex`, and `claude-sonnet` each completed successfully. The Sonnet worker
  resolved to `claude-sonnet-5-5` and used a read-only tool call.
- `make build` and `./scripts/test-wheel-runtime.sh` passed. The final rebuilt wheel was also installed outside the
  checkout with dependencies resolved independently of `uv.lock`: three fresh templates selected 5.5, three saved Sonnet
  5 proxy files and the 1.0.1 backend config retained exact bytes, and a fresh offline LiteLLM backend completed
  start/health/stop.
- `make pre-commit`: all hooks passed after applying import-order fixes.

The live LiteLLM probe exposed unsupported sampling fields reaching Anthropic. The shared translated request builder now
enforces catalog sampling constraints after merging provider extras. Regression coverage preserves caller-owned extras
while removing temperature, top-p, and top-k for Sonnet 5.5; existing conditional-sampling client tests also pass.

Native `between_tools` remains an approximation on translated routes; callers needing its exact semantics and bound
thinking history should use Anthropic passthrough. The verification above covers the merged implementation; release
candidate evidence is recorded separately below.

## 1.0.2 release verification

The maintainer explicitly waived fresh manual QA for 1.0.2 and authorized publication using the completed PR and
exact-wheel checks. This disposition applies only to 1.0.2; no new manual QA pass or reuse of an older artifact identity
is claimed.

Candidate: `dist/multi_forge-1.0.2-py3-none-any.whl`, SHA-256
`6b595a661fbeb0f178aecafcc79edb21ab7731d857d23909c267e0f7618b5ac9`.

- `make build` produced the wheel and sdist; `uv lock` changed only the project version to 1.0.2.
- Full `make pre-commit` passed. The version, Sonnet 5.5, GPT-6.1 Sol, and QA checklist contract selection passed all 56
  tests.
- The exact wheel installed into a fresh Python 3.13.11 environment with 86 independently resolved dependencies;
  `uv pip check` and `forge --version` passed.
- Installed-wheel checks verified nine fresh templates, ten unchanged saved snapshots, native pin preservation,
  translated forced-tool validation, and atomic native effort-floor rejection. LiteLLM create/start/health/stop passed.

The unexecuted QA selection contains 163 steps, 554 assertions, eight human checkpoints, and eight planned paid
operations. Its selection was validated, but no manual QA execution or pass is claimed.
