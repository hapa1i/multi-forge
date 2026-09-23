# September model refresh

Completed 2026-09-23. [PR #255](https://github.com/hapa1i/multi-forge/pull/255) merged as `e107dd13` with all five
GitHub checks passing. The merged tree matches verified branch head `6258db15`.

Add the major newly released models in Forge's existing provider families in one PR, and make Claude Opus 5.5 the
default Opus. Execution branch: `feat/september-model-refresh`, based on `abcefb15`.

Scope: Opus 5.5; GPT-6 Sol, Luna, and their OpenRouter Pro variants; DeepSeek V4.1 Flash and V4 Pro 0813; Qwen3.8 Flash
and Max 0902; GLM 5.3 Flash and FlashX; and packaged LiteLLM support for the existing Gemini 3.8 Flash catalog entry.
Preserve explicit older models and other family defaults.

The intrinsic catalog, route catalog, templates, workflow workers, and direct Claude pins must agree. Existing
user-owned proxy and backend snapshots stay unchanged. LiteLLM compatibility includes offline pricing, reasoning/tool
request shapes, fresh backend realization, and clean-wheel startup.

Evidence: [OpenRouter models](https://openrouter.ai/api/v1/models),
[Opus migration](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide),
[Sol](https://developers.openai.com/api/docs/models/gpt-6-sol),
[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), and
[Gemini 3.8](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash). Research snapshots were fetched September
23, 2026. No public Gemini Flash 3.9 was found.

See [execution checklist](checklist.md).
