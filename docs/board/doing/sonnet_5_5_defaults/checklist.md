# Claude Sonnet 5.5 checklist

Current focus: review and shipment. Implementation and runtime verification are complete; Gemini 4 remains deferred.

- [x] Verify public release, provider IDs, capabilities, prices, and Gemini availability.
- [x] Add Sonnet 5.5 capabilities, aliases, route, and workflow selection; preserve explicit Sonnet 5.
- [x] Promote direct Claude and fresh proxy Sonnet defaults without changing saved snapshots or Gemini defaults.
- [x] Supply and validate offline LiteLLM metadata, effort translation, and cache pricing.
- [x] Verify thinking modes, tool choices, signed-block preservation, and sampling constraints.
- [x] Synchronize runtime design, end-user upgrade guidance, and packaged QA expectations.
- [x] Run focused and required targeted integration checks, aggregate unit/regression suites, and pre-commit.
- [x] Build and verify the clean wheel, fresh realization, and saved snapshot preservation.
- [x] Review the complete diff and record validation and any remaining limitations.
- [ ] Record closeout after shipment.

| Test                  | Fixture                                        | Assertion                                                                             |
| --------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------- |
| Default adoption      | Packaged catalogs and fresh templates          | Sonnet aliases and tiers choose 5.5; explicit 5 and Gemini defaults remain            |
| Saved configuration   | Existing Sonnet 5 proxy/backend snapshots      | Upgrade reads preserve choices and bytes                                              |
| Native metadata       | Offline LiteLLM process                        | Supported efforts and token/cache costs match the public contract                     |
| Request compatibility | Adaptive and between-tools requests with tools | Valid controls survive; invalid controls fail accurately; signed history is preserved |
| Packaging             | Clean wheel installation                       | Catalogs load and the packaged backend starts, reports healthy, and stops             |

Verification on October 1, 2026:

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

Release QA and publishing are outside this implementation pass. Native `between_tools` remains an approximation on
translated routes; callers needing its exact semantics and bound thinking history should use Anthropic passthrough.
