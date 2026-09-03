# Forge Proxies — Routing Configuration

**Proxies are where you configure model routing and LLM defaults.**

To use different models, change reasoning effort, or switch providers: create or customize a proxy.

- Canonical architecture: [`docs/design.md`](../design.md)
- Configuration overview: [`config.md`](config.md)
- Sessions (workflow settings): [`session.md`](session.md)

---

## Why proxies exist

Claude Code doesn't send session IDs downstream. The proxy identifies requests by which port they hit. Therefore:

- **Proxy = base_url/port = routing configuration**
- Different routing needs → different proxy
- Sessions reference proxies but cannot modify them

### Consequence (normative)

- **LLM routing + default hyperparameters are proxy-owned.**
- **Sessions cannot override proxy-owned routing/hyperparams.**

If you want different model mappings or thinking defaults: use a different proxy.

### API model capabilities

Provider CLIs sometimes limit the models they serve. For example, OpenAI's Codex CLI caps GPT-5.5 at 400K tokens as a
serving-budget decision, even though the model supports 1,050,000 tokens via the API. Forge proxies route through the
API directly, so a proxy can use API context windows and reasoning effort levels that a product CLI may not expose.

It can also route to API models that product CLIs don't expose at all -- like `gpt-5.5-pro` (1M context) -- or to
different providers within a single workflow (GPT for planning, Claude for execution).

The tradeoff is cost: you pay API rates instead of bundled subscription pricing. Use Forge
[spend caps](#cost-tracking-and-spend-caps) when you want warn/reject limits on that spend.

### System prompt addendums

When routing to non-Anthropic models, Forge automatically injects a tool-discipline addendum into the system prompt at
session launch. Non-Anthropic models tend to hallucinate optional tool parameters (e.g., `"pages": ""` on Read calls)
and reach for Bash as a workaround for tool errors. The addendum teaches them to use minimal valid parameters and prefer
dedicated tools. No configuration needed.

Note: addendums are injected by the session launcher (`--append-system-prompt-file`), not by the proxy itself. Direct
HTTP use of the proxy does not include them.

### No-proxy mode

When using Claude Code directly (without Forge proxy), proxies are not used. Sessions still function for workflow
settings (worktrees, artifacts, policies, etc.), and `--model` may select a direct Claude model. Proxy tier mappings and
hyperparameter defaults apply only when a proxy route is selected.

---

## Proxy templates

Forge provides ready-to-use built-in proxy templates:

| Template                     | Use case                                        |
| ---------------------------- | ----------------------------------------------- |
| `openrouter-anthropic`       | Claude models via OpenRouter (direct)           |
| `openrouter-deepseek`        | DeepSeek models via OpenRouter (direct)         |
| `openrouter-glm`             | GLM / Z.ai models via OpenRouter (direct)       |
| `openrouter-kimi`            | Kimi models via OpenRouter (direct)             |
| `openrouter-minimax`         | MiniMax models via OpenRouter (direct)          |
| `openrouter-openai`          | GPT models via OpenRouter (direct)              |
| `openrouter-qwen`            | Qwen models via OpenRouter (direct)             |
| `openrouter-gemini`          | Gemini models via OpenRouter (direct)           |
| `openrouter-openai-codex`    | OpenAI Codex models via OpenRouter (direct)     |
| `openrouter-gemini-flash`    | Gemini Flash via OpenRouter (cheap, direct)     |
| `litellm-anthropic`          | Anthropic models via remote/shared LiteLLM      |
| `litellm-anthropic-local`    | Local LiteLLM + Anthropic API key               |
| `litellm-openai`             | OpenAI models via remote/shared LiteLLM         |
| `litellm-gemini`             | Gemini models via remote/shared LiteLLM         |
| `litellm-openai-local`       | Local LiteLLM + OpenAI API key                  |
| `litellm-openai-codex-local` | Local LiteLLM + OpenAI Codex models             |
| `anthropic-passthrough`      | Raw Anthropic passthrough; inspect enabled      |
| `codex-responses-local`      | Sessionless Codex TUI via Responses passthrough |
| `litellm-gemini-local`       | Local LiteLLM + Gemini API key                  |
| `litellm-gemini-flash-local` | Local LiteLLM + Gemini Flash (fast/cheap)       |

The table lists all twenty user-facing templates. `litellm-gemini-test` also exists internally, but it is hidden from
normal end-user template lists.

Built-in templates declare `proxy.backend`, the config field that names the backend owning endpoint and credential
requirements. If you customize a template under `~/.forge/templates/<name>.yaml`, keep `proxy.backend` set to an
existing backend such as `openrouter`, `litellm-remote`, or `litellm-gemini-local`; Forge derives local backend
auto-start and remote upstream URLs from that backend at proxy creation time.

If you edit a copied `proxy.yaml` directly, `backend` must start with a lowercase letter or digit and may contain only
lowercase letters, digits, `.`, `_`, or `-`. Forge reports a malformed value as an invalid `proxy.backend` before a
managed session launches; it does not silently reinterpret spellings such as `OpenRouter`.

OpenRouter templates default to `https://openrouter.ai/api/v1`. Set `OPENROUTER_BASE_URL` only when you intentionally
route OpenRouter-compatible traffic through a different endpoint; new proxies created from OpenRouter templates will
copy that resolved upstream URL into `proxy.yaml`.

Use `forge model backend list` to inspect built-in backends, required credentials, and any matching local LiteLLM
managed process. Use `forge model backend test-auth <backend>` when you want Forge to resolve the backend's credentials
and probe the upstream endpoint without printing secret values. Remote backends such as `openrouter` and
`litellm-remote` are built in and have no local start/stop lifecycle; local LiteLLM backends can be started by backend
name or by the `litellm --port <port>` adapter form. Stop live local backend processes by the managed process id shown
in `forge model backend list` (for example, `forge model backend stop litellm-4000`), or flush every registered managed
process with `forge model backend stop --all`. Forge signals the complete detached LiteLLM process group. If the group
cannot be signalled, stop exits nonzero and retains its managed-process row so the ownership and retry target are not
lost. `forge model backend delete litellm` also retains the adapter config, omits `Deleted`, and exits nonzero when any
required process stop fails. If a newly started LiteLLM process never becomes healthy, Forge kills its complete detached
group so a spawned worker cannot remain on the port.

The local LiteLLM backends (`litellm-gemini-local`, `litellm-openai-local`, `litellm-anthropic-local`, and
`codex-responses-local`) all share one adapter and port (`litellm` on `4000`), so a single LiteLLM process backs every
local backend whose credential it is configured for. The default config serves Gemini and OpenAI models from one
`litellm-4000` process, so `forge model backend list` shows that managed process under each matching backend and marks
it `(shared)`; starting a second matching backend reuses the running process rather than launching a new one. This is
expected -- there is one local LiteLLM process, not one per backend.

### Picking up GPT-5.6 Sol defaults after an upgrade

New proxies created from the current built-in OpenAI templates use GPT-5.6 Sol as follows:

| Template                     | GPT-5.6 Sol tiers |
| ---------------------------- | ----------------- |
| `openrouter-openai`          | sonnet, opus      |
| `litellm-openai`             | sonnet, opus      |
| `litellm-openai-local`       | sonnet, opus      |
| `openrouter-openai-codex`    | opus              |
| `litellm-openai-codex-local` | opus              |
| `codex-responses-local`      | sonnet, opus      |

An existing `proxy.yaml` is a user-owned snapshot, so upgrading Forge does not rewrite its tiers. Either edit the
affected tiers to `openai/gpt-5.6-sol` with `forge proxy edit <proxy_id>`, or create a fresh proxy from the built-in
template with `forge proxy create <template> --name <new_proxy_id>`. Then restart the affected proxy and verify real
upstream access:

```bash
forge proxy stop <proxy_id>
forge proxy start <proxy_id> --smoke-test
```

Local LiteLLM adapter configuration is also user-owned. For `litellm-openai-local`, `litellm-openai-codex-local`, or
`codex-responses-local`, add the GPT-5.6 routes to `~/.forge/backends/litellm/config.yaml`; alternatively, back up
customizations and recreate the adapter config from the current built-in default:

```bash
forge model backend list
forge model backend stop <runtime-id> # for example, litellm-4000
cp ~/.forge/backends/litellm/config.yaml ~/.forge/backends/litellm/config.yaml.bak
forge model backend delete litellm
forge model backend create litellm
forge model backend start litellm --port 4000
```

After updating the local adapter, restart each affected proxy with `--smoke-test`. Custom templates under
`~/.forge/templates/` are also preserved and must be updated explicitly.

### Picking up current model defaults and alternatives after an upgrade

New proxies created from the current built-in templates use these defaults:

| Template                                            | New default tiers                                |
| --------------------------------------------------- | ------------------------------------------------ |
| `openrouter-anthropic`, `litellm-anthropic(-local)` | opus -> Claude Opus 5                            |
| `anthropic-passthrough`                             | opus -> Claude Opus 5 (informational)            |
| `openrouter-kimi`                                   | sonnet/opus -> Kimi K3                           |
| `openrouter-qwen`                                   | haiku/sonnet -> Qwen3.8 27B, opus -> Qwen3.8 Max |
| `openrouter-glm`                                    | sonnet/opus -> GLM 5.3                           |
| `openrouter-gemini-flash`                           | all tiers -> Gemini 3.8 Flash                    |
| `openrouter-gemini`                                 | haiku -> Gemini 3.8 Flash                        |
| `litellm-gemini`, `litellm-gemini-local`            | haiku -> Gemini 3.7 Flash                        |
| `litellm-gemini-flash-local`                        | all tiers -> Gemini 3.7 Flash                    |

Gemini 3.8 Flash is the current Gemini Flash family and OpenRouter default. It is a GA model with a 1,048,576-token
input limit, 65,536-token output limit, and `low`/`medium`/`high` thinking levels (`medium` by default). Google
documents sampling parameters as deprecated and ignored, so Forge does not advertise sampling overrides. Gemini 2.5,
3.5, 3.6, and 3.7 Flash remain selectable through the OpenRouter Flash template. Gemini 3.7 also stays the local and
remote LiteLLM default: LiteLLM 1.99's bundled model catalog has no 3.8 pricing/capability entry. See Google's
[3.8 announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/),
[3.8 model reference](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash),
[3.7 migration guidance](https://ai.google.dev/gemini-api/docs/latest-model), and
[Gemini API release notes](https://ai.google.dev/gemini-api/docs/changelog).

The tier-1 cascade checker therefore defaults to Gemini 3.8 Flash through OpenRouter and Gemini 3.7 Flash through local
LiteLLM as `gemini/gemini-3.7-flash` or remote LiteLLM as `vertex_ai/gemini-3.7-flash` (see [policy.md](policy.md)). The
Kimi template keeps K3 as its default and exposes the coding-specialized `kimi-k2.7-code` as an explicit Sonnet/Opus
model alternative.

The Anthropic templates retain Opus 5 as their opus-tier default and now expose both Fable 5.1 and Fable 5 as explicit
alternatives. The unversioned `fable` and `claude-fable` aliases select Fable 5.1; use `claude-fable-5` when you need
the prior version.

Qwen3.8 27B is now both the Haiku and Sonnet default because it was the least-expensive multimodal Qwen with a ZDR
endpoint in the audit. Qwen3.8 Max is the configured Opus model, but the default OpenRouter data policy resolves it to
`qwen/qwen3.8-2.4t-a95b`: OpenRouter's ZDR endpoint catalog had no compatible Max endpoint in the 2026-08-21 audit. See
[OpenRouter ZDR](#openrouter-zero-data-retention-zdr) for the effective route and explicit opt-out.

Existing `proxy.yaml` files and the local LiteLLM adapter config are user-owned snapshots; upgrading Forge does not
rewrite them. Follow the same remediation as the GPT-5.6 section above: edit the affected tiers with
`forge proxy edit <proxy_id>` or recreate the proxy from the template, then restart with `--smoke-test`. For the local
LiteLLM path, the required Gemini 3.7 Flash and Anthropic Fable 5.1 routes must exist in
`~/.forge/backends/litellm/config.yaml` — update the materialized config or delete/recreate it, then restart the
backend; restarting alone re-reads the old copy. A stale Anthropic proxy that does not expose Fable 5.1 fails explicitly
on `--model fable`; it is never replaced implicitly.

---

## Core commands (cheat sheet)

```bash
# Templates
forge proxy template list        # List available templates
forge proxy template show <name> # Show template configuration
forge proxy template edit <name> # Customize a template (copy-on-first-edit)
forge proxy template reset <name># Reset to built-in default

# Create / start
forge proxy create <template> [--name <id>] [--no-start] [--smoke-test] [--json]
forge proxy start <proxy_id> [--smoke-test]
forge proxy stop <proxy_id> [--force] [--kill-adopted]

# Show / list
forge proxy show <proxy_id>      # Full proxy configuration
forge proxy list                 # All proxies with status

# Modify
forge proxy edit <proxy_id>      # Open in $EDITOR
forge proxy set <proxy_id> <key>=<value>

# Delete
forge proxy delete <proxy_id>... [--yes] [--kill-adopted] [--no-kill]

# Metrics
forge proxy metrics [proxy_id]   # Runtime metrics (tokens, latency, failures); aggregates all when >1
forge proxy metrics --json       # Raw JSON output

# Maintenance
forge proxy validate <proxy_id>  # Validate config
```

Stale proxies (dead PIDs) are pruned automatically by `forge proxy list`, `create`, and `start`; `forge clean` removes
them globally.

**Ownership is retained on stop failure.** `stop` exits non-zero and leaves the registry row/config available when
termination is refused or fails. `delete` removes the last live owner only after its required stop succeeds, so
rerunning the command remains possible and failure never prints `Deleted`. Deleting a shared-port alias,
default-detaching an adopted process, or using `--no-kill` intentionally leaves the process alive and succeeds.
Multi-delete continues other targets, then exits non-zero if any required stop failed.

**Ownership is also retained on start failure.** A failed `forge proxy start <proxy_id>` restores the proxy's prior
registry row, or records a config-only proxy as `stopped`, so it remains visible to `proxy list` and can be retried.

**Auto-start from a template.** `--proxy` (on `forge session start/resume/fork` and `forge claude start`) and
`--supervisor-proxy` (on `forge session start/fork` and `forge policy supervisor set`) accept a **template name** as
well as a running proxy id. If no proxy is running for that name, Forge starts one from the matching template -- no
separate `forge proxy create` needed -- and prints the proxy it started (stop it later with
`forge proxy stop <proxy_id>`). A name that matches neither a running proxy nor a template fails with a hint to run
`forge proxy template list`.

An explicit non-Claude `forge session start|resume|fork|incognito --model <catalog-id>` can also select and start the
first admissible packaged-catalog proxy. This is an explicit paid-routing boundary: Forge prints the resolved route
before child launch, does not scan unrelated running proxies to reorder candidates, and does not fall through after a
selected proxy fails. `--no-launch` may still start the proxy; session or incognito cleanup does not stop it.

---

## OpenRouter (direct, no LiteLLM)

OpenRouter templates (`openrouter-anthropic`, `openrouter-deepseek`, `openrouter-glm`, `openrouter-kimi`,
`openrouter-minimax`, `openrouter-openai`, `openrouter-qwen`, `openrouter-gemini`, `openrouter-openai-codex`,
`openrouter-gemini-flash`) call the OpenRouter API directly -- no LiteLLM subprocess needed.

```bash
# Store your key
forge auth login -c openrouter

# Create and start (pick a model family)
forge proxy create openrouter-anthropic

# Launch Claude Code through OpenRouter
forge claude start --proxy <proxy_id>
```

Default tiers use Anthropic Claude models on OpenRouter. Edit the proxy to use any OpenRouter model:

```bash
forge proxy edit <proxy_id>
# Change tiers to e.g.:
#   haiku: google/gemini-3.8-flash
#   sonnet: anthropic/claude-sonnet-4.6
#   opus: openai/gpt-5.5
```

Models not in Forge's catalog (e.g., `meta-llama/llama-3.1-70b`) work -- the proxy uses safe defaults for
`max_output_tokens` and `context_window` when catalog data is unavailable.

### OpenRouter zero data retention (ZDR)

Direct OpenRouter proxies require ZDR by default. With `allow_non_zdr: false` (also the compatibility default when the
key is absent), Forge sends `provider.zdr: true` on every request. OpenRouter then restricts routing to endpoints it
currently marks ZDR-compatible. This request policy is the enforcement boundary; Forge's small `zdr_fallbacks` map only
replaces models already known to lack a compatible endpoint before dispatch.

Forge audited the bundled OpenRouter defaults and alternatives against OpenRouter's
[ZDR endpoint catalog](https://openrouter.ai/api/v1/endpoints/zdr) on 2026-08-21, then checked the newly added Fable 5.1
slug on 2026-09-02 and confirmed the new `google/gemini-3.8-flash` route on 2026-09-03. Gemini 3.8 Flash had an eligible
endpoint; the original seven exceptions plus Fable 5.1 did not and use these required-ZDR fallbacks:

```yaml
allow_non_zdr: false
zdr_fallbacks:
  anthropic/claude-fable-5.1: anthropic/claude-opus-5
  anthropic/claude-fable-5: anthropic/claude-opus-5
  qwen/qwen3.6-flash: qwen/qwen3.8-27b
  qwen/qwen3.6-plus: qwen/qwen3.8-27b
  qwen/qwen3.6-max-preview: qwen/qwen3.8-2.4t-a95b
  qwen/qwen3.7-plus: qwen/qwen3.8-27b
  qwen/qwen3.7-max: qwen/qwen3.8-2.4t-a95b
  qwen/qwen3.8-max: qwen/qwen3.8-2.4t-a95b
```

These built-in rules also protect older proxy snapshots that predate the keys; values in a proxy's own `zdr_fallbacks`
replace them. `GET /` reports the user-owned selection under `runtime.configured_tier_mappings`, the model Forge will
actually dispatch under `runtime.tier_mappings`, and the active rule under `runtime.data_policy`. Unknown models are not
guessed: Forge still sends `provider.zdr: true`, so OpenRouter rejects the request if it has no eligible endpoint.

Fallback values are exact OpenRouter backend slugs. Forge strips Claude Code's `[1m]` lookup hint from the configured
source before matching and never appends that client-side hint to the fallback target.

The 2.4T A95B fallback preserves the flagship text/code posture but is text-only. If Opus must accept images, replace
the mapping target with the ZDR-compatible multimodal `qwen/qwen3.8-27b`; that trades capability for modality and lower
cost.

To make a direct OpenRouter proxy eligible for non-ZDR endpoints, opt in explicitly and restart it:

```bash
forge proxy set <proxy_id> allow_non_zdr=true
forge proxy stop <proxy_id>
forge proxy start <proxy_id> --smoke-test
```

This removes Forge's request-level ZDR requirement and bypasses its ZDR fallback. It cannot weaken ZDR enabled in your
OpenRouter account or guardrail: OpenRouter combines those policies, so you must disable the account-side requirement
too if you intend to use a non-ZDR-only model. See OpenRouter's
[ZDR guide](https://openrouter.ai/docs/guides/features/zdr) and
[provider-routing reference](https://openrouter.ai/docs/guides/routing/provider-selection).

The per-proxy opt-out and fallback contract applies only to direct OpenRouter proxies. Separately, Forge-owned direct
OpenRouter plan checks and transfer/rewind transcript curation always send `provider.zdr: true`; a proxy's
`allow_non_zdr` setting cannot weaken those calls. Forge neither discovers nor claims ZDR support for LiteLLM routes,
does not send OpenRouter ZDR fields through LiteLLM, and rejects `allow_non_zdr` or `zdr_fallbacks` keys in a LiteLLM
`proxy.yaml`.

---

## Model alternatives

Anthropic proxy templates (`openrouter-anthropic`, `litellm-anthropic`, `litellm-anthropic-local`) configure user-facing
`model_alternatives` to support multiple Claude model versions at the same tier. Their opus tier defaults to Opus 5 and
their sonnet tier to Sonnet 5, with Fable 5.1, Fable 5, Opus 4.8, Opus 4.6, and Sonnet 4.6 as alternatives.
(`anthropic-passthrough` forwards the client's model unchanged, so `--model` selects any Claude model directly with no
alternatives map.) Use `--model` to select an alternative:

```bash
# Default: opus tier routes to Opus 5, sonnet tier to Sonnet 5
forge session start my-session --proxy openrouter-anthropic

# Select the current Fable family model
forge session start my-session --proxy openrouter-anthropic --model claude-fable
```

The proxy resolves the alternative at request time -- Claude Code sends the model name, the proxy looks up
`model_alternatives[tier][model]` and routes to the configured backend model. Tier-level hyperparameters
(reasoning_effort, etc.) still apply regardless of which alternative is selected. Under required ZDR, Fable 5.1 and
Fable 5 resolve to Opus 5 because the dated endpoint checks found no Fable-compatible ZDR route.

For Claude models, `forge session --model` still uses a compatible proxy's tier defaults and `model_alternatives`
exactly as before. The same flag now accepts any Forge catalog model: non-Claude requests resolve a compatible
source/template from the packaged route catalog, then select a serving proxy tier. Use `--model-tier haiku|sonnet|opus`
only when tier selection is ambiguous; proxy-owned tier mappings and hyperparameters are not mutated.

To add or edit alternatives, use `forge proxy edit <proxy_id>`:

```yaml
model_alternatives:
  opus:
    claude-fable-5-1: anthropic/claude-fable-5.1
    claude-fable-5: anthropic/claude-fable-5
    claude-opus-4-8: anthropic/claude-opus-4.8
    claude-opus-4-6: anthropic/claude-opus-4.6
  sonnet:
    claude-sonnet-4-6: anthropic/claude-sonnet-4.6
```

The OpenRouter backend slug uses dotted `5.1`; the direct Anthropic and LiteLLM model ID is `claude-fable-5-1` (with the
usual `anthropic/` LiteLLM prefix). Fresh proxies receive the correct provider-specific mapping from their template.
Existing user-owned proxy snapshots must be edited or recreated to gain the new alternative.

For per-role guidance on when to pin an opus alternative (e.g. `--model claude-fable`) vs leave the default Opus 5
mapping in place — including the supervisor-vs-executor split, the structural reasons MRCR varies across model versions,
and per-family cost + multi-needle retrieval data — see [model_selection.md](model_selection.md).

---

## Proxy lifecycle

### List available proxies

```bash
forge proxy list
```

Shows:

- proxy id
- template
- base_url / port
- status/health
- pid (if Forge spawned it)

### Create a proxy

`create` ensures the proxy is running (reuse/adopt/spawn as needed):

- Creates the proxy config if it doesn't exist
- Starts the proxy if it's not running
- Returns the base_url

```bash
# Create from template (reuse/adopt/spawn as needed)
forge proxy create openrouter-openai
# → Proxy created at http://localhost:8096

# Create with per-tier overrides
forge proxy create openrouter-openai \
  --opus-reasoning high

# Create with custom name
forge proxy create openrouter-openai --name my-high-reasoning

# Create config only (don't start the server)
forge proxy create openrouter-openai --no-start

# Start and verify upstream connectivity (sends a real request)
forge proxy start openrouter-openai --smoke-test

# Create/start and return one scriptable creation + verification result
forge proxy create openrouter-openai --json --smoke-test
```

**Semantics (reuse/adopt/spawn):**

- Reuses an existing healthy proxy for that template if present
- Adopts an orphan proxy at the expected default port if found
- Spawns a new proxy if neither exists
- Blocks until the proxy is healthy (with timeout)
- Records in `~/.forge/proxies/index.json`

Use `--smoke-test` after first setup or credential changes to verify the proxy can reach its upstream LLM provider.
Without it, health checks only confirm the local proxy process is alive.

On the normal create/start path, `--json --smoke-test` prints one JSON object: the usual creation fields plus
`smoke_test.passed` and `smoke_test.detail`. A failed probe exits non-zero but leaves the successfully created, reused,
or adopted proxy available for inspection and retry. `--no-start` remains config-only and does not run the probe.

If a credential change leaves a local LiteLLM backend in a suspect state, run `forge model backend stop --all` (or
`forge model backend stop --all --yes` in automation) before restarting proxies. This clears managed local backend
processes and registry rows without deleting adapter config files.

### Start Claude with a proxy

```bash
forge claude start --proxy <proxy_id>
```

What this does:

- Resolves `<proxy_id>` in `~/.forge/proxies/index.json`
- Healthchecks the proxy (`GET /`) and verifies proxy identity
- Launches `claude` with `ANTHROPIC_BASE_URL=<proxy.base_url>`
- Sets `CLAUDE_CODE_ATTRIBUTION_HEADER=0` only for translated/third-party proxy routes, preserving prompt caching
  without leaking the setting into direct Anthropic or `anthropic_passthrough` launches
- Sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` based on proxy's model context window

On translated LiteLLM and OpenRouter routes, Forge also preserves Claude Code's inbound User-Agent for the upstream
gateway. The forwarded value has control characters removed and is capped at 256 characters. This is not general header
passthrough: credentials, cookies, and Forge correlation headers are not relayed by this mechanism, and native Anthropic
or Responses passthrough routes keep their own explicit header policies.

### Start Codex with a Responses-capable proxy

```bash
forge codex status
forge codex start --proxy codex-responses-local
forge codex start --proxy <proxy_id> --sandbox read-only -- -m gpt-5.5
```

`forge codex start --proxy` is the Codex equivalent of a bare proxy launch: it opens the foreground Codex TUI through a
Forge proxy but creates no Forge session, manifest, artifacts, or `.forge/` requirement. It is intentionally different
from `forge session start --runtime codex`, which records a managed Codex thread.

The proxy must advertise `wire_shape: openai_responses_passthrough` and `capabilities.responses_ingress: true` from
`GET /`. The built-in `codex-responses-local` template provides that shape by forwarding Codex's raw `/v1/responses*`
traffic to a local LiteLLM backend, preserving reasoning items byte-for-byte. It uses the `openai-api` credential
(`OPENAI_API_KEY`) for the upstream LiteLLM/OpenAI leg; the Codex child itself does not need native OpenAI or Codex
login for this proxy-backed launch.

Forge passes Codex temporary argv `-c` provider overrides, never writes Codex's `config.toml`, and scrubs inherited
Codex/OpenAI auth, session, proxy, and run-tree env vars before starting the child. Extra Codex args go after `--`; a
user-supplied `-m`/`--model` overrides the proxy default model.

### Delete a proxy

```bash
forge proxy delete <proxy_id>
```

Stops the proxy and then removes its registry entry and overlay. If a required stop is refused or fails, the command
exits non-zero and preserves both ownership records; it does not print `Deleted`. Deleting one of several live same-port
aliases keeps the shared process running. Use `--no-kill` for an explicit detach, or `--kill-adopted` only when Forge
may terminate an adopted process after verifying its identity.

### Other commands

```bash
# Validate a proxy config file
forge proxy validate <proxy_id>
```

Stale proxy entries (dead processes) are pruned automatically by `forge proxy list`, `create`, and `start`;
`forge clean` removes them globally.

---

## Customizing proxies

### At creation time

Specify per-tier overrides when creating a proxy:

```bash
forge proxy create openrouter-openai \
  --opus-reasoning high \
  --sonnet-reasoning medium \
  --sonnet-temperature 0.7
```

These overrides are saved to the proxy file (`~/.forge/proxies/<proxy_id>/proxy.yaml`).

### Edit an existing proxy

After creating a proxy, customize it further:

```bash
# Edit the proxy file in $EDITOR
forge proxy edit <proxy_id>

# Or set individual values
forge proxy set <proxy_id> tier_overrides.opus.reasoning_effort=high

# View full configuration
forge proxy show <proxy_id>

# Validate the config
forge proxy validate <proxy_id>
```

### Proxy file format (user edit surface)

When you create a proxy, Forge writes a complete `proxy.yaml` from the template. You own this file and can edit it
directly. The key fields you'll typically customize are `default_tier` and `tier_overrides`:

```yaml
# ~/.forge/proxies/<proxy_id>/proxy.yaml
proxy_format: 1
template: openrouter-openai
template_digest: abc123...

provider: openrouter
backend: openrouter
proxy_endpoint: http://localhost:8096
port: 8096
upstream_base_url: https://openrouter.ai/api/v1
allow_non_zdr: false
zdr_fallbacks: {}

tiers:
  haiku: openai/gpt-5.4-mini
  sonnet: openai/gpt-5.6-sol
  opus: openai/gpt-5.6-sol

default_tier: sonnet
tool_prefixes_to_ignore: []

tier_overrides:
  sonnet:
    reasoning_effort: medium
    temperature: 0.7
  opus:
    reasoning_effort: high
    thinking_budget_tokens: 16384

provider_settings: {}
prompt_caching: passthrough
auto_cache_min_tokens: 1024

costs:
  caps:
    per_day: null
    per_month: null
  on_cap_hit: reject
```

**What you'll typically edit:** `default_tier`, `tier_overrides`, and sometimes `provider_settings`. Leave
`proxy_format`, `template`, `provider`, `backend`, `proxy_endpoint`, `upstream_base_url`, `port`, and `tiers` alone
unless you know what you're doing — those are set from the template/backend catalog at creation.

Custom templates may also set `tool_prefixes_to_ignore`, `prompt_caching`, and `auto_cache_min_tokens`. Forge copies
those values into each new proxy; existing `proxy.yaml` files remain user-owned snapshots and keep compatibility
defaults when the keys are absent. `allow_non_zdr` and `zdr_fallbacks` are direct-OpenRouter-only fields. Tool-ignore
entries must be strings, `model_alternatives` and `zdr_fallbacks` must contain string-to-string mappings,
`prompt_caching` is `passthrough` or `auto_inject`, and `auto_cache_min_tokens` is an integer. Forge rejects malformed
values when loading either a template or a proxy instance.

Configuration authored by Forge 0.9.4 or earlier remains readable for one release window. Explicit occurrences of its
three inert fields warn once per process; omission is silent, and new templates or proxy files omit them. Remove
`enable_preamble` and `openai_api_mode` from custom template provider blocks, remove `provider_settings.openai_api_mode`
from existing `proxy.yaml` files, and remove `session.manifest_filename` from old Forge configuration. Backend and
`wire_shape` already select the proxy transport; session manifests always use `forge.session.json`. Their old values
never changed runtime behavior.

**Available tier_override keys:** `reasoning_effort`, `temperature`, `max_tokens`, `thinking_budget_tokens`. All are
per-tier because each model has different limits and optimal defaults.

**Precedence chain** (first non-null wins):

1. Request explicit value (e.g., `temperature` in API call)
2. Per-tier override (`tier_overrides.<tier>.*`)
3. Model catalog default (built-in per-model defaults)

**Example:** If a request includes `temperature=0.5`, it overrides the proxy's `tier_overrides.opus.temperature`.

Tier hyperparameters do not have an environment-variable override layer. Environment variables remain supported for
documented credentials and connection values, such as `OPENROUTER_API_KEY` and `LITELLM_BASE_URL`; use the proxy file
for tier defaults.

Provider, upstream URL, and template are fixed at creation. The proxy file only tunes defaults **within** that proxy's
routing scope.

---

## Proxies are shared state

⚠︎ Multiple sessions can use the same proxy. Modifying a proxy affects ALL sessions using it.

```bash
# Safe: create a separate proxy for different config
forge proxy create openrouter-openai --opus-reasoning high

# Careful: modifying an existing proxy affects everyone using it
forge proxy edit shared-proxy
```

---

## Canonical workflow: Plan -> Execute -> Panel

1. Create a **planning proxy** (`openrouter-openai`) and start Session A with that template.
2. Approve plan; stop.
3. Fork to Session B with an **execution proxy** (`forge session fork <parent> --name <session_b> --proxy <proxy_id>`).
4. Fork to Session C with a **review proxy** (`forge session fork <parent> --name <session_c> --proxy <proxy_id>`).
5. Use A and C for independent reviews; have B synthesize and fix.

Proxies make this deterministic: each session's requests hit a specific base URL, so routing defaults are stable.

---

## Proxy metrics

Each running proxy tracks in-memory metrics: request counts, token usage (input/output/cached), per-tier and per-model
breakdowns, failure rates, and latency. Metrics reset on proxy restart.

```bash
# View metrics for a specific proxy
forge proxy metrics my-proxy

# View all active proxies (the default when more than one is registered)
forge proxy metrics

# JSON output (for scripting)
forge proxy metrics --json            # {proxy_id: metrics | null} for every registered proxy
forge proxy metrics my-proxy --json   # Raw metrics object for one selected proxy
```

The bare JSON form always uses the proxy-ID mapping for zero, one, or many registrations, with `null` for an unreachable
proxy. Selecting a proxy keeps the raw metrics object. Both forms write JSON directly to stdout without terminal
wrapping or markup interpretation, so long or bracket-rich values remain valid data.

Metrics are also available via the proxy's `GET /` endpoint under the `metrics` key:

```bash
curl http://localhost:8085/ | jq .metrics
```

**What metrics track:**

- **Tokens**: input, output, cached (for cost visibility vs Codex)
- **Failed tokens**: tokens consumed by requests that failed (wasted spend)
- **Per-tier / per-model**: breakdown by routing tier and actual backend model
- **Failure types**: categorized by error type (tool_call_error, api_error, stream_error)
- **Latency**: average request duration

If a provider returns a non-streaming response that Forge cannot translate into the requested API format, the proxy
returns HTTP 500 with a stable `api_error` instead of fabricating a successful assistant response. Provider-reported
tokens and cost still count toward totals and failed-token spend, and the provider-attempt trace remains available for
diagnosis. Forge does not return provider response or exception text to the client or write it to ordinary proxy logs.
Streaming conversion failures retain their existing in-band SSE error contract.

---

## Cost tracking and spend caps

Proxy request costs are logged as downstream telemetry under `~/.forge/telemetry/downstream/`. Legacy
`~/.forge/costs/requests/` files may exist from older installs; Forge no longer reads, writes, or cleans them -- delete
them manually if present. New request spend writes to downstream records, and the by-verb view joins those records to
run ids instead of writing verb snapshot files.

If you upgrade across a backend-identity telemetry break, older downstream records are skipped rather than reattributed
under the new backend-instance contract. `forge telemetry costs show --json` reports `skipped_legacy_schema`, and the
human cost/activity views print a note when records in the selected window were fenced.

```bash
forge telemetry costs show                    # Today's costs, by verb
forge telemetry costs show --by-verb          # Explicit spelling of the default view
forge telemetry costs show --by-model         # Today's costs, by model
forge telemetry costs show --period week      # This week
forge telemetry costs show openrouter-anthropic    # Filter by proxy

forge telemetry costs reset                   # Wipe ALL cost + usage telemetry to zero (prompts; --yes to skip)
forge telemetry costs reset --dry-run         # Preview what would be removed, delete nothing
```

`--by-verb` and `--by-model` are mutually exclusive. In the verb table, `run(s)` counts unique Forge run IDs and `reqs`
counts downstream requests, so one workflow run that makes several model requests remains one run. The JSON form keeps
both `by_verb` and `by_model` summaries regardless of the selected human breakdown.

`today`, `week`, and `month` are local-calendar windows. Forge honors a process `TZ` supplied as an IANA key, an
absolute or colon-prefixed TZif path, or a POSIX rule string; invalid values fall back to `/etc/localtime`.

`forge telemetry costs reset` deletes legacy cost logs, downstream/upstream telemetry shards, spend-cap snapshots,
sidecar audit drift state, **and** the usage-attribution ledger (`forge telemetry activity`/`forge +$Y` data) under
`~/.forge/`. It also clears the derived status-line cost and supervisor-health caches so status-line segments recompute
from the now-empty telemetry instead of replaying cached values. It is irreversible (confirm prompt unless `--yes`). A
running proxy keeps its cost totals **and** cap counters in memory until restarted — so a live proxy's cumulative-cost
header, snapshot, and `forge telemetry costs show` figures do not zero until you restart it (`forge proxy stop <id>`
then `forge proxy start <id>`).

> **Per-session view:** `forge telemetry costs show` is the authoritative, **proxy-scoped** dollar view. The status-line
> `cost` segment shows the interactive Claude session's proxy-reported `~$`, scoped by subtracting the proxy total
> captured at session launch. For a **session-scoped** rollup of what Forge did — supervisor checks (including failed
> ones), tokens, and *reported-or-estimated* cost (best-effort, may be partial) — use
> [`forge telemetry activity [session]`](session.md#what-a-session-did-forge-telemetry-activity--session-end-summary).
> The views are complementary: spend is billed per proxy; activity is attributed per session; the status line is live
> and best-effort for the current interactive launch.

### Which surface answers which question?

Forge surfaces cost and usage through several views with deliberately different scopes. Pick the one that matches your
question. Forge never prices a request from a local table — a missing cost shows as `unavailable`, never invented (per
the provenance column: `forge telemetry costs show` is reported-only; `forge telemetry activity` also includes
best-effort verb-snapshot estimates):

| Surface                                | Question it answers                               | Scope                                                                   | Cost provenance                                                                 |
| -------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `forge telemetry costs show`           | "What did this proxy actually spend?"             | one proxy's request log (proxy-scoped)                                  | reported `$` or `unavailable`; **authoritative** spend view                     |
| `forge telemetry activity [session]`   | "What did Forge's automation do this session?"    | one Forge session — operation outcomes + model calls joined by run tree | reported-or-estimated `$`, best-effort attribution                              |
| status-line `cost` segment             | "What is my Claude session costing / quota left?" | one interactive launch; proxy mode subtracts the proxy launch baseline  | Claude's reported cost/quota, or proxy-reported `~$`; never recomputed by Forge |
| status-line `forge +$Y` (`forge_cost`) | "What did Forge add on top of my session?"        | one Forge session, **excluding** the main interactive harness           | reported-or-nothing (subscription/OAuth → nothing)                              |

Set caps on the proxy:

```bash
forge proxy set openrouter-anthropic costs.caps.per_day=20.00
forge proxy set openrouter-anthropic costs.caps.per_month=100.00
forge proxy set openrouter-anthropic costs.on_cap_hit=warn
```

Caps are enforced after each completed request: a request may cross a cap and complete, then the next request is blocked
once logged spend reaches the cap. `on_cap_hit=reject` returns HTTP 429 with `spend_cap_exceeded`; `on_cap_hit=warn`
lets the request continue and returns `X-Spend-Warning`.

> Earlier versions had a `costs.cap_mode` setting (`post`/`strict`); it was removed and caps are now always post-event.
> A leftover `cap_mode:` line — or any unrecognized key under `costs`/`costs.caps` — is now rejected with a config error
> naming the key, so a stale spend-cap setting can't silently change enforcement. Delete it; `forge proxy validate`
> surfaces the error before the proxy starts.

Cap enforcement is process-local and best-effort. For reliable cap enforcement, run a single proxy process per proxy ID.
Telemetry logs accumulate in `~/.forge/telemetry/`. The proxy re-bootstraps from downstream cost logs
(`~/.forge/telemetry/downstream/`) plus `~/.forge/telemetry/caps/<proxy_id>.json` at next startup. That cap-state
snapshot is deliberate: a path migration or dropped best-effort JSONL write must not silently reset a monthly cap to
`$0`. Snapshot writes are coalesced by request count/time and flushed on graceful proxy shutdown; the live proxy's
in-memory counters remain authoritative between flushes.

Shared downstream shards are bounded by the global `telemetry.downstream` policy in `~/.forge/config.yaml`, after cap
bootstrap. Current UTC calendar-month shards survive both age and size pruning. See
[Downstream telemetry retention](config.md#downstream-telemetry-retention) for status, conflict handling, and migration.

### Budget planning

If your provider gives you a monthly API credit or your team has a fixed budget for model usage, set caps to match:

```bash
forge proxy set openrouter-openai costs.caps.per_month=100
forge proxy set openrouter-openai costs.on_cap_hit=reject
```

Caps are enforced after each completed request — a request may cross the cap and complete, then the next is blocked. Use
`on_cap_hit=warn` if you prefer alerts without hard stops. Pair with `forge telemetry costs show --period month` to
monitor burn rate.

---

## Audit and intercept (optional always-on)

A proxy can also **observe** and optionally **control** the wire between Claude Code and the provider. These fields are
inert by default, so existing proxies are unchanged — set them to opt in. (The `anthropic-passthrough` template is the
exception: it ships with `intercept.mode: inspect`.) Useful when you want local evidence of what was actually sent
(system prompts, tool surfaces, drift over time) or a signature-safe place to enforce prompt guards.

Two settings, kept separate:

- **`wire_shape`** — how requests reach the upstream. `openai_translated` (default) is translated and **drops thinking
  blocks** (inspectable but lossy), but preserves tool-selection intent: Anthropic `any` requires a tool call, `auto`
  remains optional, and named/disabled choices remain named/disabled. If `tool_prefixes_to_ignore` removes every
  required tool or the specifically named tool, Forge returns HTTP 400 `invalid_request_error` instead of sending an
  unsatisfiable upstream request. `anthropic_passthrough` forwards the raw Anthropic request and **preserves thinking
  blocks byte-for-byte** (signature-safe; required for control/override). The shipped `anthropic-passthrough` template
  uses it.
- **`intercept.mode`** — `passthrough` (default, no inspection), `inspect` (observe: hashes + drift + redacted audit
  metadata), or `override` (inspect plus apply prompt augment/guards and a reasoning-effort floor). `override` requires
  `wire_shape: anthropic_passthrough`.

For catalogued Claude models with native effort support, an override reasoning floor sets `output_config.effort` without
lowering a stronger client value. Adaptive-only models reject manual `thinking.type=enabled` or `thinking.budget_tokens`
with HTTP 400; older models retain the legacy budget mapping when the requested floor can be represented safely. If the
floor changes either control surface, Forge removes `temperature`, `top_p`, and `top_k` because Anthropic rejects those
combinations. A no-op floor leaves them unchanged. The client receives a stable, actionable error with the Forge request
ID; detailed validation text remains in server logs. Audit mutation records include only the changed effort/budget
values and removed key names, never sampling values.

Anthropic passthrough also preserves safe upstream response metadata. Retry guidance and Anthropic rate-limit headers
reach the client on both successful and failed requests, including responses to streaming requests. Forge removes
upstream cookies/authentication challenges, account-selection metadata, hop-by-hop framing, content length/encoding, and
the upstream proxy-owned request/cost/resolution fields; the proxy's own request id, spend warning, and streaming cache
policy take precedence. Response bodies and SSE chunks remain unchanged.

Quick start (observe):

```bash
forge proxy create anthropic-passthrough --name audit-test   # signature-safe wire, inspect by default
forge proxy set audit-test intercept.mode=inspect
# run a session through it, then:
forge proxy audit show audit-test        # redacted records: hashes, counts — no secrets
forge proxy audit diff audit-test        # system/tool drift + any override mutations, over time
curl -s localhost:<port>/ | jq '.intercept_mode, .wire_shape'   # preflight: is inspect active and signature-safe?
```

`%proxy audit show` / `%proxy audit diff` are the read-only in-session equivalents (type them in Claude Code).

Audit records are **redacted before they are written** — metadata records hold hashes/lengths/counts only, never prompt
or response text. Records live in downstream telemetry at `~/.forge/telemetry/downstream/*.jsonl` (owner-only).
Retention is enforced once at proxy startup through the global `telemetry.downstream` policy; audit has no independent
pruner or effective retention setting. Current-calendar-month downstream shards are preserved because the same files
also carry active-month spend evidence for cap bootstrap.

⚠︎ **`audit_full_body` is a higher-risk opt-in.** It additionally captures **redacted** bodies (roles, block types,
per-block lengths — still never plaintext) in downstream telemetry: the request body on every path, and the response
body only for non-streaming passthrough today (streaming and the translated path don't capture response bodies yet).
Forge prints a privacy warning when you enable it:

```bash
forge proxy set audit-test audit.audit_full_body=true
```

**Sidecar-recommended, host-supported.** Both host and `--sidecar` sessions support the audit path. Sidecar is
recommended for an always-on posture (the proxy's lifecycle is coupled to the session). A sidecar launched with a proxy
makes its audit + cost logs host-visible automatically:

```bash
forge session start demo --sidecar --proxy audit-test
# after the session, on the host:
forge proxy audit show audit-test        # records written inside the container are here
```

---

## Request diagnostics logging

Normal proxy logging is quiet by default: successful `GET /` health/runtime-truth polls log at debug, and streaming no
longer dumps per-chunk bodies — a clean stream produces one compact lifecycle line (request id, chunk count, flags), and
an error or client disconnect is logged once. You only see noise when something is actually wrong (a `4xx`/`5xx`, a slow
poll, or a disconnect). The durable "what happened to my request?" answer comes from the cost/audit/usage/provider-trace
planes, not from log volume.

For deeper debugging, each proxy has an optional **bounded, redacted** request-diagnostics log under
`~/.forge/logs/requests/` (owner-only), controlled by a `logging.requests` block in the proxy file:

```yaml
# ~/.forge/proxies/<id>/proxy.yaml
logging:
  requests:
    enabled: auto # off | auto (only when running at log_level=debug) | on (always)
    body_capture: metadata # metadata (no body) | redacted (sanitized structure, never plaintext)
    response_capture: metadata
    max_file_mb: 16 # rotate the active shard at this size (0 = unbounded)
    max_total_mb: 256 # prune oldest shards over budget at startup (0 = unbounded)
    retention_days: 14 # prune shards older than this at startup (0 = no age bound)
    stream_chunks: false # opt-in per-chunk dumps (off even at log_level=debug)
    stream_chunk_max_bytes: 0 # truncate each dumped chunk (0 = small default cap)
```

Like audit, this **never** writes plaintext: there is no `full` mode — `body_capture=full` is rejected with a pointer to
the audit policy, and `redacted` reuses the same redaction as audit (roles, block types, lengths — no prompt/completion/
tool text). `enabled: on` is the way to capture diagnostics without turning on full `log_level=debug` spam. Retention is
enforced at proxy startup. `forge logs show` notes the current capture mode; `forge proxy show <id> --raw` shows the
configured block.

---

## Provider trace (request lifecycle diagnostics)

Provider lifecycle metadata answers one question after a timeout: *what happened to this provider request?* It was born
from an incident -- a supervised fork's checks timed out before the final streaming usage chunk and left no trace
locally or in OpenRouter's dashboard.

Records live inside owner-only downstream telemetry under `~/.forge/telemetry/downstream/` and carry **no** prompt,
completion, tool output, or request body -- only lifecycle/correlation evidence (request id, proxy, backend instance,
model, provider generation id, stream flags, disconnect, and whether local cost was seen). Written only for routes whose
backend instance declares provider-trace capability (OpenRouter enabled in v1); gateway-routed OpenRouter through
non-capable backend instances writes nothing.

```bash
# Recent traces (today by default; --period today|week|month|all)
forge telemetry trace list
forge telemetry trace list --session my-session      # by session label
forge telemetry trace list --root-run-id run_abc...   # exact run tree
forge telemetry trace list --period week --json

# One record / a plain-language explanation
forge telemetry trace show <request_id>
forge telemetry trace explain <request_id>
```

`explain` answers five questions from **local records only** (no remote lookup):

```text
req_... left Forge via proxy crimson-apricot -> OpenRouter openai/gpt-5.5 (upstream: Azure).
Stream started and emitted chunks; final usage was not observed; client disconnected.
Provider generation id: gen-... (session forge_sess_..._supervisor).
Local cost is unavailable, not zero.
No remote lookup was performed.
```

Provider-trace diagnostics are terminal-only; there is no in-chat direct-command mirror.

**Notes:**

- `--session` matches the hashed session **label** only -- two same-named sessions in one `FORGE_HOME` share it. Use
  `--root-run-id` when you need an exact match.
- "Local cost is unavailable, not zero" is the point: a stream cancelled before its final usage chunk has no local cost,
  which is different from a genuine `$0`.
- Remote OpenRouter reconciliation is intentionally out of scope here -- this surface is local-only by design.

**Recording the session id upstream (opt-in).** `provider_trace.inject_provider_user` (**global, default off**) makes
OpenRouter routes carry the Forge session grouping id in the OpenAI-standard `user` field, so a session's (or a fork's)
requests are **recorded in the provider's account-side record (e.g. OpenRouter's `/generation` record) for account-side
lookup**. The value is the hashed `forge_sess_<hash>[_role]` id (or a `forge_run_<hash>` fallback) -- never the raw
session name. It is one switch, set in `~/.forge/config.yaml`:

```bash
forge config set provider_trace.inject_provider_user=true
```

One toggle governs both **proxied** routes and Forge's **direct** `core.llm` calls (plan-check, transfer curation), so a
run's calls group together upstream regardless of path. Restart any running proxy after enabling so it re-reads the
toggle. Observability only (not routing -- recognition is stickiness-neutral); non-OpenRouter routes stay quiet.

> **Moved from `proxy.yaml`.** This was previously a per-proxy `proxy.yaml` key. It is now global in
> `~/.forge/config.yaml`. A stale `provider_trace.inject_provider_user` left in `proxy.yaml` still loads but is
> **ignored** with a one-time warning naming the `forge config set` command above. Retention also moved to global
> `telemetry.downstream`; stale `audit`/`provider_trace` retention keys are compatibility inputs only and can be removed
> explicitly with `forge config migrate-retention --yes`.

### Remote reconciliation

`forge model backend reconcile <backend>` answers the *other* half of "what happened to this request?": it joins your
local provider-trace evidence to the **backend's own account-side record**. The mechanism is generic over any backend
with a remote adapter; **OpenRouter is the first adapter**.

```bash
# Local-anchored: a local request id -> its generation id -> the remote record
forge model backend reconcile openrouter --request-id req_abc...

# Remote-only: the backend's own record id (e.g. an OpenRouter gen-... id)
forge model backend reconcile openrouter --remote-id gen-...

forge model backend reconcile openrouter --request-id req_abc... --json   # stable JSON
```

Results are bucketed: **joined** (local + remote matched), **remote** (a raw remote-id lookup), **missing-remote**
(present locally, absent remotely -- e.g. an aborted stream the backend never finalized), and **not-queryable** (a local
trace with no generation id, or a remote lookup that timed out / was rate-limited / lacked credentials). Remote and
local cost/tokens are shown **separately with provenance** -- a remote figure never overwrites a locally observed one,
and a missing remote record never implies the request did not happen. Metadata only: it never fetches prompt/completion
content. Windowed account-wide activity/analytics (management key) is a planned follow-on.

---

## Prerequisites

- **Claude Code >= 2.1.81** -- required for `--bare` (used by workflow subprocesses for faster startup). Older versions
  produce `--bare: unknown option` errors.

---

## Troubleshooting

### "I changed my session but the proxy didn't change models"

That's expected. Sessions don't control proxy routing.

- Verify you launched Claude with the intended proxy (`forge claude start --proxy <id>`)
- Verify the proxy is healthy (`forge proxy list` / `GET /`)

### "A proxy is running but `forge proxy list` doesn't show it"

Re-create with `forge proxy create <template>` to register it.

### "I put tier→model in ~/.forge/config.yaml and nothing changed"

`~/.forge/config.yaml` is not for routing configuration. Per-proxy config belongs in
`~/.forge/proxies/<proxy_id>/proxy.yaml`.

### Where do I configure routing?

**In your proxy file:** `~/.forge/proxies/<proxy_id>/proxy.yaml`

Or **customize the template** before creating proxies: `forge proxy template edit <name>` creates a user copy at
`~/.forge/templates/<name>.yaml` that overrides the built-in. Future proxies created from that template will use your
customized version.

NOT in:

- Session files (cannot modify routing)
- `~/.forge/config.yaml` (not for routing; use per-proxy file or template)

---

## Advanced

### Proxy file anatomy (authoritative)

| File                                     | Purpose                                           |
| ---------------------------------------- | ------------------------------------------------- |
| `~/.forge/proxies/<proxy_id>/proxy.yaml` | Per-proxy configuration                           |
| `~/.forge/proxies/index.json`            | Registry of all proxies (name, port, pid, status) |
| `~/.forge/templates/<name>.yaml`         | User-customized templates (overrides built-in)    |
| `src/forge/config/defaults/templates/`   | Built-in templates (shipped with Forge)           |

### What `forge proxy create` actually does

The create command implements **reuse/adopt/spawn** logic:

1. **Reuse**: Check registry for existing healthy proxy with matching template
2. **Adopt**: Check expected default port for orphan proxy (not in registry)
3. **Spawn**: Start new proxy if neither exists

Optional create-time smoke verification reports against whichever source won. In JSON mode it augments that one creation
result instead of printing a second document; verification failure does not undo creation.

### Runtime truth

The proxy `GET /` endpoint is the authoritative source for:

- Proxy identity
- Canonical runtime backend id
- Effective tier→model and per-tier model-alternative mappings, after any active ZDR substitution
- Current health status
- Runtime metrics (requests, tokens, latency)

The added `runtime.backend_id` and `runtime.model_alternatives` fields are secret-free. Older proxies remain compatible:
`forge session model show` falls back from live runtime to current `proxy.yaml`, then the supported launch commitment,
and labels the source instead of presenting fallback as live truth. The opt-in status-line `marking` segment is
stricter: without the authoritative live fields it renders `mark:?`, never a config-derived yes/no. File caches
(`index.json`, `proxy.yaml`) are operational conveniences; a reachable proxy is runtime truth.

### Gotchas

| Trap                                    | Explanation                                                         |
| --------------------------------------- | ------------------------------------------------------------------- |
| "Edited proxy.yaml but nothing changed" | Restart proxy or re-create for changes to take effect               |
| "Proxy says healthy but proxy is dead"  | `forge proxy list` auto-prunes dead entries; `forge clean` does too |
| "Can't find my proxy"                   | Check `~/.forge/proxies/index.json` for registered proxies          |
