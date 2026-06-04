# Metric Evidence Simplification

Status: accepted, parked in `todo/` until an execution branch starts.

## Summary

Forge should stop acting like a pricing oracle. Cost, usage, rate limits, failures, content filters, latency, and cache
behavior should all be modeled as **route-reported metric evidence**: facts observed after a runtime/provider/gateway
request completes. Forge records those facts, derives aggregates, and applies policy to future actions.

The product rule:

```text
request/action runs
  -> route/runtime reports facts
  -> Forge records metric evidence
  -> Forge updates aggregates
  -> Forge evaluates policies
  -> policy affects future requests/actions
```

This makes cost a normal metric instead of a special subsystem with separate accounting semantics. It also gives users a
clearer story: Forge shows what the route reported; if a route cannot report a value, Forge says unavailable rather than
inventing a billing truth from a local price table.

## Motivation

Forge now spans several genuinely different execution and billing routes:

- Interactive Claude Code, which reports session fields to `statusLine` over stdin.
- Headless `claude -p`, which can report JSON/stream JSON usage/cost when requested.
- Anthropic passthrough, OpenRouter, LiteLLM, and future gateway routes, each with different reported-cost surfaces.
- Codex CLI and future Codex runtime work, where `codex exec --json` reports token usage but does not expose the same
  local dollar signal as Claude Code.
- Future sidecar/proxy work that may observe more runtime traffic, including OAuth-backed runtime requests, but still
  may not prove who pays.

The current design carries local pricing and presents several subtly different "cost" views: Claude-reported status-line
cost, Forge proxy catalog estimates, verb snapshot estimates, usage-ledger attribution, and spend-cap totals. That makes
the system hard to explain and easy to misread.

## Ruthless Terminology Cleanup

Do not let one field imply several concepts. Split them and name them plainly:

| Term                 | Meaning                                                                        | Examples / notes                                                          |
| -------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| `route`              | How the work reached a model/runtime                                           | `claude_interactive`, `claude_p`, `forge_proxy`, `core_llm`, `codex_exec` |
| `reporter`           | The source that supplied the metric evidence                                   | Claude Code, OpenRouter, LiteLLM, Forge proxy, Codex JSONL                |
| `measurement_source` | What kind of metric was observed                                               | reported cost, reported tokens, gateway spend, runtime usage, none        |
| `payer`              | Who appears to pay, only when provable or user-declared                        | Anthropic API, Claude subscription, OpenRouter credits, unknown           |
| `confidence`         | Whether a value is reported, calculated by a gateway, inferred, or unavailable | `reported`, `gateway_calculated`, `inferred`, `unknown`                   |
| `scope`              | What the aggregate covers                                                      | interactive session, Forge session, proxy process, proxy history, account |
| `policy_action`      | What Forge does after the aggregate crosses a threshold                        | warn next request, reject next request, stop workflow, degrade route      |

Avoid these overloaded phrases unless the qualifier is present:

- "cost" without source/scope
- "authoritative spend" for local estimates
- "API billing" inferred only from `ANTHROPIC_API_KEY`
- "usage" when the surface really means Forge automation activity, not the whole interactive conversation
- "exact" for dollar values that are still catalog estimates

Preferred display language:

- `$0.23 OpenRouter reported`
- `$0.23 LiteLLM reported`
- `$0.23 Claude reported`
- `Quota 41% Claude`
- `cost unavailable`

## Design Direction

### Scope (this card): additional cost only, never the main harness

Forge does not own or recompute the main harness's cost — that stays Claude Code's number in every regime (OAuth or API
key). Interactive mode is in scope here for **one reason**: the status line (`forge status-line`) is Forge's own script
and must render correctly whether the session came from `forge session start` or from a plain `claude` the user launched
themselves (ambient).

When a Forge proxy happens to observe main harness traffic, that raw request evidence may still exist in proxy logs, but
user-facing Forge status/usage surfaces must not blend it into "Forge additional cost." The separation is display and
attribution first: Claude's native harness signal stays Claude's; Forge's extra work is shown separately.

The status line shows two clearly-separated things:

- **Claude Code's native signal, as Claude's.** Branch on `rate_limits`: present -> show the quota as Claude's
  subscription signal; absent -> show Claude's own `cost.total_cost_usd` as Claude-reported cost with payer unknown unless
  the user explicitly declared API mode. Forge never re-attributes or recomputes it.
- **Forge's additional cost, clearly marked as Forge's** (e.g. `forge +$Y`) — the extra `claude -p` work Forge caused,
  rendered as a distinct segment so it never blends into Claude's native cost.

Forge only *tracks* (ledger/attribution) additional cost when the route reporter returns cost metadata: Claude headless
JSON/stream-json, OpenRouter, LiteLLM, or another gateway/runtime reporter. No reported pricing -> report nothing, not a
catalog estimate.

This narrows once MITM-by-default puts Forge on the wire for harness traffic too; out of scope for this card.

### 1. Reported Cost Wins

Use cost reported by the route when available:

- Interactive Claude Code harness: **not tracked or reported by Forge** (see Scope). The status-line `rate_limits` quota
  is used only as Claude subscription/quota display evidence.
- Headless `claude -p`: record the run's JSON/stream-json cost metadata when present; if a run returns no JSON pricing,
  report nothing rather than estimate.
- OpenRouter: use OpenRouter-reported cost surfaces instead of recomputing from Forge's catalog.
- LiteLLM: use LiteLLM response/proxy spend metadata instead of recomputing from Forge's catalog.
- Codex: ingest `codex exec --json` token usage; cost remains unavailable unless a Codex/OpenAI surface reports credits
  or dollars.

Local pricing should no longer be the normal user-facing accounting source. For this card's scoped implementation, no
reported cost means no dollar cost is recorded or displayed.

### 2. Post-Flight Policies

Remove strict/preflight dollar cap semantics. A request may cross a cap; Forge records the reported cost and then blocks
or warns on the next request.

The simplified cap model:

```yaml
costs:
  caps:
    per_day: 20
    per_month: 100
  on_cap_hit: reject  # reject | warn
```

Document the tradeoff directly:

> Caps are enforced after completed requests using reported route cost. They prevent further spend after a cap is
> reached; they do not pre-estimate pending requests.

The same event/aggregate/policy loop is the longer-term generalization target for non-cost policies. This card should not
implement every row below; it should keep the data model compatible with them:

| Signal           | Post-event fact                   | Aggregate                         | Possible policy                         |
| ---------------- | --------------------------------- | --------------------------------- | --------------------------------------- |
| Cost             | reported charge                   | daily/monthly spend               | reject or warn next request             |
| Tokens           | input/output/cached/reasoning     | volume by route/model/session     | warn, downgrade route, stop workflow    |
| Rate limits      | remaining quota / reset           | latest known quota state          | pause, route elsewhere                  |
| Failures         | timeout/error/refusal             | recent failure rate               | retry, circuit-break backend            |
| Content filters  | filter/refusal category           | count by route/model/session      | stop workflow, require approval         |
| Latency          | request duration                  | p50/p95 or recent moving average  | mark backend degraded                   |
| Tool errors      | command/tool failure              | error rate by command/tool        | pause automation, require user approval |
| Policy decisions | supervisor allow/warn/deny/errors | session/workflow decision summary | escalate or stop workflow               |

### 3. Status Line as Reporter Channel

Claude Code's status-line stdin is a reporter channel, not a billing authority. It does not expose an explicit
`auth_mode`, `billing_mode`, `using_api_key`, or `using_oauth` field.

Rules for `forge status-line`:

- If `rate_limits` is present, treat it as strong subscription/quota evidence and show quota as the primary signal.
- Render Forge's own additional `claude -p` cost as a **distinct, labeled segment** (e.g. `forge +$Y`), separate from
  Claude's native cost/quota — never merge the two numbers.
- Do not infer API billing from `cost.total_cost_usd`; Claude may report dollar-equivalent estimated cost under
  subscription/OAuth.
- Do not infer API billing from a Forge credential-file key. `ANTHROPIC_API_KEY` availability is a capability signal,
  not a payer signal for the interactive runtime.
- If a Forge launch marker or session manifest is present, use Forge launch metadata to describe route evidence:
  direct/proxy, proxy id/base URL, and whether an API key was made available to the child.
- If `forge status-line` runs inside a plain `claude` process not launched by Forge, render it as an **ambient Claude**
  session using only Claude stdin fields and immediate env. Do not consult Forge credential-file resolution to classify
  billing.

Recommended launch metadata for Forge-started Claude sessions:

| Field                         | Meaning                                                |
| ----------------------------- | ------------------------------------------------------ |
| `launch_route`                | `direct` / `proxy` / `sidecar` / `custom_base_url`     |
| `proxy_id` / `base_url`       | Known proxy route, when Forge set one                  |
| `api_key_available_to_child`  | Whether Forge put `ANTHROPIC_API_KEY` in Claude's env  |
| `api_key_source`              | `env` / `file` / `none` / `unknown`                    |
| `user_declared_billing_mode`  | Explicit override, if configured                       |
| `runtime_reported_quota_seen` | Whether Claude stdin has shown subscription rate-limit |

### 4. Runtime Generalization

Keep the route-reporter model runtime-neutral:

- Claude interactive: status-line stdin reporter.
- Claude headless: JSON/stream-json reporter.
- Codex headless: `codex exec --json` reporter, with token usage on `turn.completed`.
- Codex interactive: native footer and `/status` are user-facing runtime UI, not a Forge telemetry channel unless Codex
  exposes one.
- Proxies/gateways: response metadata or spend APIs are reporter channels.
- Sidecar/proxy future: richer observation improves route evidence, but payer remains separate unless the route proves
  it.

## Known Bugs And Drift To Fold In

These came out of the auth/cost/usage audit and should be handled with or before this card:

1. **Status-line billing inference is misleading.** `RenderContext.billing_mode` currently treats raw
   `ANTHROPIC_API_KEY` in the interactive env as API billing. Because Forge hydrates credential-file values into
   interactive Claude envs, that can misclassify OAuth/subscription sessions.
2. **Interactive vs headless hydration is coupled.** `build_claude_env()` injects a resolvable `ANTHROPIC_API_KEY` into
   both interactive and headless Claude processes. Decide whether this remains a compatibility default with explicit
   labeling, or add an opt-in path that keeps API keys out of interactive sessions while preserving headless auth.
3. **Ambient status-line sessions need a distinct path.** `forge status-line` can run inside `claude` launched directly
   by the user, not only `forge session start`. Ambient sessions must not be classified using Forge launch assumptions.
4. **Cost-log readers crash on valid-but-non-object JSON.** `read_usage_events()` guards with `isinstance(record, dict)`
   (`ledger.py:217`); the cost plane doesn't — both `read_cost_logs()` (`cost_logger.py:127`) and
   `bootstrap_from_logs()` (`cost_tracker.py:136`) call `.get()` on each decoded line, so a stray `[]`/`1`/`"x"` raises
   `AttributeError` (not caught by the surrounding `OSError` handler), crashing `forge proxy costs` and the cap
   bootstrap at proxy startup. Fix: add the ledger's `isinstance(record, dict): continue` guard to both paths;
   corruption-class, so it needs a regression test.
5. **Credential docs are stale.** End-user and design credential tables omit `OPENROUTER_BASE_URL` for `openrouter` even
   though the code models it as a non-secret connection value. They also need clearer wording around effective template
   coverage for `anthropic-passthrough`.
6. **`auth_ignore_env` docs overpromise separation.** Current docs imply shell keys can be ignored for Forge
   subprocesses while Claude Code uses its own auth, but hydration applies to interactive launches too. User docs should
   state the actual behavior or the implementation should add the separation.
7. **Usage naming is too broad.** `forge usage` reports Forge automation activity plus policy decisions, not total
   interactive session usage. Rename, subtitle, or consistently label this scope in docs and CLI output.
8. **"Exact" and "authoritative" language is unsafe.** Proxy request joins can be exact by `request_id`, and provider
   token counts can be exact, but dollar values are not provider invoices unless the route reports them.

## Implementation Slices

1. **Schema and vocabulary pass**

   - Define metric evidence fields that separate route, reporter, measurement source, payer, confidence, and scope.
   - Decide whether to evolve the existing usage ledger or introduce a broader metric-event ledger.
   - Update `docs/design.md` and `docs/design_appendix.md` only for shipped slices.

2. **Cost source replacement**

   - Teach proxy/gateway paths to persist reported cost when available.
   - Remove local pricing from normal accounting output.
   - Verify no hidden dependency on the pricing catalog must survive before deleting or isolating it.
   - Preserve route-reported tokens even when cost is unavailable.

3. **Post-flight aggregate policies**

   - Remove `cap_mode: strict` or mark it deprecated.
   - Apply cap decisions after reported-cost events update aggregates.
   - Lock/reject/warn future requests when aggregates cross thresholds.
   - Generalize the same policy loop for failure/content-filter/latency thresholds where practical.

4. **Status-line honesty**

   - Prefer `rate_limits` over API-key presence for subscription display in `auto`.
   - Add Forge launch metadata for Forge-started Claude sessions.
   - Add ambient-mode handling when no Forge launch/session metadata exists.
   - Keep explicit `statusline.cost_mode=api|subscription` as a user declaration, not an inference.

5. **Headless runtime reporters**

   - For Claude headless, consider using JSON/stream-json output so `claude -p` can report cost/usage directly.
   - For Codex headless, ingest `codex exec --json` `turn.completed.usage`.
   - Keep runtime-native reported values separate from proxy/gateway reported values.

6. **Docs and CLI cleanup**

   - Update `docs/end-user/authentication.md`, `docs/end-user/config.md`, `docs/end-user/proxy.md`, and
     `docs/end-user/session.md` with the new terms and scopes.
   - Fold or supersede `docs/auth_cost_metric.md` as the internal map once implementation starts.
   - Add a user-facing "which surface answers which question?" table.

## Open Questions

- Is there any hidden dependency on the local pricing catalog outside normal user-facing cost accounting that must survive
  the removal?
- Should reported-cost caps support token-only fallback policies, or should dollar caps simply ignore cost-unavailable
  events?
- Should `forge usage` be renamed, or is a clear subtitle enough?
- Where should launch metadata live: session manifest only, a status-line sidecar file, or both?
- How much OpenRouter/LiteLLM reported-cost coverage can be implemented synchronously from responses versus follow-up
  lookup APIs?
- Should `auth_ignore_env` be redefined narrowly, or should a new config key express interactive/headless credential
  separation?

## Acceptance Shape

When complete, users should be able to answer these questions without understanding Forge internals:

- What route did this work use?
- Which reporter supplied the metric?
- Is this dollar amount reported, calculated by a gateway, estimated by Forge, or unavailable?
- What scope does this aggregate cover?
- What policy will Forge apply after this threshold is crossed?
- Did Forge launch this Claude session, or is this an ambient Claude status line?
