# Proxy Log Hygiene -- Execution Checklist

Branch: `proxy_log_hygiene`. Card: [card.md](card.md). Full scope (slices 0-5) per user decision 2026-06-16.

## Current Focus

Slice 0 (provider_trace loader bug) -> Slice 1 (quiet polls) -> ... -> Slice 5 (prune + reporting) -> docs + adversarial
review + closeout.

## Decisions (locked)

- **Scope**: full card (slices 1-5) plus the `provider_trace` loader bug folded in as Slice 0 (same two loader sites
  Slice 4 wires).
- **Config home (card Q1)**: **per-proxy** `logging` block on `ProxyConfig` + `ProxyInstanceConfig`, modeled on
  `AuditConfig`. Matches `audit`/`intercept`/`provider_trace`; reuses `forge proxy edit`. No global `logging.requests`
  block (avoids new `forge config` plumbing).
- **GET / polls (card Q2)**: successful 200 -> DEBUG; keep INFO for `status >= 400` OR `elapsed > SLOW_POLL_S`. Not
  silent, not sampled. Slow-poll visibility is NEW behavior (none exists today).
- **Request-JSONL default (card Q3)**: `enabled: auto` = preserve today's coupling (`log_level == debug`).
  Backward-compatible; `on`/`off` are explicit. `on` decouples capture from full debug spam (still bounded + redacted).
- **Lifecycle summary scope (card)**: **all providers** (the in-log summary is provider-neutral; the OpenRouter gate
  bounds only the structured provider-trace plane).
- **Retention ownership (recon gap)**: per-proxy prune at proxy startup (idempotent, audit precedent) bounds
  `logs/requests/` shards; global `log_retention_days` sweep stays the coarse floor. Documented, no conflict.
- **`stream_chunks` (card)**: default `false` -> the compact lifecycle summary replaces per-chunk lines. `true`
  re-enables **truncated + redacted** per-chunk traces bounded by `stream_chunk_max_bytes`. **Never** raw bodies; reject
  `body_capture=full` with a pointer to the audit redacted-body policy.
- **Pruner reuse**: factor one shared `prune_jsonl_shards(dir, *, retention_days, max_total_mb, pattern)` helper;
  migrate `prune_audit_logs` + `prune_provider_traces` to call it (kills the byte-identical third copy) only if their
  tests stay green; else add the request pruner alone and note the debt.

## Claim corrections (from recon, fold into card.md before closeout)

- Card names `src/forge/proxy/openrouter.py` (does not exist). Sole chunk-dump offender is `converters.py:874` (+
  secondary `:1016`); core llm clients / client_adapter / passthrough stream loops are clean.
- "INFO on every poll" is only true at `log_level=info|debug`; default `off` suppresses it. Noise is scoped to opted-in
  users -- state this in the card.
- "keep failures/slow polls visible" has NO existing implementation to preserve -- it is new behavior to add.
- `logs/requests/` vs `costs/requests/` vs `audit/requests/` are distinct coexisting planes sharing the leaf name
  `requests`; no contradiction with the appendix.

## Slice 0 -- provider_trace loader bug (folded)

- [x] `config/loader.py:435-457` `load_proxy_instance_config_from_dict` passes
  `provider_trace=data.get("provider_trace", {})`.
- [x] `config/loader.py:557-567` `_proxy_instance_to_forge_config` passes `provider_trace=proxy_config.provider_trace`.
- [x] Confirmed the running-proxy read path: `server.py:1054` reads
  `config.proxy.provider_trace.inject_openrouter_user`, `:181` prunes from `config.proxy.provider_trace`; chain is
  `proxy.yaml -> load_proxy_instance_config -> _from_dict -> _proxy_instance_to_forge_config -> config.proxy`.
- [x] Regression `tests/regression/test_bug_provider_trace_loader_dropped.py` (3 tests): verified to FAIL without the
  fix (stash-revert-rerun) and pass with it. Both hops + defaults-when-absent.

## Slice 1 -- quiet successful GET / polls

- [x] `proxy/server.py` middleware: `logger.log(level, ...)` with
  `level = INFO if status>=400 or elapsed>_SLOW_POLL_LOG_S else DEBUG`. Reuses existing `elapsed`/`status` locals +
  `verbose_endpoints`.
- [x] `_SLOW_POLL_LOG_S = 1.0` module constant (above the middleware).
- [x] Non-200 still emits one INFO line (status embedded). Verbose endpoints unchanged.
- [x] `tests/src/proxy/test_server_log_hygiene.py` (5 tests): repeated 200 -> 0 INFO; slow / 503 -> 1 INFO; verbose
  endpoint keeps its DEBUG line. All green.

## Slice 2 -- bound per-chunk dumps

- [x] `converters.py` full-chunk dump -> `smart_format_str(chunk)` bounded AND `logger.isEnabledFor(DEBUG)` guard.
- [x] `converters.py` full `tool_calls_delta` dump -> same bounded + guarded treatment.
- [x] `tests/src/proxy/test_converters_log_hygiene.py`: spy proves `smart_format_str` called 0x when DEBUG off; a 10k
  chunk is truncated (\<500-char field cap, raw string absent) when DEBUG on.

## Slice 3 -- compact all-provider lifecycle summary

- [x] Added `chunk_count` counter in the converter loop.
- [x] Shared `format_stream_lifecycle_summary(...)` in `proxy/utils.py` (metadata-only: outcome + chunks + flags +
  error_type). Converter `finally` emits it: DEBUG for clean, INFO for error/disconnect -- replaces the bare
  `logger.info(... conversion finished)`.
- [x] All-provider (NOT OpenRouter-gated). Demoted the two redundant per-stream INFO bookends (`Starting ... conversion`
  and `Received final finish_reason`) to DEBUG -> a clean stream emits ZERO converter INFO.
- [x] Passthrough relay (`passthrough.py`) reuses the same helper (chunk_count counter added): DEBUG normally, INFO on
  client disconnect -- which the relay previously logged nowhere (the incident class). TTFB deferred (raw byte stream;
  total latency stays in cost/metrics records).
- [x] `tests/src/proxy/test_converters_log_hygiene.py`: clean stream -> one DEBUG summary `chunks=3`, zero INFO;
  disconnect -> one INFO `stream disconnected chunks=1`; pure-helper render tests (ok/error/disconnect, no bodies).

## Slice 4 -- per-proxy `logging` config block

- [x] `config/schema.py`: `RequestLogConfig` (8 fields) with strict `__post_init__` (enum/bool/non-negative-int,
  `body_capture=full` rejected with audit pointer) + `_coerce_request_log_config`. Nested under `LoggingConfig`
  (`logging.requests`, forward-compatible) + `_coerce_logging_config`. Both use `_reject_unknown_keys`.
- [x] `logging: LoggingConfig` on `ProxyConfig` + `ProxyInstanceConfig`; coerced in both `__post_init__`.
- [x] Wired `logging` through BOTH loader hops (`loader.py` `_from_dict` + `_proxy_instance_to_forge_config`).
- [x] `proxy/utils.py`: `request_logging_enabled(cfg)` helper (duck-typed: auto/on/off) + `log_request_response`
  `request_log=` param. `metadata` (default) omits bodies; `redacted` includes `_redact_body_for_log` structure (NO
  second sanitizer, no plaintext). Threaded `config.proxy.logging.requests` into all 4 server call sites.
- [x] **stream_chunks wiring (4c)**: `convert_openai_to_anthropic_sse` gains `stream_chunks`/`stream_chunk_max_bytes`
  (kw-only); per-chunk dumps now require opt-in AND DEBUG (off even at `log_level=debug` by default), truncated to
  `stream_chunk_max_bytes`. Server passes `config.proxy.logging.requests.stream_chunks/...max_bytes`.
- [x] `tests/src/config/test_request_log_config.py` (18) + `tests/src/proxy/test_request_logging.py` (8): coercion
  strictness, full-rejection through loader, both loader hops carry the block, enabled matrix, metadata-vs-redacted
  writes (no plaintext leak). Converter opt-in/truncation tests updated. All green.

## Slice 5 -- request-log prune + capture-mode reporting

- [x] Shared `proxy/retention.py::prune_jsonl_shards(...)`; `proxy/utils.py::prune_request_logs(...)` over
  `logs/requests/*_requests.*.jsonl`. Migrated `prune_audit_logs` + `prune_provider_traces` to delegate to it (third
  byte-identical copy removed; their suites stay green).
- [x] `max_file_mb` per-file rotation: `_active_request_log_shard` rolls seq0 -> `.1.jsonl` ... once a shard hits the
  cap (0 = unbounded, historical name). Wired into the writer.
- [x] `server.py`: `_maybe_prune_request_logs()` reading `config.proxy.logging.requests`, wired into
  `_ensure_runtime_state()` beside audit/provider-trace (once-per-process flag).
- [x] `forge proxy show <id>` renders a configured `logging:` block via the raw proxy.yaml dump (same as
  audit/provider_trace; effective defaults aren't serialized -- consistent existing behavior).
- [x] `cli/logs.py`: updated `requests/` description + an informational note (per-proxy logging.requests, auto/on/off,
  bodies redacted/no plaintext, points to `forge proxy show`). No secrets printed.
- [x] `tests/src/proxy/test_request_log_prune.py` (11): retention + size-cap + pattern scoping + rotation;
  `test_logs_command.py` note test. Migrated audit/provider-trace prune suites unchanged.

## Acceptance tests

| Test                       | Fixture                                        | Assertion                                          | Test File                                                    |
| -------------------------- | ---------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------ |
| provider_trace not dropped | proxy.yaml with `provider_trace:` non-defaults | derived ProxyConfig carries them                   | `tests/regression/test_bug_provider_trace_loader_dropped.py` |
| poll quiet                 | repeated 200 GET / at info level               | 0 INFO completion lines                            | `tests/src/proxy/test_server_log_hygiene.py`                 |
| slow/err poll visible      | GET / with elapsed>threshold or 503            | exactly 1 INFO line                                | `tests/src/proxy/test_server_log_hygiene.py`                 |
| chunk dump bounded         | huge chunk, DEBUG on                           | logged string \<= max bytes; DEBUG off -> no build | `tests/src/proxy/test_converters_log_hygiene.py`             |
| lifecycle summary          | normal + cancelled stream                      | one summary line; chunk_count>0; disconnected flag | `tests/src/proxy/test_converters_log_hygiene.py`             |
| config strictness          | `body_capture=full`, unknown key               | ValueError with audit pointer / unknown-key        | `tests/src/config/test_request_log_config.py`                |
| enabled modes              | auto/on/off + log_level                        | correct write/skip matrix                          | `tests/src/proxy/test_request_logging.py`                    |
| request prune              | over-budget shards                             | oldest pruned, 0600 preserved                      | `tests/src/proxy/test_request_log_prune.py`                  |

## Reviewer follow-ups (2026-06-16, all verified against code before fixing)

- [x] **No caller content in stream logs** (`converters.py`): 8 sites (per-delta text/tool-args, whole-chunk/`tc_delta`
  WARNING dumps, buffered-tool close-event `partial_json`) -> metadata only (len/keys/index). Opt-in `stream_chunks` is
  the sole raw-content path. Tests: `test_text_delta_*`, `test_tool_args_delta_*`, `test_buffered_tool_close_*`,
  `test_malformed_chunk_warning_*` in `test_converters_log_hygiene.py`.
- [x] **stop_sequences plaintext leak** (`utils.py`): removed from `_SAFE_KEYS`; `{"redacted": True, "count": N}`.
  Closes audit + request planes. Regression: `test_bug_request_log_stop_sequences_plaintext.py` (redactor + on-disk).
- [x] **CLI int coercion** (`cli/proxy.py`): `forge proxy set` int-casts `max_file_mb` + `stream_chunk_max_bytes`.
  Regression: `test_bug_proxy_set_request_log_ints.py`.
- [x] **Third construction site** (`proxy_orchestrator.py::create_proxy_file`): copies template `provider_trace` +
  `logging`. Regression added to `test_bug_provider_trace_loader_dropped.py` (create path).
- [x] Two adversarial review rounds + a full enumeration of every converter `logger.*` call confirmed no remaining
  caller-content interpolation (only index/len/keys/token-counts/enums/tool-names survive).

## Closeout

- [x] `make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat/gitleaks); `git add -u` after auto-format.
- [x] Targeted unit suites green (6401 unit + 438 regression); relevant proxy integration tests pass:
  `test_proxy_local_litellm_e2e.py` (3, incl. streaming SSE) + `test_provider_trace_e2e.py` (2, incl. cancelled-stream
  disconnect). Validates the converter signature change + loader fix on the live-proxy path.
- [x] Adversarial review workflow on the full diff before final (9 agents, 7 dimensions + refute-by-default verify): 0
  blockers/majors/minors in production code; 1 confirmed nit (no direct 0600 assertion on the request shard) -> fixed
  via `test_written_shard_is_owner_only_0600`; 1 rejected (passthrough coverage, out of scope).
- [x] Docs: design.md §7.x (renamed A.11 anchor + Request-log-hygiene note) + design_appendix §A.11 (new `logging`
  block: YAML, field table, plane note) + end-user `proxy.md` (Request diagnostics logging section) + `cli_reference.md`
  (`forge logs` delta; `forge proxy show --raw` already covers block rendering).
- [x] Fold the claim corrections above into `card.md` (Resolution section + Status update).
- [x] `change_log.md` entry (newest-first) + promoted the loader two-hop / shared-pruner invariants to `impl_notes.md`.
- [x] `git mv docs/board/doing/proxy_log_hygiene docs/board/done/proxy_log_hygiene` after merge.
