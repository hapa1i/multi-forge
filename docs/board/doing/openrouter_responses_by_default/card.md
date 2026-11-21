# Enable Responses by default on all OpenRouter proxies

Forge 1.1.8 refused `forge codex start --proxy cyan-coconut` when this saved `openrouter-gemini` proxy used
`wire_shape: openai_translated`. With a one-field edit and restart, the same ID and port advertised Responses and
`google/gemini-4-neon`. The workaround also switches the bare smoke test to Responses and makes the proxy-wide audit
report describe Responses even for Claude's translated Messages. An upgrade and restart should enable both clients on
the original saved configuration. [Original Responses card](../../done/codex_openrouter_responses/card.md)

## Routing and upgrade decisions

- Replace the OpenRouter rule requiring both a proxy-wide Responses wire shape and a Responses-capable backend. The
  OpenRouter source enables `POST /v1/responses` for every model family. Live launch still verifies the proxy ID,
  template and advertised endpoint capability. A direct OpenRouter launch also needs the live Responses policy to select
  the correct ZDR, tool and cost behavior. An explicit `openai_responses_passthrough` profile retains its Responses
  smoke default and legacy launch contract. The existing shape-and-source rule and subresource relay apply to
  `codex-responses-local`. [Recorded launcher invariant](../../impl_notes/runtime_telemetry.md)
- For a snapshot with a missing or blank `backend`, accept an exact `provider: openrouter` with the same saved upstream,
  subject to the direct Responses URL validator. An explicit unknown or conflicting backend is ineligible. Scope this
  fallback to the Responses handler, advertised policy, preflight, credentials and accounting. Preserve the saved file
  bytes and legacy Messages attribution and provider-trace behavior.
- Saved-config preflight predicts support after restart. At launch, a matching 1.1.8 process that still advertises
  Responses as disabled gets a refusal naming the stop/start commands for that ID. A different proxy on the port remains
  an identity error. A verified older proxy advertising the legacy shape and capability can still serve Codex. An older
  launcher needs upgrading to discover Responses on a translated profile.
- Claude uses the saved tiers, alternatives and overrides. Codex uses the proxy's default tier model or an explicit
  OpenRouter slug, subject to the saved routing policy. At Codex launch, disclose when Messages inspection is enabled
  and Responses has no body audit. On a saved `allow_non_zdr=true` profile, disclose that Forge permits hosted tools and
  caller-supplied routing. Account restrictions still apply. [Codex proxy contract](../../../end-user/codex_proxy.md)
- Both endpoints charge one proxy spend cap. Use Responses eligibility when validating, loading and enforcing
  `costs.on_unreported_cost`. An absent policy means `reject`. Honor an explicit saved `allow`, including one 1.1.8
  ignored on a translated proxy, and surface the uncounted-spend notice at launch. Recovery from a missing-cost block
  uses an operator-initiated restart. It can interrupt either client and clears in-memory effort observations. Recorded
  spend survives. [Spend and recovery](../../../end-user/codex_proxy.md#spend-and-diagnostics)

## Endpoint-specific audit and smoke tests

Add per-endpoint inspection and reasoning-preservation reports to `GET /`. Keep top-level `wire_shape` and `intercept`
as the legacy profile view for older clients. Claude's status line reads the Messages report. Translated Messages
supports system-prompt inspection and drops signed thinking blocks. Responses preserves opaque reasoning by value and
has no body audit. Put the observed endpoint in the existing audit payload's `route.endpoint`, alongside the actual
`route.wire_shape`. Older records may lack the endpoint.
[Runtime audit design](../../../design_runtime.md#7x-optional-always-on-proxy-audit-and-control)

Add `--smoke-endpoint messages|responses` to select the endpoint of `--smoke-test` on `forge proxy create` and
`forge proxy start`. A bare check probes Messages on a translated profile and Responses on an explicit Responses
profile. A translated Messages probe sends a tier name. A Responses probe sends the upstream model slug. Probe only the
selected endpoint and name it in the human result and the create command's JSON alongside `passed` and `detail`.
[Proxy management CLI](../../../cli_reference.md#proxy-management)

## Acceptance evidence

Exercise both clients against a loopback upstream with synthetic credentials.
[Existing integration fixtures](../../../../tests/integration/proxy/test_codex_openrouter_responses_e2e.py)

1. Pin a synthetic pre-edit `cyan-coconut` fixture to `backend: openrouter` and `wire_shape: openai_translated`. Record
   the 1.1.8 Codex refusal. After restart on the new build, compare file bytes and exercise both clients on one port.
   Check Haiku/Hydrogen, Sonnet and Opus/Neon, a custom alternative, a tier override and a Codex tool continuation.
   Compare effective tier maps across all bundled OpenRouter templates.
2. Use a separate backend-less OpenRouter snapshot to verify live ZDR policy, the Codex web-search setting, Responses
   accounting and existing Messages attribution. Exercise an older running process, an older capable process,
   `codex-responses-local`, an unsupported backend and a wrong live ID as distinct cases.
3. Pin `wire_shape: openai_responses_passthrough` and `intercept.mode: inspect` in the audit fixture. Record the missing
   `(lossy)` label on 1.1.8. Assert both endpoint reports, the endpoint on a Messages audit record, the corrected Claude
   status and the Codex launch disclosure. Exercise the hosted-tools disclosure with a saved non-ZDR profile.
4. Check the upstream path and model for each explicit and bare smoke probe. Return a completed Responses generation
   without cost under the default policy. Its smoke must fail nonzero and the next Responses create must be refused.
   Messages smoke must still pass. Verify that both a newly set `allow` and a previously ignored saved `allow` admit
   unpriced Responses, surface the launch notice and leave the unreported charge unknown.
5. With a two-cent reject cap, charge one cent through each endpoint. The next generation on either endpoint must be
   refused before upstream dispatch.

## Risks and evidence limits

The recorded live Codex tool trials covered Astra and Gemini 4 Carbon. Passing the proposed loopback checks would
establish Forge routing across templates. Upstream model, tool and ZDR availability still vary. Responses traffic counts
under the proxy's default tier in `by_tier`, including when a caller supplies a different slug.
[Provider results](../../done/codex_openrouter_responses/probe-results.md)

A launch disclosure informs Codex users about body inspection. An operator who requires a Messages-only listener would
need a server-enforced opt-out covering direct HTTP callers. Whether to add that control is a separate decision.

At implementation, sync the launcher, runtime and telemetry designs, CLI reference and verification procedure. Keep
operator instructions in the Codex proxy guide, link them from the general proxy guide and submit the
implementation-note correction for human review. [Launcher contract](../../../design.md#34-proxy-vs-no-proxy-mode) ·
[Telemetry design](../../../design_telemetry.md) · [Proxy guide](../../../end-user/proxy.md) ·
[Verification procedure](../../../developer/verification.md#sessionless-codex-through-openrouter-responses)
