# Unified Backend Concept -- Execution Checklist

Branch: `unified_backend`. Card: [card.md](card.md). Epic:
[`epic_telemetry_architecture`](../epic_telemetry_architecture/card.md).

## Current Focus

Promote model source identity to a first-class backend/source axis without collapsing the existing proxy and provider
axes:

- **Proxy**: the Forge routing endpoint Claude or subprocesses hit.
- **Provider**: the per-request wire client inside the proxy/runtime.
- **Backend/source**: the upstream model source, local or remote, that should own auth, endpoint, health, and downstream
  telemetry attribution.

Start with a source-map and design lock. This branch must avoid the fifth-concept trap: adding remote backends without
absorbing template source identity, auth dependency mapping, and downstream telemetry attribution would make the system
more confusing, not less.

## Active Constraints

- Keep static source definitions separate from runtime local-process instances. Remote backends have no PID, port
  ownership, or lifecycle registry row.
- Keep lifecycle verbs local-only. Remote sources may be listed, shown, and auth-tested, but must not implement fake
  `start`/`stop`.
- Preserve session/proxy separation. A backend/source id attributes downstream model-call evidence; it is not a session
  key and not a substitute for run-tree joins.
- Preserve auth-resolution semantics: environment before credential store unless `auth_ignore_env` is set; never print
  secrets; treat `Credential.unlocks_features` as presentation-only.
- Preserve proxy template behavior during migration. Local templates still auto-start required local services; remote
  templates still resolve endpoint + credentials without local lifecycle.
- Treat user-facing CLI/config vocabulary changes as research-preview clean breaks, with docs and tests rather than
  compatibility shims.

## Phase 0 -- Source Map And Design Lock

- [x] Enumerate every current source-identity site: `BackendDependency`, `BackendAdapter`/`BackendManager`,
  `BackendInstance.backend_id` and `BackendRegistry`, `ProviderType` (`typing.Literal` in
  `src/forge/core/llm/detection.py`), `AdapterProviderType` (`typing.Literal` in `src/forge/proxy/client_adapter.py`),
  `ModelProvider` (the enum in `src/forge/proxy/client_factory.py`), proxy template `preferred_provider`, provider
  `base_url`, `BackendDependency`, `TEMPLATE_ENV_VARS`, `credentials_for_template()`, credential connection values,
  downstream writers, provider-trace gating, OpenRouter `user` injection, and `forge backend` CLI verbs.
- [x] Record the current unit of each identity: static definition, runtime instance, proxy template, wire-client
  provider, credential dependency, telemetry origin, model-source attribution key, or user-facing display label.
- [x] Decide naming: use `ModelSource` / source definition internally while keeping `forge backend` as the user-facing
  CLI noun.
- [x] Decide source ids for v1: use catalog-defined ids. Template names may alias to source ids where useful; local
  source ids must stay in a disjoint value-space from runtime instance ids (`litellm-local`, not `litellm-4000`) and may
  resolve through backend dependency/port metadata, while remote ids point at endpoint/auth definitions.
- [x] Resolve the `backend_id` name collision: add an explicit downstream `backend_id` as the canonical model-source key
  while preserving `BackendInstance.backend_id` as the local runtime-instance id. Phase 4 writes the catalog source id
  to downstream `backend_id`, not the runtime `BackendInstance.backend_id`.
- [x] Resolve the `source_kind` overload: existing downstream writers use `source_kind="proxy"` or `"provider"` as a
  telemetry-origin axis. Do not silently reuse that field for `local`/`remote`; decide the carrier for backend/source
  attribution while preserving origin semantics.
- [x] Decide the static definition home and schema shape: add a built-in code-level backend-domain source catalog
  distinct from `~/.forge/backends/index.json`, which remains a local runtime-instance registry. The existing
  `~/.forge/backends/<adapter>/config.yaml` is service config, not a source manifest. User-defined custom sources are
  out of scope for v1. Templates gain `proxy.source`.
- [x] Decide endpoint representation for catalog entries: support literal URL, connection-value reference
  (`LITELLM_BASE_URL`, `OPENROUTER_BASE_URL`), and local backend-dependency-derived URL.
- [x] Decide provider vocabulary fate: use `ProviderType` as the source definition's wire hint in Phase 1, then narrow
  to `AdapterProviderType` and `ModelProvider` at adapter/factory seams instead of deleting/collapsing them.
- [x] Decide direct Anthropic/passthrough scope for v1: include `anthropic-passthrough` as a remote template source and
  `anthropic-direct` as a direct-runtime source for auth/telemetry attribution.
- [x] Decide whether the OpenRouter `user` injection gate in `server.py` migrates with provider-trace or remains an
  intentionally direct-OpenRouter-only sibling: keep direct-only unless a source declares an OpenRouter user-grouping
  capability.
- [x] Decide direct writer attribution for v1: proxy paths derive downstream `backend_id` from `proxy.source`; non-proxy
  direct usage writers may set it only from an explicit provider/reporter -> source mapping and otherwise leave it
  nullable.
- [x] Decide lifecycle CLI shape: `list`/`show`/`test-auth` use source ids; `start`/`stop` should accept source operands
  far enough to return intentional remote no-lifecycle capability errors while local sources resolve to existing
  lifecycle. `create` and `delete` remain local-only adapter/instance operations in v1 because built-in remote sources
  are not user-created or user-deleted.
- [x] Decide v1 health semantics for remote sources: `list` stays offline and reports configured/missing/unprobed;
  `test-auth` performs explicit network/auth probes.
- [x] Decide one auth provenance vocabulary for source views: JSON uses `env`, `credential_file`, `none`, and
  `omitted_by_config` only for deliberate interactive-key omission; human "not configured" maps from `none`.
- [x] Record the proposed design lock in [card.md](card.md): supertype name, remote id unit, carrier decision, provider
  vocabulary fate, `source_kind` axis decision, template shape, and lifecycle CLI shape.
- [ ] Get human acknowledgement of the Phase 0 design lock before Phase 1 code.
- [x] Update this checklist if the source map changes the phase ordering before coding. No phase-order change needed;
  Phase 1 remains catalog/type primitives first.

## Phase 1 -- Catalog And Type Primitives

- [ ] Add typed model-source/backend definitions with `id`, `kind`, endpoint/base URL or connection-value reference,
  `ProviderType` wire-client hint, credential dependencies, and capabilities such as provider-trace eligibility.
- [ ] Represent local lifecycle as a local-only refinement or related instance type, not as a field every remote source
  must fake.
- [ ] Add built-in definitions for existing remote OpenRouter templates, remote LiteLLM templates, local LiteLLM
  templates, `litellm-gemini-test`, and Anthropic passthrough/direct behavior according to the Phase 0 decision.
- [ ] Add strict validation for duplicate ids, unknown kind/provider values, missing credential declarations, and bad
  endpoint/connection-value shapes.
- [ ] Add tests proving remote definitions never enter the PID/port runtime registry and local definitions still map to
  their lifecycle adapter where needed.
- [ ] Update [design_appendix.md](../../../design_appendix.md) for the shipped source-definition schema and static-vs-
  runtime ownership before moving to the next phase.

## Phase 2 -- Template And Auth Integration

- [ ] Migrate proxy templates from inline model-source identity to a catalog/source reference where Phase 0 decided it
  belongs.
- [ ] Enumerate the actual template classes in tests: five user-facing `*-local` templates plus internal
  `litellm-gemini-test` use `backend_dependency`; OpenRouter templates and `anthropic-passthrough` carry inline provider
  `base_url`; remote LiteLLM templates resolve endpoint from `LITELLM_BASE_URL`.
- [ ] Preserve local template auto-start behavior by resolving source definitions to the existing `BackendDependency` /
  `BackendManager` path or its chosen replacement.
- [ ] Resolve remote endpoint and connection values through the source definition plus credentials/connection values
  (`OPENROUTER_BASE_URL`, `LITELLM_BASE_URL`, etc.) without duplicating auth logic.
- [ ] Bridge `TEMPLATE_ENV_VARS` and `credentials_for_template()` to the new source definitions, or replace them with a
  single generated/typed dependency map. Do not use `Credential.unlocks_features` as logic.
- [ ] Update schema/loader sites for any new template key. `_load_template_config()` ends in
  `dict_to_dataclass(ForgeConfig, config_dict, strict=True)`, so the new `proxy.source` field must be accepted by
  `ProxyConfig` or transformed before strict dataclass loading.
- [ ] Add no-secret tests for env, credential-file, `auth_ignore_env`, missing key, connection-value provenance, and
  strict-loader rejection of unsupported source shapes.
- [ ] Update [design_appendix.md](../../../design_appendix.md), [cli_reference.md](../../../cli_reference.md) if user
  template syntax changes, and relevant `docs/end-user/*` guides as template/source behavior ships.

## Phase 3 -- Backend CLI And Operator Views

- [ ] Rework `forge backend list` to show both local and remote sources with kind, endpoint, required credential,
  credential provenance, and health/reachability status. Treat these as net-new output fields; today's `--json` only
  emits runtime registry fields (`backend_id`, `adapter_type`, `port`, `pid`, `status`).
- [ ] Rework `forge backend show <id>` to render source definition details and, for local sources, current runtime
  instance state when present.
- [ ] Add `forge backend test-auth <id>` as a net-new command, or intentionally choose another command name in the Phase
  0 design lock. Cover local and remote sources with typed outcomes and no secret echo in human or JSON output.
- [ ] Rework lifecycle verb signatures according to the Phase 0 verb split. Remote `start`/`stop` attempts must reach a
  concise no-lifecycle capability error rather than dying at Click's `litellm` choice validation; `create`/`delete`
  remain local-only adapter/instance operations with explicit help/error text.
- [ ] Update `forge authentication status` only if needed to point users toward the unified source view without
  duplicating the source table.
- [ ] Add CLI tests for human and `--json` output, remote no-lifecycle behavior, missing credentials, credential-file
  provenance, local runtime-instance display, and command parsing of remote lifecycle operands.
- [ ] Update [cli_reference.md](../../../cli_reference.md), relevant `docs/end-user/*` guides, and any design appendix
  command-contract notes as the CLI behavior ships.

## Phase 4 -- Proxy Runtime And Downstream Attribution

- [ ] Thread the chosen backend/source id through proxy startup and request handling without changing session-owned
  routing semantics.
- [ ] Extend the existing downstream writer seam instead of re-authoring it. Audit and update all current source-id
  writers: `proxy/cost_logger.py` (`source_id=proxy_id`, `source_kind="proxy"`), `proxy/provider_trace_logger.py`
  (`source_id=proxy_id`, `source_kind="proxy"`), `proxy/audit_logger.py` (`source_id=proxy_id`, `source_kind="proxy"`),
  and `core/usage/emit.py` (four `source_id` sites: the `claude_p` path keys on `measurement.reporter`, while the
  worker/Codex/direct `core.llm` paths key on `provider`; all use provider-origin `source_kind` when present).
- [ ] Use `core/usage/measurement.py` and `UsageMeasurement` as the shipped measurement seam:
  `resolve_claude_p_measurement`, `resolve_codex_measurement`, and `resolve_direct_llm_measurement`. Do not implement
  against the epic's aspirational `resolve_measurement` name.
- [ ] Implement the Phase 0 carrier decision: add an explicit `backend_id` field or map the conceptual backend key onto
  an existing field without overloading `source_kind`'s proxy/provider origin semantics.
- [ ] Populate downstream `backend_id` from the catalog source id, never from `BackendInstance.backend_id`. For
  non-proxy direct emitters, use an explicit provider/reporter -> source mapping only where unambiguous; otherwise leave
  `backend_id` nullable for v1.
- [ ] Add read-side behavior if the carrier needs it. `read_downstream_records()` currently filters by `proxy_id` and
  run/session ids, not by `source_id`/`source_kind` or `backend_id`.
- [ ] Replace the `provider_trace_logger.py` early return `if provider_name != "openrouter": return` with a
  backend/source capability or selected-source gate. Keep callers in `server.py` and `passthrough.py` on the same
  helper, preserve the direct-OpenRouter incident behavior, keep gateway-routed OpenRouter semantics explicit, and
  delete the forward-reference comment in `provider_trace_logger.py` when the migration lands.
- [ ] Decide and implement whether the OpenRouter `user` injection gate in `server.py` follows the same backend/source
  capability or remains direct-OpenRouter-only by design.
- [ ] Preserve run-tree joining and double-count suppression. Backend/source identity is an attribution dimension, not a
  replacement for `forge_root_run_id`.
- [ ] Preserve nullable-cost semantics and existing cap bootstrap behavior.
- [ ] Add regression coverage for provider-trace broadening, proxied/direct measurement precedence, downstream source-id
  joins, duplicate-`downstream_event_id` merge behavior for the new source key, read-side filtering if added, and no
  double-count in `forge activity` / `forge proxy costs show`.
- [ ] Update [design.md](../../../design.md) §3.14 and [design_appendix.md](../../../design_appendix.md) for the shipped
  downstream attribution key and writer ownership before moving to closeout.

## Phase 5 -- Migration And Closeout

- [ ] Verify all per-phase design-doc, CLI-reference, and end-user doc tasks are complete for the shipped shape.
- [ ] Update this card and the telemetry epic if the shipped shape changes the shared contract.
- [ ] Add a compact entry to [change_log.md](../../change_log.md) when implementation ships.
- [ ] Promote durable lessons to [impl_notes.md](../../impl_notes.md) after human review.
- [ ] Run focused unit/regression tests for backend, config loader/schema, auth capabilities, templates, proxy
  telemetry, provider trace, activity, and CLI surfaces.
- [ ] Run relevant integration tests if proxy startup, backend lifecycle, template resolution, or backend CLI behavior
  changes.
- [ ] Run `make pre-commit` before closeout.
- [ ] After merge, move this card to `docs/board/done/unified_backend/` and update the epic sequencing.

## Acceptance Tests

| Test                                            | Fixture                                                                                                               | Assertion                                                                                                                                | Test File                                                                                                                                                         |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unified source listing                          | local LiteLLM runtime instance plus OpenRouter/remote LiteLLM definitions                                             | `forge backend list --json` exposes net-new local and remote source fields: kind, endpoint, credential provenance, and health            | `tests/src/cli/test_backend_commands.py`                                                                                                                          |
| Remote source has no lifecycle                  | OpenRouter remote source; `forge backend start/stop/delete openrouter`                                                | command reaches an intentional capability error or documented adapter-only contract and creates no runtime registry entry                | `tests/src/cli/test_backend_commands.py`, `tests/integration/backend/test_backend_cli.py`, `tests/integration/backend/test_proxy_backend_integration.py`          |
| Static definitions stay out of runtime registry | remote backend catalog loaded with empty `~/.forge/backends/index.json`                                               | remote definitions are listed but `BackendRegistry.backends` remains local-instance only                                                 | `tests/src/backend/test_registry.py`                                                                                                                              |
| Template source resolution                      | `openrouter-*`, remote `litellm-*`, five user-facing `*-local` templates, internal `litellm-gemini-test`, passthrough | templates resolve endpoint/provider/credentials through the source catalog while local/test templates still auto-start dependencies      | `tests/src/config/test_loader.py`, `tests/src/config/test_schema.py`                                                                                              |
| Auth provenance is secret-free                  | env key, credential-file key, ignored env, missing key, connection value                                              | source/auth views report one provenance vocabulary and actionable errors without key material                                            | `tests/src/core/auth/test_capabilities.py`, `tests/src/core/auth/test_template_secrets.py`, `tests/src/core/auth/test_secrets.py`                                 |
| Downstream source key                           | proxy cost, provider trace, audit, and direct usage emitters                                                          | all downstream attempt writers carry the canonical backend/source id while preserving proxy/provider origin semantics and run-tree ids   | `tests/src/core/telemetry/test_downstream.py`, `tests/src/proxy/test_cost_logger.py`, `tests/src/proxy/test_audit_logger.py`, `tests/src/core/usage/test_emit.py` |
| Provider trace gate broadens safely             | direct OpenRouter and non-OpenRouter backend attempts                                                                 | provider lifecycle records are written by backend/source capability, not hardcoded provider literal, and non-eligible sources stay quiet | `tests/src/proxy/test_provider_trace_logger.py`, `tests/src/proxy/test_passthrough.py`, `tests/src/proxy/test_server_provider_trace.py`                           |
| No cost double-count                            | proxied `claude -p` self-report plus proxy downstream evidence                                                        | activity/proxy cost surfaces use proxy evidence once and keep unavailable cost distinct from zero                                        | `tests/src/core/ops/test_usage_summary.py`, `tests/regression/test_bug_usage_cost_precedence.py`                                                                  |

## Open Decisions

Open decisions are gated in Phase 0. Do not leave a detached decision list here; when a new question appears, add it to
the Phase 0 design-lock checklist and cross-reference the phase it gates.
