# Proxy Log Hygiene -- quiet defaults and bounded request diagnostics

**Status**: Proposed. Split from the OpenRouter observability investigation on 2026-06-14.

**References**: proxy runtime truth `GET /`, request logs under `~/.forge/logs/requests/`, proxy logs under
`~/.forge/logs/proxy/`, audit/intercept design in `docs/design.md` §7.x and `docs/design_appendix.md` §A.11-A.12.

## Problem

Forge currently emits too much low-value proxy log volume while still missing the compact facts operators need during
timeouts.

The motivating investigation saw proxy logs dominate local log size over a short window. Two visible contributors:

- successful `GET /` health/runtime-truth polls are INFO-logged on every status-line/proxy check
- streaming adapters can DEBUG-log full adapted chunks, creating large text logs when debug is enabled

This makes `forge logs` noisy and expensive to inspect, but it does not solve the observability problem. The durable
answer to "what happened to my request?" should come from structured cost/audit/usage/provider-trace records, not from
megabytes of repeated health checks or chunk dumps.

## Proposal

Make normal proxy logging quieter, bounded, and aligned with Forge's existing no-plaintext audit policy.

### 1. Quiet successful health/runtime-truth polls

Do not INFO-log every successful `GET /` poll at normal log level. Keep visibility for:

- failures
- slow responses above a small threshold
- state transitions that matter to an operator
- debug-level traces when explicitly requested

The status line and health checks should be able to poll frequently without turning proxy logs into an access-log
stream.

### 2. Stop per-chunk stream dumps by default

Streaming chunks should not be dumped at normal debug settings. Replace full chunk dumps with compact lifecycle counters
or opt-in bounded traces:

- request id
- stream start/end
- chunk count
- first-chunk latency and total latency when available
- final usage seen/not seen
- error/timeout/disconnect markers

If a developer enables per-chunk diagnostics, truncate and redact fields before writing. Chunk diagnostics are debugging
evidence, not replay fixtures.

This card owns the logging behavior: stop raw chunk dumps and render compact in-log lifecycle summaries. The
OpenRouter/provider-trace card should consume the same shared stream-lifecycle instrumentation to persist structured
provider trace records, so the proxy streaming loop does not grow two drifting capture paths.

### 3. Bound request/response JSONL diagnostics

Request JSONL remains useful, but it should have explicit retention and size limits so debug sessions cannot grow
without bound:

```yaml
logging:
  requests:
    enabled: auto              # off | auto | on
    body_capture: metadata     # metadata | redacted
    response_capture: metadata # metadata | redacted
    max_file_mb: 16
    max_total_mb: 256
    retention_days: 14
    stream_chunks: false
    stream_chunk_max_bytes: 0
```

`metadata` means method/path/model/status/timing/request ids/counts only. `redacted` means the existing redacted-body
builders may include sanitized structure. `enabled: on` is an intentional new capability for local diagnostics that is
not tied to global `log_level=debug`; it still stays bounded and redacted. There is intentionally no `full` or plaintext
mode here.

### 4. Keep body capture policy unified with audit

Forge's audit design deliberately says `audit.audit_full_body` captures redacted bodies only and that there is no raw
body mode. Request logging should not create a second, contradictory capture policy.

User-configurable logging should therefore control:

- whether request diagnostics are written
- metadata-only vs redacted-body capture
- extra redaction header names/patterns
- retention and size budgets
- whether bounded stream diagnostics are enabled

It should not allow accidental plaintext prompt, completion, or tool-output persistence. If Forge ever decides to add a
plaintext replay fixture mode, that needs a separate design decision that explicitly revises the audit contract.

## Open questions

- Should request diagnostic config live under global `logging.requests`, per-proxy config, or both with per-proxy
  overrides?
- Should successful `GET /` polls be silent, sampled, or DEBUG-only?
- Should the default for request JSONL be `off` or `auto` tied to `log_level=debug`?
- Should `forge logs` report current request/audit capture settings and retention budgets?

## Risks

- Overcorrecting could remove useful debugging evidence. Keep explicit debug toggles, but make them bounded and
  redacted.
- Request logging and audit logging already overlap. The implementation should reuse redaction helpers instead of
  inventing a parallel sanitizer.
- Changing log defaults may surprise users who depend on INFO access-style logs. Document the new debug switch.

## Acceptance sketch

- **Health polls stay quiet**: repeated successful `GET /` proxy polls at normal log level do not add one INFO line per
  poll.
- **Slow health poll visible**: a delayed `GET /` handler logs the slow poll once with request id and timing.
- **Stream chunks compact**: a streaming request with many chunks produces lifecycle summaries, not full chunk bodies.
- **Per-chunk debug bounded**: explicit stream chunk diagnostics are redacted/truncated and respect max bytes.
- **Request logs redact by default**: request/response JSONL enabled with default config omits or redacts prompts, tool
  output, and completions.
- **No plaintext body mode**: config validation rejects `body_capture=full` with a pointer to audit redacted-body
  policy.
- **Retention enforced**: diagnostics over the size/date budget prune oldest shards and preserve owner-only permissions.
- **Logs surface capture mode**: `forge logs` or config output identifies request diagnostics as off/metadata/redacted
  without printing secrets.
