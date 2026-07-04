# Inventory -- backend_instance_identity_model

Phase 1 work-product only. This file records today's contracts so Phase 2 can decide the target identity model without
silently changing compatibility promises. It is not a design-doc promotion.

The reader/writer lists name the load-bearing paths found during the Phase 1 sweep. They are representative, not a
mechanical rename checklist; any Phase 3 field migration must re-grep from scratch.

## Boundary Tags

- **Strict durable state**: Forge-owned persisted state, code-defined catalogs, or validated in-memory contracts where
  unknown/corrupt values should fail or be explicitly migrated.
- **System boundary**: user-owned config, historical logs, or external input where unknown values should be handled by a
  documented compatibility/degradation path.
- **Display-only**: derived CLI/help/read output. These surfaces can still be public machine output, but they are not
  the source of truth for attribution or routing.

## Machine Contracts

### `ModelSource.id`

- **Boundary:** strict durable state (code-defined catalog).
- **Writers:** `src/forge/backend/sources.py` (`BUILTIN_MODEL_SOURCES`, `ModelSource`).
- **Readers:** `src/forge/backend/sources.py` (`get_model_source`, `resolve_model_source_id`,
  `model_source_for_template`), `src/forge/core/lanes.py`, `src/forge/config/loader.py`, `src/forge/cli/backend.py`,
  `src/forge/core/ops/backend_reconcile.py`, `src/forge/backend/remote/base.py`,
  `src/forge/proxy/provider_trace_logger.py`, `src/forge/proxy/responses_ingress.py`,
  `src/forge/core/runtime/codex_preflight.py`.
- **Current meaning:** canonical catalog id for a model backend/source row such as `openrouter`, `claude-max`, or
  `litellm-gemini-local`. It is also the value that many current `backend_id` fields carry.
- **Migration note:** high-risk rename target. Template aliases are already accepted through `template_names`, but
  canonical ids are persisted in proxy config, lane records, telemetry, and public JSON.

### `ModelSource.template_names`

- **Boundary:** strict durable state (code-defined catalog).
- **Writers:** `src/forge/backend/sources.py`.
- **Readers:** `src/forge/backend/sources.py` (`resolve_model_source_id`, `model_source_for_template`),
  `src/forge/config/loader.py`, `src/forge/core/auth/template_secrets.py`.
- **Current meaning:** compatibility and template-name aliases that resolve to one canonical `ModelSource.id`.
- **Migration note:** this is the existing alias mechanism to preserve old names while a successor id model is
  introduced.

### `proxy.backend` in proxy templates

- **Boundary:** system boundary on input, strict at template load.
- **Writers:** shipped templates under `src/forge/config/defaults/templates/`; user template copies under the Forge
  home.
- **Readers:** `src/forge/config/loader.py` (`read_template`, `_resolve_template_backend`, `_apply_template_backend`),
  `src/forge/core/auth/template_secrets.py`.
- **Current meaning:** template-declared backend instance id, alias, or unambiguous backend-kind shorthand.
  `_apply_template_backend` rejects old `proxy.source`, invalid, unknown, missing, ambiguous, or runtime-native values
  and canonicalizes to the backend instance id before schema loading.
- **Migration note:** S2 took the clean-break path for old `proxy.source`: template load fails loudly with a migration
  tip instead of retaining a compatibility reader.

### `ProxyConfig.backend` and runtime `proxy.yaml` `backend`

- **Boundary:** `ProxyConfig.backend` is strict while creating from a template; persisted `ProxyInstanceConfig.backend`
  in `proxy.yaml` is a system boundary at runtime.
- **Writers:** `src/forge/config/loader.py` writes canonical `proxy.backend` into template data;
  `src/forge/proxy/proxy_orchestrator.py` copies it into `ProxyInstanceConfig.backend`.
- **Readers:** `src/forge/config/schema.py` (`ProxyConfig`, `ProxyInstanceConfig`), `src/forge/proxy/server.py`
  (`_backend_instance_id`), `src/forge/proxy/responses_ingress.py`, `src/forge/core/runtime/codex_preflight.py`.
- **Current meaning:** canonical backend instance id when known. Runtime `proxy.yaml` unknowns warn once and degrade by
  returning the raw value; missing backend disables downstream attribution, provider trace, and provider-user grouping.
- **Migration note:** runtime `proxy.yaml` cannot become reject-on-unknown without changing the current system-boundary
  invariant.

### Proxy route JSON `source` and `ProxyIdentity.source`

- **Boundary:** display-only/public machine output, not canonical backend identity storage.
- **Writers:** `src/forge/proxy/server.py` (`_inspect_route`) writes route metadata with `"backend"` carrying the
  configured backend instance id; the root proxy response writes `proxy.source` from `ProxyIdentity.source`.
- **Readers:** request audit/guard context, proxy status/launch-preflight consumers, and external clients that inspect
  the proxy's JSON responses.
- **Current meaning:** `_inspect_route().backend` is backend identity. `ProxyIdentity.source` is a separate provenance
  axis (`registry` vs `derived`) for how the proxy identity was established.
- **Migration note:** S4 removed the legacy route `"source"` key with no alias. Do not rename `ProxyIdentity.source` as
  part of backend identity cleanup; it is intentionally provenance, not model backend identity.

### Legacy `BackendInstance.backend_id` / current `ManagedBackendProcess.process_id`

- **Boundary:** strict durable state in the local backend registry.
- **Writers:** `src/forge/backend/__init__.py` (`BackendManager.ensure_backend`, `stop_backend`),
  `src/forge/backend/adapters/litellm.py`, tests that construct registry fixtures.
- **Readers:** `src/forge/backend/registry.py`, `src/forge/backend/__init__.py`, `src/forge/cli/backend.py`.
- **Current meaning:** local managed process id, currently adapter plus port, e.g. `litellm-4000`.
- **Migration note:** S3 renamed the code/schema object to `ManagedBackendProcess.process_id` and registry schema v2
  clean-breaks old v1 `backend_id` process records with a rebuild/recreate tip. This is not the same axis as
  `ModelSource.id`. It is local-lifecycle-only; remote backends do not have registry processes today.

### Backend registry `~/.forge/backends/index.json`

- **Boundary:** strict durable state.
- **Writers:** `src/forge/backend/registry.py` (`BackendRegistryStore.write`, `update`),
  `src/forge/backend/__init__.py`, `src/forge/cli/backend.py` lifecycle commands.
- **Readers:** `src/forge/backend/registry.py`, `src/forge/backend/__init__.py`, `src/forge/cli/backend.py`.
- **Current meaning:** Forge-owned index of local managed processes keyed by `ManagedBackendProcess.process_id` under a
  schema-v2 `processes` map.
- **Migration note:** registry shape is not suitable as the only future backend-instance registry because it is
  local-lifecycle state only; non-local remote instances need separate persistence/config, not fake lifecycle state.

### `forge model backend ... --json`

- **Boundary:** display-only public machine output.
- **Writers:** `src/forge/cli/backend.py` (`_source_record`, `_managed_process_record`, `show_cmd`, `test_auth_cmd`).
- **Readers:** external scripts/users; guard tests in `tests/src/cli/test_backend_commands.py` and
  `tests/src/cli/test_output_streams.py`.
- **Current meaning:** source rows expose `"backend_instance_id": source.id`; local process details live under
  `"managed_process"` with `"process_id": ManagedBackendProcess.process_id`. Process-only fallback output uses
  `"managed_process_id"`.
- **Migration note:** S4 removed the old `"source_id"`, `"runtime_instance"`, nested process `"backend_id"`, and
  top-level CLI JSON `"backend_id"` identity aliases. The coupled internal names also moved:
  `_runtime_instance_record(...)` to `_managed_process_record(...)`, and `BackendEnsureResult.instance` to
  `BackendEnsureResult.process`.

### Downstream telemetry `source_id`, `source_kind`, and `backend_id`

- **Boundary:** strict durable state for new writes; system boundary for historical log reads.
- **Writers:** `src/forge/core/telemetry/downstream.py`, `src/forge/proxy/cost_logger.py`,
  `src/forge/proxy/provider_trace_logger.py`, `src/forge/proxy/audit_logger.py`, `src/forge/proxy/responses_ingress.py`,
  `src/forge/core/usage/emit.py`.
- **Readers:** `src/forge/core/telemetry/downstream.py`, `src/forge/core/ops/usage_summary.py`,
  `src/forge/core/ops/backend_reconcile.py`, `src/forge/cli/activity.py`, `src/forge/cli/telemetry.py`,
  `src/forge/cli/session_lifecycle.py`.
- **Current meaning:** `source_id`/`source_kind` are origin/correlation fields (`proxy`, `provider`, reporter);
  `backend_id` is backend-instance attribution when known. Proxy-origin writers populate it from runtime
  `proxy.backend`; direct emitters map known providers/reporters to backend instance ids (`anthropic-direct`,
  `openrouter`).
- **Migration note:** OQ-2 is the load-bearing decision. Do not collapse `backend_id` into the `source_id`/`source_kind`
  origin axis. S5 bumps the downstream schema to `schema_version=2` for the backend-instance identity break and skips
  missing/older downstream schemas in current read paths instead of silently reattributing historical records; activity
  and cost views surface skipped legacy-schema counts so a fully fenced window does not look like ordinary empty data.

### Usage ledger `UsageEvent.runtime`

- **Boundary:** strict durable state for usage events.
- **Writers:** `src/forge/core/usage/emit.py`.
- **Readers:** `src/forge/core/usage/ledger.py`, `src/forge/core/ops/usage_summary.py`, `src/forge/cli/activity.py`.
- **Current meaning:** lane/runtime vocabulary (`claude_code`, `codex`, `gemini`, `core_llm`), not model backend kind,
  backend instance, or local process.
- **Migration note:** keep runtime out of the backend-instance model except where a lane says which runtime can reach a
  backend.

### `Lane.backend_id` and `LaneRecord.backend_id`

- **Boundary:** `Lane.backend_id` is a strict validated in-memory contract; `LaneRecord.backend_id` is strict durable
  session state with drift-tolerant reads.
- **Writers:** lane constants and callers under `src/forge/session/`, `src/forge/policy/`, and
  `src/forge/session/consumer_lanes.py`.
- **Readers:** `src/forge/core/lanes.py`, `src/forge/session/models.py`, `src/forge/session/consumer_lanes.py`, session
  memory/shadow/supervisor/team dispatch paths.
- **Current meaning:** canonical `ModelSource.id` after alias normalization. Persisted manifest records deliberately do
  not validate against today's catalog on raw read; billing helpers return `None` on drift instead of substituting.
- **Migration note:** any successor backend identity needs compatibility for stored session manifests and lane
  constants.

### Remote reconciliation adapter registry and result identity

- **Boundary:** strict code registry plus public op result surface.
- **Writers:** `src/forge/backend/remote/base.py`, remote adapter modules such as
  `src/forge/backend/remote/openrouter.py`, `src/forge/core/ops/backend_reconcile.py`.
- **Readers:** `src/forge/core/ops/backend_reconcile.py`, `src/forge/cli/backend.py`.
- **Current meaning:** the remote adapter registry still has an internal `source_id` attribute matching the catalog id,
  while the public reconcile op/result surface uses `backend_instance_id`. `render_reconcile_lines` prints
  `backend=<id>`.
- **Migration note:** S4 removed the public reconcile `source_id` result field, `source=<id>` text, and "backend source"
  errors in `backend_reconcile.py`. The remote adapter registry's internal `source_id` is not a public CLI/backend JSON
  identity key.

### Adjacent derivations intentionally excluded from identity axes

- **Boundary:** derived route/auth/lifecycle facts, not canonical identity fields.
- **Fields:** `proxy.family`, template/config `backend_dependency`, and `TEMPLATE_ENV_VARS`.
- **Owners/readers:** `src/forge/config/schema.py`, `src/forge/config/loader.py`,
  `src/forge/core/auth/template_secrets.py`, `docs/design_appendix.md`.
- **Current meaning:** these are derived from or adjacent to `ModelSource`/template data: route family, local lifecycle
  dependency, and template-facing credential compatibility.
- **Migration note:** they may need updates when source/backend identity moves, but they are not themselves the object
  id, instance id, telemetry attribution key, or CLI JSON identity surface.

## Human-Facing Term Inventory

- **Already migrated by C2:** `forge model backend` help, tables, `docs/cli_reference.md`, `docs/end-user/proxy.md`, and
  `docs/design_appendix.md` §A.2.1 use "backend", "backend instance", and "adapter" for public CLI concepts. The
  `runtime` word remains reserved for the agent/runtime axis.
- **Machine names intentionally still visible:** `source_id`, `source_kind`, `ModelSource`, and telemetry `backend_id`
  remain because they are telemetry/config/code contracts, not prose cleanup. The main literal-bearing docs are
  `docs/end-user/proxy.md`, `docs/design.md`, `docs/design_appendix.md`, and this board card/checklist.
- **Design/docs literals:** `proxy.source` is visible only as a legacy rejected config field; `ModelSource` is the
  current implementation object; `backend_dependency` and `TEMPLATE_ENV_VARS` are derived compatibility surfaces. Those
  should not be renamed until the Phase 2 model and Phase 3 compatibility plan exist.

## Local LiteLLM Sharing

- The concrete many-to-one case is one managed local process, `litellm-4000`, backing multiple local catalog rows:
  `litellm-gemini-local`, `litellm-openai-local`, and any other local LiteLLM source whose required env vars match the
  process config.
- `src/forge/cli/backend.py` derives the display relationship through `_local_source_matches_backend_config`,
  `_managed_process_for_source`, and `_process_source_map`; list/show then render `(shared)` and `shared_with`.
- This matching is **display-only**. It must not become telemetry attribution. Telemetry attribution currently follows
  the proxy's configured backend/catalog id through `_backend_instance_id`, while the local process id remains
  `ManagedBackendProcess.process_id`.

## Phase 2 Feed

- The current `ModelSource` object mixes catalog identity, endpoint/auth/capabilities, template aliases, local
  lifecycle, runtime-native reachability, and billing posture.
- There are already three distinct identity axes using overlapping names: catalog source ids, local process instance
  ids, and telemetry/lane backend ids.
- `proxy.backend` has two different validation postures: strict for templates, warn-and-degrade for runtime
  `proxy.yaml`; old `proxy.source` has no compatibility reader.
- Remote backends are static catalog rows today. Adding duplicate remote instances requires a new persistence/config
  story, not just renaming `ModelSource.id`.
