# Checklist -- backend_instance_identity_model

**Branch**: `feat/backend-instance-identity-model` - **Card**: [`card.md`](card.md)

**Current focus**: Phase 3 / S5 telemetry backend identity clean break. S4 moved backend CLI JSON to
`backend_instance_id` / `managed_process` and inspect-route metadata to `backend`. Next action: migrate telemetry
backend attribution.

## Invariants (do not violate during migration)

- **Do not undo C2.** `done/cli_style_ux_compliance` C2 shipped public backend / backend-instance / adapter wording
  while deliberately keeping machine names stable for later clean-break slices. S3 deliberately renamed the local
  process schema from `BackendInstance.backend_id` to `ManagedBackendProcess.process_id`; remaining telemetry machine
  names such as `source_id`, `source_kind`, and `backend_id` must change only in their owning slices -- never as an
  incidental rename riding along a wording pass.
- **Runtime vocabulary stays the lane runtime axis.** `runtime` means the `forge.core.runtime_vocab` axis -- agent
  runtimes `claude_code` / `codex` / `gemini` plus the in-process `core_llm` -- never a model backend (kind, instance,
  or local process).
- **Local lifecycle stays local-only.** Remote backend instances gain no fake start/stop semantics; managed PID/port
  state attaches only to local instances.
- **Runtime `proxy.yaml` remains a system boundary** (user-owned): unknown values under the new canonical backend field
  warn-and-degrade on the runtime read path. Old `proxy.source` may fail loudly under the clean-break plan. Strict
  reject-on-unknown stays scoped to the **template load path** (`_apply_template_backend`) -- shipped *or* user
  templates, since `read_template` prefers the user copy -- not the runtime `proxy.yaml` read path.
- **Telemetry origin fields are not backend identity fields.** `source_id`/`source_kind` in downstream telemetry remain
  the origin/correlation axis unless a later slice explicitly renames that axis. The clean break targets
  backend-identity fields such as config `proxy.backend`, CLI/backend JSON `backend_instance_id`, and `managed_process`.

## Phase 0 -- Activation (complete)

- [x] Create or switch to the execution branch.
- [x] Move `docs/board/todo/backend_instance_identity_model/` to `docs/board/doing/backend_instance_identity_model/`.
- [x] Re-read `done/cli_style_ux_compliance` C2/OQ-2 so the migration does not undo the CLI terminology decision
  (captured as the first Invariant above).

## Phase 1 -- Inventory current contracts

**Deliverable**: `inventory.md` (this card dir) -- the raw work-product Phase 2 decides from. Inventory stays in the
card dir; it is not promoted to design docs.

- [x] Enumerate persisted fields and JSON keys with their reader(s) and writer(s): `ModelSource.id`, `source_id`,
  `source_kind`, legacy `BackendInstance.backend_id`, `runtime_instance`, telemetry `backend_id`, `proxy.source`, the
  backend registry (`~/.forge/backends/index.json`), telemetry ledgers, and proxy templates. **Assertion:** load-bearing
  reader/writer paths are named with boundary tags -- strict durable state vs system boundary vs display-only -- so
  Phase 2 knows which fields can clean-break and what failure behavior each surface needs.
- [x] Enumerate human-facing terms in CLI help, end-user docs, design docs, and board notes. **Assertion:** the
  inventory separates already-migrated public terminology (C2) from still-legacy machine-contract names, so Phase 3
  never re-touches a C2 surface.
- [x] Capture local LiteLLM sharing behavior. **Assertion:** the inventory shows the concrete many-to-one case -- one
  `litellm-4000` process backing both `litellm-gemini-local` and `litellm-openai-local` -- and names
  `_local_source_matches_backend_config` (`cli/backend.py`) as **display-only**, never a telemetry-attribution source.

## Phase 2 -- Design decision

**Deliverable**: decisions recorded in `card.md` as the chosen target architecture; promoted to `design.md` /
`design_appendix.md §A.2.1` only when the corresponding code ships (board contract: cards are aspirational, design docs
are contract).

- [x] **OQ-1 -- object shape.** Decide whether the target is a rename of `ModelSource` or a split into backend kind +
  backend instance. **Assertion:** worked through concrete examples -- `openrouter`, `claude-max`, a hypothetical second
  remote of the same kind, and local `litellm-4000` -- each landing on exactly one canonical object.
- [x] **OQ-2 -- telemetry identity.** Decide what downstream `backend_id` means post-migration. **Assertion:** the
  meaning is stated for singleton remotes, duplicate remotes, and shared local LiteLLM, and says whether existing
  records are ignored, shown as legacy-shape records, or migrated by a deliberate tool (no silent attribution drift;
  keep `backend_id` distinct from the `source_id`/`source_kind` origin axis).
- [x] **OQ-3/OQ-4 -- config + ambiguity.** Decide the config spelling and the singleton-to-duplicate transition.
  **Assertion:** `proxy.source` has a clean-break failure/recreate plan, the successor spelling has read/write behavior
  documented, exact instance ids resolve before aliases/kind shorthands, and ambiguous unmatched shorthand **fails
  loudly**, not mis-routes to one instance.
- [x] **OQ-5 -- scope boundary.** Decide foundation-only vs remote-instance CRUD, explicitly and with rationale.
  **Assertion:** the card states the choice (non-goals currently lean foundation-only -- confirm or overturn, do not
  leave it implicit in a Phase 3 guardrail), and the Phase 3 slice list matches it.

## Phase 3 -- Implementation slices

_Slice-ordering guardrails:_

- Land schema/domain resolution with clean-break failure tests before public surfaces.
- Migrate proxy config before CLI JSON so proxy-created runtime files use the new identity field.
- Route `proxy.backend` through the new backend-instance resolver; keep `resolve_model_source_id` only where a later
  slice explicitly justifies the legacy model-source path or removes it.
- Keep telemetry origin `source_id`/`source_kind` distinct from backend identity unless a slice explicitly renames that
  origin axis.
- Keep remote backend instances connection/auth-only; no remote CRUD or remote lifecycle commands in this card.

### S1 -- Core backend identity resolver

- [x] Introduce the minimal backend kind / backend instance resolver in `src/forge/backend/sources.py` (or a sibling
  module if that keeps the boundary cleaner). **Assertion:** exact backend instance ids resolve first, explicit aliases
  resolve second, unique kind/name shorthand resolves third, unmatched ambiguous kind/name shorthand fails loudly, and
  `litellm-4000` is not a backend instance id. **Tests:** `tests/src/backend/test_sources.py`.
- [x] Add duplicate-remote fixtures in tests only (for example `openrouter` + `openrouter-work`) without adding remote
  CRUD. **Assertion:** singleton ids continue to resolve as concrete instances; duplicate kind shorthand errors.
  **Tests:** `tests/src/backend/test_sources.py`.

_Expectation note_: shipped catalog kinds are mostly latent today; many bare-kind shorthands intentionally fail as
ambiguous until explicit `backend_kind` values are assigned per instance.

### S2 -- Proxy config clean break

- [x] Make `proxy.backend` the canonical template/runtime field and update shipped templates. **Assertion:** template
  load rejects old `proxy.source` with a migration/recreate tip and rejects unknown `proxy.backend` strictly. **Tests:**
  `tests/src/config/test_loader.py`, `tests/src/core/auth/test_template_secrets.py`.
- [x] Keep runtime `proxy.yaml` as a system boundary for the new field. **Assertion:** unknown `proxy.backend` in
  runtime config warns-and-degrades; old `proxy.source` fails loudly with a recreate tip. **Tests:** `tests/src/proxy/`.

### S3 -- Managed local process vocabulary

- [x] Rename the local registry/process axis away from backend instance identity. **Assertion:** the durable
  `~/.forge/backends/index.json` schema clean-breaks old `backend_id` process records with a rebuild/recreate tip, while
  live local process behavior remains local-only. **Tests:** `tests/src/backend/`,
  `tests/integration/backend/test_backend_cli.py`.
- [x] Preserve shared LiteLLM display semantics. **Assertion:** one managed process can still back
  `litellm-gemini-local` and `litellm-openai-local`, and list/show mark the process as shared. **Tests:**
  `tests/src/cli/test_backend_commands.py`.

### S4 -- CLI/proxy JSON clean break

- [x] Replace backend CLI JSON identity keys and coupled internal builders/results with backend-instance /
  managed-process names. **Assertion:** source-row `source_id`, nested `runtime_instance`,
  `_runtime_instance_record(...)`, `BackendEnsureResult.instance`, and `ReconcileResult.source_id` do not survive in the
  new shape/API; old-shape expectations fail through tests rather than compatibility aliases. **Tests:**
  `tests/src/cli/test_backend_commands.py`, `tests/src/cli/test_output_streams.py`, `tests/src/backend/test_manager.py`,
  `tests/src/cli/test_backend_reconcile.py`, `tests/src/core/ops/test_backend_reconciliation.py`.
- [x] Replace proxy route/inspect wire backend identity keys. **Assertion:** `_inspect_route()` no longer reports
  backend identity as `"source"` and now reports it as `"backend"` with no alias. `ProxyIdentity.source` remains
  provenance of the proxy identity lookup, not backend identity. **Tests:** `tests/src/proxy/`,
  `tests/src/cli/test_proxy_commands.py`.
- [x] Add runtime terminology guards for help and docs touched by this card. **Assertion:** `runtime` never labels a
  backend instance or managed local process. **Tests:** `tests/src/cli/test_backend_commands.py` or a focused docs/CLI
  grep test.

### S5 -- Telemetry backend identity clean break

- [ ] Route new proxy/direct telemetry writes through backend instance ids. **Assertion:** downstream telemetry
  `backend_id` is the logical backend instance id for singleton remotes, duplicate remotes, and shared local LiteLLM;
  the local managed-process id is not used for attribution. **Tests:** `tests/src/proxy/test_provider_trace.py`,
  `tests/src/core/ops/test_usage_summary.py`.
- [ ] Decide and implement the historical-record outcome. **Assertion:** pre-break records are ignored, shown as
  legacy-shape records, or migrated by a deliberate tool; no view silently reinterprets legacy ids. **Tests:**
  `tests/src/cli/test_activity.py`, telemetry/cost tests touched by the implementation.

### S6 -- Docs and closeout

- [ ] Update shipped docs for implemented behavior only. **Assertion:** `docs/design.md`, `docs/design_appendix.md`,
  `docs/end-user/proxy.md`, and `docs/cli_reference.md` match the final CLI/config/telemetry behavior.
- [ ] Add board closeout entries. **Assertion:** `docs/board/change_log.md` records shipped behavior, and
  `docs/board/impl_notes.md` receives only durable invariants after review.

## Verification

| Test area                 | Fixture                                | Assertion                                                                                        | Test File                                                                   |
| ------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| Clean-break failures      | old `proxy.source` / old JSON fields   | old shapes fail loudly with a migration/recreate tip naming the successor                        | `tests/src/config/test_loader.py`, `tests/src/cli/test_backend_commands.py` |
| Remote duplicate identity | two instances of one remote kind       | exact instance ids resolve; ambiguous unmatched shorthand errors, not mis-routes                 | `tests/src/backend/test_sources.py`                                         |
| Local LiteLLM sharing     | one process backs multiple source rows | `list`/`show` still mark the process `(shared)`; telemetry attribution follows the OQ-2 decision | `tests/src/cli/test_backend_commands.py`                                    |
| Runtime terminology guard | CLI/docs help surfaces                 | `runtime` never labels a backend instance or managed local process                               | `tests/src/cli/test_backend_commands.py` or focused grep test               |
| Telemetry clean break     | pre- and post-break records            | historical records follow the documented legacy/ignore/migrate outcome; no silent reattribution  | `tests/src/cli/test_activity.py`, telemetry/cost tests touched by S5        |

## Closeout

- [ ] Design docs and end-user docs updated for shipped behavior.
- [ ] `docs/board/impl_notes.md` updated only with durable invariants after human review.
- [ ] `docs/board/change_log.md` entry added when code ships.
- [ ] Card moved to `done/` after verification and review.
