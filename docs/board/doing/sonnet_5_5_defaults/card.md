# Claude Sonnet 5.5 defaults

Adopt Claude Sonnet 5.5 as the Anthropic/OpenRouter Sonnet default, with explicit Sonnet 5 selection retained. Execution
branch: `feat/sonnet-5-5-defaults`, based on `3a5d38eb`.

Keep the intrinsic catalog, route catalog, direct Claude pins, proxy templates, workflow workers, and packaged backend
metadata aligned. Existing user-owned proxy and backend snapshots keep their selections and bytes. Gemini defaults stay
unchanged: Google's September 30 Gemini 4 Argon announcement describes a restricted rollout, and the public Gemini API
and OpenRouter catalogs did not list it on October 1, 2026.

Sonnet 5.5 uses native `claude-sonnet-5-5` and OpenRouter `anthropic/claude-sonnet-5.5`. It has adaptive thinking and a
`between_tools` mode for disabling up-front thinking; `disabled` and forced tool choices are rejected. Thinking blocks
are bound to conversation history. Verify these boundaries, supported effort levels, streaming/tool continuity, and
offline pricing before promoting defaults. LiteLLM 1.102.0 lacks packaged Sonnet 5.5 metadata and rejects `xhigh` in an
offline request-conversion probe.

Sources, checked October 1, 2026:

- [Anthropic model specifications](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)
- [Anthropic migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)
- [OpenRouter model](https://openrouter.ai/anthropic/claude-sonnet-5.5)
- [LiteLLM support](https://docs.litellm.ai/blog/claude_sonnet_5_5)
- [Gemini 4 Argon announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-argon/)

See the [execution checklist](checklist.md).
