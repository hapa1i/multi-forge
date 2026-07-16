# GPT-5.6 implementation checklist

Completed: 2026-07-16

## Current focus

Closeout complete; implementation and verification are recorded.

## Catalog and routing

- [x] Catalog exposes Sol, Terra, Luna, and the official unsuffixed Sol alias.
- [x] OpenAI sonnet/opus defaults select Sol while haiku remains GPT-5.4 Mini.
- [x] OpenAI detection and local LiteLLM model registration recognize the new family.

## Proxy and workflow defaults

- [x] All six affected OpenAI proxy templates replace their GPT-5.5 tier defaults with Sol.
- [x] Default workflow worker identity and provider references both select Sol.
- [x] User and bundled-skill documentation describes the new defaults and explicit upgrade path.

## Acceptance tests

| Test                                | Fixture                                | Assertion                                                           | Test File                                                  |
| ----------------------------------- | -------------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------- |
| Catalog family and alias resolution | bundled model catalog                  | all three variants load and base/provider aliases resolve to Sol    | `tests/src/core/models/test_model_catalog_resolution.py`   |
| OpenAI default tier promotion       | bundled model catalog                  | haiku stays GPT-5.4 Mini while sonnet/opus select Sol               | `tests/src/core/models/test_model_catalog_load.py`         |
| Six-template tier mapping           | each affected built-in OpenAI template | every former GPT-5.5 tier is exactly `openai/gpt-5.6-sol`           | `tests/src/config/test_loader.py`                          |
| Local LiteLLM route materialization | fresh built-in adapter config          | base, Sol, Terra, and Luna route names and targets are present      | `tests/src/backend/test_creation.py`                       |
| Workflow provider-reference drift   | catalog-derived OpenAI worker          | worker identity and OpenRouter/LiteLLM refs select Sol together     | `tests/src/review/test_models.py`                          |
| Workflow command-surface drift      | CLI help and executable docs examples  | every advertised model is selectable; stale worker names are absent | `tests/src/cli/test_workflow_docs.py`                      |
| Intelligence-score peer buckets     | GPT-5.6 and existing catalog profiles  | Sol and Terra retain their intentional coarse peer tiers            | `tests/src/core/models/test_model_catalog_resolution.py`   |
| LiteLLM proxy request forwarding    | hermetic Responses API upstream        | sonnet resolves and forwards the exact Sol slug with tier overrides | `tests/integration/proxy/test_proxy_openai_routing_e2e.py` |
| OpenRouter live routing             | configured OpenRouter credential       | sonnet completes with resolved tier/model headers naming Sol        | `tests/integration/proxy/test_proxy_openrouter_e2e.py`     |

## Verification

- [x] Focused catalog, config, backend, review, and skill tests pass (`611 passed`).
- [x] Review follow-up suite passes after reflow cleanup (`554 passed`).
- [x] Targeted proxy integration verifies Sol as the resolved model (`2 passed`: hermetic LiteLLM and live OpenRouter).
  - Additional live probes were attempted: direct local LiteLLM reached OpenAI but the configured key lacks GPT-5.6
    permission (401); remote LiteLLM credentials are not configured in this environment.
- [x] `make test-unit` (`7936 passed, 1 skipped, 117 deselected`) and `make pre-commit` pass.
- [x] Wheel and sdist build and separate clean-install full-profile asset checks pass.

## Review follow-up

- [x] Replace stale GPT-5.5 worker examples in workflow CLI help and end-user docs with GPT-5.6 Sol.
- [x] Validate executable workflow documentation model arguments against the live worker registry.
- [x] Correct the panel skill's Claude Opus default description to 4.8.
- [x] Record Sol and Terra scores as intentional coarse peer buckets and guard those relationships.
- [x] Remove formatter-only reflow from the implementation diff.

## Closeout

- [x] Record verification in `docs/board/change_log.md`.
- [x] Move this card to `docs/board/done/gpt_5_6_models/`.
