<!-- prereq: 0.3 -->

## 7. Cost Tracking & Spend Caps

### 7.1 Cost CLI (Empty State)

<!-- auto -->

```bash
# Use a guaranteed-empty proxy_id for empty-state tests.
# Other sections (e.g., section 4 guided sessions) may have created real cost logs,
# so we cannot assume global cost logs are empty.
forge telemetry costs show qa-no-such-proxy 2>&1
echo "---"
forge telemetry costs show qa-no-such-proxy --period all 2>&1
echo "---"
forge telemetry costs show qa-no-such-proxy --json
```

- [ ] `forge telemetry costs show qa-no-such-proxy` shows `No cost data for today (qa-no-such-proxy).`
- [ ] `--period all` shows `No cost data for all (qa-no-such-proxy).`
- [ ] `--json` returns valid JSON with `total_cost_micros: 0` and `total_requests: 0`

### 7.2 Cost CLI (JSON Structure)

<!-- auto -->

```bash
# Verify JSON output schema using the empty-proxy filter (guaranteed empty)
forge telemetry costs show qa-no-such-proxy --json | python3 -c "
import json, sys
d = json.load(sys.stdin)
fields = {'period','proxy_id','total_cost_micros','total_cost_usd','total_requests','interactive_cost_micros','by_verb','by_model','reported_requests','unavailable_requests'}
missing = fields - set(d.keys())
print(f'MISSING={missing}' if missing else 'ALL_FIELDS_PRESENT')
print(f'period={d[\"period\"]}')
print(f'reported={d[\"reported_requests\"]} unavailable={d[\"unavailable_requests\"]}')
"
```

- [ ] JSON contains all required fields: `period`, `proxy_id`, `total_cost_micros`, `total_cost_usd`, `total_requests`,
  `interactive_cost_micros`, `by_verb`, `by_model`, `reported_requests`, `unavailable_requests`
- [ ] `period` is `today`
- [ ] `reported_requests` and `unavailable_requests` are present (provenance replaced the old `estimated` flag)

### 7.3 Seed Fixture Request Logs

<!-- auto -->

```bash
# Seed QA-prefixed fixture request logs matching cost_logger.py record schema.
# Uses qa-fixture prefix and PID 99999 to avoid collision with real proxy logs.
mkdir -p ~/.forge/costs/requests
cat > ~/.forge/costs/requests/qa-fixture_99999.jsonl <<'EOF'
{"ts":"2026-05-01T00:00:00Z","proxy_id":"qa-fixture","model":"test/gemini-2.5-flash","tier":"haiku","input_tokens":200,"output_tokens":80,"cached_tokens":0,"cost_micros":300,"reporter":"litellm","confidence":"gateway_calculated","latency_ms":120.0,"failed":false,"request_id":"req-qa-001"}
{"ts":"2026-05-01T00:01:00Z","proxy_id":"qa-fixture","model":"test/gemini-3.1-pro-preview","tier":"sonnet","input_tokens":500,"output_tokens":150,"cached_tokens":50,"cost_micros":1200,"reporter":"litellm","confidence":"gateway_calculated","latency_ms":350.0,"failed":false,"request_id":"req-qa-002"}
{"ts":"2026-05-01T00:02:00Z","proxy_id":"qa-fixture","model":"test/gemini-3.1-pro-preview","tier":"opus","input_tokens":1000,"output_tokens":400,"cached_tokens":100,"cost_micros":3500,"reporter":"litellm","confidence":"gateway_calculated","latency_ms":800.0,"failed":false,"request_id":"req-qa-003"}
EOF

# Verify fixture is readable -- filter by qa-fixture to isolate from real proxy logs
forge telemetry costs show qa-fixture --period all --json
```

- [ ] Fixture file created at `~/.forge/costs/requests/qa-fixture_99999.jsonl`
- [ ] `forge telemetry costs show qa-fixture --period all --json` shows `total_cost_micros` of 5000 (300 + 1200 + 3500)
- [ ] `total_requests` is 3
- [ ] `by_model` contains both `test/gemini-2.5-flash` and `test/gemini-3.1-pro-preview`

### 7.5 Cost CLI Breakdowns

<!-- auto -->

```bash
# By-model breakdown -- filter to qa-fixture to isolate from real proxy logs
forge telemetry costs show qa-fixture --by-model --period all 2>&1

echo "---"

# JSON with proxy_id filter
forge telemetry costs show qa-fixture --period all --json
```

- [ ] `--by-model` table shows model names with cost and token columns
- [ ] JSON output has `proxy_id: "qa-fixture"`
- [ ] Filtered `total_requests` is 3 (only qa-fixture records)
- [ ] Rich table output captured via `2>&1` (console uses stderr)

### 7.6 Malformed Log Resilience

<!-- auto -->

```bash
# Append non-JSON garbage lines to the fixture request log
echo 'THIS_IS_NOT_JSON' >> ~/.forge/costs/requests/qa-fixture_99999.jsonl
echo '<<<CORRUPT>>>' >> ~/.forge/costs/requests/qa-fixture_99999.jsonl

# Cost CLI should skip malformed lines -- filter to qa-fixture for deterministic count
forge telemetry costs show qa-fixture --period all --json 2>&1
echo "EXIT=$?"
```

- [ ] Command succeeds (exit 0) despite malformed lines
- [ ] Valid records still returned (`total_requests` is 3, not 5)
- [ ] No traceback or error on stderr

### 7.7 Spend Cap Configuration via CLI

<!-- prereq: 4.2 -->

<!-- auto -->

```bash
# Set spend caps on the test proxy from section 4
forge proxy set "$FORGE_QA_GEMINI_PROXY" costs.caps.per_day=20.00
forge proxy set "$FORGE_QA_GEMINI_PROXY" costs.caps.per_month=100.00
forge proxy set "$FORGE_QA_GEMINI_PROXY" costs.on_cap_hit=reject

# Validate config is healthy after cap changes
forge proxy validate "$FORGE_QA_GEMINI_PROXY"

# Show raw YAML to verify caps appear
forge proxy show "$FORGE_QA_GEMINI_PROXY" --raw
```

- [ ] `costs.caps.per_day` appears in raw YAML as `20.0` (float, not string `"20.00"`)
- [ ] `costs.caps.per_month` appears as `100.0`
- [ ] `on_cap_hit` is `reject`
- [ ] Config validates successfully after setting caps
- [ ] Raw YAML shows complete `costs:` section with `caps` and `on_cap_hit`

### 7.8 Spend Cap Config Validation (Invalid Values)

<!-- prereq: 4.2 -->

<!-- auto -->

```bash
# Invalid on_cap_hit -- should be rejected
forge proxy set "$FORGE_QA_GEMINI_PROXY" costs.on_cap_hit=invalid 2>&1; echo "EXIT=$?"
```

- [ ] Invalid `on_cap_hit` rejected with validation error (exit non-zero)
- [ ] `on_cap_hit` error message references valid values (`reject`/`warn`)

### 7.9 Spend Cap Enforcement (Reject Mode)

<!-- prereq: 4.2 -->

<!-- requires: api_key -->

<!-- human:guided -->

Seed a current-timestamp cost log so the proxy's cost tracker bootstraps above the cap, then make a request to verify
rejection. This avoids depending on a real request landing above a tiny cap (which is non-deterministic for cheap
models).

```
# Set a low daily cap on the working QA OpenAI proxy in the container
forge proxy set "$FORGE_QA_OPENAI_PROXY" costs.caps.per_day=0.01
forge proxy set "$FORGE_QA_OPENAI_PROXY" costs.on_cap_hit=reject

# Seed a cost log with a current timestamp so the tracker bootstraps above the cap.
# The tracker reads ~/.forge/telemetry/downstream/YYYY-MM_*.jsonl on startup (bootstrap_from_logs).
mkdir -p ~/.forge/telemetry/downstream
MONTH=$(date -u +%Y-%m)
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "{\"ts\":\"$TS\",\"proxy_id\":\"$FORGE_QA_OPENAI_PROXY\",\"model\":\"seed\",\"tier\":\"sonnet\",\"input_tokens\":0,\"output_tokens\":0,\"cached_tokens\":0,\"cost_micros\":50000,\"reporter\":\"litellm\",\"confidence\":\"gateway_calculated\",\"latency_ms\":0,\"failed\":false,\"request_id\":\"req-qa-cap-seed\"}" \
  > ~/.forge/telemetry/downstream/${MONTH}_99999_qa-cap-seed.jsonl

# Restart proxy so it bootstraps from the seeded log (--force bypasses shared-port check)
forge proxy stop "$FORGE_QA_OPENAI_PROXY" --force 2>/dev/null || true
forge proxy start "$FORGE_QA_OPENAI_PROXY"

# Make a request -- should be rejected immediately
forge claude start --proxy "$FORGE_QA_OPENAI_PROXY"
# Say "hello" -- expect rejection or error about spend cap, then exit (/exit)

# Clean up seeded log
rm -f ~/.forge/telemetry/downstream/${MONTH}_99999_qa-cap-seed.jsonl
```

- [ ] After proxy restart, the seeded cost triggers the daily cap
- [ ] Proxy returns HTTP 429 or Claude reports a `spend_cap_exceeded` error
- [ ] Error message includes current spend and limit amounts
- [ ] Error message suggests `forge proxy set <id> costs.caps.per_day=<amount>` to adjust

### 7.10 Spend Cap Enforcement (Warn Mode)

<!-- prereq: 4.2 -->

<!-- requires: api_key -->

<!-- human:guided -->

Switch to warn mode and verify requests succeed with a warning header instead of being blocked. Uses the same seeded
cost log approach for deterministic cap triggering.

```
# Use the same deterministic cap settings as 7.9, then switch to warn mode.
forge proxy set "$FORGE_QA_OPENAI_PROXY" costs.caps.per_day=0.01
forge proxy set "$FORGE_QA_OPENAI_PROXY" costs.on_cap_hit=warn

# Re-seed the cost log (cleanup from 7.9 removed it)
mkdir -p ~/.forge/telemetry/downstream
MONTH=$(date -u +%Y-%m)
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "{\"ts\":\"$TS\",\"proxy_id\":\"$FORGE_QA_OPENAI_PROXY\",\"model\":\"seed\",\"tier\":\"sonnet\",\"input_tokens\":0,\"output_tokens\":0,\"cached_tokens\":0,\"cost_micros\":50000,\"reporter\":\"litellm\",\"confidence\":\"gateway_calculated\",\"latency_ms\":0,\"failed\":false,\"request_id\":\"req-qa-cap-warn\"}" \
  > ~/.forge/telemetry/downstream/${MONTH}_99999_qa-cap-seed.jsonl

# Restart proxy so it bootstraps with the seeded cost (--force bypasses shared-port check)
forge proxy stop "$FORGE_QA_OPENAI_PROXY" --force 2>/dev/null || true
forge proxy start "$FORGE_QA_OPENAI_PROXY"

# Make a direct request and capture response headers.
BASE_URL=$(jq -r --arg id "$FORGE_QA_OPENAI_PROXY" '.proxies[$id].base_url' ~/.forge/proxies/index.json)
curl -sS -D /tmp/qa-spend-warn.headers -o /tmp/qa-spend-warn.body \
  -w 'HTTP=%{http_code}\n' \
  -H 'content-type: application/json' \
  -H 'x-api-key: test' \
  -H 'user-agent: claude-code/qa-spend-warn' \
  "$BASE_URL/v1/messages" \
  -d '{"model":"claude-3-5-haiku-20241022","max_tokens":16,"temperature":0,"messages":[{"role":"user","content":"Reply with exactly one word: ok"}]}'

# Verify the response was allowed and included the warn-mode header.
grep -i '^x-spend-warning:' /tmp/qa-spend-warn.headers
cat /tmp/qa-spend-warn.body | jq -r '._request_id // empty'
# If curl did not report HTTP=200, inspect the proxy error details:
# cat /tmp/qa-spend-warn.body | jq .
# forge logs --tail proxy

# Optional Claude smoke: run with debug output, say "hello", then exit (/exit).
# The deterministic header check above is the source of truth for this step.
forge claude start --proxy "$FORGE_QA_OPENAI_PROXY" -- --debug

# Clean up seeded log
rm -f ~/.forge/telemetry/downstream/${MONTH}_99999_qa-cap-seed.jsonl /tmp/qa-spend-warn.headers /tmp/qa-spend-warn.body
```

- [ ] Request succeeds (not blocked) in warn mode
- [ ] `curl` reports `HTTP=200`
- [ ] `grep -i '^x-spend-warning:' /tmp/qa-spend-warn.headers` prints the spend-cap warning header
- [ ] Optional Claude debug run also succeeds (no `spend_cap_exceeded` block)

### 7.11 Cleanup Fixture Cost Logs

<!-- auto -->

```bash
# Remove only QA fixture files -- do not touch real proxy cost logs
rm -f ~/.forge/costs/requests/qa-fixture_*.jsonl

# Remove cap-seed logs from 7.9/7.10 (in case cleanup within those steps failed)
rm -f ~/.forge/telemetry/downstream/*_qa-cap-seed.jsonl

# Verify cleanup: no QA-owned cost fixture files remain
ls ~/.forge/costs/requests/qa-fixture_*.jsonl 2>&1 || echo "QA_REQUEST_LOGS_CLEAN"
ls ~/.forge/telemetry/downstream/*_qa-cap-seed.jsonl 2>&1 || echo "QA_CAP_SEED_LOGS_CLEAN"

# Reset spend caps on test proxies
forge proxy set "$FORGE_QA_GEMINI_PROXY" costs.caps.per_day=none 2>/dev/null || true
forge proxy set "$FORGE_QA_GEMINI_PROXY" costs.caps.per_month=none 2>/dev/null || true
forge proxy set "$FORGE_QA_GEMINI_PROXY" costs.on_cap_hit=reject 2>/dev/null || true
forge proxy set "$FORGE_QA_OPENAI_PROXY" costs.caps.per_day=none 2>/dev/null || true
forge proxy set "$FORGE_QA_OPENAI_PROXY" costs.caps.per_month=none 2>/dev/null || true
forge proxy set "$FORGE_QA_OPENAI_PROXY" costs.on_cap_hit=reject 2>/dev/null || true

# Restart the QA OpenAI proxy so the running proxy drops seeded spend/cap state from 7.9/7.10
forge proxy stop "$FORGE_QA_OPENAI_PROXY" --force 2>/dev/null || true
forge proxy start "$FORGE_QA_OPENAI_PROXY"
```

- [ ] QA fixture request logs removed (no `qa-fixture_*.jsonl` in `requests/`)
- [ ] QA cap seed logs removed (no `*_qa-cap-seed.jsonl` in `telemetry/downstream/`)
- [ ] Spend caps reset on QA OpenAI and Gemini test proxies

### 7.12 Per-Session Activity (`forge telemetry activity`)

<!-- prereq: 0.3 -->

<!-- auto -->

`forge telemetry activity [session]` renders operation outcomes plus model calls. This fixture seeds transitional
usage-attribution events (`~/.forge/usage/events/`) for a throwaway session and asserts the model-call rollup --
including the workflow worker/verb split (one panel = 1 call + N workers, not N+1 calls) and the cost-honesty rendering:
the aggregate cost is reported-or-estimated/best-effort (flagged with `~` and a footnote), while
`forge telemetry costs show` is the authoritative spend view.

```bash
cd $FORGE_TEST_REPO

# A resolvable session for `forge telemetry activity` to target (no Claude launch).
forge session delete qa-usage --yes --force 2>/dev/null || true
forge session start qa-usage --no-launch

# Seed fixture usage events: 3 supervisor (1 error) + one panel verb aggregate + 3 panel
# worker leaves. The workers share command="panel"; the double-count fix must keep them
# out of `calls`. PID 99999 avoids collision with any real ledger shard.
mkdir -p ~/.forge/usage/events
cat > ~/.forge/usage/events/qa-usage-fixture_99999.jsonl <<'EOF'
{"schema_version":1,"run_id":"qa-r1","root_run_id":"qa-r1","runtime":"claude_code","command":"supervisor","status":"success","session":"qa-usage","attribution_granularity":"verb","input_tokens":200,"output_tokens":80,"cost_micro_usd":300,"ts":"2026-05-01T00:00:00Z"}
{"schema_version":1,"run_id":"qa-r2","root_run_id":"qa-r2","runtime":"claude_code","command":"supervisor","status":"success","session":"qa-usage","attribution_granularity":"verb","input_tokens":150,"output_tokens":60,"cost_micro_usd":250,"ts":"2026-05-01T00:01:00Z"}
{"schema_version":1,"run_id":"qa-r3","root_run_id":"qa-r3","runtime":"claude_code","command":"supervisor","status":"error","session":"qa-usage","attribution_granularity":"verb","ts":"2026-05-01T00:02:00Z"}
{"schema_version":1,"run_id":"qa-r4","root_run_id":"qa-r4","runtime":"claude_code","command":"panel","status":"success","session":"qa-usage","attribution_granularity":"verb","input_tokens":700,"output_tokens":230,"cost_micro_usd":1500,"ts":"2026-05-01T00:03:00Z"}
{"schema_version":1,"run_id":"qa-w1","root_run_id":"qa-r4","runtime":"claude_code","command":"panel","status":"success","session":"qa-usage","attribution_granularity":"worker","ts":"2026-05-01T00:03:01Z"}
{"schema_version":1,"run_id":"qa-w2","root_run_id":"qa-r4","runtime":"claude_code","command":"panel","status":"success","session":"qa-usage","attribution_granularity":"worker","ts":"2026-05-01T00:03:02Z"}
{"schema_version":1,"run_id":"qa-w3","root_run_id":"qa-r4","runtime":"claude_code","command":"panel","status":"success","session":"qa-usage","attribution_granularity":"worker","ts":"2026-05-01T00:03:03Z"}
EOF

# JSON contract + the double-count assertion
forge telemetry activity qa-usage --all --json | python3 -c "
import json, sys
d = json.load(sys.stdin)
cmds = {c['command']: c for c in d['downstream']['rows']}
sup, panel = cmds.get('supervisor', {}), cmds.get('panel', {})
print(f'total_attempts={sum(c.get(\"attempts\", 0) for c in cmds.values())}')
print(f'supervisor calls={sup.get(\"calls\")} errors={sup.get(\"errors\")}')
print(f'panel calls={panel.get(\"calls\")} workers={panel.get(\"workers\")}')
print('DOUBLE_COUNT_OK' if panel.get('calls') == 1 and panel.get('workers') == 3 else 'DOUBLE_COUNT_FAIL')
print(f'session={d[\"session\"]} tagging_partial={\"session_tagging_partial\" in d[\"notes\"]}')
print(f'cost_partial={d[\"downstream\"][\"cost_partial\"]} total_cost_micro_usd={d[\"downstream\"][\"total_cost_micro_usd\"]}')
"

echo "---"
# Human-readable render (Rich table -> stderr): the Workers column appears only with a fan-out.
forge telemetry activity qa-usage --all 2>&1

# Clean up
rm -f ~/.forge/usage/events/qa-usage-fixture_99999.jsonl
forge session delete qa-usage --yes --force 2>/dev/null || true
```

- [ ] `total_attempts` is 7 (3 supervisor + 1 panel verb + 3 panel workers)
- [ ] `supervisor calls=3 errors=1` (the error mirrors an OpenRouter content-filter failure)
- [ ] `panel calls=1 workers=3` and the script prints `DOUBLE_COUNT_OK` (verb + workers not double-counted)
- [ ] `session=qa-usage tagging_partial=True`
- [ ] `cost_partial=True total_cost_micro_usd=2050` (the 3 reported costs sum to 2050; the supervisor error + 3 workers
  report no cost, so the aggregate is flagged best-effort/partial -- missing costs are not priced to 0)
- [ ] Human render shows the `Model calls` pane with a `supervisor` row and a `panel` row, a `Workers` column with `3`
  on the panel row, and a `Total: 7 events` line
- [ ] Human render cost honesty: the `Total:` line carries a `~` best-effort marker, and the footnotes include
  `best-effort and partial` and `reported-or-estimated` (the always-on
  `'forge telemetry costs show' is the authoritative spend view` pointer)
- [ ] Fixture shard + `qa-usage` session removed at the end

### 7.13 Cost Provenance (reported vs `unavailable`)

<!-- auto -->

The north star: a missing cost shows as `unavailable`, never invented from a local price table.
`forge telemetry costs show` (the authoritative view) counts a request with no reported cost in `unavailable_requests`
and excludes it from the dollar total -- it is never summed as `0`. Uses an isolated `qa-prov` proxy_id so the shared
`qa-fixture` 3-request invariant (7.5/7.6) is untouched.

```bash
mkdir -p ~/.forge/costs/requests
cat > ~/.forge/costs/requests/qa-fixture_prov-99999.jsonl <<'EOF'
{"ts":"2026-05-01T00:00:00Z","proxy_id":"qa-prov","model":"test/gemini-2.5-flash","tier":"haiku","input_tokens":200,"output_tokens":80,"cached_tokens":0,"cost_micros":2500,"reporter":"litellm","confidence":"gateway_calculated","latency_ms":120.0,"failed":false,"request_id":"req-prov-001"}
{"ts":"2026-05-01T00:01:00Z","proxy_id":"qa-prov","model":"test/gemini-3.1-pro-preview","tier":"sonnet","input_tokens":500,"output_tokens":150,"cached_tokens":0,"cost_micros":null,"reporter":"provider","confidence":"unavailable","latency_ms":300.0,"failed":false,"request_id":"req-prov-002"}
EOF

forge telemetry costs show qa-prov --period all --json | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'total_requests={d[\"total_requests\"]}')
print(f'reported={d[\"reported_requests\"]} unavailable={d[\"unavailable_requests\"]}')
print(f'total_cost_micros={d[\"total_cost_micros\"]}')
"

# Self-clean (the qa-fixture_* name is also swept by 7.11 as a safety net).
rm -f ~/.forge/costs/requests/qa-fixture_prov-99999.jsonl
```

- [ ] `total_requests=2 reported=1 unavailable=1` (the null-cost `req-prov-002` is counted as unavailable, not dropped)
- [ ] `total_cost_micros=2500` -- the missing cost is NOT summed as 0 and NOT priced from a local table
  (reported-or-unavailable: the authoritative `forge telemetry costs show` view never invents a dollar figure)
- [ ] Provenance fixture removed at the end

### 7.14 Reset Telemetry (`forge telemetry costs reset`)

<!-- auto -->

<!-- destructive -->

`forge telemetry costs reset` wipes every recorded cost + usage telemetry plane to zero: legacy request cost logs
(`~/.forge/costs/requests/`), downstream/upstream telemetry (`~/.forge/telemetry/downstream/`,
`~/.forge/telemetry/upstream/`), durable spend-cap/audit-state snapshots, and the usage-attribution ledger
(`~/.forge/usage/events/`). It also clears the **derived** status-line cost cache
(`~/.forge/cache/statusline/fcost-*.json`) so `forge +$Y` recomputes from the now-empty ledger instead of replaying a
cached value within its TTL — but the unrelated transcript cache-hit entries (`{digest}.json`) survive, and the legacy
audit plane (`~/.forge/audit/`) is left untouched. `--dry-run` lists what would go without deleting; `--yes` skips the
confirm prompt. A running proxy keeps its cost totals AND cap counters in memory (a separate process the CLI cannot
reach), so the command prints a restart tip rather than claiming a live proxy's cumulative cost/caps are zeroed. This is
destructive: it clears all cost telemetry in the container, so it runs last in section 7.

```bash
# Seed one shard in each of the three reset planes, an audit sentinel that must survive,
# a derived fcost cache that must clear, and a cache-hit entry that must survive.
mkdir -p ~/.forge/costs/requests ~/.forge/usage/events ~/.forge/audit ~/.forge/cache/statusline
echo '{"ts":"2026-05-01T00:00:00Z","proxy_id":"qa-reset","model":"test/x","tier":"haiku","input_tokens":1,"output_tokens":1,"cached_tokens":0,"cost_micros":100,"reporter":"litellm","confidence":"gateway_calculated","latency_ms":1.0,"failed":false,"request_id":"qa-reset-1"}' > ~/.forge/costs/requests/qa-reset_99999.jsonl
echo '{"schema_version":1,"run_id":"qa-reset-r1","root_run_id":"qa-reset-r1","runtime":"claude_code","command":"qa","status":"success","attribution_granularity":"verb","cost_micro_usd":100,"ts":"2026-05-01T00:00:00Z"}' > ~/.forge/usage/events/qa-reset_99999.jsonl
echo '{"qa":"audit-sentinel"}' > ~/.forge/audit/qa-reset-sentinel.jsonl
echo '{"version":1,"computed_at":0,"cost_micro_usd":9999}' > ~/.forge/cache/statusline/fcost-qareset.json
echo '{"version":1,"cache_hit_rate":0.5}' > ~/.forge/cache/statusline/qaresetdigest.json

# Dry-run must LIST the planes + the cache and delete nothing.
forge telemetry costs reset --dry-run 2>&1
echo "---"

# Real reset (non-interactive).
forge telemetry costs reset --yes 2>&1
echo "---"

# Verify the planes + fcost cache are empty, while audit + cache-hit survive.
echo "requests=$(ls ~/.forge/costs/requests/*.jsonl 2>/dev/null | wc -l | tr -d ' ')"
echo "events=$(ls ~/.forge/usage/events/*.jsonl 2>/dev/null | wc -l | tr -d ' ')"
echo "fcost=$(ls ~/.forge/cache/statusline/fcost-*.json 2>/dev/null | wc -l | tr -d ' ')"
echo "cache_hit=$(ls ~/.forge/cache/statusline/qaresetdigest.json 2>/dev/null | wc -l | tr -d ' ')"
echo "audit_sentinel=$(ls ~/.forge/audit/qa-reset-sentinel.jsonl 2>/dev/null | wc -l | tr -d ' ')"
echo "---"

# Second reset with nothing left is a clean no-op.
forge telemetry costs reset --yes 2>&1

# Clean up the audit sentinel + the surviving cache-hit entry.
rm -f ~/.forge/audit/qa-reset-sentinel.jsonl ~/.forge/cache/statusline/qaresetdigest.json
```

- [ ] `--dry-run` prints `The following will be removed:` with a `request cost logs`, `usage ledger`, and
  `status-line cost cache` line, then `(dry-run) Nothing deleted.` -- and the planes still hold their shards
- [ ] `--yes` prints `Reset complete: removed N telemetry file(s).` (N >= 3) followed by the `Tip:` restart guidance
  naming `forge proxy stop <id>` / `forge proxy start <id>`
- [ ] After the real reset: `requests=0 events=0 fcost=0` (planes + derived cost cache cleared) while `cache_hit=1`
  (transcript cache-hit untouched) and `audit_sentinel=1` (audit plane untouched)
- [ ] The second `reset --yes` with nothing left prints `No cost or usage telemetry to reset.` (clean no-op, no error)
- [ ] Audit sentinel + cache-hit entry removed at the end

---
