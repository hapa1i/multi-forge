# Serialize LLM client initialization

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `doing/` -- active in Wave 8 Batch 1 on `agent/wave8-batch-1` from `2bc3b56b`.

**Finding**: O091 (LOW race/resource leak).

## Goal

Ensure concurrent first use of one LiteLLM/OpenRouter adapter constructs and retains exactly one `AsyncOpenAI` client.

## Verified Evidence

Both `_get_client` implementations check `_client`, await credential resolution, then construct and assign without a
lock or second check. Two cold callers can each build a client; the later assignment replaces the first while a caller
still owns its pool.

## Acceptance Criteria

- Use per-instance async initialization serialization with a second cache check after lock acquisition.
- Construct credentials, optional custom-CA HTTP transport, and `AsyncOpenAI` exactly once for concurrent cold callers.
- Clean up a separately created HTTP transport if client construction fails.
- Preserve cache hits, auth retry/invalidation behavior, provider headers, and adapter request semantics.
- Do not broaden this member into the separately proposed credential-invalidation scope decision.

## Verification

Add deterministic concurrent cold-start tests for both adapters plus construction-failure cleanup. Run focused core LLM
and auth-retry tests, full unit/regression suites, the relevant no-`.env` auth path, and `make pre-commit`.
