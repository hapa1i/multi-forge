# Serialize LLM client initialization

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped in Batch 1 PR #225 (`fd548c8e`) on 2026-08-20.

**Execution**: `agent/wave8-batch-1` from pushed `main` at `2bc3b56b`.

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

The focused LLM/auth slice passed 211 tests and the no-`.env` file-credential path passed four. The integrated Batch 1
head passed 9,331 unit tests with 124 deselected, 992 regressions, full pre-commit, board/link checks, and all five
GitHub checks.
