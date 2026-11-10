# Claude Fable 5.2 support

## Goal

Add Fable 5.2 and make it the target of the stable Fable aliases and `claude-fable` worker. Preserve the default Claude
model, Anthropic tier defaults, default worker quorum, and explicit Fable 5/5.1 selections.

## Verified provider contract

Checked 2026-11-10 against the [Anthropic overview](https://platform.claude.com/docs/en/models/fable-5-2/overview),
[migration guide](https://platform.claude.com/docs/en/models/fable-5-2/migration-guide),
[cache contract](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), and
[OpenRouter model](https://openrouter.ai/anthropic/claude-fable-5.2).

- Native ID: `claude-fable-5-2`; OpenRouter ID: `anthropic/claude-fable-5.2`.
- 1,000,000-token context and 128,000-token maximum output; image input supported.
- Always-on adaptive thinking, five effort levels from `low` through `max`, default `high`; sampling overrides and
  forced tool choice are unsupported. Prompt caching starts at 512 tokens.
- Per-million-token prices: $8 input, $40 output, $0.20 cache read, $10 five-minute cache write, $16 one-hour write.
- Anthropic requires 30-day retention unless expressly authorized otherwise. OpenRouter's public ZDR endpoint catalog
  contained zero Fable 5.2 endpoints and six Opus 5.5 endpoints on this date; preserve the required-ZDR Opus fallback.
- Preserved thinking enforces its prefix check for every account. Older models cannot read 5.2 thinking blocks.

## Scope and ownership

Follow the [model catalog contract](../../../design_runtime.md#a5-model-catalog-368) and
[saved configuration procedure](../../../end-user/proxy.md#updating-saved-proxy-and-backend-configurations). Update
packaged catalog/routes/templates/backend metadata and user guidance. Existing proxy/backend snapshots remain
user-owned. The [Fable 5.1 card](../../done/claude_fable_5_1/card.md) records the previous family-default migration.

## Risks

- Provider slugs differ in their version punctuation.
- Pinned LiteLLM may need explicit capability/pricing metadata for the new model.
- Repointed aliases must refuse an incompatible saved proxy with actionable recovery.
- Translated routes do not promise native signed-thinking continuity; passthrough must preserve the original history.
