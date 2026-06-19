# Backend Remote Reconciliation -- join local downstream telemetry to remote account-side evidence

**Status**: Active in `doing/` (resumed from `paused/openrouter_remote_reconciliation` on 2026-06-19). Generalized from
the OpenRouter-specific original: the mechanism is now generic over any backend source, with **OpenRouter as the first
adapter**. `upstream_downstream_ledgers` and `unified_backend` (PR #39) have both landed, so the telemetry shape and the
`backend_id` source key this card consumes now exist.

**Epic**: [`epic_telemetry_architecture`](../epic_telemetry_architecture/card.md).

**Shipped in two PRs**:

- **PR 1 (generic refactor)**: remove the last OpenRouter coupling from the provider-trace / provider-user-grouping
  surfaces (capability + config-key rename, drop the `provider_name == "openrouter"` fallbacks) so the feature builds on
  a backend-neutral base. No new feature.
- **PR 2 (MVP feature)**: `forge backend reconcile <source-id>` single-id lookup joining one local downstream trace to
  one remote record via a backend remote-adapter registry.

**References**: provider-trace DTOs projected from downstream telemetry; downstream records keyed by `backend_id`;
OpenRouter `/api/v1/generation` (first adapter); run-tree headers. Windowed activity/analytics (`/api/v1/activity`,
`/api/v1/analytics/query`, management key) is a **designed-for deferred follow-on**, not part of this card's MVP.

## Problem

After Forge has local provider lifecycle evidence in downstream telemetry, an operator still needs to ask the backend
what the account saw: final token counts, cost, upstream provider, and cancellation status. The mechanism should be
**generic over any backend source** -- OpenRouter is the first adapter, not the feature.

Remote reconciliation is useful but contingent. The motivating incident involved streams cancelled by a local supervisor
timeout before final usage arrived. A backend may not expose those aborted generations. In that case the correct answer
is a local one: Forge saw the stream start, then lost the final usage/cost evidence when the client/subprocess
disconnected. This card therefore **enhances local trace, never replaces it**.

## Preconditions / boundaries

- `upstream_downstream_ledgers` and `unified_backend` have landed. Local provider-trace reads are projections from
  downstream model-call evidence; `backend_id` is the canonical downstream source key.
- Build on the shipped downstream/`backend_id` seam and existing provider-trace read DTOs. Do not recreate a standalone
  provider-trace plane or re-author the shared usage-provenance branch (epic contract item 4).
- The remote side is metadata-only. For OpenRouter, generation metadata lives at `/api/v1/generation?id=...`; the
  content endpoint (`/api/v1/generation/content`) is out of scope.
- Remote-reconcile capability = **adapter-registry presence**, not a `ModelSourceCapabilities` flag (a flag could drift;
  registry presence is the single source of truth and keeps a read/account-side concern out of the proxy-write-path
  capability struct).
- Proxied provider-user grouping uses the standard `user` field (shipped). Direct `core.llm` `user` injection remains
  the separate [`openrouter_user_direct_callers`](../../todo/openrouter_user_direct_callers/card.md) card.

## Superseded Phase 0 decisions

The original Phase 0 (in [checklist.md](checklist.md)) locked an OpenRouter-specific shape. Resuming generically
supersedes:

- **CLI namespace**: `forge backend reconcile <source-id>` (was `forge provider openrouter ...`).
- **Op/module layout**: `core/ops/backend_reconcile.py` + an adapter registry under `src/forge/backend/remote/` (was
  `core/ops/openrouter_reconciliation.py`).
- **Config-key migration**: alias-with-warning, since `proxy.yaml` is user-owned config / a system boundary (was an
  implicit clean break).

The remaining Phase 0 decisions hold: on-demand only, metadata-only (no content fetch), `gen-...` id vocabulary, normal
vs management key class, no blocking live probe, stable `--json`.

## MVP feature (PR 2): `forge backend reconcile`

A generic op joins one local downstream trace to one remote record for a named source. OpenRouter is the first adapter.

### Module layout

```
src/forge/backend/remote/{base,openrouter}.py   # protocol + registry + generic DTOs; OpenRouter adapter
src/forge/core/ops/backend_reconcile.py         # generic op + DTOs + render_reconcile_lines
src/forge/cli/backend.py                         # new `reconcile` leaf
```

### Behavior

- `--request-id` (local-anchored): `read_downstream_records(backend_id=source_id, request_id=...)` -> latest attempt ->
  `provider_generation_id` -> adapter lookup -> one entry. No local record under that source -> `ForgeOpError`.
- `--remote-id` (single-sided): adapter lookup directly, no local side.
- Remote/network failures are **renderable data** (`RemoteOutcome`), never exceptions; one bad lookup must not abort
  reconciliation. `RemoteAdapterError` is reserved for adapter bugs / config faults and never embeds a key or body.
- Buckets are **comparative**: `missing-remote`/`missing-local` require both a local anchor and a remote answer, so
  single-sided lookups yield only `remote`/`not-queryable`. A coarse bucket plus a precise per-entry `remote_outcome`
  means no reason is lost when outcomes share a bucket.
- Never overwrite local cost/tokens with remote; preserve both with provenance.
- Adapters declare a per-path credential id so the op emits one consistent setup hint.

### Reconciliation taxonomy

- **joined**: local request id matched to a remote `found` record (carries `remote_cancelled`).
- **remote**: raw `--remote-id` found, no local side.
- **missing-remote**: local id present, remote `not_found` (the incident: an aborted stream 404s).
- **not-queryable**: local trace with no `provider_generation_id`, a remote `unavailable`/`not_authorized`, or a
  single-sided lookup that was not `found`.
- **local** / **missing-local**: window-mode only -- **deferred follow-on**.

## Deferred follow-on (designed-for, not shipped here)

Windowed two-sided reconciliation: OpenRouter `fetch_activity` (`/api/v1/activity`) + optional analytics; the
`openrouter-management` credential (`OPENROUTER_MANAGEMENT_KEY`); `reconcile_window` + the `local`/`missing-local`
buckets + `--period/--from/--to`; optional `%backend reconcile`. The protocol already declares the window methods and
per-path credential fields, so this is a clean addition with no MVP rework.

## Risks

- Remote APIs may not expose cancelled streams -> render `missing-remote`, never "request never happened".
- Account/key mismatches can produce false `missing-remote` -> surface key provenance class.
- Remote vs local cost differ in timing/aggregation -> keep both with provenance.
- Content endpoints can expose prompts/completions -> never fetch content without an explicit, privacy-reviewed flag.

## Acceptance sketch (MVP)

- **Generation lookup joins**: local trace with a mocked generation id + remote response -> `joined` with remote
  tokens/cost/provider/status alongside the local request id.
- **Cancelled still joins**: remote `found` + `cancelled=True` -> `joined` with `remote_cancelled=True` (cancelled is
  still remote evidence).
- **Missing remote explicit**: local id + remote 404 -> `missing-remote`.
- **Not-queryable renders, never raises**: local trace with no provider generation id -> a `not-queryable` entry that
  still renders the local evidence.
- **Single-sided**: raw `--remote-id` found -> `remote`; raw `--remote-id` not_found/unavailable/not_authorized ->
  `not-queryable`.
- **Credential actionable**: `not_authorized` sets `needs_credential_id`; CLI prints the setup hint with no key echo.
- **Source-scoped**: a record under a different `backend_id` is not matched in `--request-id` mode (-> `ForgeOpError`).
- **Local evidence preserved**: differing remote/local cost both shown with provenance.
- **JSON stable**: `--json` has `counts`/`entries`, no secrets, no content fields.
