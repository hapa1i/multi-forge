# Adopt Gemini 4 Carbon

User-authorized November 10, 2026. Branch: `feat/gemini-4-carbon`, based on `main` at `457c9a59`.

Shipped November 10, 2026 via [PR #298](https://github.com/hapa1i/multi-forge/pull/298) (`a8fce9e0`).

Add Gemini 4 Carbon across the intrinsic catalog, provider routes, Gemini templates, local LiteLLM deployments, and
workflow selection. Make Carbon the Gemini Sonnet/Opus default and generic Gemini worker target. Keep Flash at Haiku and
preserve explicit Argon/older Pro selections and saved user-owned proxy/backend configurations.

Carbon uses a unified 1,048,576-token context, low/medium/high thinking with medium as its default, and implicit
caching. Ordinary Google AI requests support 65,536 output tokens; Vertex foreground segments allow 65,536 streaming or
32,768 non-streaming. Long decode requires continuation and remains outside this change. Sampling overrides are ignored
by the native API and must be filtered by Forge.

Sources checked November 10, 2026:

- [OpenRouter model](https://openrouter.ai/google/gemini-4-carbon)
- [OpenRouter endpoint metadata](https://openrouter.ai/api/v1/models/google/gemini-4-carbon/endpoints)
- [Google migration and pricing](https://aistudio.google.com/docs/whats-new-gemini-4-carbon)
- [Vertex caching limits](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/context-cache/context-cache-overview)
- [Google model specification](https://ai.google.dev/gemini-api/docs/models/gemini-4-carbon)
- [Vertex migration and request limits](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-carbon)

Validate the pinned LiteLLM adapter's native thinking and offline metadata support before promoting the new defaults.
Existing materialized configurations require explicit operator adoption; a package upgrade must not rewrite them.
