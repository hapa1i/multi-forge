# Adopt Gemini 4 Argon

User-authorized on October 13, 2026. Branch `codex/gemini-4-argon` starts from freshly fetched `origin/main`
`2ec4a22a37f1a94da946b8342d799549e638c7c7` in a separate worktree.

Add Gemini 4 Argon to the intrinsic and route catalogs and promote it over Gemini Pro in the Gemini family's Sonnet and
Opus defaults. Keep Flash at Haiku and preserve explicit historical model selections and user-owned proxy/backend
snapshots. Align workflow selection, fresh templates, supported provider deployments, and migration guidance.

The catalog output limit is 65,536 tokens inside a unified 1,048,576-token context. Vertex non-streaming requests have a
narrower 32,768-token output limit. Thinking supports low, medium, and high, with medium as the model default. Sampling
controls are ignored by the native API. Long decode beyond 65,536 requires a separate continuation/background contract
and is outside this change.

Sources checked October 13, 2026:

- [OpenRouter model](https://openrouter.ai/google/gemini-4-argon)
- [Google model specification](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon)
- [Google migration guide](https://ai.google.dev/gemini-api/docs/latest-model)
- [Vertex request limits](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-argon)

Keep LiteLLM 1.102.0 and forward native Argon `thinkingConfig` through its supported provider-parameter path. Its
generic reasoning mapper sends legacy thinking budgets for Argon. Versions 1.104+ fix that mapper but also require a
master key, which changes Forge's existing local backend contract; authentication redesign is outside this card.
