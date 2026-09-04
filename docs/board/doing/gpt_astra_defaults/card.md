# Add GPT-6 Astra and promote the GPT default

## Goal

Add GPT-6 Astra and OpenRouter's Astra Pro model to the catalog, and make standard Astra the default OpenAI model for
the existing sonnet/opus and review-worker roles.

## Verified provider contracts

- OpenAI's native model ID is `gpt-6-astra`: 1,050,000 context tokens, 128,000 output tokens, image input, and reasoning
  efforts `low`, `medium`, `high`, `xhigh`, and `max`. Tool use requires Responses; sampling parameters are unsupported.
- OpenRouter lists `openai/gpt-6-astra` and `openai/gpt-6-astra-pro` with the same context/output limits and effort
  vocabulary. Its ZDR catalog lists Azure endpoints for both on 2026-09-05.
- OpenAI documents Pro as a reasoning mode. The provider-specific Pro model slug is therefore routed only through
  OpenRouter; this change does not invent a native OpenAI Pro model ID or a new reasoning-mode interface.

Sources: [OpenAI model](https://developers.openai.com/api/docs/models/gpt-6-astra),
[OpenAI migration guide](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra),
[OpenRouter catalog](https://openrouter.ai/api/v1/models), and
[OpenRouter ZDR endpoints](https://openrouter.ai/api/v1/endpoints/zdr).

## Scope and constraints

- Update intrinsic profiles, aliases, route candidates, OpenAI proxy defaults, the bundled local backend, and relevant
  workflow/QA guidance.
- Preserve lightweight haiku and specialized Codex sonnet choices, existing model IDs, explicit historical Sol
  selection, and current tier-specific reasoning settings.
- Keep model capability, provider routing, and execution mode separate.
- Preserve materialized user proxy/backend configuration; document edit/recreate and restart steps.
- Verify fresh routing, historical alternatives, Responses tool requests, and packaged resources.
- Bundle verified standard Astra pricing in the LiteLLM deployment because 1.99 lacks it in its packaged cost map;
  verify cached-token costs, the 272K threshold, and a live gateway cost header with metadata refresh disabled.
