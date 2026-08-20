# Serialize LLM client initialization checklist

Current focus: implementation and aggregate verification are complete on `agent/wave8-batch-1` in card commit
`bb809245`; awaiting Batch 1 review and merge.

## Phase 1 -- Pin the race and cleanup boundary

- [x] Recheck current `main`: both adapter `_get_client` methods await credential resolution between an unlocked cache
  check and client assignment, allowing duplicate cold-start construction.
- [x] Add deterministic concurrent cold-start regressions for LiteLLM and OpenRouter that require one credential lookup,
  one `AsyncOpenAI` construction, and one shared returned client.
- [x] Add a LiteLLM construction-failure regression proving a separately created custom-CA HTTP transport is closed.
  Before implementation, the focused regression file failed deterministically at all three boundaries: both adapters
  performed two credential lookups, and the LiteLLM custom-CA transport was not closed.

## Phase 2 -- Implement

- [x] Add per-instance async initialization serialization and a second cache check after acquiring it in both adapters.
- [x] Close a separately created LiteLLM HTTP transport if `AsyncOpenAI` construction fails, preserving the original
  exception.
- [x] Preserve hot-cache, auth invalidation/retry, provider header, custom-CA, and request behavior without expanding
  credential-invalidation ownership.

## Phase 3 -- Verify and publish

- [x] Run focused LLM client and auth-retry tests plus the no-`.env` file-credential path:
  - `uv run pytest tests/src/core/llm tests/regression/test_bug_o091_llm_client_initialization.py tests/regression/test_bug_stale_client_after_invalidation.py tests/regression/test_bug_proxy_retry_lock_deadlock.py tests/regression/test_bug_local_litellm_openai_creds.py -q`
    -- 211 passed.
  - `uv run pytest tests/integration/core/test_auth_credential_resolution.py::TestCredentialManagerFileResolution -q` --
    4 passed.
  - Focused Ruff, Black, isort, mypy, Pyright, and `git diff --check` -- passed (Pyright printed only its newer-version
    notice).
- [x] Run the full unit/regression suites and `make pre-commit` on the integrated Batch 1 head:
  `9,330 passed, 124 deselected`; `990 passed`; all hooks passed.
- [x] Record exact verification evidence and commit this card without mixing another Batch 1 implementation
  (`bb809245`).

## Acceptance tests

| Boundary              | Fixture                                             | Assertion                                                           | Tier            |
| --------------------- | --------------------------------------------------- | ------------------------------------------------------------------- | --------------- |
| LiteLLM cold start    | two callers blocked in first credential lookup      | one client/credential lookup; both callers receive identical object | unit/regression |
| OpenRouter cold start | same deterministic two-caller barrier               | one client/credential lookup; both callers receive identical object | unit/regression |
| Custom CA failure     | transport created; `AsyncOpenAI` constructor raises | transport closes once and cache stays empty                         | unit/regression |
| Hot cache             | initialized adapter called again                    | cached client returns without lock-path credential work             | unit            |
| Auth retry            | provider rejects stale credential                   | existing invalidate/close/rebuild behavior remains unchanged        | regression      |
