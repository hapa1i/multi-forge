# Epic: Proxy diagnostic data hygiene

**Parent epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Lane**: `todo/` -- accepted coordination work parked pending review and merge of the Wave 5 MEDIUM admission record.

## Goal

Keep proxy diagnostics useful for correlation and failure triage without placing caller prompts, tool payloads,
malformed arguments, or unvalidated correlation values into ordinary logs or debug tool-event records.

## Design Authority

- [`docs/design_appendix.md` §A.11](../../../design_appendix.md#a11-intercept-audit-and-request-logging-configuration-7x)
  defines metadata/redacted capture and a no-plaintext posture for proxy diagnostics.
- [`docs/board/impl_notes.md`](../../impl_notes.md#no-caller-content-in-proxy-logs-redactor-excludes-caller-free-text-proxy_log_hygiene-review-2026-06-16)
  records that ordinary proxy module logs may carry metadata only; raw stream chunks require explicit opt-in.
- [`docs/developer/coding_standards.md` §5](../../../developer/coding_standards.md#system-boundaries-external-data)
  requires best-effort external-input handling to degrade to a safe, visible default.
- [`review_combined.md`](../../review_combined.md) supplies D035, D036, O037, O038, and O042.

## Reproduction Record

Five MEDIUM findings were rechecked on merged `main` at `c9c4bc2e`. One disposable pytest module passed six
broken-behavior characterizations; one also carried a current-behavior `0600` control assertion. The module was removed
after evidence capture.

| Finding      | Fixture                                                          | Observed result                                                                 |
| ------------ | ---------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| O037         | system/message/schema canaries; translated request at DEBUG      | all three caller-controlled values appeared in converter logs                   |
| O038         | malformed string/dict arguments plus a non-function tool call    | WARNING/ERROR records contained each raw payload                                |
| O042         | converter logger held above DEBUG; formatting spy                | suppressed request/schema debug messages still invoked the formatter twice      |
| D035 payload | 17,000-character tool-event detail                               | full caller detail reached JSONL unchanged                                      |
| D035 warning | client tool failure                                              | failure plaintext reached the ordinary WARNING                                  |
| D035 control | the same tool-event shard                                        | the file was already owner-only (`0600`), correcting part of the historical row |
| D036         | client `X-Request-ID` containing whitespace and path-like syntax | value reached request state, ordinary logs, and the response header verbatim    |

Source inspection also confirms that `forge logs clean` and optional `log_retention_days` discover `tool_events`, so
D035's original no-pruner wording is stale. `open_secure_append` already mitigates shard exposure with `0600` files;
free-form plaintext, unbounded per-record details, and missing `0700` directory hardening remain. No new per-plane
retention setting is admitted.

## Members and Sequence

| Order | Findings         | Member                                                                                      | Review boundary                                          |
| ----- | ---------------- | ------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| 1     | O037, O038, O042 | [`remove_proxy_converter_plaintext_logs`](../remove_proxy_converter_plaintext_logs/card.md) | translated request/response logging and eager formatting |
| 2     | D035             | [`make_tool_events_metadata_only`](../make_tool_events_metadata_only/card.md)               | tool-event schema, caller failure diagnostics, file dirs |
| 3     | D036             | [`validate_proxy_request_ids`](../validate_proxy_request_ids/card.md)                       | untrusted correlation header at proxy ingress            |

The converter member goes first because one metadata-only rewrite closes both plaintext and suppressed-formatting
findings without changing request/response conversion. D035 follows with a separate structured-record schema and keeps
the explicitly opted-in `tool_failures` plane intact. D036 remains independent because accepting or replacing a client
correlation value is an ingress compatibility decision, not log rendering.

## Shared Constraints

- Preserve translated request/response bodies, malformed-argument fallback objects, tool sanitization, and streaming
  output byte-for-byte; only diagnostics change.
- The opt-in `logging.requests.stream_chunks` path remains the sole sanctioned raw converter dump.
- `log_tool_failures=true` remains an explicitly opted-in, bounded plaintext plane and must not be silently disabled or
  repurposed.
- Metadata strings and collections written to `tool_events` must be structurally allowlisted and length/count bounded;
  arbitrary nested `details` are not metadata.
- Valid, conventional client request IDs remain stable. Invalid or overlong values mint a normal Forge request ID and
  never appear in logs, telemetry, or response headers.
- Each member retains a marked regression that fails on its merged-main base and runs the relevant translated-proxy
  Docker integration before closeout.

## Closeout

Close this epic only after all three members ship independently, the review ledger records their dispositions, and the
ordinary-log, structured-tool-event, and request-correlation boundaries are covered by retained regressions. Remaining
Wave 5 MEDIUM rows stay with the parent maintenance epic.
