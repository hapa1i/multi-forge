# Design Appendix (Reference Details)

**Companion to [design.md](design.md).** Precision reference material extracted to keep the main doc focused on
architectural narrative. Each section notes its origin for cross-referencing.

---

## A. Configuration Reference

Extracted from [design.md §3.6](design.md#36-configuration-system). Core definitions, ownership invariants, and proxy
lifecycle UX remain in design.md. This section covers detailed schemas, templates, and operational guidance.

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

> **Implementation note:** Internally, config is layered (base defaults -> proxy defaults -> template overlay -> proxy
> overlay -> env). Users only edit the proxy overlay. `validate_user_config()` enforces this by rejecting proxy-owned
> and template-owned keys in `~/.forge/config.yaml`.

**Note:** Provider/base_url/template are set when the proxy is created. The per-proxy overlay only tunes defaults
**within** that proxy's routing scope.

### A.2 Proxy templates vs user-defined proxies (§3.6.5)

**Proxy templates** (internal, pre-canned configurations):

| Template                  | Use case                                    |
| ------------------------- | ------------------------------------------- |
| `openrouter-anthropic`    | Claude models via OpenRouter (direct)       |
| `openrouter-deepseek`     | DeepSeek models via OpenRouter (direct)     |
| `openrouter-glm`          | GLM / Z.ai models via OpenRouter (direct)   |
| `openrouter-kimi`         | Kimi models via OpenRouter (direct)         |
| `openrouter-minimax`      | MiniMax models via OpenRouter (direct)      |
| `openrouter-openai`       | GPT models via OpenRouter (direct)          |
| `openrouter-qwen`         | Qwen models via OpenRouter (direct)         |
| `openrouter-gemini`       | Gemini models via OpenRouter (direct)       |
| `openrouter-openai-codex` | OpenAI Codex via OpenRouter (direct)        |
| `openrouter-gemini-flash` | Gemini Flash via OpenRouter (cheap, direct) |
| `litellm-openai`          | OpenAI models via remote/shared LiteLLM     |
| `litellm-gemini`          | Gemini models via remote/shared LiteLLM     |
| `litellm-anthropic`       | Anthropic models via remote/shared LiteLLM  |
| `litellm-gemini-local`    | Local LiteLLM + Gemini API key              |
| `litellm-anthropic-local` | Local LiteLLM + Anthropic API key           |

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

### A.2.1 Model source catalog (§3.6.5 / unified backend Phase 1/2)

Forge now has a built-in, code-level model-source catalog in `forge.backend.sources`. It is a static definition layer
for the upstream model source a proxy or direct runtime reaches; it is **not** user-authored durable state and it is
distinct from both proxy templates and runtime backend instances.

| Layer                    | Owner / Location                             | Unit                                                                                  |
| ------------------------ | -------------------------------------------- | ------------------------------------------------------------------------------------- |
| Model-source catalog     | `forge.backend.sources`                      | Static source definition: id, kind, endpoint shape, credentials, provider, capability |
| Proxy templates          | `src/forge/config/defaults/templates/*.yaml` | Operational routing profiles that declare `proxy.source`                              |
| Local backend config     | `~/.forge/backends/<adapter>/config.yaml`    | LiteLLM service config (`model_list` / routing), copied by `forge backend create`     |
| Runtime backend registry | `~/.forge/backends/index.json`               | PID/port/status rows for running local process instances only                         |

`ModelSource.id` is the canonical catalog id. Local source ids intentionally live in a different value-space from
runtime instance ids: for example, `litellm-gemini-local` is a source id, while `litellm-4000` remains a
`BackendInstance.backend_id`. Downstream telemetry uses `backend_id` for source attribution and writes the catalog
source id rather than the runtime instance id.

Source definitions have:

- `id`: stable catalog id, lowercase letters/digits plus `-`, `_`, or `.`
- `kind`: `local` or `remote`
- `provider`: `ProviderType` from dependency-light `forge.core.provider_types` (`litellm_remote`, `litellm_local`,
  `anthropic`, `openrouter`)
- `endpoint`: one of `literal_url`, `connection_value`, or `local_backend`
- `credential_ids`: credential registry names such as `openrouter`, `litellm-remote`, `anthropic-api`, `openai-api`, or
  `gemini-api`
- `capabilities`: currently includes auth-probe, provider-trace eligibility, and provider-user-grouping capability
- `local_lifecycle`: local-only refinement with adapter and default port; required env vars are derived from
  `credential_ids`; remote sources never set it
- `template_names`: current proxy templates that resolve to the canonical source id during template loading

The shipped v1 catalog includes:

| Source id                 | Kind   | Provider         | Endpoint shape                       | Credentials      | Notes                                     |
| ------------------------- | ------ | ---------------- | ------------------------------------ | ---------------- | ----------------------------------------- |
| `openrouter`              | remote | `openrouter`     | `OPENROUTER_BASE_URL` + default URL  | `openrouter`     | Provider-trace and user-group capable     |
| `litellm-remote`          | remote | `litellm_remote` | `LITELLM_BASE_URL`                   | `litellm-remote` | Aliases remote LiteLLM templates          |
| `anthropic-passthrough`   | remote | `anthropic`      | `https://api.anthropic.com`          | `anthropic-api`  | Proxy-template source, no lifecycle       |
| `anthropic-direct`        | remote | `anthropic`      | `https://api.anthropic.com`          | `anthropic-api`  | Direct-runtime attribution source         |
| `litellm-gemini-local`    | local  | `litellm_local`  | local LiteLLM backend on port `4000` | `gemini-api`     | Also aliases `litellm-gemini-flash-local` |
| `litellm-openai-local`    | local  | `litellm_local`  | local LiteLLM backend on port `4000` | `openai-api`     | Also aliases `litellm-openai-codex-local` |
| `litellm-anthropic-local` | local  | `litellm_local`  | local LiteLLM backend on port `4000` | `anthropic-api`  | Local Anthropic via LiteLLM               |
| `litellm-gemini-test`     | local  | `litellm_local`  | local LiteLLM backend on port `4001` | `gemini-api`     | Internal integration-test dependency      |

Catalog validation rejects duplicate source ids or aliases, unknown `kind`/`provider` values, missing or unknown
credentials, malformed literal URLs, malformed connection-value env var names, remote lifecycle declarations, and local
sources without lifecycle. Remote definitions are never written to `BackendRegistry`.

Proxy templates declare `proxy.source: <source-id-or-alias>`. During template loading, Forge resolves that value through
the catalog, stores the canonical source id on `ProxyConfig.source`, derives any local `BackendDependency` from the
source lifecycle, and resolves remote provider `base_url` from the source endpoint shape. Shipped local templates no
longer carry inline `backend_dependency`; OpenRouter and Anthropic passthrough templates no longer carry inline provider
`base_url`. Remote LiteLLM templates resolve `LITELLM_BASE_URL` through the same connection-value path used by
credentials. OpenRouter templates resolve `OPENROUTER_BASE_URL` the same way, defaulting to
`https://openrouter.ai/api/v1` when no override is configured.

`TEMPLATE_ENV_VARS` remains as a compatibility map for existing auth callers, but it is generated from
`ModelSource.credential_ids` and source endpoint connection values. Template `backend_dependency.required_env_vars`,
`credentials_for_template()`, sidecar secrets, and proxy preflight therefore derive from the same catalog-backed source
of truth. Credential metadata itself lives in dependency-light `src/forge/core/credential_registry.py`; template-aware
helpers stay in `src/forge/core/auth/capabilities.py`, avoiding an auth/template/source import cycle.

`forge backend` is the operator view over this catalog. `forge backend list` reads the static sources plus the local
runtime registry and reports source kind, endpoint shape, required credentials, per-variable provenance, offline
auth/health status, and any matching local `BackendInstance`. The local LiteLLM sources share one adapter/port
(`litellm` on `4000`), so a single runtime instance can back several sources at once; `forge backend list` marks such an
instance `(shared)` and `--json` carries a `runtime_instance.shared_with` list of the sibling source ids. The command
stays offline for remote sources: configured remote sources show as `unprobed` until an operator runs
`forge backend test-auth <source-id>`, which resolves the same credentials and performs the source's reachability/auth
probe without echoing secret values. `forge backend show <source-id>` renders catalog details and local runtime state
when a source has lifecycle. `start` and `stop` accept local source ids or legacy adapter operands; remote source
operands return an intentional no-lifecycle capability error. `create` and `delete` remain local adapter/config
operations because built-in remote sources are not user-created durable state.

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

### A.6 Credentials and Connection Values (§3.6.9)

Credentials resolve from environment variables first (`.env`, shell exports), then fall back to the Forge credential
store (`~/.forge/credentials.yaml`, managed by `forge auth login`). Env vars override stored credentials unless
`auth_ignore_env` is set in `~/.forge/config.yaml`.

Six atomic credentials (defined in `forge.core.auth.capabilities`):

| Credential       | Env var(s)                                              | Capabilities                                                                    |
| ---------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `openrouter`     | `OPENROUTER_API_KEY` (+ optional `OPENROUTER_BASE_URL`) | All `openrouter-*` proxies, OSS workflow models                                 |
| `anthropic-api`  | `ANTHROPIC_API_KEY`                                     | Forge subprocesses, `litellm-anthropic-local` + `anthropic-passthrough` proxies |
| `openai-api`     | `OPENAI_API_KEY`                                        | `litellm-openai-local` proxy                                                    |
| `gemini-api`     | `GEMINI_API_KEY`                                        | `litellm-gemini-local` proxy                                                    |
| `codex-api`      | `CODEX_API_KEY`                                         | Native Codex headless runs (`codex exec`); not `OPENAI_API_KEY` / ChatGPT login |
| `litellm-remote` | `LITELLM_API_KEY` + `LITELLM_BASE_URL`                  | All remote `litellm-*` proxy templates                                          |

`auth_ignore_env: true` in runtime config (`~/.forge/config.yaml`) skips all env vars for credential resolution. Both
the sync path (`resolve_env_or_credential`) and async path (`CredentialManager` via `EnvSecretsProvider`) respect the
flag. `build_claude_env()` hydrates credential-file values into subprocess env dicts when the flag is active — this
changes the *source* of the resolved key (file vs env) for **both** interactive and headless launches; it does **not**
keep a key out of the interactive session. Withholding a key from interactive Claude is the separate
`interactive_anthropic_api_key: omit` control (§A.7), not `auth_ignore_env`.

**Rule:** Credential storage holds secrets and connection values (e.g., `LITELLM_BASE_URL`). Connection values are a
convenience fallback for bootstrapping proxy creation (`forge proxy create`). Once `proxy.yaml` exists, proxy-owned
routing is authoritative. Do NOT store other routing configuration in credential storage.

**Credential registry and capability helpers**:

- Credential data: `src/forge/core/credential_registry.py`
- Template-aware helpers: `src/forge/core/auth/capabilities.py`

Single source of truth for credential metadata. Key types and functions:

```python
EnvVar(name, required=True, secret=True, connection_value=False, default_value=None)
Credential(name, env_vars, unlocks_features, signup_url, note, not_needed_for)

credentials_for_template(template: str) -> list[Credential]
format_missing_credential_error(credential, *, missing_vars, template=None,
    context=None, extra_hint=None, profile=None, env_ignored=False) -> str
```

`TEMPLATE_ENV_VARS` is generated from the model-source catalog for template-facing compatibility. It maps each template
to required credential env vars and required connection-value env vars such as `LITELLM_BASE_URL`.
`credentials_for_template()` bridges that generated map to `CREDENTIALS` (credential → metadata) via reverse lookup.
`format_missing_credential_error()` produces actionable messages with signup URLs, `forge auth login` commands, and
`not_needed_for` disambiguation (rendered for credentials that define it: `anthropic-api` and `codex-api`).

### A.7 Runtime config (§3.6.10 -- `~/.forge/config.yaml`)

Global Forge runtime preferences. **Separate from `ForgeConfig`** -- the proxy imports `forge.config.config` as a
singleton; runtime preferences must not leak into routing. Runtime config lives in `forge.runtime_config`.

```yaml
proxy_mode: host              # host | sidecar
sidecar_image: forge-sidecar:latest
user_agent_claude_code_version: ""
context_limit: 200000
status_timeout: 2.0
memory_writer_timeout: 300
log_level: off               # off | debug | info | warning
interactive_anthropic_api_key: inherit   # inherit | omit
```

`interactive_anthropic_api_key: omit` strips `ANTHROPIC_API_KEY` from Forge-managed **interactive** `claude` launches
only (session start/resume/fork and `forge claude start`), so a subscription/OAuth session is not billed against a key
meant for other tools. Headless subprocesses (supervisor, memory writer, panel workers, `claude -p --bare`) keep normal
credential resolution. The omission is recorded as `confirmed.launch.api_key_source = omitted_by_config`. Host launches
finalize the key in `build_claude_env`'s interactive wrapper (after `extra_vars`); sidecar launches pass
`FORGE_OMIT_INTERACTIVE_KEY=1` so `entrypoint.sh` unsets the key for Claude *after* the in-container proxy captured its
upstream credential (so the proxy keeps upstream auth for every template).

- **Optional**: missing file = built-in defaults
- **Auto-created on first access**: `forge config show` seeds the file with documented defaults
- **Fail-open**: invalid YAML warns, returns defaults
- **Unknown keys**: warned, ignored (forward compatible)
- **CLI**: `forge config` (help), `forge config show [--raw]`, `forge config set`, `forge config edit`,
  `forge config reset`; `%config` (read-only) in-session

See [docs/end-user/config.md](end-user/config.md) for the full user guide.

### A.7a Claude settings preset (`~/.forge/claude.preset.json`)

User-editable JSON merged into Claude Code `settings.json` by `forge extension enable`.

```json
{
  "hooks": {
    "...": "forge hook ..."
  },
  "statusLine": {
    "type": "command",
    "command": "forge status-line",
    "padding": 0
  },
  "permissions": {
    "allow": ["Write", "Edit"]
  }
}
```

- **Auto-created on first access**: `forge claude preset` / `forge claude preset show`
- **Built-in defaults are intentionally minimal**: hooks, status line, and memory writer permissions
- **Merged keys only**: `hooks`, `statusLine`, `env`, and `permissions`
- **User customization surface**: usually permissions and extra env vars; hooks/status line only if intentionally
  overriding Forge defaults
- **Validation**: must be valid JSON object; corruption errors include recovery hints
- **CLI**: `forge claude preset` (show), `forge claude preset show [--raw]`, `forge claude preset edit`,
  `forge claude preset reset [--yes]`

See [docs/end-user/config.md](end-user/config.md) for the full user guide.

### A.8 Status line guidance (§3.6.11)

Status line reads Claude Code's stdin JSON plus two env-var-addressed sources:

| Source            | Address                                | What it provides                                                       | Availability          |
| ----------------- | -------------------------------------- | ---------------------------------------------------------------------- | --------------------- |
| Claude Code stdin | piped JSON                             | model, workspace, context_window, cost, rate_limits, session_id        | Always                |
| Session file      | `FORGE_SESSION`                        | Intent, overrides, confirmed facts                                     | Always (file)         |
| Proxy registry    | `ANTHROPIC_BASE_URL` -> reverse lookup | proxy_id, template, port                                               | Always (file)         |
| Proxy `GET /`     | `ANTHROPIC_BASE_URL` -> query          | tier mappings, context windows, metrics, intercept posture, spend caps | Only if proxy running |

**Information strategy:**

1. **Session identity**: Read `FORGE_SESSION` -> locate `.forge/sessions/<name>/forge.session.json`
2. **Proxy identity**: Reverse lookup `ANTHROPIC_BASE_URL` in `~/.forge/proxies/index.json`
3. **Runtime truth**: Query proxy `GET /` for tier mappings, context windows, metrics, intercept posture, and spend caps
   (may fail gracefully)

**On `session_id`:** Claude Code DOES pass `session_id` in the stdin JSON, but it is NOT used for session discovery —
only as the cache key for the throttled direct-mode cache-hit-rate. Session discovery still keys off `FORGE_SESSION`.

**No CWD fallback:** If `FORGE_SESSION` is not set, the status line shows no session information. It does not scan CWD
for `.forge/` directories.

**Configuration (`statusline:` in `~/.forge/config.yaml`).** A segment registry renders an ordered, user-selectable set
of fields. `statusline.segments` is the ordered allowlist (empty -> `DEFAULT_ORDER`, which reproduces the pre-config bar
byte-for-byte). Other keys: `cost_mode` (`auto|api|subscription`), `palette` (`default|earthy`), `glyphs`
(`ascii|unicode`), `cache_hit` (`auto|off`), `cache_hit_ttl`, `forge_cost_ttl` (`forge_cost` throttle window, seconds,
default 10, `>= 1`). `forge config set`/`edit` is the strict allowlist gate (rejects unknown segment names and bad
enums; the on-disk loader fails open per-subtree); the renderer drops unknown names and falls back to `DEFAULT_ORDER` if
a non-empty config resolves to nothing. The flat `show_rate_limits` key was removed (clean break) — `rate_limits` is now
an opt-in segment. Default-off segments: `rate_limits`, `cache_hit`, `supervisor`, `policy`, `audit`, `drift`,
`spend_cap`, `launch`, `forge_cost`. Full key/segment reference: `docs/end-user/config.md`.

**Billing-aware cost.** Billing mode is an explicit **declaration**, never inferred from a key. `cost_mode=api` shows
real `$`; `cost_mode=subscription` shows quota burn (dollars are a phantom on a subscription) — both the 5h and weekly
windows, `5h:N% · 7d:M%`, heat-mapped on the context gradient with the reset bound to the hotter window (`7d:52%↻1d`).
`cost_mode=auto` shows the quota when `rate_limits` is present, else hedges `≈$` — an `ANTHROPIC_API_KEY` in the env is
a *capability*, not proof of who pays (Forge may have hydrated it into an OAuth session), so it never flips `auto` to
API dollars. Proxy mode always shows the proxy's *reported* `~$` (may undercount; cost-unavailable routes are excluded,
not locally priced).

**Launch metadata.** The opt-in `launch` segment renders `confirmed.launch` (CLI-written once at start): the route
(`direct` / `proxy:<id>` / `custom`) and the api-key posture (`key:env|file|none|omit`). It describes how the session
reached the model and whether a key was made available — honest auth provenance the status line cannot infer from the
ambient env. Manifest-gated: absent for ambient sessions (no `FORGE_SESSION`).

**Forge session cost (`forge_cost`, Phase 5).** The opt-in `forge +$Y` segment shows **Forge-added LLM spend for this
session, excluding the main interactive harness** (`route=claude_interactive`) — what Forge spent *on top of* the
session the human drives (memory writer, supervisor, review fan-out), visually distinct from Claude's native `cost`.
Computed live on poll by summing reported-cost ledger events (`sum_forge_added_cost`); reported-or-unavailable, never
estimated, so subscription/OAuth sessions (cost-absent) render nothing. The harness exclusion is load-bearing: the card
forbids blending observed main-harness traffic into "Forge additional cost". Manifest-gated (no session → no segment).
The ledger read is throttled **time-only** by `read_or_compute_session_cost` (key = `sha256(forge_root + session_name)`,
the Forge identity, NOT the Claude stdin `session_id` which rolls on `/compact`): unlike the cache-hit throttle it has
no transcript-mtime shortcut, because headless cost accrues via ledger writes that never touch the transcript (which
would otherwise freeze the value all session). A legitimate `0` is cached; a ledger read error fails open (no segment,
never cached). Window: `forge_cost_ttl` (default 10s).

**Supervisor health (`supervisor` suffix, v1).** When the opt-in `supervisor` segment is active, a fail-open suffix
`!N <kind>` appends to the posture token (`SUP!3 timeout`, `SUP(susp)!2 timeout`, `SUP(off)!4 error`): N is the
newest-first contiguous run of frontier-supervisor `claude -p` runs the usage ledger recorded as a non-`success`
`status` (reset by the first `success`), `<kind>` is `timeout` or `error`. Posture-independent — suspended/off emit no
events, so prior fail-open history stays visible. ASCII `!` (no unicode glyph; survives `normalize-text`). Tiered like
`format_spend_cap`: YELLOW 1-2, RED `>=3`; the suffix never shows at 0, so a healthy `SUP` is byte-identical to today.
Read throttled + fail-open by `read_or_compute_session_health` (same `forge_cost_ttl` window, distinct `fhealth-`
cache); a read error degrades to **posture-only** (no suffix), never hiding the posture (unlike `forge_cost`, whose
whole value is ledger-derived). Source combines legacy `UsageEvent.status`/`failure_type` with upstream supervisor
policy outcomes, so timeout/subprocess failures, proxy lookup fail-opens, depth skips, and parse fail-opens all
contribute to the streak when recorded.

**Rendering.** The `where` bucket (`path`, `branch`) leads concatenated; all other segments are separator-joined in the
configured order. `RenderContext` derivations are lazy `cached_property` — a segment not in the active set does zero I/O
(no transcript scan, git subprocess, or proxy-field access it would otherwise trigger). Forge-unique segments read
**effective** session state (`apply_overrides(intent, overrides)`), so a `%policy`/`%supervisor` override changes
posture without an intent edit.

**Labeling:** Proxy info is authoritative for routing. Session info is authoritative for workflow.

### A.9 Proxy cost configuration and logs (§3.14)

Per-proxy cost controls live in the user-owned proxy file:

```yaml
# ~/.forge/proxies/<proxy_id>/proxy.yaml
costs:
  caps:
    per_day: 20.00
    per_month: 100.00
  on_cap_hit: reject
```

| Field                  | Values           | Meaning                                                           |
| ---------------------- | ---------------- | ----------------------------------------------------------------- |
| `costs.caps.per_day`   | positive USD     | Rolling 24-hour cap                                               |
| `costs.caps.per_month` | positive USD     | Calendar-month cap                                                |
| `costs.on_cap_hit`     | `reject`, `warn` | `reject` returns 429; `warn` adds `X-Spend-Warning` and continues |

Caps are enforced post-event: a request may cross a cap and complete, then the next request is blocked once accumulated
spend has reached the cap. There is no pre-flight estimate mode (`cap_mode` was removed in the metric-evidence card).

CLI updates use the normal proxy edit surface:

```bash
forge proxy set openrouter-anthropic costs.caps.per_day=20.00
forge proxy set openrouter-anthropic costs.on_cap_hit=warn
```

Runtime logs:

| Path                                       | Schema owner                         | Retention policy                                     |
| ------------------------------------------ | ------------------------------------ | ---------------------------------------------------- |
| `~/.forge/telemetry/downstream/*.jsonl`    | `forge.core.telemetry.downstream`    | Append-only, reset/user-prune                        |
| `~/.forge/telemetry/upstream/*.jsonl`      | `forge.core.telemetry.upstream`      | Append-only, reset/user-prune                        |
| `~/.forge/telemetry/caps/<proxy_id>.json`  | `forge.core.telemetry.caps`          | Durable cap checkpoint; reset by explicit cost reset |
| `~/.forge/telemetry/audit_state/<id>.json` | `forge.proxy.audit_logger`           | Sidecar drift baseline                               |
| `~/.forge/usage/events/*.jsonl`            | `forge.core.usage.ledger`            | Transitional attribution ledger; reset/user-prune    |
| `~/.forge/costs/requests/*.jsonl`          | legacy `forge.proxy.cost_logger`     | Legacy cap migration/reset compatibility             |
| `~/.forge/costs/verbs/*.jsonl`             | legacy `forge.core.reactive` wrapper | Retired writer; legacy reset compatibility           |

Downstream attempt records contain timestamp, proxy/source ID, model/tier, token counts, `cost_micros` (null when no
route reported a cost), request ID, latency, metric-evidence provenance (`reporter` + `confidence`), provider lifecycle
fields, optional redacted audit payloads, and the **run-tree correlation** `forge_run_id`/`forge_root_run_id` (§3.14 /
§A.13: null for the interactive harness and any non-Forge-originated traffic; set when a Forge-routed `claude -p`
subprocess forwarded the validated `X-Forge-Run-ID`/`X-Forge-Root-Run-ID` headers). `backend_id` is the canonical
model-source catalog id (`openrouter`, `litellm-remote`, `anthropic-direct`, etc.) used for upstream source attribution.
It is distinct from `source_id`/`source_kind`, which remain the telemetry-origin axis (`proxy` or `provider`). Two
companion headers ride the same proven-proxy path for provider-trace correlation: `X-Forge-Session` (an opaque
`forge_sess_<hash>` / `forge_run_<hash>` grouping id derived by hashing the session name + role — the raw name is never
sent) and `X-Forge-Command` (the sanitized command role). Like the run-id headers they are validated on read, stored on
`request.state`, and are **internal Forge↔proxy correlation only — never forwarded upstream** (the passthrough allowlist
drops them). They are distinct from provider-bound metadata such as the OpenRouter `user` field, which is deliberately
sent upstream. There is no local price catalog, so cost is reported-or-unavailable, never inferred from tokens. The
downstream idempotency key is `downstream_event_id`: the proxy mints one stable id per physical attempt and uses it for
both cost and provider lifecycle writes; true duplicate writes of that same attempt merge, while distinct
attempts/retries get distinct ids. `backend_id` filtering is applied after duplicate-attempt merge so later same-attempt
records with null `backend_id` can add evidence without erasing attribution. Legacy verb records are no longer written;
by-verb cost derives from downstream attempts joined to `usage/events` by run id.

The proxy `GET /` endpoint reports in-memory metrics and cost totals for live status. The JSONL request logs remain the
bootstrap source for cap enforcement after restart.

Cap enforcement is process-local. Each proxy process bootstraps from shared JSONL logs at startup, but in-flight spend
is not coordinated across concurrent processes. To coordinate caps across processes, run a single proxy process per
proxy ID.

Telemetry logs accumulate indefinitely. `forge proxy costs reset` wipes legacy cost-log planes (`costs/requests/` +
`costs/verbs/`), downstream/upstream telemetry shards, cap-state snapshots, audit sidecar state, **and** the
usage-attribution ledger (`usage/events/`) to zero in one step, and clears the derived status-line caches
(`cache/statusline/fcost-*.json` for `forge +$Y`, `fhealth-*.json` for supervisor health) so a wiped ledger cannot
replay a cached value; it prompts for confirmation unless `--yes`, and `--dry-run` previews. Either way, a running proxy
keeps its cost totals and cap counters in memory until restarted — it re-bootstraps from the remaining downstream/legacy
logs plus cap state at next startup, so restart any active proxy to also zero its live cumulative cost and cap
enforcement.

---

### A.10 System prompt addendums (non-Anthropic proxy routing)

When a Forge session launches with a proxy that routes to non-Anthropic models, the session launcher injects a
model-family-specific system prompt addendum via `--append-system-prompt-file`. These addendums teach the model to
construct minimal valid tool-call objects (avoiding empty placeholders like `"pages": ""` or `"offset": null`) and to
prefer dedicated tools (Read/Edit/Write) over Bash. Both OpenAI and Gemini share the same core tool-discipline guidance;
the Gemini variant uses stronger Bash-avoidance language due to a higher observed rate of `cat`/`sed`/`grep` use.

**Injection layer:** `src/forge/cli/session_addendum.py` resolves the addendum at session launch time
(`session_lifecycle.py`), not inside the proxy request path. Direct HTTP use of a proxy does not get addendum injection.

**Catalog field:** `system_prompt_addendum` on each model entry in `model_catalog.yaml`. Value is a relative path like
`system_prompt_addendums/openai.md` pointing to a markdown resource in `src/forge/core/data/`.

**Lookup:** `get_system_prompt_addendum(model_or_alias)` in `forge.core.models.catalog` resolves the model, loads the
resource, and returns the content string. Returns `None` for models not in the catalog or without an addendum (fails
open -- common with OpenRouter's open model space).

---

### A.11 Intercept, audit, and request-logging configuration (§7.x)

Optional always-on audit/control fields on the user-owned proxy file. All default to inert, so existing proxies are
unchanged. Coercion is **strict** — unknown sub-keys raise (a typo like `audit.full_body` must not silently disable
full-body capture).

```yaml
# ~/.forge/proxies/<proxy_id>/proxy.yaml
wire_shape: anthropic_passthrough # openai_translated (default) | anthropic_passthrough
intercept:
  mode: inspect # passthrough (default) | inspect | override
  override: # applied only in override mode (requires anthropic_passthrough)
    system_prompt_augment: "" # cache-aware system-prompt insert
    system_prompt_guards:
      - { pattern: "SECRET", action: block } # action: warn | block | strip
audit:
  audit_full_body: false # opt-in: capture REDACTED bodies (never plaintext)
  redact_headers: [] # extra header names to redact (denylist + substring)
  retention_days: 14
  max_total_mb: 512
logging:
  requests: # bounded debug diagnostics under ~/.forge/logs/requests/ (proxy_log_hygiene)
    enabled: auto # off | auto (couples to log_level=debug) | on
    body_capture: metadata # metadata (no body) | redacted (sanitized structure; never plaintext)
    response_capture: metadata # metadata | redacted
    max_file_mb: 16 # per-shard rotation cap (0 = unbounded)
    max_total_mb: 256 # prune oldest shards over budget at startup (0 = unbounded)
    retention_days: 14 # prune shards older than N days at startup (0 = no age bound)
    stream_chunks: false # opt-in per-chunk debug dumps (off even at log_level=debug)
    stream_chunk_max_bytes: 0 # truncate each dumped chunk (0 = small default cap)
```

| Field                                      | Values                                       | Meaning                                                                                           |
| ------------------------------------------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `wire_shape`                               | `openai_translated`, `anthropic_passthrough` | Wire truth; passthrough preserves thinking blocks (signature-safe)                                |
| `intercept.mode`                           | `passthrough`, `inspect`, `override`         | `override` requires `wire_shape: anthropic_passthrough`                                           |
| `intercept.override.system_prompt_augment` | string                                       | Cache-aware system-prompt insert (after the last `cache_control`)                                 |
| `intercept.override.system_prompt_guards`  | list of `{pattern, action}`                  | `pattern` is a regex (compiled at config load); action warn/block/strip                           |
| `audit.audit_full_body`                    | bool (default `false`)                       | Capture redacted bodies; there is **no** raw-body mode                                            |
| `audit.redact_headers`                     | list of strings                              | Extra header names to redact beyond the built-in denylist                                         |
| `audit.retention_days`                     | int                                          | Prune shards older than N days at proxy startup                                                   |
| `audit.max_total_mb`                       | int                                          | Prune oldest shards once total exceeds N MB at startup                                            |
| `logging.requests.enabled`                 | `off`, `auto`, `on` (default `auto`)         | `auto` couples to `log_level=debug`; `on` decouples bounded capture                               |
| `logging.requests.body_capture`            | `metadata`, `redacted` (default `metadata`)  | `metadata` omits the body; `redacted` reuses the audit redaction builder; **no** `full`/plaintext |
| `logging.requests.response_capture`        | `metadata`, `redacted` (default `metadata`)  | Same policy for the response body                                                                 |
| `logging.requests.max_file_mb`             | int (default `16`, `0` = unbounded)          | Per-shard rotation cap                                                                            |
| `logging.requests.max_total_mb`            | int (default `256`, `0` = unbounded)         | Prune oldest request shards over budget at startup                                                |
| `logging.requests.retention_days`          | int (default `14`, `0` = no age bound)       | Prune request shards older than N days at startup                                                 |
| `logging.requests.stream_chunks`           | bool (default `false`)                       | Opt-in per-chunk debug dumps; off even at `log_level=debug`                                       |
| `logging.requests.stream_chunk_max_bytes`  | int (default `0` = small cap)                | Truncate each dumped chunk                                                                        |

Reasoning-effort pinning in override mode **reuses** `tier_overrides.<tier>.reasoning_effort` (§A.1) — it is not a new
`intercept` key. `forge proxy set <id> intercept.mode=inspect` (and `audit.audit_full_body=true`, which prints a privacy
warning naming `~/.forge/telemetry/downstream/`) edits these via the normal proxy surface.

`logging.requests` (`RequestLogConfig`, `forge.config.schema`) governs the **debug request-diagnostics** plane at
`~/.forge/logs/requests/<YYYYMMDD>_requests.<pid>[.<seq>].jsonl` — owner-only 0600 (`open_secure_append`), PID-sharded,
rotated at `max_file_mb`. It is distinct from downstream telemetry and legacy `costs/requests/`, which may share similar
shard names but are separate planes. The block is strictly coerced (unknown sub-keys raise; `body_capture=full` is
rejected with a pointer to the audit no-plaintext policy) and reuses the audit body redactor — there is no second
sanitizer and no plaintext mode. Retention is enforced once per process at proxy startup by the shared
`prune_jsonl_shards` helper (which also backs the audit and provider-trace planes); the global `log_retention_days`
sweep remains the coarse floor.

---

### A.12 Audit log schema (§7.x)

Records are persisted **already redacted** (the typed builders redact headers/bodies before calling the writer, which
only appends). The no-plaintext-secret guarantee is regression-tested
(`tests/regression/test_bug_audit_header_redaction_no_leak.py`).

| Path                                                  | Owner                             | Notes                                           |
| ----------------------------------------------------- | --------------------------------- | ----------------------------------------------- |
| `~/.forge/telemetry/downstream/<YYYY-MM>_<pid>.jsonl` | `forge.core.telemetry.downstream` | Owner-only 0600, append-only, PID-sharded       |
| `~/.forge/proxies/<id>/audit_state.json`              | drift baseline (host)             | `schema_version`, `last_seen` hash map          |
| `~/.forge/telemetry/audit_state/<id>.json`            | drift baseline (sidecar)          | Same shape; the config dir is mounted read-only |

Every record carries `schema_version`, `ts`, `request_id`, `proxy_id`, and a `record_type`:

- `request`: `mode`, `route`, `full_body`, `system_prompt_hash`, `tool_surface_hash`, `thinking`, `cache_markers`,
  `counts`. Full-body adds redacted `request_headers/body` on every path and structural-only `response_headers/body`
  only for non-streaming passthrough. Streaming captures response usage metadata only; the translated path is
  request-body only. Streaming full-body response capture and translated-path response capture are both deferred.
- `drift`: `dimension` (`system_prompt` | `tool_surface`), `previous_hash`, `current_hash`, `route`.
- `mutation`: `mode: override`, `blocked`, `system_prompt_hash_before/after`, and `mutations[]`. Each mutation records
  `{target, action, ...}` plus hashes, lengths, and budgets only: `augment_len`, `cache_invalidation_expected`,
  `pattern_hash`, `stripped_count`, `effort_floor`, `budget_before/after`.

Reading skips records written by a newer Forge (`schema_version` > current) with a one-time warning.
`forge proxy audit show|diff` (§4.0) is the read surface.

### A.13 Usage-attribution ledger schema (§3.14)

The canonical **attribution** plane: which run/workflow/session invoked which runtime/provider/model via which route,
and what it consumed. Modeled on the audit log (versioned, strictly read). The three data planes stay physically
separate and are joined by a shared proxy `request_id`:

| Path                                          | Owner                     | Notes                                                    |
| --------------------------------------------- | ------------------------- | -------------------------------------------------------- |
| `~/.forge/usage/events/<YYYY-MM>_<pid>.jsonl` | `forge.core.usage.ledger` | Owner-only 0600, append-only, PID-sharded; `UsageEvent`s |

`UsageEvent` carries `schema_version` (= 1) plus an auto-stamped `event_id` (`evt_…`, for dedupe/debugging) and `ts`:

| Group            | Fields                                                                                             |
| ---------------- | -------------------------------------------------------------------------------------------------- |
| Attribution core | `run_id`, `root_run_id`, `runtime`, `command`, `status` (required); `parent_run_id` (optional)     |
| Context          | `session`, `workflow`, `provider`, `model`, `proxy_id`                                             |
| Provenance       | `billing_mode`, `measurement_source`, `attribution_granularity`, `route`, `reporter`, `confidence` |
| Consumption      | `input_tokens`, `output_tokens`, `cached_tokens`, `latency_ms`, `failure_type`, `cost_micro_usd`   |
| Cross-plane refs | `source_refs` = `{cost_request_id, audit_request_id}` (nullable)                                   |

Enumerations are `Literal`s (provenance is recorded, never inferred):

- `measurement_source`: `proxy_request_exact` | `verb_snapshot_estimated` | `provider_usage_exact` | `runtime_native` |
  `unattributed` — how the cost/token figures were obtained, so an event lacking an exact figure says so rather than
  guessing. `provider_usage_exact` = exact in-band token usage from either a direct `core.llm` call **or** a direct
  `claude -p` envelope that reported `usage` but no cost (Phase 5, e.g. OAuth). `runtime_native` (Phase 5, emitted) = a
  runtime self-reported its own cost+usage: a direct `claude -p --output-format json` run (`reporter=claude_code`), or a
  native `codex`/`gemini` runtime later. `proxy_request_exact` (Phase 4g) is the provenance of a **read-time** figure,
  not a stored event source: a proxied `claude -p` event keeps `verb_snapshot_estimated` in the ledger, but
  `forge activity` / `forge +$Y` recompute that run tree's cost exactly from the cost plane (sum of cost records by
  `forge_root_run_id`) and label the result `proxy_request_exact`, **suppressing** the snapshot to avoid
  double-counting. Suppression is **per-run-subtree** (the snapshot's own run, or a verb whose direct children produced
  records — derived from worker `parent_run_id`), never whole-root, so a correctly-unstamped sibling sharing the session
  root keeps its snapshot instead of being silently dropped. A figure with no snapshot estimate mixed in — cost-plane
  exact (4g root-join) and/or runtime-reported (`runtime_native`) — renders **without** the `~` estimate marker
  (`cost_estimated=False` on the summary/command DTOs); a figure mixing in a snapshot estimate keeps `~`.
- `billing_mode`: `api` | `subscription_interactive` | `subscription_headless_credit` | `subscription_quota` | `unknown`
  (`unknown` is the honest default where the signal is ambiguous).
- `attribution_granularity`: `worker` | `verb` | `session`.
- `route`: `claude_interactive` | `claude_p` | `forge_proxy` | `core_llm` | `codex_exec` | `gemini_headless` — how the
  work reached the model (invocation channel). Emitted now: `claude_p`/`core_llm`/`codex_exec` (plus `None` on an
  aggregate spanning mixed routes); `claude_interactive`/`gemini_headless` stay reserved, like the unemitted
  `subscription_*` billing modes. `forge_proxy` is reserved **here** — it is emitted now as a `reporter`, not yet as a
  `route` (it appears in both literals).
- `reporter`: `claude_code` | `forge_proxy` | `openrouter` | `litellm` | `provider` | `codex_jsonl` — the source of the
  **metric** evidence (tokens **and/or** a cost figure, *not* specifically cost), so `reporter=provider` alongside
  `confidence=unavailable` is coherent: the provider reported tokens, just no dollars. Emitted now: `provider`,
  `forge_proxy`, `claude_code` (Phase 5 — a direct `claude -p` verb/worker that self-reports cost+usage), and
  `codex_jsonl` (Phase 5c — a `codex exec` run's JSONL `turn.completed.usage`).
- `confidence`: `reported` | `gateway_calculated` | `inferred` | `unavailable` | `unknown` — trustworthiness of **this
  event's own `cost_micro_usd` only** (token provenance is `measurement_source`; the two axes are orthogonal — the
  tagger is `measurement_source=provider_usage_exact` with `confidence=unavailable`, *not* a contradiction). A null cost
  is `unavailable` regardless of any `source_refs`-joined cost record. `unknown` is legacy/default (provenance never
  recorded); a known-no-cost route is `unavailable`, not `unknown`. Proxy cost is `reported` (OpenRouter body
  `usage.cost`) or `gateway_calculated` (LiteLLM `x-litellm-response-cost` header) when a route reports it, else
  `unavailable` (Anthropic passthrough; LiteLLM streaming) — the price catalog was removed, so `inferred` is no longer
  produced on the proxy cost path (the literal remains reserved).

`source_refs` is null on native-runtime events (no proxy) and stays null on `claude -p` traffic: Phase 4g correlates a
proxied `claude -p` run to its exact cost through the **run tree** (`forge_root_run_id` stamped on each cost record),
not through a single-valued `source_refs.cost_request_id` — one run makes many requests, so the run-tree join is the
right shape and `source_refs` is intentionally left null (the
`tests/regression/test_bug_usage_claude_p_null_source_refs.py` invariant holds). The event stays useful without it
(run/model/billing_mode/tokens). Reading skips — with a one-time warning — records written by a newer Forge
(`schema_version` > current), and (strict on shape) records with unknown fields. `read_usage_events()` is the typed read
surface. The `route`/`reporter`/`confidence` fields were **added additively at `schema_version` 1 (no bump)**: optional
\+ defaulted, so existing v1 records load unchanged. A *pre-Phase-1* reader, by contrast, drops the newer records as
unknown-field corruption — acceptable for best-effort, PID-sharded, pruned local telemetry, and **not** a state to
migrate around.

**Instrumented emitters (Phase 4c).** The workflow verbs (`panel`/`analyze`/`debate`/`consensus`) emit one estimated
verb-level event each (`measurement_source=verb_snapshot_estimated`, attributed to the ambient run — per-worker cost is
not available); the memory writer, semantic supervisor, team supervisor (Phase 5), and shadow curation emit one event
per `claude -p` run (attributed to that subprocess's run identity, via the `track_verb_cost` holder); the action tagger
emits a `provider_usage_exact` event from a direct `core.llm` call (exact in-band provider tokens). On the **direct
path**, Forge resolves the call's base_url synchronously: if it is a registered Forge proxy, the tagger forwards an
`X-Request-ID` and records an exact `source_refs.cost_request_id` join (the proxy logs its cost record under the same
id); otherwise it sends no header and leaves the ref null (a dangling join is worse than none). Direct-path
`billing_mode` stays `unknown` unless the caller proves direct + real-credential billing (the tagger routes via local
LiteLLM with a dummy key, so it can't). All emit best-effort, never gate the work they measure, and record `latency_ms`;
`claude -p` events carry null `source_refs` and join to exact cost by run tree (`forge_root_run_id`, Phase 4g). Helpers:
`emit_verb_usage`, `emit_usage_for_session_result`, `emit_direct_llm_usage` (`forge.core.usage.emit`). Each also stamps
`route`/`reporter`/`confidence`: tagger → `core_llm`/`provider`/`unavailable`; the verb aggregate claims no single
`route`.

**Cost precedence on `claude -p` verbs (Phase 5).** Every `claude -p` run requests `--output-format json`
(capability-gated, retry-once-and-latch), so the runtime can self-report. Exactly **one** reporter attributes cost per
run:

- **Proxied** (`base_url` set) → the proxy snapshot wins: `forge_proxy` / `reported` / `verb_snapshot_estimated` with
  snapshot tokens (Claude's Anthropic-priced `total_cost_usd` is ignored — wrong for a non-Anthropic backend and a
  duplicate of the proxy's report). No snapshot cost → `None` / `unavailable`. The stored event stays
  `verb_snapshot_estimated`, but the read surface recomputes the run tree's cost exactly from the cost plane and
  supersedes this snapshot (Phase 4g `proxy_request_exact`; see §A.13).
- **Direct** (no proxy) → the runtime self-reports: `claude_code` / `reported` / `runtime_native` with exact in-band
  tokens. A parsed envelope with usage but no cost (OAuth) → `provider_usage_exact` / `unavailable` (tokens kept, cost
  honestly absent). Neither → `unavailable`.

Tokens follow the cost source (no mixed provenance: a `verb_snapshot_estimated` event never carries the exact in-band
tokens). This is the first emission of `reporter=claude_code` and `measurement_source=runtime_native`.

**Per-worker fan-out events (Phase 4d/5).** The review fan-out (`run_multi_review` →
`ClaudeHeadlessInvoker.run_parallel`) emits one event per worker (`attribution_granularity=worker`): the run-tree leaf
(run/parent/root) plus the **actual routed** `model` (`route.model_ref`), `provider`, and `proxy_id`, with `status` and
`latency_ms`. Cost follows the same one-reporter precedence (Phase 5): a **direct** worker self-reports (`claude_code` /
`runtime_native`, or `provider_usage_exact` tokens-only); a **proxied** worker stays `unattributed` with null
cost/tokens — the verb-level aggregate above holds the estimated proxied total, so attributing per-worker would
double-count. Helper: `emit_worker_usage`.

**Read surface — `forge activity` and the session-end summary.**
`build_session_activity_summary(name, forge_root, since=)` produces a `SessionActivitySummary` with compatibility
command rollups plus two explicit panes. The `upstream` pane groups `UpstreamOutcome`s by
command/operation/status/reason and carries `PolicyActivity` from the manifest fallback; the fallback is capped at
`MAX_DECISION_LOG`, so `log_capped` is surfaced and duplicate manifest/upstream warnings are suppressed. The
`downstream` pane groups model-call/spend evidence visible to the session: downstream records whose run tree is known
from upstream or `usage/events`, records whose provider-session id matches the hashed session prefix, and transitional
`usage/events` command rows for labels/legacy error counts. Rows carry `join_state` (`matched`, `upstream_only`,
`downstream_only`); a truly orphaned downstream record with no session-known run tree is not session-attributable.

`forge activity --json` is a clean-break shape with top-level `session`, `since`, `upstream`, `downstream`, `shadow`,
`subagents`, and `notes` only. Old top-level `commands`, `policy`, `total_events`, and `session_tagging_partial` fields
are represented inside panes or `notes`. The launcher still prints the compact one-line `render_summary_line(...)` on
exit (host, sidecar, fork) from the same builder. The `failing open: N timeout, N error` clause still comes from the
window's supervisor failure split; JSON exposes those legacy counts under `downstream.rows[*].error_kinds`. Cost is
reported-or-estimated and may be partial; `forge proxy costs show` is authoritative.

Per-emitter session coverage (a per-session summary is honest about what it can attribute):

| Emitter                                                        | Tags `session`? | Notes                                                                                        |
| -------------------------------------------------------------- | --------------- | -------------------------------------------------------------------------------------------- |
| Semantic supervisor (`emit_usage_for_session_result`)          | Yes             | `session=context.session_name` (= manifest name)                                             |
| Supervisor shadow (`emit_usage_for_session_result` + upstream) | Yes             | `command=supervisor-shadow`; `operation=policy.shadow_drain`; re-rooted under origin session |
| Memory writer (`emit_usage_for_session_result`)                | Yes             | `session=session_name`                                                                       |
| Workflow verbs panel/analyze/debate/consensus                  | Yes             | threaded `session=$FORGE_SESSION` (verb aggregate + per-worker)                              |
| Transfer curation (`emit_direct_llm_usage`, `transfer-curate`) | Yes             | `session=$FORGE_SESSION`; ai-curated strategy only; `route=core_llm`/`runtime=forge_cli`     |
| Plan check (`emit_direct_llm_usage`, `plan-check`)             | Yes             | cascade tier-1; `session=context.session_name`; `route=core_llm`                             |
| Action tagger (`emit_direct_llm_usage` + upstream outcome)     | Partially       | upstream tags `session`; spend event remains untagged, so cost coverage may be partial       |

**Sidecar.** When a sidecar session launches with a proxy id, the launcher mounts `~/.forge/usage/` rw alongside
`audit/`, `costs/`, and `telemetry/` (§7), so the in-container supervisor/verb events, downstream/upstream telemetry,
and cap state survive the `--rm` container. Template-only sidecars (no proxy id) mount none of these, so their telemetry
stays ephemeral — consistent with how they already drop audit/costs.

### A.14 Provider lifecycle fields in downstream telemetry (§3.14)

Provider lifecycle / correlation evidence answers "did this request leave Forge, which route/generation, did the stream
start, finish, or lose its final usage chunk?" It is now stored as metadata-only fields on downstream attempt records
under `~/.forge/telemetry/downstream/`, rather than in a separate provider-trace directory. Born from an incident where
a supervised fork's checks timed out before the final streaming usage chunk and left no trace locally or remotely.

| Path                                    | Owner                             | Notes                                                               |
| --------------------------------------- | --------------------------------- | ------------------------------------------------------------------- |
| `~/.forge/telemetry/downstream/*.jsonl` | `forge.core.telemetry.downstream` | Owner-only 0600 shards; provider fields live on `DownstreamRecord`s |

`read_provider_traces()` projects downstream attempts into the legacy `ProviderTraceRecord` DTO for CLI/core-op callers.
Provider lifecycle fields carried by the downstream schema include:

| Group       | Fields                                                                                                                                 |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Correlation | `request_id`, `proxy_id`, `backend_id`, `mapped_model`, `forge_run_id`, `forge_root_run_id`, `provider_session_id`, `provider_command` |
| Provider    | `provider`, `selected_provider`, `provider_response_id`, `provider_generation_id`, `provider_request_id`, `provider_headers`           |
| Lifecycle   | `request_mode`, `stream_started`, `first_chunk_seen`, `final_usage_seen`, `client_disconnected`, `local_usage_status`, `timeout_seen`  |
| Cost echo   | `reported_cost_micros`, `latency_ms` (diagnostic copies; the cost plane stays the spend source of truth)                               |

Semantics and invariants:

- **Metadata-only.** There is deliberately no prompt/completion/tool/body field. `provider_headers` is the Phase 2
  correlation allowlist (`x-request-id` / `x-generation-id` / `x-litellm-call-id` / `x-litellm-model-id`), re-applied at
  the writer so a future caller that bypasses the upstream allowlist still cannot persist auth/cookie headers.
- **Source-capability gated.** Written only when the selected backend source declares provider-trace capability.
  `openrouter` opts in for v1; gateway-routed OpenRouter through non-capable LiteLLM sources writes nothing. The
  passthrough relay is instrumented with the same lifecycle but remains quiet for current non-capable passthrough
  sources.
- **`first_chunk_seen`** = first user-visible content chunk; the internal `_provider_meta` carrier (which delivers the
  `gen-…` id, captured on the **first** stream event) does not count, so a stream cancelled before any content still
  records the generation id with `first_chunk_seen=false`.
- **`local_usage_status`** = `available` when the proxy locally saw a final usage chunk or a reported cost, else
  `unavailable`. Probe 2 (`[REMOTE-ABSENT]`) confirmed an aborted stream is not remotely retrievable, so the status is
  answered from local evidence only — no remote `/generation` lookup.
- **`timeout_seen` is always `false`.** The proxy observes only its own client disconnect (`client_disconnected`), never
  the parent's `subprocess.run` timeout; the field is a join target for later run-tree correlation, not proxy-populated.
- **Joins** spend/usage by shared `request_id` + run-tree ids; one `claude -p` run produces many requests, so the
  run-tree join (`forge_root_run_id`) is the right shape (`tests/regression/test_bug_provider_trace_run_tree_join.py`).
- Reading skips, with a one-time warning, records written by a newer Forge (`schema_version` > current), and (strict on
  shape) records with unknown fields or bad `Literal` values. `read_provider_traces()` is the typed read surface.
  Provider-trace retention delegates to unified downstream shard pruning; current-calendar-month downstream shards are
  preserved for spend-cap bootstrap, and filtered compaction is follow-up work.
- **Read surface (Phase 4).** `forge provider trace list|show|explain` (op-backed `core/ops/provider_trace.py`;
  `%provider trace` mirrors it via the shared `render_explanation_lines` text contract). `list` filters by session
  *label* (re-derived `forge_sess_<hash>` prefix) / `forge_root_run_id` / `--period`; `explain` joins downstream spend
  evidence by `request_id` within ±5m for cost confidence. Local-only — no remote `/generation` lookup.
- **Session-id injection (opt-in).** `provider_trace.inject_provider_user` (default off) forwards the validated
  `X-Forge-Session` id (or a `forge_run_<hash>` fallback) into the provider's top-level `user` field on source-capable
  proxied routes — probe 3 found `user` is retained in the indexed `/generation` record for account-side lookup, while a
  custom `session_id` is ignored. Server-gated (`_provider_user_value`) and adapter-forwarded via
  `extra["openai"]["user"]`; metadata-only, hashed, never the raw session name. Direct `core.llm` callers (plan-check,
  curation) are a documented follow-up, not wired here.

---

## B. Work Queue Internals

Extracted from [design.md §3.13](design.md#313-async-work-queue). Design goals and rationale remain in design.md.

### B.1 Marker schema (v2)

```json
{
    "schema_version": 2,
    "kind": "stop",
    "marker_id": "uuid-123",
    "forge_version": "0.9.0",
    "created_at": "2026-01-07T12:00:00Z",
    "payload": {
        "session_id": "uuid-123",
        "forge_root": "/abs/path/to/forge/project",
        "project_root": "/abs/path/to/repo",
        "session_name": "my-session",
        "transcript_snapshot_rel": ".forge/artifacts/..."
    },
    "attempt_count": 0,
    "last_attempt_at": null,
    "last_error": null
}
```

**Key fields:** `kind` = routing key (which handler); `marker_id` = filename key (caller chooses idempotency, e.g.
session ID); `payload` = kind-specific data; `attempt_count`/`last_error` = retry tracking. Marker ID validated with
`^[A-Za-z0-9._-]+$`. The `handoff` marker payload additionally carries `origin_run_id`/`origin_root_run_id` (the
originating session's run-tree identity, snapshotted at Stop time) so the detached memory writer roots under that
session rather than the draining CLI ([design_workflows.md §4.5](design_workflows.md#45-operational-constraints)).

### B.2 Processing contract

Handlers are passed explicitly as a `handlers` dict (no global registry -- avoids import-order coupling and test state
leakage): `process_pending_work(handlers={"stop": handler, "index": handler})`.

| Outcome                             | Behavior                                                                |
| ----------------------------------- | ----------------------------------------------------------------------- |
| Handler succeeds                    | Delete marker under lock                                                |
| Handler raises                      | Keep marker, increment `attempt_count`, write `last_error` under lock   |
| Lock contention                     | Skip (another process holds it)                                         |
| No handler for kind                 | Skip, log warning (leave in place)                                      |
| `attempt_count >= MAX_ATTEMPTS` (5) | Move to `pending-work/failed/` (poison marker, preserved for debugging) |

### B.3 Known marker kinds

| Kind      | Producer            | Handler                                 |
| --------- | ------------------- | --------------------------------------- |
| `stop`    | Stop hook           | No-op (delete only)                     |
| `index`   | Stop hook           | Index transcript for search             |
| `handoff` | Stop hook (planned) | Spawn the memory writer for memory docs |

---

## C. Install Model Reference

Reference details for [design.md §5.1](design.md#51-extensions-install-model).

### C.1 Scope model

| Scope     | Extensions Path                       | Settings Path                 | Use case                                           |
| --------- | ------------------------------------- | ----------------------------- | -------------------------------------------------- |
| `user`    | `~/.claude/{commands,agents,skills}/` | `~/.claude/settings.json`     | Personal global (default; prevents worktree drift) |
| `project` | `.claude/{commands,agents,skills}/`   | `.claude/settings.json`       | Team-shared (checked in)                           |
| `local`   | `.claude/{commands,agents,skills}/`   | `.claude/settings.local.json` | Personal per-project                               |

### C.2 Installable modules + profiles

| Module        | Installs                                           | Notes                                                            |
| ------------- | -------------------------------------------------- | ---------------------------------------------------------------- |
| `commands`    | Slash commands markdown                            |                                                                  |
| `agents`      | Subagents markdown                                 |                                                                  |
| `skills`      | Skills (SKILL.md + resources/scripts)              | Scripting layer for Forge workflows (see design_workflows.md §3) |
| `hooks`       | Hook settings entries (invoke `forge hook ...`)    | No hook scripts installed; requires `hooks.*` settings merge     |
| `status-line` | `statusLine` setting (invokes `forge status-line`) | No scripts installed; same pattern as hooks                      |
| `permissions` | Forge-required permission entries                  | Merged as unions                                                 |
| `codex-hooks` | Managed hook block in Codex `config.toml`          | Scope-mapped target; best-effort (see §C.6)                      |

Profiles:

- `minimal`: `commands`
- `standard`: `commands`, `agents`, `skills`, `hooks`, `permissions`, `status-line`, `codex-hooks` (default)
- `full`: all modules (same as standard; reserved for future heavy modules)

### C.3 Settings merge rules

| Setting             | Merge behavior                                             |
| ------------------- | ---------------------------------------------------------- |
| `hooks.*`           | Append + dedupe by command path (invokes `forge hook ...`) |
| `permissions.allow` | Union unique entries                                       |
| `permissions.deny`  | Union unique entries                                       |
| `statusLine`        | Scalar merge; conflict fails unless `--force`              |
| `model`             | Never touched                                              |

All settings modifications must be backed up first (`settings.json.forge-backup`).

### C.4 Tracking file (`~/.forge/installed.json`)

The installer must track what it changed so:

- `forge extension sync` updates only tracked items
- `forge extension disable` removes only tracked files and reverts only Forge-added settings entries

### C.5 Multi-scope installation (skill resolution)

Skills use `${CLAUDE_SKILL_DIR}` (a Claude Code built-in) to reference co-located resources. This variable resolves to
the directory of the **executing** SKILL.md, so each installation is self-contained -- resources always come from the
same scope as the SKILL.md that was invoked.

**Dual-scope behavior:** Installing Forge at two scopes (e.g., `--scope user` + `--scope project`) creates independent
copies of every skill. Each copy has its own SKILL.md, resources, and scripts. Forge does **not** deduplicate across
scopes.

| Concern             | Behavior                                                                                  |
| ------------------- | ----------------------------------------------------------------------------------------- |
| Resource resolution | Safe: `${CLAUDE_SKILL_DIR}` is self-referential (no cross-scope mismatch)                 |
| Which copy runs     | Determined by Claude Code's scope precedence (not controlled by Forge)                    |
| Version skew        | If scopes are updated independently, one copy may be stale                                |
| Hook duplication    | Both scopes add hook entries to their respective settings files; hooks may fire from both |
| Uninstall           | Scope-specific: `forge extension disable` removes only the targeted scope                 |

**Recommendation:** Use a single scope per project. If both exist, disable one:

```bash
forge extension disable --scope user     # Remove user-level
forge extension enable --scope project   # Keep project-level only
```

### C.6 Codex hook registration (codex-hooks module)

`forge extension enable` registers Forge's two Codex hooks by appending a marker-delimited managed block
(`# >>> forge hooks >>>` … `# <<< forge hooks <<<`) to the Codex config the Forge install scope maps to:

| Forge scope         | Codex config target                                        |
| ------------------- | ---------------------------------------------------------- |
| `user`              | `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`) |
| `project` / `local` | `<project_root>/.codex/config.toml`                        |

Codex has no settings.local analog, so both project scopes target the one per-project config. The scope choice carries a
trust cost (stage 84): user scope needs **one** trust ceremony ever; project/local scope needs one **per repo**.

Mechanics (`src/forge/install/codex_hooks.py`):

- **Forge never rewrites the user's config.toml** — codex-cli owns it. Merge appends or replaces only the managed block,
  re-validates the merged content with `tomllib` before an atomic write, and backs up first
  (`.config.toml.forge.backup.<ts>`). Disable removes only the block (a whitespace-only remainder deletes the file).
- **Trust-byte stability**: the rendered entry bytes are golden-pinned — Codex's `trusted_hash` covers the registration
  definition, so changing a command string or entry shape silently invalidates existing enrollment.
- **Dedupe vs manual registrations**: all Forge commands already registered outside the markers → skip (manual
  registration kept, untracked); a partial manual registration → conflict (installing would double-register).
- **Best-effort module**: a missing `codex` binary or a config conflict degrades to a visible skip — it never sets
  `InstallPlan.has_conflicts` and never blocks the Claude install.
- **Event-name validation**: registration event names are validated against the probe-pinned 10-event set at plan time
  (Codex itself loads bogus event names silently).
- Tracking records `codex_config_path` + `codex_commands` in `~/.forge/installed.json`; `forge extension status` shows
  the registration; disable refuses a tracked path that no longer matches the scope mapping.

Registration alone is inert: enable prints a Next-steps block naming the one-time interactive trust ceremony (run
`codex`, grant trust). Enrollment is unverifiable pre-turn (design.md §3.9), so Forge never claims it.

---

## D. Interactive Manual Testing

Automated tests catch logic bugs but miss UX/latency/real-system failures. Previous manual testing found 5 real bugs
(including a macOS crash) that ~2,400 automated tests missed.

**Why checklist-driven.** Early versions let the agent improvise commands — producing invented CLI commands, interactive
prompts that hang the Bash tool, and leaked API keys. The fix: pre-written checklists where commands and assertions are
deterministic and the agent only interprets results. Checklist edits change tests without modifying skill instructions.

**Three skills** with escalating isolation, tied to install profiles:

| Skill                | Profile    | Isolation                                          | Audience          |
| -------------------- | ---------- | -------------------------------------------------- | ----------------- |
| `/forge:smoke-test`  | `standard` | Host, read-only probes                             | End users         |
| `/forge:walkthrough` | `standard` | Host, hermetic test repo (`--sidecar` adds Docker) | End users / demos |
| `/forge:qa`          | `full`     | Docker container                                   | Maintainers       |

**Shared pattern — checklist + wrapper + annotations.** Each skill reads a checklist, runs commands through a
mode-specific wrapper, and routes items by annotation. A three-window model (Session A runs the skill, Session B is the
subject under test, Terminal for raw CLI) enables interactive verification of things the agent can't see. Session A
prompts the user to open Terminal early. Session B is launched only when the checklist first needs interactive
verification.

**Key design decisions:**

- Share the pattern/convention, not the prompt — each skill is self-contained (no cross-mode confusion)
- Checklist is single source of truth — editing it changes tests without SKILL.md modifications
- Each skill-local `walkthrough-state.py` is the deterministic bookkeeper — agent classifies (pass/fail/skip), and the
  script counts
- No per-checklist-item scripts — wrapper + lifecycle scripts are enough
- `/forge:qa` tied to `full` install profile (Docker dependency)

> See also [testing-guidelines.md](developer/testing-guidelines.md) for the full testing reference.

### D.1 Annotation types

| Annotation               | Session A does                                 | User does                              |
| ------------------------ | ---------------------------------------------- | -------------------------------------- |
| `<!-- auto -->`          | Runs command via wrapper, checks assertions    | Nothing                                |
| `<!-- human:confirm -->` | Runs command, shows output                     | Eyeballs output in Session A, confirms |
| `<!-- human:guided -->`  | Tells user what to do in Session B or Terminal | Does it, reports back to Session A     |
| `<!-- requires: X -->`   | Checks infra probe                             | Skip if unavailable                    |
| `<!-- destructive -->`   | Runs command (safe in sandbox)                 | Nothing                                |

### D.2 Wrapper abstraction

| Skill                | Wrapper                        | Isolation                        |
| -------------------- | ------------------------------ | -------------------------------- |
| `/forge:walkthrough` | `bash run-in-repo.sh <cmd>`    | env redirection + 4 safety gates |
| `/forge:qa`          | `docker exec $CONTAINER <cmd>` | OS-level container boundary      |

**Three-window model:** Session A prompts the user to open Terminal early. Session B is launched only when the checklist
first needs interactive verification.

### D.3 Per-skill details

**Smoke test** (`smoke-test.sh`): Read-only probes with mtime snapshot assertions. Not checklist-driven.

**Walkthrough** (checklist-driven via `run-in-repo.sh`): Annotated checklist (11 sections) covering install, verify,
guided exploration, proxy/session creation, live Claude session, and cleanup. Hermetic isolation via
`setup-test-repo.sh` (FORGE_HOME redirection, marker file, 4 safety gates in `run-in-repo.sh`).

**Full QA** (checklist-driven via `docker exec`): 312-item checklist split into per-section files
(`resources/checklist.md` index + `resources/checklist/*.md`, 20 sections). Includes `human:guided` items for
interactive verification. State tracking with `--from X.Y` resume. Separate skill prevents cross-mode contamination.

**Deterministic bookkeeper** (`walkthrough-state.py`): Each checklist-driven skill keeps a local state script that
parses its checklist markdown into structured JSON. Seven commands: `index`, `step N.X`, `summary` (read-only) + `init`,
`record`, `var`, `report` (state machine). Code blocks tagged `runnable` (`bash` = true, plain \`\`\`\`\`\`\`\` =
display-only). State file uses SHA-256 hash for drift detection. 58 unit tests.

---

## E. Shared LLM Client (`src/forge/core/llm/`)

`AnthropicClient` deferred; currently uses `OpenAIClient` for all providers via LiteLLM.

**Purpose:** Unified async-first LLM client abstraction for Proxy, Policy, and Skills components.

### E.1 Design principles

1. **Async-first**: All clients async; sync usage via `SyncAdapter` wrapper
2. **Canonical types**: `Message`, `CompletionResponse`, `StreamEvent` -- no raw dicts
3. **Injectable credentials**: `CredentialManager` with TTL caching, testable
4. **Separation**: LLM calls only; tier orchestration stays in Proxy

### E.2 Module structure

```text
src/forge/core/llm/
├── types.py        # Message, StreamEvent, ModelHyperparameters, ToolCall
├── protocols.py    # LLMClient protocol
├── credentials.py  # CredentialManager (injectable singleton)
├── errors.py       # NoApiKeyError, AuthenticationError, ProviderError
└── clients/        # LiteLLMClient
```

### E.3 Core types (signatures)

```python
class ModelHyperparameters(BaseModel):
    max_tokens: int; temperature: float | None; reasoning_effort: ReasoningEffort | None
    thinking: ThinkingConfig | None; strict: bool  # Error vs warn on unsupported params

class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict]; tool_calls: list[ToolCall] | None

class CompletionResponse(BaseModel): text: str; tool_calls: list[ToolCall] | None; usage: dict
class StreamEvent(BaseModel): type: Literal["text_delta", "tool_call_delta", "response_end", ...]
```

### E.4 Client protocol

```python
class LLMClient(Protocol):
    @property
    def model(self) -> str: ...
    async def complete(self, messages: list[Message], *, tools=None, hyperparams=None) -> CompletionResponse: ...
    async def stream(self, messages, *, tools=None, hyperparams=None) -> AsyncGenerator[StreamEvent, None]: ...
    async def count_tokens(self, messages, tools=None) -> int: ...
```

### E.5 Factory and provider detection

```python
def get_client(model: str, *, provider: ProviderType | None = None) -> LLMClient:
    """Sync factory, async methods. Provider auto-detected from model prefix."""
    # vertex_ai/, openai/, anthropic/ -> litellm_remote
    # gemini/ -> litellm_local
```

### E.6 Sync adapter

```python
class SyncAdapter:
    """Wraps async client for sync contexts. Uses asyncio.run() -- cannot nest in event loop."""
    def ask(self, prompt: str, *, system: str | None = None) -> str: ...
```

> **Trap:** Policy uses `SyncAdapter`; Proxy is async. Don't import sync Policy logic into Proxy -- `asyncio.run()`
> crashes in running loop. Use async-first at boundaries.

### E.7 Unsupported parameter policy

| Mode                     | Behavior                         |
| ------------------------ | -------------------------------- |
| `strict=False` (default) | Warn + ignore unsupported params |
| `strict=True`            | Raise `UnsupportedParamError`    |

### E.8 Relationship to Proxy

| Concern                        | Owner              |
| ------------------------------ | ------------------ |
| LLM API calls, auth, streaming | `core.llm`         |
| Tier mappings, templates       | `proxy.templates`  |
| Format conversion              | `proxy.converters` |

---

## F. WorkflowPolicy Cost Model

Migrated from the former archived Appendix C. Contextualizes why the tagger->checker->reviewer pipeline
(design_workflows.md §1.2) uses a branching architecture.

Cost model for a divergence-from-mean workflow: tagger ($0.001/call) filters 80% of changes as non-architectural. Of the
20% that reach a checker ($0.001), ~80% short-circuit as aligned. Only ~4% reach the reviewer ($0.05). Total: ~$0.32/100
changes vs $5.00 reviewing everything.

---

## G. Subprocess Routing Reference

Extracted from [design.md §3.6.12](design.md#3612-subprocess-routing-resolution-normative). Resolution chain concept,
fail-open/fail-closed semantics, and per-invocation routing plan remain in design.md.

### G.1 Core types (from `core.reactive.routing`)

```python
RoutingSource = Literal[
    "explicit",          # CLI flag override (--proxy, --supervisor-proxy, config URL)
    "subprocess_proxy",  # Session ambient (FORGE_SUBPROCESS_PROXY)
    "preferred_proxy",   # Catalog hint (ModelSpec.preferred_proxy)
    "route_scan",        # Compatible running proxy found via route matching
    "session_proxy",     # Inherited ANTHROPIC_BASE_URL
    "direct",            # Intentional direct execution (direct-only model specs)
    "unresolved",        # No route found (shared resolver terminal step)
]

@dataclass(frozen=True)
class ModelRoute:
    provider: str              # "openrouter", "litellm", or "direct"
    credential: str            # Credential from credential_registry.py (e.g., "openrouter", "anthropic-api")
    family: str                # Model family (e.g., "openai", "gemini", "anthropic")
    template_id: str | None    # Proxy template this route can use; None for direct
    template_family: str | None  # Template's explicit family metadata; None for direct
    model_ref: str             # Provider-specific model ID (e.g., "openai/gpt-5.5")

@dataclass(frozen=True)
class RoutingResult:
    base_url: str | None       # None = direct Anthropic or unresolved
    proxy_id: str | None       # Resolved proxy identity (for cost tracking, logging)
    template: str | None       # Proxy template (for tier override awareness)
    source: RoutingSource      # Which chain step resolved this route
    route: ModelRoute | None   # Present when model compatibility is known; None for unresolved or opaque routing
    credential: str | None     # route.credential, duplicated for ergonomics
    warning: str | None = None # Non-fatal diagnostic (e.g., "preferred proxy not running")
```

`direct` and `unresolved` are both "no proxy" but semantically different. `direct` = intentional direct execution
(produced by `review.routing` for direct-only specs like `claude-opus`). `unresolved` = no route found (produced by the
shared resolver as its terminal step). `route` is present when model compatibility is known; `None` can mean unresolved
or opaque/non-model-specific routing (e.g., explicit base URL with no routes supplied). `source` and `base_url`
distinguish them.

### G.2 Workflow types (from `review.routing`)

```python
@dataclass(frozen=True)
class WorkerRoutingPlan:
    routes: tuple[RoutingResult, ...]  # Indexed by worker position (same order as spec list)
    resolved_at: str                   # ISO timestamp for staleness detection
    via_override: str | None           # --proxy value, if set (for logging)
```

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

## H. Transfer Context Schema

Extracted from [design.md §3.9](design.md#39-session-resume-context-management). The transfer document is a stable,
frontmatter-backed Markdown contract produced by `assemble_transfer_context` (`src/forge/session/transfer.py`).

### H.1 Frontmatter (child-agnostic)

Every strategy prepends one YAML block. It carries **no `child` field** — child identity is path-derived, so
`generated.md` and the `children/<child>.md` copy stay byte-identical (the `ensure_child` copy and the auto-name retry
byte-compare in `manager.py` both depend on this).

```yaml
---
forge_transfer:
  schema_version: 1
  parent: <parent-session-name>
  strategy: ai-curated | structured | full | minimal
  schema: full | compatibility-fallback   # "full" only for a successful ai-curated body
  depth: <int>                              # lineage depth (regenerate restores this)
  generated_at: <ISO8601>
  lineage: [<parent>, <grandparent>, ...]
  transcript_artifact: <forge-root-rel path | null>
  token_estimate: <int | null>
  target_runtime: claude                    # claude (default) | codex — shipped (5d relabel, 5e bridge)
---
```

Reads are **best-effort** (`parse_transfer_frontmatter`): the doc is an LLM-consumed artifact with a user-editable
overlay (a system boundary), so missing/malformed frontmatter warns and still returns the body — it never hard-fails.

### H.2 Sections

`ai-curated` emits the full 8-section contract; code owns the skeleton and the model fills section bodies (it returns
structured JSON, parsed with `extract_json_from_response`). Decisions cite a transcript turn (`[turn N]`) or file;
citations are validated against the turn range the model saw and fabricated ones are dropped with a warning
(`_validate_decision_citations`), so `schema: full` does not overstate evidence quality. Sections 1–7 live in the AI
snapshot; section 8 is the separate notes overlay (so the snapshot has 7 headers and the composed launch view has 8):

1. `## Lineage`
2. `## Goal / Current Task`
3. `## Decisions` (cited)
4. `## Current State`
5. `## Relevant Files` (`file:line`)
6. `## Open Questions`
7. `## Runtime Hints`
8. `## User Notes` (overlay)

`minimal | structured | full` keep their existing bodies and set `schema: compatibility-fallback`.

### H.3 File layout and overlay

```
<forge_root>/.forge/prev_sessions/<parent>/generated.md               # parent AI cache (regenerate rewrites)
<forge_root>/.forge/prev_sessions/<parent>/children/<child>.md        # per-child AI snapshot (frozen; never edited)
<forge_root>/.forge/prev_sessions/<parent>/children/<child>.notes.md  # per-child user overlay (the editable surface)
```

The launcher appends the snapshot plus the notes overlay (when it has user content) to one `--append-system-prompt-file`
via `_combine_prompt_files`. `forge transfer regenerate` rewrites only `generated.md`; snapshots and notes are never
overwritten. GC pairs a notes file's liveness to its snapshot — it is never orphaned independently
(`_detect_orphan_transfer_files`).

### H.4 Relationship to `ctx` (prior art)

The transfer schema (§H.1–M.3) is **Forge-owned and canonical**. [`ctx`](https://github.com/dchu917/ctx) is **prior art
and inspiration only** — its concepts (workstreams, exact transcript binding, branching, indexed retrieval, local
storage, curation) informed this substrate. Forge will **not** take `ctx` as a dependency: curated transfer is
load-bearing for Forge's session, policy, and usage story, so its contract lives in-tree. The schema is self-contained
and **no `ctx` interop is planned**. An optional import/export bridge could be built on the existing schema later
without changing it, but that is explicitly not committed work.

---

## I. Codex Runtime Reference

Extracted from [design.md §3.9](design.md#39-session-resume-context-management) and
[design_workflows.md §3.5](design_workflows.md#35-workflow-runners). Lifecycle narrative (headless turns, interactive
TUI sessions, delivery modes, post-exit reconciliation) remains in design.md.

### I.1 Recorded Codex facts (`confirmed.codex`)

All CLI-owned (§3.5):

| Field                                          | Source                                                                                                                     |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `thread_id`                                    | Stream `thread.started` (headless) or post-exit reconciliation (interactive)                                               |
| `rollout_path` / `rollout_source`              | See provenance table below                                                                                                 |
| `auth_method` / `auth_source` / `billing_mode` | Preflight's secret-free auth posture (refreshed per turn)                                                                  |
| `last_run_at`                                  | Per turn                                                                                                                   |
| `context_delivery`                             | `initial_message \| session_start_hook \| hook_undelivered`; `None` for bare interactive starts (a transfer-delivery fact) |

`rollout_source` provenance (the matching file is `$CODEX_HOME/sessions/…/rollout-*-<thread_id>.jsonl`):

- `discovered_by_thread_id`: glob located by a stream-known thread_id.
- `session_start_hook`: a receipt's codex-reported `transcript_path` supersedes the glob; a receipt can also recover a
  `thread_id` the stream missed.
- `discovered_post_exit`: interactive time+cwd discovery — the rollout **filename** is the thread source (filename
  timestamps are local time, so discovery filters by mtime).

`confirmed.launch` and `claude_session_id` stay unset (§3.5).

### I.2 Codex `RuntimeSpec` declarations

Load-bearing values (probe evidence in `scripts/experiments/codex-hooks/README.md`):

- `native_hooks="enrollment_gated"`: hooks fire only after a one-time interactive TUI trust ceremony. Trust keys on the
  registering config's path; `trusted_hash` is not black-box computable, so enrollment is never verifiable pre-turn.
- `pretool_policy="partial"`: post-enrollment PreToolUse deny + `updatedInput` are pinned headless, but enforcement
  exists only in enrolled homes. Malformed hook output fails open; PermissionRequest has not been observed firing.
- `interactive="default"`: Forge-managed interactive sessions (bare TUI start and `codex resume` reattach, §3.9).
- `hook_min_version`: machine-readable registration floor a preflight checks — not a firing guarantee.
- `hook_feature_flag=None`: Codex hooks are default-on.

### I.3 Codex operational guards (probe-churn + enrollment)

Codex's trust/enrollment and `apply_patch`/argv behavior are pinned **empirically**, not contractually, so two
operator-facing guards backstop version churn and the unverifiable trust ceremony:

- **Validated-version ceiling.** `CODEX_VERSION_VALIDATED` (`core/runtime/codex_preflight.py`) names the newest
  codex-cli the probe harness was run against end-to-end. `CodexPreflight.version_beyond_validated` is `True` when the
  installed binary sorts strictly above it; `forge runtime preflight codex` then prints a non-blocking re-probe notice
  (a bump never fails readiness — the facts are just unverified for that version). Mirrors the 4g
  `CLAUDE_VERSION_VALIDATED` guard; bump after a green probe round.
- **Empirical enrollment check.** `forge runtime preflight codex --verify-enrollment` (`core/ops/codex_enrollment.py`)
  confirms user-scope hooks are trust-enrolled by *effect*: it runs one trivial managed `codex exec` turn in a throwaway
  git repo and reports enrolled iff `codex-session-start` fired (the observation receipt appeared). Short-circuits with
  no turn when the answer is already knowable (not ready / not registered); a turn that fails to complete reports
  `UNVERIFIED`, not "not enrolled". Tests **user** scope only (path-stable, one-ceremony-covers-all); project-scope
  hooks need a turn inside the project.
