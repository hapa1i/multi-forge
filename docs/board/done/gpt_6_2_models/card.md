# Adopt GPT-6.2 Astra and Sol

Merged to `main` on November 19, 2026 as `1d710f90`. [PR #300](https://github.com/hapa1i/multi-forge/pull/300)

Add the November 17 GPT-6.2 release to Forge. Use standard Astra for the general OpenAI Sonnet and Opus tiers, the
Codex-template Opus tier, and the OpenAI workflow worker. Operators can select Sol explicitly or use either Pro variant
through OpenRouter. Versioned model IDs continue to select the requested generation.

OpenAI lists `gpt-6.2-astra` and `gpt-6.2-sol`. Both models require reasoning and use Responses for tool calls.
[OpenAI release notes](https://developers.openai.com/api/docs/changelog) ·
[GPT-6.2 migration guide](https://developers.openai.com/api/docs/guides/latest-model)

On November 19, 2026, OpenRouter listed four interactive IDs and an Azure ZDR endpoint for each. Its Pro IDs select the
underlying model's Pro reasoning mode. [OpenRouter model catalog](https://openrouter.ai/api/v1/models) ·
[ZDR endpoint catalog](https://openrouter.ai/api/v1/endpoints/zdr)

Branch `feat/gpt-6-2-models` starts at `24568e35`.
