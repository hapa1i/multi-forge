# Launch Codex through a direct OpenRouter proxy

Picked up on 2026-11-19. The maintainer approved the [execution checklist](checklist.md). The
[free loopback results](probe-results.md) are recorded. The [first paid manifest](paid-probe-manifest.json) stopped at
the unrestricted Fable baseline. The approved [Qwen manifest](paid-probe-manifest-qwen.json) also stopped when
OpenRouter reported that account-level ZDR excluded the sole Qwen endpoint. The maintainer selected the narrower stage
60 criterion below for this account. The [revised stage 60 manifest](paid-probe-manifest-qwen-account-zdr.json) ran and
stopped before Astra when Qwen's ZDR-specific 404 lacked the required structured reasons. On 2026-11-20 the maintainer
accepted that exact refusal. The Astra continuation passed with account ZDR enabled. Stage 70 verified cost and
generation identity for unary and streamed Astra responses. Stage 80 hit the $2 key's credit limit on the first native
call. The approved $5 retry passed with account ZDR enabled. Native Astra and Gemini read the fixture and wrote its
contents to a second file on resume. All 13 policy fixtures and the native Astra metadata run passed. The results are
ready for maintainer review before product implementation. [Probe results](probe-results.md) ·
[Stage 80 manifest](paid-probe-manifest-codex-only.json) · [Stage 80 receipt](evidence/paid-63d4a6f0/codex.json)

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

Forge can trace a local attempt even when the upstream supplies no identity. Stage 70 found reported cost on both unary
and streaming Astra requests. The route's missing-cost policy covers endpoints that omit the field.

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
- The Responses reference shows `usage.cost` in its usage example and a `resp_` ID in its full response example. Stage
  70 captured both modes and verified the actual response IDs against generation lookup.
  [Create a response](https://openrouter.ai/docs/api/api-reference/responses/create-a-response)

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

## Probe scope

The four stages used synthetic content. Stage 50 ran on localhost. Each live run used an operator-approved manifest. The
following criteria governed the probes. [Probe verdicts](probe-results.md#probe-verdicts) ·
[OpenRouter probe harness](../../../../scripts/experiments/openrouter/README.md)

1. **Codex request capture.** Repeat the local capture on the proxy floor, QA pin, general validation ceiling and
   0.170.0. Compare the TUI and `codex exec` with web search at its default and disabled. Retain distinct request
   layouts and measure how each binary displays and retries candidate refusals. A floor that requires another path or
   cannot run local tools under required ZDR reopens the route's compatibility decision.
2. **ZDR on this account.** Keep the account's ZDR setting on. Reuse the verified Qwen account-policy refusal as the
   baseline. Check the current ZDR catalog for Astra's presence and the absence of both Qwen slugs. With
   `provider.zdr=true` on both requests, require a ZDR-specific Qwen refusal and completed assistant text from Astra.
   Stop if Qwen is served. Keep the sanitized refusal as evidence for Forge's diagnostic. This establishes routing under
   the combined account and request settings. The independent effect of the request flag remains unverified.
3. **Cost and identity.** Capture unary and streaming responses with routing metadata off and on. Record where cost
   appears, the terminal event, the response ID, any selected-provider field, and whether an observed ID resolves
   through `/api/v1/generation`. Use the terminal usage for synchronous accounting. Allow for indexing delay when
   reconciling a completed generation.
4. **Codex against OpenRouter, without Forge.** In an isolated Codex home, apply the launcher's provider overrides with
   OpenRouter's base URL and key. With the default model and one non-OpenAI slug, read a synthetic fixture through a
   tool, use it in a follow-up turn and edit a scratch file. This pins whether OpenRouter accepts the observed request
   shapes, `client_metadata` and the `namespace` tool type, whether it executes a hosted tool, and whether fallback
   metadata is adequate. Replay the captured layouts over HTTP with Forge's intended ZDR and model settings. Use actual
   returned tool and reasoning items for the continuation. A non-OpenAI slug that cannot finish the task reopens the
   metadata decision.

## Decisions

- **Model metadata.** Keep the launcher's `env_key` contract. OpenAI slugs Codex recognizes use its bundled metadata.
  Other slugs run on fallback metadata and show Codex's warning, which the guide documents. A catalog relay
  (`GET /v1/models` with command auth) and `/model` picker discovery are a separate card.
- **Request guarantee.** The route preserves caller fields by value. Its routing changes are `provider.zdr=true` when
  ZDR is required and `model` when a configured fallback applies. Sibling `provider` keys pass through. With
  `allow_non_zdr`, Forge leaves both routing fields as supplied. Fallbacks come from `model_for_zdr_policy`, as on the
  Messages path, including operator-configured cross-family replacements. Forge omits `client_metadata` and
  `prompt_cache_key` on the direct route, including when `allow_non_zdr` is enabled.
- **Requested and effective model.** For OpenRouter Responses the downstream record carries the requested slug in
  `model` and the dispatched slug in `mapped_model`. The launcher prints both for a launch-time fallback.
  `forge telemetry trace show` exposes the pair for each dispatch, including an in-TUI model change. Metrics and cost
  breakdowns group by the dispatched slug.
- **Hosted tools.** Under required ZDR the route admits only client-executed tool types, in either request shape, and
  refuses others with a diagnostic that names the opt-out. For such a proxy the launcher adds `-c web_search="disabled"`
  so the default launch is not refused. Operator arguments follow the launcher's, so the proxy enforces the rule.
- **Unsupported operations.** For an OpenRouter source, the proxy answers every `/v1/responses/*` subresource with a
  local OpenAI-shaped error and makes no upstream call. Nothing unaccounted reaches the paid upstream. The LiteLLM route
  keeps relaying them.
- **Retries.** The relay does not retry. A Codex retry is a new request and passes the same policy and cap check.
- **Unreported cost.** On direct OpenRouter Responses, the proposed `costs.on_unreported_cost` defaults to `reject`. A
  completed or billable incomplete generation with missing cost blocks subsequent Responses creates on that proxy.
  Failed requests and cancellations before a terminal leave the flag clear. Create and start smoke tests report an
  unpriced generation on the attempt that incurred it. Restart clears the observed flag. A source-declared gap persists
  and dollar caps recover their recorded totals. With `allow` through `forge proxy set`, requests can continue and the
  launcher warns that unreported spend cannot count toward caps. Messages and other sources retain their cost policy.
- **Endpoint join.** A base whose path ends in `/v1` is the version root and gets `/responses`. Any other base gets
  `/v1/responses`. This keeps a custom gateway's prefix and the LiteLLM route. Apply `decisions_url`'s scheme and
  authority checks to OpenRouter bases. Existing HTTP LAN and Docker LiteLLM bases continue to work.
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
  Strip an inherited `OPENROUTER_API_KEY` from either sessionless proxy-backed Codex child. With dotenv disabled, a
  nested Forge command can still resolve the key from the Forge credential store. Exercise the environment and Forge
  credential-store paths with dotenv disabled. [Responses relay](../../../../src/forge/proxy/responses_passthrough.py) ·
  [Child environment](../../../../src/forge/session/codex_invoke.py) ·
  [Base validation precedent](../../../../src/forge/core/judgments/openrouter.py)
- **OpenRouter policy.** Apply the existing `provider.zdr` requirement and configured model fallbacks to the outgoing
  Responses request. A caller-supplied provider object cannot weaken a required policy. Apply the hosted-tool rule.
  Exercise the per-proxy opt-out and expose the requested and effective model when a fallback applies. Preserve opaque
  reasoning items, tool arguments and call IDs while setting routing fields. A structured account-ZDR refusal names the
  model and points to OpenRouter's privacy settings. A text-only ZDR refusal identifies the restriction without
  attributing it to a single policy. Suggest a ZDR-eligible model in either case. The Forge opt-out cannot override
  OpenRouter account or guardrail policy.
  [Forge's OpenRouter policy](../../../end-user/proxy.md#openrouter-zero-data-retention-zdr) ·
  [Fallback resolution](../../../../src/forge/proxy/model_routes.py)
- **Codex compatibility.** OpenRouter requires full history on each request and rejects stored-response continuation.
  The captured Codex requests already comply. Verify streaming, tool-result replay, compaction and a follow-up turn on
  the supported Codex binaries, for every distinct captured request shape. Answer unsupported Responses operations
  locally. Explicit model selection is the deliverable.
  [OpenRouter Responses API](https://openrouter.ai/docs/api_reference/responses/overview) ·
  [OpenRouter's Codex guide](https://openrouter.ai/blog/tutorials/codex-cli-openrouter/)
- **Spend and trace evidence.** Read `usage.cost` in unary and terminal streaming responses. Request
  `X-OpenRouter-Metadata: enabled` for the selected endpoint. Record the generation ID and provider in the existing
  `provider_generation_id` and `selected_provider` fields. Add no telemetry fields. Charge a generation once,
  distinguish missing cost from zero, and preserve upstream failure and disconnect evidence. Refuse after an unreported
  cost unless the operator has set the override, and print the launch notice when they have.

## Acceptance

1. Use a local OpenRouter-shaped upstream with the real Forge proxy, and every distinct captured Codex layout as a
   fixture. Assert the exact upstream URL for default and custom bases, the bearer, model and ZDR fields, and value
   equality of every other field under the chosen identifier policy. Add a synthetic encrypted reasoning item to copies
   of the captured tool continuations for both models. Cover conflicting caller settings, opt-out, fallback, a hosted
   tool, a subresource request, missing credentials and upstream errors, including the ZDR refusal. Check that the child
   environment has no `OPENROUTER_API_KEY`. Check that the launcher refuses a Messages-only proxy and still launches the
   existing LiteLLM Responses proxy, whose upstream URLs and subresource relay are unchanged.
2. Build cost fixtures from the shapes the cost probe captured. Reconcile them with `forge proxy metrics`,
   `forge telemetry costs show` and `forge telemetry trace explain`. A repeated terminal usage event charges once. A
   subsequent request over a configured reject cap stops at Forge. After a completed generation with no cost, the next
   request and the smoke test are refused with a diagnostic naming the override. With the override set, requests
   continue, cost stays unavailable and the launcher prints its notice. A cancelled stream does not trip the check. An
   existing LiteLLM Responses proxy whose upstream sends no cost header keeps serving.
3. With dotenv disabled, once per credential source, `forge proxy create codex-responses-openrouter --json --smoke-test`
   emits one result object and `forge runtime preflight codex --proxy <proxy_id>` reports `proxy_supported`. The smoke
   passes with reported cost or explicit opt-in. A missing-cost refusal exits nonzero and leaves the proxy available for
   inspection.
4. Run a small live Codex TUI smoke against OpenRouter under an approved manifest. The manifest names the Codex version,
   both models, a reject cap and at most three prompts per model. Configure and verify the cap on the named proxy, then
   launch by its exact ID. With the default model and an explicit non-OpenAI slug, have Codex read a synthetic fixture
   through a tool, use its result in the next turn and edit a scratch file. Correlate the requested model, dispatched
   model and generation through `forge telemetry trace show` and
   `forge model backend reconcile openrouter --request-id`. Record the client version, catalog behavior and supported
   operations.
5. Verify the template ships in the wheel. Update the runtime design: the wire shape's guarantee, which now says
   byte-for-byte, the unsupported-operation rule and the template inventory. Update the end-user proxy guide with the
   tested launch command, credential, model selection, unreported-cost override and observed limitations. The guide's
   [Codex launch section](../../../end-user/proxy.md#start-codex-with-a-responses-capable-proxy) sits in a file at its
   25,000-token target, so the change must net out or move that section to its own guide.

## Open questions and risks

- **Client identifiers.** All 18 retained fixtures carry `client_metadata`. Their `prompt_cache_key` also equals the
  session and thread IDs. Passing through both fields discloses native identifiers by default. The Messages route's
  Forge-generated, hashed grouping ID is opt-in. The direct Responses route drops both native fields. OpenRouter
  receives no Codex cache grouping key from this route.
- **BYOK cost.** OpenRouter documents `usage.cost` as its account charge and reports the provider charge separately in
  `cost_details`. A Forge cap based on the former can undercount provider-billed inference. The paid key included BYOK
  in its limit. Forge measures OpenRouter account credit using `usage.cost`. A separate BYOK provider bill falls outside
  that cap. [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)
- **Astra encrypted reasoning.** Stage 80 verified encrypted tool continuation on Gemini. Astra emitted no reasoning
  item during this task. The implementer owns the synthetic fidelity check in the checklist and retains this limit on
  the live claim.
- **Client coupling.** The request shape changed with model metadata inside one binary. The tool allow-list and fixtures
  follow captured shapes, so required ZDR refuses a new Codex tool type until Forge admits it. Retain 0.141.0 as the
  launcher floor for the tested task. Its evidence is from loopback and HTTP fixture replay. The native paid run used
  0.170.0.
- **Cross-family fallback.** Codex picks the request shape from the requested slug. Built-in fallbacks stay within a
  model family. An operator-configured fallback across families would send one family's shape to another.
- **Cancelled streams.** A stream cancelled before its terminal event reports no cost. Forge records that cost as
  unavailable, so the cap undercounts it.
