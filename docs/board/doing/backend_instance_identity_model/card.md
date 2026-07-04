# Backend instance identity model -- make every model backend instance-addressable

**Lane**: `doing/` -- active on branch `feat/backend-instance-identity-model`. Draft execution plan in
[`checklist.md`](checklist.md).

**Origin**: split out of [`done/cli_style_ux_compliance`](../../done/cli_style_ux_compliance/card.md) C2/OQ-2 on
2026-07-03. C2 should clean up public CLI terminology without renaming storage/JSON/domain fields. This card owns the
deeper abstraction migration needed to support multiple configured remote backends of the same kind.

## Problem

Forge currently exposes a useful but leaky backend model:

| Current concept              | Example                                            | Issue                                                                                   |
| ---------------------------- | -------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `ModelSource.id`             | `openrouter`, `claude-max`, `litellm-gemini-local` | "Source" is real internally but is not a first-class CLI noun.                          |
| `BackendInstance.backend_id` | `litellm-4000`                                     | This is a local managed process instance, but the CLI has called it a runtime instance. |
| Telemetry `backend_id`       | current catalog source id                          | The name says backend, while the value is the catalog/source identity.                  |
| `runtime`                    | `codex`, `claude_code`                             | Already means agent/frontend runtime, so using it for backend processes is ambiguous.   |

That is tolerable for today's singleton remotes, but it is the wrong shape for the next abstraction: multiple configured
remote backend instances of the same kind. For example, a Claude-compatible API should be able to stand beside
`claude-max` without being forced into a one-off catalog/source identity, and multiple OpenRouter-like or
Anthropic-compatible remotes should not require a new CLI noun.

## Target vocabulary

| Term                   | Meaning                                                                                            | Examples / notes                                                                                                   |
| ---------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Runtime                | Agent/frontend runtime that runs the work.                                                         | `codex`, `claude_code`. Never a model backend process.                                                             |
| Backend kind / adapter | Implementation or protocol/provider family.                                                        | `openrouter`, `litellm`, `anthropic`, future `anthropic-compatible`; local kinds may have lifecycle adapters.      |
| Backend instance id    | Stable id for a concrete configured inference target, local or remote.                             | `openrouter`, `claude-max`, `litellm-gemini-local`, future `anthropic-compatible-work`.                            |
| Managed local process  | Forge-managed PID/port/process state backing one or more local backend instances.                  | `litellm-4000`; local-only lifecycle state, not the logical backend instance id.                                   |
| Backend name / alias   | Human-facing label or compatibility alias that resolves to a backend instance id when unambiguous. | For singleton remotes it may equal the instance id; exact instance-id matches always win over alias/kind matching. |

The important future-proofing point: **remote backends are instances too**. Today a singleton remote can use its backend
name as its instance id. Later, multiple configured remotes of the same kind can get distinct instance ids without
inventing a separate "source" CLI noun.

Local LiteLLM remains special because Forge manages local processes for it. That lifecycle difference should be a
capability on the backend instance, not a reason to reserve "instance" only for local processes.

## Scope

This card should be an architecture/schema migration, not a CLI wording pass.

- Inventory every persisted and machine-readable identity field: `ModelSource.id`, `BackendInstance.backend_id`,
  `runtime_instance`, `source_id`, telemetry `backend_id`, `proxy.source`, backend registry files, proxy templates, and
  docs that describe those contracts.
- Decide the canonical domain objects and names. Do not merely rename `ModelSource` mechanically if the target object is
  really a configured backend instance, a backend definition, or a backend kind.
- Define a clean-break plan for configs, JSON readers, telemetry records, and docs. Old field names can fail loudly with
  migration/recreate guidance instead of being accepted through compatibility readers.
- Decide what telemetry `backend_id` means after migration. This is non-trivial for local LiteLLM because today's source
  ids encode provider/auth intent while `litellm-4000` can be shared by multiple local source rows.
- Keep agent/frontend runtime vocabulary separate from model backend vocabulary throughout the migration.

## Non-goals

- Do not implement a new remote backend kind in this card unless the design explicitly chooses a small fixture backend
  to prove the abstraction.
- Do not make C2 depend on this card. C2 can improve public help/metavar language first while leaving storage and JSON
  contracts unchanged.
- Do not silently change telemetry attribution. A clean break is allowed, but the implementation must explicitly decide
  whether historical records are ignored, shown as legacy-shape records, or migrated by a deliberate tool -- never
  silently reattributed.

## Candidate shape

The eventual model likely has:

- Backend kind / adapter definitions: minimal implementation families, lifecycle/probe mechanisms, and default
  capabilities.
- Backend instances: configured inference targets keyed by a stable instance id, with endpoint/auth/billing and
  instance-level capability overrides.
- Local lifecycle records: process/PID/port state attached only to managed local backend instances.
- Clean-break surface migration: singleton backend names may continue to resolve to their instance ids, but old field
  names such as `source_id`, `proxy.source`, and `runtime_instance` do not need compatibility readers.

This is intentionally a candidate, not a final design. The first active phase should verify whether the current
`ModelSource` catalog is closer to a backend instance definition, a backend kind definition, or a mixed object that
needs to split.

## Phase 2 decision (accepted)

The inventory points to a split, but not the naive one where the local process id becomes the backend instance id.
Recommended target:

- **Backend kind / adapter definition**: implementation or protocol/provider family (`openrouter`, `litellm`,
  `anthropic`, `openai-compatible`, future `anthropic-compatible`). This is distinct from the existing `EndpointKind`
  enum: `runtime_native` remains an endpoint/transport shape, while backend kind says which provider or protocol family
  a configured instance belongs to.
- **Backend instance definition**: concrete configured inference target keyed by stable instance id. The current
  `ModelSource` object is closest to this object because it already carries endpoint, credentials, capabilities, billing
  posture, template names, and reachability.
- **Managed local process**: PID/port/process state for Forge-managed local backends. S3 moved the old
  `BackendInstance.backend_id` (`litellm-4000`) to `ManagedBackendProcess.process_id`, keeping it out of the universal
  backend instance id axis. Because `~/.forge/backends/index.json` is strict durable state, the schema v2 rename fails
  old v1 records with a clear rebuild/recreate tip rather than silently accepting the old schema.

Concrete examples:

- `openrouter`: kind `openrouter`, singleton instance id `openrouter` (the name and instance id are currently
  synonymous).
- `claude-max`: instance id `claude-max`, backend kind/provider `anthropic`, endpoint kind `runtime_native`.
- `chatgpt`: instance id `chatgpt`, backend kind/provider `openai`, endpoint kind `runtime_native`.
- Future duplicate remote: kind `anthropic-compatible`, instance ids such as `claude-compatible-work` and
  `claude-compatible-personal`, each with its own endpoint/auth config.
- Local LiteLLM: backend instances such as `litellm-gemini-local` and `litellm-openai-local` share a managed local
  process id such as `litellm-4000`. Telemetry and lane binding should keep the logical backend instance id, not
  collapse to the shared process id.

Capability ownership rule:

- Transport/lifecycle mechanisms and probe implementations belong to backend kinds/adapters.
- Endpoint/auth/billing posture, runtime reachability, and externally visible feature gates belong to backend instances.
- Kind definitions may provide defaults, but the resolved capability used by callers must be instance-specific. Today's
  `ModelSource.capabilities` reads (`provider_trace`, `provider_user_grouping`, `responses_ingress`) therefore migrate
  to resolved backend-instance capabilities unless Phase 3 proves a specific flag is truly invariant for every instance
  of a kind.

Recommended OQ resolutions:

- **OQ-1 object shape:** split into backend kind / backend instance / managed local process. Model a minimal kind axis
  in this card (`kind_id`/adapter family) so duplicate-remote fixtures and ambiguity checks are computable, but keep the
  rest foundation-only. Rename or replace `ModelSource` as a backend instance definition, then factor out shared
  kind/adapter metadata only where it removes duplicated lifecycle/protocol facts.
- **OQ-2 telemetry identity:** downstream telemetry `backend_id` should mean backend instance id. Existing catalog
  source ids mostly already behave as logical instance ids; keep `source_id`/`source_kind` as the origin axis. Do not
  backfill historical records initially, and do not add read aliases for renamed ids unless Phase 3 deliberately adds a
  one-shot migration tool. New views must not silently join or reinterpret pre-break records. If process attribution is
  needed later, add a separate local-process field instead of overloading `backend_id`. S5 takes the clean-break path:
  new downstream writes use `schema_version=2`; current readers skip missing/older downstream schemas with one warning
  and surface activity/cost skip counts instead of reinterpreting them under the backend-instance contract.
- **OQ-3/OQ-4 config + ambiguity:** make the canonical config spelling `proxy.backend` with backend instance id/name
  values. `proxy.source` is not a compatibility reader in the clean-break path: templates or runtime `proxy.yaml` files
  that still use it should fail loudly with a recreate/migration tip. The new `proxy.backend` field keeps the existing
  posture split: strict reject-on-unknown at template load, warn-and-degrade for unknown values in runtime `proxy.yaml`.
  Resolution precedence is: exact backend instance id first, explicit alias second, then optional unique kind/name
  shorthand. Therefore `proxy.backend: openrouter` keeps resolving to the concrete instance `openrouter` even after
  `openrouter-work` exists. Only an unmatched shorthand that resolves to more than one instance fails loudly with a tip
  to choose a concrete backend instance id. S4 renamed the inspect-route backend-identity key from
  `_inspect_route().source` to `backend` with tests. `ProxyIdentity.source` remains provenance of the proxy identity
  lookup, not backend identity.
- **OQ-5 scope boundary:** keep this card foundation-only: schema/domain/resolution/clean-break migration, plus
  fixture-backed duplicate-remote tests if useful. Do not add remote backend CRUD or remote lifecycle commands here;
  those belong in a follow-up card once the identity model is stable.

## Resolved questions

| Question                                                                                        | Why it matters                                                                                                     |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Does `ModelSource` become a backend instance definition, or split into backend kind + instance? | A mechanical rename could preserve today's confusion under better words.                                           |
| Should downstream telemetry `backend_id` point to backend instance id after migration?          | Current records use catalog source ids; local LiteLLM process ids can be shared across source/provider rows.       |
| What is the config spelling for user-defined remote backend instances?                          | `proxy.source` is legacy vocabulary; a `proxy.backend` migration would affect templates, docs, and user config.    |
| How do singleton aliases behave once a user creates a second remote instance of the same kind?  | Exact instance ids keep resolving; only unmatched shorthand/alias resolution can become ambiguous and fail loudly. |
| Is remote-instance CRUD in scope, or only the identity/schema foundation?                       | Supporting multiple remotes may require user-managed config before it requires lifecycle verbs.                    |

## Acceptance shape

- Public docs and CLI text use `backend` / `backend instance` / `adapter` consistently, with `runtime` reserved for
  agent/frontend runtime.
- Machine contracts have a documented clean-break path: new names are canonical, old names fail loudly with actionable
  guidance where they are still encountered, and tests pin both the new shape and old-shape failure.
- Multiple remote backend instances of the same kind can be represented without inventing a separate "source" CLI noun.
- Local managed lifecycle remains local-only; remote backend instances do not gain fake start/stop semantics.
