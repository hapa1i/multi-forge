# Auth, Cost, and Metrics Surfaces

A code-grounded map of every surface in Forge that resolves credentials, records cost, or reports usage/metrics, and the
correlation between them. Written to answer recurring questions like "why does the status line show dollars when I'm on
a subscription?" without re-reading the tree each time.

**Scope:** describes *shipped* behavior (per documentation-guidelines Rule 2). A clearly-fenced "Proposed changes"
section at the end is the only forward-looking content.

**Anchors:** file paths + symbol names are the durable reference. Line numbers are anchors as of `main @ 563840a`
(2026-06-04) and will drift; grep the symbol if a line number is stale.

**One-line orientation:** cost is **three physically-separate write planes** joined by a proxy `request_id`; auth is
**one resolution chain** feeding **four consumer roles**; the two meet at `billing_mode`, which is computed differently
on each read surface.

---

## 0. Quick answer (the FAQ)

**"I authenticate with OAuth/subscription but the status line shows `$X.XX`, not my 5h/weekly quota. Why?"**

The status line's `auto` cost mode classifies billing from a single signal: is `ANTHROPIC_API_KEY` present in the
interactive session's environment (`statusline/context.py:80` `has_api_key` -> `context.py:87` `billing_mode`). It has
**no way to observe which credential Claude Code actually authenticated with** — Claude's stdin JSON reports a
`total_cost_usd` regardless. In Forge, `ANTHROPIC_API_KEY` is *legitimately* present for headless `claude -p` workers
run with `--bare` (which disables OAuth, so it requires the key; without a key Forge omits `--bare` and `claude -p`
falls through to OAuth — see §11), and Forge **hydrates that key into the interactive session's env too** (§12, Finding
F1). So the env signal reads `api` whenever a key is resolvable anywhere, and you get `$`.

**Fix (shipped):** `forge config set statusline.cost_mode=subscription` — bypasses the heuristic and shows quota. This
does not affect headless workers. See Part V for the full playbook and why moving the key to the credential file does
*not* fix the display.

---

## Part I — Cost & metrics surfaces

### 1. The three write planes

All append-only JSONL under `~/.forge/` (respects `FORGE_HOME`), PID-sharded so concurrent processes never contend. They
are physically separate by design (design.md §3.14) and never merge; plane 3 references planes 1-2 by a shared proxy
`request_id`.

| Plane           | Path                                   | Writer (file:symbol)                                   | Record                                                                                                                                                                                                    | Role                                               |
| --------------- | -------------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| 1. Request cost | `costs/requests/<YYYY-MM>_<pid>.jsonl` | `proxy/cost_logger.py:44` `log_request_cost`           | proxy_id, model, tier, in/out/cached tokens, `cost_micros` (null when unreported), latency, `failed`, `request_id`, `reporter`, `confidence`                                                              | **Spend source of truth** + cap bootstrap          |
| 2. Verb cost    | `costs/verbs/<YYYY-MM>_<pid>.jsonl`    | `core/reactive/cost_tracking.py:207` `track_verb_cost` | verb, cost delta, tokens, request_count, duration, `per_proxy[]`, `estimated:true`, `cost_measured`                                                                                                       | Per-command attribution (ESTIMATED snapshot delta) |
| 3. Usage ledger | `usage/events/<YYYY-MM>_<pid>.jsonl`   | `core/usage/ledger.py:147` `log_usage_event`           | `UsageEvent` (run/parent/root, runtime, command, status, provider/model/proxy, `billing_mode`, `measurement_source`, `route`, `reporter`, `confidence`, tokens, latency, `cost_micro_usd`, `source_refs`) | **Attribution** (who/what/which runtime)           |

Schema/version notes:

- Plane 1 is versioned (`COST_SCHEMA_VERSION = 1`, `cost_logger.py:23`); `read_cost_logs` (`:92`) skips newer-schema
  records (and malformed lines), surfacing the former once at warning level; legacy unversioned records (no
  `schema_version`) are read normally (`cost_logger.py:127`).
- Plane 3 is strictly read (`read_usage_events`, `ledger.py:176`, `dacite.Config(strict=True)`): unknown fields, invalid
  literals, and wrong nested types are corruption, skipped with a **per-record** warning (`ledger.py:252`). Malformed
  JSON and non-object lines (`[]`, `"x"`, `1`) skip **silently** (`:213`, `:217`); only newer-schema lines get a
  **one-time** warning (`:220`).
- Plane 2 (`read_verb_logs`, `cost_tracking.py:266`) is the unversioned legacy shape.

**Cross-plane join:** the proxy mints one `request_id` per request and threads it into the plane-1 writer and (when
audit is on) the audit writer. Plane 3's `SourceRefs` (`ledger.py:78`, `{cost_request_id, audit_request_id}`) is
**nullable** and currently exact only on the direct `core.llm` path (the action tagger; see §14); `claude -p` traffic
leaves it null (Forge is not the HTTP client — deferred to Phase 4g).

### 2. In-memory proxy state (live, never persisted)

| Surface        | file:symbol                                              | Holds                                                                                      | Notes                                                                                                                                                                               |
| -------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CostTracker`  | `proxy/cost_tracker.py:38`                               | daily/monthly accumulators                                                                 | Bootstraps from plane 1 at startup (`bootstrap_from_logs:66`, curr+prev month for rolling 24h); `record:151` per request; `check_cap:185` enforces; `cap_summary:225` feeds `GET /` |
| `ProxyMetrics` | `proxy/metrics.py:44` (singleton `:222`)                 | counts, tokens, `cost_micros`, per-tier/per-model (derives `cache_hit_rate` in `snapshot`) | `record_request:91`; `snapshot:157` is the `GET /` payload                                                                                                                          |
| Tracker init   | `proxy/server.py` `_initialize_cost_tracker_from_config` | wires config caps -> tracker                                                               | Lazy on first POST and on `GET /` so status readers see fresh state                                                                                                                 |

### 3. Live runtime endpoint + headers

`proxy/server.py` `root()` (`GET /`) is the bridge from in-memory state to every reader. It returns
`metrics = proxy_metrics.snapshot()` with `_attach_cap_summary()` nesting `CostTracker.cap_summary()` under
`metrics.costs.caps`. Key fields consumers read:

- `metrics.costs.total_usd` (reported-only sum; cost-unavailable requests excluded),
  `metrics.costs.caps.{daily,monthly}.{current_usd,limit_usd,percent}`
- `metrics.cache_hit_rate`, per-tier/per-model breakdown
- `wire_shape`, `intercept_mode` (audit posture; see design.md §7.x)

Per-request response headers (`proxy/server.py`): `X-Request-Cost`, `X-Cumulative-Cost`, `X-Spend-Warning`
(`_with_spend_warning`), `X-Resolved-Model`, `X-Resolved-Tier`.

### 4. CLI read surfaces

| Command                    | file:symbol                                                                                      | Reads                                                              | Output                                                                                                                                                                   |
| -------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `forge proxy costs [id]`   | `cli/proxy_costs.py:74` `costs_cmd`                                                              | planes 1 + 2                                                       | `--period today\|week\|month\|all`, `--by-model`, `--by-verb`, `--json`; computes "Interactive" as residual. **Authoritative spend view.**                               |
| `forge proxy metrics [id]` | `cli/proxy.py` `metrics_cmd`                                                                     | live `GET /`                                                       | per-tier/per-model, cache-hit, failures; `--json`, `--all`                                                                                                               |
| `forge usage [session]`    | `cli/usage.py:37` `usage_cmd` -> `core/ops/usage_summary.py:98` `build_session_activity_summary` | plane 3 (session-filtered) + manifest `confirmed.policy.decisions` | per-command run/error/token/cost + conditional Workers column; supervisor allow/warn/deny; `--json/--days/--all`. **Estimated; footnote points to `forge proxy costs`.** |
| session-end line           | `usage_summary.py:128` `render_summary_line`                                                     | same builder                                                       | one-liner on exit (host/sidecar/fork launch paths)                                                                                                                       |

`forge usage` honesty: joins two sources with different guarantees — the ledger (uncapped) for cost/tokens, and
`confirmed.policy.decisions` (capped at `MAX_DECISION_LOG=100`) for supervisor verdicts. It re-reads the manifest fresh
from disk because hooks mutate `confirmed.*` during the run. Coverage flags: `cost_partial`, `session_tagging_partial`
(set true when the session had activity, because some emitters — the action tagger — never tag a session). The Workers
column exists because a fan-out emits 1 verb event + N worker events sharing `command`; worker-granularity events go in
`CommandUsage.workers` so an N-worker panel doesn't read as N+1 calls.

### 5. Status-line segments

Producers in `cli/statusline/registry.py`; formatters in `cli/status_line.py`.

| Segment           | Producer                   | Formatter                                              | Source                                                                                                           | In `DEFAULT_ORDER`?                                  |
| ----------------- | -------------------------- | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `cost`            | `_produce_cost:93`         | `get_session_metrics:746` / `format_billing_cost:1098` | proxy `GET /` `total_usd` (`~$`) · stdin `cost.total_cost_usd` (`$` API) · quota / `≈$` (subscription/ambiguous) | yes                                                  |
| `tokens`          | `_produce_tokens:116`      | `format_token_breakdown`                               | stdin `context_window.*` or transcript scan                                                                      | yes                                                  |
| `lines`           | `_produce_lines:112`       | `format_line_changes`                                  | stdin `cost.*` or git numstat                                                                                    | yes                                                  |
| `model` (ctx bar) | `_produce_model:74`        | `get_context_display`                                  | stdin `context_window` (proxy override)                                                                          | yes                                                  |
| `cache_hit`       | `_produce_cache_hit:139`   | `format_cache_hit`                                     | proxy `cache_hit_rate` · else throttled transcript compute                                                       | no (opt-in)                                          |
| `rate_limits`     | `_produce_rate_limits:103` | `format_rate_limits:1051`                              | stdin `rate_limits.{five_hour,seven_day}`                                                                        | no (opt-in; self-suppresses when `cost` shows quota) |
| `spend_cap`       | `_produce_spend_cap:240`   | `format_spend_cap`                                     | proxy `metrics.costs.caps`                                                                                       | no (opt-in, **proxy-only**)                          |

Cost-rendering distinctions (all in `status_line.py`): `~$` proxy reported, may undercount (`get_session_metrics`,
`is_proxy=True`), plain `$` direct API real (`_fmt_dollars:713`), `≈$` ambiguous hedge (`format_billing_cost`, only when
no quota data), quota `RL:N%`+reset (`format_rate_limits` via `_extract_short_window:986` +
`_format_reset_countdown:1016`). Spend-cap amounts use `_fmt_cap_money:720` (4 decimals below a cent, so sub-cent smoke
caps don't collapse to `0c`).

Cache-hit throttle (direct mode): `statusline/throttle.py`, cached at
`$FORGE_HOME/cache/statusline/<sha256(session_id or transcript_path)>.json` (`throttle.py:34-35`; the digest input is
`session_id`, falling back to `transcript_path` — not a join — and SHA-256 with `usedforsecurity=False`, not SHA-1),
recompute on transcript change or TTL.

### 6. Cost config surfaces

| Config           | Location                                                                          | Keys                                                                                                         |
| ---------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Proxy spend caps | `proxy.yaml` `costs.*` (`config/schema.py` `CostConfig`/`CostCaps`)               | `caps.per_day`, `caps.per_month` (USD), `on_cap_hit` (`reject`\|`warn`)                                      |
| Status-line cost | `~/.forge/config.yaml` `statusline.*` (`runtime_config.py:66` `StatusLineConfig`) | `cost_mode` (`auto`\|`api`\|`subscription`, default `auto`, `:78`), `cache_hit`, `cache_hit_ttl`, `segments` |

Cap enforcement: `check_cap` runs before forwarding and checks accumulated recorded spend — post-event, so a request may
cross a cap and complete and the next request is blocked; `reject` returns HTTP 429 `spend_cap_exceeded`, `warn`
forwards + sets `X-Spend-Warning`. Enforcement is process-local (each proxy process bootstraps from shared JSONL;
in-flight spend is not coordinated across processes).

### 7. Authoritative vs estimated (units matter)

| Surface             | Scope                                | Unit                                   | Caveat                                                                                                                                               |
| ------------------- | ------------------------------------ | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Status-line `cost`  | the one interactive session rendered | `$` (api) / quota (sub) / `~$` (proxy) | phantom `$` on OAuth (see Part III)                                                                                                                  |
| `forge usage`       | one Forge session's ledger events    | reported `$` or `unavailable` + tokens | `cost_partial` / `session_tagging_partial`; passthrough routes report no `$`                                                                         |
| `forge proxy costs` | one proxy's request log              | reported `$` or `unavailable`          | sums **route-reported** cost only (OpenRouter body / LiteLLM header); unreported requests are counted `unavailable`, never priced from a local table |

---

## Part II — Auth surfaces

### 8. The resolution chain & precedence

One sync entry point: `resolve_env_or_credential(var)` (`core/auth/template_secrets.py:69`).

```text
process env  >  .env (loaded override=False)  >  ~/.forge/credentials.yaml (active profile)
   └─ auth_ignore_env=true  ->  credential file ONLY (env + .env skipped)
```

- `.env` is loaded by `python-dotenv` at `cli/main.py:16` (unconditional, every `forge` command) and `config/loader.py`
  (`override=False` both places), so process env always wins over `.env`.
- `auth_ignore_env` (`runtime_config.py:189`, default `False`) flips the chain to credential-file-only. Readers:
  `template_secrets.py:58` `_auth_ignore_env`, `EnvSecretsProvider._should_ignore`, `env.py` `_hydrate_credentials`,
  `proxy_orchestrator.py` backend injection, CLI auth display.
- Async path: `CredentialManager` (`core/llm/credentials.py:192`, TTL-cached, per-provider locks) over a
  `ChainSecretsProvider(EnvSecretsProvider -> FileSecretsProvider)`; same precedence, also honors `auth_ignore_env`.

### 9. Credential registry (`core/auth/capabilities.py`)

`EnvVar` (`:17`) + `Credential` (`:28`) + `CREDENTIALS` registry (`:39`). Five atomic credentials:

| Credential       | Env var(s)                                                | Unlocks                                                                                                          |
| ---------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `openrouter`     | `OPENROUTER_API_KEY` (+ `OPENROUTER_BASE_URL` conn-value) | all `openrouter-*` proxies, OSS workflow workers                                                                 |
| `anthropic-api`  | `ANTHROPIC_API_KEY`                                       | **Forge subprocesses (claude -p)**, direct Anthropic workers, `litellm-anthropic-local`, `anthropic-passthrough` |
| `openai-api`     | `OPENAI_API_KEY`                                          | `litellm-openai-local`                                                                                           |
| `gemini-api`     | `GEMINI_API_KEY`                                          | `litellm-gemini-local`                                                                                           |
| `litellm-remote` | `LITELLM_API_KEY` (+ `LITELLM_BASE_URL` conn-value)       | all remote `litellm-*`                                                                                           |

- The **Unlocks** column blends the registry's `unlocks_features` strings with *effective* template coverage from
  `TEMPLATE_ENV_VARS` (`template_secrets.py:18`): e.g. `anthropic-passthrough` is **not** in `anthropic-api`'s
  `unlocks_features` (`capabilities.py:56`) but requires `ANTHROPIC_API_KEY` through `TEMPLATE_ENV_VARS`.
- `connection_value=true` (e.g. `LITELLM_BASE_URL`) marks non-secret routing endpoints that bootstrap proxy creation;
  skipped in the credential preflight (they can come from CLI/config). Once `proxy.yaml` exists, its `base_url` is
  authoritative.
- `credentials_for_template(template)` (`:125`) bridges `TEMPLATE_ENV_VARS` (`template_secrets.py:18`) -> `CREDENTIALS`.
  `format_missing_credential_error(...)` (`:147`) renders the actionable failure (signup URL, `forge auth login`
  command, `not_needed_for` disambiguation, an `env_ignored` diagnostic).
- `RETIRED_NAMES` (`:97`) rejects `anthropic`/`litellm-local` with guidance.

### 10. Credential store + CLI

`~/.forge/credentials.yaml` (`core/auth/credentials_file.py`): `0600`, versioned (schema v1, `CredentialVersionError` on
mismatch), profile-keyed (`FORGE_PROFILE` or `default`), atomic writes under an advisory lock. CLI:
`forge authentication login|status|logout|profiles` (`cli/auth.py`; registered as `authentication` with alias `auth` at
`cli/main.py:333`). `status` reports per-var source (`env` / `file:<profile>` / `not configured` /
`not configured (env ignored)`), honoring `auth_ignore_env`.

### 11. The four consumer roles

| Role                      | Auth used                                                               | Mechanism                                                                                                                 |
| ------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1. Interactive session    | Claude Code's own OAuth/keychain OR `ANTHROPIC_API_KEY`                 | `claude` (no `--bare`); proxy mode sets `ANTHROPIC_BASE_URL`                                                              |
| 2. Headless `claude -p`   | `--bare` **requires `ANTHROPIC_API_KEY`**; no key -> OAuth (or a proxy) | `can_use_bare()` adds `--bare` only when a key resolves; no key -> OAuth fallthrough (forced `bare=True` + no key errors) |
| 3. Forge `core.llm` calls | per-provider via `CredentialManager`                                    | async, TTL-cached                                                                                                         |
| 4. Proxy upstream         | provider key to the model API                                           | `x-api-key` (passthrough) / `Bearer` (openai-compat)                                                                      |

### 12. Launch-time env building + the hydration finding

`build_claude_env(base_url, extra_vars, direct, derive_run_identity)` (`core/reactive/env.py:156`) builds every Claude
subprocess env. It calls `_hydrate_credentials(env)` (`:239`) **unconditionally at `:190`**, and **both** the
interactive launch (`session/claude/invoke.py:162` `_build_environment` -> `build_claude_env`) **and** headless workers
go through it.

`_hydrate_credentials` logic:

- `auth_ignore_env=false` (default): if `ANTHROPIC_API_KEY` absent from env but present in the credential file -> inject
  it.
- `auth_ignore_env=true`: ignore env; inject the file value if present, else **pop** the key.

**Finding F1 (verified): hydration is uniform across interactive and headless.** The interactive Claude process receives
`ANTHROPIC_API_KEY` whenever it is resolvable anywhere (env, `.env`, or credential file). There is no Forge path that
keeps the key out of the interactive session to force OAuth. `direct=True` / `--no-proxy` only scrub
`ANTHROPIC_BASE_URL` and the subprocess-proxy vars (`:199-204`); hydration runs *before* that branch and is unaffected.

### 13. Proxy upstream auth

`TEMPLATE_ENV_VARS` (`template_secrets.py:18`) maps each template to its required vars. `_ensure_template_credentials`
(`proxy_orchestrator.py:265`) preflights before spawn (connection-value vars skipped), raising
`format_missing_credential_error` on a miss. Upstream key injection:

- `anthropic-passthrough`: `x-api-key: <ANTHROPIC_API_KEY>` via `passthrough.py:42` `build_upstream_headers`.
- litellm / openrouter (translated): `Authorization: Bearer` via the OpenAI SDK client.

Audit logs redact these before persistence (`proxy/utils.py` `redact_headers`, substring denylist incl. `authorization`,
`api-key`, `token`).

---

## Part III — The correlation (auth -> billing_mode -> cost surface)

This is where auth and cost meet. **The same `ANTHROPIC_API_KEY` is read by two different "has key?" checks with
deliberately different semantics, feeding two different planes, expressed in two different `billing_mode`
vocabularies.**

### 14. Two `has_api_key` checks

| Check                                                    | Reads                                     | Honors file / `auth_ignore_env`? | Feeds                                                    |
| -------------------------------------------------------- | ----------------------------------------- | -------------------------------- | -------------------------------------------------------- |
| `RenderContext.has_api_key` (`statusline/context.py:80`) | **raw** `os.environ["ANTHROPIC_API_KEY"]` | no                               | status-line interactive `billing_mode` (`context.py:87`) |
| `_anthropic_key_present()` (`core/usage/emit.py:255`)    | `resolve_env_or_credential` (env + file)  | yes                              | usage-ledger `billing_mode` via `infer_billing_mode`     |

Both signals are downstream of Finding F1: because `build_claude_env` hydrates the resolvable key into the interactive
env, and `forge status-line` is a child of the interactive Claude process, the status line's "raw env" read already
contains any file-hydrated key. **The raw-env guard is necessary but not sufficient** to avoid the OAuth-as-API
misclassification (Finding F2).

### 15. `infer_billing_mode` (the ledger's classifier)

`core/usage/billing.py:14`: `return "api" if (direct and has_api_key) else "unknown"`. Conservative — `api` only when
the call is direct (no proxy in path) AND a key authenticates it; everything else `unknown`. **Never returns a
subscription mode.**

### 16. Two `billing_mode` vocabularies (do not conflate)

| Plane                      | Type                | Values                                                                                                     | Defined                    |
| -------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------- |
| Status line (display)      | heuristic           | `api` \| `subscription` \| `ambiguous`                                                                     | `statusline/context.py:87` |
| Usage ledger (attribution) | recorded provenance | `api` \| `subscription_interactive` \| `subscription_headless_credit` \| `subscription_quota` \| `unknown` | `core/usage/ledger.py:59`  |

The ledger's `subscription_*` literals exist in the enum but **no shipped emitter produces them** — `infer_billing_mode`
only ever yields `api`/`unknown`. They are reserved for a future native-runtime path that records subscription
provenance directly rather than inferring it; the design docs define the enum and a Phase 5 native runtime but do not
yet bind these literals to a specific runtime.

### 17. Auth state -> what each surface reports

| Auth state (this run)                                 | Interactive billing (status line)                  | Headless verb billing (ledger)                | Proxy plane                                |
| ----------------------------------------------------- | -------------------------------------------------- | --------------------------------------------- | ------------------------------------------ |
| Direct + `ANTHROPIC_API_KEY` resolvable               | `auto`->`api` -> **`$`** (phantom if really OAuth) | `direct=true,key=true` -> `api`               | n/a                                        |
| Direct + no key anywhere                              | `auto`->`ambiguous` -> quota / `≈$`                | `unknown` (and `--bare` cannot run)           | n/a                                        |
| Proxy mode (`ANTHROPIC_BASE_URL` set)                 | proxy -> **`~$`** reported (may undercount)        | `direct=false` -> `unknown` (upstream opaque) | `forge proxy costs` (reported/unavailable) |
| `--subprocess-proxy` (direct main + proxied children) | interactive: `api`/`ambiguous`                     | children: `unknown` (proxied)                 | proxy plane for children                   |

"Usage is a combination" is literally **three coexisting billing realities on one machine**: interactive `api`/quota
(status line) + headless verbs `api`/`unknown` (ledger) + proxied work `unknown` + reported (may-undercount) proxy `$`.
No surface unifies them; the ledger is the closest unifier but **cannot see the interactive OAuth session's quota
consumption at all** (Forge is not the HTTP client for it).

---

## Part IV — Findings & known limitations

- **F1 — Uniform hydration couples interactive and headless key presence.** `build_claude_env` injects a resolvable
  `ANTHROPIC_API_KEY` into the interactive session env, not just headless workers (§12). Consequence: Forge cannot
  currently present "interactive on OAuth + headless on API key" through key placement alone.
- **F2 — Status-line raw-env guard is defeated by upstream hydration.** `context.py:80` reads raw env to "see the main
  session's actual auth," but that env was already hydrated by `build_claude_env`, so the key is present whenever it is
  resolvable for any role. The env signal is therefore `api` regardless of OAuth.
- **F3 — `auth_ignore_env` intent vs behavior tension.** Its docstring frames it as "shell keys are for Claude Code, not
  Forge subprocesses," but `_hydrate_credentials` applies the flag to the interactive launch too: it changes the
  *source* of the injected key (file vs env), not *whether* the interactive session gets one. It does not isolate
  interactive OAuth from headless API auth.
- **F4 — The OAuth-vs-API ambiguity is irreducible at the wire-blind layer.** When both OAuth and a key are available,
  which one Claude Code bills against is Claude Code's own precedence; Forge cannot observe it. `cost_mode` exists as
  the explicit override for exactly this case.
- **F5 — `source_refs` is exact only on the direct `core.llm` path.** `claude -p` ledger events carry null `source_refs`
  (Forge is not the HTTP client). Per-request correlation for `claude -p` is deferred to Phase 4g.
- **F6 — Proxy spend is reported-or-unavailable; Forge is not a cost oracle.** Plane 1 writes the cost a route actually
  reported (`reporter` + `confidence`: OpenRouter body `usage.cost` → `reported`, LiteLLM header → `gateway_calculated`)
  or `cost_micros:null` / `confidence:"unavailable"` when none did (Anthropic passthrough; LiteLLM streaming). There is
  no local price table. Consequently **spend caps fire only for routes that report cost** —
  passthrough/streaming-LiteLLM dollar caps are no-ops (tokens still tracked). `forge proxy costs` sums reported cost
  only and is still not a provider invoice.

---

## Part V — Operator playbook

**Goal: see subscription quota on the status line while keeping `ANTHROPIC_API_KEY` available for headless workers.**

1. **Declare the billing mode (shipped, zero-risk):**

   ```bash
   forge config set statusline.cost_mode=subscription
   ```

   The status line stops reading `has_api_key` and renders the 5h quota (`format_rate_limits`), provided Claude Code
   passes `rate_limits` in its stdin. Headless workers are unaffected (they still resolve the key for `--bare`).

2. **What does NOT work:** moving the key into `~/.forge/credentials.yaml` (with or without `auth_ignore_env`). Per
   Finding F1, `_hydrate_credentials` injects the file value back into the interactive env, the status line inherits it,
   and you still get `$`.

3. **Verify actual billing:** run `/status` (or `/login`) inside Claude Code. If `ANTHROPIC_API_KEY` is set and you did
   not explicitly select the subscription, Claude Code may be billing the key — in which case the `$` is *real* and the
   status line is correct. To force OAuth for the interactive session, make the key unresolvable *everywhere*: strip it
   from `.env`/shell **and** remove it from `~/.forge/credentials.yaml` — otherwise `_hydrate_credentials` injects it
   back (Finding F1). Declaring `cost_mode=subscription` (step 1) is the lower-effort path.

**Authority for spend questions:** `forge proxy costs` (proxy plane). `forge usage` is per-session; its cost is
reported-or-unavailable, attributed by snapshot delta. The status-line number is the single interactive session only.

---

## Part VI — Proposed changes (NOT shipped)

Recorded for follow-up; none of this is implemented.

- **P1 — Make `auto` subject-correct.** Have `statusline/context.py:87` `billing_mode` consult
  `rate_limits.{five_hour,seven_day}` (subscription quota windows describe *this* interactive session and survive
  hydration, since they come from Claude Code's stdin, not the env) before falling back to `has_api_key`. Fixes the
  OAuth-on-Max case for every user without a config change. **Gate:** confirm an API-key-authenticated *interactive*
  session does not also emit those windows, else it would regress an API user to the quota view. Explicit
  `cost_mode=api` must continue to win.
- **P2 — Separate interactive vs headless hydration.** Give `build_claude_env` (or its callers) a way to keep
  `ANTHROPIC_API_KEY` out of the *interactive* env while still hydrating *headless* workers, so OAuth-for-shell +
  API-for-workers becomes expressible and the env signal becomes truthful. Higher risk (some users authenticate the
  interactive session via the API key and rely on hydration), so it needs an explicit opt-in.
- **P3 — Promotion.** If this map is useful as normative reference, link it from documentation-guidelines "Authority
  Map" and/or fold the schema-level detail into `design_appendix.md` (§A.9 cost config / §A.13 usage ledger).

---

## Appendix — File / symbol index

| Area                     | file:symbol                                                                                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Request cost log         | `proxy/cost_logger.py:44` `log_request_cost`, `:92` `read_cost_logs`                                                                                         |
| Cost tracker / caps      | `proxy/cost_tracker.py:38` `CostTracker` (`:66` bootstrap, `:185` check_cap, `:225` cap_summary)                                                             |
| Proxy metrics            | `proxy/metrics.py:44` `ProxyMetrics` (`:157` snapshot, `:222` singleton)                                                                                     |
| Cost calc + GET /        | `proxy/server.py` `_calc_and_log_cost`, `root`, `_attach_cap_summary`, `_with_spend_warning`                                                                 |
| Verb cost                | `core/reactive/cost_tracking.py:207` `track_verb_cost`, `:46` `VerbCostResult`, `:266` `read_verb_logs`                                                      |
| Usage ledger             | `core/usage/ledger.py:91` `UsageEvent`, `:147` `log_usage_event`, `:176` `read_usage_events`, `:59` `BillingMode`, `:47` `MeasurementSource`                 |
| Usage emitters           | `core/usage/emit.py:47/102/147/196` emit\_\*; `:255` `_anthropic_key_present`                                                                                |
| Billing classifier       | `core/usage/billing.py:14` `infer_billing_mode`                                                                                                              |
| Per-session read         | `cli/usage.py:37` `usage_cmd`; `core/ops/usage_summary.py:98` `build_session_activity_summary`, `:128` `render_summary_line`                                 |
| Proxy cost CLI           | `cli/proxy_costs.py:74` `costs_cmd`; `cli/proxy.py` `metrics_cmd`                                                                                            |
| Status-line cost         | `cli/statusline/registry.py:93` `_produce_cost`; `cli/status_line.py:746` `get_session_metrics`, `:1098` `format_billing_cost`, `:1051` `format_rate_limits` |
| Status-line billing mode | `cli/statusline/context.py:80` `has_api_key`, `:87` `billing_mode`                                                                                           |
| Credential registry      | `core/auth/capabilities.py:39` `CREDENTIALS`, `:125` `credentials_for_template`, `:147` `format_missing_credential_error`                                    |
| Credential resolution    | `core/auth/template_secrets.py:69` `resolve_env_or_credential`, `:18` `TEMPLATE_ENV_VARS`, `:58` `_auth_ignore_env`                                          |
| Credential store / CLI   | `core/auth/credentials_file.py`; `cli/auth.py`                                                                                                               |
| Async credentials        | `core/llm/credentials.py:192` `CredentialManager`                                                                                                            |
| Env build + hydration    | `core/reactive/env.py:156` `build_claude_env`, `:239` `_hydrate_credentials`                                                                                 |
| Interactive launch       | `session/claude/invoke.py:162` `_build_environment`                                                                                                          |
| Proxy upstream auth      | `proxy/proxy_orchestrator.py:265` `_ensure_template_credentials`; `proxy/passthrough.py:42` `build_upstream_headers`                                         |
| Config                   | `runtime_config.py:66` `StatusLineConfig` (`:78` cost_mode, `:189` auth_ignore_env); `config/schema.py` `CostConfig`/`CostCaps`                              |
