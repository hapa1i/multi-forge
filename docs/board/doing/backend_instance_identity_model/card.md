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

| Term                   | Meaning                                                                                            | Examples / notes                                                                      |
| ---------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Runtime                | Agent/frontend runtime that runs the work.                                                         | `codex`, `claude_code`. Never a model backend process.                                |
| Backend kind / adapter | Implementation or protocol family.                                                                 | `litellm`, future `anthropic-compatible`; local kinds may have lifecycle adapters.    |
| Backend instance       | Concrete configured inference target, local or remote.                                             | `openrouter`, `claude-max`, future `anthropic-compatible-work`, local `litellm-4000`. |
| Backend name           | Human-facing configured backend label; for singleton remotes it may equal the backend instance id. | Compatibility bridge while only one instance of a remote kind exists.                 |

The important future-proofing point: **remote backends are instances too**. Today a singleton remote can use its backend
name as its instance id. Later, multiple configured remotes of the same kind can get distinct instance ids without
inventing a second axis.

Local LiteLLM remains special because Forge manages local processes for it. That lifecycle difference should be a
capability on the backend instance, not a reason to reserve "instance" only for local processes.

## Scope

This card should be an architecture/schema migration, not a CLI wording pass.

- Inventory every persisted and machine-readable identity field: `ModelSource.id`, `BackendInstance.backend_id`,
  `runtime_instance`, `source_id`, telemetry `backend_id`, `proxy.source`, backend registry files, proxy templates, and
  docs that describe those contracts.
- Decide the canonical domain objects and names. Do not merely rename `ModelSource` mechanically if the target object is
  really a configured backend instance, a backend definition, or a backend kind.
- Define a compatibility plan for existing configs, JSON readers, telemetry records, and docs. Old fields may need
  aliases for at least one release window even if the internal model moves.
- Decide what telemetry `backend_id` means after migration. This is non-trivial for local LiteLLM because today's source
  ids encode provider/auth intent while `litellm-4000` can be shared by multiple local source rows.
- Keep agent/frontend runtime vocabulary separate from model backend vocabulary throughout the migration.

## Non-goals

- Do not implement a new remote backend kind in this card unless the design explicitly chooses a small fixture backend
  to prove the abstraction.
- Do not make C2 depend on this card. C2 can improve public help/metavar language first while leaving storage and JSON
  contracts unchanged.
- Do not silently change telemetry attribution. Any telemetry identity migration needs explicit compatibility and
  backfill/read-path decisions.

## Candidate shape

The eventual model likely has:

- Backend kind / adapter definitions: implementation families and lifecycle/probe capabilities.
- Backend instances: configured inference targets keyed by a stable instance id.
- Local lifecycle records: process/PID/port state attached only to managed local backend instances.
- Legacy aliases: singleton remote backend names resolve to their instance ids; old `source_id`/`proxy.source` fields
  resolve through compatibility readers during migration.

This is intentionally a candidate, not a final design. The first active phase should verify whether the current
`ModelSource` catalog is closer to a backend instance definition, a backend kind definition, or a mixed object that
needs to split.

## Open questions

| Question                                                                                        | Why it matters                                                                                                       |
| ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Does `ModelSource` become a backend instance definition, or split into backend kind + instance? | A mechanical rename could preserve today's confusion under better words.                                             |
| Should downstream telemetry `backend_id` point to backend instance id after migration?          | Current records use catalog source ids; local LiteLLM process ids can be shared across source/provider rows.         |
| What is the config spelling for user-defined remote backend instances?                          | `proxy.source` is legacy vocabulary; a `proxy.backend` migration would affect templates, docs, and user config.      |
| How do singleton aliases behave once a user creates a second remote instance of the same kind?  | `openrouter` can be both name and instance id today, but ambiguity must fail loudly once names are no longer unique. |
| Is remote-instance CRUD in scope, or only the identity/schema foundation?                       | Supporting multiple remotes may require user-managed config before it requires lifecycle verbs.                      |

## Acceptance shape

- Public docs and CLI text use `backend` / `backend instance` / `adapter` consistently, with `runtime` reserved for
  agent/frontend runtime.
- Machine contracts have a documented migration path: old names still parse where promised, new names are canonical
  where adopted, and tests pin both.
- Multiple remote backend instances of the same kind can be represented without inventing a separate "source" CLI noun.
- Local managed lifecycle remains local-only; remote backend instances do not gain fake start/stop semantics.
