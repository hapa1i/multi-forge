# Forge Runtime and Routing Design

Canonical proxy, backend, model-routing, shared-client, subprocess, and isolation contracts.

Subprocess transport selection and consumer-lane contracts live in [subprocess routing](design_subprocesses.md). This
entry point retains proxy/backend lifecycle, model catalogs, configuration, and isolation.

---

## Runtime and routing contracts

#### 3.6.3 Proxy lifecycle UX

**Implemented:**

```bash
# List proxies
forge proxy list

# Create a proxy from template with optional per-tier overrides
forge proxy create litellm-openai \
  --opus-reasoning high \
  --sonnet-temperature 0.7
```

**Also implemented:**

```bash
# Start Claude pinned to this proxy
forge claude start --proxy <proxy_id>

# Edit proxy config
forge proxy edit <proxy_id>
# OR: forge proxy set <proxy_id> tier_overrides.opus.reasoning_effort=high

# Delete proxy
forge proxy delete <proxy_id>
```

**Stop/delete ownership contract.** A required process stop that is refused or fails exits non-zero and keeps the
registry row and proxy configuration as actionable ownership. `delete` decides shared-port ownership under the registry
lock; when the target is the last live reference and termination is required, it completes that stop before removing the
row or overlay. A later overlay-removal failure restores the row with stopped state when termination already succeeded.
Default adopted detach, explicit `--no-kill`, already-stopped processes, and deletion while another live same-port alias
remains are intentional successful outcomes. Multi-delete continues independent targets but exits non-zero and reports
failures if any required stop fails.

**Create smoke-result contract.** On the normal reuse/adopt/spawn path, `proxy create --json` emits one creation result.
Without `--smoke-test`, its established top-level fields remain unchanged. With `--smoke-test`, the same object adds
`smoke_test: {passed, detail}`; a failed probe exits non-zero but retains the successfully created or resolved proxy.
Human-mode verification output remains unchanged. `--no-start` is config-only and does not run a smoke probe.

**Translated request-metadata contract.** The `openai_translated` route carries the inbound User-Agent through internal
`_user_agent` metadata for both LiteLLM (local or remote) and OpenRouter clients. The adapter strips control characters
and caps the upstream value at 256 characters. This is a narrow identity relay, not general header passthrough:
authorization, API keys, cookies, and internal `X-Forge-*` correlation headers do not enter it, and the Anthropic-native
and Responses passthrough allowlists are unchanged.

**Launch-time auto-start (lookup-or-start).** `--proxy` (session start/resume/fork, `forge claude`) and
`--supervisor-proxy` (session start/fork, `forge policy supervisor set`) accept a template name. When the name is a
template, the launcher routes through `ensure_proxy()` → `start_proxy()` (reuse a live proxy, else adopt/spawn) instead
of a lookup-only `resolve_proxy()`. This makes a template name with no running proxy — or a registry entry marked
`healthy` that is no longer reachable — start a live proxy rather than fail. A bare proxy_id is still presence-only
(revive with `forge proxy start <id>`); a name matching neither a proxy nor a template fails with a
`forge proxy template list` hint.

**Overlay boundary:** You do NOT edit internal templates/model catalog—only your proxy overlay.

> **Configuration reference details** — proxy overlay schema, template inventory, confusion traps, secrets, runtime
> config (`~/.forge/config.yaml`), model catalog, and status line guidance are in
> [design_runtime.md §A](design_runtime.md#a-configuration-reference).

### 3.7 Proxy runtime truth

When reachable, live proxy `GET /` is authoritative for tier→model mappings and context windows; caches are not:

```json
{
  "is_proxy": true,
  "status": "running",
  "proxy": { "template": "litellm-openai", "base_url": "http://localhost:8085" },
  "wire_shape": "openai_translated",
  "intercept_mode": "passthrough",
  "intercept": { "mode": "passthrough", "can_inspect": { "...": "..." } },
  "tiers": {
    "haiku": { "model": "gpt-4o-mini", "context_window": 128000 },
    "sonnet": { "model": "gpt-4o", "context_window": 128000 },
    "opus": { "model": "o3", "context_window": 200000 }
  },
  "runtime": {
    "backend_id": "openrouter",
    "configured_tier_mappings": { "...": "..." },
    "tier_mappings": { "...": "..." },
    "model_alternatives": { "opus": { "claude-opus-4-8": "anthropic/claude-opus-4.8" } },
    "data_policy": { "zdr": "not_applicable", "zdr_fallbacks": {} }
  }
}
```

**Key points:**

- Proxy and session state remain independent; status tools read both (see §3.6.2).

- `runtime.backend_id`, `runtime.tier_mappings`, and `runtime.model_alternatives` are secret-free effective loaded
  routing facts. The exposed tier and alternative targets include the same active ZDR substitutions used for dispatch.
  Older responses that omit the additive fields remain readable, but callers label config or launch-commit recovery as
  fallback rather than live runtime evidence.

- Known optional tier keys may be present with an empty string when that tier has no route. Runtime-truth readers omit
  those empty entries from the exposed mapping without rejecting the otherwise authoritative response; unknown keys,
  non-string values, or a map with no nonempty route remain non-authoritative.

- Top-level `status` is `running` when downstream retention resolves and completes without an enforcement error; it is
  `degraded` when retention resolution or pruning fails. Degraded retention remains reachable and keeps the proxy
  identity fields available; the nested `downstream_retention` object carries the recovery detail.

- Spend cap rejections return HTTP 429 with `error.type=spend_cap_exceeded`

- Warn-mode spend caps allow the request and attach `X-Spend-Warning`

- `wire_shape` is the authoritative wire truth (a passthrough proxy may carry `provider: litellm` as a credential slot
  only); `intercept_mode` + `intercept.can_inspect` let a launcher report "inspect active (signature-safe)" vs "inspect
  active (lossy)" before launch (§7.x)

- `wire_shape: openai_responses_passthrough` is the **Codex-facing** raw OpenAI **Responses** shape on `/v1/responses*`
  (create + retrieve/cancel/input_items/delete/compact/input_tokens). It forwards traffic byte-for-byte (signature-safe;
  `can_inspect.*=false`, like `anthropic_passthrough`). Routing requires that wire shape plus backend
  `responses_ingress`; `GET /`'s `capabilities.responses_ingress` and Codex preflight's `proxy_supported` expose the
  conjunction. Reported `x-litellm-response-cost` is USD→micros; an OpenAI-direct upstream is token-telemetry-only. The
  launcher is `forge codex start --proxy` (§3.4). The shared `proxy.sse_framing` incremental data/JSON framer serves
  both raw passthrough usage taps; accumulators own protocol event merging and lifecycle semantics.

  The shape governs the Responses ingress; it does not make the proxy exclusive to Codex. The same
  `codex-responses-local` instance deliberately accepts Claude-backed sessions and workers on `/v1/messages`, where the
  ordinary Anthropic-to-OpenAI translation path applies. Messages callers receive no raw-Responses signature guarantee.

**Marking-practice separation.** Runtime truth identifies effective routes; it does not classify provider practices. The
package-owned `core/data/model_practices.yaml` separately records dated, source-linked provider declarations under
conjunctive runtime/route/backend/billing scope. Route journals snapshot the declaration resolved at launch, while
terminal reads compare that snapshot with the current catalog. Live marking entries are generated only from the new
authoritative runtime maps; config and route-commit fallbacks stay visibly non-live. The initial production catalog is
valid and intentionally empty, so every model resolves to `unknown` until a separately reviewed source change lands. An
`effective_from` date becomes eligible on that UTC calendar date.

**Tier selection precedence:**

1. Request explicit tier (model name contains `haiku|sonnet|opus`)
2. Proxy default tier (configured for that base URL)

Tier-word detection for raw model names is single-sourced in `forge.core.tiers.detect_tier_word()`. The status line's
display-name helper remains separate because it has different display fallback behavior (defaults to `sonnet` when no
tier word is visible).

This applies to tier selection *within* a resolved proxy. Which proxy a subprocess uses is decided by the resolution
chain (§3.6.12).

## 7. Isolation and Proxy Modes

| Concern                  | Solution                                     | Owner                                                                                             |
| ------------------------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Security isolation       | Seatbelt/bubblewrap per-command              | Claude Code native ([sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime)) |
| Full container isolation | microVMs via `docker sandbox run`            | [Docker Sandboxes](https://docs.docker.com/ai/sandboxes/claude-code/)                             |
| Proxy lifecycle coupling | `--sidecar` bundles proxy + Claude in Docker | Forge sidecar mode                                                                                |

**Sidecar mode** solves operational problems (not security): lifecycle coupling, port isolation, version consistency,
log isolation. Configurable via `~/.forge/config.yaml` (`proxy_mode: host|sidecar`), overrideable with `--sidecar` /
`--host-proxy`. The launch checkout supplies `.claude/`, while the session manifest's Forge root supplies `.forge/`;
Forge mounts both at their corresponding paths under `/workspace`. It does NOT mount all of `~/.forge` (UID issues,
undermines port isolation). The launcher stages the canonical sidecar-compatible Claude runtime-hook inventory at
`<forge_root>/.forge/sidecar-home/settings.json`, mounted as the in-container user scope at
`/root/.claude/settings.json`. Those entries use the image-resolvable bare form (`forge hook <name>`), because every
sidecar is already a managed session and does not need the host dispatcher's enrollment gate. The unsupported advisory
authority catch-all is host-only and omitted from this inventory because its bare command lacks the dispatcher fast
gate. The file is replaced on every launch and the entrypoint merges `apiKeyHelper` into it idempotently; project
`.claude/settings*.json` bytes are never rewritten. `FORGE_FORGE_ROOT` is normalized to `/workspace` for hook reads,
while deferred-work markers retain the host checkout and manifest-owned Forge root separately. Stop therefore probes for
pending shadow candidates through the mounted `/workspace` Forge root and translates only the resulting marker payload
back to host-resolvable paths.

The host `~/.forge/pending-work/` queue is mounted read-write at `/root/.forge/pending-work/`, so Stop-enqueued
index/memory/shadow markers survive `--rm` for host-CLI draining. **Narrow exception (§7.x audit path):** a proxy-id
session also mounts its `~/.forge/proxies/<id>/` read-only for intercept/audit config and, when the host file exists,
`~/.forge/config.yaml` read-only at `/root/.forge/config.yaml` for global runtime settings. It mounts `~/.forge/audit/`,
`~/.forge/costs/`, `~/.forge/usage/`, and `~/.forge/telemetry/` read-write so legacy audit/cost files,
downstream/upstream telemetry, cap state, and the usage-attribution ledger survive container removal. That ledger is the
only record of in-container supervisor/verb activity and feeds `forge telemetry activity` and the session-end summary
for sidecar sessions. These are the only global `~/.forge` subdirectories mounted, preserving the port-isolation
rationale. On Linux the sidecar runs as the host `--user uid:gid`; that uid has no passwd entry, so the launcher pins
`HOME=/root` and the image makes `/root` traversable/writable (`chmod 0777 /root`) so the mapped uid can reach the
`/root/.forge` and `/root/.claude` mounts — an accommodation for the ephemeral single-session `--rm` sandbox, **not** a
security-sandbox guarantee. Sidecar sessions also persist their launch mode, extra mounts, and image in `intent.launch`
so `forge session resume <name>` can replay the same runtime wiring later. Project-scoped `statusLine` remains the D3
exception to user-scope hook ownership and resolves through the sidecar image's `PATH`.

**Forge still owns:** Docker test infrastructure, runtime config. `src/forge/sidecar/` provides sidecar mode —
operational, not a security sandbox.

### 7.x Optional Always-On Proxy (audit and control)

A Forge proxy can be a user-controlled chokepoint that **observes** and optionally **controls** the wire between Claude
Code and the model provider. The audit/intercept fields default to inert, so existing proxies are unchanged; the shipped
`anthropic-passthrough` template is the deliberate exception (it opts into `inspect`). The motivation is operational:
agent quality can change at the harness boundary without leaving local evidence. A Forge-controlled proxy gives Forge a
durable observation point and a signature-safe control point.

**Two orthogonal axes** (kept distinct everywhere):

1. **Wire shape** (`wire_shape` on the proxy config) — how the request reaches the upstream:

   - `openai_translated` (default): `convert_anthropic_to_openai` → upstream → `convert_openai_to_anthropic`. **Strips
     `thinking`/`redacted_thinking` blocks** — inspectable but **not** signature-safe (lossy). Tool choice maps `any` →
     `required`, `auto` → `auto`, named → named function, and `none` → `none` across GPT Responses; impossible filtered
     required/named choices return HTTP 400 before upstream acquisition.
   - `anthropic_passthrough`: forwards the raw Anthropic body unchanged and streams the response back unchanged.
     **Preserves thinking blocks byte-for-byte** (signature-safe). Shipped as the `anthropic-passthrough` template
     (`provider: litellm` is a credential slot only; `wire_shape` is the wire truth, and `GET /` labels it so).

2. **Intercept mode** (`intercept.mode`, per proxy):

   - `passthrough` (default): no body inspection.
   - `inspect`: observe only — hash the system prompt + tool surface, detect drift, write redacted audit metadata.
   - `override`: inspect **plus** apply mutations to the current request. **Requires
     `wire_shape: anthropic_passthrough`** (rejected at config load otherwise) so mutations are signature-safe.

At proxy ingress, optional client `X-Request-ID` values are untrusted correlation metadata. Forge preserves values of
1--128 ASCII letters, digits, `.`, `_`, and `-` exactly; absent or invalid values are replaced with a fresh endpoint
identifier (`req_`, `tok_`, or `inf_`) before request state, logs, telemetry, audit, or response handling diverges. The
rejected value is neither normalized nor recorded.

Forge's direct `core.llm` request-ID minter is contract-tested against this ingress validator. That coupling preserves
the exact `source_refs.cost_request_id` join when a registered Forge proxy is the resolved target.

Both raw passthrough transports share one response-header boundary. Safe provider metadata such as `retry-after` and
rate-limit counters is relayed on successful, error, streaming, and non-streaming upstream responses. Hop-by-hop fields
(including names nominated by `Connection`), authentication/cookie fields, OpenAI account selectors, content
length/encoding, and upstream proxy-owned fields (`x-request-id`, cost/resolution headers, and `X-Forge-*`) are stripped
case-insensitively. Forge then overlays its own request id, spend warning, and streaming `Cache-Control` with
case-insensitive replacement. Header handling never mutates the relayed response body or SSE chunks.

**Observe (`inspect`).** Before forwarding, the proxy records a redacted metadata audit record (hashes of the system
prompt and tool surface, cache markers, token counts — never plaintext) and runs drift detection: the first observation
of a hash dimension seeds a baseline; a later change emits a `drift` record. `audit.audit_full_body` (opt-in, OFF by
default) additionally captures **redacted** bodies (structure only — never plaintext, no raw-body mode): the request
body on every path, the response body only for non-streaming passthrough today (streaming/translated deferred; §A.12 has
the per-path contract). The global `telemetry.downstream` policy bounds these shared shards; audit does not own a
separate pruner or effective retention promise.

**Control (`override`).** Builds → validates → applies a mutation plan to the **current request's control surfaces
only** — the system prompt and generation parameters, **never** historical messages:

- cache-aware `system_prompt_augment` (inserted after the last `cache_control` marker so the cached prefix stays
  byte-identical; markerless appends and flags cache invalidation);
- `system_prompt_guards` (`warn`/`block`/`strip`; all `block` checks run first, so a strip can't half-mutate a blocked
  request — a block returns HTTP 403 `intercept_guard_blocked`);
- reasoning-effort pin — **reuses** `tier_overrides.<tier>.reasoning_effort` as a floor (not a new key). Catalogued
  Claude models with native effort use `output_config.effort`; adaptive-only models reject manual
  `thinking.type=enabled` or `thinking.budget_tokens` with HTTP 400. Mode-specific `between_tools_reasoning_efforts`
  restricts the floor to `low`/`medium`/`high` on Sonnet 5.5; incompatible floors fail before any mutation or forwarding
  with an actionable HTTP 400. Older models retain the legacy `thinking.budget_tokens` mapping when the floor can be
  represented safely. If a pin changes either control surface, Forge removes `temperature`, `top_p`, and `top_k` because
  Anthropic rejects those combinations; a no-op pin leaves them unchanged. The public 400 response is stable and carries
  the Forge request ID, while detailed validation text remains server-local.

**Mutation-safety invariant (normative):** override fingerprints the `messages` list (SHA256) before and after apply and
raises (`RuntimeError`, fail-closed, no forward) if it changed. Override never writes `messages[0..n-1]`, so signed
reasoning in historical turns is untouched. Mutation records carry hashes/lengths, effort or budget before/after values,
and removed sampling key names only, never sampling values.

**Route-bound caveat.** Intercept is a property of the resolved proxy/route, not the session. A direct-mode session has
no chokepoint; launch-time preflight reports visibility explicitly (it never silently "degrades to passthrough").
`GET /` surfaces both axes (`wire_shape`, `intercept_mode`, `intercept.can_inspect`, `thinking_blocks_preserved`) so a
launcher can say "inspect active (signature-safe)" vs "inspect active (lossy)".

**Sidecar-recommended, host-supported.** Both modes support the audit path; sidecar is recommended for an always-on
posture (lifecycle-coupled, port-isolated), with the narrow mounts of §7 making in-container records host-visible.

**Read surface.** `forge proxy audit show [id]` and `forge proxy audit diff [id]` (drift + override mutations in one
timeline) render redacted records; `%proxy audit show|diff` is the in-session equivalent. Redaction happens **before**
persistence — the typed builders redact, then call the writer — so no raw body reaches disk.

See [design_telemetry.md §A.11](design_telemetry.md#a11-intercept-audit-and-request-logging-configuration-7x) (config
schema) and [§A.12](design_telemetry.md#a12-audit-log-schema-7x) (audit record schema + log paths).

**Request-log hygiene (separate plane).** Normal proxy logging stays quiet by default so the durable answer to "what
happened to my request?" comes from the structured cost/audit/usage/provider-trace planes, not log volume. Successful
`GET /` runtime-truth polls log at DEBUG; INFO is reserved for `status >= 400` or slow polls (`elapsed > 1.0s`).
Streaming no longer dumps per-chunk bodies — a clean stream emits one DEBUG lifecycle summary (request id, chunk count,
first-chunk/final-usage flags), and INFO only on error or client disconnect (the passthrough relay surfaces disconnects
that were previously logged nowhere). The optional `logging.requests` block (per-proxy, strict, bounded, redacted —
[§A.11](design_telemetry.md#a11-intercept-audit-and-request-logging-configuration-7x)) governs the debug
`~/.forge/logs/requests/` plane; `body_capture=full` is rejected (audit no-plaintext policy), and one shared
`prune_jsonl_shards` helper bounds the audit, provider-trace, and request planes alike.

## A. Configuration Reference

Extracted from [design.md §3.6](design_installation.md#36-configuration-system). Core definitions, ownership invariants,
and proxy lifecycle UX remain in design.md. This section covers detailed schemas, templates, and operational guidance.

### A.1 Proxy overlay schema (§3.6.4 — user edit surface)

The **only** user-editable config for routing defaults:

```yaml
# ~/.forge/proxies/<proxy_id>/proxy.yaml
proxy:
  default_tier: sonnet                    # Top-level tier default
  litellm:                                # Provider-namespaced overrides
    tier_overrides:
      sonnet:
        reasoning_effort: medium
        temperature: 0.7
        max_tokens: 8192
      opus:
        reasoning_effort: high
        thinking_budget_tokens: 16384
        max_tokens: 16384
      haiku:
        temperature: 0.3
        max_tokens: 4096
    model_alternatives:                   # Per-tier alternative backend mappings
      opus:
        claude-opus-4-8: anthropic/claude-opus-4-8
```

**Note:** All hyperparameters are per-tier because each model has different limits and optimal defaults.

**Precedence chain** (first non-null wins):

1. Request explicit value (e.g., `temperature` in API call)
2. Per-tier override (`proxy.<provider>.tier_overrides.<tier>.*`)
3. Model catalog default (built-in per-model defaults)

> **Implementation note:** Config-file layers are base -> proxy defaults -> template -> instance. Tier hyperparameters
> stop at the instance/catalog chain; documented environment resolution remains boundary-specific.

Creation copies template `tool_prefixes_to_ignore` and provider `prompt_caching`/`auto_cache_min_tokens` into user-owned
`proxy.yaml`; runtime never re-merges the template. Provider/base_url/template stay fixed.

Failed starts restore the prior registry row; config-only starts keep a pid-less `stopped` row. Cleanup changes only an
unchanged `starting` row, preserving concurrent replacements.

### A.2 Proxy templates vs user-defined proxies (§3.6.5)

**Proxy templates** (internal, pre-canned configurations):

| Template                     | Use case                                                       |
| ---------------------------- | -------------------------------------------------------------- |
| `openrouter-anthropic`       | Claude models via OpenRouter (direct)                          |
| `openrouter-deepseek`        | DeepSeek models via OpenRouter (direct)                        |
| `openrouter-glm`             | GLM / Z.ai models via OpenRouter (direct)                      |
| `openrouter-kimi`            | Kimi models via OpenRouter (direct)                            |
| `openrouter-minimax`         | MiniMax models via OpenRouter (direct)                         |
| `openrouter-openai`          | GPT models via OpenRouter (direct)                             |
| `openrouter-qwen`            | Qwen models via OpenRouter (direct)                            |
| `openrouter-gemini`          | Gemini models via OpenRouter (direct)                          |
| `openrouter-openai-codex`    | OpenAI Codex via OpenRouter (direct)                           |
| `openrouter-gemini-flash`    | Gemini Flash via OpenRouter (cheap, direct)                    |
| `litellm-openai`             | OpenAI models via remote/shared LiteLLM                        |
| `litellm-gemini`             | Gemini models via remote/shared LiteLLM                        |
| `litellm-anthropic`          | Anthropic models via remote/shared LiteLLM                     |
| `litellm-gemini-local`       | Local LiteLLM + Gemini API key                                 |
| `litellm-gemini-flash-local` | Gemini Flash via local LiteLLM + Gemini API key                |
| `litellm-anthropic-local`    | Local LiteLLM + Anthropic API key                              |
| `litellm-openai-local`       | Local LiteLLM + OpenAI API key                                 |
| `litellm-openai-codex-local` | OpenAI Codex models via local LiteLLM + OpenAI API key         |
| `anthropic-passthrough`      | Raw Anthropic passthrough; signature-safe; inspect enabled     |
| `codex-responses-local`      | Raw Codex Responses plus translated Claude Messages ingress    |
| `litellm-gemini-test`        | Internal integration-test dependency; hidden from normal lists |

Twenty-one templates ship; `litellm-gemini-test` is test infrastructure, so twenty are user-facing.

A proxy template is an operational profile:

- Location: `src/forge/config/defaults/templates/*.yaml`
- Defines: `proxy.preferred_provider`, `proxy.default_port`, `proxy.family`, tier->model mappings, `tier_overrides`
- `proxy.family` (e.g., `openai`, `anthropic`, `gemini`) -- explicit model family metadata used by route derivation for
  native-family ranking. Required on all templates; validated at load time.
- **NOT a user edit surface** -- clone into a proxy to customize

**User-defined proxies:**

Currently, set overrides at create time:

```bash
forge proxy create openrouter-openai --opus-reasoning high
```

Create-and-edit pattern:

```bash
forge proxy create openrouter-openai --name my-high-reasoning
forge proxy edit my-high-reasoning
```

**Principle:** Create from template, then edit (don't modify internals).

### A.2.1 Backend instance catalog (§3.6.5 / unified backend Phase 1/2)

Forge has a built-in, code-level backend instance catalog in `forge.backend.sources` (still implemented as
`ModelSource`). It is the static definition layer for the upstream model backend a proxy or direct runtime reaches; it
is **not** user-authored durable state and it is distinct from both proxy templates and managed local backend processes.

| Layer                    | Owner / Location                             | Unit                                                                                    |
| ------------------------ | -------------------------------------------- | --------------------------------------------------------------------------------------- |
| Backend instance catalog | `forge.backend.sources`                      | Static instance definition: id, kind, endpoint shape, credentials, provider, capability |
| Proxy templates          | `src/forge/config/defaults/templates/*.yaml` | Operational routing profiles that declare `proxy.backend`                               |
| Local backend config     | `~/.forge/backends/<adapter>/config.yaml`    | LiteLLM service config (`model_list` / routing), copied by `forge model backend create` |
| Runtime backend registry | `~/.forge/backends/index.json`               | PID/port/status rows for managed local backend processes only                           |

`ModelSource.id` is currently the canonical backend instance id. Backend instance ids intentionally live in a different
value-space from managed process ids: for example, `litellm-gemini-local` is a backend instance id, while `litellm-4000`
remains a `ManagedBackendProcess.process_id`. Downstream telemetry uses `backend_id` for backend-instance attribution
and writes the logical backend instance id rather than the managed process id.

Backend instance definitions have:

- `id`: stable catalog id, lowercase letters/digits plus `-`, `_`, or `.`
- `kind`: `local` or `remote`
- `provider`: `ProviderType` from dependency-light `forge.core.provider_types` (`litellm_remote`, `litellm_local`,
  `anthropic`, `openrouter`, `openai`). `openai` is catalog-only -- a subscription provider, never a `core.llm` routing
  target (`detect_provider` maps `openai/<model>` to `litellm_remote`)
- `endpoint`: one of `literal_url`, `connection_value`, `local_backend`, or `runtime_native`. A `runtime_native`
  endpoint carries no URL and no Forge credential -- connection and auth are owned by the runtime (a subscription
  reached through its native login)
- `credential_ids`: credential registry names such as `openrouter`, `litellm-remote`, `anthropic-api`, `openai-api`, or
  `gemini-api`. By validator symmetry a `runtime_native` backend instance declares **none** (auth is runtime-owned);
  every other endpoint kind declares at least one
- `billing_posture`: declared billing nature, `per_token` (default), `subscription_quota`, or `free`. Distinct from the
  per-invocation `BillingMode` in `core/usage`, but its first consumer: `resolve_billing_mode` reads a keyless direct
  run's bound-lane backend posture and emits `subscription_quota` when the posture is `subscription_quota` (the shared
  spelling)
- `reachable_via`: lane runtimes that can reach the backend instance, empty = any. A subscription pins the runtime whose
  native login authenticates it (`chatgpt -> ("codex",)`, `claude-max -> ("claude_code",)`);
  `forge.core.lanes._reachable` reads this
- `capabilities`: currently includes auth-probe, provider-trace eligibility, and provider-user-grouping capability
- `local_lifecycle`: local-only refinement with adapter and default port; required env vars are derived from
  `credential_ids`; remote backend instances never set it
- `template_names`: current proxy templates that resolve to the canonical backend instance id during template loading

The translated proxy route uses a separate, deliberately collapsed `TierClientFactory.ModelProvider` vocabulary:
`litellm`, `openrouter`, and `unknown`. Both backend providers `litellm_local` and `litellm_remote` enter that boundary
as `ModelProvider.LITELLM`; the factory resolves local versus remote only when it creates the adapter. Route-level
metadata gates therefore compare the routing enum, never backend-provider string literals. For `openai_translated`
requests, the LiteLLM and OpenRouter enum members carry only the inbound User-Agent as `_user_agent`; the adapter strips
control characters and caps the upstream header at 256 characters. Credentials, cookies, and internal `X-Forge-*`
headers are not part of this relay.

The shipped v1 catalog includes:

| Backend instance id       | Kind   | Provider         | Endpoint shape                       | Credentials      | Notes                                                                                           |
| ------------------------- | ------ | ---------------- | ------------------------------------ | ---------------- | ----------------------------------------------------------------------------------------------- |
| `openrouter`              | remote | `openrouter`     | `OPENROUTER_BASE_URL` + default URL  | `openrouter`     | Provider-trace and user-group capable                                                           |
| `litellm-remote`          | remote | `litellm_remote` | `LITELLM_BASE_URL`                   | `litellm-remote` | Aliases remote LiteLLM templates                                                                |
| `anthropic-passthrough`   | remote | `anthropic`      | `https://api.anthropic.com`          | `anthropic-api`  | Proxy-template backend, no lifecycle                                                            |
| `anthropic-direct`        | remote | `anthropic`      | `https://api.anthropic.com`          | `anthropic-api`  | Direct-runtime attribution backend                                                              |
| `chatgpt`                 | remote | `openai`         | `runtime_native` (no URL)            | (none)           | Subscription via codex; `subscription_quota`, `reachable_via=("codex",)`                        |
| `claude-max`              | remote | `anthropic`      | `runtime_native` (no URL)            | (none)           | Claude Max subscription via claude_code; `subscription_quota`, `reachable_via=("claude_code",)` |
| `litellm-gemini-local`    | local  | `litellm_local`  | local LiteLLM backend on port `4000` | `gemini-api`     | Also aliases `litellm-gemini-flash-local`                                                       |
| `litellm-openai-local`    | local  | `litellm_local`  | local LiteLLM backend on port `4000` | `openai-api`     | Also aliases `litellm-openai-codex-local`                                                       |
| `litellm-anthropic-local` | local  | `litellm_local`  | local LiteLLM backend on port `4000` | `anthropic-api`  | Local Anthropic via LiteLLM                                                                     |
| `codex-responses-local`   | local  | `litellm_local`  | local LiteLLM backend on port `4000` | `openai-api`     | Raw Codex Responses plus translated Claude Messages; responses-ingress + provider-trace         |
| `litellm-gemini-test`     | local  | `litellm_local`  | local LiteLLM backend on port `4001` | `gemini-api`     | Internal integration-test dependency                                                            |

Catalog validation rejects duplicate backend instance ids or aliases, unknown `kind`/`provider`/`billing_posture`
values, missing or unknown credentials, a `runtime_native` backend instance that declares any credential or endpoint
URL, a `reachable_via` entry outside the lane runtime axis (`{core_llm}` plus the agent `RUNTIMES`, via dependency-light
`forge.core.runtime_vocab`), malformed literal URLs, malformed connection-value env var names, remote lifecycle
declarations, and local backend instances without lifecycle. Remote definitions are never written to `BackendRegistry`.

Proxy templates declare `proxy.backend: <backend-instance-id-or-alias>`. During template loading, Forge resolves that
value through the catalog, stores the canonical backend instance id on `ProxyConfig.backend`, derives any local
`BackendDependency` from backend lifecycle metadata, and resolves remote provider `base_url` from the backend endpoint
shape. A `runtime_native` backend instance cannot back a proxy: template loading rejects a `proxy.backend` pointing at
one, because a key-authenticated proxy injects its own bearer key and so cannot present the backend's runtime-owned
subscription credential (the "no key-auth proxy support for subscriptions" boundary -- the limit is the key-auth
transport, not the backend). Shipped local templates no longer carry inline `backend_dependency`; OpenRouter and
Anthropic passthrough templates no longer carry inline provider `base_url`. Remote LiteLLM templates resolve
`LITELLM_BASE_URL` through the same connection-value path used by credentials. OpenRouter templates resolve
`OPENROUTER_BASE_URL` the same way, defaulting to `https://openrouter.ai/api/v1` when no override is configured.

The copied runtime `proxy.yaml` remains user-owned and accepts unknown backend ids for forward compatibility when they
use canonical identifier syntax. Canonical ids start with a lowercase letter or digit and contain only lowercase
letters, digits, `.`, `_`, or `-`; malformed spellings fail schema validation with `proxy.backend` named. A canonical
but unknown id remains readable, warns once at the running proxy boundary, and fails capability gates safely.

`TEMPLATE_ENV_VARS` remains as a compatibility map for existing auth callers, but it is generated from
`ModelSource.credential_ids` and backend endpoint connection values. Template `backend_dependency.required_env_vars`,
`credentials_for_template()`, sidecar secrets, and proxy preflight therefore derive from the same catalog-backed source
of truth. Credential metadata itself lives in dependency-light `src/forge/core/credential_registry.py`; template-aware
helpers stay in `src/forge/core/auth/capabilities.py`, avoiding an auth/template/catalog import cycle.

`forge model backend` is the operator view over this catalog. `forge model backend list` reads the static backend
instances plus the local managed-process registry and reports backend kind, endpoint shape, required credentials,
per-variable provenance, offline auth/health status, and any matching local `ManagedBackendProcess`. The local LiteLLM
backend instances share one adapter/port (`litellm` on `4000`), so a single managed process can back several backend
instances at once; `forge model backend list` marks such a process `(shared)` and `--json` carries
`managed_process.shared_with` as sibling backend instance ids. The command stays offline for remote backend instances:
configured remotes show as `unprobed` until an operator runs `forge model backend test-auth <backend>`, which resolves
the same credentials and performs the backend's reachability/auth probe without echoing secret values. A
`runtime_native` backend instance carries no Forge credential, so `list` reports its auth as `runtime_native` and health
as `runtime-owned`, and `test-auth` skips the probe with a pointer to `forge runtime preflight codex` instead of
reporting a credential failure. `forge model backend show <backend-or-process>` renders backend details and local
managed-process state when a backend has lifecycle, while a process id such as `litellm-4000` renders a registry-only
managed-process view. `start` stays config-oriented: it accepts local backend instance ids or adapter operands with
`--port`. `stop` is process-oriented: it accepts managed process ids such as `litellm-4000`, or `--all` for every
registered local managed process; local backend ids and bare adapters are rejected with a process-id recovery tip, and
remote backend operands keep the intentional no-lifecycle capability error. Local LiteLLM processes lead the detached
process group created at startup, so failed startup health kills the complete group and stop signals the complete group
rather than only the leader. The registry row is removed only after the adapter reports successful teardown;
authorization or other signal failures leave the row intact for an operator retry. `create` and `delete` remain local
adapter/config operations because built-in remote backend instances are not user-created durable state.
`delete <adapter>` may stop matching managed processes before removing the config, but any required stop failure retains
the config, omits the success claim, and exits nonzero. `delete <adapter> --port <port>` is no longer a managed-process
spelling.

### A.3 Confusion traps / anti-patterns (§3.6.6)

| Anti-pattern                            | Why it fails                                                                        |
| --------------------------------------- | ----------------------------------------------------------------------------------- |
| "Session changes routing"               | Proxy cannot apply per-session routing without a stable session ID in requests.     |
| "Global config changes tier->model"     | Tier->model mapping is defined by proxy templates/proxies only.                     |
| "Proxy overlay in ~/.forge/config.yaml" | Wrong location. Per-proxy overlays belong under `~/.forge/proxies/<id>/proxy.yaml`. |

YAML config ignores `null` (no-op); session overrides (JSON) use `null` to clear fields. Do NOT share override
implementations.

### A.4 Runtime truth vs files (§3.6.7)

Status line should read live proxy truth when available; clearly label file fallbacks (see design.md §3.7).

### A.5 Model catalog (§3.6.8)

The model catalog is **authoritative internal data**:

- Location: `src/forge/core/data/model_catalog.yaml`
- Defines: intrinsic model capabilities, context windows, aliases, and per-family defaults
- **NOT a user edit surface**

GPT-6 Astra is the OpenAI Sonnet/Opus default and GPT workflow worker. GPT-5.4 Mini remains the general Haiku default;
Codex templates retain their coding Sonnet model. Astra and the explicit GPT-6.1 Sol alternative require reasoning
(`low` through `max`) and reject sampling overrides. `sol` and `gpt-sol` select 6.1. Both use Responses on LiteLLM
routes; the translated builder filters sampling by catalog capabilities and effort.

Explicit GPT-6 Sol/Luna pins retain native Responses and OpenRouter routes. Their sampling overrides require `none`
reasoning (`sampling_requires_no_reasoning`). Proxy/template validation requires explicit `reasoning_effort: none` for
temperature overrides; alternatives also need request-time filtering because tier defaults can differ. Native reasoning
with tools requires Responses. The three GPT-6 Pro entries have only OpenRouter routes: native OpenAI exposes Pro as a
reasoning mode.

Proxy/backend snapshots remain user-owned; upgrades preserve translated tier selections. Passthrough forwards the
client's model. Context-estimator model pins apply only to translated Messages routes, including Responses-capable
proxies; Anthropic passthrough and unknown wire shapes receive no pins.

Claude Opus 5.5 is the Anthropic/OpenRouter Opus default, stable `claude-opus` worker, and direct alias target; explicit
Opus 5 pins remain selectable. It uses always-on adaptive thinking at `medium` effort. OpenRouter uses
`anthropic/claude-opus-5.5`; native Anthropic uses `claude-opus-5-5`.

Claude Sonnet 5.5 is the Anthropic/OpenRouter Sonnet default. The `claude-sonnet` workflow worker and direct aliases
select `claude-sonnet-5-5`; explicit Sonnet 5 pins and the `claude-sonnet-5` worker remain selectable. OpenRouter uses
`anthropic/claude-sonnet-5.5`. Sonnet 5.5 defaults to `high` adaptive effort. Both Claude 5.5 models declare
`supports_forced_tool_choice: false`; translated conversion validates the resolved model before dispatch and returns
HTTP 400 for `any` or named choices, directing callers to `auto`/`none`. Native `between_tools` turns off up-front
thinking at `low`, `medium`, or `high`; `disabled` and manual budgets are invalid. Passthrough preserves this mode and
signed history. Translated routes approximate `between_tools` with their lowest supported effort. Config and passthrough
override validation reject manual budgets for every catalog model whose thinking modes exclude `enabled`. The shared
translated request builder removes unsupported sampling fields after merging provider extras, using the intrinsic
catalog even when gateway metadata does not yet recognize the model.

LiteLLM 1.102 packages Astra and Gemini 3.8 Flash metadata. Bundled GPT-6.1 Sol, GPT-6 Sol/Luna, and Claude 5.5
deployments supply capability and token/cache pricing in `model_info`. Sol/Luna metadata covers the above-272K premium;
6.1 Sol cache reads cost 5% of uncached input. Boundary tests require removing overrides when packaged support arrives.
Pricing belongs to backend configuration, outside the intrinsic catalog. Sonnet 5.5's `thinking_always_on: false`
prevents LiteLLM from silently deleting invalid `disabled` requests and enabling adaptive thinking; native validation
rejects them and directs callers to `between_tools`.

The model route catalog is separate **authoritative operational data**:

- Location: `src/forge/core/data/model_routes.yaml`
- Owner: `forge.core.models.model_routes`
- Defines: ordered direct runtime or proxy source/template/provider-model references for every normalized intrinsic
  model
- Source credentials, endpoint/lifecycle facts, and template ownership remain in `forge.backend.sources`; proxy tier
  maps remain in template/proxy configuration
- **NOT a user edit surface**

The `codex-responses-local` GPT candidate is intentional shared-route compatibility. It preserves the pre-catalog
workflow order and supplies an OpenAI-key local route for interactive Claude selection. Route evidence records the
configured Responses capability while the Claude request itself uses the translated Messages ingress.

`load_model_route_catalog()` reads the packaged resource, enforces exact schema fields, canonical model coverage,
candidate uniqueness, catalog-listed provider refs, and direct-first Claude compatibility, then validates
source/template ownership through the model-source catalog. The frozen result is cached; tests use
`clear_model_route_catalog_cache()` for explicit reloads. The loader does not import session lifecycle or workflow
callers.

`normalize_model_route_request()` returns the canonical request, base route key, Claude tier, and optional Claude Code
`[1m]` transport modifier. Canonical `*-1m` models and `[1m]` spellings share the base candidate list. Catalog-listed
OpenRouter dot-form Claude 4.6 aliases retain their existing 1M normalization; corresponding hyphen forms retain base
normalization.

**Workflow model specs** (`src/forge/review/models.py`):

```python
ModelSpec(name, model_id, family, description,
          prompt=None, prompt_mode="override", worker_id=None, runtime="claude_code")
```

`model_id` is Forge-canonical (for example, `gpt-6-astra`, not a provider slug), and `family` is the model's intrinsic
family. A spec owns worker identity, description, prompt, and runtime only. `derive_model_routes()` normalizes
`model_id`, reads the shared route catalog's already ordered candidates, and combines them with static template/source
metadata to produce `ModelRoute` values. It does not scan or mutate the proxy registry. Runtime-native workers such as
Codex bypass the catalog deliberately.

Live workflow routing advisories compare provider model refs with both effective `runtime.tier_mappings` and
`runtime.model_alternatives` from the proxy's `GET /` response.

### A.10 System prompt addendums (non-Anthropic proxy routing)

Non-Anthropic proxy sessions may inject a catalog-selected `--append-system-prompt-file` that teaches valid minimal tool
calls and prefers dedicated tools over shell substitutes (Gemini uses stronger Bash guidance). The
`system_prompt_addendum` catalog field points into `src/forge/core/data/`; `forge.session.addendum` resolves and writes
it at session launch, never in the proxy request path. Unknown/unconfigured models fail open with no addendum, and
direct HTTP proxy use receives none.

---
