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

### `proxy.source` in proxy templates

- **Boundary:** system boundary on input, strict at template load.
- **Writers:** shipped templates under `src/forge/config/defaults/templates/`; user template copies under the Forge
  home.
- **Readers:** `src/forge/config/loader.py` (`read_template`, `_resolve_template_source`, `_apply_template_source`),
  `src/forge/core/auth/template_secrets.py`.
- **Current meaning:** template-declared source/catalog id or alias. `_apply_template_source` rejects invalid, unknown,
  missing, or runtime-native values and canonicalizes to `source.id` before schema loading.
- **Migration note:** any successor spelling needs a template-input compatibility reader and clear errors for old,
  unknown, and ambiguous values.

### `ProxyConfig.source` and runtime `proxy.yaml` `source`

- **Boundary:** `ProxyConfig.source` is strict while creating from a template; persisted `ProxyInstanceConfig.source` in
  `proxy.yaml` is a system boundary at runtime.
- **Writers:** `src/forge/config/loader.py` writes canonical `proxy.source` into template data;
  `src/forge/proxy/proxy_orchestrator.py` copies it into `ProxyInstanceConfig.source`.
- **Readers:** `src/forge/config/schema.py` (`ProxyConfig`, `ProxyInstanceConfig`), `src/forge/proxy/server.py`
  (`_backend_source_id`), `src/forge/proxy/responses_ingress.py`, `src/forge/core/runtime/codex_preflight.py`.
- **Current meaning:** canonical model-source id when known. Runtime `proxy.yaml` unknowns warn once and degrade by
  returning the raw value; missing source disables downstream attribution, provider trace, and provider-user grouping.
- **Migration note:** runtime `proxy.yaml` cannot become reject-on-unknown without changing the current system-boundary
  invariant.

### `BackendInstance.backend_id`

- **Boundary:** strict durable state in the local backend registry.
- **Writers:** `src/forge/backend/__init__.py` (`BackendManager.ensure_backend`, `stop_backend`),
  `src/forge/backend/adapters/litellm.py`, tests that construct registry fixtures.
- **Readers:** `src/forge/backend/registry.py`, `src/forge/backend/__init__.py`, `src/forge/cli/backend.py`.
- **Current meaning:** local managed process instance id, currently adapter plus port, e.g. `litellm-4000`.
- **Migration note:** this is not the same axis as `ModelSource.id`. It is local-lifecycle-only; remote backends do not
  have registry instances today.

### Backend registry `~/.forge/backends/index.json`

- **Boundary:** strict durable state.
- **Writers:** `src/forge/backend/registry.py` (`BackendRegistryStore.write`, `update`),
  `src/forge/backend/__init__.py`, `src/forge/cli/backend.py` lifecycle commands.
- **Readers:** `src/forge/backend/registry.py`, `src/forge/backend/__init__.py`, `src/forge/cli/backend.py`.
- **Current meaning:** Forge-owned index of local process instances keyed by `BackendInstance.backend_id`.
- **Migration note:** registry shape is not suitable as the only future backend-instance registry unless Phase 2 decides
  how non-local remote instances persist without fake lifecycle state.

### `forge model backend ... --json`

- **Boundary:** display-only public machine output.
- **Writers:** `src/forge/cli/backend.py` (`_source_record`, `_runtime_instance_record`, `show_cmd`, `test_auth_cmd`).
- **Readers:** external scripts/users; guard tests in `tests/src/cli/test_backend_commands.py` and
  `tests/src/cli/test_output_streams.py`.
- **Current meaning:** source rows expose both `"backend_id": source.id` and `"source_id": source.id`; local runtime
  details live under `"runtime_instance"` with its own `"backend_id": instance.backend_id`. Unmatched local instances
  use `"source_id": null`.
- **Migration note:** this duplicated shape is intentionally transitional from C2. A Phase 3 JSON migration should be
  explicit, tested, and not bundled with help-text cleanup. The `runtime_instance` key itself is also a first-class OQ-1
  JSON-migration candidate if the target term is "backend instance"; do not leave it behind as accidental
  runtime-vocabulary residue.

### Downstream telemetry `source_id`, `source_kind`, and `backend_id`

- **Boundary:** strict durable state for new writes; system boundary for historical log reads.
- **Writers:** `src/forge/core/telemetry/downstream.py`, `src/forge/proxy/cost_logger.py`,
  `src/forge/proxy/provider_trace_logger.py`, `src/forge/proxy/audit_logger.py`, `src/forge/proxy/responses_ingress.py`,
  `src/forge/core/usage/emit.py`.
- **Readers:** `src/forge/core/telemetry/downstream.py`, `src/forge/core/ops/usage_summary.py`,
  `src/forge/core/ops/backend_reconcile.py`, `src/forge/cli/activity.py`, `src/forge/cli/telemetry.py`,
  `src/forge/cli/session_lifecycle.py`.
- **Current meaning:** `source_id`/`source_kind` are origin/correlation fields (`proxy`, `provider`, reporter);
  `backend_id` is catalog attribution when known. Proxy-origin writers populate it from runtime `proxy.source`; direct
  emitters map known providers/reporters to catalog ids (`anthropic-direct`, `openrouter`).
- **Migration note:** OQ-2 is the load-bearing decision. Do not collapse `backend_id` into the `source_id`/`source_kind`
  origin axis, and do not silently reattribute historical records.

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

### Remote reconciliation adapter `source_id`

- **Boundary:** strict code registry plus public op result surface.
- **Writers:** `src/forge/backend/remote/base.py`, remote adapter modules such as
  `src/forge/backend/remote/openrouter.py`.
- **Readers:** `src/forge/core/ops/backend_reconcile.py`, `src/forge/cli/backend.py`.
- **Current meaning:** remote adapter registry key matching the model-source catalog id.
- **Migration note:** current errors/output still say "backend source" and `render_reconcile_lines` prints
  `source=<id>`. Treat that as a machine-contract residue, not a C2 public-wording target that should be edited
  casually.

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
- **Machine names intentionally still visible:** `source_id`, `source_kind`, `runtime_instance`, `proxy.source`,
  `ModelSource`, and telemetry `backend_id` remain because they are JSON/config/code contracts, not prose cleanup. The
  main literal-bearing docs are `docs/end-user/proxy.md`, `docs/design.md`, `docs/design_appendix.md`, and this board
  card/checklist.
- **Design/docs literals:** `proxy.source` is a literal legacy config field; `ModelSource` is the current implementation
  object; `backend_dependency` and `TEMPLATE_ENV_VARS` are derived compatibility surfaces. Those should not be renamed
  until the Phase 2 model and Phase 3 compatibility plan exist.
- **Residual ambiguous wording to revisit only with schema work:** backend reconciliation still has `source_id` result
  fields, "backend source" errors, and `source=<id>` text output in `src/forge/core/ops/backend_reconcile.py`.

## Local LiteLLM Sharing

- The concrete many-to-one case is one local registry instance, `litellm-4000`, backing multiple local catalog rows:
  `litellm-gemini-local`, `litellm-openai-local`, and any other local LiteLLM source whose required env vars match the
  process config.
- `src/forge/cli/backend.py` derives the display relationship through `_local_source_matches_backend_config`,
  `_runtime_instance_for_source`, and `_instance_source_map`; list/show then render `(shared)` and `shared_with`.
- This matching is **display-only**. It must not become telemetry attribution. Telemetry attribution currently follows
  the proxy's configured source/catalog id through `_backend_source_id`, while the local process id remains
  `BackendInstance.backend_id`.

## Phase 2 Feed

- The current `ModelSource` object mixes catalog identity, endpoint/auth/capabilities, template aliases, local
  lifecycle, runtime-native reachability, and billing posture.
- There are already three distinct identity axes using overlapping names: catalog source ids, local process instance
  ids, and telemetry/lane backend ids.
- `proxy.source` has two different compatibility postures: strict for templates, warn-and-degrade for runtime
  `proxy.yaml`.
- Remote backends are static catalog rows today. Adding duplicate remote instances requires a new persistence/config
  story, not just renaming `ModelSource.id`.
