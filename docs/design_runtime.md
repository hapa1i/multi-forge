# Forge Runtime and Routing Design

Canonical proxy, backend, model-routing, shared-client, subprocess, and isolation contracts.

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

#### 3.6.12 Subprocess routing resolution (normative)

Forge subprocesses (workflow workers, semantic and team supervisors, memory writer) share `resolve_subprocess_routing()`
when they need Forge-owned transport selection. This replaced ad-hoc resolution paths that implemented different
fallback chains with different semantics. Intentional direct and runtime-native arms bypass the resolver.

**Resolution chain** (sources not supplied by a caller are skipped):

| Step | Source             | Behavior                                                                                        |
| ---- | ------------------ | ----------------------------------------------------------------------------------------------- |
| 1    | `explicit`         | Opaque base-URL override                                                                        |
| 2    | `explicit`         | Named CLI/config proxy; strict registration, reachability, and route compatibility              |
| 3    | `subprocess_proxy` | Ambient `FORGE_SUBPROCESS_PROXY`; strict, or host-injected sidecar URL/metadata                 |
| 4    | `preferred_proxy`  | Catalog hint (`ModelSpec.preferred_proxy`); soft -- skip if not running                         |
| 5    | `route_scan`       | Find any running proxy compatible with a derived `ModelRoute`                                   |
| 6    | `session_proxy`    | Inherited `ANTHROPIC_BASE_URL`; opaque URLs are accepted when the caller does not require route |
| 7    | `unresolved`       | No route found; callers decide fail-open vs fail-closed                                         |

`source="direct"` is produced by workflow routing (`review.routing`) for direct-only model specs (e.g., `claude-opus`
running `claude -p --bare`), not by the shared resolver. Workflow routing also produces `source="runtime_native"` for
the Codex worker; that source intentionally has no `ModelRoute` because Codex owns model selection and auth. More
generally, `route=None` can also mean unresolved or opaque/non-model-specific routing (e.g., explicit base URL), so
`source` and `base_url` distinguish the cases.

**Supervisor model scope:** When semantic-supervisor routing resolves to a proxy URL, it invokes
`claude -p --model opus` and clears inherited Claude model-pin env vars (`ANTHROPIC_MODEL`,
`ANTHROPIC_DEFAULT_*_MODEL`). This keeps executor/session `--model` pins local to the executor while allowing the
semantic supervisor to use the selected proxy's `opus` tier.

The team supervisor also clears inherited model pins whenever any source resolves a base URL, including explicit,
ambient, inherited, and sidecar-injected URLs. It deliberately does **not** pass `--model opus`: the resumed team
supervisor keeps its existing model posture instead of acquiring semantic-supervisor tier policy. `direct=True` skips
resolution, while a truly unresolved route dispatches direct; both retain inherited model pins.

**Team commitment boundary:** The team handler resolves routing before its `on_dispatch` callback. Explicit or ambient
named proxies are strict: missing, corrupt, or unreachable entries fail open by skipping the check before lane freeze or
dispatch-usage emission. This includes an ambient `FORGE_SUBPROCESS_PROXY` that is unregistered (previously silently
fell through to direct) and one that is registered but unreachable (previously failed after dispatch commitment).
Reachable ambient proxies, inherited `ANTHROPIC_BASE_URL`, and sidecar-injected URLs keep the same destination but are
now visible early enough for cost tracking and model-pin scrubbing. The team caller supplies no `ModelRoute`, so
`preferred_proxy` and `route_scan` are no-ops.

This chain applies to the supervisor's default `claude_code` lane. The `codex` lane arm (the supervisor's
`consumer_lanes` binding, epic consumer_lanes) bypasses it entirely: `codex exec` runs **direct** to OpenAI with no
Forge proxy. See [design_runtime.md §G](design_runtime.md#g-subprocess-routing-reference) for the consumer-lane layer.

**Fail behavior by subprocess type:**

| Subprocess          | On unresolved   | Rationale                                                        |
| ------------------- | --------------- | ---------------------------------------------------------------- |
| Workflows           | Fail closed     | User asked for this work; partial results worse than an error    |
| Semantic supervisor | Fail open       | Blocking the coding session is worse than skipping a check       |
| Team supervisor     | Dispatch direct | No configured route is a valid direct resumed-session posture    |
| Memory writer       | Fail open       | Async/best-effort; benefits future sessions, not the current one |

**Review worker preparation:** `review.worker_preparation` owns role/stance marker validation and fill, stable worker
IDs/labels, and `model:assignment` parsing. Commands retain domain types, routing/fan-out, and JSON schemas.

**Per-invocation routing plan:** Workflow commands resolve one frozen `WorkerRoutingPlan` for all workers at invocation
start. With Codex, it freezes one fresh cached readiness/auth/billing preflight; no workflow verb runs an inline doctor.
This prevents fan-out drift and keeps two-round consensus on one snapshot. Workflow JSON exposes decisions in
`resolved_models`: runtime, requested/actual model, provider, proxy, template, source, and selection state. Codex
entries report `resolved_model=null` and `model_selection="runtime_default"` because Forge neither pins nor observes the
exact model.

> **Routing reference details** — data type schemas (`ModelRoute`, `RoutingResult`, `WorkerRoutingPlan`), function
> signatures, route derivation ranking, and sidecar constraints are in
> [design_runtime.md §G](design_runtime.md#g-subprocess-routing-reference).

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
- reasoning-effort pin — **reuses** `tier_overrides.<tier>.reasoning_effort` as a floor (not a new key), in Anthropic
  `thinking.budget_tokens` units. If the pin changes `thinking`, Forge removes `temperature`, `top_p`, and `top_k` from
  that request because Anthropic rejects the combination; a no-op pin leaves those fields unchanged.

**Mutation-safety invariant (normative):** override fingerprints the `messages` list (SHA256) before and after apply and
raises (`RuntimeError`, fail-closed, no forward) if it changed. Override never writes `messages[0..n-1]`, so signed
reasoning in historical turns is untouched. Mutation records carry hashes/lengths/budgets and removed sampling key names
only, never sampling values.

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
| `codex-responses-local`      | Raw Responses passthrough for `forge codex start --proxy`      |
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
| `codex-responses-local`   | local  | `litellm_local`  | local LiteLLM backend on port `4000` | `openai-api`     | Codex `/v1/responses` passthrough; responses-ingress + provider-trace                           |
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
- Defines: model capabilities, context windows, provider mappings
- **NOT a user edit surface**

**Workflow model specs** (`src/forge/review/models.py`):

```python
ModelSpec(name, model_id, family, provider_refs, description,
         preferred_proxy=None, prompt=None, prompt_mode="override", worker_id=None)
```

Key fields: `model_id` is Forge-canonical (e.g., `gpt-5.5`, not `openai/gpt-5.5`). `family` is the model's native family
(e.g., `openai`, `anthropic`, `gemini`). `provider_refs` is ordered `(namespace, model_ref)` tuples declaring how to
reach the model via each provider. `preferred_proxy` is a soft catalog hint, overridable by `--proxy` or route scan.

### A.10 System prompt addendums (non-Anthropic proxy routing)

Non-Anthropic proxy sessions may inject a catalog-selected `--append-system-prompt-file` that teaches valid minimal tool
calls and prefers dedicated tools over shell substitutes (Gemini uses stronger Bash guidance). The
`system_prompt_addendum` catalog field points into `src/forge/core/data/`; `forge.session.addendum` resolves and writes
it at session launch, never in the proxy request path. Unknown/unconfigured models fail open with no addendum, and
direct HTTP proxy use receives none.

---

## G. Subprocess Routing Reference

Extracted from [design.md §3.6.12](design_runtime.md#3612-subprocess-routing-resolution-normative). Resolution chain
concept, fail-open/fail-closed semantics, and per-invocation routing plan remain in design.md.

**Consumer-lane layering (epic consumer_lanes).** Forge resolves each consumer's `(runtime, backend, model)` lane and
dispatches by runtime (`forge.core.lanes`; `resolve_lane` is pure). Persisted `consumer_lanes` bindings cover semantic
supervisor, shadow-curation, memory-writer, and team-supervisor. Policy-check resolves `SUPERVISOR_CONSUMER` and
**injects** its `LaneRecord` into `run_supervisor_check` for the two `_dispatch_supervisor` arms:

- **`claude_code`** (default lane) -- the byte-identical `claude -p` path; transport (direct vs proxy / `base_url`) is
  still derived inside the arm by `resolve_subprocess_routing` (the chain below). The lane layer never touches the proxy
  registry.
- **`codex`** -- the non-Claude supervisor lane, selected by the supervisor's `consumer_lanes` binding (a declared
  `SUPERVISOR_CONSUMER` candidate on the `chatgpt` subscription backend, `reachable_via=("codex",)`, T2). The
  policy-check hook reads the binding (`read_bound_lane`, confirmed-first then intent) and **injects** the resolved lane
  into `run_supervisor_check`, which never reads the store. Runs headless `codex exec` **direct** to OpenAI (no proxy,
  read-only sandbox), **blind/transfer-fed** -- Codex has no `--resume`, so the approved plan must reach it via the
  plan-override preamble. Preflight is **cached, never probed in the hook**: `codex doctor` is ~20s and
  `run_doctor=False` cannot see `codex_store` (ChatGPT-login) auth, so the arm reads the `run_doctor=True` preflight
  that `forge runtime preflight codex` wrote to `core/runtime/codex_preflight_cache.py` (invalidated by codex-binary +
  `$CODEX_HOME/auth.json` mtime + TTL). The invoker auto-emits the sole `emit_codex_usage`, and the arm passes
  `Attribution.operation=None` so the shared invoker **suppresses** its upstream-outcome row -- the engine's
  `policy.evaluate` is the arm's only upstream row (parity with the claude arm; T5/WS1 resolved T4's documented
  double-count). Every failure (bad override, cold/stale/unready cache, plan-absent, or any setup exception) **fails
  open** -- the supervisor's contract (design_workflows §1.2).

For supervisor, shadow-curation, and memory-writer, `runtime_id` selects the Claude Code or Codex arm. Codex
`backend_id`/`model` are placement metadata: Codex selects its model; preflight auth determines billing. Claude Code
`backend_id` drives `resolve_billing_mode` (for example, `claude-max`). Team-supervisor lacks a Codex candidate and is
billing-only. T1b replaced `supervisor_runtime` with a persisted consumer-lane `LaneRecord`. The **first policy check**
for a registered supervisor freezes an explicit `intent.consumer_lanes` override into `confirmed.consumer_lanes` -- a
commitment, not a dispatch. Default lanes never freeze and remain re-pinnable. `--supervisor-runtime` and
`policy supervisor set <target> --runtime` set the override; raw `set` is rejected. Re-pinning is an idempotent no-op;
`policy supervisor remove` clears intent and confirmed.

**Aux consumers on `claude-max` (T6a).** All three aux consumers use the same machinery. A `claude-max` binding keeps
the default `claude_code` runtime, changing the **billing label, not dispatch**. Shadow-curation and memory-writer also
have dispatch-changing Codex lanes (T6b/T6c); team-supervisor is billing-only.
`forge session lane set --consumer <id> --backend claude-max` writes `intent`; `on_dispatch` freezes it into `confirmed`
on Claude dispatch, or `codex exec` for shadow-curation and memory-writer. `persist_lane_freeze` is best-effort: lock
failure never blocks a run; skipped/throttled runs never freeze. Under lock, it uses the supervisor's
`read_bound_lane(m) == dispatched_lane` guard. Unlike the supervisor's first-check commitment, aux consumers freeze only
on dispatch; they lack a registration commitment point. `read_bound_backend_id` yields `claude-max`; a **keyless +
direct** run is `subscription_quota`, a resolvable key wins as `api`, and a proxied run is `unknown`. Billing works from
`intent` alone (confirmed-first **then intent**); freezing adds immutability and a stable observable binding, not the
label.

**Shadow-curation codex arm (T6b).** This clean mirror-T4 consumer (blind, read-only, stdout-is-output) allows
`Lane(codex, chatgpt, gpt-5-codex)`. The curate CLI passes its `LaneRecord` to `run_shadow_curation`, which validates
`LaneRecord -> Lane -> resolve_lane`; invalid explicit bindings fail loud before any wrong-arm dispatch. Runtime
branches into `_dispatch_codex_shadow_curation` before Claude `on_dispatch`; the `claude_code` path stays
byte-identical. The arm mirrors `_dispatch_codex_supervisor` -- cached preflight, read-only direct `codex exec`,
self-contained prompt -- but its contract differs on three axes:

- **Degrade: fail-loud, not fail-open.** User-invoked, so a cold/unready preflight or a failed turn returns
  `CurationResult(success=False)` carrying a refresh hint surfaced by the CLI (human via `print_error` + `--json`, the
  new `CurationResult.error`); it never silently falls back to claude.
- **Upstream row: `operation="memory.shadow_curation"`, not `None`.** Curation has no engine `policy.evaluate` row, so
  the invoker's auto `record_upstream_operation` is its only upstream outcome and must match the claude path -- the
  opposite of the supervisor arm, which suppresses that row.
- **Freeze past the preflight skip-gate.** `on_dispatch` fires only after preflight passes: a cold preflight that never
  spawns codex does not freeze; a turn that spawns then fails still freezes (claude-arm parity). `runtime_is_error` is
  folded (the invoker's `success` is returncode-only) so an exit-0-but-failed turn fails loud instead of persisting an
  empty report.

**Memory-writer codex arm (T6c).** Its `Lane(codex, chatgpt, gpt-5-codex)` can **write the repo** in augment mode.
`forge memory-writer run` passes the bound `LaneRecord` to `run_memory_writer`, which resolves
`LaneRecord -> Lane -> resolve_lane` **before** the Claude-availability check, then branches into
`_dispatch_codex_memory_writer` ahead of Claude `on_dispatch`. It differs from T6b in two ways:

- **Degrade: best-effort async, not fail-loud.** The writer runs detached from the work queue (stdout -> DEVNULL), so
  every failure logs + records an outcome + `return False` (never raises, never fails-open). Resolving the runtime
  before the `is_claude_available()` gate -- which now guards only the claude arm -- lets a codex-bound writer run when
  claude is absent (Finding 2).
- **Per-mode sandbox; no permission scan (D4).** `review-only` -> `read-only`; `augment` -> `workspace-write`, editing
  the designated docs in place. A Phase 0 probe confirmed codex auto-approves in-project writes and auto-rejects
  out-of-project ones -- but a rejection exits 0 with `is_error=False` (it rides `turn.completed`), so
  `runtime_is_error` does not catch it. Immaterial: an in-project doc update (`cwd=forge_root`) never hits that path, so
  the Claude `_stdout_indicates_permission_denied` scan is not ported; real provider/turn failures still fold via
  `runtime_is_error`.

Outcome recording matches T6b (Finding 1): the invoker's `_emit_codex` owns the single upstream row for a spawned run
(failure-biased, so a success writes none under default volume -- claude parity); the arm records manually only on a
no-spawn preflight/setup failure.

Team-supervisor (plan-blind without snapshot machinery) stays billing-only for now, pending a context-model change --
its shape diverges from the mirror-T4 template. (Memory-writer's divergent shape shipped as T6c, above.)

**Observability (T5/T1b).** `forge policy supervisor status` displays the full `(runtime, backend, model)` lane via
`resolve_supervisor_lane(read_bound_lane(...))`: the **frozen `confirmed` binding** when present (a real dispatch
record, T1b), else the `intent` override or the default claude lane. `runtime_id` selects the arm; the codex
`model=gpt-5-codex` stays nominal (codex picks its own model). Status revalidates `LaneRecord -> Lane` on every call and
**never rewrites** the manifest, so a frozen lane whose catalog entry was later removed prints `Lane: not executable`
rather than crashing or silently falling back to the default. `forge telemetry activity` shows the per-call
`runtime`/`billing_mode` each command ran on (`mixed` when a command's events disagree); the usage ledger carries no
catalog backend id, so the full lane shows only on supervisor status. The team event tagger emits `team-tagger` usage
events through `.complete()`, which retains the token counts that `.ask()` discarded.

**Subscription-exhaustion degrade (T7).** A supervisor check that exhausts its bound codex subscription
(`failure_type="subscription_exhausted"`, classified in `run_supervisor_check` from the codex JSONL message -- no
structured status survives the `codex exec` boundary) persists a sticky degrade overlay in
`confirmed.policy.policy_states["forge.supervisor_lane_degrade"]`, deliberately *separate* from the immutable
`consumer_lanes` binding. The write rides the existing freeze lock behind the same
`read_bound_lane(m) == dispatched_lane` stale-write guard; the read side (`register_supervisor_and_restore`) injects
`lane_record=None` when degraded, so later checks dispatch the default claude lane while the frozen codex binding stays
observable (`lane show` and `supervisor status` annotate it `degraded`, `from`/`to` audit-only -- routing never trusts
the stored `to_lane`). Reset follows the *binding*, not the command name: `supervisor remove` and a re-pin
(`set --runtime/--backend`, `session lane set --consumer supervisor`) clear it; `session lane clear` does not (the
frozen binding still dispatches codex); a fresh process resume (`SessionStart source in {startup, resume}`) clears it so
a refilled weekly quota is retried, while `compact`/`clear` preserve it (mid-sitting -- re-arming codex would just
re-exhaust). The degrade emits exactly one upstream `policy.lane_degraded` outcome (`command=supervisor`,
`reason_code=subscription_exhausted`, from/to lane in `message`), read by `forge telemetry activity` -- not a
`UsageEvent`. Fail-open throughout (design_workflows §1.2): a degrade-path error still degrades the check to allow, and
a drifted default catalog still degrades (route by `None`, `to_lane` null).

### G.1 Core types (from `core.reactive.routing`)

```python
RoutingSource = Literal[
    "explicit",
    "subprocess_proxy",
    "preferred_proxy",
    "route_scan",
    "session_proxy",
    "direct",
    "runtime_native",
    "unresolved",
]

@dataclass(frozen=True)
class ModelRoute:
    provider: str
    credential: str
    family: str
    template_id: str | None
    template_family: str | None
    model_ref: str

@dataclass(frozen=True)
class RoutingResult:
    base_url: str | None
    proxy_id: str | None
    template: str | None
    source: RoutingSource
    route: ModelRoute | None
    credential: str | None
    warning: str | None = None
```

`direct` has a concrete route. `runtime_native` deliberately has none because the runtime owns selection and auth (the
`codex` worker). `unresolved` means failure. A route-null shared-resolver result can still be successful opaque base-URL
passthrough; `source` and `base_url` distinguish it.

### G.2 Workflow types (from `review.routing`)

```python
@dataclass(frozen=True)
class WorkerRoutingPlan:
    routes: tuple[RoutingResult, ...]
    resolved_at: str
    via_override: str | None
    codex_preflight: CodexPreflight | None = None
```

Workflow plans accept `route=None` only for `runtime_native`; every other route-null entry fails closed. This does not
narrow the shared resolver's opaque `require_route=False` successes.

### G.3 Key function signatures

```python
def resolve_subprocess_routing(
    explicit_base_url: str | None = None,
    explicit_proxy: str | None = None,
    preferred_proxy: str | None = None,
    routes: tuple[ModelRoute, ...] = (),
    *,
    require_route: bool = False,
    use_environment: bool = True,
    advisory_check: bool = False,
) -> RoutingResult:
    """Unified routing resolution for all Forge subprocesses.

    Walks the 6-step chain. Callers decide fail-open vs fail-closed
    based on source and their use case.
    """

def derive_model_routes(spec: RoutableSpec) -> tuple[ModelRoute, ...]:
    """Expand compact model metadata into concrete routing options.

    Combines ModelSpec fields with template/auth metadata. Does not
    inspect the proxy registry or check running state.
    """

def resolve_invocation_routing(
    specs: Sequence[Any],
    via: str | None = None,
) -> WorkerRoutingPlan:
    """Resolve routing for all workers at invocation start.

    Fail-closed: raises if any worker has no route.
    """

def resolve_model_flag(route: ModelRoute) -> str | None:
    """Return --model flag for a routed workflow worker.

    Proxied workers: route.model_ref. Direct workers: None (use env pins).
    """
```

### G.4 Route derivation ranking

`derive_model_routes()` produces routes in deterministic order:

1. preferred_proxy match first (if it matches a derived route)
2. provider_refs order (from `ModelSpec.provider_refs`)
3. Native-family templates before OpenRouter passthrough cross-family templates
4. Alphabetical template name tiebreaker

Registry scan then ranks matched proxies:

1. Route preference order (from `derive_model_routes()` ranking above)
2. Alphabetical proxy_id as tiebreaker

### G.5 Sidecar constraints

In sidecar mode (`~/.forge` not mounted), registry-dependent steps are unavailable:

| Step                | Host mode | Sidecar mode                                                   |
| ------------------- | --------- | -------------------------------------------------------------- |
| `explicit_base_url` | Opaque    | Works (returned before sidecar checks; opaque URL passthrough) |
| `explicit_proxy`    | Registry  | Works only via injected env metadata                           |
| `subprocess_proxy`  | Registry  | Works via `FORGE_SUBPROCESS_BASE_URL`/`PROXY_ID`/`TEMPLATE`    |
| `preferred_proxy`   | Registry  | No-op (registry unavailable)                                   |
| `route_scan`        | Registry  | No-op (registry unavailable)                                   |
| `session_proxy`     | Env       | Works (`ANTHROPIC_BASE_URL` inherited from host)               |

Proxy IDs are resolved on the host before entering the sidecar. If a user supplies a plain proxy ID inside a sidecar
with no injected metadata, Forge fails with an actionable error suggesting `--subprocess-proxy` at session start or
running the workflow on the host.

---
