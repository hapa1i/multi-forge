# Count the full GPT-6.2 Ultrafast cost above 272,000 input tokens

Shipped on `main` on 2026-11-23. [Completed checklist](checklist.md)

During launch, OpenAI prices Ultrafast at three times the Standard rate for the request's context length. Forge's
bundled Astra and Sol deployments specify the short- and long-context prices. LiteLLM 1.102.2 drops the long-context
Ultrafast fields from its pricing lookup. At 272,001 input tokens the gateway reports the Standard amount, and Forge
uses that amount for telemetry and daily and monthly proxy caps.
[OpenAI pricing](https://developers.openai.com/api/docs/pricing)

Forge launches its pinned LiteLLM 1.102.2 gateway through `forge.backend.litellm_pricing`. The calculator reads the
selected deployment's registered Ultrafast prices and accounts for 12-hour writes when the upstream response reports
their count. Verify output and cache pricing at 272,000 and 272,001 input tokens. Operators with saved local deployments
can merge the new retention rates into their existing pricing. Independently operated gateways require a compatible
calculator and matching deployment prices.

The [March price change](../../todo/gpt_62_ultrafast_pricing/card.md) tracks the later six-times multiplier.
