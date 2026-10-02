# October model refresh

Adopt Claude Sonnet 5.5 as the Anthropic/OpenRouter Sonnet default and add GPT-6.1 Sol. Move `sol` and `gpt-sol` to 6.1
while retaining explicit Sonnet 5 and GPT-6 Sol pins. Astra remains the OpenAI tier and workflow default. Execution
branch: `feat/sonnet-5-5-defaults`, based on `3a5d38eb`; review is PR #256.

Keep the intrinsic catalog, route catalog, direct Claude pins, proxy templates, workflow workers, and packaged backend
metadata aligned. Existing user-owned proxy and backend snapshots keep their selections and bytes. Gemini defaults stay
unchanged: Google's September 30 Gemini 4 Argon announcement describes a restricted rollout, and the public Gemini API
and OpenRouter catalogs did not list it on October 1, 2026.

Sonnet 5.5 uses native `claude-sonnet-5-5` and OpenRouter `anthropic/claude-sonnet-5.5`. It has adaptive thinking and a
`between_tools` mode for disabling up-front thinking; `disabled` and forced tool choices are rejected. Thinking blocks
are bound to conversation history. Verify these boundaries, supported effort levels, streaming/tool continuity, and
offline pricing before promoting defaults. LiteLLM 1.102.0 lacks packaged Sonnet 5.5 metadata and rejects `xhigh` in an
offline request-conversion probe.

GPT-6.1 Sol is public as native `gpt-6.1-sol` and OpenRouter `openai/gpt-6.1-sol`. It retains the 1.05M context and 128K
output envelope, but requires reasoning (`low` through `max`, default `medium`) and Responses for tool calling. Sampling
controls are unsupported. Cached reads cost 5% of input, with the existing >272K premium and Flex/Fast rates. LiteLLM
1.102.0 lacks its offline metadata. Verify cost accounting and streaming/tool execution on both provider paths. Existing
snapshots remain user-owned; the user explicitly approved moving the unversioned Sol aliases to 6.1.

Sources, checked October 1, 2026:

- [Anthropic model specifications](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)
- [Anthropic migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)
- [OpenRouter model](https://openrouter.ai/anthropic/claude-sonnet-5.5)
- [LiteLLM support](https://docs.litellm.ai/blog/claude_sonnet_5_5)
- [Gemini 4 Argon announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-argon/)
- [GPT-6.1 Sol specification](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [GPT-6 migration guidance](https://developers.openai.com/api/docs/guides/latest-model)

See the [execution checklist](checklist.md).
