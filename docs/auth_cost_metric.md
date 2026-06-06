# Internal Audit Map — Auth, Cost & Metrics Seams

A code-grounded map of every surface in Forge that resolves credentials, records cost, or reports usage/metrics, and the
correlation between them. Written **for implementers**, to answer recurring questions like "why does the status line
show dollars when I'm on a subscription?" without re-reading the tree each time.

> **This is a supporting internal map, not the contract.** For **shipped, normative** behavior see:
>
> - `design.md §3.14` — cost telemetry, spend caps, three-plane model, per-session read surface
> - `design_appendix.md §A.8` — status-line billing honesty (`cost_mode`, `forge_cost`, launch metadata)
> - `design_appendix.md §A.9` — proxy cost config + post-event cap enforcement
> - `design_appendix.md §A.13` — usage-attribution ledger (`route`/`reporter`/`confidence`, emitters, read surface)
>
> Where this map and the design docs disagree, the design docs win.

**Anchors:** file paths + symbol names are the durable reference. Line numbers drift — grep the symbol if one is stale.

**One-line orientation:** cost is **three physically-separate write planes** joined by a proxy `request_id`; auth is
**one resolution chain** feeding **four consumer roles**; the two meet at `billing_mode`, which since Phase 4 is a
**declaration** (`cost_mode` + `rate_limits` evidence), never inferred from key presence.

---

## 0. Quick answer (the FAQ)

**"I authenticate with OAuth/subscription but the status line shows `$X.XX`, not my 5h/weekly quota. Why?"**

Since Phase 4 (metric-evidence) the status line **never infers an API payer from key presence**. In `cost_mode=auto` it
shows the 5h quota when Claude Code reports `rate_limits`, otherwise a hedged `≈$` — it does not flip to plain `$`
because an `ANTHROPIC_API_KEY` exists in the env (a key is a *capability*, not proof of who pays; Forge may have
hydrated it into an OAuth session). A plain `$` appears only when you **declare** `cost_mode=api`.

**Two controls (both shipped):**

- `forge config set statusline.cost_mode=subscription` — always show quota, never dollars.
- `forge config set interactive_anthropic_api_key=omit` — keep `ANTHROPIC_API_KEY` *out of* the interactive session
  entirely (so it runs on your Claude Code login), while headless workers still resolve it. This is the path that
  Finding F1 (below) used to say did not exist; Phase 4 added it.

---

## Part I — Cost & metrics surfaces

### 1. The three write planes

All append-only JSONL under `~/.forge/` (respects `FORGE_HOME`), PID-sharded so concurrent processes never contend. They
are physically separate by design (design.md §3.14) and never merge; plane 3 references planes 1-2 by a shared proxy
`request_id`.

| Plane           | Path                                   | Writer (file:symbol)                               | Record                                                                                                                                                                                                    | Role                                               |
| --------------- | -------------------------------------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| 1. Request cost | `costs/requests/<YYYY-MM>_<pid>.jsonl` | `proxy/cost_logger.py` `log_request_cost`          | proxy_id, model, tier, in/out/cached tokens, `cost_micros` (null when unreported), latency, `failed`, `request_id`, `reporter`, `confidence`                                                              | **Spend source of truth** + cap bootstrap          |
| 2. Verb cost    | `costs/verbs/<YYYY-MM>_<pid>.jsonl`    | `core/reactive/cost_tracking.py` `track_verb_cost` | verb, cost delta, tokens, request_count, duration, `per_proxy[]`, `estimated:true`, `cost_measured`                                                                                                       | Per-command attribution (ESTIMATED snapshot delta) |
| 3. Usage ledger | `usage/events/<YYYY-MM>_<pid>.jsonl`   | `core/usage/ledger.py` `log_usage_event`           | `UsageEvent` (run/parent/root, runtime, command, status, provider/model/proxy, `billing_mode`, `measurement_source`, `route`, `reporter`, `confidence`, tokens, latency, `cost_micro_usd`, `source_refs`) | **Attribution** (who/what/which runtime)           |

Schema/version notes:

- Plane 1 is versioned (`COST_SCHEMA_VERSION = 1`); `read_cost_logs` skips newer-schema records (one-time warning) and
  malformed lines; legacy unversioned records (no `schema_version`) read normally. The non-dict-line guard
  (`isinstance(record, dict)`) is on every cost/audit/usage reader (Phase 0, regression-tested).
- Plane 3 is strictly read (`read_usage_events`, `dacite.Config(strict=True)`): unknown fields, invalid literals, and
  wrong nested types are corruption, skipped with a per-record warning. Non-object lines skip silently; only
  newer-schema lines get a one-time warning.
- Plane 2 (`read_verb_logs`) is the unversioned legacy shape. `estimated:true` here is a real field name (a snapshot
  delta genuinely *is* an estimate), not unsafe "estimated-dollar" prose.

**Cross-plane join:** the proxy mints one `request_id` per request and threads it into the plane-1 writer and (when
audit is on) the audit writer. Plane 3's `SourceRefs` (`{cost_request_id, audit_request_id}`) is **nullable** and
currently exact only on the direct `core.llm` path (the action tagger; see §14); `claude -p` traffic leaves it null
(Forge is not the HTTP client — deferred to Phase 4g).

### 2. In-memory proxy state (live, never persisted)

| Surface        | file:symbol                                              | Holds                                                                                      | Notes                                                                                                                                         |
| -------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `CostTracker`  | `proxy/cost_tracker.py`                                  | daily/monthly accumulators                                                                 | Bootstraps from plane 1 at startup (curr+prev month for rolling 24h); `record` per request; `check_cap` enforces; `cap_summary` feeds `GET /` |
| `ProxyMetrics` | `proxy/metrics.py` (singleton)                           | counts, tokens, `cost_micros`, per-tier/per-model (derives `cache_hit_rate` in `snapshot`) | `record_request`; `snapshot` is the `GET /` payload                                                                                           |
| Tracker init   | `proxy/server.py` `_initialize_cost_tracker_from_config` | wires config caps -> tracker                                                               | Lazy on first POST and on `GET /` so status readers see fresh state                                                                           |

### 3. Live runtime endpoint + headers

`proxy/server.py` `root()` (`GET /`) bridges in-memory state to every reader: `metrics = proxy_metrics.snapshot()` with
`_attach_cap_summary()` nesting `CostTracker.cap_summary()` under `metrics.costs.caps`. Consumers read
`metrics.costs.total_usd` (reported-only sum; cost-unavailable requests excluded),
`metrics.costs.caps.{daily,monthly}.{current_usd,limit_usd,percent}`, `metrics.cache_hit_rate`, and `wire_shape`/
`intercept_mode` (audit posture; design.md §7.x). Per-request response headers: `X-Request-Cost` (omitted on null cost),
`X-Cumulative-Cost` (omitted until a reported-cost event exists), `X-Spend-Warning`, `X-Resolved-Model`,
`X-Resolved-Tier`.

### 4. CLI read surfaces

| Command                    | file:symbol                                                                                      | Reads                                                              | Output                                                                                                                                                                               |
| -------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `forge proxy costs [id]`   | `cli/proxy_costs.py` `costs_cmd`                                                                 | planes 1 + 2                                                       | `--period today\|week\|month\|all`, `--by-model`, `--by-verb`, `--json`; computes "Interactive" as residual. **Authoritative spend view.**                                           |
| `forge proxy metrics [id]` | `cli/proxy.py` `metrics_cmd`                                                                     | live `GET /`                                                       | per-tier/per-model, cache-hit, failures; `--json`, `--all`                                                                                                                           |
| `forge activity [session]` | `cli/activity.py` `activity_cmd` -> `core/ops/usage_summary.py` `build_session_activity_summary` | plane 3 (session-filtered) + manifest `confirmed.policy.decisions` | per-command run/error/token/cost + conditional Workers column; supervisor allow/warn/deny; `--json/--days/--all`. **Reported-or-estimated; footnote points to `forge proxy costs`.** |
| session-end line           | `usage_summary.py` `render_summary_line`                                                         | same builder                                                       | one-liner on exit (host/sidecar/fork launch paths)                                                                                                                                   |

`forge activity` honesty: joins two sources with different guarantees — the ledger (uncapped) for cost/tokens, and
`confirmed.policy.decisions` (capped at `MAX_DECISION_LOG=100`) for supervisor verdicts. It re-reads the manifest fresh
from disk because hooks mutate `confirmed.*` during the run. Coverage flags: `cost_partial`, `session_tagging_partial`
(some emitters — the action tagger — never tag a session). The Workers column exists because a fan-out emits 1 verb
event

- N worker events sharing `command`; worker-granularity events go in `CommandUsage.workers` so an N-worker panel doesn't
  read as N+1 calls. The command reports Forge **automation** activity (supervisor/memory-writer/workflow verbs), not
  the full interactive session — hence the rename from `forge usage` (Phase 6).

### 5. Status-line segments

Producers in `cli/statusline/registry.py`; formatters in `cli/status_line.py`. Key cost segments:

- `cost` (`_produce_cost` / `format_billing_cost`): proxy `GET /` `total_usd` (`~$`, may undercount) · declared-`api`
  dollars · quota / `≈$` (subscription/auto). In `DEFAULT_ORDER`.
- `forge_cost` (`_produce_forge_cost`, opt-in): `forge +$Y` — reported Forge-added LLM spend for the session,
  **excluding** the main interactive harness (`sum_forge_added_cost`, `route != claude_interactive`);
  reported-or-nothing.
- `spend_cap` (`_produce_spend_cap`, opt-in, proxy-only): proxy `metrics.costs.caps`.
- `launch` (`_produce_launch`, opt-in): `confirmed.launch` route + `key:<posture>` (incl. `key:omit`).
- `rate_limits` (opt-in; self-suppresses when `cost` shows quota), `cache_hit` (opt-in, throttled).

Cost-rendering distinctions: `~$` proxy reported (may undercount), plain `$` only when `cost_mode=api`, `≈$` ambiguous
hedge (only when no quota data), quota `RL:N%`+reset. Billing mode is a **declaration**, not inferred from the env key
(§14–16).

### 6. Cost config surfaces

| Config           | Location                                                                       | Keys                                                                                                                    |
| ---------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| Proxy spend caps | `proxy.yaml` `costs.*` (`config/schema.py` `CostConfig`/`CostCaps`)            | `caps.per_day`, `caps.per_month` (USD), `on_cap_hit` (`reject`\|`warn`). `cap_mode` was removed (Phase 3).              |
| Status-line cost | `~/.forge/config.yaml` `statusline.*` (`runtime_config.py` `StatusLineConfig`) | `cost_mode` (`auto`\|`api`\|`subscription`, default `auto`), `forge_cost_ttl`, `cache_hit`, `cache_hit_ttl`, `segments` |
| Interactive key  | `~/.forge/config.yaml` (`runtime_config.py`, flat)                             | `interactive_anthropic_api_key` (`inherit`\|`omit`) — `omit` withholds the key from interactive launches only           |

Cap enforcement: `check_cap` checks accumulated recorded spend post-event, so a request may cross a cap and complete and
the next is blocked; `reject` returns HTTP 429 `spend_cap_exceeded`, `warn` forwards + sets `X-Spend-Warning`. Because
spend accrues only from reported cost, dollar caps fire only for cost-reporting routes (OpenRouter, LiteLLM non-stream).
Enforcement is process-local (run one proxy process per id for reliable caps).

### 7. Authoritative vs reported-or-estimated (units matter)

| Surface             | Scope                                | Unit                                      | Caveat                                                                                                                                               |
| ------------------- | ------------------------------------ | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Status-line `cost`  | the one interactive session rendered | `$` (declared api) / quota / `~$` (proxy) | **Claude's** native signal; never recomputed by Forge. `auto` shows quota-or-`≈$`, never `$` from key presence                                       |
| `forge activity`    | one Forge session's ledger events    | reported `$` or `unavailable` + tokens    | `cost_partial` / `session_tagging_partial`; passthrough routes report no `$`; the session total is best-effort                                       |
| `forge proxy costs` | one proxy's request log              | reported `$` or `unavailable`             | sums **route-reported** cost only (OpenRouter body / LiteLLM header); unreported requests are counted `unavailable`, never priced from a local table |

See `design_appendix.md §A.9/§A.13` and `end-user/proxy.md` ("which surface answers which question?") for the
user-facing version.

---

## Part II — Auth surfaces

### 8. The resolution chain & precedence

One sync entry point: `resolve_env_or_credential(var)` (`core/auth/template_secrets.py`).

```text
process env  >  .env (loaded override=False)  >  ~/.forge/credentials.yaml (active profile)
   └─ auth_ignore_env=true  ->  credential file ONLY (env + .env skipped)
```

- `.env` is loaded by `python-dotenv` at `cli/main.py` and `config/loader.py` (`override=False` both places), so process
  env always wins over `.env`.
- `auth_ignore_env` (`runtime_config.py`, default `False`) flips the chain to credential-file-only. Readers:
  `template_secrets.py` `_auth_ignore_env`, `EnvSecretsProvider._should_ignore`, `env.py` `_hydrate_credentials`,
  `proxy_orchestrator.py` backend injection, CLI auth display. It changes the **source** of the key (file vs env) for
  both interactive and headless launches; it does **not** decide whether the interactive session gets a key (that is
  `interactive_anthropic_api_key`, §12).
- Async path: `CredentialManager` (`core/llm/credentials.py`, TTL-cached, per-provider locks) over a
  `ChainSecretsProvider(EnvSecretsProvider -> FileSecretsProvider)`; same precedence, also honors `auth_ignore_env`.

### 9. Credential registry (`core/auth/capabilities.py`)

`EnvVar` + `Credential` + `CREDENTIALS` registry. Five atomic credentials:

| Credential       | Env var(s)                                                | Unlocks                                                                                                          |
| ---------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `openrouter`     | `OPENROUTER_API_KEY` (+ `OPENROUTER_BASE_URL` conn-value) | all `openrouter-*` proxies, OSS workflow workers                                                                 |
| `anthropic-api`  | `ANTHROPIC_API_KEY`                                       | **Forge subprocesses (claude -p)**, direct Anthropic workers, `litellm-anthropic-local`, `anthropic-passthrough` |
| `openai-api`     | `OPENAI_API_KEY`                                          | `litellm-openai-local`                                                                                           |
| `gemini-api`     | `GEMINI_API_KEY`                                          | `litellm-gemini-local`                                                                                           |
| `litellm-remote` | `LITELLM_API_KEY` (+ `LITELLM_BASE_URL` conn-value)       | all remote `litellm-*`                                                                                           |

- `anthropic-passthrough` is now in `anthropic-api`'s `unlocks_features` (Phase 6, Bug #5) **and** is required via
  `TEMPLATE_ENV_VARS` — `credentials_for_template("anthropic-passthrough")` resolves to `anthropic-api` by reverse
  lookup.
- `connection_value=true` (e.g. `LITELLM_BASE_URL`, `OPENROUTER_BASE_URL`) marks non-secret routing endpoints that
  bootstrap proxy creation; skipped in the credential preflight. Once `proxy.yaml` exists, its `base_url` is
  authoritative.
- `credentials_for_template(template)` bridges `TEMPLATE_ENV_VARS` -> `CREDENTIALS`.
  `format_missing_credential_error(...)` renders the actionable failure (signup URL, `forge auth login`,
  `not_needed_for`, an `env_ignored` diagnostic).
- `RETIRED_NAMES` rejects `anthropic`/`litellm-local` with guidance.

### 10. Credential store + CLI

`~/.forge/credentials.yaml` (`core/auth/credentials_file.py`): `0600`, versioned (schema v1), profile-keyed
(`FORGE_PROFILE` or `default`), atomic writes under an advisory lock. CLI:
`forge authentication login|status|logout|profiles` (`cli/auth.py`; alias `auth`). `status` reports per-var source
(`env` / `file:<profile>` / `not configured` / `not configured (env ignored)`), honoring `auth_ignore_env`.

### 11. The four consumer roles

| Role                      | Auth used                                                               | Mechanism                                                                                                                 |
| ------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1. Interactive session    | Claude Code's own OAuth/keychain OR `ANTHROPIC_API_KEY`                 | `claude` (no `--bare`); proxy mode sets `ANTHROPIC_BASE_URL`; `interactive_anthropic_api_key=omit` withholds the key      |
| 2. Headless `claude -p`   | `--bare` **requires `ANTHROPIC_API_KEY`**; no key -> OAuth (or a proxy) | `can_use_bare()` adds `--bare` only when a key resolves; no key -> OAuth fallthrough (forced `bare=True` + no key errors) |
| 3. Forge `core.llm` calls | per-provider via `CredentialManager`                                    | async, TTL-cached                                                                                                         |
| 4. Proxy upstream         | provider key to the model API                                           | `x-api-key` (passthrough) / `Bearer` (openai-compat)                                                                      |

### 12. Launch-time env building + the interactive-key control

`build_claude_env(base_url, extra_vars, direct, derive_run_identity, interactive)` (`core/reactive/env.py`) builds every
Claude subprocess env.

- **Headless** (`interactive=False`, the default for workers): `_hydrate_credentials(env)` runs inline — if
  `ANTHROPIC_API_KEY` is absent from env but present in the credential file, inject it (`auth_ignore_env=true` pops env
  and injects the file value, else pops the key).
- **Interactive** (`interactive=True`, the session frontend): the inline hydrate is skipped; the frontend calls
  `apply_interactive_api_key(env, interactive=True)` **last** (after `extra_vars`), which resolves the key with a source
  and either sets it or — when `interactive_anthropic_api_key=omit` — pops it and records
  `confirmed.launch.api_key_source = omitted_by_config`. Under a sidecar the omission is applied by `entrypoint.sh` via
  `FORGE_OMIT_INTERACTIVE_KEY=1`, *after* the in-container proxy captured its upstream credential.

So the default is still hydrate-into-both, but `interactive_anthropic_api_key=omit` is the supported path to run the
interactive session on OAuth while headless workers keep API auth.

### 13. Proxy upstream auth

`TEMPLATE_ENV_VARS` maps each template to its required vars. `_ensure_template_credentials` (`proxy_orchestrator.py`)
preflights before spawn (connection-value vars skipped). Upstream key injection: `anthropic-passthrough` sends
`x-api-key: <ANTHROPIC_API_KEY>` (`passthrough.py` `build_upstream_headers`); litellm / openrouter (translated) send
`Authorization: Bearer` via the OpenAI SDK client. Audit logs redact these before persistence (`proxy/utils.py`
`redact_headers`).

---

## Part III — The correlation (auth -> billing_mode -> cost surface)

This is where auth and cost meet. Phase 4 split the two `billing_mode` notions cleanly: the **status line** is a
declaration, the **ledger** is recorded provenance. The status line no longer reads the env key at all.

### 14. Where `ANTHROPIC_API_KEY` is (and is not) read

| Reader                                            | Reads                                    | Honors file / `auth_ignore_env`? | Feeds                                                                  |
| ------------------------------------------------- | ---------------------------------------- | -------------------------------- | ---------------------------------------------------------------------- |
| Status line                                       | **nothing** (no key read since Phase 4)  | n/a                              | `RenderContext.billing_mode` = `cost_mode` declaration + `rate_limits` |
| `_anthropic_key_present()` (`core/usage/emit.py`) | `resolve_env_or_credential` (env + file) | yes                              | usage-ledger `billing_mode` via `infer_billing_mode`                   |

The old `RenderContext.has_api_key` raw-env read was **deleted** in Phase 4 (it produced the OAuth-as-API misread). The
ledger's key check is unaffected: it records attribution provenance, not display billing.

### 15. `infer_billing_mode` (the ledger's classifier)

`core/usage/billing.py`: `return "api" if (direct and has_api_key) else "unknown"`. Conservative — `api` only when the
call is direct (no proxy) AND a key authenticates it; everything else `unknown`. Never returns a subscription mode.

### 16. Two `billing_mode` vocabularies (do not conflate)

| Plane                      | Type                | Values                                                                                                     | Input                                                      |
| -------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Status line (display)      | **declaration**     | `api` \| `subscription` \| `ambiguous`                                                                     | `statusline.cost_mode` + stdin `rate_limits` (NOT the key) |
| Usage ledger (attribution) | recorded provenance | `api` \| `subscription_interactive` \| `subscription_headless_credit` \| `subscription_quota` \| `unknown` | `infer_billing_mode` (only ever `api`/`unknown` today)     |

The ledger's `subscription_*` literals exist in the enum but no shipped emitter produces them — reserved for a future
native-runtime path that records subscription provenance directly.

### 17. Auth/declaration state -> what each surface reports

| State (this run)                        | Interactive billing (status line)               | Headless verb billing (ledger)                | Proxy plane                                |
| --------------------------------------- | ----------------------------------------------- | --------------------------------------------- | ------------------------------------------ |
| `cost_mode=auto`, `rate_limits` present | quota (`RL:N%`)                                 | `direct=true,key=true` -> `api`               | n/a                                        |
| `cost_mode=auto`, no `rate_limits`      | hedged `≈$` (never plain `$` from key presence) | `api` or `unknown` by key                     | n/a                                        |
| `cost_mode=api` (declared)              | real `$` (Claude's `total_cost_usd`)            | `api` or `unknown` by key                     | n/a                                        |
| Proxy mode (`ANTHROPIC_BASE_URL` set)   | proxy `~$` reported (may undercount)            | `direct=false` -> `unknown` (upstream opaque) | `forge proxy costs` (reported/unavailable) |

No surface unifies them; the ledger is the closest unifier but **cannot see the interactive OAuth session's quota
consumption** (Forge is not the HTTP client for it). `forge +$Y` (`forge_cost`) deliberately shows only Forge's *added*
spend, never the main harness.

---

## Part IV — Findings & known limitations

- **F1 — RESOLVED (Phase 4): interactive key omission now exists.** Hydration is still uniform *by default*
  (`_hydrate_credentials` injects a resolvable key into both interactive and headless envs), but
  `interactive_anthropic_api_key=omit` (§12) withholds it from the interactive session while headless workers keep it.
  "Interactive on OAuth + headless on API key" is now expressible.
- **F2 — RESOLVED (Phase 4): the status line no longer reads the env key.** `RenderContext.has_api_key` was deleted;
  `billing_mode` is a declaration (`cost_mode` + `rate_limits`), so a hydrated key can no longer force a phantom `$`.
- **F3 — `auth_ignore_env` is source-only (documented).** It changes the *source* of the injected key (file vs env), not
  *whether* the interactive session gets one. The interactive/headless separation is `interactive_anthropic_api_key`,
  not `auth_ignore_env` — now stated in `end-user/authentication.md` and `design_appendix.md §A.6` (Phase 6, Bug #6).
- **F4 — The OAuth-vs-API ambiguity is irreducible at the wire-blind layer.** When both OAuth and a key are available,
  which one Claude Code bills against is Claude Code's own precedence; Forge cannot observe it. `cost_mode` is the
  explicit override for exactly this case.
- **F5 — `source_refs` is exact only on the direct `core.llm` path.** `claude -p` ledger events carry null `source_refs`
  (Forge is not the HTTP client). Per-request correlation for `claude -p` is deferred to Phase 4g.
- **F6 — Proxy spend is reported-or-unavailable; Forge is not a cost oracle.** Plane 1 writes the cost a route actually
  reported (`reporter` + `confidence`: OpenRouter body `usage.cost` → `reported`, LiteLLM header → `gateway_calculated`)
  or `cost_micros:null` / `confidence:"unavailable"` when none did (Anthropic passthrough; LiteLLM streaming). No local
  price table. Spend caps fire only for routes that report cost; `forge proxy costs` sums reported cost only and is
  still not a provider invoice.

> **Operator playbook (shipped controls).** To show subscription quota on the status line:
> `forge config set statusline.cost_mode=subscription`. To run the interactive session on OAuth while headless workers
> keep API auth: `forge config set interactive_anthropic_api_key=omit`. See `end-user/config.md` +
> `end-user/authentication.md`. (Phase 4 shipped the former proposals P1 "make `auto` consult `rate_limits`" and P2
> "separate interactive vs headless hydration"; they are no longer open.)

---

## Appendix — File / symbol index

| Area                        | file:symbol                                                                                                                                                 |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Request cost log            | `proxy/cost_logger.py` `log_request_cost`, `read_cost_logs`                                                                                                 |
| Cost tracker / caps         | `proxy/cost_tracker.py` `CostTracker` (bootstrap, `check_cap`, `cap_summary`)                                                                               |
| Proxy metrics               | `proxy/metrics.py` `ProxyMetrics` (`snapshot`, singleton)                                                                                                   |
| Cost calc + GET /           | `proxy/server.py` `_calc_and_log_cost`, `root`, `_attach_cap_summary`, `_with_spend_warning`                                                                |
| Verb cost                   | `core/reactive/cost_tracking.py` `track_verb_cost`, `VerbCostResult`, `read_verb_logs`                                                                      |
| Usage ledger                | `core/usage/ledger.py` `UsageEvent`, `log_usage_event`, `read_usage_events`, `BillingMode`, `MeasurementSource`; `core/usage/vocabulary.py`                 |
| Usage emitters              | `core/usage/emit.py` `emit_*`; `_anthropic_key_present`                                                                                                     |
| Billing classifier          | `core/usage/billing.py` `infer_billing_mode`                                                                                                                |
| Per-session read            | `cli/activity.py` `activity_cmd`; `core/ops/usage_summary.py` `build_session_activity_summary`, `render_summary_line`, `sum_forge_added_cost`               |
| Proxy cost CLI              | `cli/proxy_costs.py` `costs_cmd`; `cli/proxy.py` `metrics_cmd`                                                                                              |
| Status-line cost            | `cli/statusline/registry.py` `_produce_cost`/`_produce_forge_cost`; `cli/status_line.py` `get_session_metrics`, `format_billing_cost`, `format_rate_limits` |
| Status-line billing mode    | `cli/statusline/context.py` `billing_mode` (declaration: `cost_mode` + `rate_limits`; no key read)                                                          |
| Credential registry         | `core/auth/capabilities.py` `CREDENTIALS`, `credentials_for_template`, `format_missing_credential_error`                                                    |
| Credential resolution       | `core/auth/template_secrets.py` `resolve_env_or_credential`, `TEMPLATE_ENV_VARS`, `_auth_ignore_env`, `resolve_env_or_credential_with_source`               |
| Credential store / CLI      | `core/auth/credentials_file.py`; `cli/auth.py`                                                                                                              |
| Async credentials           | `core/llm/credentials.py` `CredentialManager`                                                                                                               |
| Env build + interactive key | `core/reactive/env.py` `build_claude_env`, `_hydrate_credentials`, `apply_interactive_api_key`                                                              |
| Interactive launch          | `session/claude/invoke.py` `_build_environment`                                                                                                             |
| Proxy upstream auth         | `proxy/proxy_orchestrator.py` `_ensure_template_credentials`; `proxy/passthrough.py` `build_upstream_headers`                                               |
| Config                      | `runtime_config.py` `StatusLineConfig` (`cost_mode`), `interactive_anthropic_api_key`, `auth_ignore_env`; `config/schema.py` `CostConfig`/`CostCaps`        |
