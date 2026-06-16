# Checklist -- OpenRouter Provider Trace

Execution plan for `docs/board/doing/openrouter_observability/card.md`. Branch: `openrouter-observability`.

Grounded in a verified codebase investigation (2026-06-15). Every file:line below was confirmed against `src/` before
planning; see **Card corrections** for claims the code refuted.

## Current focus

**Phases 0 + 1 + 2 + 3 are implemented** (Phase 3 pending its Docker-integration commit gate). Phase 0 — all four probes
settled 2026-06-15. **Phase 1 (identity headers)** + **Phase 2 (additive `ProviderTraceMeta`)** shipped offline:
provider/generation id + selected upstream + allowlisted headers flow from the OpenRouter/LiteLLM clients to the proxy
boundary via a typed internal carrier, separate from the synthetic `chatcmpl-<ts>` id; the carrier rides as a dedicated
`_provider_meta` chunk (streaming) so a cancelled stream keeps the gen id.

**Phase 3 (trace plane + SSE seam) is implemented.** The converters seam intercepts the `_provider_meta` carrier, tracks
the four lifecycle flags (with `GeneratorExit` + `CancelledError` disconnect detection), and packs everything under one
reserved `final_usage["_provider_trace"]` key (carrier mechanism = widen-the-dict). `server.py` writes a metadata-only
record at both the streaming and non-streaming `on_complete` sites via the shared `record_provider_trace` helper in the
neutral-leaf `provider_trace_logger.py` (gated direct-OpenRouter-only). The plane mirrors the audit log (versioned,
owner-only 0600/0700, strict-dacite read, retention prune) and re-applies the Phase 2 header allowlist at the writer.
The passthrough relay is instrumented identically but **latent** (the gate suppresses its write — it never carries
OpenRouter). probe 2 (`[REMOTE-ABSENT]`) justifies the local-only `unavailable` status. 186 Phase 3 unit + 4 regression
tests green; 2 live-OpenRouter integration tests pass (clean stream + the cancelled-stream incident path). **Remaining:
the Docker-integration commit gate** (`make test-integration` + `make pre-commit` + change-log entry + commit).

**Phase 5** (injection) keeps the **channel correction**: inject under `user` (recognized), not `session_id` (ignored);
routing neutral, so the flag stays default OFF.

## Decisions locked (this card)

| Decision                       | Choice                                                                        | Consequence                                                                                                                                                                                                                                                              |
| ------------------------------ | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `session_id` injection default | **Opt-in config flag, default OFF**                                           | Injection (Phase 5) is gated; the trace plane works without it. Decouples observability from the routing-behavior change.                                                                                                                                                |
| `session_id` granularity       | **`forge_sess_<hash>_<role>`**, fallback `forge_run_<hash>`                   | `root_run_id` is the only id all direct callers share -> right fallback. Human name is hashed, never sent raw.                                                                                                                                                           |
| Trace retention / reset        | **Match audit (14d / 512 MB); NOT in `forge proxy costs reset`**              | Traces are metadata-only diagnostics, not spend truth. One mental model with the audit plane. Chosen once, shared with `proxy_log_hygiene`.                                                                                                                              |
| Action tagger scope            | **Out of scope (documented gap)**                                             | `tagger.py` defaults to `gemini -> litellm_local`, no `provider=` arg; reaching OpenRouter is a separate routing change.                                                                                                                                                 |
| Provider metadata shape        | **Nested optional `ProviderTraceMeta`** on `CompletionResponse`/`StreamEvent` | Lower churn than ~6 flat fields x2 models; keeps synthetic-id namespace separate. (`types.py` has no `extra='forbid'`; `cost_usd` was added the same additive way.)                                                                                                      |
| Trace-write home               | **One shared helper invoked from the proxy `on_complete` seam**               | Only existing shared stream-lifecycle point with `request_id` + run-tree headers in hand. Direct `core.llm` callers populate `provider_meta` but join via the usage ledger, not the proxy trace plane.                                                                   |
| Carrier mechanism (P3)         | **Widen the dict, one reserved key**                                          | `final_usage`/`_OnCompleteCallback` arg widen `Dict[str,int]`→`Dict[str,Any]`; all trace payload quarantined under `final_usage["_provider_trace"]`. Mirrors `reported_cost_micros`; callback arity stable; one call site (`server.py`).                                 |
| Shared-helper home (P3)        | **`record_provider_trace` in the neutral-leaf `provider_trace_logger.py`**    | `server.py` lazily imports `passthrough`; a helper in `server.py` imported by `passthrough.py` would invert that and risk a cycle. The leaf is imported by both — no cycle. Gate + `local_usage_status` derivation live there.                                           |
| Passthrough mirror (P3)        | **Forward-wired, latent today**                                               | Instrumented with the same four flags + the one shared helper, but the OpenRouter gate suppresses its write (passthrough never carries OpenRouter). Tested both ways (flags computed; gate suppresses). Avoids a second writer for a future passthrough-routed provider. |
| Plane scope (P3)               | **Direct-OpenRouter-only (`provider_name == "openrouter"`)**                  | Covers the direct `openrouter-openai` incident path the probes exercised. Gateway-routed OpenRouter (LiteLLM→OpenRouter) is **out of scope** — documented, not silently excluded. Broadening later keys off `provider_meta.selected_provider`, not `provider_name`.      |

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

- [x] **Type** (`src/forge/core/llm/types.py`, `__init__.py`): added `ProviderTraceMeta(BaseModel)`, all 7 fields
  optional/defaulted; `provider_meta: ProviderTraceMeta | None = None` on both `CompletionResponse` and `StreamEvent`;
  exported (import + `__all__`). - *Verified*: both models construct without it; all-`None` meta valid; full unit suite
  (6119) stays green (`test_types.py` additions).
- [x] **Non-streaming populate** (`openai_compat.py`): added `provider_trace_meta(response, provider)` — body `id` →
  `provider_response_id`; `provider_generation_id` only when the id is a `gen-…` (probe 1, so plain `chatcmpl-` ids
  don't masquerade as generation ids); `selected_provider` from the body `provider` field / `model_extra`. Wired into
  `openai_response_to_completion`. - *Verified*: OpenRouter completion carries `provider="openrouter"` + gen id; LiteLLM
  carries `provider="litellm"`, no generation id.
- [x] **Streaming populate** (`openrouter.py`): captures the **first-seen** non-null `chunk.id` (set-once) into a local
  and **emits `provider_meta` on the first content/tool event** (not only the terminal usage/`response_end`). Emitting
  early is what lets a stream *cancelled before the final usage chunk* — the incident case — still surface its id; the
  terminal events still carry it for the clean / no-content path. An `isinstance(str)` guard means a bare-mock chunk id
  yields no meta (and keeps existing MagicMock streaming tests green). - *Verified*: stream emits meta on the first
  `text_delta`/`tool_call_delta`, a later id does not overwrite, non-string id → `provider_meta=None`
  (`test_openrouter.py`).
- [x] **Responses streaming fallback carries meta** (`litellm.py`): GPT-5 has no real streaming, so `stream()` falls
  back to one non-streaming Responses call and re-emits synthetic events; those events now pass
  `provider_meta=response.provider_meta` (text_delta, tool_call_delta, usage, response_end) instead of dropping it (R2).
  \- *Verified*: all four synthetic events carry the completion's `provider_meta`
  (`test_litellm_gpt5.py::TestResponsesStreamingFallbackProviderMeta`).
- [x] **Header allowlist** (`openai_compat.py`, shared): `provider_trace_headers()` (tiny exact-name allowlist:
  `x-request-id`, `x-generation-id`, `x-litellm-call-id`, `x-litellm-model-id`) and `merge_provider_headers()` live in
  `openai_compat` so the LiteLLM and **direct OpenRouter** paths share one allowlist source. `litellm.py`
  `_merge_response_metadata` delegates to it; the **direct `openrouter.py` non-streaming path now switches to
  `with_raw_response.create()`** (`raw.parse()` + `raw.headers`) so it populates `provider_meta.headers` too — the prior
  "deferred" gap (R3) is closed. Streaming has no raw-response handle → `headers=None`. - *Verified*: only allowlisted
  names+values kept; auth/cookies dropped; direct non-streaming OpenRouter carries `headers`; streaming `headers=None`
  (`test_openai_compat.py`, `test_openrouter.py`, `test_litellm_cost.py`).
- [x] **Adapter carry-through** (`proxy/client_adapter.py`): widened `AdapterProviderType` to include `"openrouter"`,
  which made the `get_client(provider=...)` `# type: ignore` provably redundant — **removed** it (mypy + pyright clean).
  `provider_meta` rides as a typed carrier (`ProviderTraceMeta.model_dump(exclude_none=True)`) under `_provider_meta`:
  the non-streaming dict, and on the streaming path a **dedicated metadata-only carrier chunk** (`choices=[]`) emitted
  once the instant the first event carrying `provider_meta` arrives — *not* nested in the terminal usage chunk. The
  dedicated chunk is what guarantees a cancelled stream's gen id reaches the Phase 3 seam before any abort (R1). The
  synthetic `chatcmpl-<ts>` id stays separate from `provider_generation_id`. - *Verified*: carrier chunk present and
  emitted at most once; a stream ending before its usage chunk still delivers the carrier; synthetic id stays `!=`
  `provider_generation_id`; full unit suite green (`test_client_adapter.py`). (Reconstruction into `ProviderTraceMeta` +
  the converters read happen at the Phase 3 trace seam.)

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

- [x] **Lifecycle flags at the one seam** (`src/forge/proxy/converters.py`): `convert_openai_to_anthropic_sse` now
  tracks `_stream_started` (after `message_start`), `_first_chunk_seen` (first **user-visible** text/tool
  `content_block_start` — the `_provider_meta` carrier is excluded), `_final_usage_seen` (usage-parse block), and
  intercepts the `_provider_meta` carrier chunk (stashes into `_provider_trace_meta`, `continue`s — never yielded, and
  the prior spurious empty-`choices` WARNING is gone). Disconnect caught with
  `except (asyncio.CancelledError, GeneratorExit):` (both are `BaseException`, so `except Exception` misses them) → sets
  `_client_disconnected=True`, re-raises; the `finally` packs
  `final_usage["_provider_trace"] = {"provider_meta", "lifecycle"}` and fires `on_complete` exactly once.
  `_OnCompleteCallback` first arg + `final_usage` widened `Dict[str, int]`→`Dict[str, Any]` (mirrors the
  `reported_cost_micros` precedent; arity unchanged). - *Verified*: carrier emits nothing and leaves
  `first_chunk_seen=False`; `CancelledError` **and** `GeneratorExit` both set `client_disconnected`, propagate, fire
  `finally` once; clean stream → `first_chunk_seen/final_usage_seen=True`, `client_disconnected=False`; **carrier-only
  then disconnect** (the incident path) → `provider_generation_id` present, `first_chunk_seen=False`,
  `final_usage_seen=False`, `client_disconnected=True`; the **delayed id-then-name tool path** also flips
  `first_chunk_seen` (a provider that streams the tool id before its name still emits a visible `content_block_start`),
  while the id-only buffer chunk emits nothing and leaves it unset (`tests/src/proxy/test_converters_lifecycle.py`, 7
  tests).
- [x] **Mirror in passthrough** (`src/forge/proxy/passthrough.py`): `_stream_opened_upstream` now tracks
  `stream_started`/`client_disconnected` (via `except (asyncio.CancelledError, GeneratorExit):` on the relay) and reads
  `saw_content`/`saw_final_usage` off the `_UsageAccumulator` (`_merge` sets them), funneling into the **same**
  `record_provider_trace(...)` from the neutral-leaf `provider_trace_logger.py` — **not** a second writer, and **not**
  imported from `server.py` (no cycle). `forward()` threads a `provider_trace_ctx`. - *Verified*: passthrough computes
  the four flags and calls the one shared helper; with `provider_name != "openrouter"` the gate suppresses the write
  (forward-wiring is **latent** today — passthrough never carries OpenRouter); no `from forge.proxy.server import` in
  `passthrough.py` (4 mirror tests in `tests/src/proxy/test_passthrough.py`).
- [x] **Trace plane writer/reader** (`src/forge/proxy/provider_trace_logger.py`, new — modeled on `audit_logger.py` /
  `ledger.py`, **not** `cost_logger.py`): `PROVIDER_TRACE_SCHEMA_VERSION=1`; own `_lock` + `_warned_newer_schema` latch;
  `_traces_dir()=get_forge_home()/"providers"/"openrouter"/"traces"` (three levels); shard `{YYYY-MM}_{pid}.jsonl`.
  `ProviderTraceRecord` adds `proxy_id`/`mapped_model` (card §4) and `request_mode` ∈ `{streaming,non_streaming}` beside
  the Phase 2 `ProviderTraceMeta`-derived fields; metadata-only (no body/prompt/completion). `write_provider_trace`
  **re-applies** the Phase 2 allowlist (`provider_trace_headers` lazily imported from `openai_compat` — verified
  acyclic) as defense-in-depth, `open_secure_append` under `_lock`, chmods all three dir levels 0700, best-effort.
  `record_provider_trace` (the **shared** helper both `server.py` and `passthrough.py` call) gates
  `provider_name != "openrouter"`, derives `local_usage_status`. `read_provider_traces` strict-dacite +
  skip-newer-schema-warn-once; `prune_provider_traces` cloned from `prune_audit_logs`. - *Verified*: 0600 files under
  0700 three-level dirs; newer-schema skipped with exactly one warning; unknown field rejected (strict); non-object line
  skipped; forced `OSError` swallowed; **header-bypass guard** — a `provider_meta` carrying `authorization`/`x-api-key`/
  `cookie` persists only allowlisted names (`tests/src/proxy/test_provider_trace_logger.py`, 18 tests).
- [x] **Write from the proxy** (`src/forge/proxy/server.py`): `create_message` captures
  `forge_session, forge_command = _forge_session_command(raw_request)` beside `_forge_run_ids`. `_on_stream_complete`
  unpacks `usage["_provider_trace"]` and, **after** `_calc_and_log_cost`, calls
  `record_provider_trace(request_mode="streaming", proxy_id=PROXY_ID, mapped_model=actual_model_id, ...)`; the
  non-streaming block calls it with `request_mode="non_streaming"`, lifecycle trivially complete,
  `provider_meta=openai_response.get("_provider_meta")`. `timeout_seen=False` always — the proxy sees only its own peer
  disconnect, never the parent's `subprocess.run` timeout (documented inline). - *Verified*: OpenRouter stream
  disconnecting before final usage →
  `stream_started/first_chunk_seen=True, final_usage_seen=False, client_disconnected=True, local_usage_status="unavailable"`;
  clean → `final_usage_seen=True, status="available"`; the cost record schema is unchanged; a litellm/gateway route
  writes **no** trace — `test_litellm_gateway_route_writes_no_trace_by_design` asserts the suppression is deliberate
  scope, not an accidental miss (`tests/src/proxy/test_server_provider_trace.py`, 3 tests).
- [x] **Config + prune** (`src/forge/config/schema.py`, `provider_trace_logger.py`, `server.py`): `ProviderTraceConfig`
  (`retention_days=14`, `max_total_mb=512`; bool-rejecting int validation + `_coerce_provider_trace_config` with
  `_reject_unknown_keys`) nested into **both** `ProxyConfig` **and** `ProxyInstanceConfig` (the two ProxyConfig-shaped
  dataclasses — parity with `audit`; each `__post_init__` coerces its own field). `prune_provider_traces` cloned from
  `prune_audit_logs`, wired into `_maybe_prune_provider_traces()` (with a `_provider_traces_pruned` latch) called from
  `_ensure_runtime_state` beside `_maybe_prune_audit_logs`. - *Verified*: config rejects unknown keys + non-bounded/bool
  values, defaults 14/512; prune deletes over `retention_days` and oldest-first over `max_total_mb` preserving
  0600/0700; prune invoked once per process (`tests/src/config/test_schema.py`, 6 provider_trace tests).
- [x] Design-doc sync: `design.md §3.14` now names the **fourth** provider-trace plane (lifecycle/correlation under
  `providers/openrouter/traces/<month>_<pid>.jsonl`, written at the proxy `on_complete` seam, joined by `request_id` +
  run-tree ids, **not** wiped by `forge proxy costs reset`, direct-OpenRouter-only) + a `provider_trace:` yaml block;
  `design_appendix.md` gains `### A.14 Provider-trace plane schema` (cloned the §A.13 ledger-schema style — path/owner
  table, field-groups table, metadata-only/direct-only/`timeout_seen`/`first_chunk_seen` semantics, run-tree join note).
  **`docs/end-user/proxy.md` is deferred to Phase 4** — it lands with the `forge provider trace` read CLI (no
  user-facing surface exists yet to document).

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

- [x] **Command-core op** (`src/forge/core/ops/provider_trace.py`, `__init__.py`): `list_provider_traces` /
  `show_provider_trace` / `explain_provider_trace` return frozen DTOs, raise `ForgeOpError`, take `ExecutionContext`
  (shape of `core/ops/proxy.py`). `explain` builds a `ProviderTraceExplanation` DTO (left-Forge, route, provider
  session/generation id, stream lifecycle, cost-unavailable-vs-zero) from local records only; the pure
  `render_explanation_lines` plain-text contract is shared by the terminal + `%` surfaces. Cost enrichment is a bounded
  `read_cost_logs(trace_ts ±5m)` lookup by `request_id` for the cost record's `confidence`. - *Verified*: ops are
  Click/print-free; never call a remote endpoint; 11 tests in `tests/src/core/ops/test_provider_trace.py`.
- [x] **CLI group** (`src/forge/cli/provider.py`, `cli/main.py`): `provider` group orients; nested `trace` group;
  `list`/`show`/`explain` leaves; `--json` shapes are bare-array (list) / single-dict (show) / `asdict(exp)` (explain)
  via `dataclasses.asdict()`; errors via `print_error_with_tip` + exit 1. `list` filters: `--session` (label),
  `--root-run-id` (exact), `--period today|week|month|all` (default today), `--limit` (50). **Decision (Q1 unanswered):
  `explain` is route-only / trace-derived — no credential-source lookup; the "never print a key" guardrail holds
  trivially (the record has no credential field). Credential-source bucket remains an easy additive extension.** -
  *Verified*: bare groups print usage (exit 2, matching `forge proxy`); `--json` parity; no key value printed; 11 tests
  in `tests/src/cli/test_provider_trace.py`.
- [x] **Direct commands `%provider trace list|show|explain`** (scope addition — user chose to include now): mirrors
  `%proxy audit`, read-only, `list` capped at 10; reuses the same ops + `render_explanation_lines` (byte-identical to
  the terminal narrative). Wired in `cli/hooks/{direct_commands,commands}.py` + help; scope policy in
  `cli_reference §2`. - *Verified*: 6 tests in `tests/src/cli/hooks/test_direct_commands_provider.py`.
- [x] Docs sync: `docs/cli_reference.md` Provider-trace table + `%` scope/commands; `docs/end-user/proxy.md` new
  "Provider trace" section (Day-1 rule); `design.md §3.14` + `design_appendix.md §A.14` read-surface note.

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
