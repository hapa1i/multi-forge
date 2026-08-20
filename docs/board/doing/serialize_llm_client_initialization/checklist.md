# Serialize LLM client initialization checklist

Current focus: active in Wave 8 Batch 1 on `agent/wave8-batch-1`; pin concurrent cold-start behavior for both adapters.

## Phase 1 -- Pin the race and cleanup boundary

- [x] Recheck current `main`: both adapter `_get_client` methods await credential resolution between an unlocked cache
  check and client assignment, allowing duplicate cold-start construction.
- [ ] Add deterministic concurrent cold-start regressions for LiteLLM and OpenRouter that require one credential lookup,
  one `AsyncOpenAI` construction, and one shared returned client.
- [ ] Add a LiteLLM construction-failure regression proving a separately created custom-CA HTTP transport is closed.

## Phase 2 -- Implement

- [ ] Add per-instance async initialization serialization and a second cache check after acquiring it in both adapters.
- [ ] Close a separately created LiteLLM HTTP transport if `AsyncOpenAI` construction fails, preserving the original
  exception.
- [ ] Preserve hot-cache, auth invalidation/retry, provider header, custom-CA, and request behavior without expanding
  credential-invalidation ownership.

## Phase 3 -- Verify and publish

- [ ] Run focused LLM client and auth-retry tests, the no-`.env` credential path, regression and full unit suites, and
  `make pre-commit`.
- [ ] Record exact verification evidence and commit this card without mixing another Batch 1 implementation.

## Acceptance tests

| Boundary              | Fixture                                             | Assertion                                                           | Tier            |
| --------------------- | --------------------------------------------------- | ------------------------------------------------------------------- | --------------- |
| LiteLLM cold start    | two callers blocked in first credential lookup      | one client/credential lookup; both callers receive identical object | unit/regression |
| OpenRouter cold start | same deterministic two-caller barrier               | one client/credential lookup; both callers receive identical object | unit/regression |
| Custom CA failure     | transport created; `AsyncOpenAI` constructor raises | transport closes once and cache stays empty                         | unit/regression |
| Hot cache             | initialized adapter called again                    | cached client returns without lock-path credential work             | unit            |
| Auth retry            | provider rejects stale credential                   | existing invalidate/close/rebuild behavior remains unchanged        | regression      |
