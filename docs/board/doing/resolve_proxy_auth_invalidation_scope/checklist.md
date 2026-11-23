# Checklist: resolve proxy authentication invalidation scope

[Card](card.md). Branch `refactor/proxy-auth-invalidation-scope`, based on `main` at `450c05eb`.

## Current focus

Option 2 is implemented and verified on the branch. Review, merge, and closeout remain.

## Evidence required by the card

- [x] **Callers reverified.** `rg -n invalidate_and_retry src/` returns the definition and one caller: the non-streaming
  retry in `src/forge/proxy/server.py`. It passes `resolved_route.tier`, declared `str` on `_ResolvedModelRoute`. Tests
  replace the method with stand-ins and pass string tiers. No dynamic lookup, entry point, config field, CLI output, or
  end-user guide names the method.
- [x] **Cache identity characterized at three layers.** `TierClientFactory._cache` is keyed by `(model_name, tier)`.
  Each core client holds one `AsyncOpenAI` client. `CredentialManager._cache` is keyed by credential provider
  (`litellm_remote`, `litellm_local`, `openrouter`). The factory builds only `CoreLLMClientAdapter`, over
  `LiteLLMClient` or `OpenRouterClient`.
- [x] **Sibling tier and second model covered.** Both appear in the unit test and in the cross-layer test; see
  [Acceptance tests](#acceptance-tests).
- [x] **One-retry limit and tier hyperparameters preserved.** The handler's retry block is unchanged.
  `test_o015_authentication_retry_preserves_resolved_tier` still asserts one retry with the failed tier. The new unit
  test asserts that the rebuilt adapter carries that tier's hyperparameters.
- [x] **Closing decided.** The factory does not close evicted adapters; see the card's [Decision](card.md#decision). A
  loopback run on `CoreLLMClientAdapter` measured the in-flight effect of the core client's own close: a second request
  failed authentication, and a stream already in flight on the same adapter ended after one chunk with
  `ProxyStreamError` type `api_error`.
- [x] **Focused auth/cache tests and targeted proxy integration coverage run.** See [Verification](#verification).

## Compatibility evidence for the deleted branch

Recorded for [coding standards](../../../developer/coding_standards.md#compatibility-evidence-before-deletion).

- **Unreachable.** The `tier=None` branch needed a caller without a tier. The only caller always holds
  `_ResolvedModelRoute.tier`, a `str`.
- **Surface.** Private implementation. Only `forge.proxy.server` imports `TierClientFactory`.
- **Tests.** `test_invalidate_and_retry_all_tiers_rebuilds_client_after_releasing_refresh_lock` characterized only the
  deleted branch and is removed with it. The single-tier deadlock regression is unchanged.
- **Action.** Clean deletion, with `tier: str` required. With `tier=None` planted at the call site, pyright and mypy
  both rejected the argument.
- **Wiring rejected.** The branch encoded wider eviction as a possible safety measure. It could not be wired as written,
  and the card's Decision records why wider eviction is not adopted.

## Implementation

- [x] `invalidate_and_retry(model_name, *, tier: str)` evicts only `(model_name, tier)` and rebuilds that tier. The
  all-tier branch and its default-tier fallback are deleted. The docstring states the eviction contract.
- [x] `tier_client_factory` in `tests/src/proxy/conftest.py` isolates the process-wide factory for both new test files.
- [x] `docs/design_runtime.md` §3.6.3 states the translated authentication-refresh contract.
- [x] Both `replace_legacy_tier_inference` links point at this card's `doing/` path.

## Acceptance tests

| Test                                 | Fixture                                               | Assertion                                                    | Test File                                                |
| ------------------------------------ | ----------------------------------------------------- | ------------------------------------------------------------ | -------------------------------------------------------- |
| Retry rebuilds only the failed entry | failed entry, sibling tier, and second model cached   | new adapter with the failed tier's hyperparameters           | `tests/src/proxy/test_client_factory.py`                 |
| Stale siblings recover               | real adapters over an in-memory gateway; key replaced | one rejected request per stale adapter, then the new key     | `tests/src/proxy/test_client_factory_integration.py`     |
| Streaming failure surfaces           | stream on a stale adapter                             | `authentication_error`; the same adapter streams next time   | `tests/src/proxy/test_client_factory_integration.py`     |
| Retry releases the refresh lock      | three seeded cache entries                            | lock free inside `get_client`; only the failed entry evicted | `tests/regression/test_bug_proxy_retry_lock_deadlock.py` |

Each mutation below was applied alone, tested, and reverted.

| Mutation                                   | Tests that failed                              |
| ------------------------------------------ | ---------------------------------------------- |
| Evict every tier of the model              | unit, sibling cross-layer, deadlock regression |
| Evict nothing                              | unit, deadlock regression                      |
| Rebuild with the default tier              | unit, sibling cross-layer, deadlock regression |
| `complete()` skips credential invalidation | sibling cross-layer, stale-client regression   |
| Chat stream keeps its HTTP client          | streaming cross-layer, stale-client regression |

## Verification

- [x] Focused auth/cache tests: 42 passed across the two new files, the deadlock and stale-client regressions, the three
  handler auth-retry regressions, and `tests/src/proxy/test_metrics_integration.py`.
- [x] `make test-unit`: 12,062 passed.
- [x] `make test-regression`: 2,738 passed.
- [x] Targeted integration with synthetic credentials: 55 passed, with one slow live-credential test deselected.
- [x] `make pre-commit`: every hook passed.

```bash
PYTHON_DOTENV_DISABLED=1 GEMINI_API_KEY= OPENROUTER_API_KEY= ./scripts/test-integration.sh \
  -m "integration and not slow" \
  tests/src/proxy/test_client_factory_integration.py \
  tests/src/proxy/test_metrics_integration.py \
  tests/integration/core/test_auth_credential_resolution.py \
  tests/integration/proxy/test_litellm_streaming_cost_e2e.py \
  tests/integration/proxy/test_finish_reason_e2e.py \
  tests/integration/proxy/test_proxy_openai_routing_e2e.py \
  tests/integration/proxy/test_effort_observation_e2e.py \
  tests/integration/proxy/test_request_id_validation_e2e.py
```

Not run: `forge proxy start <proxy_id> --smoke-test`. It sends a paid upstream request and would need the proxy
restarted from this checkout.

## Not changed by this card

- **Stale siblings.** Each stale sibling adapter makes one rejected upstream request, which a streaming caller sees as
  an error. The card's [Decision](card.md#decision) records why the factory does not address it.
- **In-flight abort.** A core client's `_close_client()` closes the HTTP client that other requests on the same adapter
  are still using.
- **Text-based classification.** Core clients classify a failure as authentication by the words `authentication` or
  `unauthorized` in the error text. LiteLLM 1.102.2 words gateway rejections as `Authentication Error, ...`.
  OpenRouter's wording is unverified.
- **No end-to-end 401 coverage.** No test under `tests/integration/proxy/` drives a real proxy through an upstream 401.

## Closeout

- [ ] Merge to `main`.
- [ ] Add the change-log entry.
- [ ] Decide whether the items under "Not changed by this card" need cards.
- [ ] Review whether core-client recovery belongs in `docs/board/impl_notes/runtime_telemetry.md`.
- [ ] Move the card to `done/` and repoint the two `replace_legacy_tier_inference` links.
