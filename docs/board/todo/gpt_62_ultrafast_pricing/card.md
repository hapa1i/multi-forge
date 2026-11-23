# Update GPT-6.2 Ultrafast pricing for March 1, 2027

Review before **2027-03-01 (Pacific time)**. OpenAI lists the Ultrafast launch rate for GPT-6.2 Astra and Sol at 3 times
Standard through February 28 and 6 times Standard beginning March 1. This applies to the Standard rate for the request's
context length. [OpenAI pricing](https://developers.openai.com/api/docs/pricing)

Forge ships explicit prices for both deployments in `src/forge/config/defaults/backends/litellm.yaml`. The
[long-context accounting fix](../../done/gpt_62_ultrafast_long_context_cost/card.md) covers the launch period.

- Recheck OpenAI's effective prices and the locked LiteLLM cost map before the change takes effect. Update the bundled
  inputs, outputs and cache rates for both models wherever a deployment override is still required.
- Run the offline service-tier pricing tests at 272,000 and 272,001 input tokens. Verify the new multiplier for both
  models on input, output, cache reads, and cache writes with 30-minute and 12-hour retention.
- Update the model selection guide and the saved-backend upgrade instructions so operators can refresh their
  materialized deployments.
  [GPT-6.2 pricing and upgrade guide](../../../end-user/model_selection.md#gpt-62-astra-and-sol)
