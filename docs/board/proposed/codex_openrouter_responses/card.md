# Launch Codex through a direct OpenRouter proxy

Proposed on 2026-11-19.

## Operator outcome

Give the sessionless Codex TUI a Forge-owned route to OpenRouter, including non-OpenAI models. The proposed template is
`codex-responses-openrouter`.

```bash
forge codex start --proxy codex-responses-openrouter
forge codex start --proxy codex-responses-openrouter -- -m google/gemini-4-carbon
```

The first command should use the template's default model. The second should select the explicit OpenRouter slug,
subject to the proxy's configured zero data retention (ZDR) policy. Both should work with the OpenRouter credential
alone. The operator gets Forge's proxy traces and spend caps while Codex runs its usual local tools.

Today `codex-responses-local` is the only template the launcher accepts. It needs an OpenAI API key and a local LiteLLM
backend, and it serves OpenAI models only.

Traces need nothing from the upstream. Spend caps need OpenRouter to report cost on this endpoint, which its
documentation does not promise. The cost probe below settles that. Without reported cost, the route runs only after the
operator opts in.

## Verified on 2026-11-19

Forge code:

- The relay joins `{base}/v1/responses`. OpenRouter's base is `https://openrouter.ai/api/v1`, so the request would go to
  `/api/v1/v1/responses`.
- The relay reads cost only from the `x-litellm-response-cost` response header. It records no generation ID or selected
  provider.
- The relay makes one upstream attempt. A transport error returns 502.
- The ingress parses each POST body and serializes it again, and forwards only the `openai-beta` request header. The
  route already preserves values, not bytes.
- Only `POST /v1/responses` is cap-checked and charged. Other `/v1/responses/*` paths are relayed unaccounted. The proxy
  has no `/v1/models` route.
- The Codex child keeps an inherited `OPENROUTER_API_KEY`.
- The proxy already resolves the `openrouter` credential for a Responses source and labels OpenRouter cost as
  `reported`. `forge proxy create|start --smoke-test` already posts a unary request through the same relay.

OpenRouter documentation:

- Responses is stateless. Each request carries the full history, and `store: true` or a non-null `previous_response_id`
  returns 400. `POST /api/v1/responses` is the only documented operation.
- The `provider` object, including `zdr`, is documented for Responses. The error for a model with no ZDR endpoint is
  not. Tool backends are not filtered by `zdr`.
- Cost fields are documented for Chat Completions only. The Responses usage example has token counts and a `resp_` ID.

Local capture of Codex 0.170.0 (`codex exec`, the launcher's provider overrides, a loopback stub). It is preliminary:
the logs are not retained, and 0.170.0 is above the 0.161.0 validated ceiling.

- With the launcher's `env_key` credential, Codex called only `POST /v1/responses` and never requested a model catalog.
  `google/gemini-4-carbon` produced Codex's fallback-metadata warning. `openai/gpt-6.2-astra` was recognized.
- With command auth, Codex requested `GET /v1/models?client_version=0.170.0`. A 404 was not fatal.
- Every request had `store: false`, `stream: true`, no `previous_response_id` and the full history, including tool calls
  and results. Automatic compaction ran as ordinary `POST /v1/responses` requests.
- The request shape depends on the metadata Codex resolves. A fallback-metadata model gets top-level `tools` of type
  `function`, `namespace` and `web_search`. A recognized model gets an `additional_tools` input item, `text.verbosity`
  and `reasoning.context`, and showed no hosted tool.
- Both shapes carry `client_metadata`. In the fallback shape it holds Codex's installation, session and thread IDs.
  `-c web_search="disabled"` removes the hosted tool.
- With the compaction limit forced low and a stub that always reported usage above it, Codex sent 2,055 requests in 60
  seconds. Forge's cap is the only bound on such a loop.

## Probe first

Pin these facts before promotion to `todo/`, as operator-gated stages in the
[OpenRouter probe harness](../../../../scripts/experiments/openrouter/README.md). The first stage is free. The others
spend OpenRouter credit and need an approved manifest. Use synthetic content throughout.

1. **Codex request capture.** Repeat the local capture with retained, sanitized logs on the proxy contract floor
   (0.141.0), the QA-pinned binary and the newest admitted binary. Include the TUI, which may request more than
   `codex exec`. A binary that calls another path, or a floor that behaves differently, reopens the metadata and
   unsupported-operation decisions.
2. **ZDR enforcement.** Take a model with no ZDR endpoint from that day's ZDR endpoint catalog. The built-in fallback
   table names candidates. It must succeed without `provider.zdr` and be refused with `provider.zdr: true`. A ZDR-listed
   model must succeed with the field. A refused baseline is inconclusive, because account-level enforcement masks the
   field. Stop if the model is served with the field set. Keep the refusal's status and body as the fixture for Forge's
   diagnostic.
3. **Cost and identity.** Capture one unary and one streaming response. Record where cost appears, the terminal event,
   the response ID, any selected-provider field, and whether the ID resolves through `/api/v1/generation`. A response
   with no cost does not stop the card. The route then ships behind the unreported-cost override, and the source
   declares the gap so the refusal comes before the first request. A delayed generation lookup stays a different design.
4. **Codex against OpenRouter, without Forge.** In an isolated Codex home, apply the launcher's provider overrides with
   OpenRouter's base URL and key. With the default model and one non-OpenAI slug, read a synthetic fixture through a
   tool, use it in a follow-up turn and edit a scratch file. This pins whether OpenRouter accepts both request shapes,
   `client_metadata` and the `namespace` tool type, whether it executes a hosted tool, and whether fallback metadata is
   adequate. A non-OpenAI slug that cannot finish the task reopens the metadata decision.

## Decisions

These hold unless a probe reopens them.

- **Model metadata.** Keep the launcher's `env_key` contract. OpenAI slugs Codex recognizes use its bundled metadata.
  Other slugs run on fallback metadata and show Codex's warning, which the guide documents. A catalog relay
  (`GET /v1/models` with command auth) and `/model` picker discovery are a separate card.
- **Request guarantee.** The route preserves caller fields by value. Forge owns two: `provider.zdr`, forced to `true`
  when ZDR is required, and `model`, when a configured fallback applies. Other `provider` keys pass through. With
  `allow_non_zdr`, Forge sets neither. Fallbacks come from `model_for_zdr_policy`, as on the Messages path.
- **Requested and effective model.** The trace records the requested slug in `model` and the dispatched slug in
  `mapped_model`. Both fields exist. The launcher prints both when the launch model has a fallback. A model changed
  inside Codex shows only in `forge telemetry trace show`.
- **Hosted tools.** Under required ZDR the route admits only client-executed tool types, in either request shape, and
  refuses others with a diagnostic that names the opt-out. For such a proxy the launcher adds `-c web_search="disabled"`
  so the default launch is not refused. Operator arguments follow the launcher's, so the proxy enforces the rule.
- **Unsupported operations.** For an OpenRouter source, the proxy answers every `/v1/responses/*` subresource with a
  local OpenAI-shaped error and makes no upstream call. Nothing unaccounted reaches the paid upstream. The LiteLLM route
  keeps relaying them.
- **Retries.** The relay does not retry. A Codex retry is a new request and passes the same policy and cap check.
- **Unreported cost.** The route fails closed, with a manual override. After a completed generation reports no cost, the
  proxy refuses further generations and names the override. The create and start smoke tests apply the same check. The
  state is in memory, like cap counters. The proposed override is `costs.on_unreported_cost`, beside `costs.on_cap_hit`:
  `reject` by default, and `allow` through `forge proxy set`. Under `allow`, requests run, cost stays unavailable, not
  zero, and caps cannot fire. The launcher says so at each launch. Nothing in Forge then bounds a client loop. The key
  governs this route only. Other routes keep recording missing cost as unavailable and serving.
- **Endpoint join.** A base whose path ends in `/v1` is the version root and gets `/responses`. Any other base gets
  `/v1/responses`. This keeps a custom gateway's prefix and the LiteLLM route. Validate the base as `decisions_url`
  does: HTTP(S), no credentials or query, HTTPS for remote hosts.
- **Session routing.** The template is not added to `model_routes.yaml`. Its Messages ingress is the existing translated
  OpenRouter path and keeps that path's policy.

## Implementation

- **Route and launch.** Give the direct OpenRouter source Responses capability and the new template the
  `openai_responses_passthrough` wire shape. Add the template to `OPENROUTER_TEMPLATE_NAMES`. Reuse the launcher's live
  identity and capability checks, temporary provider overrides and loopback credential. Keep managed Codex sessions
  outside this card. A saved Messages proxy, including `openrouter-openai-codex`, should continue to report its actual
  wire shape. [Source catalog](../../../../src/forge/backend/sources.py) ·
  [Launcher contract](../../../design.md#34-proxy-vs-no-proxy-mode)
- **Endpoint and credentials.** Join the path once for both default and custom bases, preserving the LiteLLM route.
  Strip an inherited `OPENROUTER_API_KEY` from the Codex child. Forge commands that Codex runs then resolve the
  credential from the Forge credential store only. Credential resolution in the proxy needs no change. Exercise the
  environment and Forge credential-store paths with dotenv disabled.
  [Responses relay](../../../../src/forge/proxy/responses_passthrough.py) ·
  [Child environment](../../../../src/forge/session/codex_invoke.py) ·
  [Base validation precedent](../../../../src/forge/core/judgments/openrouter.py)
- **OpenRouter policy.** Apply the existing `provider.zdr` requirement and configured model fallbacks to the outgoing
  Responses request. A caller-supplied provider object cannot weaken a required policy. Apply the hosted-tool rule.
  Exercise the per-proxy opt-out and expose the requested and effective model when a fallback applies. Preserve opaque
  reasoning items, tool arguments and call IDs while setting routing fields. Turn OpenRouter's ZDR refusal into a
  diagnostic that names the model and the opt-out.
  [Forge's OpenRouter policy](../../../end-user/proxy.md#openrouter-zero-data-retention-zdr) ·
  [Fallback resolution](../../../../src/forge/proxy/model_routes.py)
- **Codex compatibility.** OpenRouter requires full history on each request and rejects stored-response continuation.
  The captured Codex requests already comply. Verify streaming, tool-result replay, compaction and a follow-up turn on
  the supported Codex binaries, for both request shapes. Answer unsupported Responses operations locally. Explicit model
  selection is the deliverable. [OpenRouter Responses API](https://openrouter.ai/docs/api_reference/responses/overview)
  · [OpenRouter's Codex guide](https://openrouter.ai/blog/tutorials/codex-cli-openrouter/)
- **Spend and trace evidence.** Read OpenRouter's reported cost where the cost probe finds it, in unary and terminal
  streaming responses. Record the generation ID and selected provider in the existing `provider_generation_id` and
  `selected_provider` fields. Add no telemetry fields. Charge a generation once, distinguish missing cost from zero, and
  preserve upstream failure and disconnect evidence. Refuse after an unreported cost unless the operator has set the
  override, and print the launch notice when they have.

## Acceptance

1. Use a local OpenRouter-shaped upstream with the real Forge proxy, and both captured Codex request shapes as fixtures.
   Assert the exact upstream URL for default and custom bases, the bearer, model and ZDR fields, and value equality of
   every other field, including encrypted reasoning items. Cover conflicting caller settings, opt-out, fallback, a
   hosted tool, a subresource request, missing credentials and upstream errors, including the ZDR refusal. Check that
   the child environment has no `OPENROUTER_API_KEY`. Check that the launcher refuses a Messages-only proxy and still
   launches the existing LiteLLM Responses proxy, whose upstream URLs and subresource relay are unchanged.
2. Build cost fixtures from the shapes the cost probe captured. Reconcile them with `forge proxy metrics`,
   `forge telemetry costs show` and `forge telemetry trace explain`. A repeated terminal usage event charges once. A
   subsequent request over a configured reject cap stops at Forge. After a completed generation with no cost, the next
   request and the smoke test are refused with a diagnostic naming the override. With the override set, requests
   continue, cost stays unavailable and the launcher prints its notice. A cancelled stream does not trip the check. An
   existing LiteLLM Responses proxy whose upstream sends no cost header keeps serving.
3. With dotenv disabled, once per credential source, `forge proxy create codex-responses-openrouter --json --smoke-test`
   emits one passing result object and `forge runtime preflight codex --proxy <proxy_id>` reports `proxy_supported`.
4. Run a small live Codex TUI smoke against OpenRouter under an approved manifest. The manifest names the Codex version,
   both models, a reject cap and at most three prompts per model. With the default model and an explicit non-OpenAI
   slug, have Codex read a synthetic fixture through a tool, use its result in the next turn and edit a scratch file.
   Correlate the requested model, dispatched model and generation through `forge telemetry trace show` and
   `forge model backend reconcile openrouter --request-id`. Record the client version, catalog behavior and supported
   operations.
5. Verify the template ships in the wheel. Update the runtime design: the wire shape's guarantee, which now says
   byte-for-byte, the unsupported-operation rule and the template inventory. Update the end-user proxy guide with the
   tested launch command, credential, model selection, unreported-cost override and observed limitations. The guide's
   [Codex launch section](../../../end-user/proxy.md#start-codex-with-a-responses-capable-proxy) sits in a file at its
   25,000-token target, so the change must net out or move that section to its own guide.

## Open questions and risks

- **Installation ID.** `client_metadata` would carry Codex's installation, session and thread IDs to OpenRouter. The
  LiteLLM route already forwards the field. Proposed: forward it unchanged and document it. Stripping it would make a
  third Forge-owned field.
- **Client coupling.** The request shape changed with model metadata inside one binary. The tool allow-list and fixtures
  follow captured shapes, so required ZDR refuses a new Codex tool type until Forge admits it. The 0.141.0 floor was
  validated against LiteLLM only. Decide after the capture stage whether this route keeps it.
- **Cross-family fallback.** Codex picks the request shape from the requested slug. Built-in fallbacks stay within a
  model family. An operator-configured fallback across families would send one family's shape to another.
- **Cancelled streams.** A stream cancelled before its terminal event reports no cost. Forge records that cost as
  unavailable, so the cap undercounts it.
