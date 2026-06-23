# Change Log

Completed-work record for Forge implementation sessions.

## Maintenance

- Updated by the memory writer with `strategy=changelog`, and by humans when closing a phase.
- Add compact entries for completed work only. Pending tasks belong in card checklists.
- Follow `docs/developer/board_contract.md` "Change Log Policy": each entry needs Goal, Key changes, and Verification.
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
> `**Verification**:`. Use newest-first order. See `docs/developer/board_contract.md` "Change Log Policy" for the full
> spec.

## 2026-06-23

### forge_cli_cleanup Slice 03: move telemetry surfaces

**Goal**: Co-locate operator observability under `forge telemetry` and clean-break the old scattered paths.

**Key changes**:

- Added `forge telemetry activity|trace|costs`; removed top-level `forge activity`, `forge provider`, and
  `forge proxy costs`.
- Retired `%provider trace` with no `%telemetry` replacement; `%help` no longer advertises it.
- Moved telemetry-cost human output to stdout, kept JSON on stdout, and tightened the single-leaf group guard while
  removing the fixed `forge provider` ledger entry.
- Updated CLI docs, end-user guides, QA checklists, design breadcrumbs, integration activity coverage, and agent-facing
  guidance.

**Verification**: telemetry-focused unit/hooks suite (213 passed); targeted activity integration (1 passed); `uv build`;
`make pre-commit`.

### forge_cli_cleanup Slice 04: move backend under `forge model`

**Goal**: Build the decided `forge model` namespace and clean-break the old top-level backend path.

**Key changes**:

- Added `forge model` with visible children `backend` and `catalog`; `catalog` renders the static model catalog with
  `--json`.
- Moved all backend verbs to `forge model backend`; old `forge backend ...` now falls through to Click's native "No such
  command" handling.
- Updated recovery tips, shipped QA/config templates, integration harness/fixture paths, `AGENTS.md`, docs, impl notes,
  and command-tree invariant debt (`forge model backend show`, plus `catalog` in the read-leaf JSON guard).
- Kept `forge workflow list-models` as runtime readiness and reworded it to "workflow models".

**Verification**: focused unit/regression slice (69 passed); backend integration (8 passed); proxy smoke (1 passed);
`uv build`; CLI sanity checks; `make pre-commit`.

### forge_cli_cleanup Slice 06: remove `forge session context` (clean break)

**Goal**: Drain the last hidden CLI tombstone — remove the deprecated `forge session context` alias so the surface
relies on Click's native "No such command" instead of a redirect shim.

**Key changes**:

- Deleted the hidden `forge session context` command and its now-dead `_print_session_context` helper from
  `session_manage.py` (plus the two `__all__` exports). The behavior already lives in `forge session show`
  (`--json`/`--field`).
- Kept the `forge.core.ops.session_context` module — still used by `session show`, `activity`, `policy`, and the
  `%`-direct commands. Corrected its "Used by" docstring and two mis-attributed comments in `session_manage.py`.
- Dropped the `session context` note from `cli_reference.md`; fixed the now-stale "deprecated" reference in
  `impl_notes.md`.
- Deleted `tests/src/cli/test_session_context.py` (removed code → delete test); the ops test
  `tests/src/core/ops/test_session_context.py` stays.

**Verification**: `forge session context` exits 2 with Click "No such command" (no tombstone). Tombstone sweep confirmed
`context` was the only deprecated-alias `hidden=True` command (`hook`/`memory-writer`/`status-line`/`policy shadow run`
are live internals). 267 tests pass across `test_session_commands`, `test_session_context` (ops),
`test_command_tree_invariants`, `test_activity`, `test_policy_shadow`, `test_direct_commands_provider`.

### forge_codex_command_group closeout: sessionless Codex proxy launcher card

**Goal**: Close the active `forge_codex_command_group` card after the status surface, Responses passthrough transport,
and sessionless `forge codex start --proxy` launcher shipped.

**Key changes**:

- Moved the card from `doing/` to `done/` and updated its checklist/card closeout state.
- Synced end-user docs for the sessionless Codex proxy launch path, including the `codex-responses-local` template,
  Responses-capable proxy requirement, env scrub/no-`config.toml` boundary, and `openai-api` credential ownership.
- Promoted durable implementation notes for the Codex Responses passthrough and launcher identity/capability gates.
- Recorded the remaining live 200 reasoning round-trip as an accepted operator residual: it still needs a working
  OpenAI/LiteLLM key, but the routing/launcher path has been verified up to upstream 401/429.

**Verification**: Docs-only closeout; `make pre-commit-md` clean.

### forge_codex_command_group Phase 4: `forge codex start --proxy` launcher

**Goal**: Ship the sessionless, proxy-backed Codex TUI launcher -- the consumer the card was built for -- on top of the
Phase 3 Responses transport.

**Key changes**:

- **CLI** (`src/forge/cli/codex.py`): new `forge codex start --proxy <id-or-template> [--sandbox] [-- codex-args]` leaf.
  Order: codex-installed -> hard version gate -> `ensure_proxy` -> capability gate -> exec, with the full error matrix
  on a stderr `Console` via `forge.cli.output` helpers (closes the Phase 1 stderr-Console deferral).
- **Version gate** (`core/runtime/codex_preflight.py`): `CODEX_PROXY_CONTRACT_VALIDATED = "0.141.0"` +
  `codex_proxy_contract_blocker()`. Fail-closed below the floor (parsed only); unparseable/None allowed. Distinct
  surface from the 0.139.0 probe ceiling and the 0.131.0 hook floor.
- **Capability gate** (`proxy/proxy_orchestrator.py`): `assert_proxy_responses_capable()` + `ProxyUnreachableError` /
  `ProxyNotResponsesCapableError`. Requires the full `wire_shape == openai_responses_passthrough` AND
  `capabilities.responses_ingress` conjunction off `GET /` (mirrors the runtime route gate); returns the proxy's
  default-tier model. **Review fix**: also re-verifies proxy identity (`is_proxy` + `proxy_id` + `template`) from the
  same body via `expected_proxy_id`/`expected_template`, raising `ProxyIdentityMismatchError` -- `ensure_proxy` returns
  exact ids by registry presence, not liveness, so a stale entry on a reused port can't misroute Codex to a different
  proxy.
- **Bare invocation** (`session/codex_invoke.py`): `invoke_codex_bare_proxy` + pure env/argv builders.
  `_CODEX_BARE_PROXY_STRIP_VARS` scrubs native codex/OpenAI auth, the 5 OpenAI account/routing vars, and
  session/run-tree identity; re-establishes NO native auth (the proxy owns upstream); list-mode `-c` provider argv; `-m`
  auto-default suppressed when the user passes one; never `--strict-config`.
- **Allowlist**: removed `forge codex` from `SINGLE_LEAF_GROUP_ALLOWLIST` (now 2 leaves); updated the registration test.
- **Docs**: `cli_reference.md` `start` row; `design.md` §3.4 "Bare launch (Codex)" + §3.7 consumer cross-ref.

**Verification**: 62 new unit tests (version blocker, capability + identity gate, env/argv/invoke, CLI matrix) pass;
full `tests/src/cli` suite green; `make pre-commit` clean. Live gate: real codex 0.141.0 routed via the list-mode `-c`
argv to `POST /v1/responses`, and the identity check was live-verified against a real proxy body (correct id passes,
wrong id rejects). The 200 reasoning round-trip stays credential-blocked (dead key), as in Phase 3.

## 2026-06-22

### forge_codex_command_group Phase 3: Codex Responses proxy transport (passthrough)

**Goal**: Give Forge's proxy a Codex-facing OpenAI **Responses** ingress so `forge codex start --proxy` (Phase 4) has a
Responses-capable proxy, and flip the dead `proxy_supported` preflight posture live — without dropping Codex's
reasoning-item continuity.

**Key changes** (revises card Slice 2: passthrough, not the originally-scoped translating transport — translation drops
signed reasoning):

- New `openai_responses_passthrough` wire shape forwards Codex's raw `/v1/responses*` traffic byte-for-byte. Shared
  SSE-teardown core extracted to `proxy/stream_relay.py` (Anthropic passthrough's 32 tests unchanged);
  Responses-specific forwarding in `proxy/responses_passthrough.py` (Bearer injection + strip inbound
  auth/`OpenAI-Organization`/`-Project`, tolerant usage side-tap, `x-litellm-response-cost` USD→micros, response-header
  allowlist that also drops the proxy-owned `x-request-id`).
- `proxy/responses_ingress.py` (new): the FastAPI\<->transport glue — the `/v1/responses*` handler, route registrar
  (`POST /v1/responses` create before the `{rest:path}` catch-all), and GET / advertisement helpers. Route gated on
  `wire_shape == openai_responses_passthrough` **and** the source's `responses_ingress` else 501; bodyless GET/DELETE
  never call `.json()`. Extracted from `server.py` to keep that module under the 2.5k-line cap (reads proxy runtime
  state via a lazy `import forge.proxy.server`, which also avoids a load-time cycle). `server.py` registers the routes
  and uses the helpers in `GET /`.
- `backend/sources.py`: `responses_ingress` capability, `codex-responses-local` source/template (litellm-local upstream
  so cost is reported), `source_bearer_auth_env_var()` (single secret env var; fail-closed on 0/>1).
- `core/runtime/codex_preflight.py`: `proxy_supported` now returned, gated on the **same** wire_shape ∧
  `responses_ingress` conjunction the route enforces (file-read preflight can't green-light a proxy the runtime would
  501).
- `proxy_orchestrator.py`: smoke test POSTs a Responses request for this wire shape.
- Accounting precision (pre-merge review): cost/metrics/spend-cap are wired only for the generation endpoint
  (`POST /v1/responses`), so a `GET /v1/responses/{id}` retrieve echoing the original `usage` can't double-count; the
  `OnComplete` callback now carries `error_type`, and a terminal `response.failed` (streamed or non-streamed 200) folds
  into `failed=True` instead of being recorded as success (`response.incomplete` stays a billed partial success).
- Docs: `docs/design.md` §3.4 wire-shape section.

**Verification**: 54 unit tests (`tests/src/proxy/test_responses_transport.py`, incl. the accounting-gate +
terminal-status regressions) + preflight conjunction cases; full unit suite green (6702 passed) — the new source's only
ripple was the `backend list` shared-instance test (codex-responses-local is an OpenAI-credentialed co-tenant of
litellm-4000, now in its `shared_with`); `make pre-commit` clean. **Live gate** (real `codex-cli 0.141.0` → forge
`:8105` → litellm `:4000` → OpenAI): `GET /` advert + intercept table confirmed; codex drove `POST /v1/responses`
(streaming) through the route (not 501), single `X-Request-ID` relayed back. **Deferred**: a 200 reasoning round-trip is
credential-blocked (this env's `OPENAI_API_KEY` is dead) — must be re-confirmed with a live key before the card closes.

### forge_codex_command_group Phase 1: `forge codex status` (read-only Codex inspection)

**Goal**: Ship the read-only Codex inspection surface as the first independently-shippable slice of the codex
command-group card; the proxy-backed launcher stays parked behind the Phase 2 probe.

**Key changes**:

- New `forge codex` group (`src/forge/cli/codex.py`) with one leaf, `status`: reports binary + version
  (`get_runtime("codex").detect()`), per-scope Codex config path, managed-block presence, Forge-only event-aware
  registration pairs, and a static enrollment posture (`yes/no/partial/wrong-event`). Never claims enrollment — points
  to `forge runtime preflight codex --verify-enrollment`.
- Scope resolution mirrors the installer: default = detected scope via `find_forge_installation` (else user);
  project/local roots resolve by walking up for `.git`/`.codex` (not bare cwd); `--all` lists user/project/local
  distinctly (config collapses project\<->local, but tracking is scope-keyed).
- `start` deliberately **not** shipped: a no-`--proxy` placeholder that always errors would be a tombstone and could pin
  a `--proxy` contract the Phase 2 kill criterion may invalidate. `forge codex` is allowlisted as intentional
  single-leaf phasing debt in `SINGLE_LEAF_GROUP_ALLOWLIST` (remove when `start --proxy` ships in Phase 4).
- Docs: `cli_reference.md` "Codex management" section.

**Verification**: 14 unit tests in `tests/src/cli/test_codex_status.py` (scope detection, subdir root resolution,
`--all` local, Forge-only filter, wrong-event, no-`start`-command) plus tree-invariant + output guards = 31 pass;
`make pre-commit` clean (mypy, pyright, ruff, black, isort, mdformat).

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

## 2026-06-10 -- 2026-06-14 (compacted)

- **Codex frontend shipped as a first-class alternate runtime.** Phases 2-6 added the one-command Codex launch path
  (`forge session start/resume --runtime codex`), hook adapter/responder surfaces, SessionStart transfer delivery,
  interactive TUI support, codex-hooks installation/enrollment plumbing, capability/version guards, and review fixes
  around fork/rollback isolation, enrollment state, policy persistence, handoff artifacts, and invoker behavior. The
  closeout moved the card to done and recorded remaining empirical enrollment residuals.
- **Deferred Codex items remain tracked** (full detail in `done/codex_frontend/` and `done/runtime_abstraction/`):
  app-server transport (`codex app-server`/`--stdio`, unevaluated by scope decision), filing the upstream fail-open
  issue (draft ready), and the PermissionRequest/`trusted_hash` source-dive (documented-not-built).
- **Codex probe and enrollment evidence was preserved at the decision level.** Stages 84-87 covered cross-project trust,
  version churn, guided enrollment, and interactive reattach smoke paths. The durable outcome was that trust is scoped,
  `pretool_policy` is partial/enrollment-gated, SessionStart additional context is viable when enrolled, and some
  guided/operator steps remain intentionally external to non-interactive automation.
- **Supervisor/session work landed in parallel.** Supervisor cascade added tier-1 plan checks before the frontier
  supervisor; launch controls gained cascade/reasoning-effort parity across subprocesses; shadow sampling measured
  false-aligned cascade outcomes; same-dir transfer forks decoupled transfer mode from worktree isolation.
- **Verification highlights**: focused Codex runtime/hook/session suites, real-Codex E2E probes, supervisor cascade and
  shadow suites, same-dir transfer fork regressions, mypy/pyright, and `make pre-commit` were run across the compacted
  work. Detailed per-phase matrices remain in git history before this compaction.

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
