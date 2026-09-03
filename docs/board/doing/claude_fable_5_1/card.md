# Claude Fable 5.1 support

## Goal

Add Anthropic's Claude Fable 5.1 to Forge's model catalog and routing surfaces, and make it the default model selected
by the stable Fable aliases and review-worker name without changing the global Opus tier default.

## Verified upstream contract

- Anthropic model ID: `claude-fable-5-1`.
- OpenRouter model ID: `anthropic/claude-fable-5.1`.
- Context window: 1,000,000 tokens; maximum output: 128,000 tokens.
- Adaptive thinking is always on; supported effort levels are `low`, `medium`, `high`, `xhigh`, and `max`, with `high`
  as the default.
- Input/output pricing remains $10/$50 per million tokens; cache reads are $0.25 per million tokens.
- OpenRouter's ZDR endpoint catalog had no Fable 5.1 route on 2026-09-02.

Sources: [Anthropic model overview](https://platform.claude.com/docs/en/models/fable-5-1/overview),
[Anthropic effort reference](https://platform.claude.com/docs/en/build-with-claude/effort), and
[OpenRouter model page](https://openrouter.ai/anthropic/claude-fable-5.1-20260831).

## Accepted behavior

- Add `claude-fable-5-1` as a canonical catalog model while retaining `claude-fable-5`.
- Move the unversioned `fable` and `claude-fable` aliases to 5.1; retain explicit Fable 5 aliases.
- Keep Anthropic and OpenRouter `opus` defaults on Claude Opus 5. Fable remains an explicit higher-capability choice.
- Make the named `claude-fable` workflow/review worker use 5.1.
- Add Fable 5.1 to direct-model routing and to all Anthropic proxy alternative maps.
- Preserve required-ZDR behavior on OpenRouter by falling back from both Fable versions to Opus 5.
- Document that materialized user proxy configuration is not rewritten automatically.

## Risks

- OpenRouter uses a dotted `5.1` slug while Anthropic and LiteLLM use the hyphenated API ID.
- Anthropic requires 30-day retention for Fable 5 and 5.1 unless it expressly authorizes ZDR.
- Forced tool choice is unsupported, and older Claude models cannot consume Fable 5.1 thinking blocks.
- Repointing only the catalog aliases would leave the review worker and proxy alternatives pinned to Fable 5.
- Omitting the ZDR fallback would make the new bundled alternative violate Forge's audited required-ZDR posture.
