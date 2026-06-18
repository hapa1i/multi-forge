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

### Full model capabilities

Provider CLIs sometimes limit the models they serve. For example, OpenAI's Codex CLI caps GPT-5.5 at 400K tokens as a
serving-budget decision, even though the model supports 1,050,000 tokens via the API. Forge proxies route through the
API directly, so you get the model's full context window and the complete set of reasoning effort levels.

This also means access to models that product CLIs don't expose at all -- like `gpt-5.5-pro` (1M context, higher
reasoning quality) or mixing providers within a single workflow (GPT for planning, Claude for execution).

The tradeoff is cost: you pay API rates instead of bundled subscription pricing. Forge's
[spend caps](#cost-tracking-and-spend-caps) make this manageable.

### System prompt addendums

When routing to non-Anthropic models, Forge automatically injects a tool-discipline addendum into the system prompt at
session launch. Non-Anthropic models tend to hallucinate optional tool parameters (e.g., `"pages": ""` on Read calls)
and reach for Bash as a workaround for tool errors. The addendum teaches them to use minimal valid parameters and prefer
dedicated tools. No configuration needed.

Note: addendums are injected by the session launcher (`--append-system-prompt-file`), not by the proxy itself. Direct
HTTP use of the proxy does not include them.

### No-proxy mode

When using Claude Code directly (without Forge proxy), proxies are not used. Sessions still function for workflow
settings (worktrees, artifacts, policies, etc.), but tier/model routing and hyperparameter defaults do not apply — those
require a proxy instance.

---

## Proxy templates

Forge provides ready-to-use proxy configurations (internal templates):

| Template                     | Use case                                    |
| ---------------------------- | ------------------------------------------- |
| `openrouter-anthropic`       | Claude models via OpenRouter (direct)       |
| `openrouter-deepseek`        | DeepSeek models via OpenRouter (direct)     |
| `openrouter-glm`             | GLM / Z.ai models via OpenRouter (direct)   |
| `openrouter-kimi`            | Kimi models via OpenRouter (direct)         |
| `openrouter-minimax`         | MiniMax models via OpenRouter (direct)      |
| `openrouter-openai`          | GPT models via OpenRouter (direct)          |
| `openrouter-qwen`            | Qwen models via OpenRouter (direct)         |
| `openrouter-gemini`          | Gemini models via OpenRouter (direct)       |
| `openrouter-openai-codex`    | OpenAI Codex models via OpenRouter (direct) |
| `openrouter-gemini-flash`    | Gemini Flash via OpenRouter (cheap, direct) |
| `litellm-anthropic`          | Anthropic models via remote/shared LiteLLM  |
| `litellm-anthropic-local`    | Local LiteLLM + Anthropic API key           |
| `litellm-openai`             | OpenAI models via remote/shared LiteLLM     |
| `litellm-gemini`             | Gemini models via remote/shared LiteLLM     |
| `litellm-openai-local`       | Local LiteLLM + OpenAI API key              |
| `litellm-openai-codex-local` | Local LiteLLM + OpenAI Codex models         |
| `litellm-gemini-local`       | Local LiteLLM + Gemini API key              |
| `litellm-gemini-flash-local` | Local LiteLLM + Gemini Flash (fast/cheap)   |

`litellm-gemini-test` also exists internally, but it is hidden from normal end-user template lists.

Built-in templates declare `proxy.source`, the canonical model-source id that owns endpoint and credential requirements.
If you customize a template under `~/.forge/templates/<name>.yaml`, keep `proxy.source` set to an existing source id
such as `openrouter`, `litellm-remote`, or `litellm-gemini-local`; Forge derives local backend auto-start and remote
upstream URLs from that source at proxy creation time.

OpenRouter templates default to `https://openrouter.ai/api/v1`. Set `OPENROUTER_BASE_URL` only when you intentionally
route OpenRouter-compatible traffic through a different endpoint; new proxies created from OpenRouter templates will
copy that resolved upstream URL into `proxy.yaml`.

---

## Core commands (cheat sheet)

```bash
# Templates
forge proxy template list        # List available templates
forge proxy template show <name> # Show template configuration
forge proxy template edit <name> # Customize a template (copy-on-first-edit)
forge proxy template reset <name># Reset to built-in default

# Create / start
forge proxy create <template> [--name <id>] [--no-start]
forge proxy start <proxy_id> [--smoke-test]
forge proxy stop <proxy_id>

# Show / list
forge proxy show <proxy_id>      # Full proxy configuration
forge proxy list                 # All proxies with status

# Modify
forge proxy edit <proxy_id>      # Open in $EDITOR
forge proxy set <proxy_id> <key>=<value>

# Delete
forge proxy delete <proxy_id> [--yes] [--kill-adopted]

# Metrics
forge proxy metrics [proxy_id]   # Runtime metrics (tokens, latency, failures)
forge proxy metrics --all        # Metrics for all active proxies
forge proxy metrics --json       # Raw JSON output

# Maintenance
forge proxy clean                # Clean up stale proxies
forge proxy validate <proxy_id>  # Validate config
```

**Auto-start from a template.** `--proxy` (on `forge session start/resume/fork` and `forge claude start`) and
`--supervisor-proxy` (on `forge session start/fork` and `forge policy supervise`) accept a **template name** as well as
a running proxy id. If no proxy is running for that name, Forge starts one from the matching template -- no separate
`forge proxy create` needed -- and prints the proxy it started (stop it later with `forge proxy stop <proxy_id>`). A
name that matches neither a running proxy nor a template fails with a hint to run `forge proxy template list`.

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
#   haiku: google/gemini-3.5-flash
#   sonnet: anthropic/claude-sonnet-4.6
#   opus: openai/gpt-5.5
```

Models not in Forge's catalog (e.g., `meta-llama/llama-3.1-70b`) work -- the proxy uses safe defaults for
`max_output_tokens` and `context_window` when catalog data is unavailable.

---

## Model alternatives

Anthropic proxy templates (`openrouter-anthropic`, `litellm-anthropic`, `litellm-anthropic-local`) configure user-facing
`model_alternatives` to support multiple Claude model versions at the same tier. Their opus tier defaults to Claude
Fable 5, with Opus 4.8 and Opus 4.6 as alternatives. (`anthropic-passthrough` forwards the client's model unchanged, so
`--model` selects the model directly with no alternatives map.) Use `--model` to select an alternative:

```bash
# Default: opus tier routes to Claude Fable 5
forge session start my-session --proxy openrouter-anthropic

# Select an Opus alternative instead (4.8 or 4.6)
forge session start my-session --proxy openrouter-anthropic --model claude-opus-4-8
```

The proxy resolves the alternative at request time -- Claude Code sends the model name, the proxy looks up
`model_alternatives[tier][model]` and routes to the configured backend model. Tier-level hyperparameters
(reasoning_effort, etc.) still apply regardless of which alternative is selected.

`--model` is currently a Claude model pin. Other proxy templates may define `model_alternatives` for explicit proxy API
requests that already send the matching model name, but those alternatives are not selected by `forge session --model`.

To add or edit alternatives, use `forge proxy edit <proxy_id>`:

```yaml
model_alternatives:
  opus:
    claude-opus-4-8: anthropic/claude-opus-4.8
    claude-opus-4-6: anthropic/claude-opus-4.6
```

For per-role guidance on when to pin `--model claude-opus-4-8` vs leave the default Fable 5 mapping in place — including
the supervisor-vs-executor split, the structural reasons MRCR varies across model versions, and per-family cost +
multi-needle retrieval data — see [model-selection.md](model-selection.md).

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
```

**Semantics (reuse/adopt/spawn):**

- Reuses an existing healthy proxy for that template if present
- Adopts an orphan proxy at the expected default port if found
- Spawns a new proxy if neither exists
- Blocks until the proxy is healthy (with timeout)
- Records in `~/.forge/proxies/index.json`

Use `--smoke-test` after first setup or credential changes to verify the proxy can reach its upstream LLM provider.
Without it, health checks only confirm the local proxy process is alive.

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

### Delete a proxy

```bash
forge proxy delete <proxy_id>
```

Stops the proxy and cleans up registry entries and overlay files.

### Other commands

```bash
# Prune stale proxies (dead processes)
forge proxy clean

# Validate a proxy config file
forge proxy validate <proxy_id>
```

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
source: openrouter
proxy_endpoint: http://localhost:8096
port: 8096
upstream_base_url: https://openrouter.ai/api/v1

tiers:
  haiku: openai/gpt-5.4-mini
  sonnet: openai/gpt-5.5
  opus: openai/gpt-5.5

default_tier: sonnet

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
`proxy_format`, `template`, `provider`, `source`, `proxy_endpoint`, `upstream_base_url`, `port`, and `tiers` alone
unless you know what you're doing — those are set from the template/source catalog at creation.

**Available tier_override keys:** `reasoning_effort`, `temperature`, `max_tokens`, `thinking_budget_tokens`. All are
per-tier because each model has different limits and optimal defaults.

**Precedence chain** (first non-null wins):

1. Request explicit value (e.g., `temperature` in API call)
2. Per-tier override (`tier_overrides.<tier>.*`)
3. Model catalog default (built-in per-model defaults)

**Example:** If a request includes `temperature=0.5`, it overrides the proxy's `tier_overrides.opus.temperature`.

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
3. Fork to Session B and relaunch Claude against an **execution proxy** (`forge claude start --proxy <proxy_id>`).
4. Fork to Session C and relaunch Claude against a **review proxy** the same way.
5. Use A and C for independent reviews; have B synthesize and fix.

Proxies make this deterministic: each session's requests hit a specific base URL, so routing defaults are stable.

---

## Proxy metrics

Each running proxy tracks in-memory metrics: request counts, token usage (input/output/cached), per-tier and per-model
breakdowns, failure rates, and latency. Metrics reset on proxy restart.

```bash
# View metrics for a specific proxy
forge proxy metrics my-proxy

# View all active proxies
forge proxy metrics --all

# JSON output (for scripting)
forge proxy metrics --json
```

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

---

## Cost tracking and spend caps

Proxy request costs are logged as downstream telemetry under `~/.forge/telemetry/downstream/`. Legacy
`~/.forge/costs/requests/` and `~/.forge/costs/verbs/` files may exist from older installs; new request spend writes to
downstream records, and the by-verb view joins those records to run ids instead of writing new verb snapshot files.

```bash
forge proxy costs show                    # Today's costs, by verb
forge proxy costs show --by-model         # Today's costs, by model
forge proxy costs show --period week      # This week
forge proxy costs show openrouter-anthropic    # Filter by proxy

forge proxy costs reset                   # Wipe ALL cost + usage telemetry to zero (prompts; --yes to skip)
forge proxy costs reset --dry-run         # Preview what would be removed, delete nothing
```

`forge proxy costs reset` deletes legacy cost logs, downstream/upstream telemetry shards, spend-cap snapshots, sidecar
audit drift state, **and** the usage-attribution ledger (`forge activity`/`forge +$Y` data) under `~/.forge/`. It also
clears the derived status-line cost and supervisor-health caches so status-line segments recompute from the now-empty
telemetry instead of replaying cached values. It is irreversible (confirm prompt unless `--yes`). A running proxy keeps
its cost totals **and** cap counters in memory until restarted — so a live proxy's cumulative-cost header, snapshot, and
`forge proxy costs show` figures do not zero until you restart it (`forge proxy stop <id>` then
`forge proxy start <id>`).

> **Per-session view:** `forge proxy costs show` is the authoritative, **proxy-scoped** dollar view. The status-line
> `cost` segment shows the interactive Claude session's proxy-reported `~$`, scoped by subtracting the proxy total
> captured at session launch. For a **session-scoped** rollup of what Forge did — supervisor checks (including failed
> ones), tokens, and *reported-or-estimated* cost (best-effort, may be partial) — use
> [`forge activity [session]`](session.md#what-a-session-did-forge-activity--session-end-summary). The views are
> complementary: spend is billed per proxy; activity is attributed per session; the status line is live and best-effort
> for the current interactive launch.

### Which surface answers which question?

Forge surfaces cost and usage through several views with deliberately different scopes. Pick the one that matches your
question. Forge never prices a request from a local table — a missing cost shows as `unavailable`, never invented (per
the provenance column: `forge proxy costs show` is reported-only; `forge activity` also includes best-effort
verb-snapshot estimates):

| Surface                                | Question it answers                               | Scope                                                                   | Cost provenance                                                                 |
| -------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `forge proxy costs show`               | "What did this proxy actually spend?"             | one proxy's request log (proxy-scoped)                                  | reported `$` or `unavailable`; **authoritative** spend view                     |
| `forge activity [session]`             | "What did Forge's automation do this session?"    | one Forge session — operation outcomes + model calls joined by run tree | reported-or-estimated `$`, best-effort attribution                              |
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
> If an older `proxy.yaml` still has a `cap_mode:` line, remove it — the proxy otherwise refuses to load with a message
> telling you to.

Cap enforcement is process-local and best-effort. For reliable cap enforcement, run a single proxy process per proxy ID.
Telemetry logs accumulate in `~/.forge/telemetry/` (with legacy cost logs under `~/.forge/costs/` from older installs).
The proxy re-bootstraps from downstream/legacy cost logs plus `~/.forge/telemetry/caps/<proxy_id>.json` at next startup.
That cap-state snapshot is deliberate: a path migration or dropped best-effort JSONL write must not silently reset a
monthly cap to `$0`. Snapshot writes are coalesced by request count/time and flushed on graceful proxy shutdown; the
live proxy's in-memory counters remain authoritative between flushes.

### Budget planning

If your provider gives you a monthly API credit or your team has a fixed budget for model usage, set caps to match:

```bash
forge proxy set openrouter-openai costs.caps.per_month=100
forge proxy set openrouter-openai costs.on_cap_hit=reject
```

Caps are enforced after each completed request — a request may cross the cap and complete, then the next is blocked. Use
`on_cap_hit=warn` if you prefer alerts without hard stops. Pair with `forge proxy costs show --period month` to monitor
burn rate.

---

## Audit and intercept (optional always-on)

A proxy can also **observe** and optionally **control** the wire between Claude Code and the provider. These fields are
inert by default, so existing proxies are unchanged — set them to opt in. (The `anthropic-passthrough` template is the
exception: it ships with `intercept.mode: inspect`.) Useful when you want local evidence of what was actually sent
(system prompts, tool surfaces, drift over time) or a signature-safe place to enforce prompt guards.

Two settings, kept separate:

- **`wire_shape`** — how requests reach the upstream. `openai_translated` (default) is translated and **drops thinking
  blocks** (inspectable but lossy). `anthropic_passthrough` forwards the raw Anthropic request and **preserves thinking
  blocks byte-for-byte** (signature-safe; required for control/override). The shipped `anthropic-passthrough` template
  uses it.
- **`intercept.mode`** — `passthrough` (default, no inspection), `inspect` (observe: hashes + drift + redacted audit
  metadata), or `override` (inspect plus apply prompt augment/guards and a reasoning-effort floor). `override` requires
  `wire_shape: anthropic_passthrough`.

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
Retention is enforced at proxy startup via `audit.retention_days` and `audit.max_total_mb`; current-calendar-month
downstream shards are preserved because the same files also carry active-month spend evidence for cap bootstrap.

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
enforced at proxy startup. `forge logs` notes the current capture mode; `forge proxy show <id> --raw` shows the
configured block.

---

## Provider trace (request lifecycle diagnostics)

Provider lifecycle metadata answers one question after a timeout: *what happened to this OpenRouter request?* It was
born from an incident -- a supervised fork's checks timed out before the final streaming usage chunk and left no trace
locally or in OpenRouter's dashboard.

Records live inside owner-only downstream telemetry under `~/.forge/telemetry/downstream/` and carry **no** prompt,
completion, tool output, or request body -- only lifecycle/correlation evidence (request id, proxy, model, provider
generation id, stream flags, disconnect, and whether local cost was seen). Direct-OpenRouter only.

```bash
# Recent traces (today by default; --period today|week|month|all)
forge provider trace list
forge provider trace list --session my-session      # by session label
forge provider trace list --root-run-id run_abc...   # exact run tree
forge provider trace list --period week --json

# One record / a plain-language explanation
forge provider trace show <request_id>
forge provider trace explain <request_id>
```

`explain` answers five questions from **local records only** (no remote lookup):

```text
req_... left Forge via proxy crimson-apricot -> OpenRouter openai/gpt-5.5 (upstream: Azure).
Stream started and emitted chunks; final usage was not observed; client disconnected.
Provider generation id: gen-... (session forge_sess_..._supervisor).
Local cost is unavailable, not zero.
No remote lookup was performed.
```

The same three commands are available in-session as `%provider trace list|show|explain` (read-only).

**Notes:**

- `--session` matches the hashed session **label** only -- two same-named sessions in one `FORGE_HOME` share it. Use
  `--root-run-id` when you need an exact match.
- "Local cost is unavailable, not zero" is the point: a stream cancelled before its final usage chunk has no local cost,
  which is different from a genuine `$0`.
- Remote OpenRouter reconciliation is intentionally out of scope here -- this surface is local-only by design.

**Recording the session id upstream (opt-in).** `provider_trace.inject_openrouter_user` (per-proxy, **default off**)
makes proxied direct-OpenRouter requests carry the Forge session grouping id in the OpenAI-standard `user` field, so a
session's (or a fork's) requests are **recorded in OpenRouter's `/generation` record for account-side lookup**. The
value is the hashed `forge_sess_<hash>[_role]` id (or a `forge_run_<hash>` fallback) -- never the raw session name.
Enable it per proxy and restart the proxy:

```yaml
provider_trace:
  inject_openrouter_user: true # default false; proxied direct-OpenRouter only
```

Observability only (not routing -- recognition is stickiness-neutral); direct `core.llm` callers (plan-check, curation)
are unchanged this release.

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

### Runtime truth

The proxy `GET /` endpoint is the authoritative source for:

- Proxy identity
- Tier→model mappings
- Current health status
- Runtime metrics (requests, tokens, latency)

File caches (index.json, proxy.yaml) are convenience; proxy state is truth.

### Gotchas

| Trap                                    | Explanation                                                |
| --------------------------------------- | ---------------------------------------------------------- |
| "Edited proxy.yaml but nothing changed" | Restart proxy or re-create for changes to take effect      |
| "Proxy says healthy but proxy is dead"  | Run `forge proxy clean` to clean stale entries             |
| "Can't find my proxy"                   | Check `~/.forge/proxies/index.json` for registered proxies |
