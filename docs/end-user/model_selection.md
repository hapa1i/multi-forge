# Choosing Models for Each Forge Role

Forge templates default per **role**, not per "newest available." A coding executor, a plan supervisor, a one-shot
reviewer, and a panel quorum worker reward different capabilities. A new model can be excellent for bounded coding work
and still be the wrong default for a long-context supervisor.

This page covers role selection, model capabilities, alternatives and model-specific upgrade requirements. Provider
benchmarks, pricing, context windows and cache behavior change quickly; check the linked provider references and
`forge proxy template show <name> --raw` before changing a team default.

- [Model capabilities and upgrades](#model-capabilities-and-upgrades): current release details and provider caveats
- [Proxy operations](proxy.md): setup, saved-configuration upgrades, transport and ZDR policy
- [Workflow workers](workflow.md#quick-start): available worker names, the default quorum and runtime readiness
- Skill model-family detection: [`skills.md`](skills.md#model-aware-resource-selection)
- Supervisor configuration: [`policy.md`](policy.md#semantic-supervisor-advanced)
- Auth and credentials: [`authentication.md`](authentication.md#which-auth-do-i-need)

---

## TL;DR

| Role                                  | Default posture                                                             | Why                                                              |
| ------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| **Executor** (writes code)            | Use the proxy/session model that performs best on your task envelope        | Coding quality, tool discipline, and latency matter most         |
| **Supervisor** (judges diffs vs plan) | Prefer the validated long-context default for that proxy's `opus` tier      | The job is retrieving and citing the right plan item             |
| **One-shot review**                   | Try newer/high-capability models freely                                     | The context is bounded and easier to validate                    |
| **Panel / debate**                    | Mix providers and model families                                            | Different defaults expose different bugs                         |
| **Memory writer**                     | Prefer a cheaper summarization-capable model after a review-only smoke test | Single-transcript synthesis is usually cost-sensitive            |
| **Cost-conscious supervision**        | Use warn-only mode until local validation proves blocker quality            | False-positive blocks are more expensive than missed suggestions |

The rule of thumb: **pin models per role, then validate locally**. Do not promote a newly released model to a
fail-closed supervisor role just because it improved on coding benchmarks.

---

## Why Context Fidelity Varies

Long-context behavior can change between model releases even when short-context coding scores improve. Providers tune
attention, caching, compression, reasoning budgets, and serving policy differently across versions. Those changes can
alter a model's ability to retrieve several similar facts from a long conversation.

That matters because Forge roles stress different failure modes:

1. **Supervisor**: long-context retrieval, citation fidelity, and confidence calibration.
2. **Executor**: coding quality, tool discipline, latency, and instruction following.
3. **One-shot reviewer**: bounded-context reasoning and bug finding.
4. **Memory writer**: summarization quality and cost.

Forge's `model_alternatives` field in proxy templates exists so you can keep more than one version of a vendor's model
available at the same proxy. You do not have to choose once for all roles.

---

## Supervisor Requirements

The semantic supervisor (`forge policy supervisor`) runs `claude -p --resume <planner_uuid> --fork-session` on
Write/Edit by default, throttled by policy settings. When routed through a proxy, Forge passes `--model opus` and clears
inherited executor model pins so the supervisor uses that proxy's `opus` tier. Its job is to read the planner's
conversation, locate the relevant plan section for the action being taken, and emit a verdict with cited evidence.

The model guidance below applies to the default `claude_code` runtime. The supervisor lane is selectable: pinning
`--supervisor-runtime codex` (or `forge policy supervisor set <target> --runtime codex`) routes checks to OpenAI's Codex
instead; `--model` selects an explicit reviewer model, so these Claude picks do not apply. Native Codex planning sources
have a narrower [tested model/auth matrix](native_supervision.md). The lane is frozen on the first check — see
[policy.md](policy.md#supervisor-runtime-lane).

This is **not** code writing. Coding leaderboards are useful context, but they are not sufficient for choosing a
supervisor. Validate these dimensions locally:

| Capability                               | What it controls                                                                                   | How to validate locally                                           |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Long-context retrieval                   | Whether the supervisor locates the right plan item among similar distractors                       | Run known aligned/divergent diffs against real planner sessions   |
| Structured output                        | Whether the verdict schema is honored without prose preamble or schema drift                       | Inspect `--json` output and parser failures                       |
| Confidence calibration                   | Whether high confidence means the verdict is actually right                                        | Track false-positive and false-negative examples                  |
| Citation fidelity                        | Whether quoted plan text appears verbatim or is paraphrased into something the user cannot inspect | Grep every cited phrase in the source plan/transcript             |
| Cache effectiveness on the stable prefix | Whether the supervisor prompt + plan override hits the provider's cache on each call               | Check `forge proxy metrics <proxy_id> --json` after repeated runs |

Supervisor cost is usually driven by the stable prompt/context prefix and any hidden reasoning tokens. Before changing
the model, confirm the selected provider is caching repeated supervisor calls and tune `reasoning_effort` if the proxy
exposes it.

---

## Role-Fit Matrix

Use this matrix with the current template catalog and provider docs:

| Family shape                    | Usually good for                                            | Be careful with                                     |
| ------------------------------- | ----------------------------------------------------------- | --------------------------------------------------- |
| Claude-family coding models     | Long-running executor sessions, supervisors, review passes  | Version-to-version long-context behavior changes    |
| OpenAI/Codex-family models      | Code review, code-focused execution, panel diversity        | Citation fidelity in fail-closed supervision        |
| Gemini-family models            | Cross-family supervision, large-context review, low latency | Gateway-specific cache/context limits               |
| DeepSeek/Kimi/Qwen/GLM/MiniMax  | Cost-conscious warn-only checks, panel dissent, bulk tasks  | Promoting to sole blocker without repo-local trials |
| Cheap/fast models in any family | Memory writer, taggers, pre-checks                          | High-consequence enforcement                        |

Treat this as a starting posture, not a benchmark table. Record the exact model version, provider route, source date,
and local validation result whenever you change a proxy default.

---

## Forge-Specific Patterns

### Select The Session Model Before Launch

Claude-runtime `forge session start|resume|fork|incognito --model <catalog-id-or-alias>` selects the requested model and
its durable launch route. A new Claude request stays direct unless you constrain it with `--proxy`; a non-Claude request
uses the first admissible packaged-catalog proxy. `--model-tier haiku|sonnet|opus` resolves a multi-tier proxy match and
requires `--model`. The selected route is printed before launch and reused by a later bare resume.

This may start a paid proxy, including with `--no-launch`. An explicit `--proxy` is strict, `--no-proxy` is Claude-only,
and Forge never falls through to a second provider after selecting a route. Forge `--model` is separate from Claude
Code's in-conversation `/model`: the Forge flag owns prelaunch session routing; `/model` changes the already running
Claude conversation.

The default `/walkthrough` makes the intent/evidence boundary visible with a direct Claude alias: it creates a
`--no-launch` session, shows the canonical requested model and null route commitment, then resumes it and inspects the
supported direct commitment. This is a teaching example; it does not imply that a pre-seeded conversation id proves a
runtime launch.

### Use `model_alternatives` Instead Of Multiple Proxies

Use the proxy's `model_alternatives` to compare versions without creating a proxy per model. The
[Claude mappings and caveats](#claude-alternatives-and-fable-retention) describe current choices; the
[proxy guide](proxy.md#model-alternatives) owns resolution and tier precedence.

```bash
# Planner/supervisor source on the proxy's default opus tier (Opus 5.5)
forge session start planner --proxy openrouter-anthropic

# Executor pinned to a ZDR-compatible alternative exposed by the same proxy
forge session start exec --proxy openrouter-anthropic --model claude-opus-4-8 --supervise planner
```

The executor's `--model` pin changes routing for that session's main Claude process. Proxied supervisor calls clear
inherited Claude model-pin environment variables and pass `--model opus`, so the proxy resolves the supervisor through
its `tiers.opus` mapping unless you choose a different supervisor proxy.

### Cross-Route The Supervisor

When the planner conversation is mid-long, multimodal, or expensive to supervise with the executor's family, route the
supervisor through another proxy and validate the result:

```bash
# Executor on one proxy, supervisor on another
forge policy supervisor set planner --session exec --supervisor-proxy openrouter-gemini

# Cost-conscious supervisor candidate in warn-only workflows
forge policy supervisor set planner --session exec --supervisor-proxy openrouter-deepseek
```

This is the side-channel architecture pattern: executor and supervisor use different proxies intentionally.
`apply_supervisor_routing()` auto-seeds the supervisor proxy from the planner's `confirmed.started_with_proxy` when you
do not pass `--supervisor-proxy`, so override only when you want non-default routing.

### Model-Route Scope

Model-route intent is session-local for proxied supervisors. If you select `--model claude-opus-4-8` on the executor,
the supervisor does not reuse that selection; it requests the configured supervisor proxy's `opus` tier.

For same-worktree final review, you can move the planner itself to a different model before resuming it:

```bash
forge session resume planner --model claude-opus-4-6
```

`resume --model` updates the session's stored model route and Claude execution pin, so later resumes keep using the
selected Claude version until you change it again.

When forking into the reviewer/executor role instead, pin the child directly:

```bash
forge session fork planner --name reviewer --model claude-opus-4-6
```

### Read Route And Provider-Declaration Evidence

Use `forge session model show <session> --json` to compare configured intent, the route Forge committed before launch,
and currently reachable proxy mappings. Use `forge session model history <session> --json` for the complete strictly
validated commit/abort sequence. These are route-provenance reads, not per-request traces: a proxy may change after
launch, and a request may select a different tier or alternative.

The optional status-line `marking` segment shows `mark:yes`, `mark:no`, or `mark:?` for the request model. Its source is
a dated provider declaration matched conjunctively against the canonical model and runtime/route/backend/billing scope.
`no` means the provider declared that exact scoped model unmarked; Forge did not inspect the output or admit it as safe.
An `effective_from` value becomes eligible on that UTC calendar date. The production catalog intentionally contains no
declarations at launch of this feature, so results remain unknown until a separate source review adds one.

Provider declarations do not replace isolation. The supported marking-sensitive workflow is still a fresh, transfer-free
producer in a distinct worktree: do not seed it with planner transcripts or other possibly marked content. Even an exact
live `unmarked` declaration says nothing about content already in context, later provider/proxy changes, watermark
persistence, or authorship.

### Direct-Mode Planner Constraint

If the planner runs in direct mode (no proxy, `ANTHROPIC_API_KEY` only), `should_supervisor_use_direct()` makes the
auto-seeded supervisor direct too. Otherwise the executor's inherited `ANTHROPIC_BASE_URL` could silently hijack the
supervisor request. In direct mode there is no proxy `opus` tier to restore; use `--supervisor-proxy` when you need the
supervisor to follow a Forge proxy mapping.

### Skill Model-Family Detection Follows The Proxy

`review`, `review-docs`, and `understand` auto-detect the model family from the proxy template's `opus` tier via
`forge session show --field model_family`. The Claude selectors are `/<name>` and the Codex selectors are `$<name>`.
Today, specialized code/document resources exist for OpenAI and Gemini; Anthropic and currently unmapped families use
the Anthropic-tuned default unless additional family resources and mappings are added.

---

## Cost Optimization Order

Three levers, applied in order. Skip ahead only if the cheaper lever does not move the cost enough:

### 1. Verify Cache Is Hitting

The supervisor's prompt template + plan override should behave like a stable prefix on providers that support prompt
caching. Check that the cache is actually active:

```bash
forge proxy metrics <proxy_id> --json   # look for cached_input_tokens > 0
```

Cache thresholds and discounts vary by provider and gateway. If the metric stays at zero after repeated comparable
supervisor calls, verify the proxy template and gateway support caching before changing models.

### 2. Tune `reasoning_effort`

The same model can cost more at higher effort settings. The supervisor's task is a structured verdict with citations; it
does not always require maximum reasoning. Try a lower effort and re-run known aligned/divergent examples:

```bash
forge proxy set <proxy_id> tier_overrides.opus.reasoning_effort=medium
```

Reserve higher effort for executor sessions or for supervisors where local validation proves it catches materially more
important divergences.

### 3. Swap The Model

If cache is hitting and effort is tuned but cost is still too high, test a cheaper family. Start in warn-only mode or as
a panel worker, collect false positives/negatives, and promote only after it performs well on your repo's real plans and
diffs.

---

## Validating New Model Releases

Major model releases periodically change behavior in ways that affect role suitability. Before adopting a new version as
your role default, check:

1. **Are long-context benchmarks reported for the context sizes you use?** If not, run local trials before using it for
   supervision.
2. **Has the tokenizer changed?** Effective cost can shift at unchanged per-token pricing.
3. **Are inference controls still exposed?** Less control over effort/reasoning budgets means less ability to tune
   cost-quality trade-offs.
4. **Is the prior version still available?** Forge's `model_alternatives` is the mechanism for keeping a validated prior
   choice accessible while new versions ship.
5. **Did your local validation pass?** A model whose reliability shifts silently between releases is not a stable
   foundation for fail-closed roles.

The validation loop:

```bash
# Pin the candidate on an executor session
forge session start trial --proxy openrouter-anthropic --model claude-opus-4-8

# Run supervisor evaluation on representative diffs
forge policy supervisor evaluate -f src/forge/session/store.py -r <trial-session-id> \
  --proxy openrouter-anthropic --json

# Compare verdict quality, citation accuracy, and false-positive rate
# against the prior version before promoting the new default
```

If verdict quality holds, update the template default. If it regresses on the role you are testing, keep the validated
prior version as the template default and expose the new version through `model_alternatives` for the roles where its
strengths matter.

---

## Model Capabilities And Upgrades

These notes describe the bundled defaults and the model-specific changes needed when adopting them. For the shared
edit/recreate, backup, validation and restart steps, use
[Updating saved proxy and backend configurations](proxy.md#updating-saved-proxy-and-backend-configurations).

### API model capabilities

Provider CLIs sometimes limit the models they serve. For example, OpenAI's Codex CLI caps GPT-5.5 at 400K tokens as a
serving-budget decision, even though the model supports 1,050,000 tokens via the API. Forge proxies route through the
API directly, so a proxy can use API context windows and reasoning effort levels that a product CLI may not expose.

It can also route to API models that product CLIs don't expose at all -- like `gpt-5.5-pro` (1M context) -- or to
different providers within a single workflow (GPT for planning, Claude for execution).

The tradeoff is cost: you pay API rates instead of bundled subscription pricing. Use Forge
[spend caps](proxy.md#cost-tracking-and-spend-caps) when you want warn/reject limits on that spend.

### Picking up GPT-6 Astra defaults after an upgrade

New proxies created from the current built-in OpenAI templates use GPT-6 Astra as follows:

| Template                     | GPT-6 Astra tiers |
| ---------------------------- | ----------------- |
| `openrouter-openai`          | sonnet, opus      |
| `litellm-openai`             | sonnet, opus      |
| `litellm-openai-local`       | sonnet, opus      |
| `openrouter-openai-codex`    | opus              |
| `litellm-openai-codex-local` | opus              |
| `codex-responses-local`      | sonnet, opus      |

The general Haiku tier remains GPT-5.4 Mini; Codex-specialized templates retain their coding Haiku/Sonnet models. GPT-6
Sol and Luna, GPT-6.1 Sol, and GPT-5.6 Sol are explicit alternatives. The OpenRouter OpenAI templates also expose
`gpt-6-astra-pro`, `gpt-6-sol-pro`, and `gpt-6-luna-pro`. For example:

```bash
forge session start astra-review --model astra-pro --proxy openrouter-openai
```

Both Astra variants require reasoning; supported efforts are `low`, `medium`, `high`, `xhigh`, and `max`. Replace
`reasoning_effort: none` with `low` or another supported effort, and remove temperature overrides when migrating an
older custom configuration. Forge routes standard Astra through Responses on LiteLLM backends. Pro is available through
OpenRouter in Forge; OpenAI's native API uses a reasoning mode on `gpt-6-astra` rather than a separate Pro model ID. See
the [OpenAI model reference](https://developers.openai.com/api/docs/models/gpt-6-astra) and
[reasoning guide](https://developers.openai.com/api/docs/guides/reasoning).

GPT-6.1 Sol is selectable with `--model gpt-6.1-sol`, `--model sol`, or `--model gpt-sol`; explicit `gpt-6-sol` pins
retain the prior version. Astra remains the OpenAI tier default. Like Astra, 6.1 Sol requires reasoning (`low` through
`max`, default `medium`) and rejects sampling overrides; `none` and `minimal` are unsupported. Forge uses Responses for
its native tool calls. Cache reads cost $0.10 per million tokens, half GPT-6 Sol's rate. See the
[GPT-6.1 Sol reference](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

GPT-6 Sol and Luna support `none` as well as `low`, `medium`, `high`, `xhigh`, and `max` reasoning effort, with `medium`
as their model default. They accept temperature and `top_p` overrides only with `none` effort. A tier mapped to Sol or
Luna must explicitly set `reasoning_effort: none` to configure a temperature override; otherwise proxy and template
validation reject the configuration. When Sol or Luna is selected as a model alternative, request-time filtering still
removes sampling overrides that may be valid for the tier's default model. Forge uses Responses for their native OpenAI
routes because reasoning with tool calls requires that API; Chat Completions accepts tool calls only with
`reasoning_effort: none`. Their Pro entries are OpenRouter-only alternatives, following Astra Pro's separate-slug
convention. See the [Sol](https://developers.openai.com/api/docs/models/gpt-6-sol) and
[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) model references. Selecting them explicitly does not
change the Astra tier defaults.

For an existing translated proxy, the Astra tier model is `openai/gpt-6-astra`. Local LiteLLM backends
(`litellm-openai-local`, `litellm-openai-codex-local`, and `codex-responses-local`) also need the `openai/gpt-6-astra`
deployment. Apply these changes with the
[saved-proxy/backend upgrade procedure](proxy.md#updating-saved-proxy-and-backend-configurations), which covers editing,
recreation and restart order.

LiteLLM 1.102 packages Astra and Gemini 3.8 Flash metadata. Argon, GPT-6.1 Sol, GPT-6 Sol/Luna, and Claude 5.5 require
the bundled routes' `model_info` blocks for offline capability and cost support. The GPT-6 entries cover cache tokens
and the above-272K input premium. For remote LiteLLM, its operator must install compatible deployments using that
server's upstream providers and credentials; the [Gemini Vertex deployment](#gemini-4-argon) differs from the bundled
Google AI deployment.

For workflow worker selection and readiness, see [workflow.md](workflow.md#quick-start). Existing OpenRouter proxies can
forward explicit GPT-6.1 Sol workflow requests. To select it as a session alternative, edit or recreate the proxy to
include `gpt-6.1-sol: openai/gpt-6.1-sol` in the intended tier's `model_alternatives`. Existing LiteLLM backends also
need the complete `openai/gpt-6.1-sol` deployment, including `use_responses_api: true` and `model_info`.

### Picking up current model defaults and alternatives after an upgrade

New proxies created from the current built-in templates use these defaults:

| Template                                            | New default tiers                                           |
| --------------------------------------------------- | ----------------------------------------------------------- |
| `openrouter-anthropic`, `litellm-anthropic(-local)` | sonnet -> Sonnet 5.5, opus -> Opus 5.5                      |
| `anthropic-passthrough`                             | Sonnet 5.5 / Opus 5.5 (informational; client selects model) |
| `openrouter-kimi`                                   | sonnet/opus -> Kimi K3                                      |
| `openrouter-qwen`                                   | haiku/sonnet -> Qwen3.8 27B, opus -> Qwen3.8 Max            |
| `openrouter-glm`                                    | sonnet/opus -> GLM 5.3                                      |
| `openrouter-gemini-flash`                           | all tiers -> Gemini 3.8 Flash                               |
| `openrouter-gemini`                                 | haiku -> Gemini 3.8 Flash, sonnet/opus -> Gemini 4 Argon    |
| `litellm-gemini`, `litellm-gemini-local`            | haiku -> Gemini 3.8 Flash, sonnet/opus -> Gemini 4 Argon    |
| `litellm-gemini-flash-local`                        | all tiers -> Gemini 3.8 Flash                               |

#### Gemini 4 Argon

Gemini 4 Argon replaces the older Gemini Pro models as the Sonnet/Opus default. Select it explicitly with
`--model gemini-4-argon`; prior Pro models, including `gemini-3.1-pro-preview`, remain explicit selections. Argon has a
unified 1,048,576-token context shared by input, thinking, and output. Forge uses its 65,536-token synchronous output
limit on Google AI. Vertex allows 65,536 output tokens per streaming request and 32,768 per unary request. Choose `low`,
`medium`, or `high` reasoning (`medium` is the model default); `temperature`, `top_p`, and `top_k` are ignored by Google
and are not supported Forge overrides. Argon supports implicit caching but not explicit context caches. See Google's
[model reference](https://ai.google.dev/gemini-api/docs/models/gemini-4-argon) and
[Vertex guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-4-argon).

Forge preserves output cutoffs, including partial tool calls; see the
[translated response contract](proxy.md#translated-response-limits-and-history).

The bundled LiteLLM entry uses Google's introductory Argon prices through November 30, 2026: $2 input, $10 output
(including thinking), and $0.10 cached input per million tokens. Google doubles those rates on December 1. Saved backend
configs retain their pricing metadata, so update the `model_info` rates explicitly when the promotion ends to keep cost
reporting accurate. Google Cloud has the same introductory rates. See Google's
[Gemini API pricing schedule](https://ai.google.dev/gemini-api/docs/latest-model#pricing) and
[Cloud launch pricing](https://cloud.google.com/blog/products/ai-machine-learning/gemini-4-argon-available-on-google-cloud).

To adopt Argon, follow the
[saved-configuration upgrade procedure](proxy.md#updating-saved-proxy-and-backend-configurations) with these Sonnet/Opus
tier models: `google/gemini-4-argon` for OpenRouter, `gemini/gemini-4-argon` for local LiteLLM, or
`vertex_ai/gemini-4-argon` for remote LiteLLM. Remove sampling overrides from those tiers and retain older models under
`model_alternatives` if you need explicit selections. LiteLLM also needs the corresponding deployment in its saved
backend config. Current Forge supports Argon on pinned LiteLLM 1.102 by sending native `thinkingConfig` with the
selected thinking level; no LiteLLM upgrade is required. Update Forge as well as the saved deployment metadata when
adopting Argon, so requests avoid the adapter's generic reasoning conversion to an unsupported `thinkingBudget`.

- **Local Google AI:** copy the complete bundled `gemini/gemini-4-argon` deployment into the saved backend config,
  including `model_info`. It uses `GEMINI_API_KEY` and `prompt_cache_min_tokens: 4096`.
- **Remote Vertex:** the server operator must configure a Vertex deployment. Set both `model_name` and
  `litellm_params.model` to `vertex_ai/gemini-4-argon`. Replace the bundled Google AI `api_key` with the server's Vertex
  authentication (ADC or `vertex_credentials`) and configure `vertex_project` and `vertex_location`. Retain the complete
  capability and pricing metadata, changing `model_info.base_model` to `vertex_ai/gemini-4-argon` and
  `prompt_cache_min_tokens` to `6144`. The 65,536 output limit describes streaming; unary requests are limited to
  32,768. Forge's gateway connection still uses `LITELLM_BASE_URL` and `LITELLM_API_KEY`; Vertex credentials belong on
  the server. See [LiteLLM's Vertex configuration](https://docs.litellm.ai/docs/providers/vertex) and Google's
  [Vertex caching limits](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-argon).

Argon workflow requests select the model explicitly: an existing OpenRouter proxy can forward them without changing tier
defaults, and a saved LiteLLM proxy can keep its older tiers once its restarted backend serves Argon. A backend snapshot
without Argon fails workflow preflight with migration guidance instead of falling back to an older Pro model. See
[workflow readiness](workflow.md#quick-start) for `forge workflow list-models --available --json` and the limits of its
deployment check.

#### Gemini 3.8 Flash

Gemini 3.8 Flash is the current Gemini Flash default across OpenRouter and LiteLLM. It is a GA model with a
1,048,576-token input limit, 65,536-token output limit, and `low`/`medium`/`high` thinking levels (`medium` by default).
Google documents sampling parameters as deprecated and ignored, so Forge does not advertise sampling overrides. Gemini
2.5, 3.5, 3.6, and 3.7 Flash remain selectable through the OpenRouter Flash template. See Google's
[3.8 announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/),
[3.8 model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash),
[Gemini API release notes](https://ai.google.dev/gemini-api/docs/changelog).

The tier-1 cascade checker also defaults to Gemini 3.8 Flash through OpenRouter, local LiteLLM as
`gemini/gemini-3.8-flash`, and remote LiteLLM as `vertex_ai/gemini-3.8-flash` (see [policy.md](policy.md)).

#### Claude Sonnet and Opus 5.5

The Anthropic templates use Opus 5.5 as their opus-tier default. The unversioned `opus` and `claude-opus` aliases also
select 5.5; explicit `claude-opus-5` pins retain Opus 5. Opus 5.5 uses always-on adaptive thinking with a model default
of `medium` effort. Custom integrations must use `auto` or `none` tool choice: forced tool choices and disabling
thinking are rejected. See Anthropic's
[migration guide](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide).

To adopt Sonnet 5.5, follow the
[saved-configuration upgrade procedure](proxy.md#updating-saved-proxy-and-backend-configurations) and set the translated
proxy's Sonnet tier to `anthropic/claude-sonnet-5.5` for OpenRouter or `anthropic/claude-sonnet-5-5` for LiteLLM. Add
`claude-sonnet-5: anthropic/claude-sonnet-5` under `model_alternatives.sonnet` to keep the prior version selectable;
older snapshots do not have this alternative. Passthrough uses the client's model, so select `--model claude-sonnet-5`
to keep Sonnet 5. A saved LiteLLM backend must also expose the new native route and its pricing/effort metadata.

Sonnet 5.5 rejects manual thinking budgets and sampling overrides. For native Messages requests, use adaptive thinking
or `thinking: {type: between_tools}` to turn off up-front thinking. `between_tools` accepts no extra fields and works
only at `low`, `medium`, or `high` effort; it cannot change effort mid-conversation. A passthrough override floor of
`xhigh` or `max` returns HTTP 400 before mutation or forwarding: use adaptive thinking or lower the floor. Use `auto` or
`none` tool choice; translated Sonnet/Opus 5.5 routes reject forced choices with HTTP 400. Preserve signed thinking
blocks with append-only history. Forge's passthrough preserves those native controls; translated routes map
`between_tools` to their lowest supported reasoning effort. See the
[Sonnet 5.5 migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide).

#### Claude alternatives and Fable retention

The bundled `openrouter-anthropic` template exposes these alternatives alongside its Sonnet/Opus 5.5 defaults:

```yaml
model_alternatives:
  opus:
    claude-fable-5-1: anthropic/claude-fable-5.1
    claude-fable-5: anthropic/claude-fable-5
    claude-opus-5: anthropic/claude-opus-5
    claude-opus-4-8: anthropic/claude-opus-4.8
    claude-opus-4-6: anthropic/claude-opus-4.6
  sonnet:
    claude-sonnet-5: anthropic/claude-sonnet-5
    claude-sonnet-4-6: anthropic/claude-sonnet-4.6
```

OpenRouter slugs use dotted versions (`anthropic/claude-opus-5.5`); native Anthropic uses hyphens (`claude-opus-5-5`),
prefixed with `anthropic/` on LiteLLM routes. Use the
[saved-configuration upgrade procedure](proxy.md#updating-saved-proxy-and-backend-configurations) to add these mappings
to an existing proxy.

`--model claude-fable` and `--model fable` select Fable 5.1, the current family default. Use `--model claude-fable-5` to
retain the prior version explicitly:

```bash
forge session start fable-review --proxy openrouter-anthropic --model claude-fable
```

On OpenRouter routes, Forge uses its required-ZDR fallback for both Fable versions by default. Check the
[ZDR policy](proxy.md#openrouter-zero-data-retention-zdr) for dated endpoint evidence, the effective model and the
explicit opt-out needed to use Fable itself.

An existing proxy is a user-owned snapshot. If it predates the 5.1 alternative, `--model fable` fails and names that
proxy instead of silently changing to direct Anthropic. Update or recreate the proxy, select a compatible proxy with
`--proxy`, or explicitly cross the boundary with `--no-proxy`.

Anthropic's direct API requires 30-day retention for Fable 5 and 5.1 unless Anthropic expressly authorizes ZDR. The 5.1
[migration contract](https://platform.claude.com/docs/en/models/fable-5-1/migration-guide) accepts only `auto` or `none`
tool choice, and an older Claude model drops Fable 5.1 thinking blocks it cannot read and replans after a route switch.
Use a fresh transfer (`forge session resume <name> --fresh --model <older-model>`) when you want that switch to start
from an explicit summary boundary rather than native history.

#### OpenRouter family alternatives

The Kimi template keeps K3 as its default and exposes the coding-specialized `kimi-k2.7-code` as an explicit Sonnet/Opus
model alternative.

The existing OpenRouter family templates also expose these explicit alternatives without changing their tier defaults:

| Template              | New alternatives                                                          |
| --------------------- | ------------------------------------------------------------------------- |
| `openrouter-deepseek` | `deepseek-v4.1-flash-1017`, `deepseek-v4.1-flash`, `deepseek-v4-pro-0813` |
| `openrouter-kimi`     | `kimi-k3.1-pro`                                                           |
| `openrouter-minimax`  | `minimax-m3.1-flash`                                                      |
| `openrouter-qwen`     | `qwen3.8-flash`, `qwen3.8-max-0902`                                       |
| `openrouter-glm`      | `glm-5.3-flash`, `glm-5.3-flashx`                                         |

The dated Qwen Max entry preserves the explicit snapshot identity; `qwen3.8-max` remains separately selectable.

Kimi K3.1 Pro, MiniMax M3.1 Flash, and DeepSeek V4.1 Flash 1017 support image input and a 1,048,576-token context
through OpenRouter. Kimi uses `low`, `high`, or `max` reasoning and filters temperature, top-p, and top-k. Use `auto` or
`none` tool choice for this route; Forge conservatively rejects forced choices because the endpoint does not support
forcing a named tool. MiniMax M3.1 Flash adds `low`, `medium`, `high`, `xhigh`, and `max` effort controls; MiniMax M3
retains its existing behavior. DeepSeek's dated snapshot has its own identity and supports `low`, `high`, and `max`
effort.

```bash
forge proxy create openrouter-kimi
forge session start kimi-review --proxy openrouter-kimi --model kimi-k3.1-pro
forge workflow panel -p "Review the current diff" --context blind \
  -m kimi-k3.1-pro,minimax-m3.1-flash,deepseek-v4.1-flash-1017
```

These routes use Forge's [translated history contract](proxy.md#translated-response-limits-and-history), which differs
from Kimi's native recommendation to preserve reasoning history. The alternatives do not change family defaults. See
[workflow.md](workflow.md#quick-start) for the authoritative worker inventory and default quorum. For existing proxy
snapshots, apply the desired `model_alternatives` entries using the
[saved-configuration upgrade procedure](proxy.md#updating-saved-proxy-and-backend-configurations).

Qwen3.8 27B is now both the Haiku and Sonnet default because it was the least-expensive multimodal Qwen with a ZDR
endpoint in the audit. The configured Max and explicit Flash/Max 0902 selections require fallback routes under Forge's
default OpenRouter data policy. See [OpenRouter ZDR](proxy.md#openrouter-zero-data-retention-zdr) for dated audits,
effective model IDs, image limitations and the explicit opt-out.

---

## Reference

| Role                  | CLI entry point                                     | Implementation                                               |
| --------------------- | --------------------------------------------------- | ------------------------------------------------------------ |
| Executor              | `forge session start [--proxy <id>] [--model <m>]`  | `src/forge/session/manager.py`, `src/forge/cli/session.py`   |
| Supervisor            | `forge policy supervisor set <target>`              | `src/forge/policy/semantic/supervisor.py`                    |
| `/review` / `$review` | `src/skills/review/content.md` + `forge-skill.yaml` | `src/forge/core/ops/session_context.py` for family detection |
| `/panel` / `$panel`   | `forge workflow panel ...`                          | `src/forge/review/engine.py`, `src/forge/review/models.py`   |
| `/debate` / `$debate` | `forge workflow debate ...`                         | `src/forge/review/engine.py` (adversarial runner)            |
| Memory writer         | Stop enqueues; a later CLI drain launches it        | `src/forge/session/memory_writer.py`                         |

Use `forge model catalog` to inspect Forge's static model capability catalog. Use `forge workflow list-models` when you
need runtime readiness for workflow workers, including the cached preflight state of the opt-in `codex` worker. The
catalog reports intrinsic capabilities and explicit defaults; Forge does not assign comparative intelligence scores.

See the [workflow guide](workflow.md#quick-start) for panel/debate worker choices and readiness. To add alternatives or
change tier defaults, follow the
[proxy configuration procedure](proxy.md#updating-saved-proxy-and-backend-configurations).
