# Headless cost/usage reporter spike (metric-evidence Phase 5a)

**Hard gate for Phase 5.** Question: does `claude -p --output-format json` expose per-run cost
(`total_cost_usd`) and token `usage` that Forge can record — across the auth modes and flag combos Forge
actually builds? Card rule (north star): present → record with provenance `reported`; absent →
`unavailable`. **Never** estimate from a price table.

Run once per auth mode (the harness detects the mode from the env and prints a verdict per flag combo):

```bash
# direct API key
ANTHROPIC_API_KEY=sk-... ./reproduce.sh
# OAuth / subscription (no key in env; OAuth creds in ~/.claude)
./reproduce.sh
# proxied
ANTHROPIC_BASE_URL=http://localhost:8080 ./reproduce.sh
```

## Observed envelope shape (the load-bearing finding)

On **Claude Code 2.1.165**, `claude -p --output-format json` emits a **JSON array** of events, not the
single `ResultMessage` object the docs describe:

```
[ {"type":"system","subtype":"init",...},
  {"type":"assistant","message":{...},...},
  {"type":"result","subtype":"success","result":"<model text>",
   "total_cost_usd":0.0269,"is_error":false,"usage":{...},"modelUsage":{...},...} ]
```

**Cost/usage live in the LAST element whose `type=="result"`.** `result.result` is the model's text (what
Forge's existing consumers read). `usage` carries `input_tokens`, `output_tokens`, `cache_read_input_tokens`,
`cache_creation_input_tokens` (plus nested extras). `total_cost_usd` is documented `float | None` and an
**estimate**. `modelUsage[<model>].costUSD` mirrors the aggregate (camelCase). `stream-json --verbose`
ends with a `{"type":"result",...}` line carrying the same totals.

→ `parse_headless_envelope` (Phase 5b) must accept **both** the array (take the last `result`) and a bare
`result` object, and fall back to raw text on anything else.

`is_error` is a real top-level field on the result element and can be `true` with **exit 0** (driven by
`subtype` ∈ `error_during_execution` / `error_max_turns` / …). So Forge maps `is_error → status` (#3);
`_JSON_IS_ERROR_RELIABLE = True`.

## Verdict matrix

`[COST-REPORTED]` = `total_cost_usd` is a number · `[USAGE-REPORTED]` = `usage.input_tokens` present ·
`[JSON-INCOMPATIBLE]` = combo errored / non-JSON.

| Auth mode | `plain` | `--model` | `--resume --fork-session` | `--bare` | `--bare --resume --fork-session --model` | `stream-json` |
| --------- | ------- | --------- | ------------------------- | -------- | ---------------------------------------- | ------------- |
| **direct API key** (confirmed, 2.1.165) | COST-REPORTED + USAGE-REPORTED | COST + USAGE | COST + USAGE | COST + USAGE | COST + USAGE | terminal `result`, `total_cost_usd` present |
| **OAuth / subscription** | _run under OAuth to fill_ — expected `[COST-ABSENT]` (no per-call dollar billing; `total_cost_usd` may be null) + `[USAGE-REPORTED]` | … | … | n/a (`--bare` disables OAuth) | n/a | _fill_ |
| **proxied** | JSON-compatible; `total_cost_usd` present but **Anthropic-priced** (wrong for non-Anthropic backends) → **Forge ignores it; the proxy cost plane wins** (5c precedence) | … | … | n/a | n/a | _fill_ |

All five **direct-API-key** combos returned `rc=0`, valid JSON, a terminal `result` element, and a real
`total_cost_usd` (e.g. `0.0269`, `0.0299`, `0.0023`) with full `usage`. No `[JSON-INCOMPATIBLE]` cell.

## DECISION

**GO (broad), for the direct path.** `--output-format json` is JSON-compatible with **every** Forge flag
combo (plain, `--model`, `--resume --fork-session`, `--bare`, the full supervisor combo, and
`stream-json`), and direct API-key runs reliably report `total_cost_usd` + exact `usage`, and `.result`
round-trips the model text. → Wire it.

Encoded for the wiring (Phase 5b, `src/forge/core/reactive/headless_json.py`):

- **Capability guard = retry-once-and-latch, no version probe.** The wiring requests JSON optimistically;
  if a CLI rejects `--output-format` it retries once without it and latches "unsupported" for the process.
  This is strictly cheaper than a `claude --version` gate (a modern CLI pays zero extra spawns; an old CLI
  self-heals with one instant flag-rejection) and never shells out on the hot path. Confirmed unnecessary
  on 2.1.165 (no combo rejected), so the latch never trips in practice.
- `_JSON_INCOMPATIBLE = frozenset()` — no incompatible combo found on 2.1.165 (a hook for a future regression).
- `_JSON_IS_ERROR_RELIABLE = True` — `is_error` is a trustworthy top-level field; map it into status.

**Provenance (5c):**
- **Direct** `claude -p` (no proxy) → `total_cost_usd` → `reporter="claude_code"`, `confidence="reported"`,
  `measurement_source="runtime_native"`. **Closes today's `unavailable` gap.**
- **Proxied** `claude -p` → the proxy cost plane stays authoritative (`reporter="forge_proxy"`); Claude's
  `total_cost_usd` is ignored for cost (Anthropic-priced → wrong for non-Anthropic backends + double-count).
  Exact in-band tokens are NOT mixed onto the snapshot-sourced event (#4).

**Open rows (not blocking the GO):** OAuth/subscription `total_cost_usd` nullability and the proxied
cost-compatibility row are filled by running `reproduce.sh` under those auth modes. Per the card, an OAuth
`[COST-ABSENT]` result is correct — record tokens (`provider_usage_exact`), keep cost `unavailable`, never
fake. The Docker contract test (`tests/integration/docker/test_headless_cost_report_contract.py`) pins the
API-key row in CI; this script pins the host matrix.
