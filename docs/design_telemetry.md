# Forge Telemetry Design

Canonical status, spend, audit, usage-attribution, and provider-lifecycle contracts.

---

## Telemetry contracts

### 3.14 Cost tracking and spend caps

Forge records model-call evidence in a unified downstream telemetry plane under `~/.forge/telemetry/downstream/`. Legacy
`~/.forge/costs/*` files may still exist from older installs, but new proxy spend, redacted audit/drift/mutation facts,
provider lifecycle metadata, direct `core.llm` evidence, and native Codex token evidence write to downstream records.
Operation outcomes (policy checks, including no-call fail-opens) write to `~/.forge/telemetry/upstream/`.

| Path                                       | Writer                                    | Purpose                                                     |
| ------------------------------------------ | ----------------------------------------- | ----------------------------------------------------------- |
| `telemetry/downstream/<month>_<pid>.jsonl` | Proxy + Forge runtime emitters            | Per-attempt model-call evidence + audit/drift/mutation data |
| `telemetry/upstream/<month>_<pid>.jsonl`   | Operation/policy boundaries               | Per-operation outcomes; default volume is non-success       |
| `telemetry/caps/<proxy_id>.json`           | Proxy spend-cap tracker                   | Durable cap checkpoint used at restart bootstrap            |
| `telemetry/audit_state/<proxy_id>.json`    | Audit drift detector in proxy-id sidecars | Writable sidecar drift baseline                             |
| `usage/events/<month>_<pid>.jsonl`         | Legacy usage emitters                     | Transitional session activity/read-surface attribution      |

`core.telemetry.jsonl_io` owns sorted telemetry-shard reads, object-line decoding, and period matching; plane readers
retain schema fences, warnings, counters, filters, typed decoding, and sorting. `core.state.timestamps` owns ISO parsing
and local bounds: telemetry permits naive-as-UTC, each CLI owns `all`, and `TZ` accepts IANA, absolute/colon TZif, and
POSIX forms with `/etc/localtime` fallback. Relative display selects compact/full-word styles.

Downstream attempts are the proxy-spend source of truth. **Forge is not a cost oracle:** it records only route-reported
cost (OpenRouter `usage.cost` or LiteLLM `x-litellm-response-cost`) with its reporter/confidence, and records
`cost_micros:null`/`confidence="unavailable"` otherwise; no local price catalog infers dollars from tokens. Nullable
`backend_id` names the logical backend instance, distinct from the telemetry-origin `source_id`/`source_kind`; direct
emitters set it only when the mapping is unambiguous. Schema-v2 readers fence older records with a warning and expose
skip counts rather than reattribute them.

`CostTracker` takes the larger attempt/checkpoint total. Completion updates counters before an unbounded FIFO worker
persists cost/trace and coalesced snapshots. Shutdown drains jobs and retries failed checkpoints; hangs can delay it.
Passthrough response-body audit and overload/drop stay separate. Current-month shards preserve restart evidence.

The directory's lifecycle owner is global `telemetry.downstream` in `~/.forge/config.yaml` (`14` days/`512` MB by
default; `0` disables either bound). After cap bootstrap, each process resolves once and prunes once. Explicit global
config wins; otherwise agreeing explicit legacy values become warned `legacy_consensus`, omissions do not conflict, and
conflicting/unreadable inputs disable pruning with degraded status. Startup never rewrites proxy files. Explicit
`forge config migrate-retention [--yes]` writes the global owner before removing still-matching legacy keys; human/JSON
status exposes configured/effective/source plus deprecations and conflicts.

The legacy `costs/verbs/` writer and reader have been removed. The default `forge telemetry costs show` by-verb view
joins downstream attempts to `usage/events` by `forge_run_id`. Unique joined run IDs count runs; downstream rows count
requests, and unjoined requests remain "Interactive"/unattributed. The usage ledger itself remains during the transition
for session activity and run-tree joins, but it is no longer the durable spend source.

The transitional **usage-attribution ledger** (`~/.forge/usage/events/`, schema in
[§A.13](design_telemetry.md#a13-usage-attribution-ledger-schema-314)) records which run/workflow/session invoked each
model and carries `route`, `reporter`, `confidence`, consumption, and latency. It remains physically separate from
downstream, where spend, audit, and provider-lifecycle evidence coexist. Workflow verbs and headless consumers emit
best-effort events that never gate measured work. Direct `core.llm` calls may join by `source_refs.cost_request_id`;
`claude -p` cannot know individual proxy request ids, so its `source_refs` stays null. Instead, validated run-tree
headers let the proxy record `forge_run_id`/`forge_root_run_id`, and `forge telemetry activity`/`forge +$Y` join exact
downstream cost by root run id (one run can make many requests, so a single request ref is the wrong shape).

**Headless self-report.** Every `claude -p` run requests `--output-format json` (capability-gated with a
retry-once-and-latch backstop, so an older CLI that rejects the flag self-heals), so the runtime can self-report cost
and usage. Exactly **one** reporter attributes cost per run: a **proxied** run keeps the proxy snapshot
(`forge_proxy`/`reported`, Claude's Anthropic-priced `total_cost_usd` ignored as wrong-and-duplicate); a **direct** run
self-reports (`claude_code`/`reported`/`runtime_native`) — closing the prior `unavailable` gap on direct verbs — or,
when the envelope carries usage but no dollar figure (OAuth), records exact tokens with cost honestly `unavailable`.
Tokens follow the cost source (no mixed provenance). The run's `billing_mode` is resolved separately from cost: a
keyless direct `claude -p` consumer bound to a subscription lane (the `claude-max` backend) is labeled
`subscription_quota` (`resolve_billing_mode`, gated on the bound backend's `subscription_quota` posture; a resolvable
key still wins as `api`), while cost stays `unavailable` — only the label changes, never a fabricated dollar figure. The
opt-in `forge_cost` status-line segment surfaces this as `forge +$Y`: Forge-added LLM spend for the session,
**excluding** the main interactive harness (`route=claude_interactive`), reported-or-unavailable and distinct from
Claude's native cost ([§A.8](design_telemetry.md#a8-status-line-guidance-3611)).

**Native Codex usage.** A `codex exec` run goes **direct to OpenAI** (no Forge proxy), so there is no proxy cost record
to join: `emit_codex_usage` records `route=codex_exec`/`reporter=codex_jsonl`/`runtime_native` with the **exact** tokens
from the JSONL `turn.completed.usage`, but `cost_micro_usd=null`/`source_refs=null` and `confidence=unavailable` (the
ledger's `confidence` is a cost signal, and Codex reports no dollars — honest absence, not a fabricated $0). The event
carries the resolved `billing_mode` from `CodexPreflight`. Because the Codex child shares its parent's run tree
(`stamp_run_identity`), a Codex leaf and a Claude leaf join under the same `root_run_id` in `forge telemetry activity`.

**Transfer curation usage.** The `ai-curated` transfer's curation step makes a `core.llm` call (an Anthropic model via
OpenRouter) that is now attributed: it emits `route=core_llm`/`reporter=provider`/`runtime=forge_cli`/
`command=transfer-curate` with the provider's exact tokens (cost `unavailable` — `emit_direct_llm_usage` computes no
dollar figure for a direct `core.llm` call, so the event records exact tokens but no cost). The emit no-ops without an
ambient run identity, so a plain `forge session resume --strategy ai-curated` stays silent; the cross-runtime bridge
mints a run-tree root, so there the curation event and the `codex exec` run share one `root_run_id` and
`forge telemetry activity` shows both sides of the hop.

**Provider lifecycle evidence.** Backend-gated fields record dispatch, provider, and stream progress
([§A.14](design_telemetry.md#a14-provider-lifecycle-fields-in-downstream-telemetry-314)); trace reads are local and
exclude prompts/secrets. Global `provider_trace.inject_provider_user` hashes run grouping across proxy/direct paths and
affects observability only.

Each proxy may define:

```yaml
costs:
  caps:
    per_day: 20.00
    per_month: 100.00
  on_cap_hit: reject  # reject | warn
```

The user-injection opt-in is global in `~/.forge/config.yaml` (`provider_trace.inject_provider_user`, governing both
proxied and direct routes). Downstream lifecycle is also global, under `telemetry.downstream`. The old proxy-local
`audit`/`provider_trace` retention keys remain deprecated migration inputs for one compatibility release; new proxy
files do not author them. A stale `inject_provider_user` left in `proxy.yaml` loads with a one-time relocation warning
and is ignored.

Caps are enforced after each completed request, from accumulated recorded spend: a request may cross a cap and complete,
then the next request is blocked once spend has reached the cap. Because spend accrues only from reported cost, **dollar
caps fire only for routes that report cost** (OpenRouter, LiteLLM non-streaming); Anthropic-passthrough and
LiteLLM-streaming dollar caps are no-ops (their tokens are still tracked). `reject` returns HTTP 429 with:

```json
{
  "type": "error",
  "error": {
    "type": "spend_cap_exceeded",
    "message": "daily spend cap reached: ..."
  }
}
```

`warn` mode forwards the request and returns the same message in `X-Spend-Warning`. Cost tracking is best effort:
cost-capture or log write failures must not break successful LLM responses.

#### Per-session usage read surface

`forge telemetry activity [session]` aggregates the captured per-session planes into a two-pane human-readable view. The
**Operation outcomes** pane reads upstream outcomes by `session` (policy checks, supervisor fail-open/no-call outcomes,
memory writer, supervisor shadow drain, shadow curation, workflows/workers, transfer curation, and action tagging). The
**Model calls** pane reads downstream spend/token evidence joined by run tree, with `usage/events` retained as a
transitional source for session-tagged run correlation, labels, legacy error counts, and fallback cost.
`downstream_only` therefore means "downstream/model-call evidence whose run tree is known to this session but has no
matching upstream outcome"; fully orphaned downstream records with no session-known run tree are not attributable to a
session. When older downstream schemas are fenced during an upgrade, the activity downstream pane reports
`skipped_legacy_schema` so a fully legacy window does not look like ordinary empty data.

The manifest's **`confirmed.policy.decisions`** remains a compatibility fallback for success/cached policy counts and
warning text that upstream suppresses at the default `upstream_event_volume=non_success`; it is capped at
`MAX_DECISION_LOG`, so `log_capped` marks that older success/cached counts may be missing. Upstream non-success outcomes
are uncapped, and manifest/upstream duplicate warnings are deduped. The aggregation is a UI-agnostic command-core
builder (`forge.core.ops.usage_summary.build_session_activity_summary`, §3.12) shared by the CLI and the compact
`render_summary_line(...)` launcher exit line (host, sidecar, and fork). Cost is reported-or-estimated and may be
partial; `forge telemetry costs show` stays the authoritative spend view. See
[design_telemetry.md §A.13](design_telemetry.md#a13-usage-attribution-ledger-schema-314) for the read surface and
coverage.

### A.8 Status line guidance (§3.6.11)

Status line reads Claude Code's stdin JSON plus two env-var-addressed sources:

| Source            | Address                                | What it provides                                                  | Availability          |
| ----------------- | -------------------------------------- | ----------------------------------------------------------------- | --------------------- |
| Claude Code stdin | piped JSON                             | model, workspace, context_window, cost, rate_limits, session_id   | Always                |
| Session file      | `FORGE_SESSION`                        | Intent, overrides, confirmed facts                                | Always (file)         |
| Proxy registry    | `ANTHROPIC_BASE_URL` -> reverse lookup | proxy_id, template, port                                          | Always (file)         |
| Proxy `GET /`     | `ANTHROPIC_BASE_URL` -> query          | backend, tier/alternative maps, context, metrics, intercept, caps | Only if proxy running |

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
`spend_cap`, `launch`, `forge_cost`, `marking`. Full key/segment reference: `docs/end-user/config.md`.

**Segment-lazy source acquisition.** `types.py` owns neutral facts, `sources.py` fail-open acquisition, `formatting.py`
presentation/ANSI width/truncate/wrap, and `rendering.py` palette/hardening/final layout. `status_line.py` owns only
stdin, plan-shared proxy/session acquisition, terminal width, and stdout; lower modules never import it. Registry
requirements are unioned once: `path`, `branch`, `lines`, `tokens`, `think`, and `hooks` need neither shared source;
`model`, `rate_limits`, `cache_hit`, `audit`, `drift`, and `spend_cap` need proxy; `breadcrumb`, `loop`, `sidecar`,
`supervisor`, `policy`, `launch`, and `forge_cost` need session; `cost` and `marking` need both. Thus `[path, branch]`
touches neither shared source. Lazy `RenderContext.cached_property` is the process-local per-render cache; persistent
throttles remain file-backed. The empty/default layout requests both sources and stays byte-compatible and fail-open.

**Billing-aware cost.** Billing mode is an explicit **declaration**, never inferred from a key. `cost_mode=api` shows
real `$`; `cost_mode=subscription` shows quota burn instead of dollar spend — both the 5h and weekly windows,
`5h:N% · 7d:M%`, heat-mapped on the context gradient with the reset bound to the hotter window (`7d:52%↻1d`).
`cost_mode=auto` shows the quota when `rate_limits` is present, else hedges `≈$` — an `ANTHROPIC_API_KEY` in the env is
a *capability*, not proof of who pays (Forge may have hydrated it into an OAuth session), so it never flips `auto` to
API dollars. Proxy mode always shows the proxy's *reported* `~$` (may undercount; cost-unavailable routes are excluded,
not locally priced).

**Launch metadata.** The opt-in `launch` segment renders `confirmed.launch` (CLI-written once at start): the route
(`direct` / `proxy:<id>` / `custom`) and the api-key posture (`key:env|file|none|omit`). It describes how the session
reached the model and whether a key was made available — honest auth provenance the status line cannot infer from the
ambient env. Manifest-gated: absent for ambient sessions (no `FORGE_SESSION`).

**Provider-declared text marking.** The opt-in `marking` segment renders the observed stdin model as `mark:yes`,
`mark:no`, or `mark:?`. For a proxy route it applies server routing precedence (explicit request tier before proxy
default; matching model alternative before tier default) and requires the new authoritative live backend and mapping
fields for `yes` or `no`. Older/unreachable proxy responses and config/route-commit fallback render `?`. Direct mode
also renders `?` in this version because Forge has no authoritative direct backend identity. A missing stdin model omits
only this segment. Catalog, source, and expected mapping failures resolve to `?`; unexpected producer failures retain
the registry's segment-level fail-open behavior. `no` means a matching provider declaration says unmarked—it is not
detection, admission, or an authorship claim. The segment is not in `DEFAULT_ORDER`.

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
newest-first contiguous run of recorded frontier-supervisor non-success outcomes across Claude or Codex lanes (reset by
the first `success`), and `<kind>` is `timeout` or `error`. Posture-independent — suspended/off emit no events, so prior
fail-open history stays visible. ASCII `!` (no unicode glyph; survives `normalize-text`). Tiered like
`format_spend_cap`: YELLOW 1-2, RED `>=3`; the suffix never shows at 0, so a healthy `SUP` is byte-identical to today.
Read throttled + fail-open by `read_or_compute_session_health` (same `forge_cost_ttl` window, distinct `fhealth-`
cache); a read error degrades to **posture-only** (no suffix), never hiding the posture (unlike `forge_cost`, whose
whole value is ledger-derived). Source combines legacy `UsageEvent.status`/`failure_type` with upstream supervisor
policy outcomes, so timeout/subprocess failures, proxy lookup fail-opens, depth skips, and parse fail-opens all
contribute to the streak when recorded.

**Rendering.** `where` (`path`, `branch`) leads concatenated; other segments are separator-joined in configured order.
Lazy `RenderContext.cached_property` derivations prevent inactive-segment I/O. Forge-unique segments read **effective**
session state (`apply_overrides(intent, overrides)`), so `%policy`/`%supervisor` overrides change posture without intent
edits.

Human token/USD strings use explicit `forge.core.metric_formatting` policies: whole-cent direct cost, fractional-cent
proxy cost, and four-decimal tiny caps. Context size stays separate.

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

| Path                                       | Schema owner                      | Retention policy                                     |
| ------------------------------------------ | --------------------------------- | ---------------------------------------------------- |
| `~/.forge/telemetry/downstream/*.jsonl`    | `forge.core.telemetry.downstream` | Global `telemetry.downstream`; current month kept    |
| `~/.forge/telemetry/upstream/*.jsonl`      | `forge.core.telemetry.upstream`   | Append-only until explicit reset/user prune          |
| `~/.forge/telemetry/caps/<proxy_id>.json`  | `forge.core.telemetry.caps`       | Durable cap checkpoint; reset by explicit cost reset |
| `~/.forge/telemetry/audit_state/<id>.json` | `forge.proxy.audit_logger`        | Sidecar drift baseline                               |
| `~/.forge/usage/events/*.jsonl`            | `forge.core.usage.ledger`         | Transitional attribution ledger; reset/user-prune    |

Downstream attempts carry model/tokens, reported-or-null cost with provenance, redacted audit/provider lifecycle fields
(§A.14), and optional run-tree ids from validated `X-Forge-Run-ID`/`X-Forge-Root-Run-ID` headers. `backend_id` is the
logical backend instance (not a local managed-process id), while `source_id`/`source_kind` identify telemetry origin.
Schema-v2 readers warn and count skipped older records instead of reattributing them. Internal `X-Forge-Session`
(hashed, never the raw name) and `X-Forge-Command` correlation headers are validated and never forwarded upstream; the
explicit OpenRouter `user` field is separate. There is no local price catalog. Stable per-attempt `downstream_event_id`
merges duplicate evidence without collapsing retries; backend filtering occurs after merge. By-verb cost joins
downstream to transitional `usage/events` by run id.

Proxy completion updates memory before an unbounded FIFO worker persists detached cost/lifecycle records and cap
snapshots. Lifespan drains accepted jobs and retries failed checkpoints; filesystem hangs can delay it. `GET /` remains
live. Passthrough response-body audit and overload/drop policy are separate; downstream shards bootstrap restarts.

Caps are process-local; use one process per proxy ID.

After cap bootstrap, global retention bounds downstream shards but preserves the current UTC month; upstream and usage
accumulate until cleanup. `forge telemetry costs reset` (previewable with `--dry-run`) wipes all telemetry, cap/audit
state, usage attribution, and derived cost/health caches. Running proxies retain in-memory totals/caps until restarted.

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
| `logging.requests.enabled`                 | `off`, `auto`, `on` (default `auto`)         | `auto` couples to `log_level=debug`; `on` decouples bounded capture                               |
| `logging.requests.body_capture`            | `metadata`, `redacted` (default `metadata`)  | `metadata` omits the body; `redacted` reuses the audit redaction builder; **no** `full`/plaintext |
| `logging.requests.response_capture`        | `metadata`, `redacted` (default `metadata`)  | Same policy for the response body                                                                 |
| `logging.requests.max_file_mb`             | int (default `16`, `0` = unbounded)          | Per-shard rotation cap                                                                            |
| `logging.requests.max_total_mb`            | int (default `256`, `0` = unbounded)         | Prune oldest request shards over budget at startup                                                |
| `logging.requests.retention_days`          | int (default `14`, `0` = no age bound)       | Prune request shards older than N days at startup                                                 |
| `logging.requests.stream_chunks`           | bool (default `false`)                       | Opt-in per-chunk debug dumps; off even at `log_level=debug`                                       |
| `logging.requests.stream_chunk_max_bytes`  | int (default `0` = small cap)                | Truncate each dumped chunk                                                                        |

`src/forge/proxy/response_headers.py` owns raw response metadata: it excludes security/framing,
`OpenAI-Organization`/`OpenAI-Project`, `Connection` extensions, and Forge cost/resolution/correlation fields; stamps
request ids; and applies overlays case-insensitively. Transports own bodies, SSE, accounting, and teardown.

Raw transports read non-200 bodies before closing stream and client. A read `httpx.HTTPError` records one failure and
returns the stable 502 body, never partial content. Other exceptions propagate after cleanup without completion.
Readable errors preserve status, body, and safe headers.

Override reasoning reuses `tier_overrides.<tier>.reasoning_effort` (§A.1). Normal `forge proxy set` edits
intercept/audit fields and warns that full-body audit writes redacted structure to downstream telemetry. Audit/provider
lifecycle share cost shards under global `telemetry.downstream`; old proxy retention keys are compatibility inputs
removed explicitly by `forge config migrate-retention`.

Strict `RequestLogConfig` owns separate owner-only, PID-sharded debug diagnostics under `~/.forge/logs/requests/`, with
rotation and per-proxy retention via `prune_jsonl_shards`. It rejects unknown/full-plaintext modes and reuses the audit
redactor; `log_retention_days` remains the coarse floor.

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
  `pattern_hash`, `stripped_count`, `effort_floor`, `budget_before/after`, and key-name-only
  `removed_sampling_parameters`.

Reading skips records written by a newer Forge (`schema_version` > current) with a one-time warning.
`forge proxy audit show|diff` (§4.0) is the read surface.

### A.13 Usage-attribution ledger schema (§3.14)

The canonical **attribution** plane: which run/workflow/session invoked which runtime/provider/model via which route,
and what it consumed. Modeled on the audit log (versioned, strictly read). The three data planes stay physically
separate and are joined by a shared proxy `request_id`:

The proxy validates an optional client `X-Request-ID` before using that join key: 1--128 ASCII letters, digits, `.`,
`_`, and `-` are preserved exactly; an absent or invalid value mints the normal endpoint-prefixed ID. Rejected values
never enter the joined planes or the Forge-owned response header.

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
  native `codex` runtime. `proxy_request_exact` (Phase 4g) is the provenance of a **read-time** figure, not a stored
  event source: a proxied `claude -p` event keeps `verb_snapshot_estimated` in the ledger, but
  `forge telemetry activity` / `forge +$Y` recompute that run tree's cost exactly from the cost plane (sum of cost
  records by `forge_root_run_id`) and label the result `proxy_request_exact`, **suppressing** the snapshot to avoid
  double-counting. Suppression is **per-run-subtree** (the snapshot's own run, or a verb whose direct children produced
  records — derived from worker `parent_run_id`), never whole-root, so a correctly-unstamped sibling sharing the session
  root keeps its snapshot instead of being silently dropped. A figure with no snapshot estimate mixed in — cost-plane
  exact (4g root-join) and/or runtime-reported (`runtime_native`) — renders **without** the `~` estimate marker
  (`cost_estimated=False` on the summary/command DTOs); a figure mixing in a snapshot estimate keeps `~`.
- `billing_mode`: `api` | `subscription_interactive` | `subscription_headless_credit` | `subscription_quota` | `unknown`
  (`unknown` is the honest default where the signal is ambiguous). `subscription_quota` is emitted for a keyless
  headless consumer subscription -- `codex exec` on ChatGPT, and (T0) a keyless direct run bound to the `claude-max`
  lane (`resolve_billing_mode`, gated on the bound backend's `subscription_quota` posture); `subscription_interactive`
  and `subscription_headless_credit` stay reserved.
- `attribution_granularity`: `worker` | `verb` | `session`.
- `route`: `claude_interactive` | `claude_p` | `forge_proxy` | `core_llm` | `codex_exec` — how the work reached the
  model (invocation channel). Emitted now: `claude_p`/`core_llm`/`codex_exec` (plus `None` on an aggregate spanning
  mixed routes); `claude_interactive` stays reserved, like the unemitted `subscription_*` billing modes. `forge_proxy`
  is reserved **here** — it is emitted now as a `reporter`, not yet as a `route` (it appears in both literals).
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

**Instrumented emitters (Phase 4c).** Workflow verbs (`panel`/`analyze`/`debate`/`consensus`) emit one ambient-run
`verb_snapshot_estimated` event because per-worker cost is unavailable. Claude subprocesses emit through
`emit_usage_for_session_result`; the shipped Codex memory-writer, semantic-supervisor, and shadow-curation arms emit
through `CodexHeadlessInvoker`. The action tagger emits exact in-band provider usage from `core.llm`. On the **direct
path**, Forge resolves the base URL synchronously: if it is a registered Forge proxy, the tagger forwards an
`X-Request-ID` and records an exact `source_refs.cost_request_id` join (the proxy logs its cost record under the same
id). The core minter is contract-tested against the proxy ingress validator so the accepted-ID precondition cannot
silently drift; otherwise the caller sends no header and leaves the ref null (a dangling join is worse than none).
Direct-path `billing_mode` stays `unknown` unless the caller proves direct + real-credential billing (the tagger routes
via local LiteLLM with a dummy key, so it can't). All emit best-effort, never gate the work they measure, and record
`latency_ms`; `claude -p` events carry null `source_refs` and join to exact cost by run tree (`forge_root_run_id`, Phase
4g). Helpers: `emit_verb_usage`, `emit_usage_for_session_result`, `emit_direct_llm_usage` (`forge.core.usage.emit`).
Each also stamps `route`/`reporter`/`confidence`: tagger → `core_llm`/`provider`/`unavailable`; the verb aggregate
claims no single `route`.

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
tokens). `resolve_claude_p_measurement` solely owns this precedence; emitters supply identity and persist its result.

**Per-worker fan-out events (Phase 4d/5).** The review fan-out (`run_multi_review` →
`ClaudeHeadlessInvoker.run_parallel`) emits one event per worker (`attribution_granularity=worker`): the run-tree leaf
(run/parent/root) plus the **actual routed** `model` (`route.model_ref`), `provider`, and `proxy_id`, with `status` and
`latency_ms`. Cost follows the same one-reporter precedence (Phase 5): a **direct** worker self-reports (`claude_code` /
`runtime_native`, or `provider_usage_exact` tokens-only); a **proxied** worker stays `unattributed` with null
cost/tokens — the verb-level aggregate above holds the estimated proxied total, so attributing per-worker would
double-count. Helper: `emit_worker_usage`.

**Read surface — `forge telemetry activity` and the session-end summary.**
`build_session_activity_summary(name, forge_root, since=)` produces a `SessionActivitySummary` with compatibility
command rollups plus two explicit panes. The `upstream` pane groups `UpstreamOutcome`s by
command/operation/status/reason and carries `PolicyActivity` from the manifest fallback; the fallback is capped at
`MAX_DECISION_LOG`, so `log_capped` is surfaced and duplicate manifest/upstream warnings are suppressed. The
`downstream` pane groups model-call/spend evidence visible to the session: downstream records whose run tree is known
from upstream or `usage/events`, records whose provider-session id matches the hashed session prefix, and transitional
`usage/events` command rows for labels/legacy error counts. Rows carry `join_state` (`matched`, `upstream_only`,
`downstream_only`); a truly orphaned downstream record with no session-known run tree is not session-attributable.

`forge telemetry activity --json` is a clean-break shape with top-level `session`, `since`, `upstream`, `downstream`,
`shadow`, `subagents`, and `notes` only. Old top-level `commands`, `policy`, `total_events`, and
`session_tagging_partial` fields are represented inside panes or `notes`. The launcher still prints the compact one-line
`render_summary_line(...)` on exit (host, sidecar, fork) from the same builder. The `failing open: N timeout, N error`
clause still comes from the window's supervisor failure split; JSON exposes those legacy counts under
`downstream.rows[*].error_kinds`. The downstream pane also exposes `skipped_legacy_schema` when older downstream
identity schemas were fenced from the current read. Cost is reported-or-estimated and may be partial;
`forge telemetry costs show` is authoritative. Each model-call row also carries the lane its usage events ran on --
`runtime` and `billing_mode` (uniform, `mixed` when a command's events disagree, `null`/`-` for a downstream-only row
with no usage-event source). The per-call ledger carries **no** catalog backend id, so the full
`(runtime, backend, model)` lane shows on `forge policy supervisor status`, not here.

Per-emitter session coverage (a per-session summary is honest about what it can attribute):

| Emitter                                                                   | Tags `session`? | Notes                                                                                          |
| ------------------------------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------- |
| Semantic supervisor (Claude helper / Codex invoker)                       | Yes             | `session=context.session_name` (= manifest name)                                               |
| Supervisor shadow (runtime-arm emitter + upstream)                        | Yes             | `command=supervisor-shadow`; `operation=policy.shadow_drain`; re-rooted under origin session   |
| Memory writer (Claude helper / Codex invoker)                             | Yes             | `session=session_name`                                                                         |
| Shadow curation (Claude helper / Codex invoker)                           | Yes             | `session=session_name`; `command=curation`                                                     |
| Workflow verbs panel/analyze/debate/consensus                             | Yes             | threaded `session=$FORGE_SESSION` (verb aggregate + per-worker)                                |
| Transfer curation (`emit_direct_llm_usage`, `transfer-curate`)            | Yes             | `session=$FORGE_SESSION`; ai-curated strategy only; `route=core_llm`/`runtime=forge_cli`       |
| Rewind code-delta curation (`emit_direct_llm_usage`, `rewind-code-delta`) | Yes             | `session=$FORGE_SESSION`; rewind dropped-window curation; `route=core_llm`/`runtime=forge_cli` |
| Plan check (`emit_direct_llm_usage`, `plan-check`)                        | Yes             | cascade tier-1; `session=context.session_name`; `route=core_llm`                               |
| Action tagger (`emit_direct_llm_usage` + upstream outcome)                | Partially       | upstream tags `session`; spend event remains untagged, so cost coverage may be partial         |
| Team event tagger (`emit_direct_llm_usage`, `team-tagger`)                | Partially       | `session=$FORGE_SESSION` best-effort, else ambient (the handler carries no Forge session)      |

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

These shards use the global `telemetry.downstream` policy described in §A.7 and §A.11. Provider trace has no independent
retention owner or pruner.

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
- **Backend-capability gated.** Written only for capable backend instances (currently `openrouter` and
  `codex-responses-local`); other gateway and passthrough routes stay quiet.
- **Attempt boundary.** Once billable generation dispatch starts, transport/open/non-200 failures write one lifecycle
  record joined to cost by `downstream_event_id`. Before any provider response, lifecycle flags stay false; a received
  response sets `stream_started=true`, while content/usage and header cost reflect only observed evidence. Validation,
  conversion, routing, client construction, and non-generation relays write none.
- **`first_chunk_seen`** = first user-visible content chunk. The first-event `_provider_meta` carrier does not count, so
  a pre-content cancellation can retain its generation id with `first_chunk_seen=false`.
- **`local_usage_status`** = `available` after final usage or reported cost, else `unavailable`. Probe 2
  (`[REMOTE-ABSENT]`) found aborted streams absent remotely, so this remains local evidence with no `/generation` read.
- **`timeout_seen` is always `false`.** The proxy observes only its own client disconnect (`client_disconnected`), never
  the parent's `subprocess.run` timeout; the field is a join target for later run-tree correlation, not proxy-populated.
- **Joins** spend/usage by shared `request_id` + run-tree ids; one `claude -p` run produces many requests, so the
  run-tree join (`forge_root_run_id`) is the right shape (`tests/regression/test_bug_provider_trace_run_tree_join.py`).
- Reading skips, with a one-time warning, records written by a newer Forge (`schema_version` > current), and (strict on
  shape) records with unknown fields or bad `Literal` values. `read_provider_traces()` is the typed read surface.
  Provider-trace retention delegates to unified downstream shard pruning; current-calendar-month downstream shards are
  preserved for spend-cap bootstrap, and filtered compaction is follow-up work.
- **Read surface (Phase 4).** `forge telemetry trace list|show|explain` (op-backed `core/ops/provider_trace.py`;
  terminal-only, no `%` mirror). `list` filters by session *label* (re-derived `forge_sess_<hash>` prefix) /
  `forge_root_run_id` / `--period`; `explain` joins downstream spend evidence by `request_id` within ±5m for cost
  confidence. Local-only — no remote `/generation` lookup.
- **Session-id injection (opt-in, global).** `provider_trace.inject_provider_user` (default off) lives in
  `~/.forge/config.yaml` (`get_runtime_config().provider_trace`) and governs **both** planes; probe 3 found `user` is
  retained in the indexed `/generation` record for account-side lookup, while a custom `session_id` is ignored.
  Metadata-only, hashed, never the raw session name.
  - **Proxied path.** Forwards the validated `X-Forge-Session` id (or a `forge_run_<hash>` fallback) into the top-level
    `user` field on backend-capable routes — server-gated (`_provider_user_value`), adapter-forwarded via
    `extra["openai"]["user"]`.
  - **Direct path.** `resolve_direct_provider_user(role)` (`core/usage/correlation.py`) reads the same global flag plus
    `FORGE_SESSION`/`FORGE_ROOT_RUN_ID` (root falls back to `FORGE_RUN_ID`, mirroring `reactive/env.py`) and derives the
    id with the **same** `derive_provider_session_id`, so direct ids match proxied ones for one run.
    `with_openrouter_user` sets `extra["openai"]["user"]` (deep-copy, no-clobber). Wired into plan-check (role
    `plan-check`, gated on the resolved route being OpenRouter) and transfer curation (role `transfer-curate`, always
    OpenRouter). The tagger is excluded by design — it routes via local LiteLLM, which is not a provider-user-grouping
    sink.
  - **Direct-call ZDR.** `core/llm/openrouter_policy.py::with_openrouter_zdr` sets
    `extra["openai"]["extra_body"]["provider"]["zdr"]=true` without clobbering siblings. OpenRouter plan checks and
    transfer/rewind curation always apply it; proxy `allow_non_zdr` does not govern these calls.
  - **Migration.** The pre-Phase-4 per-proxy `proxy.yaml` key is deprecated: it loads with a one-time relocation warning
    and is ignored (warn-and-degrade, user-owned config is a system boundary). The sidecar mounts `~/.forge/config.yaml`
    read-only so in-container proxied forks read the same toggle.
- **Remote reconciliation (single-id MVP).** `forge model backend reconcile <backend>` joins one local trace to one
  account-side record through `forge.backend.remote`; registry presence defines capability. OpenRouter is the first
  adapter (`GET /api/v1/generation`, metadata-only). Results are `joined`/`remote`/`missing-remote`/`not-queryable`;
  remote failures become `not-queryable`, and remote figures never overwrite local cost/tokens. Windowed activity is a
  follow-on exposed by `RemoteCapability.window_*` and `fetch_activity`.

---
