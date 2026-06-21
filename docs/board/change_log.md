# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board-contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
- Keep entries short. Do not list every file unless the file list is the point of the work.
- Use newest-first order so active work stays near the top.
- When this file approaches the documentation size limits, compact the oldest entries at the bottom into a dated summary
  that preserves decisions, verification, and deferred items. Archive detailed old entries only if the summary is still
  too large.
- Check size before long sessions or when the file feels slow to scan:

```bash
wc -l docs/board/change_log.md
./scripts/count-tokens.py --model <agent-model> docs/board/change_log.md
```

## Entries

> Format: `## YYYY-MM-DD`, then `### Phase X.Y: Short Title`, with `**Goal**:`, `**Key changes**:` as bullets, and
> `**Verification**:`. Use newest-first order. See `docs/developer/board-contract.md` "Change Log Policy" for the full
> spec.

## 2026-06-20

### openrouter_user_direct_callers: unified provider-`user` toggle + direct-caller injection

**Goal**: Extend OpenRouter `user`-field session grouping (shipped for the proxied path) to Forge's direct `core.llm`
callers, governed by a single global toggle instead of a per-proxy one — chosen on the principle *product experience
drives architecture* (one switch over two per-scope homes).

**Key changes**:

- **Global toggle**: `provider_trace.inject_provider_user` (default off) now lives in `~/.forge/config.yaml`
  (`RuntimeProviderTraceConfig`); `forge config set/edit` gained nested-section support via a `_nested_sections()`
  registry. Loader is fail-open (bad subtree resets only `provider_trace`); write surfaces (`set`/`edit`) fail-closed on
  unknown subkeys.
- **Proxied gate repointed**: `_inject_provider_user_enabled()` reads `get_runtime_config().provider_trace` (same
  pattern as `auth_ignore_env`); `proxy.yaml`'s `provider_trace` is now retention-only.
- **Sidecar**: mounts `~/.forge/config.yaml` read-only so in-container proxied forks read the same toggle.
- **Direct injection**: `with_openrouter_user` + `resolve_direct_provider_user(role)` (`core/usage/correlation.py`)
  wired into plan-check (role `plan-check`, OpenRouter-gated) and transfer curation (role `transfer-curate`). Both
  derive the id with the same `derive_provider_session_id` as the proxied path, so a run's direct and proxied OpenRouter
  calls group identically account-side. Tagger excluded by design (local LiteLLM).

**Breaking change (research preview)**: the per-proxy `proxy.yaml` `provider_trace.inject_provider_user` (and its legacy
`inject_openrouter_user` alias) is removed. A stale key still loads but is **ignored** with a one-time relocation
warning. Migration: `forge config set provider_trace.inject_provider_user=true` in `~/.forge/config.yaml`. Retention
keys (`retention_days`, `max_total_mb`) stay proxy-owned.

**Verification**: 432 tests green across all touched files (runtime-config, config CLI, schema, routing invariants,
sidecar, correlation, plan-check, transfer, 2 regressions); `mypy` + `pyright` clean on every changed source and test
module. Docs synced (design §3.14, appendix §A.14, end-user config.md + proxy.md). Sidecar integration run passed in
Docker (`test_audit_plumbing.py`: config.yaml mounted read-only + in-container `get_runtime_config()` reads the toggle).
`make pre-commit` clean.

### backend_remote_reconciliation PR 2: `forge backend reconcile` (single-id MVP)

**Goal**: Ship the MVP of backend remote reconciliation -- join one local downstream trace to one remote account-side
record for any backend with a registered remote adapter. OpenRouter is the first adapter.

**Key changes**:

- New `src/forge/backend/remote/` package: a `BackendRemoteAdapter` protocol + adapter registry (presence in the
  registry, not a `ModelSourceCapabilities` flag, is what makes a source remote-reconcile capable), generic
  metadata-only DTOs (`RemoteCapability`, `RemoteRecord`), and `RemoteAdapterError`/`RemoteAdapterNotFoundError`.
- `OpenRouterRemoteAdapter` (narrow `httpx` client) hits `GET /api/v1/generation?id=...` with the normal key, whitelists
  metadata only (never `/generation/content`), normalizes `total_cost` USD -> micros, and maps every HTTP/network result
  to a `RemoteRecord(outcome=...)` (200->found, 404->not_found, 401/403->not_authorized, else->unavailable; missing key
  -> not_authorized via a no-HTTP pre-check).
- New op `core/ops/backend_reconcile.py` (`reconcile_generation` + `render_reconcile_lines`): comparative bucket
  taxonomy `joined`/`remote`/`missing-remote`/`not-queryable`; downstream reads scoped by `backend_id`; local and remote
  cost/tokens kept separate with provenance; remote/network failures are renderable data, never raised.
- New CLI leaf `forge backend reconcile <source-id>` (`--request-id`/`--remote-id`/`--json`/`--timeout`), and docs
  (cli_reference, design_appendix §A.14, end-user/proxy.md). Windowed account-wide activity/analytics (management key,
  `local`/`missing-local` buckets) stays a declared follow-on -- the protocol already carries the window seam.
- Review hardening (from a 32-agent adversarial review, 21 confirmed findings): total numeric coercers + a parse net so
  a malformed-but-parseable 200 body (NaN/Infinity/overflow/bool, default `json.loads` accepts these) maps to
  `unavailable` instead of crashing the CLI with a traceback (the error-vs-data invariant); empty-string ids normalized
  so the xor guard and mode dispatch agree; template aliases resolved to canonical; a 200 error-envelope ->
  `unavailable`; render predicate includes `local_output_tokens`; CLI catches `RemoteAdapterError`; tip wording
  `Use --flag`.

**Verification**: `tests/src/core/ops/test_backend_reconciliation.py` + `tests/src/cli/test_backend_reconcile.py` +
`tests/src/backend/remote/test_openrouter_remote.py` -> 52 passed (14 added for the review fixes, incl. a replaced
tautological content-leak assertion); broader `tests/src/{backend,core/ops,cli}` -> 2322 passed; `make pre-commit` clean
(mypy + pyright).

## 2026-06-19

### backend_remote_reconciliation PR 1: generalize provider-trace observability over any backend

**Goal**: Resume the paused `openrouter_remote_reconciliation` work as the provider-generic
`backend_remote_reconciliation` card (OpenRouter becomes the first adapter, not the feature). PR 1 removes the last
OpenRouter coupling from the provider-trace / provider-user-grouping surfaces so the upcoming `forge backend reconcile`
feature builds on a backend-neutral base.

**Key changes**:

- Renamed the source capability `openrouter_user_grouping` -> `provider_user_grouping` (`backend/sources.py`) and the
  config key `provider_trace.inject_openrouter_user` -> `inject_provider_user` (`config/schema.py`).
- Removed the two `provider_name == "openrouter"` fallbacks: provider-trace writes and the `user`-field injection are
  now purely source-capability gated by `backend_id`. Renamed `_openrouter_user_value` -> `_provider_user_value` and
  `_inject_openrouter_user_enabled` -> `_inject_provider_user_enabled`, and dropped the now-dead `provider_name` param
  from `record_provider_trace` and all call sites + the passthrough ctx dict.
- A proxy with no `proxy.source` now writes no trace / injects no user (the fallback's only beneficiary), surfaced once
  via a dedicated `_warned_absent_backend_source` INFO latch in `server.py`.
- `proxy.yaml` is user-owned config (system boundary): the old `inject_openrouter_user` key is honored as a
  warn-and-degrade alias (new key wins if both set), not a hard reject.
- Genericized provider-coupled comments/docstrings and normative docs (design §3.14, appendix §A.14, cli_reference,
  end-user/proxy.md incl. an alias note). Board: moved `paused/openrouter_remote_reconciliation` ->
  `doing/backend_remote_reconciliation`, reframed card/checklist (two-PR plan, superseded Phase 0 decisions), and
  updated the telemetry epic's member table + the `openrouter_user_direct_callers` references.

**Verification**: `uv run pytest` over the renamed proxy/config/cli/ops surfaces + the new
`test_bug_provider_trace_inject_alias.py` regression (185 passed); `make pre-commit` clean (mypy + pyright); live
`tests/integration/proxy/test_provider_trace_e2e.py` (2 passed) confirms the real OpenRouter proxy still writes traces
via the `source: openrouter` capability gate.

### unified_backend follow-up: custom templates preflight credentials from declared source

**Goal**: Fix a credential-preflight gap left by `unified_backend` — user-named proxy templates silently skipped
credential checks because lookups keyed on the shipped-only `TEMPLATE_ENV_VARS` map, so a custom template launched
without its API key and failed at runtime instead of failing fast at start.

**Key changes**:

- `required_env_vars_for_template()` (`core/auth/template_secrets.py`) reads a template's declared `proxy.source` and
  resolves required env vars from the model-source catalog, falling back to `TEMPLATE_ENV_VARS` when no source is
  readable/declared. `credentials_for_template`, `get_secrets_for_template`, and proxy-start
  `_ensure_template_credentials` route through it.
- Read hardening: an existing-but-unreadable template (permissions/IO) or invalid YAML now logs at WARNING instead of
  degrading silently; an unknown name stays silent (`FileNotFoundError`). Still best-effort — returns the safe fallback,
  never raises into callers.
- `credentials_for_template(..., required_vars=)` reuses the resolved list on the proxy-start failure path, removing a
  redundant template read.
- AGENTS.md: added backend-source / telemetry / provider-trace operator-verification guidance.

**Verification**: New regression `tests/regression/test_bug_custom_template_source_credentials.py` plus 5
`test_template_secrets.py` unit cases (declared-source resolve, no-source/unknown-name fallback, unreadable-warns,
invalid-yaml-warns); `tests/src/{proxy,core/auth,backend,sidecar}` + regression green (156 focused); mypy clean;
`make pre-commit` clean.

### unified_backend closeout: shared local-instance display + review follow-up

**Goal**: Land the PR #39 review follow-up and close the `unified_backend` card.

**Key changes**:

- `forge backend list`/`show` now mark a local LiteLLM runtime instance shared across sources (one `litellm-4000`
  process backs Gemini + OpenAI under the shipped default config); `--json` carries `runtime_instance.shared_with`. The
  matching heuristic stays display-only and never feeds downstream telemetry `backend_id` (still derived from
  `proxy.source`).
- Proxy `_backend_source_id` warns once when `proxy.yaml` carries an unrecognized `source` (warn-and-degrade; user-owned
  config is a system boundary), instead of silently passing an unknown `backend_id` into telemetry.
- Added a multi-key backend-list test mirroring the shipped default (the case the prior gemini-only fixture masked) plus
  warn-once server coverage; documented the shared local LiteLLM process model in `proxy.md` and design appendix §A.2.1.
- Card moved `doing/ -> done/`; telemetry epic member table updated (`unified_backend` done).

**Verification**: backend CLI + new server suite (22) and proxy/backend/telemetry/usage suites (175) green;
`make pre-commit` clean (mypy + pyright). Shipped via PR #39 (squash `ab690ac9`).

## 2026-06-18

### unified_backend: model-source catalog and downstream source attribution

**Goal**: Make local and remote model sources one listable backend/source axis and key downstream telemetry on a
canonical catalog id.

**Key changes**:

- Added a built-in `ModelSource` catalog for local LiteLLM, remote LiteLLM, OpenRouter, Anthropic passthrough, and
  direct-runtime sources, with endpoint, credential, lifecycle, and capability metadata.
- Moved proxy templates to `proxy.source`, deriving endpoint/auth/lifecycle facts from the catalog while keeping runtime
  backend instances separate from static source definitions.
- Expanded `forge backend list/show/test-auth` around source ids; remote sources have intentional no-lifecycle behavior
  and local lifecycle still resolves to existing LiteLLM adapters/ports.
- Added downstream `backend_id` attribution across proxy cost, audit, provider trace, and direct usage emitters while
  preserving `source_id`/`source_kind` as writer-origin metadata.
- Replaced OpenRouter-specific provider-trace and `user` injection gates with source capabilities.

**Verification**: Focused unit/regression acceptance slice passed 526 tests; backend integration slice passed 11 tests;
`make pre-commit` clean.

### upstream_downstream_ledgers closeout: two-pane activity + upstream boundary coverage

**Goal**: Finish two-pane `forge activity` and close non-engine upstream outcome gaps.

**Key changes**:

- Extracted shared measurement resolution for proxied/direct/self-reported paths.
- Routed policy-engine writes through `record_upstream_operation(...)` and added non-engine operation outcomes.
- Reworked `forge activity` into Operation outcomes and Model calls panes with clean-break JSON and bounded rollups.
- Kept `render_summary_line(...)` in lockstep and updated design, user, CLI, QA, and board docs.

**Verification**: `mypy` clean for `measurement.py`; targeted suites passed 434/237/517 tests; integration closeout
passed 36 tests; `make pre-commit` clean.

### upstream_downstream_ledgers: telemetry clean cut and cap-safe migration

**Goal**: Re-cut Forge telemetry toward downstream model-attempt evidence and upstream operation outcomes without
silently resetting spend caps during the path move.

**Key changes**:

- Added `~/.forge/telemetry/downstream/` and `~/.forge/telemetry/upstream/` JSONL planes. Proxy cost, audit/drift/
  mutation, provider lifecycle evidence, direct `core.llm`, direct `claude -p`, and Codex usage now write downstream
  attempt records; policy evaluation outcomes write upstream records.
- Default upstream volume is `non_success`; `upstream_event_volume=all` enables success/cached-allow operation logs.
- Spend caps now persist `telemetry/caps/<proxy_id>.json` and bootstrap from
  `max(cap_state, downstream logs, legacy cost logs)`, so clean-cut migration and dropped best-effort telemetry writes
  do not reset monthly caps to zero.
- `forge proxy costs reset` now wipes old cost logs, new upstream/downstream telemetry, cap state, audit sidecar state,
  usage events, and derived status-line caches; sidecar proxy launches mount `~/.forge/telemetry/` rw.
- Provider trace reads now project downstream attempt fields, and `forge proxy costs show --by-verb` derives attribution
  by joining downstream requests to usage run ids instead of writing new `costs/verbs` shards.

**Verification**: Focused telemetry/proxy/policy/activity/sidecar suite green (264 tests), provider-trace CLI/core/
regression suite green (32 tests), direct/provider metadata regression coverage added, ruff clean on touched Python and
tests.

## 2026-06-16

### proxy_log_hygiene: reviewer follow-ups (no-plaintext leaks + CLI/create completeness)

**Goal**: Close five defects a reviewer found against the shipped card, all verified against code before fixing.

**Key changes**:

- **No caller content in stream logs** (`proxy/converters.py`): 8 log sites that emitted completion text, tool args,
  file paths (buffered `Read` close-event `partial_json`), or dumped whole malformed chunks/deltas now log metadata only
  (lengths / key-names / indices). Full content stays behind the `stream_chunks` opt-in dump.
- **stop_sequences plaintext leak** (`proxy/utils.py`): `_redact_body_for_log` listed `stop_sequences` (arbitrary caller
  text) in `_SAFE_KEYS` and copied it verbatim -> now `{"redacted": True, "count": N}`. Fixes BOTH the
  request-diagnostics and the shared audit plane.
- **CLI int coercion** (`cli/proxy.py`): `forge proxy set` now int-casts `logging.requests.max_file_mb` and
  `stream_chunk_max_bytes` (previously stayed strings and failed schema validation).
- **Third construction site** (`proxy/proxy_orchestrator.py`): `create_proxy_file` now copies template-defined
  `provider_trace` + `logging` onto the new `ProxyInstanceConfig` (was the same drop-the-block bug as Slice 0, latent
  since no shipped template carries them).

**Verification**: 4 new/extended regression tests (converter content-free logs incl. buffered-tool close event;
stop_sequences canary on redactor + on-disk shard; CLI int round-trip; template-block survival at create). Full unit +
regression green; `make pre-commit` clean. Two adversarial review rounds (verify-each-finding): round 1 found the four
above; round 2 found the 8th converter leak site; a third exhaustive enumeration of every converter log call confirmed
no remaining caller-content interpolation.

### proxy_log_hygiene: quiet defaults + bounded redacted request diagnostics (slices 0-5)

**Goal**: Cut low-value proxy log volume (poll spam, per-chunk dumps) while adding bounded, redacted request diagnostics
aligned with the audit no-plaintext policy — and fix a folded-in loader bug that silently dropped `provider_trace`.

**Key changes**:

- **Slice 0 (folded loader bug)** — `config/loader.py`: both proxy-config hops (`load_proxy_instance_config_from_dict`,
  `_proxy_instance_to_forge_config`) silently dropped the `provider_trace` block (and would have dropped the new
  `logging` block). Now wired through both. Regression: `test_bug_provider_trace_loader_dropped.py`.
- **Slice 1 (quiet polls)** — `proxy/server.py`: successful completions log at DEBUG; INFO reserved for `status >= 400`
  or slow polls (`elapsed > _SLOW_POLL_LOG_S = 1.0s`). Slow-poll visibility is new behavior (none existed).
- **Slices 2-3 (stream logging)** — `proxy/converters.py` + `proxy/passthrough.py`: per-chunk dumps now require opt-in
  AND DEBUG (off even at `log_level=debug`), truncated via `smart_format_str`. Shared `format_stream_lifecycle_summary`
  (metadata-only: outcome + chunk count + flags) replaces the per-stream INFO bookends — clean stream = one DEBUG line +
  zero converter INFO; error/disconnect = one INFO. Passthrough now surfaces client disconnects (previously logged
  nowhere).
- **Slice 4 (config)** — `config/schema.py`: per-proxy `logging.requests` (`RequestLogConfig` under `LoggingConfig`),
  strict `__post_init__` + coercers (`body_capture=full` rejected with audit pointer; bool-vs-int; unknown-key reject).
  `proxy/utils.log_request_response` gains a `request_log` param: `metadata` omits bodies, `redacted` reuses the audit
  body redactor (no second sanitizer, no plaintext). `server.py` reads it via a tolerant `_request_log_config()` helper
  (best-effort telemetry; degrades to defaults on a partial config).
- **Slice 5 (retention)** — new `proxy/retention.py::prune_jsonl_shards` (age-then-size, 0 = disable) now backs audit,
  provider-trace, AND request planes (one shared pruner; two byte-identical copies removed). `_active_request_log_shard`
  rotates at `max_file_mb`; per-process startup prune wired into `_ensure_runtime_state`. `cli/logs.py` notes capture
  mode.

**Verification**: 6401 unit + 438 regression green; `make pre-commit` clean. Integration:
`test_proxy_local_litellm_e2e.py` (3, incl. streaming SSE) + `test_provider_trace_e2e.py` (2, incl. cancelled-stream
disconnect) pass on the live-proxy path. Adversarial review (9 agents, 7 dimensions + refute-by-default verify): 0
production defects; 1 confirmed nit (missing direct 0600 assertion) fixed via `test_written_shard_is_owner_only_0600`.
Docs: design.md §7.x, appendix §A.11, end-user `proxy.md`, `cli_reference.md`.

### openrouter_observability Phase 5: OpenRouter `user`-field injection (opt-in, proxied-only)

**Goal**: Close the incident loop upstream — when enabled, proxied direct-OpenRouter requests carry the Forge session
grouping id in the OpenAI-standard `user` field, so a session/fork is recorded in OpenRouter's indexed `/generation`
record for account-side lookup (probe 3: `user` is retained, a custom `session_id` is ignored).

**Key changes**:

- **Config flag** (`config/schema.py`): `ProviderTraceConfig.inject_openrouter_user: bool = False` — field +
  `__post_init__` bool-reject + `_coerce_provider_trace_config` allowlist/constructor (all three durable-state touch
  points, so an existing proxy.yaml carrying the key is not rejected as corruption).
- **Proxied path** (`proxy/server.py`, `proxy/client_adapter.py`): a pure, testable `_openrouter_user_value` helper
  gates on `provider == "openrouter"` + the flag, prefers the already-validated `X-Forge-Session` id, and falls back to
  `forge_run_<hash>` (via `derive_provider_session_id`) when only run identity exists. It sets a `_forge_user` carrier
  (mirroring `_user_agent`); the adapter forwards it into `extra["openai"]["user"]` on both stream + non-stream, which
  `build_chat_completion_kwargs` merges to a **top-level** `user` kwarg — the verified channel, not `extra_body`.
- **Tagger gap** (`core/reactive/tagger.py`): documented (not silently no-op'd) — it routes via local LiteLLM and cannot
  reach OpenRouter, so injection is N/A.
- **Scope decision**: proxied-only. The flag is per-proxy because upstream proxy behavior belongs in per-proxy config
  (`runtime_config`/`~/.forge/config.yaml` owns runtime prefs, not this). The direct-client helper + direct callers
  (plan-check, curation) are deferred to a new `todo/openrouter_user_direct_callers/` card to avoid a second opt-in
  source; no direct-call behavior changes this release.
- **Docs**: `proxy.md` (flag + `/generation` framing), `design.md §3.14` config block + sentence,
  `design_appendix §A.14` injection bullet. No CLI/`%` surface change, so `cli_reference.md` is untouched.

**Verification**: 16 new unit tests (3 config + 4 adapter + 5 server-helper + 2 channel-proof + 2 create_message
wiring), incl. an end-to-end proof that `extra["openai"]["user"]` survives the hyperparam merge to a top-level `user`
kwarg, and a `create_message`-level test that config-ON inserts `_forge_user` before the adapter handoff;
`make test-unit` + scoped proxy integration; `make pre-commit` clean. Last shipped phase of the card.

### openrouter_observability Phase 4: `forge provider trace` read surfaces

**Goal**: Give the metadata-only provider-trace plane (shipped Phase 3) a user-facing read surface so an operator can
run `forge provider trace explain <req>` after a timeout and get a local provenance narrative instead of grepping
shards.

**Key changes**:

- **Command-core op** (`core/ops/provider_trace.py`): UI-agnostic `list`/`show`/`explain` returning frozen DTOs, raising
  `ForgeOpError`, taking `ExecutionContext` — no Click/print, no remote call. `explain` builds
  `ProviderTraceExplanation` from local trace records and answers the incident's five questions (left Forge? route?
  generation/session id? stream lifecycle? cost). Cost provenance is a **bounded** `read_cost_logs(trace_ts ±5m)` lookup
  keyed by `request_id` for the cost record's `confidence` — additive only; the trace already carries
  `reported_cost_micros`. The pure `render_explanation_lines` plain-text contract is shared verbatim by the terminal and
  `%` surfaces (no drift).
- **Terminal CLI** (`cli/provider.py`, `cli/main.py`): `provider` group orients; `trace list|show|explain` leaves;
  `--json` shapes are bare-array / single-dict / `asdict(exp)` via `dataclasses.asdict()`; errors via
  `print_error_with_tip`. `list` filters: `--session` (session-*label*, documented as imprecise), `--root-run-id`
  (exact), `--period today|week|month|all`, `--limit` (50).
- **Direct commands** (`cli/hooks/{direct_commands,commands}.py`): `%provider trace list|show|explain` mirror
  `%proxy audit` — read-only, `list` capped at 10, reusing the same ops + renderer.
- **Decision (card Q1 unanswered)**: `explain` is **route-only / trace-derived** — no credential-source resolution. The
  "never print a key" guardrail holds trivially (no credential field is read). Credential provenance remains an additive
  extension via `proxy_id → template → TEMPLATE_ENV_VARS → resolve_env_or_credential_with_source`.
- **Docs**: `cli_reference.md` (Provider-trace table + `%` scope/commands), `end-user/proxy.md` (new "Provider trace"
  section, board-contract Day-1 rule), `design.md §3.14` + `design_appendix.md §A.14` read-surface note.

**Verification**: 28 new unit tests (11 op + 11 CLI + 6 direct-command), incl. a no-secret-printed assertion and
identical terminal/`%` narratives; full `make test-unit` 6191 passed; `make pre-commit` clean (ruff/black/isort/mypy/
pyright/mdformat/gitleaks). Read-only over existing shards — no new Docker path, so unit coverage is the gate.

### openrouter_observability Phase 3: provider-trace plane + shared SSE lifecycle seam

**Goal**: Persist metadata-only, owner-only provider-trace records at the one shared stream seam so Forge can answer
"what happened to this OpenRouter request?" after a timeout — the incident this card exists for.

**Key changes**:

- **New plane** `src/forge/proxy/provider_trace_logger.py`: versioned (`PROVIDER_TRACE_SCHEMA_VERSION=1`), owner-only
  `0600` shards under `0700` three-level dirs (`~/.forge/providers/openrouter/traces/<YYYY-MM>_<pid>.jsonl`),
  strict-dacite read, retention prune — modeled on the audit log, not the unversioned cost log. The shared
  `record_provider_trace` helper lives here (the neutral leaf) so `server.py` and `passthrough.py` both call it without
  an import cycle; it gates **direct-OpenRouter-only** and derives `local_usage_status` (probe 2 `[REMOTE-ABSENT]` →
  local evidence only). `write_provider_trace` **re-applies** the Phase 2 header allowlist as defense-in-depth.
- **Converter seam** (`converters.py`): intercepts the `_provider_meta` carrier chunk (consumed, never yielded — kills a
  spurious WARNING), tracks four lifecycle flags, catches `(asyncio.CancelledError, GeneratorExit)` to record
  `client_disconnected` and re-raise, and packs all of it under one reserved `final_usage["_provider_trace"]` key
  (carrier = widen `Dict[str,int]`→`Dict[str,Any]`, mirroring `reported_cost_micros`; callback arity unchanged).
  `first_chunk_seen` flips at the first user-visible text **or** tool `content_block_start` — including the delayed
  id-then-name tool path (a provider that streams the tool id before its name); the id-only buffer chunk emits nothing,
  so it correctly leaves the flag unset.
- **Proxy write sites** (`server.py`): both streaming and non-streaming `on_complete` paths write after cost logging,
  carrying `proxy_id`/`mapped_model`/`request_mode` + run-tree/session/command join keys; `timeout_seen=False` always
  (the proxy sees its own disconnect, never the parent `subprocess.run` timeout).
- **Passthrough mirror** (`passthrough.py`): same four flags + the one shared helper, **latent today** (the gate
  suppresses the write — passthrough never carries OpenRouter); forward-wiring for a future provider.
- **Config** (`schema.py`): `ProviderTraceConfig` (`retention_days=14`, `max_total_mb=512`, bool-rejecting) nested into
  both `ProxyConfig` and `ProxyInstanceConfig`; prune wired into `_ensure_runtime_state` (once per process).
- **Docs**: design.md §3.14 now names the **fourth** plane; design_appendix §A.14 adds the `ProviderTraceRecord` schema.

**Verification**: full `make test-unit` 6161 passed; `make test-integration` 393 passed; 2 live-OpenRouter E2E pass —
the clean stream surfaces a real `gen-` id via the carrier and the **cancelled stream** records
`client_disconnected=True, final_usage_seen=False, local_usage_status="unavailable"` with the gen id intact (the
incident, end to end). Regression: metadata-only (no body/prompt/completion field; header-bypass re-filtered) + run-tree
join. `make pre-commit` clean (mypy/pyright/ruff/black/isort/mdformat/gitleaks).

### supervisor_statusline_health: surface frontier-supervisor fail-open (status line + `forge activity`)

**Goal**: Make a silently-failing supervisor visible. In the motivating incident a session's supervisor timed out 24/24
times and failed open to `allow` while the always-on status line still rendered a healthy `SUP`. Surface the fail-open
outcome the usage ledger already records — no new durable-state field.

**Key changes** (whole card, Phases 1–3):

- **Phase 1 (read, throttled)**: `read_supervisor_health(session, since) -> SupervisorHealth` over the usage ledger
  (`command="supervisor"`, newest-first contiguous `status in {error,timeout}` streak, reset on first `success`),
  surfaced via the `forge_cost` throttle (`read_or_compute_session_health`, distinct `fhealth-` cache) and exposed as a
  lazy `RenderContext.supervisor_health`. `forge proxy costs reset` also clears `fhealth-*.json`.
- **Phase 2 (status-line suffix)**: `format_supervisor` appends a posture-preserving ASCII `SUP!N <kind>` suffix
  (`SUP!3 timeout`, `SUP(susp)!2 timeout`, `SUP(off)!4 error`); YELLOW 1–2, RED `>=3` (mirrors `format_spend_cap`).
  `recent_failures==0` is byte-identical to today; a raising reader degrades to posture-only.
- **Phase 3 (`forge activity` detail + closeout)**: generic `CommandUsage.error_kinds` (per-display-kind split of
  `errors`, populated uniformly in `_aggregate_ledger`); shared `_failure_kind` maps `failure_type` to `timeout`/`error`
  (single source with `read_supervisor_health`). `format_failing_open` renders `failing open: N timeout, N error`; the
  `forge activity` Supervisor render appends it (ledger-driven, independent of the decision log) and `--json` carries
  `error_kinds`. `render_summary_line` shows the same breakdown with an explicit `error_kinds`-gated fallback to the
  legacy `"{errors} errors"` so hand-built summaries never drop the count.
- **Scope boundary**: "failing open" is the supervisor formatter's interpretation only — `error_kinds` is generic ledger
  data; a memory-writer/panel error is not relabeled. v1 covers timeout/subprocess fail-opens (the ledger's `status`);
  parse fail-opens (logged `success`), auth fail-opens (no event), and exact cached-allow reset are deferred to
  `upstream_downstream_ledgers`. Docs note the streak-vs-window distinction (`SUP!N` consecutive vs `forge activity`
  window total).

**Verification**: 191 (Phase 1) + 112 (Phase 2) + new Phase 3 cases green — `test_usage_summary.py` (error_kinds
aggregation, `_failure_kind`/`format_failing_open` units, render both policy-present/absent branches, the three
pre-existing hand-built `errors`-only tests stay green via the fallback) and `test_activity.py` (human
`failing open: 2 timeout, 1 error` + `--json` `error_kinds`); status-line suites unchanged. `make pre-commit` clean
(ruff/black/isort/mypy/pyright/mdformat/gitleaks). No integration tier — `forge activity` is a read-only render over the
ledger + manifest. Additive optional fields only; no durable-schema change.

## 2026-06-15

### openrouter_observability Phase 2 review fixes (R1–R3): no metadata lost on the incident path

**Goal**: Close three gaps a review found in the shipped Phase 2 carry-through, all on paths the card exists to trace.

**Key changes**:

- **R1 (high) — cancelled streams keep the gen id**: `openrouter.py` stream now **emits `provider_meta` on the first
  content/tool event** (not only terminal usage/`response_end`), and `client_adapter.py` carries it as a **dedicated
  metadata-only chunk** (`choices=[]`) the instant it first appears. A stream aborted before its final usage chunk — the
  incident — now still delivers `provider_generation_id` to the Phase 3 seam.
- **R2 (medium) — LiteLLM Responses streaming fallback keeps meta**: the synthetic events (text_delta, tool_call_delta,
  usage, response_end) now pass `provider_meta=response.provider_meta` instead of dropping it.
- **R3 (low/med) — direct OpenRouter non-streaming populates headers**: `_make_completion_request` switches to
  `with_raw_response.create()` (`raw.parse()` + `raw.headers`) so the direct path gets allowlisted
  `provider_meta.headers` like the LiteLLM path. The header allowlist (`provider_trace_headers` +
  `merge_provider_headers`) moved to `openai_compat.py` so both paths share one source; the prior "deferred" scope note
  is removed.

**Verification**: +6 unit tests (incident carrier chunk, end-before-usage, Responses fallback meta, direct-path headers,
shared-allowlist merge); full `make test-unit` 6125 passed; mypy + pyright clean; scoped `pre-commit` clean.

### openrouter_observability Phase 2: provider metadata through core.llm (additive ProviderTraceMeta)

**Goal**: Lift the provider/generation id, selected upstream, and allowlisted correlation headers out of raw provider
dicts and carry them to the proxy boundary on an additive, nested `ProviderTraceMeta`, kept separate from Forge's
synthetic `chatcmpl-<ts>` id.

**Key changes**:

- `core/llm/types.py` + `__init__.py`: new `ProviderTraceMeta(BaseModel)` (7 optional fields); `provider_meta` added to
  `CompletionResponse` and `StreamEvent`; exported. Additive — fakes/old providers keep working.
- `openai_compat.py`: `provider_trace_meta()` sets `provider_response_id` from `body.id`, `provider_generation_id` only
  when the id is a `gen-…` (so `chatcmpl-` ids don't masquerade), `selected_provider` from the body `provider` field.
- `openrouter.py` stream: captures the **first-seen** `chunk.id` (set-once, `isinstance(str)` guarded) and attaches it
  to the usage/`response_end` events — first-seen is what survives a cancelled stream (the incident).
- `litellm.py`: tiny exact-name header allowlist (`provider_trace_headers`) + `_merge_response_metadata` populating
  `provider_meta.headers` on the raw-response paths (never auth/cookies). Direct `openrouter.py` header capture deferred
  (it has no `with_raw_response`; body/chunk id already carries the gen id).
- `proxy/client_adapter.py`: widened `AdapterProviderType` to include `"openrouter"` (removed the now-redundant
  `type: ignore`); `provider_meta` carried as a typed `model_dump` under `_provider_meta` (non-streaming) and the usage
  chunk (streaming), mirroring `reported_cost_micros` and kept distinct from the synthetic id.

**Verification**: +25 unit tests across `test_types`, `test_openai_compat`, `test_openrouter`, `test_litellm_cost`,
`test_client_adapter`; full `make test-unit` 6119 passed; mypy + pyright + `make pre-commit` clean. (Reconstruction +
the converters read land at the Phase 3 trace seam.)

### openrouter_observability Phase 1: Forge-owned session ids + X-Forge-Session/Command headers

**Goal**: Mint opaque, path-free provider grouping ids and propagate the hashed session name + command role from
headless spawns to the proxy via two new sanitized, leak-gated headers — the identity foundation later phases join on.

**Key changes**:

- `core/run_id.py`: added `derive_provider_session_id(label, root_run_id, role)` (SHA-256 12-hex; explicit
  `forge_run_<hash(root_run_id)>` fallback when no session label), one `sanitize_label` that canonicalizes all separator
  runs to `_` (so the id suffix and `X-Forge-Command` can't drift), and `is_valid_label`/`is_valid_provider_session_id`
  validators distinct from `RUN_ID_RE`. Header/env-var name constants added.
- `core/reactive/env.py`: `_apply_correlation_headers` stamps `X-Forge-Session` (always emittable via the fallback) +
  `X-Forge-Command` (role only), both added to the Forge-owned strip-set, gated to a proven Forge proxy.
- Headless spawns tag their role + session: `supervisor` (`supervisor.py`), `memory_writer` (`memory_writer.py`),
  `review` (`engine.py`, command-only). Used the existing `run_claude_session(extra_env=...)` pass-through — no
  signature change (the plan's "plumbing gap" was a misread).
- `proxy/server.py`: middleware reads + validates both headers (spoof/over-long → `None`), stores on `request.state`
  before both wire branches; getter `_forge_session_command` added for the Phase 3 trace writer. Headers are never
  forwarded upstream (passthrough allowlist already excludes them — asserted, not re-stripped).
- `design_appendix.md` §A.13: documented the two headers as internal-only correlation, distinct from Phase 5 `user`.

**Verification**: New `test_server_forge_headers.py` (10) + additions to `test_run_id.py`, `test_env.py`,
`test_supervisor.py`, `test_memory_writer.py`; full `make test-unit` 6094 passed; `make pre-commit` clean.

### openrouter_observability Phase 0: live-probe the OpenRouter externals

**Goal**: Pin the live OpenRouter behaviors the card's later phases assume, before any provider-id field is populated.

**Key changes**:

- **Probe harness** (`scripts/experiments/openrouter/`): operator-gated, staged `reproduce.sh` + `lib.sh` +
  scan-and-fail `sanitize.sh` + async/typed `helpers/or_probe.py` + 5 stages + README. Reuses Forge credential
  resolution read-only; metadata-only records (no keys; no raw bodies without `--debug-raw`).
- **Findings** (`phase0-results.md`): the `gen-` id is in `body.id`, the `x-generation-id` header, **and** every
  streaming `chunk.id` (stable) -> streaming `provider_generation_id` is **not** structurally `None` (corrects the card
  hedge); Forge's canonical types drop it today. A stream cancelled after the first chunk is `[REMOTE-ABSENT]` (not
  retrievable via `/generation` or `/activity`), so a local-only trace is justified. On the direct path OpenRouter
  **records the OpenAI-standard `user`** (`[CHANNEL-USER-RECOGNIZED]`) but **ignores a custom `session_id`** -> Phase 5
  channel correction: inject under `user`, not `session_id`. Sticky routing `[STICKY-NEUTRAL]` across both arms
  (recognition is not routing impact) -> no enable recommendation; flag stays opt-in for observability.
- **Bug caught + fixed**: probe 2's first `[REMOTE-PRESENT-GENERATION]` was a false positive -- `_http_get` counted a
  404 JSON error body as "present". Fixed with an HTTP-200 gate (`_generation_present`), an eventual-consistency poll
  (`~23s`; an immediate `/generation` lookup 404s even for completed calls, which index in ~3s), and a completed-call
  baseline control that only allows `[REMOTE-ABSENT]` when the control indexes while the aborted id does not.
- **Review fixes** (post-run): `sanitize.sh` now **requires** GNU sed/grep (BSD silently no-ops `\b`, risking a
  false-clean secret scan); probe 3 recognition now polls the indexed `/generation` record (`_poll_generation_body`) --
  the polled re-run **flipped** `[CHANNEL-UNVERIFIABLE]` to `[CHANNEL-USER-RECOGNIZED]` (the un-polled lookup had masked
  a real recognition); `_routing_verdict` now spans **both** sticky arms so a `user` divergence can't hide behind a
  neutral `session_id`.

**Verification**: Adversarial workflow (3 independent agents) confirmed the false positive and audited every probe for
the bug class. Helper offline-tested (status gate + interleaved poll + both-arm routing verdict). Operator re-ran probes
1-3: probe 1 `[GENID-IN-STREAM-CHUNK]`, probe 2 `[REMOTE-ABSENT]`, probe 3 `[CHANNEL-USER-RECOGNIZED]`. Pre-commit clean
on all changed files (ruff/black/isort/mypy/pyright/mdformat/gitleaks); `sanitize.sh` OK. All four probes settled; Phase
0 ships no `src/` change.

### supervisor_launch_controls: launch-time cascade parity + reasoning effort across all `claude -p` subprocesses

**Goal**: Give `forge session fork/start --supervise` the tier-1 cascade knobs `forge policy supervise` already had, and
add a per-caller reasoning-effort lever to every Forge-spawned `claude -p` subprocess (no global default).

**Key changes**:

- **Cascade parity**: `fork` and `start` gained `--cascade`/`--checker-model`/`--checker-provider` (all require
  `--supervise`). Launch-time `--cascade` sets the flag only; the runtime hook escalates to the frontier when no plan
  exists yet (asymmetric with `policy supervise --cascade`, which resolves the plan eagerly).
- **Shared checker helpers**: extracted `CHECKER_PROVIDER_CHOICES`, `normalize_checker_provider_arg`,
  `validate_checker_model`, and `apply_checker_options` into `policy/semantic/supervisor.py` (Click-free); consolidated
  the duplicate provider normalizer in `plan_check.py` to one source.
- **Two effort vocabularies** (kept distinct): `claude --effort` = `low/medium/high/xhigh/max` (`max` Claude-only),
  validated by new top-level leaf `core/effort.py`; core.llm `ReasoningEffort` = `none/low/medium/high/xhigh` (`none`
  checker-only), validated in `core/llm/types.py`. `session/models.py` keeps a drift-guarded inline mirror to stay
  import-light.
- **Two argv builders learn `--effort`**: `run_claude_session` (central `-p` builder) appends `--effort` after `--model`
  and **fails loud** if an older `claude` rejects it (no silent rerun-at-default, unlike the `--output-format` retry);
  `review/engine.py:_prepare_worker` appends it to the fan-out argv.
- **Per-caller wiring**: `SupervisorConfig.supervisor_effort`/`.checker_effort`, `MemoryWriterConfig.effort`,
  `TeamSupervisorConfig.effort`; threaded into the supervisor frontier, tier-1 checker (`ModelHyperparameters` + effort
  in the plan-check cache key), memory writer, shadow curation, team supervisor, and the workflow fan-out. CLI flags:
  `--supervisor-effort`/`--checker-effort` on fork/start/`policy supervise`, `--supervisor-effort` on the one-shot
  `policy supervisor`, `--effort` on `memory enable`, `memory shadows review --curate`, and
  `workflow {panel,analyze,debate,consensus}`.
- **Memory enable early-return fix**: `_set_memory_activation` now short-circuits only when enabled/mode/effort are all
  unchanged, so `forge memory enable --effort high` persists on an already-enabled same-mode session.
- Additive optional fields only — no `SCHEMA_VERSION` bump. No global `RuntimeConfig` default-effort knob (per-caller by
  decision). Docs updated: `end-user/session.md`, `end-user/memory.md`, `cli_reference.md`, `design_workflows.md`.

**Verification**: 906 unit tests pass across new + touched files (incl. new `tests/src/core/test_effort.py`
vocab/drift-guard, `run_claude_session` fail-loud, fork/start persistence, per-consumer forwarding, vocab matrix, memory
early-return regression); `make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat/gitleaks); integration green:
`test_session_commands_integration.py::test_fork_supervise_cascade_effort_persists` and
`test_supervisor_e2e.py::test_supervisor_effort_reaches_claude_argv` (`--effort medium` in the logged claude argv).

### same_dir_transfer_forks: decouple transfer mode from worktree isolation in `forge session fork`

**Goal**: Let a same-directory fork run a curated *transfer* launch (fresh child Claude session + assembled parent
context) instead of always native `--resume --fork-session`, and stop silently dropping `--strategy`/`--inline-plan` on
same-dir forks (the bug from the supervisor investigation).

**Key changes** (`src/forge/cli/session_fork.py`, `manager.py`, `session_lifecycle.py`):

- **Auto-switch**: explicit `--strategy`/`--inline-plan` on a same-dir fork resolves `resume_mode = "transfer"` pre-fork
  (gated on `resume_mode is None`, so `--resume-mode native-relocate` never auto-switches) and prints a non-silent info
  line. The existing `--resume-mode transfer` is the explicit same-dir-legal opt-in; `native-relocate` stays
  worktree/`--into`-only. No `--fresh-transfer` flag.
- **Branch widened, not duplicated**: the worktree-transfer branch predicate becomes
  `uses_fresh_transfer = (is_worktree_fork and not native_relocate) or same_dir_transfer`, resolving `worktree_path` per
  case. Six launch refs (sidecar `session_id`/`resume_id`/`fork_session`/**`register_fork`**/`system_prompt_file`; host
  `active_claude_session_id`) now key on it. `register_fork` is load-bearing: with `fork_session=False` it is the only
  thing setting `FORGE_FORK_NAME`. Budget preflight widened to `is_cross_dir or resume_mode == "transfer"`.
- **Derivation correct under partial failure**: `manager.fork_session` writes the `"transfer"` baseline (+ pre-recorded
  `context_file`) for same-dir transfer, so a best-effort CLI `_persist_fork_transfer_derivation` refinement failure
  can't leave a requested transfer fork recorded as `"native"`.
- **Deferred-resume guard**: `_get_deferred_same_dir_fork_resume_id` returns `None` when
  `derivation.resume_mode == "transfer"`, before the confirmed-state guard — a failed UUID pre-seed can no longer
  silently native-resume a `--no-launch` transfer fork.
- **Docs**: `design.md`, `end-user/session.md`, `cli_reference.md` updated; help strings dropped "worktree-only"
  framing.

**Verification**: 41 unit tests green (7 new same-dir CLI tests, 3 regression incl. a direct guard test, new manager
derivation test); 4 integration tests green (new same-dir transfer argv has `--session-id` +
`--append-system-prompt-file` and lacks `--resume`/`--fork-session`; 3 adjacent fork-launch regressions unchanged);
`make pre-commit` clean.

## 2026-06-14

### supervisor_shadow_sampling: measure the cascade's false-aligned rate (3 slices, one PR)

**Goal**: Audit how often the cascade's tier-1 `allow` short-circuits a frontier check the frontier would have blocked,
without slowing the PreToolUse hook.

**Key changes**:

- **Slice 1 (capture, inert)**: `SupervisorConfig` gains `shadow_sample_rate`/`shadow_max_per_session`/`shadow_seed`
  (range-validated in `__post_init__`, so a bad `session set` override surfaces as `InvalidOverrideValueError`). New
  `policy/semantic/shadow.py`: deterministic stable-hash sampler (no RNG; rate 0/1 short-circuit), `capture_candidate`
  freezes a *fresh* tier-1 allow's raw inputs + copied plan (`<hash>.plan.md`) + routing snapshot to
  `.forge/artifacts/<session>/shadow/`. Cap/dedup count distinct stems across `.json`/`.processing`/`.done`. Seam in
  `plan_check.py` (fresh-allow branch, gated on rate > 0, best-effort). Fully inert at rate 0 (dir never created).
- **Slice 2 (Stop-batch drain)**: `run_supervisor_check` extracted as the single emitter (`usage_command` param +
  `SupervisorRun{decision,verdict,run_ok,parsed}`); `parse_supervisor_verdict_with_status` distinguishes a parse failure
  from a real low-confidence verdict. `enqueue_shadow_marker` + Stop-hook gate (`has_pending_candidates`) +
  `_shadow_handler` (detached `Popen`, run-tree re-root via `_memory_writer_env`). New `shadow_runner.py`: atomic claim
  (`rename` → `.processing`, at-most-once), reconstruct full context/config (plan → frozen sidecar), classify
  agree/disagree/inconclusive/error with the supervisor's own block bar; never enforces.
- **Slice 3 (read surface)**: `ShadowActivity` in `build_session_activity_summary` (counts from `.done` status, spend
  from the `supervisor-shadow` ledger row); `forge activity` Shadow line + `render_summary_line` audited/queued segment;
  `forge policy shadow` group (hidden `run` worker + `show` lists disagreement artifacts with citations).
- Docs: design_workflows.md §1.2 shadow paragraph, design_appendix.md §A.13 `supervisor-shadow` emitter row.
- Post-review hardening: relative `plan_override_path` now resolves against `forge_root` at capture (mirrors
  `load_plan_override`); deterministic post-claim failures finalize as `.done` `status="error"` (no orphaned
  `.processing` phantom-pending); detached shadow worker resets `FORGE_DEPTH=0` so the frontier replay spawns; renderer
  shows only cited (blocking) violations for a disagreement.

**Verification**: 42 drain tests (`test_shadow_runner.py`) + 73 capture tests (Slice 1) + 9 `test_usage_summary.py` + 2
`test_activity.py` + 6 `test_policy_shadow.py`; 2500 policy/workqueue/cli/core-ops tests green; mypy + pyright clean on
all 10 changed source files. Schema note: additive `SupervisorConfig` fields — old Forge cannot read new manifests
(research-preview clean break).

### codex_frontend closeout: Codex shipped as a first-class alternate runtime (card -> done)

**Goal**: Close out the `codex_frontend` card after PR #26 merged to `main`. Phases 0-6 and the residual-risk
mitigations each have their own dated entries below; this records the epic closeout and the v0.6.0 release.

**Key changes**:

- Card moved `doing/codex_frontend/ -> done/` (board-contract closeout). All phase and Open-Decision boxes ticked; only
  the deliberate Deferred items remain (app-server transport, filing the upstream fail-open issue, PermissionRequest
  source-dive).
- Durable lessons promoted to `impl_notes.md`: the capability/lifecycle runtime seam (limits-as-capability-values),
  Codex hook enrollment-gating + non-computable `trusted_hash` + fail-open PreToolUse, and the
  native-direct-to-Responses topology (governed at the session/hook seams, not the wire; `isolate_codex_home` test
  isolation).
- Post-merge doc-sync landed on the branch in #26: `design.md` split into design/appendix/workflows/cli_reference for
  the 30K doc-size limit; architecture diagrams (1/5/8) and the README updated to show Codex as an alternate runtime.

**Verification**: Full checklist ticked with per-phase verification recorded; `make pre-commit` + `make test-unit` green
before tagging; PR #26 CI (Docker integration) green at merge. Released as **v0.6.0** (covers #24 supervisor timeout,
#25 supervisor cascade, #26 Codex runtime) via the `v0.6.0` tag -> `publish.yml` -> PyPI.

## 2026-06-13

### codex_frontend Phase 6 code-review fixes: 12-finding sweep (fork / enrollment / policy / handoff / invoker)

**Goal**: Resolve a branch code review of `codex-frontend` (12 findings, P1->P3). Every confirmed behavioral finding is
fixed with a regression test; doc/process findings are fixed in place. One finding was a verification artifact
(uncommitted drift) closed by landing this slice.

**Key changes**:

- **Fork rejects a Codex parent (P1)** — two layers. `cli/session_fork.py` preflights with an actionable message (Codex
  resume / branch commands), and `SessionManager.fork_session` now raises `CannotForkCodexParentError` at the internal
  boundary before any child manifest/worktree is created. Codex sessions have no `claude_session_id`, so the old path
  built child state then failed the UUID check, orphaning it; the manager guard makes the invariant hold for every
  caller, not just the CLI preflight.
- **No TYPE_CHECKING workaround (P1)** — `cli/runtime.py` imports `CodexEnrollmentVerification` directly;
  `core/ops/codex_enrollment.py` moved its heavy probe-turn imports (invoker graph, session store) into
  `_run_probe_turn` so the CLI-facing module import stays cheap. Re-greens the
  `test_production_source_has_no_type_checking_workarounds` conformance check.
- **Event-aware enrollment identity (P2)** — new `codex_registration_pairs()` (`(event, command)`) in
  `install/codex_hooks.py`; `_read_user_scope_registration` checks `("SessionStart", cmd)`, so a wrong-event Forge
  registration no longer reads as enrolled and burns a real `codex exec` turn.
- **Shared path matcher for TDD (P2)** — extracted `is_under_directory()` into `policy/deterministic/base.py`; the Codex
  tests-first sort (`cli/hooks/codex_policy.py`) and the TDD guard now share one nested-aware matcher (their drift was
  the bug; a `pkg/tests/...` path was misordered).
- **Staged-context one-shot backstop (P2)** — `consume_pending_context` empties the staging file when `unlink` fails,
  and the delivered-reconciliation paths (`core/ops/codex_session.py`, `core/ops/codex_interactive.py`) clear pending
  unconditionally, so a re-fired SessionStart can't re-deliver stale context.
- **Runtime error is not success (P2)** — `cli/session_codex.py` adds `_codex_ok()` (returncode-success AND not
  `runtime_is_error`); launch/resume exit codes, outcome render, and the resume tip all honor it.
- **Argv exposure documented (P2)** — `session/codex_invoke.py` + `docs/end-user/session.md` note that an interactive
  `--resume-from` prompt is visible in shared-host process listings, recommending `--context-delivery hook`; confirmed
  the existing debug log emits only cwd/resume, never the prompt.
- **Manifest corruption distinct from missing (P3)** — `resolve_codex_session` narrows not-found to
  `SessionNotFoundError`; other `ForgeSessionError` now surfaces "could not be read (manifest may be corrupt)" rather
  than a misleading "not found".
- **No blank provider error (P3)** — `core/invoker/codex_stream.py` returns `None` for empty/whitespace error text and
  `core/invoker/codex.py` backfills a fallback stderr when the stream is an error.
- **Enrollment diagnostic never tracebacks (P3)** — `verify_codex_enrollment` wraps the gate sequence and degrades any
  unexpected error to an UNVERIFIED result.
- **Change-log heading restored (P3)** — the Phase 6 review-fixes entry regained its missing `###`.
- **Change-log compaction** — summarized the 2026-05-22 → 2026-06-06 tail in place (board-contract size policy) so the
  file clears the 30K-token doc limit (38.5K → 28.7K count-tokens); dates, breaking changes, decisions, and design
  pointers preserved, per-test counts and play-by-play dropped (full detail in git history).

**Verification**: 553 unit+regression tests green across the touched Codex suites — 7 new
`tests/regression/test_bug_codex_*.py` (fork orphan at the CLI **and** `fork_session` layers, enrollment wrong-event,
TDD nested layout, staged-context re-read, runtime-error exit-0, manifest corrupt-vs-missing, empty provider error) plus
a `TestNeverRaises` case in `test_codex_enrollment.py`; the no-`TYPE_CHECKING` conformance test green; mypy clean (259
files); pyright clean on the 15 changed source files (`manager.py` + `exceptions.py` added for the fork-guard
invariant); `make pre-commit` clean (with every new file staged — an earlier pass silently skipped untracked files). 24
Docker integration tests green against an image rebuilt with these changes — `test_policy_hooks.py` 21/21 (Claude +
Codex `policy-check` wires and codex session-start/staged-context delivery, covering the shared `is_under_directory` and
the one-shot staging backstop) and `test_installer.py` codex-hooks 3/3. The three real-`codex` API E2Es
(`test_codex_session_start` / `codex_exec_smoke` / `claude_to_codex_resume`) stay `CODEX_API_KEY`-gated (only
`OPENAI_API_KEY` is present, which codex rejects) and were not run; they exercise codex subprocess mechanics these fixes
do not alter.

## 2026-06-12

### codex_frontend residual-risk mitigations: version-churn guard + empirical enrollment check

**Goal**: Harden the external-binary residual risks from the card's "Risks / open questions" before closeout — Forge
owns the *detection and confirmation* surface even where the underlying behavior is codex-cli's. Three actionable items
(the `trusted_hash` source-dive and PermissionRequest pinning stay deliberately documented-not-built).

**Key changes**:

- **Validated-version ceiling (version churn).** `CODEX_VERSION_VALIDATED` (`core/runtime/codex_preflight.py`, `0.139.0`
  — the last green probe round) + additive `CodexPreflight.version_validated`/`version_beyond_validated` (defaulted, so
  every existing keyword construction stays valid). `forge runtime preflight codex` prints a **non-blocking** re-probe
  notice when the installed binary sorts strictly above the ceiling (a bump never fails readiness — the pinned
  trust/`apply_patch`/argv facts are just unverified for that version), and the real-codex E2E names the ceiling on
  failure. Mirrors the 4g `CLAUDE_VERSION_VALIDATED` guard.
- **Empirical enrollment check (the unverifiable ceremony).** `forge runtime preflight codex --verify-enrollment` over
  new `core/ops/codex_enrollment.py`: the trust ceremony is unverifiable from a config read (`trusted_hash` not
  computable), so this confirms it by *effect* — one trivial managed `codex exec` turn in a throwaway git repo, enrolled
  iff `codex-session-start` fired (the Phase 5 observation receipt appeared). Reuses `_temporary_run_env` so the codex
  child inherits `FORGE_SESSION`/`FORGE_FORGE_ROOT` and the hook resolves the disposable session exactly as in
  production. Short-circuits with **no turn** when the answer is already knowable (not ready / not registered); a turn
  that fails to complete reports `UNVERIFIED` (not "not enrolled"); the not-enrolled message is sharpened by `hook_seam`
  (managed-suppressed / disabled / re-probe hint). Tests **user** scope only (path-stable, one-ceremony-covers-all).
- **Upstream fail-open issue drafted.**
  `scripts/experiments/codex-hooks/upstream-issues/pretooluse-malformed-fails-open.md` (probe-30h reproduction: `allow`
  \+ unknown field + `continue:false` ran the command, refuting the documented fail-closed). **Owed**: the exact codex
  docs citation + an operator-confirmed `gh issue create --repo openai/codex`.
- **Docs**: design.md §5 (the verify-enrollment path beside "cannot perform or verify"); design_appendix §N.3 (both
  guards); card Risks bullets annotated with the shipped mitigations; checklist residual-risk slice + Deferred update.

**Verification**: 226 Codex-touching unit tests green (`tests/src/core/runtime/`, `test_runtime.py`,
`test_codex_enrollment.py`, the four `core/ops`/`invoker`/`session` codex suites — defaulted preflight fields keep every
construction valid); new `TestValidatedVersionGuard` (5), `test_codex_enrollment.py` (verdict-logic + `_run_probe_turn`
mechanism via a FORGE_FORGE_ROOT→receipt simulation + git-init degrade + JSON-safe/secret-free), `TestVerifyEnrollment`
CLI (4) and the two version-notice CLI cases; mypy + pyright clean on the three changed source files. No real `codex`
runs in the suite (the turn is mocked). The `--verify-enrollment` real-codex behavior is operator-gated (one quota
turn).

### codex_frontend Phase 6 review fixes: tracking preservation + (event, command) dedupe + sync ceremony

**Goal**: Fix three Phase 6 review findings — two P1s (a previously tracked Codex block orphaned when codex is
temporarily off PATH; manual-registration dedupe matching bare command strings regardless of event, so a wrong-event
registration silently skipped enforcement untracked) and one P2 (`extension sync` never printed the trust-ceremony
next-steps and `_count_actions` ignored codex, rendering a false "Already up to date." on codex-only changes).

**Key changes**:

- `Installer._execute_codex` now returns `None` for "no authoritative outcome" (module not selected, codex binary
  unavailable, conflict, apply failure) vs `(path, commands)` for a resolved read-back from disk; `init()` preserves
  prior tracking on `None` — unifying the module-dropped branch — so disable always keeps knowing about a previously
  written block. The skip-due-to-manual-registration outcome stays authoritative (`(None, [])`): ownership transferred
  to the user, tracking correctly clears.
- New `_collect_registrations()` in `codex_hooks.py`: dedupe compares `(event, command)` pairs with `type = "command"`,
  matching Codex's own registration identity; matchers deliberately ignored (a matcher'd entry still fires on
  overlapping events — installing alongside would double-fire). Wrong-event and bogus-event registrations now plan
  `install`; conflict/post-merge-validation messages name `event: command`. The event-agnostic `_collect_commands()`
  flatten is kept for the reporting surfaces (status, uninstall leftover warning) by design.
- `_count_actions` returns a third codex component (install/update = 1 action) at both call sites, and `sync_cmd` calls
  `_print_codex_completion` — a synced block can carry new entries whose per-entry `trusted_hash` is not yet granted, so
  sync is exactly where the ceremony guidance matters.

**Verification**: Two regression files, fail-confirmed against the unfixed code (6 failing + 3 behavior-guard cases):
`tests/regression/test_bug_codex_tracking_lost_on_unavailable.py` (unavailable + conflict re-runs preserve tracking and
disable still cleans up; manual-skip still drops tracking) and `tests/regression/test_bug_codex_dedupe_wrong_event.py`
(swapped/bogus events install, partial wrong-event conflicts, correct-event + matcher'd dedupe kept, non-command type
excluded). Three new CLI cases (sync restores block + counts it + prints ceremony; unchanged sync stays quiet;
codex-less re-enable keeps tracking via `status --json`). Full sweep 6341 unit+regression green; Docker
`test_installer.py` 15/15; mypy/pyright clean; `make pre-commit` clean.

### codex_frontend Phase 6: codex-hooks installer module (scope-mirroring registration)

**Goal**: `forge extension enable` registers Forge's two Codex hooks (`codex-session-start`, `codex-policy-check`) in
the Codex config the **Forge install scope maps to** — resolving the stage-84 installer-scope trade-off by user
decision: mirror the install scope (`user` -> `$CODEX_HOME/config.toml`; `project`/`local` ->
`<project>/.codex/config.toml`, Codex has no settings.local analog). Accepted trade-off: project/local installs cost one
trust ceremony per repo; enable names the ceremony explicitly so a registered-but-unenrolled install is never mistaken
for active enforcement.

**Key changes**:

- **`install/codex_hooks.py`** (new): builtin entries (trust-durable command strings, PreToolUse with NO matcher — the
  adapter filters), marker-delimited managed block (`# >>> forge hooks >>>`), `tomllib`-validated merge/remove that
  never rewrites the codex-owned `config.toml` (no TOML-writer dependency; post-merge parse validation before an atomic
  write; `.config.toml.forge.backup.<ts>`), event-name validation against the probe-pinned 10-event set (Codex loads
  bogus names silently), and dedupe vs manual registrations (full -> skip untracked; partial -> conflict — installing
  would double-register and Codex fires duplicates twice per event).
- **Installer wiring**: settings-only `InstallModule.CODEX_HOOKS` in `standard`+`full`, presence-gated on the codex
  binary (visible skip, never silent); `InstallPlan.codex` (`CodexPlan`); additive `Installation.codex_config_path`/
  `codex_commands` tracking; **codex conflicts never set `has_conflicts`** (best-effort: another tool's config must not
  fail the Claude install); uninstall removes only the managed block, refuses a tracked path that no longer matches the
  scope mapping, and deletes a whitespace-only (Forge-created) file.
- **CLI**: plan render gains a "Codex hooks (config.toml)" section; enable prints trust-ceremony Next-steps on
  install/update; `extension status` shows the registration (human + `--json`); disable previews the block removal.
- **Registry**: codex `install_scopes` `()` -> `("user", "project", "local")`; note rewritten to the shipped mapping.
- **Test isolation fix**: the new installer tests exposed that nothing isolated `CODEX_HOME` — the suite wrote the
  managed block into the real `~/.codex/config.toml` (restored from the Forge backup). New autouse `isolate_codex_home`
  fixture in `tests/conftest.py` closes the leak class for all tests.
- **Docs**: design.md §5 (seven modules + codex-hooks paragraph) + §4.1.4 (handler-only -> installer-registered +
  ceremony); design_appendix §E.2 + new §E.6 (mechanics); end-user hook.md codex sections reframed (manual TOML kept as
  a reference path); QA checklist §2.10/§2.11 (test-count 535 -> 541).

**Verification**: 59 new unit cases — `test_codex_hooks.py` (40: trust-byte golden, inline-table post-validation-only
failure with no write, full-vs-partial manual dedupe, whitespace-only deletion), `TestInstallerCodexHooks` (11: update
byte-stability, conflict-never-blocks, tampered-path refusal, module-dropped tracking preservation),
`TestEnableCodexHooks` (5 CliRunner end-to-end), registry pins; full unit+regression sweep 6329 green; Docker
`test_installer.py` 15/15 (3 new `TestCodexHooksModule` cases through the real wheel CLI: enable->status->disable cycle
with a codex shim, presence-gated skip, user-content preservation); live `forge runtime list --json` renders the flipped
scopes; `make pre-commit` clean.

### codex_frontend probe debt: operator-gated stages 85-87 harness

**Goal**: Convert the owed Phase 3/4/5 operator-gated Codex checks from README sketches into runnable probe stages:
product `codex-policy-check`, product `codex-session-start` with multi-KB `additionalContext`, and the real interactive
TUI behavior smoke.

**Key changes**:

- Added product-probe helpers to `scripts/experiments/codex-hooks/lib.sh`: stage-isolated `FORGE_HOME`, repo-root
  discovery, product-project setup, `forge` PATH guard for trust-durable product hook commands, and a guided trust
  ceremony prompt.
- Added stage `85-policy-check-e2e`: registers the real `forge hook codex-policy-check`, enables TDD on an isolated
  Forge session, asks Codex to create an impl-only file, and passes only if the manifest records a deny and the file is
  absent.
- Added stage `86-sessionstart-delivery-e2e`: registers the real `forge hook codex-session-start`, seeds a large parent
  transcript, runs the shipped `--context-delivery hook` bridge, and checks echo + `confirmed.codex` receipt facts.
- Added stage `87-interactive-smoke`: foreground TUI flow for bare start, live reattach, active-gate refusal, positional
  hold instructions, hook-delivered context, and read-only sandbox behavior, combining operator answers with manifest
  facts.
- Wired stages 85-87 into `reproduce.sh all`; post-run hardening keeps foreground TUI stdout/stderr attached to the
  terminal, aborts early when 87A did not create a thread, uses the absolute `forge` path for the second-terminal active
  gate command, and gives sandbox failures their own verdict.

**Verification**: `bash -n` on the changed harness scripts; `shellcheck -e SC1091` on the same set (dynamic stage
`source` parity); focused unit slice passed:
`uv run pytest tests/src/cli/hooks/test_codex_policy_check.py tests/src/cli/hooks/test_codex_session_start.py tests/src/session/test_codex_handoff.py tests/src/core/ops/test_codex_session.py tests/src/core/ops/test_codex_interactive.py`
(126 passed); `make pre-commit` clean. A minimal stage-style product project can run
`forge session start smoke --no-launch --no-proxy` with isolated `FORGE_HOME`, and `uv run --project ... forge --help`
validates the fallback helper command shape. Live operator run on codex-cli 0.139.0: stage 85 PASS (product
`codex-policy-check` denied the impl-only `apply_patch`; blocked file absent); stage 86 PASS (11,519-byte transfer
delivered through product `codex-session-start`, token echoed, `confirmed.codex.context_delivery` and `rollout_source`
both `session_start_hook`); stage 87 PASS after harness hardening (bare start, reattach memory, second-terminal
active-gate refusal, positional hold instructions, hook-delivered interactive bridge, and read-only sandbox denial all
operator-confirmed with matching capture facts; `sandbox_should_not_exist.txt` stayed absent). The operator also
observed that Codex CLI visibly rendered hook-delivered `SessionStart` `additionalContext` in the TUI transcript even
though it was delivered passively rather than as a positional synthetic prompt; the non-gating observation prompt was
codified after that PASS run, so the current capture predates `results/observations.txt`.

## 2026-06-11

### codex_frontend Phase 5: Interactive Codex frontend

**Goal**: Forge-manage interactive `codex` TUI sessions -- bare `forge session start --runtime codex` opens the TUI,
`--resume-from` without `--task` is an interactive bridge carrying the curated transfer, and bare `forge session resume`
reattaches via `codex resume <thread_id>`. `--task` keeps meaning headless, byte-unchanged. **Scope (user decisions)**:
bare = interactive; bridge composes both deliveries; thread capture = post-exit filesystem discovery + enrolled-home
observation receipt (separate `observation-receipt.json`; the Phase 4 delivery-receipt contract stays byte-stable);
`install_scopes` stays `()` (Phase 6) -- only `interactive="beta" -> "default"` flips.

**Key changes**:

- **Discovery** (`core/runtime/codex_rollouts.py`): `find_rollouts_since` -- mtime-filtered rollouts since a tight
  pre-launch timestamp, head-cwd narrowing (never below one candidate), thread_id parsed from the filename. The ops
  layer requires exactly one candidate (`rollout_source="discovered_post_exit"`); ambiguity refuses to guess.
- **Observation receipt** (`session/codex_handoff.py` + `cli/hooks/codex_transfer.py`): nothing-staged turns in a
  managed session record codex's own `session_id`/`transcript_path`; the handler branches on pending-file PRESENCE so a
  failed staged delivery never masquerades as an observation. Receipts stay the hooks' only writes (design.md 3.5).
- **Launcher** (`session/codex_invoke.py`, new): foreground `subprocess.run` of `codex --sandbox X [prompt]` (start) or
  `codex resume --sandbox X <tid>` (reattach -- the subcommand declares its own flag); env = sanitized child env
  (`sanitize_codex_child_env`, extracted behavior-neutral) + FORGE_SESSION/FORGE_FORGE_ROOT + a REQUIRED caller-minted
  run-identity triple -- the TUI shares the transfer-curation event's root (one run tree; a mint-when-absent default
  would silently fork it).
- **Interactive ops** (`core/ops/codex_interactive.py`, new): `start_interactive_codex_session` (bare + bridge;
  `assemble_codex_transfer` extracted from the bridge golden-pinned byte-identical; positional delivery wraps the body
  in hold instructions via `compose_codex_interactive_context` -- the positional `[PROMPT]` starts a real model turn)
  and `reattach_codex_session` (guards shared with `continue_codex_session` by extraction). Two timestamps
  (activity-summary window vs discovery window); receipts beat discovery; rollback only before the TUI launches;
  interactive turns emit no usage event; bare starts record `context_delivery=None`.
- **CLI matrix** (`cli/session_codex.py`, `cli/session_lifecycle.py`): omitting `--task` = interactive; `--task` alone
  errors; bare resume gates on the active-session registry (Claude reconnect parity, no `--force` escape) then
  reattaches; cross-project resume restructure -- the unscoped fallback always runs on a scoped miss, codex dispatches
  (cross-CWD by design), the Claude refusal stays byte-identical. `_post_exit_render` reused via lazy import (cycle).
  `session show` gains a `Delivery:` line; registry `interactive="default"`.
- **Docs**: design.md 3.4/3.5/3.9/3.10/4.0 + runtime matrix; session.md interactive section; transfer.md "later phase"
  note replaced; hook.md observation bullet; probe README stage-87 operator checklist (real-TUI smoke incl. multi-KB
  positional + hold-instructions no-autonomous-action).

**Verification**: 70 `test_session_codex.py` (matrix incl. exact errors, cross-project both runtimes, renderers) + 22
`test_codex_interactive.py` (bare/bridge/hook matrices, two-timestamp pin, run-identity equality pin, ambiguity refusal,
reattach) + 13 `test_codex_invoke.py` (argv/env/auth postures) + observation-receipt suites; full `tests/src/cli` 1761
green; runtime package 80 green; mypy clean. Docker `test_policy_hooks.py` observation cases added. Post-ship live
probes (codex 0.139.0) closed the argv/rollout-head externals: `codex resume --help` pins
`resume [OPTIONS] [SESSION_ID]` with its own `-s/--sandbox` (the launcher was corrected to pass `--sandbox` inside the
subcommand instead of root-level), and a real rollout head matched the discovery parser exactly (`session_meta` +
`payload.cwd`; filename timestamp confirmed LOCAL time, validating filter-by-mtime). Deferred verification: operator-
gated stage 87 behavioral smoke (hold instructions, multi-KB positional, enrolled hook delivery, live reattach, sandbox
behavior).

### codex_frontend follow-up: codex-policy-check silent on unresolvable sessions

**Goal**: Align the Phase 3 hook with the codex-session-start silence rule -- under a user-scope Codex registration, "no
resolvable Forge session" means Forge is not managing the turn, and unrelated Codex sessions must see no Forge stderr
noise.

**Key changes**:

- `codex_policy_check` (cli/hooks/commands.py): the no-session stderr print -> `logger.debug` (hooks debug log via
  `FORGE_DEBUG=1`). Post-resolution diagnostics (manifest/intent/engine failures, block/check summaries, no-evaluable-
  operations) keep stderr -- they only fire inside a managed Forge session. hook.md documents the silent-allow bullet.

**Verification**: `test_no_session_passes_through` strengthened (empty stderr + caplog debug pin);
`test_codex_policy_check.py` + `test_codex_session_start.py` 28/28; mypy clean.

### codex_frontend Phase 4: SessionStart transfer delivery with initial-message fallback

**Goal**: Ship the post-enrollment upgrade the 30e probe unlocked -- deliver the curated transfer to a Codex session via
a trust-enrolled SessionStart hook (`additionalContext`) instead of the initial `codex exec` prompt, with
initial-message staying the zero-setup default. The central constraint shaped the design: enrollment is unverifiable
pre-turn (the `trusted_hash` is not computable), so hook mode = explicit opt-in + staged file + post-turn receipt
reconciliation. **Scope (user decisions)**: `--context-delivery {initial-message,hook}` flag shape; hook-undelivered
fails loud (exit 1, session kept); handler-only like Phase 3 (manual registration + ceremony until the Phase 6
installer).

**Key changes**:

- **Staging module** (`session/codex_handoff.py`, new): `pending-context.md` + `context-receipt.json` under
  `<session_dir>/codex/` (GC/delete free via the session dir; pinned anyway). `consume_pending_context` writes the
  receipt BEFORE unlinking (a delivered-but-unreceipted turn would read `hook_undelivered` dishonestly); a failed
  receipt write deliberately delivers nothing. `compose_codex_initial_message` split into
  `compose_codex_handoff_context` + task suffix -- the default path is golden-pinned byte-identical (golden added before
  the refactor).
- **Handler** (`forge hook codex-session-start`, new `cli/hooks/codex_transfer.py`): resolves the session via
  FORGE_SESSION + payload-cwd rooting (the Phase 3 rule), consumes the staged file, emits the probe-pinned strict
  one-line `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}` (Codex fails OPEN on
  malformed output). Never reads the manifest -- the receipt is its only write, so `confirmed.codex` stays CLI-owned
  (design.md §3.5). Every non-delivery path (no session, nothing staged = resume turns, malformed stdin) is a silent
  exit-0 no-op with NO output -- diagnostics log at debug to the hooks log (review fix: two stderr prints would have
  made every non-Forge Codex session under a user-scope registration emit Forge noise). The command name is
  trust-durable (renaming breaks `trusted_hash` enrollment).
- **Bridge/op wiring**: `bridge_session_to_codex(staged_context_path=)` stages the framed body and sends the raw task as
  the prompt; `_temporary_run_env` now also scopes `FORGE_FORGE_ROOT` (the CHILD's forge_root -- worktree sessions'
  manifests aren't findable from payload cwd alone, benefits both codex hooks). `start_codex_session` gained
  `context_delivery` + a pre-turn guard (knowable-negative seams `disabled|unknown|managed_suppressed|untrusted` fail
  before any state; `enrollment_gated` proceeds). `_reconcile_hook_delivery` post-turn: receipt matching the stream
  thread -> `session_start_hook` (receipt `transcript_path` supersedes glob as `rollout_source="session_start_hook"`,
  cross-checked with a warning); receipt present when the stream missed `thread.started` -> **recovers**
  `thread_id = receipt.session_id` (otherwise-unresumable session stays resumable); absent/mismatched ->
  `hook_undelivered` + staged file cleared (one-shot: an enrolled resume can never late-deliver stale context; resume
  also defensively clears).
- **CLI**: `--context-delivery` Choice with Click default `None` (a real default would trip
  `reject_codex_flags_for_claude` on every plain Claude start -- regression-pinned), resolved to initial-message in
  `run_codex_start`; undelivered render prints `print_error_with_tip` (ceremony / delete-and-retry) and exits 1 even
  when the codex turn succeeded. `CodexConfirmed.context_delivery` (additive).
- **Docs**: design.md §3.9 (delivery contract; the stale "hook delivery deferred to Phase 6" claim removed at the code
  slice that falsified it) + §3.5 (receipt note); end-user hook.md (`codex-session-start` section with the probe-pinned
  NESTED registration TOML + trust-durable-name warning), session.md + transfer.md (flag, default, failure semantics);
  probe README "stage 86" operator-gated note (enrolled E2E incl. the unprobed multi-KB additionalContext size).
- **File-size compliance** (commit-hook limits): `cli/session_model_pin.py` split out of `session_lifecycle.py` (the
  --model pin validate/apply/persist helpers; same pattern as the original session.py split), design.md §3.9 verbosity
  trims (content-preserving), and the 2026-06-05 change_log block compacted per the board-contract size policy.

**Verification**: 60+ new unit cases -- `test_codex_handoff.py` (16: roundtrip/one-shot/receipt-failure),
`test_codex_session_start.py` (10: delivery, strict-wire key sets, payload-cwd rooting, 7 silent no-ops asserting empty
stdout AND stderr, incl. consume-failure fail-open), `test_codex_bridge.py` (+7: golden, staging-at-Popen-time, env
restore), `test_codex_session.py` (+8: hook-mode matrix incl. thread-id recovery + per-seam guard),
`test_session_codex.py` (+5 incl. the plain-Claude-start None-default regression), `test_gc.py` (+1 handoff-files
pinning); full blast radius 1270 ops/session/CLI tests green; mypy clean on all of `src/forge/`. Docker:
`test_policy_hooks.py` 21/21 (4 new `TestCodexSessionStartDocker` cases through the real wheel CLI, incl. the
no-FORGE_SESSION user-scope silence case; 17 pre-existing unchanged).

**Deferred**: the real-codex enrolled-hook E2E is operator-gated (stage 86, with stage 85); additionalContext payload
size beyond the 30e short token is unprobed until that round.

### codex_frontend Phase 3 follow-up: blocked actions no longer persist policy state

**Goal**: Fix four Phase 3 review findings, chiefly that both hook commands persisted engine-collected policy state
before checking whether the composed decision blocks the action.

**Key changes**:

- A blocked action (deny / unresolved needs_review) never lands -- Claude denies the Write/Edit, Codex rejects the whole
  all-or-nothing `apply_patch` -- so its collected state (e.g. TDD `tests_touched` from a clean test file riding in a
  denied patch) no longer persists; decision-log entries still persist as the audit trail. Gated in
  `_persist_policy_state` (Claude) and at the `codex-policy-check` persist call (cross-file aggregate).
- Codex stderr telemetry now labels the decisive file (first denying / first unresolved result), not `file_results[0]`,
  which could be an allowing file routing the label helper down the wrong branch.
- All three Codex wire emissions print with explicit `file=sys.stdout`; `_join_sections` types its formatter as
  `Callable[[CompositeDecision], str]`.

**Verification**: New `tests/regression/test_bug_blocked_action_persists_policy_state.py` (both runtimes, fail-confirmed
against the unfixed code) + telemetry-label unit test; 6,123 unit/regression tests green; Docker `test_policy_hooks.py`
17/17; mypy/pyright clean.

### codex_frontend Phase 3: Codex hook adapter/responder + `forge hook codex-policy-check`

**Goal**: Fill the runtime-neutral `HookAdapter`/`HookResponder` protocols with the Codex pair so a `codex exec` turn
can enforce Forge policy on `apply_patch` actions, carrying the resolved `ActionContext.runtime -> origin` rename. Scope
(user decision): **PreToolUse only** (Stop/UserPromptSubmit/SessionStart land with their Phase 4/5 consumers;
PermissionRequest stays descoped -- never observed firing headless); **handler-only** -- enforcement needs a manually
registered + trust-enrolled Codex hook until the Phase 6 installer.

**Key changes**:

- **`origin` rename** (`policy/types.py`): `ActionContext.runtime -> origin`, values `{forge_cli, claude_code, codex}`
  per the recorded `runtime_abstraction` decision -- the two on-demand CLI leaves (`forge policy check`/`supervisor`)
  become `forge_cli`; `%policy check` stays `claude_code` (Claude-context); the false "flows into attribution" docstring
  claim fixed. Zero behavioral surface (no read sites, never serialized); 47 test kwargs across 11 files.
- **apply_patch parser** (`cli/hooks/codex_patch.py`, new): `parse_apply_patch -> list[PatchFileOp] | None` over the
  probe-pinned grammar (Add/Update/Move to/Delete, `@@` hunks, End-of-File tolerance, CRLF); `None` = malformed ->
  caller fails open (converges with Codex's own rejection); `path` is the post-op Move-to target.
- **Adapter/responder** (`cli/hooks/codex_policy.py`, new): `CodexHookAdapter` normalizes per-file ops to the tool names
  every policy's `applies_to` gates on (Add->`Write`, Update->`Edit`; deletes skipped; `Bash` -> `[]`), tagging
  `origin="codex"` with runtime truth in `tool_args`; `CodexHookResponder` emits the probe-pinned deny wire
  (`hookSpecificOutput.permissionDecision="deny"` + reason, strict `json.dumps` only -- Codex FAILS OPEN on malformed
  output; `BLOCK_EXIT = 0`). Protocol cardinality became `build_contexts -> list[ActionContext]` (clean break; the
  Claude adapter returns `[ctx]`/`[]`, wire bytes unchanged); deny reason text shared via extracted
  `format_deny_text`/`format_needs_review_text` (Claude strings byte-identical).
- **`forge hook codex-policy-check`** (`cli/hooks/commands.py`): per-file evaluation with tests-first ordering (an
  atomic test+impl patch passes TDD, the `%policy check` precedent); cross-file precedence deny > needs_review >
  warn/allow; allow emits NO stdout (allow-feedback delivery unprobed); session resolved via FORGE_SESSION with
  payload-cwd `forge_root` rooting (Codex `session_id` is a thread UUID, never in the Claude index). Engine assembly
  extracted as `build_hook_engine` + `register_supervisor_and_restore` (moved-not-changed; cascade resolver wiring now
  serves both commands); `_persist_policy_decisions` writes one decision-log entry per file op in one lock cycle with an
  **explicitly aggregated** `engine_state` -- `evaluate()` clears collected state per call, so a one-shot end read would
  drop earlier files' TDD `tests_touched` (review finding, regression-pinned).
- **Docs**: design.md §4.1.4 (both shipped pairs, normalization, list cardinality, handler-only caveat) + §4.1.5 (shared
  reason text, per-runtime wire framing); registry codex note (`pretool_policy` stays `"partial"`); `protocols.py`
  docstrings; end-user `hook.md` codex-policy-check section; probe README owes "stage 85" (operator-gated enrolled
  end-to-end).

**Verification**: 57 new unit cases (24 parser, 16 adapter/responder, 17 command incl. the state-aggregation,
payload-cwd, and wire-strictness regressions and two cascade shared-wiring cases) -- full sweep 6118 unit+regression
green; mypy/pyright/pre-commit clean. Docker: `test_policy_hooks.py` 17/17 (7 new Codex cases; 10 pre-existing unchanged
-- extraction moved no Claude bytes) + `test_supervisor_e2e.py` 9/9 (cascade through the extracted registration).

**Deferred**: real-codex enrolled-hook E2E is operator-gated (trust ceremony) -- recorded as probe stage 85; whether
Codex surfaces exit-0 stderr to the agent is unobserved (warnings are advisory).

## 2026-06-10

### Supervisor cascade: tier-1 plan check before the frontier supervisor

**Goal**: Route semantic-supervisor checks through a cheap stateless tier-1 plan check (opt-in `--cascade`) so
clearly-aligned Write/Edit actions short-circuit and only uncertain ones pay the frontier `claude -p --resume` call.

**Key changes**:

- `PolicyEngine.register_resolver()`: a resolver policy runs only when pass-1 emitted `needs_review` and nothing denied;
  `_run_policy()` extraction keeps applies_to/fail-mode/state semantics identical for both passes; `_collected_state`
  cleared per `evaluate()`; `rules_active` uses `registered_policy_ids` (includes the resolver). Cascade off is
  bit-identical to the pre-cascade engine.
- `PlanCheckPolicy` (`semantic.plan_check`, new `policy/semantic/plan_check.py`): one cheap `core.llm` call (tagger
  mechanics, default OpenRouter `google/gemini-3.5-flash`, with per-provider defaults and an approximately 32K-token
  configurable prompt budget) judging the action against the approved-plan snapshot. Prompt packing uses head+tail
  excerpts, keeps diff file/hunk headers when truncated, includes Edit matched/replacement fragments and Write target
  existence context, and tells the checker when plan or action fields were truncated. Emits only `allow` (cached via
  ThrottleCache, plan fingerprint in key) or `needs_review`; every failure path escalates — degrades to frontier-always,
  never to unsupervised. Reasons ride in low-severity violations (clamped 500 chars), never `decision.warnings`, so
  resolved escalations stay silent on the allow path.
- CLI/config: `SupervisorConfig.cascade`/`checker_provider`/`checker_model`/`checker_budget_tokens`;
  `forge policy supervise --cascade/--no-cascade --checker-provider --checker-model` (modifiers with target, standalone
  toggle without); advanced budget tuning stays in session config via
  `forge session set policy.supervisor.checker_budget_tokens <tokens>`; enabling auto-resolves the plan snapshot via the
  `--reload` machinery and fails loud pre-mutation when none resolves; `%policy supervise cascade on|off`; status/show
  surfaces. Existing local LiteLLM backend configs created before `gemini/gemini-3.5-flash` was added must be
  recreated/updated or paired with an explicit served checker model such as `gemini/gemini-2.5-flash`.
- Measurement: decision-log-derived `plan_check_allow`/`plan_check_needs_review` counters (cached allows counted) in
  `forge activity` + summary line; session-tagged `plan-check` ledger events via `emit_direct_llm_usage`. Named
  needs-review (not "escalated") because a tier-1 `needs_review` co-occurring with a deterministic deny skips the
  resolver; actual frontier runs are the supervisor counters.
- Docs: design.md §4.1.2 cascade block + §4.1.5 resolver bullet + CLI row; design_appendix §D ownership + §A.13 emitter
  rows; end-user policy.md cascade subsection.

**Verification**: 5950+ unit/regression tests pass (`-m "not integration"`) incl. 80+ new cases (engine resolver,
plan-check policy, CLI, dispatcher, hook wiring, activity); Docker tier 19/19 (`test_supervisor_e2e.py` +
`test_policy_hooks.py` — escalation resolves aligned/divergent with exactly one frontier invocation, plan-check error
ledger event, CLI wiring persistence, cascade-off regression, plus a `slow`-marked real-LLM short-circuit e2e: the
default checker via the host's port-4001 LiteLLM approves an aligned action with zero frontier invocations);
`make pre-commit` hooks clean on all touched files.

**Deferred**: allow-verdict rationale is debug-logged only — validating false-aligned rates needs shadow-sampling
(follow-up idea on the card).

### codex_frontend Phase 1 follow-up: cross-project trust probe (stage 84) -> SCOPED

**Goal**: Settle the last untested Phase-1 assumption gating the Phase 6 installer story -- does ONE Codex trust
ceremony trust a hook command string in an UNRELATED repo, or only the enrolled project + its `git worktree` checkouts
(82w)?

**Key changes**:

- **New probe** `scripts/experiments/codex-hooks/stages/84-fresh-project.sh` (extends the round-3 fixture harness;
  headless, consumes the stage-80 enrolled fixture, no new ceremony). A fresh `git init` repo at a never-seen `mktemp`
  path registers a byte-identical single-entry SessionStart (same stable `$HOOKBIN/SessionStart.sh` command, differing
  ONLY in the registering config path); the path-stable user-level hook is the positive control. Two legs: 84a (no
  folder trust) then 84b (folder-trust deconfound -- 40b: folder trust alone does not fire hooks, so a fire there is the
  definition hash). Canonicalized `FRESH` (macOS /var->/private/var) so the run cwd matches the trust path; single
  `finish_verdict` exit (restore-from-base + exit-code policy); pre-leg `grep -F` self-guards; rejects
  `PROBE_USE_REAL_CODEX_HOME=1`. Wired into `reproduce.sh` (`FIXTURE_STAGES`, budget); README stage-map + 5-verdict
  vocabulary + de-staled "fixtures are headless-unavailable" bottom section.
- **Finding (real codex 0.139.0): `[CROSS-PROJECT-TRUST-SCOPED]`** -- both legs proj=0 user=1 (turn ran, positive
  control fired -- a real no-fire, not a dead turn), self_enroll=no. Cross-project trust does NOT hold; the 82w worktree
  survival was worktree->checkout canonicalization, not portable command-string trust. **Installer reframe:**
  project-scope = a ceremony per repo; USER-scope (`$CODEX_HOME/config.toml`) = one ceremony covers all projects
  (path-stable).
- **Docs synced**: card Risk bullet (UNTESTED -> RESOLVED/SCOPED) + 82w annotation; checklist new ticked Phase-1 item +
  Worktree/installer-scope Open Decision reframed; design.md §5.5.5 + `registry.py` codex note "per CODEX_HOME" ->
  path-keyed trust + user-scope guidance.

**Verification**: probe ran live on real codex 0.139.0 (2 turns) -> SCOPED, cross-checked against the
`meta/user-config.84{a,b}-after.toml` captures (not just oracle text). `bash -n` clean; shellcheck stage 84 = only info
SC1091 (one fewer finding than the shipped stage 82 -- at parity); `pre-commit` clean on stage/harness/README; the
registry-note edit carries no test assertion (grep clean), runtime/preflight suites rerun green.

### codex_frontend Phase 2 follow-up: suppress Claude display vestiges on Codex `session show`

**Goal**: Stop `session show` printing `Agent: claude-code` and `Model Family: anthropic` for Codex sessions.

**Key changes**: `_print_session_detail` gates the `Agent:` line (display-only `intent.agent` vestige, superseded by
`Runtime:`) and the whole Computed Context block (Claude routing/tier/policy state) on `runtime == "claude_code"`.
Claude sessions render unchanged; `--json` keeps its documented env-derived `context` shape.

**Verification**: new `test_show_human_suppresses_claude_vestiges` + 229 session CLI tests green; mypy clean.

### codex_frontend Phase 2: One-command Codex bridge CLI (`session start --runtime codex`)

**Goal**: Wrap the Phase-5e `bridge_session_to_codex` op in a real session lifecycle -- one command derives a
Codex-runtime session from a Claude parent, runs the first `codex exec` turn, and makes continuation a first-class
`session resume` path.

**Key changes**:

- **CLI**: `forge session start [name] --runtime codex --resume-from <parent> --task "..."` (per the resolved flag-shape
  decision) with `--strategy` (default `ai-curated`), `--depth`, `--sandbox`, `--worktree/--branch`; 17 Claude-only
  flags rejected with codex and 5 codex-only flags rejected without it. `forge session resume <name> --task "..."`
  dispatches on `intent.launch.runtime` before any Claude predicate and runs `codex exec resume <thread_id>` (cross-CWD,
  in the session's recorded worktree, prompt on stdin); `_launch_claude_for_session` refuses codex manifests as a
  backstop. New `cli/session_codex.py` (rendering) + `core/ops/codex_session.py`
  (`start_codex_session`/`continue_codex_session`). `session show` renders Runtime/Thread/Rollout/Auth; JSON adds
  `intent.runtime` + `confirmed.codex`.
- **Manifest**: `LaunchIntent.runtime` (registry ids `claude_code`/`codex`; CLI maps `claude` -> `claude_code`;
  `launch.runtime` blocked in `session set`), new `SessionConfirmed.codex` (`thread_id`, `rollout_path`,
  `rollout_source="discovered_by_thread_id"`, `auth_method`/`auth_source`/`billing_mode` from preflight, `last_run_at`).
  `confirmed.launch` + `claude_session_id` stay unset for codex (Claude-resume predicates refuse for free; ANTHROPIC-key
  posture would misread). Older Forge cannot read new manifests (strict dacite) -- accepted research-preview break; old
  manifests read fine (additive field with default).
- **Invoker**: `CodexStreamResult.thread_id` parsed from `thread.started`; runtime-neutral
  `HeadlessResult.runtime_session_id`; `prepare_codex_request(resume_thread_id=...)` appends the probe-60 form-A
  `resume <tid>` argv. New `core/runtime/codex_rollouts.py` (`find_rollout_path` by thread_id, newest-mtime wins).
- **Transfer/GC**: the snapshot is keyed by the **real session name** (Derivation.context_file -> GC-protected),
  structurally retiring the Phase-5e synthetic-children debt; bridge gains `child`/`preflight`/`output_root` (snapshot
  written under the child's indexed forge_root for nested-project worktrees, same output-root pattern as the fork
  precedent); stale-snapshot guard (reference-checked via new public `gc.referenced_transfer_context_paths()`;
  unreferenced -> replaced with paired `.notes.md`; referenced -> error) and two-phase rollback (guard failure deletes
  only the session; post-guard failure also deletes this run's snapshot+notes).
- **Docs**: design.md §3.4/§3.5/§3.9/§4.0 (one-command frontend shipped, runtime dispatch, `confirmed.codex` ownership);
  end-user `session.md` (Codex workflow + cheat sheet) + `transfer.md` (one-command flow promoted, manual recipe kept
  for sessionless handoffs).
- **Review fixes (pre-merge)**: post-creation lookup/rollback-delete scoped to the child's forge_root -- session names
  are project-scoped, so the unscoped strict resolution raised `AmbiguousSessionError` and stranded the just-created
  session whenever another project had the same name (child root now read from `state.forge_root`, no index round-trip);
  resume refreshes the recorded auth posture (`auth_method`/`auth_source`/`billing_mode`) from the fresh preflight so
  `session show` cannot report the first turn's auth after the user switches Codex auth. Regressions:
  `test_codex_session.py` (cross-project duplicate start + rollback isolation, changed-preflight resume).

**Verification**: ~150 new/extended unit tests green (invoker stream/argv, manifest roundtrip + override rejection,
rollout discovery, bridge extensions, op lifecycle incl. rollback/collision/worktree-ownership GC pinning, CLI flag
matrix/dispatch/rendering); full CLI package 1619 green; mypy/pyright clean. **Live**: real-codex E2E
`tests/integration/core/test_codex_session_start.py` passed (2 real turns) -- verifies the two probe-61 claims as a
standing guard: the `$CODEX_HOME` rollout filename ends with the live stream's thread_id, and stdin-prompt +
`exec resume` recalls turn-1 state with a stable thread id. (Probe stage 61 script written + wired into `reproduce.sh`;
the E2E supersedes its one-shot run.)

### codex_frontend Phase 1 closeout: `pretool_policy` rise + preflight `[hooks.state]` decision

**Goal**: Ship the one code unit Phase 1 deferred for an explicit decision -- align the capability encoding with the
round-3 probe findings before Phase 2 sessions load `design.md` §5.5.5 as context.

**Key changes**:

- **Registry (`core/runtime/registry.py`)**: Codex `pretool_policy` `"none"` -> `"partial"` -- Phase 1 confirmed
  post-enrollment PreToolUse deny (JSON + exit-2) and `updatedInput` mutation headless, refuting the old "unprobed"
  rationale. `"partial"`, not `"full"`: enforcement exists only in trust-enrolled homes, malformed hook output FAILS
  OPEN, and PermissionRequest is unpinned headless. `PolicyEnforcement` comment rewritten (Codex is now the partial
  runtime); the stale Codex `note` claims ("only SessionStart observed", "registration-string dimension unprobed",
  "until pre-enrollment is settled") replaced with the round-3 facts (full event coverage incl. 30e, command string in
  the `trusted_hash`, guided-ceremony posture, worktree survival, fails-open caveat, `Bash`/`apply_patch` tool names).
- **Preflight (`codex_preflight.py`, comments/docstrings only -- behavior unchanged)**: the four forward-pointing "the
  `[hooks.state]` read is Phase 1" notes now record the resolved decision -- the read is deliberately NOT implemented
  (the `trusted_hash` is not black-box computable so a record cannot be validated; enrollment survives worktrees with no
  record at the worktree's config path, so a path-keyed read would false-negative). The seam stays `enrollment_gated`;
  `untrusted` stays reserved, reachable only if a codex-cli source-dive recovers the hash.
- **`design.md` §5.5.5 synced**: `pretool_policy="partial"` with probe facts + caveats; the enrollment parenthetical
  states the settled guided-ceremony posture. Board: card Deliverables 2/3 + checklist Current Focus/Phase 1/Phase 3
  updated.

**Verification**: 63 runtime/preflight/CLI unit tests green (assertions updated to `partial`); mypy clean; stale-claim
grep (`unprobed|only SessionStart|settles pre-enrollment|...`) empty over the normative surfaces (`docs/design.md`,
`docs/design_appendix.md`, `src/`, `tests/src/`) -- the active card/checklist round-2 snapshot lines that quote the
superseded wording are annotated as historical (superseded by round 3) rather than deleted; live
`forge runtime list --json` renders `pretool_policy: partial` + `native_hooks: enrollment_gated`; `make pre-commit`
clean.

### codex_frontend Phase 1: Enrollment-mechanics probe (compacted)

**Goal**: Pin Codex hook enrollment mechanics before building Codex frontend code.

**Key changes / findings**:

- Extended `scripts/experiments/codex-hooks/` with persistent enrolled-fixture stages 80-83, hash-preimage scanning,
  sanitized payload fixtures, and board/design updates.
- Real codex-cli 0.138.0 findings: one guided "trust all" ceremony enrolled headless-firing hooks; the command string is
  part of `trusted_hash`; `trusted_hash` was not black-box computable, so programmatic pre-enrollment remained blocked
  pending source-diving; PreToolUse deny and `updatedInput` mutation worked, while malformed PreToolUse failed open.
- Enrollment survived worktrees of the enrolled project with a path-stable command string, but broad cross-project trust
  remained untested at this phase.

**Verification**: `bash -n`/shellcheck clean, hash-preimage self-test green, live stages 80-83 ran against real codex
0.138.0, captures cross-checked, `sanitize.sh` passed, and `make pre-commit` clean. Detailed probe matrices remain in
git history before compaction.

### codex_frontend Phase 0: Registry correction -- `headless_inert` -> `enrollment_gated`

**Goal**: Correct the Codex hooks capability encoding refuted by gating-probe round 2: trust-enrolled hooks DO fire
under headless `codex exec` (40c2/40d) and interactively (50c) -- the gate is a one-time trust enrollment, not the
execution mode. First code commit of the `codex_frontend` card.

**Key changes**:

- `HookSupport` (registry) and `HookSeam` (preflight) renamed `headless_inert` -> `enrollment_gated` **together**, so
  neither half of the capability model retains the refuted value. Resolves the card's literal-name Open Decision.
- The preflight verdict is pinned as capability-not-state: "hooks can fire, but this preflight has not checked the
  `[hooks.state]` record" -- never treat it as `active`. The per-hook enrollment read is Phase 1.
- Codex `RuntimeSpec` note rewritten to the round-2 facts (trust lives in user `config.toml` `[hooks.state]` keyed by
  the registering config's absolute path; survives script-*content* changes; only SessionStart observed firing).
  `pretool_policy` stays `"none"` (post-enrollment PreToolUse unprobed). `design.md` §5.5.5 synced; card.md stale
  "hook_seam is today honestly `unknown`" line fixed.

**Verification**: 63 runtime/CLI/preflight unit tests green (incl. renamed
`test_enabled_is_enrollment_gated_never_active`); mypy clean; `rg headless_inert docs/design.md src/ tests/` empty; live
`forge runtime list` renders `enrollment_gated` and `forge runtime preflight codex` renders
`Hook seam: enrollment_gated` (render asserted, exit code orthogonal); `make pre-commit` clean.

## 2026-06-04 -- 2026-06-09 (compacted)

- **Codex/runtime_abstraction closeout.** Probe-only Codex frontend evaluation confirmed `codex exec` hooks do not fire
  headless in codex-cli 0.138.0, so SessionStart transfer delivery and headless policy hooks stay no-go while the bridge
  path stays initial-message based. Runtime/preflight capability fields now report `headless_inert`/`none`. Phase 5e
  shipped `bridge_session_to_codex` (parent -> ai-curated Codex transfer -> `codex exec`, one run tree) plus transfer
  curation usage attribution; Phase 5f synced design docs and added the end-user transfer guide. Codex headless runtime,
  preflight, stream parser, unavailable-cost usage, and target-runtime transfer threading shipped in the preceding
  phases.
- **Metric evidence and activity closeout.** Forge cost accounting moved to reported-or-unavailable figures, deleted the
  price catalog, removed strict preflight cap estimates, added reporter/confidence vocabulary, and kept spend caps
  post-event. `forge usage` became `forge activity`; `forge proxy costs reset` now clears telemetry/cap/status-line cost
  state; tombstones and stale migration shims were removed as clean breaks where appropriate.
- **Workspace/status-line hardening.** `project_root` resolution became git-common-dir-derived for linked worktrees,
  `--scope repo` became `--scope workspace`, session pre-seed lifecycle docs were aligned, and status-line producer /
  cap-load / weekly-quota regressions were fixed.
- **Reader and proxy safety fixes.** Cost/audit JSONL readers gained non-object guards; headless retry, parallel
  cleanup, negative-delta, and provenance edge cases from PR review were covered by regressions.
- **Verification highlights**: Codex probe harness stages and runtime/preflight suites green; bridge/transfer/codex
  suites and real-codex E2E green; metric/activity/status-line suites and `make pre-commit` clean. Detailed per-phase
  verification remains in git history before this compaction.

## 2026-06-03 (compacted)

- **runtime_abstraction Phase 4 follow-up**: `forge usage [session]` + session-end summary
  (`read_usage_events(session=)` filter, pure `build_session_activity_summary`; design §3.12/§3.14, appendix §A.13);
  sidecar usage-ledger mount (rw, proxy-id gated). Review fixes: workflow double-count (N-worker panel read as N+1)
  split into `CommandUsage.workers`; supervisor-warning misattribution. QA proxy bugs: accepts mid-conversation
  `{"role":"system"}`; passthrough streaming errors surface real status; QA refuses a stale-revision container.
- **Statusline Enhancement (Phases 1-5)**: config-driven status line — segment registry + lazy `RenderContext`;
  billing-aware cost (`api`→$ / `subscription`→quota / `ambiguous`→`≈$`); throttled file-backed `cache_hit`;
  Forge-unique opt-in segments (`supervisor`/`policy`/`audit`/`drift`); spend-cap proximity. Break: flat
  `show_rate_limits` → opt-in `rate_limits` segment. Golden no-op guard freezes default output.

## 2026-06-02 (compacted)

- **Phase 4 hardening (4a/4c/4d)**: `run_parallel` spawn/register TOCTOU fixed with a lock-guarded `cleanup_started`
  flag (children reaped exactly once; no Ctrl+C hang/orphan); typed `HeadlessResult.cancelled` (cancelled workers emit
  no error usage); `emit_direct_llm_usage` copies `cached_tokens`; both-or-neither `origin_run_id`/`origin_root_run_id`
  contract.
- **Phase 4 integration validation**: `test_policy_hooks.py` 10/10, `test_supervisor_e2e.py` 4/4, real-claude
  memory/workers green. Pre-existing: `test_real_shadow_curation_smoke` fails on a stale `--session` arg (PR #6
  ancestor; test-only, tracked).

## 2026-06-01 (compacted)

**runtime_abstraction Phase 4 (Slices 4a-4f)** — runtime-abstraction core:

- **4a run-tree env**: `RunIdentity` + `FORGE_RUN_ID`/`PARENT`/`ROOT`, orthogonal to `FORGE_DEPTH`; memory writer
  re-roots under the session's origin identity. appendix §F.5/§C.1.
- **4b usage ledger**: durable versioned `~/.forge/usage/events/` (third plane, joined by `request_id`; schema v1 strict
  reads, never-raising writer). design §3.14, appendix §A.13.
- **4c instrument paths**: `track_verb_cost` cost holder; emitters for workflow verbs + memory-writer/supervisor/shadow
  \+ action tagger; conservative `billing_mode` (no key-presence inference).
- **4d HeadlessInvoker**: new `core/invoker/` (`HeadlessRequest`/`Result`/`Attribution` + protocol +
  `ClaudeHeadlessInvoker`); review fan-out moved **verbatim** behind `run_parallel` (the seam is the lifecycle, not
  routing). design §5.5.5.
- **4e runtime registry**: frozen `RuntimeSpec` per runtime in `RUNTIMES` (the capability source Phase 5 reads);
  tri-state capability literals with version gates; `forge runtime list`. Nothing branches on it yet.
- **4f runtime-tagged ActionContext**: `ActionContext.runtime` required attribution (policy engine stays
  runtime-agnostic); Claude halves named behind `HookAdapter`/`HookResponder` protocols. design §4.1.4/§4.1.5.
- **Phase 3 native-relocate** (PASS on Claude 2.1.158): opt-in `forge session fork --resume-mode native-relocate` (host
  only; transfer stays default) with preflights + rollback + dir-scoped cleanup. Bug: `encode_project_path` now maps
  `_`→`-` (Claude 2.1.158 hyphenates underscores). Regression `test_bug_encode_project_path_underscore.py`. design §3.9.
  Deferred: `--rewrite-paths`, sidecar native-relocate, gated default flip.
- **Phase 2 optional audit proxy**: opt-in wire chokepoint (inert by default); orthogonal `wire_shape`
  (`openai_translated`|`anthropic_passthrough`) × `intercept.mode`; thinking-preserving passthrough;
  redact-before-persist audit JSONL (`forge proxy audit show|diff`); sidecar host-persistent mounts. design
  §7.x/§3.4/§3.7. Deferred: real-upstream `@slow` passthrough replay e2e.

## 2026-05-31

**runtime_abstraction Phase 1** — schema-backed curated transfer + `forge transfer` CLI:

- `transfer.py` `_build_ai_curated_output()` emits canonical sections 1-7 + User Notes overlay; `schema_version: 1`,
  `target_runtime` reserved for Phase 5; citations outside the seen turn range dropped so `schema: full` never
  overstates evidence. Three-file artifact model (`generated.md` cache, frozen `children/<child>.md`, `.notes.md`
  overlay). New `forge transfer show|regenerate|edit|diff`. design §3.9 reframes curated transfer as the primary
  cross-boundary substrate; appendix §M.
- Closeout decisions (keep-current): `--review` stays opt-in; `structured` stays the CLI default (`ai-curated` opt-in).
  `ctx` is prior art/inspiration only, never a dependency (appendix §M.4). Schema stable for Phase 5.

## 2026-05-28 — 2026-05-29 (compacted)

- **memory_substrate (PR #8)**: split "handoff" into **memory writer** (Stop-time doc curation) and **transfer**
  (resume/fork context). `handoff_agent.py→memory_writer.py`, `handoff.py→transfer.py`; CLI
  `forge handoff run→forge memory-writer run`, `forge session handoff show→forge memory report show` (old paths
  tombstoned). Durable accept-and-tolerate: `--resume-mode handoff→transfer`, `handoff_timeout→memory_writer_timeout`.
  Intentional `handoff` KEEPs (work-queue `kind="handoff"`, artifact path, `queued_handoff`) recorded in impl_notes.
- **Add Claude Opus 4.8** (retain 4.6+4.7): `claude-opus-4-8` opt-in ($5/$25/$0.50, 1M ctx, adaptive-only); `opus`
  defaults stay on 4.6; 4.8 takes over 4.7's review/template role.
- **Memory strategies 7→4**: removed `debugging`/`patterns`/`suggested` (shadow mode now orthogonal via `--propose`;
  `suggested_*→shadow_*`); `--as`→`--strategy` (`--as` a hidden tombstone). Stale removed-strategy passports rejected.

## 2026-05-22 — 2026-05-26 (compacted)

- **Memory Enhancement project (PR #1, Phases 0-5)**: passport-authoritative doc ownership replacing manifest
  `designated_docs[]`; two primitives — passports select docs, session activation decides whether the writer runs.
  `session/passport.py` (`MemoryStrategy`, YAML frontmatter, `synthesize_passport`, `PassportError`); top-level
  `forge memory enable/track/untrack/list/status` + `forge memory shadows review`. Removed `.forge/memory.yaml`
  activation, `MemoryIntent.designated_docs`, the three-tier resolver, `ProjectMemoryConfig`, `--inherit-memory`. design
  §5.6, appendix §G; card archived to `done/memory_enhancement/`.
- **CLI hardening**: command-shape invariant (groups orient, leaves act) — `forge config show`,
  `forge search query <terms>`, `forge proxy metrics` all-proxies. Shared recovery-tip helpers (`cli/output.py`); break:
  `forge backend create <existing>` errors + exits 1. Auto-start proxies from templates (`ensure_proxy`,
  liveness-aware). Live-session deletion protection (`forge session delete` refuses a live launch without `--force`).
  Regressions: supervisor-proxy-autostart, stale-healthy-proxy, delete-live-session.
