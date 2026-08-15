# Remove obsolete proxy abstractions checklist

Current focus: Wave 7 order 11 is active from `cc03a4e6`; keep orders 12--35 parked.

## Activation and evidence

- [x] Close PR #189 on pushed `main` at `cc03a4e6`, branch from that exact closeout, and move only order 11 to `doing/`.
- [x] Recheck `forge.proxy.model_spec`: only its self-test imports it; source, resources, entry points, extensions, and
  documentation have no consumer.
- [x] Recheck `AbstractLLMClient`: no production class inherits it, while two factory comments and the server module
  preamble retain stale inheritance claims.
- [x] Recheck `ToolCallError`: production imports and catches it but never constructs or raises it; one metrics test
  injects it synthetically.
- [x] Recheck `TierClientFactory.get_cache_status()` and `clear_cache()`: both are definition-only diagnostics with no
  operator, source, or test caller.
- [x] Run the unchanged model-spec, client-factory, server, metrics, and full proxy characterization before deletion
  (829 passed).

## Implementation

- [x] Delete the test-only model-spec module and its self-only test while retaining live model-resolution coverage.
- [x] Delete `AbstractLLMClient`, update stale inheritance/type comments, and retain the concrete adapter protocol.
- [x] Move the useful failure-metrics assertion to a reachable production exception before deleting `ToolCallError` and
  both unreachable handlers.
- [x] Delete the two zero-caller factory diagnostics while preserving cache construction, expiry, invalidation, and
  credential-refresh behavior.
- [x] Preserve provider conversion, `map_model_name`, cache keys, response/error wire shapes, and the metrics schema.

## Acceptance tests

| Boundary          | Fixture                                       | Assertion                                                      |
| ----------------- | --------------------------------------------- | -------------------------------------------------------------- |
| Model resolution  | live server/model-detection tests             | supported mapping and rejection behavior remains covered       |
| Client protocol   | concrete LiteLLM/OpenRouter adapter doubles   | factory/server calls retain their structural async interface   |
| Failure metrics   | reachable non-streaming client failure        | total, per-model, per-tier, and error-type counters still move |
| Cache lifecycle   | cache hit, expiry, invalidation, auth refresh | removal of diagnostics does not change cache behavior          |
| Proxy integration | targeted real proxy request paths             | request/response conversion and telemetry remain unchanged     |

## Verification and closeout

- [x] Run focused model-resolution, factory, server, and metrics tests (67 passed), the focused regression slice (46
  passed), and the full proxy unit slice (808 passed).
- [x] Run targeted hermetic Docker OpenAI-routing proxy integration coverage (four passed).
- [x] Run `make test-unit` (9,193 passed, one expected skip), `make test-regression` (907 passed), and
  `make pre-commit`.
- [x] Run board link/lane/size and diff checks: all 885 local links across 344 Markdown files resolve, the Wave 7 graph
  is 10 done / 1 doing / 24 todo, and order 12 remains parked.
- [ ] Open one draft PR for order 11; after merge, close this member before selecting order 12.
