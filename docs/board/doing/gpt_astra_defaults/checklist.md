# GPT-6 Astra implementation checklist

Branch: `feat/gpt-astra-defaults`.

Current focus: ready for review; merge and closeout remain.

## Implementation

- [x] Verify native and OpenRouter model identities, limits, reasoning, and ZDR routes.
- [x] Add Astra profiles, aliases, and valid route candidates.
- [x] Promote existing GPT default roles and retain explicit historical model selection.
- [x] Update bundled local backend configuration and selectable review workers.
- [x] Synchronize normative and end-user documentation plus packaged QA guidance.

## Acceptance

| Test                 | Fixture                             | Assertion                                                                      | Test file                                                                      |
| -------------------- | ----------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| Catalog and defaults | Packaged model catalog              | Astra capabilities and aliases resolve; cheap/specialized tiers remain         | `tests/src/core/models/test_model_catalog_resolution.py`                       |
| Route identity       | Bundled templates and route catalog | Standard Astra is usable; Pro is OpenRouter-only; Sol stays selectable         | `tests/src/core/ops/test_session_model_routing.py`                             |
| Backend realization  | Fresh and existing backend files    | Fresh config serves Astra; existing bytes survive                              | `tests/src/backend/test_creation.py`, `tests/src/cli/test_backend_commands.py` |
| Responses transport  | Local fake upstream and real proxy  | Exact Astra model, reasoning and tools reach Responses without sampling fields | `tests/integration/proxy/test_proxy_openai_routing_e2e.py`                     |

## Verification and delivery

- [x] Run focused catalog, config, routing, backend, and workflow tests.
- [x] Run targeted proxy/session Docker integration coverage.
- [x] Run unit, regression, full pre-commit, build, and clean-wheel resource checks.
- [x] Review the final diff and record verification evidence.
- [x] Commit and prepare the branch for review.
- [ ] Record merge closeout and move the card to `done/` after shipping.

## Evidence

- Focused catalog/config/backend/workflow suite: 646 passed.
- New routing, backend pricing, and retained-model checks: 185 passed.
- Proxy and Docker session integrations: 9 passed, including live Astra on local LiteLLM and Astra/Pro on OpenRouter.
- Local LiteLLM rerun with metadata refresh disabled: 2 passed, including a nonzero gateway cost header.
- `make test-unit`: 10,240 passed; 117 integration cases deselected by the unit target.
- `make test-regression`: 1,211 passed. Both suites emit the existing Starlette/AnyIO deprecation warning.
- `make pre-commit`: passed, including types, formatting, file limits, secrets, and Markdown links.
- `make build`: wheel and sdist built. Clean wheel installed into a fresh venv with dependencies resolved outside the
  lock; catalog/aliases/defaults/routes/templates/workers and backend create/preserve/start/health/stop checks passed.
- Initial stale Sol expectations and documentation token-cache hashes were updated; final checks pass.

Integration commands:

```bash
./scripts/test-integration.sh tests/integration/proxy/test_proxy_openai_routing_e2e.py tests/integration/proxy/test_proxy_local_litellm_e2e.py::TestOpenAIProxyWithLocalLiteLLM tests/integration/proxy/test_proxy_openrouter_e2e.py::TestOpenAIProxyWithOpenRouter tests/integration/docker/test_session_routing.py -q --tb=short
./scripts/test-integration.sh tests/integration/proxy/test_proxy_local_litellm_e2e.py::TestOpenAIProxyWithLocalLiteLLM -q --tb=short
```
