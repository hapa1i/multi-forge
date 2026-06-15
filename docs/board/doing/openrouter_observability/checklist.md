# Checklist -- OpenRouter Provider Trace

Execution plan for `docs/board/doing/openrouter_observability/card.md`. Branch: `openrouter-observability`.

Grounded in a verified codebase investigation (2026-06-15). Every file:line below was confirmed against `src/` before
planning; see **Card corrections** for claims the code refuted.

## Current focus

**Phases 0 + 1 are complete.** Phase 0 -- all four probes settled 2026-06-15 (probes 1-3 re-run after harness fixes; see
`phase0-results.md`). **Phase 1 (identity headers) shipped** offline: the `X-Forge-Session`/`X-Forge-Command` minter +
sanitizer + validators, client-side stamping, headless-spawn population, and proxy read/validate, all unit-tested
(`make test-unit` 6094 green, `make pre-commit` clean). **Phase 2** (additive `ProviderTraceMeta`) is next and is
**unblocked** to populate `provider_generation_id` from the streaming `chunk.id` / non-streaming `body.id` (probe 1;
streaming is **not** structurally `None`). **Phases 3-4** (trace plane + read surface) build against fixtures (e.g. a
simulated cancelled stream) once the Phase 2 shape lands; probe 2 confirms a cancelled stream is **not remotely
retrievable** (`[REMOTE-ABSENT]`), so the local-only `unavailable` justification holds. **Phase 5** (injection) gets a
**channel correction**: OpenRouter **recognizes `user`** (records it) but **ignores `session_id`** -> inject under
`user`; routing is neutral (both arms), so the flag stays default OFF (opt-in for observability, not performance).

## Decisions locked (this card)

| Decision                       | Choice                                                                        | Consequence                                                                                                                                                                                            |
| ------------------------------ | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `session_id` injection default | **Opt-in config flag, default OFF**                                           | Injection (Phase 5) is gated; the trace plane works without it. Decouples observability from the routing-behavior change.                                                                              |
| `session_id` granularity       | **`forge_sess_<hash>_<role>`**, fallback `forge_run_<hash>`                   | `root_run_id` is the only id all direct callers share -> right fallback. Human name is hashed, never sent raw.                                                                                         |
| Trace retention / reset        | **Match audit (14d / 512 MB); NOT in `forge proxy costs reset`**              | Traces are metadata-only diagnostics, not spend truth. One mental model with the audit plane. Chosen once, shared with `proxy_log_hygiene`.                                                            |
| Action tagger scope            | **Out of scope (documented gap)**                                             | `tagger.py` defaults to `gemini -> litellm_local`, no `provider=` arg; reaching OpenRouter is a separate routing change.                                                                               |
| Provider metadata shape        | **Nested optional `ProviderTraceMeta`** on `CompletionResponse`/`StreamEvent` | Lower churn than ~6 flat fields x2 models; keeps synthetic-id namespace separate. (`types.py` has no `extra='forbid'`; `cost_usd` was added the same additive way.)                                    |
| Trace-write home               | **One shared helper invoked from the proxy `on_complete` seam**               | Only existing shared stream-lifecycle point with `request_id` + run-tree headers in hand. Direct `core.llm` callers populate `provider_meta` but join via the usage ledger, not the proxy trace plane. |

## Open implementation question (settle in Phase 5, not blocking)

- **Where does the injection opt-in flag live?** Proxied path is proxy-owned/routing-adjacent (-> `proxy.yaml`); direct
  `core.llm` callers have no proxy (-> a runtime/session setting). Recommendation: a `proxy.yaml` field for the proxied
  path + a parallel runtime-config key for direct callers, both default OFF. Decide at the start of Phase 5 itself; it
  does not block Phases 0-4.

---

## Phase 0: OpenRouter externals probes (operator-gated)

**Goal**: Pin the live OpenRouter behaviors the code cannot answer, before populating any provider-id field. Record
results under `docs/board/doing/openrouter_observability/` (probe notes) and/or `scripts/experiments/openrouter/`.

| #   | Probe                                                                                                                                                                                                                  | Records                                                                                                                       | Gates                                                                                                           |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| 1   | Generation-id source: streaming `chunk.id` vs non-streaming `body.id` vs response header vs `/api/v1/generation` lookup. Note streaming cannot use `with_raw_response`, so header-only ids are unavailable mid-stream. | Literal id format/prefix and which surface carries it                                                                         | Phase 3 field population; whether streaming `provider_generation_id` is structurally `None` (the incident case) |
| 2   | Cancelled-stream remote visibility: cancel before final usage, then query `/generation`, `/activity`, dashboard.                                                                                                       | Whether OpenRouter retains an aborted stream and via which endpoint/key; whether cost was billed                              | Phase 4 scope + the `explain` copy; justifies local-only `local_usage_status="unavailable"`                     |
| 3   | `session_id` transport: inject via `extra_body` on the direct client; separately check the LiteLLM-gateway route.                                                                                                      | Whether `session_id` reaches OpenRouter on (a) direct and (b) LiteLLM paths; exact body key; whether LiteLLM strips it        | Phase 5 channel correctness                                                                                     |
| 4   | `session_id` routing impact: repeated large supervisor-style prompts with/without sticky `session_id`.                                                                                                                 | First-token + total latency, cache indicators, provider selection, failure rate; watch the adverse pin-to-worse-provider case | Whether the opt-in flag is safe to recommend enabling; the 45s-timeout hypothesis                               |

- [x] **Harness authored** (`scripts/experiments/openrouter/`): `reproduce.sh` + `lib.sh` + `sanitize.sh` +
  `helpers/or_probe.py` (async, typed) + 5 stages (`00`-`40`) + `README.md`; results at
  `docs/board/doing/openrouter_observability/phase0-results.md`. Lint/type-checked (`bash -n`, `shellcheck`,
  `ruff`/`black`/`mypy`/`pyright`).
- [x] Probe 1 recorded (generation-id source) -- `[GENID-IN-STREAM-CHUNK]`: `gen-` id in `body.id`, `x-generation-id`
  header, **and** every stream `chunk.id` (stable across 12 chunks); Forge drops it
  (`forge_canonical_type_preserved_provider_id=false`). **Streaming `provider_generation_id` is NOT structurally
  `None`** -- corrects the hedge at line 43 / the Phase 2 streaming task.
- [x] Probe 2 recorded (cancelled-stream remote visibility) -- `[REMOTE-ABSENT]` **confirmed on re-run** after the
  false-positive fix. Aborted id: `/generation` 404 across all 6 poll attempts (~23s) **and** absent from `/activity`
  (200); the completed-call **baseline indexed to 200**, so the window was long enough and the absence is real. (The
  first run's `[REMOTE-PRESENT-GENERATION]` was a harness bug: a 404 error body counted as "present" via bare
  `bool(body)`; fixed with an HTTP-200 gate + eventual-consistency poll + baseline control.)
- [x] Probe 3 recorded (`session_id` transport, direct arm) -- `[CHANNEL-USER-RECOGNIZED]` (polled re-run). OpenRouter
  **records the OpenAI-standard `user`** (recognized -- the sent value appears in the indexed `/generation` record) but
  **ignores a custom `session_id`** (transported, unverifiable). **Channel correction APPLIES: Phase 5 should inject
  under `user`, not `session_id`** (see Card corrections + Phase 5 note). Recognition is **not** routing impact (probe 4
  neutral). Direct path only; gateway arm opt-in (LiteLLM transport code-settled, `transformation.py:165-169`). The
  first run's un-polled `[CHANNEL-UNVERIFIABLE]` was an indexing artifact (fixed via `_poll_generation_body`).
- [x] Probe 4 recorded (`session_id` routing impact) -- `[STICKY-NEUTRAL]`: sticky vs baseline within noise, no cache
  hits, single provider (`Azure`), 0% failure -> **no reason to recommend enabling** the flag (stays OFF regardless).

> If cancelled streams are absent remotely (probe 2), that is an **expected** result, not a failure -- it is the reason
> the local trace must self-describe disconnect/timeout. (Probe 2 must assert this via the 200-gated poll + baseline
> control, not a bare `bool(body)` lookup -- see the false-positive note above.)

---

## Phase 1: Forge-owned session ids + `X-Forge-Session` / `X-Forge-Command` headers

**Goal**: Mint opaque, path-free provider session ids and propagate the human session name + command role to the proxy
via new sanitized, leak-gated headers. Identity foundation every later phase joins on.

- [x] **Minter + sanitizer** (`src/forge/core/run_id.py`): added `FORGE_SESSION_HEADER`/`FORGE_COMMAND_HEADER`,
  `sanitize_label` (canonicalizes **all** separator runs to `_`, so `memory writer`/`memory-writer` collapse — one
  charset for the id suffix and the command header), `derive_provider_session_id(label, root_run_id, role)` (SHA-256
  12-hex short hash; explicit `forge_run_<hash(root_run_id)>` fallback when no label), and `is_valid_label` /
  `is_valid_provider_session_id` validators (reject spoof, distinct from `RUN_ID_RE`). 58 tests in `test_run_id.py`. -
  *Verified*: label hashed (no raw name leaks); no-label → `forge_run_<hash>`; injection/over-long rejected.
- [x] **Client-side stamping** (`src/forge/core/reactive/env.py`): `_apply_correlation_headers` now stamps
  `X-Forge-Session` (always emittable via the fallback) + `X-Forge-Command` (only when a role is set) after the run-id
  lines, with both header names added to the `forge_owned` strip-set; `FORGE_SESSION_VAR`/`FORGE_COMMAND_VAR` added
  beside the run-id var family (the `session_start.py`/`codex_invoke.py` `FORGE_SESSION` literals stay separate by
  leaf/hook discipline). - *Verified*: proven-proxy → one fresh of each, stale stripped, opaque value; non-proven →
  neither (6 new tests in `test_env.py`).
- [x] **Populate at headless spawns**: `supervisor.py` (role `supervisor` + `context.session_name`), `memory_writer.py`
  (role `memory_writer` + `session_name`), `review/engine.py` (role `review` only; no session in scope →
  `forge_run_<hash>` fallback). **Correction:** `run_claude_session` already had an `extra_env` pass-through — no
  signature change needed (the plan's "plumbing gap" was wrong; the Explore agent missed `extra_env`). - *Verified*:
  supervised fork sets both vars; writer sets both (focused tests in `test_supervisor.py` + `test_memory_writer.py`).
- [x] **Proxy read + validate** (`src/forge/proxy/server.py`): `log_requests_middleware` reads + validates both headers
  via `_valid_session_header`/`_valid_command_header` (new validators, **not** `is_valid_run_id`), stores on
  `request.state` before both branches; added getter `_forge_session_command` beside `_forge_run_ids` (consumed by the
  Phase 3 trace writer). - *Verified*: valid → stored; spoofed/over-long → `None`; build_upstream_headers drops all
  `X-Forge-*` (allowlist already excludes — asserted, not re-stripped). New `test_server_forge_headers.py` (10 tests).
- [x] Design-doc sync: `design_appendix.md` §A.13 region now documents the two headers as internal Forge↔proxy
  correlation only (dropped upstream), distinct from the Phase 5 `user` field.

| Test                                                        | Fixture                                                           | Assertion                                                                        | Test File                                      |
| ----------------------------------------------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------------- | ---------------------------------------------- |
| Session id is opaque/path-free                              | manifest name = nested path, role=`supervisor`                    | id is `forge_sess_<hash>[_supervisor]`, no `/`, no raw name                      | `tests/src/core/test_run_id.py`                |
| Headers stamped only to proven proxy, stripped-then-readded | env w/ stale `X-Forge-Session` + proven marker; second non-proven | proven: one fresh of each after run-id lines, stale removed; non-proven: neither | `tests/src/core/reactive/test_env.py`          |
| Proxy validates + never forwards                            | request w/ valid `X-Forge-Session` + spoofed `X-Forge-Command`    | state has sanitized session, command `None`; upstream headers carry neither      | `tests/src/proxy/test_server_forge_headers.py` |

---

## Phase 2: Provider metadata through `core.llm` (additive `ProviderTraceMeta`)

**Goal**: Add an optional nested `ProviderTraceMeta` to `CompletionResponse` and `StreamEvent`, populated from the
OpenRouter/LiteLLM clients, so provider id / generation id / selected upstream / allowlisted headers / sent `session_id`
flow to the proxy boundary instead of dying in raw dicts. Depends on Phase 0 probe 1 for *which field* to lift.

- [ ] **Type** (`src/forge/core/llm/types.py`, `__init__.py`): `ProviderTraceMeta(BaseModel)` all-optional/defaulted
  (`provider`, `provider_response_id`, `provider_generation_id`, `provider_request_id`, `selected_provider`, `headers`,
  `provider_session_id`); add `provider_meta: ProviderTraceMeta | None = None` to both models; export. - *Assertion*:
  `CompletionResponse(text=...)` / `StreamEvent(type=...)` with no `provider_meta` still construct; all-`None`
  `ProviderTraceMeta` valid; existing fake-client tests stay green.
- [ ] **Non-streaming populate** (`src/forge/core/llm/clients/openai_compat.py`): set `provider_meta` in
  `openai_response_to_completion` from `response.id` / `response.model_extra` (the hook already used by
  `extract_reported_cost_usd`), keyed by probe 1's finding; pass provider name through. - *Assertion*: a non-streaming
  OpenRouter completion carries `provider="openrouter"` + the probe-confirmed id; a LiteLLM completion carries
  `provider="litellm"`.
- [ ] **Streaming populate** (`src/forge/core/llm/clients/openrouter.py`): read `chunk.id` in `.stream` (currently
  dropped) onto the usage/`response_end` event; if probe 1 says the gen-id is header-only, leave
  `provider_generation_id=None` and record the structural gap (the incident must still produce a useful trace). -
  *Assertion*: streamed OpenRouter response sets `provider_meta` from `chunk.id` when present; header-only case leaves
  `provider_generation_id=None` and still records lifecycle facts.
- [ ] **Header allowlist** (`litellm.py`, `openrouter.py`): allowlist helper beside `cost_from_response_headers`;
  populate `provider_meta.headers` from `with_raw_response` on non-streaming/Responses paths only. - *Assertion*:
  `headers` contains only allowlisted correlation headers (never `Authorization`/keys); streaming leaves `headers=None`.
- [ ] **Adapter carry-through** (`proxy/client_adapter.py`, `client_factory.py`): widen `AdapterProviderType` to include
  `"openrouter"` (factory already passes it at runtime); carry `provider_meta` via an internal-only carrier key on the
  usage chunk (same pattern as `reported_cost_micros` at `converters.py:918`), keeping the synthetic `chatcmpl-<epoch>`
  id (`client_adapter.py:204/:329`) strictly separate from `provider_generation_id`. - *Assertion*: mypy passes with
  `provider="openrouter"`; the synthetic id stays `chatcmpl-<ts>` and is `!=` `provider_meta.provider_generation_id`;
  the provider id is dropped by the Anthropic translation (never reaches the client).

| Test                          | Fixture                                                               | Assertion                                                               | Test File                                  |
| ----------------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------ |
| Provider metadata is additive | fake `core.llm` client returning no `provider_meta`                   | completions/stream events normal; `provider_meta` defaults `None`       | `tests/src/core/llm/test_types.py`         |
| Provider id lifted into meta  | fake OpenRouter response `id="gen-..."` (probe surface)               | `provider_meta.provider_generation_id` set, `provider="openrouter"`     | `tests/src/core/llm/test_openai_compat.py` |
| Synthetic id != provider id   | OpenRouter completion w/ `provider_generation_id` through the adapter | response id is `chatcmpl-<ts>`, distinct from provider id; both carried | `tests/src/proxy/test_client_adapter.py`   |

---

## Phase 3: Shared stream-lifecycle seam + provider-trace plane

**Goal**: Extend the **single** shared SSE capture point with lifecycle flags, derive `local_usage_status`, and persist
metadata-only owner-only records to `~/.forge/providers/openrouter/traces/<YYYY-MM>_<pid>.jsonl`. Depends on Phases 1-2
and probe 2.

- [ ] **Lifecycle flags at the one seam** (`src/forge/proxy/converters.py`): in `convert_openai_to_anthropic_sse` track
  `stream_started` (message_start), `first_chunk_seen` (first upstream chunk), `final_usage_seen` (usage chunk parsed
  `:887-920`). Detect disconnect with a **new** `asyncio.CancelledError` catch around the `async for`, set
  `client_disconnected`, then **re-raise** (CancelledError is `BaseException`, not caught by `except Exception`). Carry
  flags additively -- prefer the `final_usage` dict carrier (precedent: `reported_cost_micros` at `:918`) so the
  `_OnCompleteCallback` signature (`:40`, fired in `finally` at `:1209`) stays stable. - *Assertion*: `on_complete`
  receives the flags; aborted stream -> `client_disconnected=True`, `final_usage_seen=False`, `finally` still fires
  once; clean stream -> `final_usage_seen=True`, `client_disconnected=False`.
- [ ] **Mirror in passthrough** (`src/forge/proxy/passthrough.py`): same flags in `_stream_opened_upstream`
  (CancelledError on the relay; `final_usage_seen` when `_UsageAccumulator` sees the final `message_delta`), funneled
  into the **same** trace helper. (Passthrough cost is structurally always unavailable.) - *Assertion*: passthrough
  stream sets the same flags; both wire shapes call one shared helper, not two writers.
- [ ] **Trace plane writer/reader** (`src/forge/proxy/provider_trace_logger.py`, new -- model on `audit_logger.py` /
  `ledger.py`, **not** `cost_logger.py`): `PROVIDER_TRACE_SCHEMA_VERSION=1`;
  `_traces_dir()=get_forge_home()/"providers"/"openrouter"/"traces"`; shard `{YYYY-MM}_{pid}.jsonl`;
  `log_provider_trace` via `open_secure_append` under a dedicated non-reentrant `_lock`; **chmod all three dir levels
  0700**; best-effort try/except that never raises. `read_provider_traces`: glob + `decode_json_object` +
  skip-newer-schema-warn-once (own latch) + strict `dacite` (`strict=True`). Fields per card §4 (no bodies). -
  *Assertion*: 0600 files under 0700 three-level dirs; newer-schema skipped with one warning; unknown field =
  corruption; non-object line skipped; forced `OSError` swallowed; no prompt/completion/body field exists.
- [ ] **Write from the proxy** (`src/forge/proxy/server.py`): in `_on_stream_complete` and the non-streaming block,
  **after** cost logging, call the writer gated to the resolved OpenRouter provider, joining by `request_id` +
  `forge_run_id`/`forge_root_run_id` + `X-Forge-Session`/`Command`. Derive `local_usage_status` (`available` when
  reported cost/final usage present, else `unavailable`). Set `client_disconnected` from the SSE flag; **leave
  `timeout_seen=False`** -- the proxy never observes the parent's `subprocess.run` timeout (it only sees a disconnect);
  `timeout_seen` is for later run-tree correlation. Document this limit. - *Assertion*: OpenRouter stream that
  disconnects before final usage -> trace `stream_started=True`, `first_chunk_seen=True`, `final_usage_seen=False`,
  `client_disconnected=True`, `local_usage_status="unavailable"`; clean -> `final_usage_seen=True`,
  `local_usage_status="available"`; a litellm route writes no OpenRouter trace.
- [ ] **Config + prune** (`src/forge/config/schema.py`, `provider_trace_logger.py`, `server.py`): `ProviderTraceConfig`
  (`retention_days=14`, `max_total_mb=512`; bool-rejecting validation + `_reject_unknown_keys`) wired into
  `ProxyConfig`. `prune_provider_traces` cloned from `prune_audit_logs` (`audit_logger.py:428`) **and wired** into a
  `_maybe_prune_provider_traces()` called from `_ensure_runtime_state` (`server.py:168`) beside
  `_maybe_prune_audit_logs` (`:176`). Do **not** repeat the dead `prune_usage_events` (`ledger.py:274`, never invoked).
  \- *Assertion*: config rejects unknown keys + non-bounded values; prune deletes over `retention_days` and oldest-first
  over `max_total_mb` preserving 0600/0700; prune is invoked once per process.
- [ ] Design-doc sync: design.md §3.14 (three planes -> **four**; provider trace is lifecycle/correlation, joined by
  `request_id` + run-tree ids, **not** wiped by `forge proxy costs reset`), design_appendix new schema subsection.

| Test                                            | Fixture                                                                       | Assertion                                                                                                   | Test File                                                      |
| ----------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Stream lifecycle traced on disconnect           | openrouter proxy, stream, client cancels before final usage                   | trace: started/first-chunk true, final-usage false, disconnected true, status `unavailable`                 | `tests/src/proxy/test_provider_trace_logger.py`                |
| Plane owner-only / versioned / strict / bounded | shard + newer-schema record + unknown-field record + non-object line          | 0600 under 0700; newer skipped w/ one warning; unknown rejected; non-object skipped; prune respects budgets | `tests/src/proxy/test_provider_trace_logger.py`                |
| Trace metadata-only; cost not overloaded        | OpenRouter stream w/ prompt + completion                                      | no prompt/completion/tool/body field in trace; cost record schema/fields unchanged                          | `tests/regression/test_bug_openrouter_trace_metadata_only.py`  |
| `claude -p` join semantics preserved            | proxied `claude -p` w/ multiple OpenRouter requests, usage `source_refs` null | trace + cost joinable by `forge_root_run_id`/`request_id`; `source_refs` stays null                         | `tests/regression/test_bug_usage_claude_p_null_source_refs.py` |

---

## Phase 4: Local read surfaces (`forge provider trace list|show|explain`)

**Goal**: An op-backed CLI group that reads the plane and answers the incident's five questions from **local facts
only** -- no remote lookup (that is the reconciliation card). Depends on Phase 3.

- [ ] **Command-core op** (`src/forge/core/ops/provider_trace.py`, `__init__.py`): `list_provider_traces` /
  `show_provider_trace` / `explain_provider_trace` returning frozen dataclasses, raising `ForgeOpError`, taking
  `ExecutionContext` (shape of `core/ops/proxy.py`). `explain` builds a provenance DTO (left-Forge, route, provider
  session/generation id, stream lifecycle, cost-unavailable-vs-zero) from local records only. - *Assertion*: ops are
  Click/print-free; `explain_provider_trace` derives only from local trace+cost records, never calls a remote endpoint.
- [ ] **CLI group** (`src/forge/cli/provider.py`, `cli/main.py`): `provider` group orients (help only); nested `trace`
  group; `list`/`show`/`explain` leaves act with sensible defaults; `--json` from the same op DTO (table/JSON cannot
  drift); `forge.cli.output.print_error_with_tip` with the call site's local console; credential provenance prints only
  `env` / `credentials.yaml` / `management key unavailable` (never a key). - *Assertion*: bare `forge provider` prints
  help; `forge provider trace list` defaults to all sessions/today; `explain req_...` renders local-only provenance;
  `--json` emits the DTO; no key value ever printed.
- [ ] Docs sync (ship with the change): `docs/cli_reference.md` lists the three leaves; design notes the fourth plane's
  join keys + retention ownership; **`docs/end-user/proxy.md`** gains a provider-trace section -- board-contract Day-1
  rule, since `forge provider trace` is a new user-facing surface (split into a dedicated guide later if it grows with
  the reconciliation card).

| Test                                          | Fixture                                                   | Assertion                                                                                                                                                    | Test File                              |
| --------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------- |
| `explain` is local-only w/ precise provenance | trace for a disconnected supervisor OpenRouter request    | states left-Forge via proxy -> OpenRouter, stream started/emitted, final usage not observed, cost **unavailable not zero**, "No remote lookup was performed" | `tests/src/cli/test_provider_trace.py` |
| list/show/json from one DTO                   | two shards, several records, `--session`/`--since` filter | table + `--json` agree; missing-record `show` -> `print_error_with_tip` + exit 1                                                                             | `tests/src/cli/test_provider_trace.py` |

---

## Phase 5: `session_id` injection (opt-in, default OFF)

**Goal**: Carry the Forge-derived (or caller-preserved) session id into the OpenRouter body via `extra_body`, gated to
OpenRouter traffic **and** behind the opt-in flag. Last phase by design (routing-affecting; user chose opt-in). Depends
on Phase 1 + probes 3-4.

> **Channel correction (probe 3, polled re-run).** OpenRouter **records the OpenAI-standard `user` field** but **ignores
> a custom `session_id`** (`[CHANNEL-USER-RECOGNIZED]`). At implementation, inject the Forge id under **`user`** (the
> recognized channel -- makes a fork findable in OpenRouter's dashboard, addressing the incident), not the
> `extra_body["session_id"]` key the tasks below were drafted against. Update each body-key reference accordingly.
> Recognition is **not** a routing win (probe 4 `[STICKY-NEUTRAL]`), so the flag stays opt-in/off for *observability*,
> not performance. A recognized `user` value is retained by OpenRouter -> keep the "hash, never raw name" rule.

- [ ] **Flag** (home per the open question above): default OFF; the proxied path and direct callers both consult it. -
  *Assertion*: with the flag off (default), no `session_id` is injected on any path -- behavior is byte-identical to
  pre-card.
- [ ] **Direct client** (`src/forge/core/llm/clients/openrouter.py`): in `_translate_params` (`:77`) inject `session_id`
  into `extra_body` when absent, **preserving** an explicit caller `extra_body["session_id"]`. - *Assertion*: no-session
  call gets the Forge value; explicit caller value unchanged (mirrors `test_preserves_existing_extra_body`).
- [ ] **Direct callers** (`core/usage/correlation.py`, `policy/semantic/plan_check.py`, `session/transfer.py`): add
  `with_openrouter_session_id(hyperparams, session_id)` (deep-copy/no-clobber like `with_forge_request_id`, targeting
  `extra["openai"]["extra_body"]["session_id"]`); wire into plan-check + curation (both already
  `provider="openrouter"`); source `session_id` from `session_name`/`FORGE_SESSION` + role via the Phase 1 minter; gate
  on `provider==openrouter`. - *Assertion*: plan-check + curation OpenRouter calls carry the id; non-OpenRouter
  unchanged; fail-open contracts (plan-check->`needs_review`, curation->structured fallback) not altered by any new
  raise.
- [ ] **Proxied path** (`proxy/client_adapter.py`, `server.py`): thread `session_id` from validated
  `X-Forge-Session`/run-tree headers into `hyperparams_data["extra"]["openai"]["extra_body"]["session_id"]` in
  `create_completion`/`create_streaming_completion` (beside `_user_agent`) **when the bound provider is openrouter**;
  fall back to `forge_run_<hash>` when `X-Forge-Session` absent. Derive server-side -- a client top-level `session_id`
  is dropped twice (MessagesRequest `extra='ignore'` + the adapter's fixed-key extraction). - *Assertion*: OpenRouter
  proxy request w/o client `session_id` reaches the client with a Forge-derived `extra_body["session_id"]`;
  non-OpenRouter route untouched; absent `X-Forge-Session` -> `forge_run_<hash>` id.
- [ ] **Tagger gap** (`core/reactive/tagger.py`): document (do not silently no-op) that the tagger cannot reach
  OpenRouter today; out of scope for this card.

| Test                                          | Fixture                                                                           | Assertion                                                                | Test File                                      |
| --------------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------- |
| Flag off = no injection                       | flag default                                                                      | no `session_id` on direct or proxied OpenRouter calls                    | `tests/src/core/llm/test_openrouter.py`        |
| Injected when absent, preserved when explicit | recorded outbound body; one no-session, one `extra_body["session_id"]="caller_x"` | first = derived value; second = `caller_x`                               | `tests/src/core/llm/test_openrouter.py`        |
| Proxied OpenRouter gets derived id            | openrouter-openai proxy, `X-Forge-Session` set, no client session                 | upstream body has derived `extra_body["session_id"]`; litellm route none | `tests/src/proxy/test_client_adapter.py`       |
| Id is private (no path leak)                  | session in nested path, plan-check -> OpenRouter                                  | id is `forge_sess_<hash>[_role]`, no filesystem path                     | `tests/src/policy/semantic/test_plan_check.py` |

---

## Card corrections (verified against code 2026-06-15)

- **The `session_id` injection channel is wrong; use `user`** (probe 3, polled re-run, `phase0-results.md`). OpenRouter
  records the OpenAI-standard `user` field (`[TRANSPORTED+RECOGNIZED]`) but ignores a custom `session_id`
  (`[TRANSPORTED+UNVERIFIABLE]`). Phase 5 should inject the Forge id under `user`; a custom `session_id` is
  Forge-local-correlation only and invisible upstream. Recognition is not routing impact (probe 4 neutral). Direct path
  measured; recognition expected path-independent (LiteLLM forwards `extra_body` verbatim).
- **`~/.forge/logs/requests/` is real** (`proxy/utils.py:493`, debug-gated, body-redacted) -- the card's References line
  is correct. It is owned by the `proxy_log_hygiene` card, **not** a join target for provider trace.
- **Synthetic `chatcmpl-<epoch-seconds>` ids are minted in `CoreLLMClientAdapter`** (`client_adapter.py:204` non-stream,
  `:329` stream), **not** in `converters.py` (which mints `msg_<uuid>` and passes the adapter id through). Do not
  relocate id minting into converters.
- **`extra_body` (not "LiteLLM may drop params") is the channel** for the OpenRouter-direct path: `OpenRouterClient` is
  a direct OpenAI-SDK wrapper, no LiteLLM. The drop-params concern applies only to openrouter-**via-LiteLLM-gateway**
  routes.
- **"Preserve caller `session_id`" only holds for direct `core.llm` calls.** On the proxied path a client top-level
  `session_id` is dropped at MessagesRequest binding (`extra='ignore'`) and again by the adapter's fixed-key extraction
  -> server-side derivation required.
- **`timeout_seen` is not proxy-derivable.** The proxy sees only a client disconnect (`CancelledError`); the 45s timeout
  is the parent's `subprocess.run` killing `claude -p` (`session_runner.py:225-283`). Record `client_disconnected`;
  leave `timeout_seen` for run-tree correlation.
- **The card's "tagger/plan-check/curation share grouping" is nuanced:** plan-check + curation reach OpenRouter; the
  tagger structurally cannot (routing change, not a header change). Tagger is out of scope here.
- **Pruning machinery to clone is `prune_audit_logs`, not "the proxy_log_hygiene retention machinery"** (that card is
  unshipped). And **wire** the prune -- `prune_usage_events` exists but is never invoked (latent dead code; don't repeat
  it).
- **Model the plane on `audit_logger.py` / `ledger.py`, not `cost_logger.py`** (the odd one out: unversioned, no strict
  reader, no prune, no parent-dir chmod). `ledger.py:1-7` documents this choice.

## Risks (carry into implementation)

- `client_disconnected` requires a new `CancelledError` catch around the SSE `async for`; it is `BaseException` --
  catch, set the flag, **re-raise**, or the worker hangs.
- All four telemetry writers are best-effort/fail-open; the new writer + lifecycle instrumentation must never raise in
  `on_complete` or it breaks the very request being observed. The module `_lock` is non-reentrant.
- Three new dir levels (`providers/`, `openrouter/`, `traces/`) all need chmod 0700; `open_secure_append` only
  guarantees 0600 files.
- Prune is lazy (first-request) -- a proxy that never serves a request never prunes (acceptable, matches audit).
- `AdapterProviderType` currently excludes `"openrouter"` though the factory passes it at runtime (masked by a
  `type: ignore`); widen the `Literal` when setting `provider_meta.provider`.
- `session_id` stickiness can pin a session to a worse provider (probe 4 gates any enable recommendation).
- `ProviderTraceMeta` is shared by all direct callers + old providers; fields must stay optional/defaulted or fakes that
  build `CompletionResponse(text=...)` break.

## Closeout

- [ ] All phase acceptance tables green (`make test-unit`); relevant integration tests for proxy/streaming changes
  (`./scripts/test-integration.sh tests/integration/proxy/...`).
- [ ] `make pre-commit` clean (ruff, black, isort, mypy, pyright, mdformat, gitleaks).
- [ ] Design + end-user docs synced: design.md §3.14 (four planes), design_appendix (provider-trace schema + §A.13 join
  note), cli_reference (`forge provider trace`), and `docs/end-user/proxy.md` (provider-trace section -- Day-1 rule).
- [ ] Change-log entry (`docs/board/change_log.md`): goal, key changes, verification.
- [ ] Promote durable lessons to `impl_notes.md` after human review (the fourth-plane idiom; the shared SSE seam; the
  synthetic-vs-provider id separation).
- [ ] Move card `doing/openrouter_observability/ -> done/` after merge to `main`.
- [ ] Hand the shared stream-lifecycle seam to `proxy_log_hygiene` (it consumes the same flags for compact in-log
  summaries -- the two cards must not double-instrument the loop).
