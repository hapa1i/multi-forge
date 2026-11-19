# Add Gemini 4 Neon and Hydrogen as the Gemini defaults

User-authorized November 19, 2026. Branch: `neon`, based on `main` at `819717bd`.

Make Gemini 4 Neon the Gemini Sonnet/Opus default and Gemini 4 Hydrogen the Haiku and Flash-template default across the
intrinsic catalog, provider routes, fresh Gemini templates, local LiteLLM deployments, and workflow selection. Carbon,
Argon, and Gemini 3.8 Flash remain explicit choices. Saved user-owned proxy and backend configurations are unchanged.

Both models differ from Carbon and Argon in ways that prevent copying their entries:

- **Thinking:** `low`, `medium`, `high`, and `xhigh`, with `high` as the native default. Carbon and Argon stop at `high`
  and default to `medium`.
- **Vertex unary output:** one 65,536-token foreground limit for streaming and non-streaming requests. Carbon and Argon
  allow 32,768 on non-streaming Vertex requests, which Forge enforces with a clamp that must not include either model.
- **Price per million tokens, flat across the window, no introductory schedule:** Neon $3 input, $15 output, $0.15
  cached input. Hydrogen $1.50, $7.50, and $0.075.

They share the unified 1,048,576-token context, 65,536-token synchronous output, ignored sampling parameters, and
implicit-only caching with a 4,096-token minimum. Long decode through continuation or background execution stays outside
Forge's request contract.

## Decisions

- **Defaults follow the owner's mapping.** Google positions Hydrogen as its everyday default and the upgrade from Gemini
  3.8 Flash, Neon between Hydrogen and Carbon, and Carbon for the hardest problems. Forge maps Hydrogen to the Flash
  position and Neon to the main tiers.
- **Google's default effort over OpenRouter's.** OpenRouter's metadata reports `default_effort: medium` for both models;
  Google's Gemini API and Vertex guides state `high`. The intrinsic catalog records Google's value.
- **Haiku pins `low` on the Pro-family templates.** Those templates set no Haiku effort, so a Haiku request without
  thinking would otherwise run Hydrogen at its native `high` on LiteLLM routes. The Flash templates already pin `low`.
- **Policy helpers stay on Gemini 3.8 Flash.** The plan-check and team-tagger defaults are owned by the policy domain
  and have lagged the template Flash default before. The plan checker has three provider routes and a 15-second review
  budget without an explicit effort; the team tagger uses local LiteLLM only. Moving either needs its own latency and
  verdict evaluation.
- **Forge covers LiteLLM 1.102's Gemini 4 gaps for all four models.** Review found that the bundled metadata sent the
  system prompt as user text and that Google AI rejected unsigned tool history from another model. Carbon and Argon had
  both defects, so the fixes include them. OpenRouter needed neither fix.
- **Flex and Priority rates cover Neon and Hydrogen only.** Carbon and Argon still report Standard cost for those tiers;
  their rates change with the December 1 price increase.

## Risks

- Google requires a paid-tier project for Neon on the Gemini API, and limits Vertex access to verified enterprise
  customers in `global`, `us`, and `eu`. A free-tier `GEMINI_API_KEY` can serve Hydrogen but not the Neon Sonnet/Opus
  default on the local route; a shared gateway must serve both `vertex_ai/` deployments.
- A thinking budget of 25,000 tokens or more from Claude Code derives `xhigh`. Carbon clamps that to `high`; Neon and
  Hydrogen honor it, so the same client setting spends more.
- Hydrogen costs twice Gemini 3.8 Flash's promotional price through December 31, 2026. Neon costs 50% more than Carbon
  through November 30, then 25% less when Carbon's introductory price ends.

Sources checked November 19, 2026:

- [OpenRouter Neon](https://openrouter.ai/google/gemini-4-neon) and
  [Hydrogen](https://openrouter.ai/google/gemini-4-hydrogen)
- [OpenRouter ZDR endpoints](https://openrouter.ai/api/v1/endpoints/zdr)
- [Google Neon migration and pricing](https://aistudio.google.com/docs/whats-new-gemini-4-neon)
- [Google Hydrogen migration and pricing](https://aistudio.google.com/docs/whats-new-gemini-4-hydrogen)
- [Google pricing](https://aistudio.google.com/docs/pricing)
- [Vertex Neon request limits](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-neon)
- [Vertex Hydrogen request limits](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-hydrogen)
