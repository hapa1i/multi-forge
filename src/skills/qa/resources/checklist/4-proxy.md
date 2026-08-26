<!-- prereq: 0.3 -->

## 4. Proxy Management

Default QA runs this section through the OpenRouter provider profile. It requires the selected provider credentials
(`OPENROUTER_API_KEY` by default), not remote LiteLLM infrastructure unless QA was started with
`--provider-profile remote-litellm`. LiteLLM template list/show checks below are metadata-only.

### 4.1 List Proxies and Templates

<!-- auto -->

```bash
# List existing proxies (none yet)
forge proxy list

# Expected: "No proxies found." + tip to run 'forge proxy template list'
# Templates are listed via the template subcommand, not inline in proxy list.

# List available templates
forge proxy template list
```

- [ ] `forge proxy list` shows "No proxies found." when none exist
- [ ] `forge proxy list` shows tip to run `forge proxy template list`
- [ ] `forge proxy template list` shows available templates (19 user-facing: anthropic-passthrough, litellm-anthropic,
  litellm-anthropic-local, litellm-gemini, litellm-gemini-flash-local, litellm-gemini-local, litellm-openai,
  litellm-openai-codex-local, litellm-openai-local, openrouter-anthropic, openrouter-deepseek, openrouter-gemini,
  openrouter-gemini-flash, openrouter-glm, openrouter-kimi, openrouter-minimax, openrouter-openai,
  openrouter-openai-codex, openrouter-qwen)
- [ ] Internal test-only templates (e.g., litellm-gemini-test) are hidden from the default list

### 4.2 Create a Proxy

<!-- auto -->

```bash
# Clean up from previous runs
forge proxy delete "$FORGE_QA_GEMINI_PROXY" --yes 2>/dev/null || true
forge proxy delete "$FORGE_QA_OPENAI_PROXY" --yes 2>/dev/null || true
forge proxy delete "$FORGE_QA_ANTHROPIC_PROXY" --yes 2>/dev/null || true
forge proxy delete openrouter-gemini --yes 2>/dev/null || true
forge proxy delete openrouter-openai --yes 2>/dev/null || true
forge proxy delete openrouter-deepseek --yes 2>/dev/null || true
forge proxy delete openrouter-minimax --yes 2>/dev/null || true
forge proxy delete test-proxy-nostart --yes 2>/dev/null || true

# Create named role proxies used by downstream session/review steps.
forge proxy create "$FORGE_QA_GEMINI_TEMPLATE" --name "$FORGE_QA_GEMINI_PROXY"

# Create a named review proxy with per-tier overrides
forge proxy create "$FORGE_QA_OPENAI_TEMPLATE" --name "$FORGE_QA_OPENAI_PROXY" --opus-reasoning high

# Create workflow-default aliases so section 14 exercises production default proxy IDs.
# In remote-litellm profile these names intentionally point at remote LiteLLM-backed proxies.
forge proxy create "$FORGE_QA_GEMINI_TEMPLATE" --no-start --name openrouter-gemini
forge proxy create "$FORGE_QA_OPENAI_TEMPLATE" --no-start --name openrouter-openai

# Workflow proxies for cheap models (openrouter profile only).
# Started directly with canonical names so models.py proxy lookup matches the running port.
if [ -n "${FORGE_QA_DEEPSEEK_TEMPLATE:-}" ]; then
  forge proxy create "$FORGE_QA_DEEPSEEK_TEMPLATE" --name openrouter-deepseek
fi
if [ -n "${FORGE_QA_MINIMAX_TEMPLATE:-}" ]; then
  forge proxy create "$FORGE_QA_MINIMAX_TEMPLATE" --name openrouter-minimax
fi

# Create config only (don't start the server)
forge proxy create "$FORGE_QA_OPENAI_TEMPLATE" --no-start --name test-proxy-nostart

# List proxies again
forge proxy list
```

- [ ] Named role proxies from `$FORGE_QA_*_TEMPLATE` created successfully (or note if skipped)
- [ ] Named role proxies, workflow aliases, and `test-proxy-nostart` appear in the list with expected base_url/port
  information
- [ ] Per-tier overrides applied to `$FORGE_QA_OPENAI_PROXY`
- [ ] Workflow proxies (`openrouter-deepseek`, `openrouter-minimax`) started for openrouter profile (or skipped for
  remote-litellm)

### 4.3 Show Proxy Details

<!-- prereq: 4.2 -->

<!-- auto -->

```bash
# Show details of a specific proxy (created in 4.2)
forge proxy show test-proxy-nostart
```

- [ ] Shows template, base_url, tier mappings
- [ ] Shows proxy configuration YAML (port, tiers, provider settings)

### 4.4 Proxy Edit and Validate

<!-- prereq: 4.2 -->

<!-- auto -->

```bash
forge proxy delete edit-test-proxy --yes 2>/dev/null || true
forge proxy create "$FORGE_QA_OPENAI_TEMPLATE" --no-start --name edit-test-proxy
forge proxy show edit-test-proxy
EDITOR=true forge proxy edit edit-test-proxy
forge proxy validate edit-test-proxy
forge proxy delete edit-test-proxy --yes
```

- [ ] `show` displays full proxy configuration
- [ ] `EDITOR=true` exercises the edit path non-interactively and leaves valid YAML
- [ ] `validate` reports config health
- [ ] `delete` removes proxy and cleans up registry

### 4.5 Stale Proxy Pruning

<!-- auto -->

Stale proxies (dead PIDs) are pruned automatically by `list`/`create`/`start`; `forge clean` removes them globally.
There is no dedicated `forge proxy clean` command.

```bash
forge proxy list   # auto-prunes dead-PID entries as a side effect
```

- [ ] `proxy list` succeeds and shows no dead-PID entries

### 4.6 Launch Session with Host Proxy

<!-- prereq: 2.4, 4.2 -->

<!-- requires: api_key -->

<!-- human:guided -->

<!-- evidence: automated-suite -->

In the **container shell**, create a session bound to a proxy, then launch Claude through the proxy.

```
# Clean up from previous runs
forge session delete proxy-session --yes --yes 2>/dev/null || true

# Create a session bound to the proxy created in 4.2 (accepts proxy_id or template name)
forge session start proxy-session --proxy "$FORGE_QA_OPENAI_PROXY" --no-launch

# Verify session recorded proxy identity
cat .forge/sessions/proxy-session/forge.session.json | jq '.intent.proxy'
# Should show template and base_url fields
```

- [ ] `--proxy` binds session to the named proxy
- [ ] Session manifest `.intent.proxy` shows template and base_url

Now launch Claude through the named proxy. This opens an interactive Claude session — exit with Ctrl-C or `/exit` when
done verifying.

```
# Launch Claude through the running proxy created in 4.2
forge claude start --proxy "$FORGE_QA_OPENAI_PROXY" -- --debug
# Claude should start with ANTHROPIC_BASE_URL pointing to the proxy
# Verify by checking the status line or running: echo $ANTHROPIC_BASE_URL inside Claude
# Exit Claude when done (Ctrl-C or /exit)
```

- [ ] `forge claude start --proxy` starts Claude routed through the named proxy
- [ ] Status line shows proxy info (template, tier mappings) when running with proxy

### 4.7 Live % Commands in Proxy Session

<!-- prereq: 2.4, 4.2 -->

<!-- requires: api_key -->

<!-- human:guided -->

<!-- evidence: automated-suite -->

Now launch Claude (or reuse the session from 4.6):

```
forge claude start --proxy "$FORGE_QA_OPENAI_PROXY" -- --debug
```

In the **live Claude session**, type these prompts:

```
%help
%session list
%proxy list
%proxy show qa-openai
```

- [ ] `%help` returns help text listing available `%` commands
- [ ] `%session list` shows sessions (including proxy-session)
- [ ] `%proxy list` shows proxies from inside the session
- [ ] `%proxy show` displays proxy details (template, tier mappings)
- [ ] Commands are intercepted by `UserPromptSubmit` hook (not passed to Claude as prompts)

Exit the Claude session when done.

### 4.8 Proxy Delete UX (Confirmation + Smart-Pointer Semantics)

<!-- prereq: 4.2 -->

<!-- human:guided -->

Test that `forge proxy delete` requires confirmation, shows the related shared-port items, and uses smart-pointer
semantics (only kills the server when deleting the last registry entry for that port).

In the **container shell**:

```
# Clean up from previous runs
forge proxy delete delete-test-proxy --yes 2>/dev/null || true
forge session delete proxy-session --yes --force 2>/dev/null || true
forge session start proxy-session --proxy "$FORGE_QA_OPENAI_PROXY" --no-launch

# Create an alias on the same shared port as the QA OpenAI proxy
forge proxy create "$FORGE_QA_OPENAI_TEMPLATE" --no-start --name delete-test-proxy

# Try to delete the alias -- should prompt for confirmation and list the related proxy entry
forge proxy delete delete-test-proxy
# Choose N to cancel
# Expected:
# - confirmation prompt appears
# - related proxies on the same port are listed (including qa-openai)
# - no false warning about proxy-session/proxy-session-url just because they share port 8085

# Verify alias still exists after cancelling
forge proxy list
# Expected: delete-test-proxy still listed

# Now confirm deletion of the alias
forge proxy delete delete-test-proxy
# Choose y to confirm
# Expected:
# - "Deleted proxy 'delete-test-proxy'"
# - shared server references are kept alive via qa-openai

# Verify alias gone but qa-openai still present
forge proxy list

# Finally test deleting the primary QA proxy while shared-port aliases remain
forge proxy delete "$FORGE_QA_OPENAI_PROXY"
# Choose N to cancel
# Expected:
# - warning lists sessions that reference qa-openai (for example proxy-session / proxy-session-url)
# - prompt makes clear other proxies share this port
```

- [ ] `forge proxy delete` prompts for confirmation (not auto-deleted)
- [ ] Deleting a non-terminal alias lists the related proxy entries sharing that port
- [ ] Choosing N cancels the delete; alias still in `forge proxy list`
- [ ] Choosing y deletes the alias while keeping the shared server alive
- [ ] Deleting the primary QA proxy lists related sessions and same-port aliases
- [ ] No false warnings about sessions when deleting a non-terminal alias that merely shares the same port

### 4.9 Template Management

<!-- auto -->

```bash
# List available templates
forge proxy template list

# Show a template
forge proxy template show litellm-openai-local

# Raw YAML output (no syntax highlighting)
forge proxy template show litellm-openai-local --raw
```

- [ ] `forge proxy template list` shows all templates with source labels (built-in / customized)
- [ ] `forge proxy template show` displays template YAML
- [ ] `--raw` outputs plain YAML

### 4.10 Show Raw YAML for a Proxy Instance

<!-- prereq: 4.2 -->

<!-- auto -->

```bash
# Show raw YAML for an existing proxy instance (created earlier)
forge proxy show test-proxy-nostart --raw
```

- [ ] Proxy instance YAML printed (no syntax highlighting)
- [ ] YAML includes the expected template/provider fields

### 4.11 Set and Validate Proxy Config (No Editor)

<!-- prereq: 4.2 -->

<!-- auto -->

```bash
# Mutate a single value via CLI (no interactive editor)
forge proxy set test-proxy-nostart default_tier=opus

# Validate after mutation
forge proxy validate test-proxy-nostart
```

- [ ] `forge proxy set` succeeds
- [ ] `forge proxy validate` reports config is valid

### 4.12 Stop a Non-Running Proxy (Shared-Port Semantics)

<!-- prereq: 4.2 -->

<!-- auto -->

```bash
# test-proxy-nostart shares a port with the running QA OpenAI proxy.
# Smart-pointer semantics prevent stopping the shared server without --force.
forge proxy stop test-proxy-nostart 2>&1 || true

# Verify: error about shared port, not a silent no-op
forge proxy stop test-proxy-nostart 2>&1; echo "EXIT=$?"
```

- [ ] Command refuses to stop: reports other proxies share the port
- [ ] Exit code is non-zero (shared-port conflict)

### 4.13 Proxy Metrics (Running Proxy)

<!-- prereq: 4.2 -->

<!-- auto -->

```bash
# Metrics for a running proxy (QA Gemini proxy created in 4.2)
forge proxy metrics "$FORGE_QA_GEMINI_PROXY"

# JSON output
forge proxy metrics "$FORGE_QA_GEMINI_PROXY" --json

# All proxies (the default aggregate when more than one is registered)
forge proxy metrics

# All proxies JSON (must be a single valid JSON object)
forge proxy metrics --json
```

- [ ] `forge proxy metrics` displays request counts, token totals, per-tier breakdown
- [ ] Per-tier breakdown includes avg latency
- [ ] `--json` outputs valid parseable JSON
- [ ] bare `metrics --json` (with >1 proxy) outputs a single valid JSON object (not one per proxy)
- [ ] Unreachable proxies show `null` in `metrics --json` output

### 4.14 Proxy Metrics (Not Found / Shared-Port)

<!-- auto -->

```bash
# Metrics for a non-existent proxy (not in registry)
forge proxy metrics nonexistent-proxy 2>&1; echo "EXIT=$?"

# Metrics for test-proxy-nostart: shares a port with qa-openai,
# so smart-pointer semantics mean it reports metrics from the shared server.
forge proxy metrics test-proxy-nostart
```

- [ ] Non-existent proxy shows error and exits non-zero
- [ ] Shared-port proxy (test-proxy-nostart) returns metrics from the shared server (exit 0)

### 4.15 Backend List (Proxy Dependency)

<!-- auto -->

```bash
# List built-in backend sources and local runtime instances (LiteLLM, etc.)
forge model backend list
```

- [ ] Shows built-in local and remote source rows such as `openrouter` and `litellm-remote`
- [ ] Shows matching local runtime instances when they are running

### 4.16 Backend Create (LiteLLM Config)

<!-- auto -->

```bash
# Create backend config (shared by all instances)
forge model backend create litellm

# Show config + status (even if not running)
forge model backend show litellm-4000 --raw
```

- [ ] Backend config created (or reports it already exists)
- [ ] `forge model backend show` displays config YAML

### 4.17 OpenRouter Templates

<!-- auto -->

<!-- evidence: automated-suite -->

```bash
# List all templates -- should now include OpenRouter alongside LiteLLM
forge proxy template list

# Show each OpenRouter template
forge proxy template show openrouter-anthropic
forge proxy template show openrouter-openai
forge proxy template show openrouter-openai-codex
forge proxy template show openrouter-deepseek
forge proxy template show openrouter-gemini
forge proxy template show openrouter-gemini-flash
forge proxy template show openrouter-glm
forge proxy template show openrouter-kimi
forge proxy template show openrouter-minimax
forge proxy template show openrouter-qwen
```

- [ ] `forge proxy template list` shows 19 user-facing templates total (8 litellm + 10 openrouter + 1
  anthropic-passthrough)
- [ ] `openrouter-anthropic` maps tiers to Claude models (haiku=claude-haiku-4.5, sonnet=claude-sonnet-5,
  opus=claude-opus-5)
- [ ] `openrouter-deepseek` maps tiers to DeepSeek models (haiku=deepseek-v4-flash, sonnet/opus=deepseek-v4-pro)
- [ ] `openrouter-glm` maps tiers to GLM models (haiku=glm-4.7-flash, sonnet/opus=glm-5.3)
- [ ] `openrouter-kimi` maps tiers to Gemma/Kimi models (haiku=gemma-4-31b-it, sonnet/opus=kimi-k3)
- [ ] `openrouter-kimi` exposes `kimi-k2.7-code` as a sonnet/opus model alternative
- [ ] `openrouter-minimax` maps tiers to Gemma/MiniMax models (haiku=gemma-4-31b-it, sonnet/opus=minimax-m3)
- [ ] `openrouter-qwen` maps tiers to Qwen models (haiku/sonnet=qwen3.8-27b, opus=qwen3.8-max)
- [ ] Every OpenRouter template defaults `allow_non_zdr` to false; no LiteLLM template contains ZDR fields
- [ ] The dated ZDR audit fallbacks cover Fable 5 and all six bundled non-ZDR Qwen slugs; Qwen3.8 Max maps to
  `qwen/qwen3.8-2.4t-a95b`
- [ ] `openrouter-openai` maps tiers to GPT models (haiku=gpt-5.4-mini, sonnet=gpt-5.6-sol, opus=gpt-5.6-sol)
- [ ] `openrouter-openai-codex` maps tiers to Codex models (haiku=gpt-5.1-codex-mini, sonnet=gpt-5.3-codex,
  opus=gpt-5.6-sol)
- [ ] `openrouter-gemini` maps tiers to Gemini models (haiku=gemini-3.7-flash, sonnet=gemini-3.1-pro-preview,
  opus=gemini-3.1-pro-preview)
- [ ] `openrouter-gemini-flash` maps all tiers to gemini-3.7-flash with tier_overrides for reasoning_effort
  (low/medium/high)
- [ ] Each OpenRouter template has a distinct default_port (8095-8104)

### 4.18 OpenRouter Proxy Create

<!-- auto -->

```bash
# Clean up from previous runs
forge proxy delete openrouter-test --yes 2>/dev/null || true

# Create an OpenRouter proxy without starting it (no OPENROUTER_API_KEY needed for config-only)
forge proxy create openrouter-anthropic --name openrouter-test --no-start

# Show proxy details
forge proxy show openrouter-test

# Show raw YAML
forge proxy show openrouter-test --raw
```

- [ ] OpenRouter proxy created from template (exit 0)
- [ ] `forge proxy show` or `forge proxy validate` displays `Provider: openrouter`
- [ ] Raw YAML shows `provider: openrouter` and tier mappings with `anthropic/` prefixed model IDs
- [ ] Proxy uses port 8095 (openrouter-anthropic default)

### 4.18.1 OpenRouter ZDR Boundary

<!-- prereq: 4.18 -->

<!-- auto -->

```bash
# Direct OpenRouter advertises and defaults to required ZDR.
forge proxy show openrouter-test --raw | rg 'allow_non_zdr: false'

# LiteLLM does not expose the OpenRouter-only controls.
! forge proxy template show litellm-openai --raw | rg 'allow_non_zdr|zdr_fallbacks'

# Create the Qwen route and inspect configured versus effective runtime truth.
forge proxy delete openrouter-zdr-test --yes 2>/dev/null || true
forge proxy create openrouter-qwen --name openrouter-zdr-test
curl -fsS "$(forge proxy list --json | jq -r '.[] | select(.proxy_id == "openrouter-zdr-test") | .base_url')/" \
  | jq '.runtime | {configured_tier_mappings, tier_mappings, data_policy}'
forge proxy stop openrouter-zdr-test
forge proxy delete openrouter-zdr-test --yes
```

- [ ] Direct OpenRouter raw config shows `allow_non_zdr: false`
- [ ] LiteLLM template output contains neither ZDR field
- [ ] Qwen configured Opus is `qwen/qwen3.8-max`, effective Opus is `qwen/qwen3.8-2.4t-a95b`, and
  `runtime.data_policy.zdr` is `required`
- [ ] Forge-owned direct OpenRouter plan checks and transfer/rewind curation remain required-ZDR regardless of this
  proxy's `allow_non_zdr` setting
- [ ] The disposable Qwen proxy stops and deletes cleanly

### 4.19 Model Alternatives

<!-- prereq: 4.18 -->

<!-- auto -->

```bash
# Check model_alternatives in the openrouter-anthropic template
forge proxy template show openrouter-anthropic --raw | grep -A3 model_alternatives

# Check instance inherits alternatives
forge proxy show openrouter-test --raw | grep -A3 model_alternatives

echo "---"

# Clean up
forge proxy delete openrouter-test --yes 2>/dev/null || true
```

- [ ] Template YAML includes `model_alternatives` section under opus tier
- [ ] Opus alternative maps `claude-opus-4-8` to `anthropic/claude-opus-4.8`
- [ ] Proxy instance inherits `model_alternatives` from template
- [ ] `openrouter-test` proxy cleaned up

### 4.20 Proxy Audit (Read-Only Metadata)

<!-- prereq: 4.2 -->

<!-- auto -->

<!-- requires: proxy -->

```bash
# Recent audit metadata (timestamps, mode, system-prompt/tool hashes).
# Metadata only -- redacted logs, so no secrets or message text are printed.
forge proxy audit show

# Period + limit filters and machine-readable output
forge proxy audit show --period all --limit 5 --json

# Wire-change timeline (drift + override mutations; hashes/lengths only)
forge proxy audit diff
```

- [ ] `forge proxy audit show` lists metadata records (time, proxy, mode, system/tool hashes) or a clean
  `No audit data for <period>.` message
- [ ] `--json` emits valid JSON (`[]` when empty, parseable array otherwise)
- [ ] `forge proxy audit diff` shows wire changes or `No wire changes for <period>.`
- [ ] No secrets, API keys, or plaintext request/response bodies appear in any output

### 4.21 Intercept / Audit Config and Passthrough Template

<!-- auto -->

```bash
# Clean up from previous runs
forge proxy delete intercept-test --yes 2>/dev/null || true
forge proxy delete passthrough-test --yes 2>/dev/null || true

# A translated proxy (openai_translated wire shape), config-only.
forge proxy create openrouter-openai --name intercept-test --no-start

# inspect mode is allowed on any wire shape (observe: hash + drift, no mutation)
forge proxy set intercept-test intercept.mode=inspect

# override mode mutates the RAW Anthropic body -> rejected unless wire_shape=anthropic_passthrough
forge proxy set intercept-test intercept.mode=override 2>&1; echo "OVERRIDE_REJECT_EXIT=$?"

# Full-body audit is the high-risk opt-in: must print a privacy warning naming ~/.forge/telemetry/downstream/
forge proxy set intercept-test audit.audit_full_body=true 2>&1

# Create a proxy from the anthropic-passthrough template (the only signature-safe wire shape).
# Config-only: no ANTHROPIC_API_KEY needed until start.
forge proxy create anthropic-passthrough --name passthrough-test --no-start
forge proxy show passthrough-test --raw | grep -E "wire_shape|default_port|port:"

# override IS allowed here because the passthrough wire shape preserves the raw body.
forge proxy set passthrough-test intercept.mode=override 2>&1; echo "OVERRIDE_OK_EXIT=$?"

# Clean up
forge proxy delete intercept-test --yes 2>/dev/null || true
forge proxy delete passthrough-test --yes 2>/dev/null || true
```

- [ ] `forge proxy set intercept-test intercept.mode=inspect` succeeds on the translated proxy
- [ ] `intercept.mode=override` is rejected (exit non-zero) naming `requires wire_shape='anthropic_passthrough'`
- [ ] `audit.audit_full_body=true` prints a privacy warning naming `~/.forge/telemetry/downstream/`
- [ ] `anthropic-passthrough` proxy created config-only with `wire_shape: anthropic_passthrough` (default port 8096)
- [ ] `intercept.mode=override` succeeds on the `anthropic-passthrough` proxy

### 4.22 Degraded Downstream Retention Status

<!-- auto -->

<!-- requires: proxy,api_key -->

Use a disposable proxy with conflicting legacy retention inputs. The proxy must stay reachable while runtime truth
reports that destructive maintenance was disabled.

```bash
forge config reset telemetry -y 2>/dev/null || true
forge proxy delete retention-degraded-qa --yes 2>/dev/null || true
forge proxy create "$FORGE_QA_OPENAI_TEMPLATE" --name retention-degraded-qa --port 18199 --no-start
forge proxy set retention-degraded-qa audit.retention_days=90
forge proxy set retention-degraded-qa provider_trace.retention_days=14
forge proxy start retention-degraded-qa

curl --fail --silent http://127.0.0.1:18199/ >/tmp/forge-retention-degraded.json
jq -e '
  .status == "degraded"
  and .downstream_retention.degraded == true
  and ([.downstream_retention.conflicts[].values[].proxy_ids[]]
       | index("retention-degraded-qa") != null)
' /tmp/forge-retention-degraded.json

forge proxy stop retention-degraded-qa
forge proxy delete retention-degraded-qa --yes
```

- [ ] A proxy with conflicting legacy retention inputs starts and `GET /` remains reachable
- [ ] Runtime truth reports top-level `status: degraded` and names `retention-degraded-qa` in the nested conflicts
- [ ] The disposable degraded proxy stops and deletes cleanly

### 4.23 Stop Failure Retains Proxy Ownership

<!-- prereq: 4.2 -->

<!-- auto -->

Use a foreign HTTP listener to force the adopted-process identity guard. The failed required stop must leave every
recovery surface intact.

```bash
forge proxy delete ownership-failure-qa --yes --no-kill 2>/dev/null || true
python3 -m http.server 18201 >/tmp/forge-ownership-failure.log 2>&1 &
FOREIGN_PID=$!
for i in $(seq 1 30); do curl --fail --silent http://127.0.0.1:18201/ >/dev/null && break; sleep 0.1; done
curl --fail --silent http://127.0.0.1:18201/ >/dev/null
forge proxy create "$FORGE_QA_OPENAI_TEMPLATE" --name ownership-failure-qa --port 18201 --no-start

set +e
forge proxy delete ownership-failure-qa --yes --kill-adopted \
  >/tmp/forge-ownership-delete.stdout 2>/tmp/forge-ownership-delete.stderr
DELETE_EXIT=$?
set -e

test "$DELETE_EXIT" -ne 0
grep "refusing to stop" /tmp/forge-ownership-delete.stderr
! grep "Deleted" /tmp/forge-ownership-delete.stdout
kill -0 "$FOREIGN_PID"
forge proxy show ownership-failure-qa --raw

kill "$FOREIGN_PID"
forge proxy delete ownership-failure-qa --yes --no-kill
```

- [ ] The identity-refused delete exits non-zero
- [ ] The diagnostic is on stderr and stdout does not claim `Deleted`
- [ ] The foreign listener remains alive after the refused stop
- [ ] The retained proxy remains readable and can be deleted after the listener stops

### 4.24 Create Smoke Failure Is One JSON Result

<!-- prereq: 4.2 -->

<!-- auto -->

Start a real proxy against a deliberately unreachable upstream. Creation must remain durable while verification fails as
one scriptable result.

```bash
forge proxy delete smoke-json-qa --yes --no-kill 2>/dev/null || true

set +e
forge proxy create "$FORGE_QA_OPENAI_TEMPLATE" \
  --name smoke-json-qa \
  --port 18203 \
  --base-url http://127.0.0.1:9/v1 \
  --json \
  --smoke-test \
  >/tmp/forge-smoke-json.stdout 2>/tmp/forge-smoke-json.stderr
SMOKE_EXIT=$?
set -e

test "$SMOKE_EXIT" -ne 0
jq -s -e '
  length == 1
  and .[0].proxy_id == "smoke-json-qa"
  and .[0].status == "healthy"
  and .[0].smoke_test.passed == false
  and (.[0].smoke_test.detail | length > 0)
' /tmp/forge-smoke-json.stdout
forge proxy show smoke-json-qa --raw >/dev/null
forge proxy delete smoke-json-qa --yes
```

- [ ] Failed create-time verification exits non-zero
- [ ] Stdout contains exactly one JSON object with creation facts and `smoke_test.passed=false`
- [ ] The failed probe leaves the created proxy registered and readable
- [ ] The preserved proxy can be deleted cleanly after inspection

### 4.25 Translated User-Agent Relay

<!-- prereq: 4.2 -->

<!-- auto -->

<!-- requires: api_key -->

<!-- paid-operations: 1 -->

Send a small Anthropic-shaped request with an explicit Claude Code User-Agent through the selected translated proxy. The
exact sanitized upstream header is pinned by integration tests; this operator smoke catches gateways that reject the
OpenAI SDK default identity.

```bash
UA_PROXY_URL=$(forge proxy show "$FORGE_QA_OPENAI_PROXY" --json | jq -r '.entry.base_url')
curl --fail --silent --show-error \
  -H 'x-api-key: test' \
  -H 'user-agent: claude-code/forge-qa' \
  -H 'content-type: application/json' \
  --data '{"model":"claude-3-5-haiku-20241022","max_tokens":16,"messages":[{"role":"user","content":"Reply with OK."}]}' \
  "$UA_PROXY_URL/v1/messages" \
  | jq -e '.type == "message" and (.content | type == "array")'
```

- [ ] A translated request with an explicit Claude Code User-Agent completes through the selected provider profile

### 4.26 Anthropic Passthrough Response Metadata

<!-- prereq: 2.4 -->

<!-- auto -->

<!-- requires: anthropic_api -->

<!-- evidence: extended-exploratory -->

<!-- paid-operations: 1 -->

When a native Anthropic credential is available, send one small request through the signature-safe passthrough and
inspect the downstream headers. Retry/error parity and the denylist are pinned by hermetic integration tests; this live
smoke confirms Anthropic's current rate-limit metadata crosses the operator boundary.

```bash
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "SKIP: ANTHROPIC_API_KEY is not configured"
else
  forge proxy delete passthrough-header-qa --yes 2>/dev/null || true
  PASSTHROUGH_HEADERS=$(mktemp)
  PASSTHROUGH_BODY=$(mktemp)
  cleanup_passthrough_header_qa() {
    rm -f "$PASSTHROUGH_HEADERS" "$PASSTHROUGH_BODY"
    forge proxy delete passthrough-header-qa --yes >/dev/null 2>&1 || true
  }
  trap cleanup_passthrough_header_qa EXIT
  forge proxy create anthropic-passthrough --name passthrough-header-qa
  PASSTHROUGH_URL=$(forge proxy show passthrough-header-qa --json | jq -r '.entry.base_url')
  curl --fail --silent --show-error \
    --dump-header "$PASSTHROUGH_HEADERS" \
    --output "$PASSTHROUGH_BODY" \
    -H 'x-api-key: test' \
    -H 'content-type: application/json' \
    --data '{"model":"claude-haiku-4-5","max_tokens":16,"messages":[{"role":"user","content":"Reply with OK."}]}' \
    "$PASSTHROUGH_URL/v1/messages"
  rg -i '^anthropic-ratelimit-[^:]+:' "$PASSTHROUGH_HEADERS"
  jq -e '.type == "message" and (.content | type == "array")' "$PASSTHROUGH_BODY"
  cleanup_passthrough_header_qa
  trap - EXIT
fi
```

- [ ] Safe Anthropic rate-limit metadata reaches the downstream response

### 4.27 Backend Lifecycle and Authentication

<!-- prereq: 4.16 -->

<!-- auto -->

```bash
case "$FORGE_QA_PROVIDER_PROFILE" in
  openrouter) QA_BACKEND=openrouter ;;
  remote-litellm) QA_BACKEND=litellm-remote ;;
esac

forge model backend list --json | jq -e --arg backend "$QA_BACKEND" 'any(.[]; .backend_instance_id == $backend)'
forge model backend show "$QA_BACKEND" --json | jq -e '.backend_instance_id != null'
forge model backend test-auth "$QA_BACKEND" --json | jq -e 'type == "object"'

# Exercise the local managed-process object separately from source ids.
forge model backend stop litellm-4199 --yes 2>/dev/null || true
forge model backend start litellm --port 4199
forge model backend show litellm-4199 --json \
  | jq -e '.found == true and .managed_process.process_id == "litellm-4199"'
forge model backend stop litellm-4199 --yes

# Delete targets the adapter config, then restore it for later cleanup.
forge model backend delete litellm --yes
test ! -d "$FORGE_HOME/backends/litellm"
forge model backend create litellm
```

- [ ] Backend list/show expose the selected configured source from the installed wheel
- [ ] `test-auth` returns structured reachability/auth evidence without exposing credentials
- [ ] `start` registers `litellm-4199`, and `stop` targets that runtime process id
- [ ] `delete litellm` removes the adapter config and `create` restores it

### 4.28 Provider Trace and Reconciliation

<!-- prereq: 4.25 -->

<!-- requires: openrouter -->

<!-- auto -->

```bash
forge telemetry trace list --period all --json | tee /tmp/qa-provider-traces.json
TRACE_ID=$(jq -r \
  'map(select(.request_id != null and .backend_id == "openrouter")) | last | .request_id // empty' \
  /tmp/qa-provider-traces.json)
test -n "$TRACE_ID"

forge telemetry trace show "$TRACE_ID" --json \
  | jq -e --arg request_id "$TRACE_ID" '.request_id == $request_id'
forge telemetry trace explain "$TRACE_ID" --json \
  | jq -e --arg request_id "$TRACE_ID" '.request_id == $request_id and .remote_lookup_performed == false'

TRACE_BACKEND=$(forge telemetry trace show "$TRACE_ID" --json | jq -r '.backend_id')
test "$TRACE_BACKEND" = openrouter
forge model backend reconcile "$TRACE_BACKEND" --request-id "$TRACE_ID" --json \
  | jq -e '.entries | type == "array"'
rm -f /tmp/qa-provider-traces.json
```

- [ ] Trace list returns a bare array containing a real request from this QA run
- [ ] Trace show returns the matching metadata-only record
- [ ] Trace explain is explicitly local-only (`remote_lookup_performed=false`)
- [ ] Backend reconcile joins the request through exactly one `--request-id` selector and returns structured entries

---
