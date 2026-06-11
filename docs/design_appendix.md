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

**Capability registry** (`src/forge/core/auth/capabilities.py`):

Single source of truth for credential metadata. Key types and functions:

```python
EnvVar(name, required=True, secret=True, connection_value=False, default_value=None)
Credential(name, env_vars, unlocks_features, signup_url, note, not_needed_for)

credentials_for_template(template: str) -> list[Credential]
format_missing_credential_error(credential, *, missing_vars, template=None,
    context=None, extra_hint=None, profile=None, env_ignored=False) -> str
```

`credentials_for_template()` bridges `TEMPLATE_ENV_VARS` (template → env var names) to `CREDENTIALS` (credential →
metadata) via reverse lookup. `format_missing_credential_error()` produces actionable messages with signup URLs,
`forge auth login` commands, and `not_needed_for` disambiguation (rendered for credentials that define it:
`anthropic-api` and `codex-api`).

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

| Path                              | Schema owner                        | Retention policy        |
| --------------------------------- | ----------------------------------- | ----------------------- |
| `~/.forge/costs/requests/*.jsonl` | `forge.proxy.cost_logger`           | Append-only, user-prune |
| `~/.forge/costs/verbs/*.jsonl`    | `forge.core.reactive.cost_tracking` | Append-only, user-prune |

Request records contain timestamp, proxy ID, model/tier, token counts, `cost_micros` (null when no route reported a
cost), request ID, latency, metric-evidence provenance (`reporter` + `confidence`), and the **run-tree correlation**
`forge_run_id`/`forge_root_run_id` (§3.14 / §A.13: null for the interactive harness and any non-Forge-originated
traffic; set when a Forge-routed `claude -p` subprocess forwarded the validated `X-Forge-Run-ID`/`X-Forge-Root-Run-ID`
headers). There is no local price catalog, so cost is reported-or-unavailable, never inferred from tokens. Both fields
are additive at `schema_version: 1` (old readers `.get` them as `None`). Verb records contain timestamp, verb name,
proxy URL/ID when known, before/after snapshots, total cost delta, request count delta, `estimated=true`, and
`cost_measured` (false when the window moved tokens but reported no cost, so a passthrough verb is not read as $0).

The proxy `GET /` endpoint reports in-memory metrics and cost totals for live status. The JSONL request logs remain the
bootstrap source for cap enforcement after restart.

Cap enforcement is process-local. Each proxy process bootstraps from shared JSONL logs at startup, but in-flight spend
is not coordinated across concurrent processes. To coordinate caps across processes, run a single proxy process per
proxy ID.

Cost logs accumulate indefinitely. `forge proxy costs reset` wipes both cost-log planes (`costs/requests/` +
`costs/verbs/`) **and** the usage-attribution ledger (`usage/events/`) to zero in one step, and clears the derived
status-line cost cache (`cache/statusline/fcost-*.json`) so `forge +$Y` does not replay a cached value (audit records
are a separate plane and are left untouched); it prompts for confirmation unless `--yes`, and `--dry-run` previews. You
can also delete individual JSONL files under `~/.forge/costs/` by hand. Either way, a running proxy keeps its cost
totals and cap counters in memory until restarted — it re-bootstraps from the remaining logs at next startup, so restart
any active proxy to also zero its live cumulative cost and cap enforcement.

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

### A.11 Intercept and audit configuration (§7.x)

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
```

| Field                                      | Values                                       | Meaning                                                                 |
| ------------------------------------------ | -------------------------------------------- | ----------------------------------------------------------------------- |
| `wire_shape`                               | `openai_translated`, `anthropic_passthrough` | Wire truth; passthrough preserves thinking blocks (signature-safe)      |
| `intercept.mode`                           | `passthrough`, `inspect`, `override`         | `override` requires `wire_shape: anthropic_passthrough`                 |
| `intercept.override.system_prompt_augment` | string                                       | Cache-aware system-prompt insert (after the last `cache_control`)       |
| `intercept.override.system_prompt_guards`  | list of `{pattern, action}`                  | `pattern` is a regex (compiled at config load); action warn/block/strip |
| `audit.audit_full_body`                    | bool (default `false`)                       | Capture redacted bodies; there is **no** raw-body mode                  |
| `audit.redact_headers`                     | list of strings                              | Extra header names to redact beyond the built-in denylist               |
| `audit.retention_days`                     | int                                          | Prune shards older than N days at proxy startup                         |
| `audit.max_total_mb`                       | int                                          | Prune oldest shards once total exceeds N MB at startup                  |

Reasoning-effort pinning in override mode **reuses** `tier_overrides.<tier>.reasoning_effort` (§A.1) — it is not a new
`intercept` key. `forge proxy set <id> intercept.mode=inspect` (and `audit.audit_full_body=true`, which prints a privacy
warning naming `~/.forge/audit/`) edits these via the normal proxy surface.

---

### A.12 Audit log schema (§7.x)

Records are persisted **already redacted** (the typed builders redact headers/bodies before calling the writer, which
only appends). The no-plaintext-secret guarantee is regression-tested
(`tests/regression/test_bug_audit_header_redaction_no_leak.py`).

| Path                                            | Owner                      | Notes                                           |
| ----------------------------------------------- | -------------------------- | ----------------------------------------------- |
| `~/.forge/audit/requests/<YYYY-MM>_<pid>.jsonl` | `forge.proxy.audit_logger` | Owner-only 0600, append-only, PID-sharded       |
| `~/.forge/proxies/<id>/audit_state.json`        | drift baseline (host)      | `schema_version`, `last_seen` hash map          |
| `~/.forge/audit/state/<id>.json`                | drift baseline (sidecar)   | Same shape; the config dir is mounted read-only |

Every record carries `schema_version`, `ts`, `request_id`, `proxy_id`, and a `record_type`:

| `record_type` | Key fields                                                                                                                                                                                                                                                                                                                                                                      |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `request`     | `mode`, `route`, `full_body`, `system_prompt_hash`, `tool_surface_hash`, `thinking`, `cache_markers`, `counts`; full-body adds the redacted `request_headers/body` (every path) and `response_headers/body` (structure only) **only for non-streaming passthrough** — streaming captures response usage metadata only; the translated path is request-body only (both deferred) |
| `drift`       | `dimension` (`system_prompt`\|`tool_surface`), `previous_hash`, `current_hash`, `route`                                                                                                                                                                                                                                                                                         |
| `mutation`    | `mode: override`, `blocked`, `system_prompt_hash_before/after`, `mutations[]` (each `{target, action, ...}` with `augment_len` / `cache_invalidation_expected` / `pattern_hash` / `stripped_count` / `effort_floor` / `budget_before/after`) — hashes, lengths, and budgets only                                                                                                |

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

**Read surface — `forge activity` and the session-end summary.** `read_usage_events(..., session=<name>)` filters the
ledger by the `session` field; `forge.core.ops.usage_summary.build_session_activity_summary(name, forge_root, since=)`
aggregates it with the manifest's `confirmed.policy.decisions` into a `SessionActivitySummary` (ledger -> per-command
`CommandUsage` run/error/token/cost rows; decisions -> `PolicyActivity` supervisor allow/warn/deny + warnings, with
`log_capped` when the decision log hit `MAX_DECISION_LOG`). The builder re-reads the manifest fresh from disk because
hooks mutate `confirmed.*` during the run. `forge activity [session]` renders a table (`--json`/`--days`/`--all`); the
launcher prints a one-line `render_summary_line(...)` on exit (host, sidecar, fork). Cost is reported-or-estimated
(best-effort; the verb-snapshot aggregate contributes estimates) and may be partial (`cost_partial`);
`forge proxy costs show` is authoritative.

Per-emitter session coverage (a per-session summary is honest about what it can attribute):

| Emitter                                                        | Tags `session`? | Notes                                                                                    |
| -------------------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------- |
| Semantic supervisor (`emit_usage_for_session_result`)          | Yes             | `session=context.session_name` (= manifest name)                                         |
| Memory writer (`emit_usage_for_session_result`)                | Yes             | `session=session_name`                                                                   |
| Workflow verbs panel/analyze/debate/consensus                  | Yes             | threaded `session=$FORGE_SESSION` (verb aggregate + per-worker)                          |
| Transfer curation (`emit_direct_llm_usage`, `transfer-curate`) | Yes             | `session=$FORGE_SESSION`; ai-curated strategy only; `route=core_llm`/`runtime=forge_cli` |
| Plan check (`emit_direct_llm_usage`, `plan-check`)             | Yes             | cascade tier-1; `session=context.session_name`; `route=core_llm`                         |
| Action tagger (`emit_direct_llm_usage`)                        | No              | policy-internal classification; left untagged (`session_tagging_partial`)                |

**Sidecar.** When a sidecar session launches with a proxy id, the launcher mounts `~/.forge/usage/` rw alongside
`audit/` + `costs/` (§7), so the in-container supervisor/verb events survive the `--rm` container and a sidecar
session-end summary + `forge activity` show the full ledger half, not just the policy-decision half. Template-only
sidecars (no proxy id) mount none of these, so their ledger events stay ephemeral — consistent with how they already
drop audit/costs.

---

## B. Direct Command Reference

Extracted from [design.md §3.11](design.md#311-direct-commands-userpromptsubmit-dispatcher). Design goal, mechanism, and
scope rationale remain in design.md.

### B.1 Scope policy table

| Category              | Allowed via `%`                                                                                                     | Not allowed via `%`                                           |
| --------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Session / plan        | `%session list`, `%plan`                                                                                            | --                                                            |
| Proxy                 | `%proxy list`, `%proxy show`, `%proxy audit show/diff` (read-only)                                                  | `%proxy create`, `%proxy edit`, `%proxy set`, `%proxy delete` |
| Policy / verification | `%policy status`, `%policy enable`, `%policy disable`, `%policy check`, `%policy supervise`, `%cancel-verification` | --                                                            |
| Cleanup               | `%clean [--scope workspace\|project\|all]` (read-only report)                                                       | destructive cleanup (use `forge clean --yes` from terminal)   |
| Utilities / config    | `%h`, `%help`, `%config`                                                                                            | --                                                            |

### B.2 Current shipped commands

%-only utilities:

- `%h` / `%help`: show direct command help
- `%config`: show effective runtime config (read-only)

Shared commands (mirrors CLI syntax):

- `%session list` (calls the same command-core op as `forge session list`)
- `%plan` (shows the current session's recorded plan file path)
- `%proxy list` (read-only: shows available proxies)
- `%proxy show <id>` (read-only: shows proxy details and tier mappings)
- `%proxy audit show|diff [id]` (read-only: recent audit metadata / wire changes; metadata only, never secrets)
- `%policy status` (shows current policy config and state)
- `%policy enable --bundle tdd [--permissive]` (enables policy enforcement)
- `%policy disable` (disables all policies for the session)
- `%policy check [--staged] [--bundle <name>]` (diagnostic policy evaluation against git diff)
- `%policy supervise <target>` (set supervisor), `off` (suspend), `on` (resume), `remove` (delete)
- `%policy supervise reload [path]` (reload latest approved plan, or from explicit path)
- `%cancel-verification` (bypasses the active Stop-hook verification loop)
- `%clean [--scope workspace|project|all]` (read-only: shows orphaned state report, default scope=project)

---

## C. Work Queue Internals

Extracted from [design.md §3.13](design.md#313-async-work-queue). Design goals and rationale remain in design.md.

### C.1 Marker schema (v2)

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
session rather than the draining CLI (§F.5).

### C.2 Processing contract

Handlers are passed explicitly as a `handlers` dict (no global registry -- avoids import-order coupling and test state
leakage): `process_pending_work(handlers={"stop": handler, "index": handler})`.

| Outcome                             | Behavior                                                                |
| ----------------------------------- | ----------------------------------------------------------------------- |
| Handler succeeds                    | Delete marker under lock                                                |
| Handler raises                      | Keep marker, increment `attempt_count`, write `last_error` under lock   |
| Lock contention                     | Skip (another process holds it)                                         |
| No handler for kind                 | Skip, log warning (leave in place)                                      |
| `attempt_count >= MAX_ATTEMPTS` (5) | Move to `pending-work/failed/` (poison marker, preserved for debugging) |

### C.3 Known marker kinds

| Kind      | Producer            | Handler                                 |
| --------- | ------------------- | --------------------------------------- |
| `stop`    | Stop hook           | No-op (delete only)                     |
| `index`   | Stop hook           | Index transcript for search             |
| `handoff` | Stop hook (planned) | Spawn the memory writer for memory docs |

---

## D. Policy Internals

Extracted from [design.md §4.1](design.md#41-policy-enforcement). Policy type definitions, supervisor mechanism,
verification loop, and action context remain in design.md.

### D.1 Shared library scope (from §4.1.2)

| Utility            | Extracted from                      | API                                                                                   |
| ------------------ | ----------------------------------- | ------------------------------------------------------------------------------------- |
| Session runner     | `supervisor.py`, `memory_writer.py` | `run_claude_session(prompt, resume_id?, model?, base_url?, timeout, unset_env_vars?)` |
| Proxy resolution   | both                                | `resolve_base_url(proxy_id?, explicit_url?, fallbacks)`                               |
| Throttle cache     | `policy/store.py`                   | `ThrottleCache(ttl).check(key) / .update(key, value)`                                 |
| Structured output  | `verdict.py`                        | `extract_json_verdict(stdout, schema)`                                                |
| Tagger             | new                                 | `tag_action(context, model, prompt) -> tags[]`                                        |
| Env builder        | both                                | `build_claude_env(base_url?) -> dict`                                                 |
| Fan-out runner     | `src/forge/review/engine.py`        | `run_multi_review(prompt, models, per_worker_prompts?)`                               |
| Adversarial runner | `src/forge/review/adversarial.py`   | `run_adversarial(proposal, skill_resource, stances, models)`                          |

### D.2 Example: Writing a new policy (from §4.1.2)

A developer adding a policy imports a few utilities and writes a class. Three abstract properties are required:
`policy_id`, `description`, and `intent` (see §4.1.1).

```python
# Example: block database migrations without review
from forge.core.reactive import tag_action, run_claude_session, ThrottleCache

class MigrationReviewPolicy(DeterministicPolicy):
    policy_id = "custom.migration_review"
    description = "Require review for database migrations"
    intent = "Prevent unreviewed schema changes from reaching production"

    def applies_to(self, ctx):
        return ctx.tool_name == "Write" and "migration" in (ctx.target_path or "")

    def _evaluate(self, ctx):
        tags = tag_action(ctx, model="haiku", prompt="Is this a schema migration? tags: migration | safe")
        if "migration" not in tags:
            return self._allow()
        verdict = run_claude_session(prompt=REVIEW_PROMPT.format(...), resume_id=config.resume_id)
        return verdict_to_decision(verdict)
```

On deny, the message includes the `intent` so models understand why the policy exists and can surface conflicts to the
user rather than working around the check.

### D.3 Policy definition ownership (from §4.1.6)

| Setting                                             | Owner   | Location                                                                                         |
| --------------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------ |
| Supervisor model (which model to use as supervisor) | Proxy   | `~/.forge/proxies/<id>/proxy.yaml`                                                               |
| Throttling settings (check frequency)               | Proxy   | `~/.forge/proxies/<id>/proxy.yaml`                                                               |
| TDD mode (off/permissive/strict)                    | Session | Session file `intent.tdd_mode`                                                                   |
| Policy enabled/disabled                             | Session | Session file `intent.policy_mode`                                                                |
| Verification config                                 | Session | Session file `intent.verification`                                                               |
| Cascade on/off + tier-1 checker route/budget        | Session | `intent.policy.supervisor.cascade`/`.checker_provider`/`.checker_model`/`.checker_budget_tokens` |

### D.4 Policy state ownership (from §4.1.6)

| State                                     | Owner           | Location                                         |
| ----------------------------------------- | --------------- | ------------------------------------------------ |
| Enforcement decisions                     | Session (hooks) | `confirmed.policy` in session file               |
| Cached verdicts (supervisor + plan-check) | Session (hooks) | `confirmed.policy.policy_states` in session file |
| "Tests touched" tracking                  | Session (hooks) | `confirmed.policy` in session file               |
| Verification iteration                    | Session (hooks) | `confirmed.verification.iterations`              |
| Last verification result                  | Session (hooks) | `confirmed.verification.last_result`             |

---

## E. Install Model Reference

Extracted from [design.md §5.1-5.4](design.md#5-extensions-install-model). Overview remains in design.md.

### E.1 Scope model (§5.1 -- mirrors Claude Code)

| Scope     | Extensions Path                       | Settings Path                 | Use case                                           |
| --------- | ------------------------------------- | ----------------------------- | -------------------------------------------------- |
| `user`    | `~/.claude/{commands,agents,skills}/` | `~/.claude/settings.json`     | Personal global (default; prevents worktree drift) |
| `project` | `.claude/{commands,agents,skills}/`   | `.claude/settings.json`       | Team-shared (checked in)                           |
| `local`   | `.claude/{commands,agents,skills}/`   | `.claude/settings.local.json` | Personal per-project                               |

### E.2 Installable modules + profiles (§5.2)

| Module        | Installs                                           | Notes                                                        |
| ------------- | -------------------------------------------------- | ------------------------------------------------------------ |
| `commands`    | Slash commands markdown                            |                                                              |
| `agents`      | Subagents markdown                                 |                                                              |
| `skills`      | Skills (SKILL.md + resources/scripts)              | Scripting layer for Forge workflows (see §5.5)               |
| `hooks`       | Hook settings entries (invoke `forge hook ...`)    | No hook scripts installed; requires `hooks.*` settings merge |
| `status-line` | `statusLine` setting (invokes `forge status-line`) | No scripts installed; same pattern as hooks                  |
| `permissions` | Forge-required permission entries                  | Merged as unions                                             |

Profiles:

- `minimal`: `commands`
- `standard`: `commands`, `agents`, `skills`, `hooks`, `permissions`, `status-line` (default)
- `full`: all modules (same as standard; reserved for future heavy modules)

### E.3 Settings merge rules (§5.3 -- normative)

| Setting             | Merge behavior                                             |
| ------------------- | ---------------------------------------------------------- |
| `hooks.*`           | Append + dedupe by command path (invokes `forge hook ...`) |
| `permissions.allow` | Union unique entries                                       |
| `permissions.deny`  | Union unique entries                                       |
| `statusLine`        | Scalar merge; conflict fails unless `--force`              |
| `model`             | Never touched                                              |

All settings modifications must be backed up first (`settings.json.forge-backup`).

### E.4 Tracking file (§5.4 -- `~/.forge/installed.json`)

The installer must track what it changed so:

- `forge extension sync` updates only tracked items
- `forge extension disable` removes only tracked files and reverts only Forge-added settings entries

### E.5 Multi-scope installation (§5.5 -- skill resolution)

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

---

## F. Workflow Runner and Skill Details

Extracted from [design.md §5.5.5-5.5.9](design.md#555-workflow-runners). Three-layer architecture, four runner types,
design principles, skills-vs-policies relationship, and CLI surfaces remain in design.md.

### F.1 Fan-out runner details (from §5.5.5)

`run_multi_review()` in `src/forge/review/engine.py`:

- N workers, each with model/proxy via `ModelSpec`
- Per-worker prompt via `ModelSpec.prompt`
- Per-worker context: `--context resume:<id>` or `--context blind`
- Direct Claude workers use `ANTHROPIC_MODEL` plus `ANTHROPIC_DEFAULT_*_MODEL`, not Claude CLI `--model`
- Parallel via `ThreadPoolExecutor` + process group cleanup
- Workers receive pre-resolved `RoutingResult` from a `WorkerRoutingPlan` (see [§L](#l-subprocess-routing-reference))
- `/forge:analyze`: single-model fan-out with an analyze resource

### F.2 Adversarial runner details (from §5.5.5)

Adversarial runner:

- Constrained to review/eval skills (stance injection)
- Inject stance via `{stance_prompt}` in resources
- Mandatory blinding: proposal + files only (no peer outputs)
- Stances: for/against/neutral with guardrails (lens, not honesty)
- Synthesize agreement vs disagreement; evidence-weighted recommendation

Adversarial-compatible skills include `{stance_prompt}` in their resource .md; `/forge:debate` enforces this.

### F.3 Panel engine details (from SS5.5.7)

Panel is the reference invocation of the fan-out runner. It fans out a review task to N models via different proxies and
collects independent findings for synthesis.

**Engine:** `forge workflow panel` CLI command.

Spawns N `claude -p` subprocesses, each with a different `ANTHROPIC_BASE_URL`. Routing for all panel workers is resolved
once at invocation start via `resolve_invocation_routing()` (see [§L](#l-subprocess-routing-reference)). Each reviewer
is a full Claude Code agent -- it can read files, investigate, and find issues with real file:line evidence.

**Execution:** Fork mode gives each reviewer the main agent's full context. Summary mode sends a focused prompt.

**Target-based review:** Positional `target` argument loads a bundled review framework (docreview.md by default,
codereview.md with `--code`). Combined with per-worker prompt support (`ModelSpec.prompt`), this enables specialized
fan-out patterns -- code review, document review, security audit -- all using the same runner.

**Synthesis:** The main agent reads all N reviews and synthesizes -- identifying consensus findings (2+ models agree),
unique insights, and conflicts. Because the main agent has full project context, it can **investigate conflicts** by
reading the disputed code -- something external synthesis (which merges text without context) cannot do.

**`/forge:analyze` as degenerate fan-out:** Single-model fan-out with an analyze-specific resource. Same panel engine
with N=1. The resource instructs the model to act as a senior engineering collaborator with deep analysis guidelines.

**Dual use:** The panel serves as both a skill (`/forge:panel src/session/ --code`) and a policy (automatic multi-model
gate before committing). Same `run_multi_review()` function, two callers -- the programmer wires both.

### F.4 Debate / adversarial reference skill (from SS5.5.8)

Debate is the reference invocation of the adversarial runner. It assigns stances to workers, blinds them from each
other, and synthesizes by weighing agreement against disagreement.

**Stances:** Each worker receives a stance directive (for/against/neutral) injected via `{stance_prompt}` in the
evaluation template. Stances influence the evaluative lens, not honesty -- all stances include ethical guardrails that
override positional framing (a "for" evaluator must still flag genuine critical issues).

**Blinding:** Each worker sees only the original proposal + files + stance prompt. Workers never see other workers'
output. Achieved by spawning separate `claude -p` processes without `--resume` (no shared session context).

**Skill constraint:** Only review/evaluation skills are adversarial-compatible. The runner checks for a
`{stance_prompt}` marker in the evaluation resource and rejects resources without it. This prevents misuse (adversarial
code generation makes no sense).

**Templates:** Two debate evaluation frameworks (embedded in CLI): a proposal evaluation template (7-point: feasibility,
correctness, trade-offs, risks, completeness, alternatives, recommendation) and a code evaluation template (5-point:
quality, security, performance, architecture, risks). `--code` selects the code template. Both produce structured
verdict output (Verdict/Confidence/Key Findings).

**Execution flow:** Parse subject -> select template (proposal or code via `--code`) -> fill template with subject ->
write to temp file -> N x adversarial runner with stance injection -> collect results -> synthesize (agreement areas,
disagreement areas, evidence-weighted recommendation). Temp file cleaned up via try/finally.

### F.5 Operational constraints (from §5.5.9)

**Recursion guard:** Skills invoke `forge` commands. `forge` commands spawn `claude -p` subprocesses. Those subprocesses
trigger hooks. If a hook spawns another subprocess, you get recursion. `build_claude_env()` sets `FORGE_DEPTH` (starting
at 0, incremented per subprocess layer). Hooks that spawn subprocesses (supervisor, memory writer) skip at depth >= 2.

**Run-tree identity (attribution, orthogonal to the recursion guard):** alongside `FORGE_DEPTH`, `build_claude_env()`
stamps `FORGE_RUN_ID` (this process), `FORGE_PARENT_RUN_ID` (the spawner), and `FORGE_ROOT_RUN_ID` (the tree root). A
child inherits the root and sets its parent to the spawner's run_id; an interactive launch (session start/resume/fork,
bare `forge claude start`) and the sidecar instead mint a fresh root (`invoke._build_environment` / `container.py`, via
`derive_run_identity=False`). Depth guards recursion; identity records who-spawned-whom for the usage ledger — the two
are independent and `FORGE_DEPTH` is never reinterpreted. The queue-decoupled memory writer is the one spawn where env
inheritance breaks: the Stop hook snapshots the originating session's run id into the handoff marker (§C.1) and the
drain handler re-roots the detached process under it, not under the unrelated draining CLI.

**JSON output contract:** `forge` commands invoked by skills must support `--json` for structured output. Skills should
never parse human-readable CLI text -- it drifts. JSON schemas are the API contract between skills and CLI.

**Child process lifecycle:** Parallel fan-out (panel runner) spawns N `claude -p` processes. If the parent is killed
(Ctrl+C), children must be terminated via process group signal (`os.killpg`). All child processes must have timeouts
(the `timeout_seconds` parameter in `run_claude_session()`).

**Skill script dependency tiers:** Skills are installed by file copy (`forge extension enable`), not as Python packages.
Scripts in `skills/*/scripts/` have no access to `forge.*` imports or third-party deps. Three tiers handle this:

| Tier               | When                                                | How                                                    | Example                                |
| ------------------ | --------------------------------------------------- | ------------------------------------------------------ | -------------------------------------- |
| Pure stdlib        | Script needs only Python builtins                   | `python3 script.py`                                    | `walkthrough-state.py`                 |
| Forge CLI command  | Script needs `forge.*` or third-party deps          | `forge <group> <cmd>`                                  | `forge hook stop`, `forge status-line` |
| `uv run` + PEP 723 | Script needs 1-2 external deps, not worth a CLI cmd | `uv run script.py` with inline `# /// script` metadata | --                                     |

**Graduation rule:** When a pure-stdlib script needs deps, promote it to a Forge CLI command (one step, no intermediate
stages). This follows the hooks pattern: `forge hook <name>` runs as a CLI command with full package deps, not as an
installed script. The same principle applies to skill scripts.

---

## G. Memory Doc Reference

Extracted from [design.md §5.6](design.md#56-designated-memory-docs). Passport model, operating modes, and the memory
writer concept remain in design.md.

### G.1 Strategy registry (from §5.6.5)

Strategies are defined in `MemoryStrategy` enum (`src/forge/session/passport.py`).

**Direct update strategies:**

| Strategy        | Behavior                                         |
| --------------- | ------------------------------------------------ |
| `project-state` | Update focus, active work, decisions, next steps |
| `checklist`     | Mark `[x]` completed, add discovered tasks       |
| `changelog`     | Add accomplishments, follow existing format      |
| `generic`       | Add any new information (default fallback)       |

Shadow mode (`--propose`) is orthogonal to strategy: any strategy works with `--propose`.

### G.2 Passport example (from §5.6.2)

Memory doc passports are `forge_memory` YAML frontmatter blocks. The passport is the doc-level source of truth for
strategy, writers, and update mode.

```yaml
---
forge_memory:
  version: 1
  intent: "Human-approved durable implementation memory for future Forge sessions."
  captures: [stable decisions, non-obvious invariants, recurring bug causes]
  excludes: [raw session summaries, pending tasks, unverified hunches]
  update:
    strategy: generic
    mode: shadow-only
    writers: all-sessions
    approval: human-promoted
    shadow_path: .forge/memory/shadow_impl_notes.md
---
```

**CLI setup** (equivalent to the passport above):

```bash
# Passports are project-lifetime and sessionless:
forge memory track docs/board/change_log.md --strategy changelog
forge memory track docs/board/impl_notes.md \
  --propose --shadow-path .forge/memory/shadow_impl_notes.md

# Enable memory for a session:
forge memory enable --session planner

# Verify:
forge memory passport show docs/board/change_log.md
forge memory list
```

`forge memory track` is idempotent and sessionless: re-running with different flags updates the passport in place; with
no flags on an already-passported doc it is a no-op. `forge memory passport remove <path>` removes the passport and
turns the file back into a normal doc, preserving unrelated frontmatter. One-off doc updates that don't need a passport
are ordinary agent instructions. All docs are processed in one `claude -p` call with per-doc strategy instructions.

### G.3 Worktree resolution (extends §5.6.5)

Managed sessions always launch from `forge_root`. The memory writer resolves designated doc paths relative to
`forge_root`, so git-tracked docs (for example, a card checklist under `docs/board/doing/<slug>/checklist.md`) target
the correct branch when working in a worktree.

Trackedness is controlled by path choice; the agent doesn't distinguish:

- `docs/board/doing/<slug>/checklist.md` -> git-tracked, branch-specific (moves with the branch)
- `.forge/memory/debugging.md` -> untracked, per-Forge-project (`.forge/` is in `.gitignore`)
- `docs/suggested/coding_standards.md` -> git-tracked shadow doc (visible in PRs if desired)

Shadow docs also resolve relative to `forge_root`, so the agent reads the branch-correct official doc.

**Transcript path handling:** Transcripts live under `<forge_root>/.forge/artifacts/`. Because `cwd` is `forge_root`,
transcript paths in the prompt must be **absolute**; designated doc paths remain relative (resolved against `cwd`).

> **Note:** Artifacts (transcripts/plans) consolidate at `forge_root` for per-project visibility. Designated docs are
> working documents and belong with branch content.

### G.4 Comparison with Claude Code auto-memory (from §5.6.5)

Claude Code (Feb 2026) ships **auto-memory**: Claude writes free-form notes to `~/.claude/projects/<project>/memory/`
during sessions. `MEMORY.md` (first 200 lines) loads at startup; topic files load on demand.

Forge's memory writer is complementary, not competitive:

| Aspect          | Auto-Memory                  | Memory Writer                              |
| --------------- | ---------------------------- | ------------------------------------------ |
| Timing          | During session (incremental) | After session (retrospective)              |
| Signal quality  | In-the-moment judgment       | Full-session hindsight                     |
| Structure       | Free-form, model-organized   | Per-doc strategies with constraints        |
| Target files    | User-local memory dir        | Project docs (repo-tracked, shareable)     |
| Curation        | None -- entries accumulate   | Shadow pattern provides human review gate  |
| Graduation path | None                         | Shadow doc -> human review -> official doc |

**Key design rationale:** Free-form capture relies on model judgment and tends to accumulate noise over time. The memory
writer reduces this via (a) retrospective synthesis, (b) per-doc topic constraints, and (c) the shadow pattern (human
curation gate).

Auto-memory is better for long-lived preferences; the memory writer is better for structured project docs and proposed
standards evolution.

**Deliberate non-integration:** The memory writer does not read auto-memory (`~/.claude/projects/<project>/memory/`) as
input. It's outside the project root (containment guard), is free-form (hard to dedupe against structured strategies),
and targets different information (preferences/patterns vs project state/standards). Occasional duplication is cheaper
than cross-format deduplication. If overlap becomes painful, a small prompt tweak can address it.

### G.5 Session activation (from §5.6.6)

Memory activation is session-scoped. The effective `memory.auto_update.enabled` (intent + overrides via
`compute_effective_intent()`) is the sole gate. No checkout-level config file.

| Field                   | Type        | Default   | Meaning                                    |
| ----------------------- | ----------- | --------- | ------------------------------------------ |
| `auto_update.enabled`   | bool        | `false`   | Whether the memory writer runs at Stop     |
| `auto_update.mode`      | str         | `augment` | `augment` (edit) or `review-only` (report) |
| `auto_update.min_turns` | int         | `5`       | Skip sessions shorter than this            |
| `auto_update.proxy`     | str \| null | `null`    | Optional `proxy_id` for the memory writer  |

Scan roots are hardcoded: `DEFAULT_SCAN_ROOTS = ("docs/",)` plus always `.forge/memory/`. Configurable roots deferred.

**Stale `.forge/memory.yaml`**: existing checkouts may have this file from a previous version. It is no longer read.
Safe to delete.

**Stale `designated_docs` in manifests**: old session manifests may contain `designated_docs` entries. These are
stripped on read with a one-time `logger.warning()` per coding-standards §5. The field no longer exists on
`MemoryIntent`.

---

## H. (Removed)

CLI patching was removed for the OSS release. Forge now uses the native `CLAUDE_CODE_AUTO_COMPACT_WINDOW` env var to
control compaction timing in proxy mode.

---

## I. Interactive Manual Testing

Extracted from [design.md §5.8](design.md#58-interactive-manual-testing). Rationale, three-skill table, three-window
model, and key design decisions remain in design.md. See also [testing-guidelines.md](developer/testing-guidelines.md)
for the full testing reference.

### I.1 Annotation types

| Annotation               | Session A does                                 | User does                              |
| ------------------------ | ---------------------------------------------- | -------------------------------------- |
| `<!-- auto -->`          | Runs command via wrapper, checks assertions    | Nothing                                |
| `<!-- human:confirm -->` | Runs command, shows output                     | Eyeballs output in Session A, confirms |
| `<!-- human:guided -->`  | Tells user what to do in Session B or Terminal | Does it, reports back to Session A     |
| `<!-- requires: X -->`   | Checks infra probe                             | Skip if unavailable                    |
| `<!-- destructive -->`   | Runs command (safe in sandbox)                 | Nothing                                |

### I.2 Wrapper abstraction

| Skill                | Wrapper                        | Isolation                        |
| -------------------- | ------------------------------ | -------------------------------- |
| `/forge:walkthrough` | `bash run-in-repo.sh <cmd>`    | env redirection + 4 safety gates |
| `/forge:qa`          | `docker exec $CONTAINER <cmd>` | OS-level container boundary      |

**Three-window model:** Session A prompts the user to open Terminal early. Session B is launched only when the checklist
first needs interactive verification.

### I.3 Per-skill details

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

## J. Shared LLM Client (`src/forge/core/llm/`)

`AnthropicClient` deferred; currently uses `OpenAIClient` for all providers via LiteLLM.

**Purpose:** Unified async-first LLM client abstraction for Proxy, Policy, and Skills components.

### J.1 Design principles

1. **Async-first**: All clients async; sync usage via `SyncAdapter` wrapper
2. **Canonical types**: `Message`, `CompletionResponse`, `StreamEvent` -- no raw dicts
3. **Injectable credentials**: `CredentialManager` with TTL caching, testable
4. **Separation**: LLM calls only; tier orchestration stays in Proxy

### J.2 Module structure

```text
src/forge/core/llm/
├── types.py        # Message, StreamEvent, ModelHyperparameters, ToolCall
├── protocols.py    # LLMClient protocol
├── credentials.py  # CredentialManager (injectable singleton)
├── errors.py       # NoApiKeyError, AuthenticationError, ProviderError
└── clients/        # LiteLLMClient
```

### J.3 Core types (signatures)

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

### J.4 Client protocol

```python
class LLMClient(Protocol):
    @property
    def model(self) -> str: ...
    async def complete(self, messages: list[Message], *, tools=None, hyperparams=None) -> CompletionResponse: ...
    async def stream(self, messages, *, tools=None, hyperparams=None) -> AsyncGenerator[StreamEvent, None]: ...
    async def count_tokens(self, messages, tools=None) -> int: ...
```

### J.5 Factory and provider detection

```python
def get_client(model: str, *, provider: ProviderType | None = None) -> LLMClient:
    """Sync factory, async methods. Provider auto-detected from model prefix."""
    # vertex_ai/, openai/, anthropic/ -> litellm_remote
    # gemini/ -> litellm_local
```

### J.6 Sync adapter

```python
class SyncAdapter:
    """Wraps async client for sync contexts. Uses asyncio.run() -- cannot nest in event loop."""
    def ask(self, prompt: str, *, system: str | None = None) -> str: ...
```

> **Trap:** Policy uses `SyncAdapter`; Proxy is async. Don't import sync Policy logic into Proxy -- `asyncio.run()`
> crashes in running loop. Use async-first at boundaries.

### J.7 Unsupported parameter policy

| Mode                     | Behavior                         |
| ------------------------ | -------------------------------- |
| `strict=False` (default) | Warn + ignore unsupported params |
| `strict=True`            | Raise `UnsupportedParamError`    |

### J.8 Relationship to Proxy

| Concern                        | Owner              |
| ------------------------------ | ------------------ |
| LLM API calls, auth, streaming | `core.llm`         |
| Tier mappings, templates       | `proxy.templates`  |
| Format conversion              | `proxy.converters` |

---

## K. WorkflowPolicy Cost Model

Migrated from the former archived Appendix C. Contextualizes why the tagger->checker->reviewer pipeline (design.md
§4.1.2) uses a branching architecture.

Cost model for a divergence-from-mean workflow: tagger ($0.001/call) filters 80% of changes as non-architectural. Of the
20% that reach a checker ($0.001), ~80% short-circuit as aligned. Only ~4% reach the reviewer ($0.05). Total: ~$0.32/100
changes vs $5.00 reviewing everything.

---

## L. Subprocess Routing Reference

Extracted from [design.md §3.6.12](design.md#3612-subprocess-routing-resolution-normative). Resolution chain concept,
fail-open/fail-closed semantics, and per-invocation routing plan remain in design.md.

### L.1 Core types (from `core.reactive.routing`)

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
    credential: str            # Credential from capabilities.py (e.g., "openrouter", "anthropic-api")
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

### L.2 Workflow types (from `review.routing`)

```python
@dataclass(frozen=True)
class WorkerRoutingPlan:
    routes: tuple[RoutingResult, ...]  # Indexed by worker position (same order as spec list)
    resolved_at: str                   # ISO timestamp for staleness detection
    via_override: str | None           # --proxy value, if set (for logging)
```

### L.3 Key function signatures

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

### L.4 Route derivation ranking

`derive_model_routes()` produces routes in deterministic order:

1. preferred_proxy match first (if it matches a derived route)
2. provider_refs order (from `ModelSpec.provider_refs`)
3. Native-family templates before OpenRouter passthrough cross-family templates
4. Alphabetical template name tiebreaker

Registry scan then ranks matched proxies:

1. Route preference order (from `derive_model_routes()` ranking above)
2. Alphabetical proxy_id as tiebreaker

### L.5 Sidecar constraints

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

## M. Transfer Context Schema

Extracted from [design.md §3.9](design.md#39-session-resume-context-management). The transfer document is a stable,
frontmatter-backed Markdown contract produced by `assemble_transfer_context` (`src/forge/session/transfer.py`).

### M.1 Frontmatter (child-agnostic)

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

### M.2 Sections

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

### M.3 File layout and overlay

```
<forge_root>/.forge/prev_sessions/<parent>/generated.md               # parent AI cache (regenerate rewrites)
<forge_root>/.forge/prev_sessions/<parent>/children/<child>.md        # per-child AI snapshot (frozen; never edited)
<forge_root>/.forge/prev_sessions/<parent>/children/<child>.notes.md  # per-child user overlay (the editable surface)
```

The launcher appends the snapshot plus the notes overlay (when it has user content) to one `--append-system-prompt-file`
via `_combine_prompt_files`. `forge transfer regenerate` rewrites only `generated.md`; snapshots and notes are never
overwritten. GC pairs a notes file's liveness to its snapshot — it is never orphaned independently
(`_detect_orphan_transfer_files`).

### M.4 Relationship to `ctx` (prior art)

The transfer schema (§M.1–M.3) is **Forge-owned and canonical**. [`ctx`](https://github.com/dchu917/ctx) is **prior art
and inspiration only** — its concepts (workstreams, exact transcript binding, branching, indexed retrieval, local
storage, curation) informed this substrate. Forge will **not** take `ctx` as a dependency: curated transfer is
load-bearing for Forge's session, policy, and usage story, so its contract lives in-tree. The schema is self-contained
and **no `ctx` interop is planned**. An optional import/export bridge could be built on the existing schema later
without changing it, but that is explicitly not committed work.
