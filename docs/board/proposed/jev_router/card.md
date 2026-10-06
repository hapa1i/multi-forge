# Jev Router support

Status: proposed. Separate from the [Jev judgments epic](../epic_jev_support/card.md) and its A1–A3 cards.

## Problem and outcome

OpenRouter's Jev Router selects a generative model **and reasoning effort** per request. This could automate model
selection for explicitly paid Forge workloads, but it does not fit Forge's current assumption that routing has already
identified the model whose capabilities and effort limits apply. Establish a supported routing contract before exposing
`typesafe/jev-router` as a normal model option.

The shipped [launch-effort change](../../done/session_launch_effort/card.md) (#257) gives explicit client effort
precedence on opted-in translated requests and normalizes it against the mapped model. Router-selected effort creates an
unresolved ownership conflict; the provider documentation does not establish whether caller effort wins, is ignored, or
constrains routing. A successful completion alone would not resolve that ambiguity.

OpenRouter documents Chat Completions, Responses and Messages support, including streaming, and optional metadata for
resolved models and routing fallback. An inclusion filter with no matches is ignored, so it cannot serve as a strict
model allowlist. Exclusions still apply; an empty resulting pool returns 404.
[Router documentation](https://openrouter.ai/docs/guides/routing/routers/jev-router)

## Design questions and scope

- Separate the requested router from the actual selected model/provider in model identity, telemetry, usage and replay.
  Preserve resolved-model/fallback evidence across streaming and translation, including failed requests.
- Define effort ownership for explicit client effort, Forge defaults and router-selected effort. Probe the combinations
  before choosing a contract; reject unsupported combinations rather than silently weakening #257's explicit-effort
  guarantee. Normalize sampling and reasoning only when the selected model's capabilities are known.
- Establish a safe context budget for the eligible model set, including output headroom and tool history. Do not
  advertise the context window of a preferred candidate when the router can select a smaller one.
- Require `provider.zdr: true` on every OpenRouter request/retry and verify its interaction with router selection and
  provider fallback. A post-response model check cannot undo disclosure. A strict candidate policy needs provider-side
  enforcement or refusal before dispatch; the documented inclusion filter alone is insufficient.
- Verify tools, structured output, streaming and Forge's relevant wire translations against the routed candidates.
  Expose actual failures and unsupported capabilities instead of treating the router as a uniform model family.
- Make the route an explicit paid opt-in. Compare actual reported cost, latency and task quality with a fixed-model
  baseline, including routing failures and fallback. This route does not spend only Jev judgment prices and does not
  satisfy everyday subscription-only supervision.

## Acceptance and validation

- Record the effort-precedence and candidate/context/ZDR decisions with supporting provider evidence and budgeted probe
  results. If an essential constraint cannot be enforced, retain an explicit unsupported result rather than enable the
  route under an inaccurate contract.
- Test empty inclusion matches, an excluded/empty candidate pool, unavailable ZDR candidates, oversized input,
  requested-versus-selected identity, retries and fallback. Verify streaming and non-streaming usage attribution without
  double counting. Use fixtures for ordinary tests and explicitly selected, budgeted live probes.
- Before product support ships, verify relevant proxy/model CLI and telemetry surfaces, sync runtime and end-user route
  documentation, and ensure installed configuration distinguishes the router from a fixed-model deployment.

## Boundary

This is dynamic generative-model routing, independent of Jev's typed Decisions client, semantic rule packs and
plan-check cascade. The [research](../epic_jev_support/research.md#jev-router-separate-card) records the distinction. No
dependency on A1 or the Codex supervisor epic is assumed.
