# Session Route Provenance and Marking

**Status**: Doing (activated 2026-08-22). Planning and implementation are tracked in [checklist.md](checklist.md) on the
per-card branch `feat/session-route-provenance`. The user ratified the contract and checklist after two review rounds;
implementation is active through PR creation.

**Epic**: M2 member of [Epic: Session Authority and Provenance](../epic_session_authority_provenance/card.md), which
owns the shared event envelope, run correlation, cross-journal compensation, and presentation boundaries with
[Artifact Authority Mode](../../done/artifact_authority_mode/card.md), the epic's shipped M1 member.

**Relationship**: authority mode decides which managed session may mutate project artifacts. This card reports how a
managed session was routed and the provider-declared text-marking posture of the selected or mapped model. It adds no
authority, enforcement, authorship attestation, admission decision, or content guarantee. Generic model-to-route
selection is separate in [Model-First Interactive Session Routing](../../proposed/model_first_session_routing/card.md);
this card does not depend on it.

**References**: [design.md §3](../../../design.md#3-shared-contracts-file-based-state-system) (session state),
[design.md §3.4](../../../design.md#34-proxy-vs-no-proxy-mode) (routing ownership),
[design_runtime.md §3.7](../../../design_runtime.md#37-proxy-runtime-truth) (live proxy facts),
[design_sessions.md §3.9](../../../design_sessions.md#39-session-resume-context-management) (launch lifecycle),
[design_runtime.md §A.2.1](../../../design_runtime.md#a21-backend-instance-catalog-365-unified-backend-phase-12)
(backend identity), [design_runtime.md §A.5](../../../design_runtime.md#a5-model-catalog-368) (intrinsic model catalog),
[design_telemetry.md §A.8](../../../design_telemetry.md#a8-status-line-guidance-3611) (status-line sources),
[`cli_reference.md`](../../../cli_reference.md) (command inventory),
[`cli_style_guidelines.md`](../../../developer/cli_style_guidelines.md) (command naming and read-surface contract),
`src/forge/session/events.py` (shared journal primitives), `src/forge/session/launch_confirmation.py` (existing
Claude-only route/auth confirmation), `src/forge/core/ops/session_authority_launch.py` (M1 launch transaction), and
`src/forge/core/ops/session_context.py` (current model context).

## Problem

Forge already supports Claude model pins on `session start`, `resume`, and `fork`; `resume --model` persists the new
pin, and `resume --proxy` / `--no-proxy` persist route intent. Existing reads expose pieces of the result:

- `forge session show --json` includes the direct pin or current proxy tier map;
- Claude-only `confirmed.launch` records the latest route and API-key/cost posture on each launch;
- the status line sees Claude Code's current request model through stdin and can combine it with live proxy mappings;
- copied direct-session transcripts retain observed assistant model transitions;
- proxy downstream telemetry records `mapped_model` per attempt.

What is missing is one session-scoped history of launch routing decisions, a typed read that distinguishes intent from
confirmed and live facts, and carefully scoped provider-declared text-marking metadata. The current evidence cannot
honestly answer which backend authored every turn: live route selection happens per request, proxy requests from the
main interactive harness are not session-correlated, and earlier model content can remain in conversation context.

The provider-marking scenario sharpens the need for honest labels. An operator may want to know whether the model
selected for a producer launch is declared to embed text marks, but that declaration is not detection and does not prove
the provenance of an artifact.

## M2 decisions awaiting ratification

These are the proposed normative decisions corresponding to the review gate in [checklist.md](checklist.md). They become
the execution contract only when that gate is checked:

1. **D1 -- launch transaction**: every attempt that reaches the child-invocation boundary commits routing evidence
   before invoking the child. Required failures abort the launch and compensate every member journal already touched.
   This card proposes the evidence-conditional clarification to frozen epic C3 described in the epic: a durably recorded
   authority abort supersedes same-run start evidence in the M1 reader, while a failed compensation append cannot create
   a durable abort claim.
2. **D2 -- journal and projection**: the routing payload is exact and secret-free. `confirmed.route_commit` stores only
   the matching event and run ids; route details remain journal-owned.
3. **D3 -- continuity**: history is derived from effective commits, where a commit followed by a same-run abort is an
   aborted attempt rather than the latest effective route. A complete state table below owns
   `supported | unproven | null`.
4. **D4 -- read schemas**: terminal reads keep one stable field set across direct, proxy, custom, runtime-native,
   legacy, fallback, and inconsistent states. Nonempty history returns validated envelope-plus-payload events in append
   order. The user-facing `session model` noun is intentional; `routing` remains the internal evidence domain.
5. **D5 -- marking catalog**: a versioned, package-owned catalog uses canonical model ids, conjunctive code-owned route
   tags, strict validation, and normalized unknown output.
6. **D6 -- runtime/status line**: live proxy truth exposes `backend_id` and `model_alternatives`; the marking segment
   declares both proxy and session sources and remains fail-open.
7. **D7 -- initial data boundary**: M2 intentionally ships a valid all-unknown production marking catalog. Route
   provenance is independently useful; `mark:yes` and `mark:no` are schema/test capabilities until a separately reviewed
   source-data change adds declarations.
8. **D8 -- release proof**: completion includes design/end-user documentation, targeted managed-session and proxy
   integration tests, and clean-wheel verification of the packaged catalog.

## Evidence model and observability boundary

The implementation keeps four planes distinct:

| Plane            | Question answered                                       | Source                                                    |
| ---------------- | ------------------------------------------------------- | --------------------------------------------------------- |
| Intent           | What should a later launch use?                         | Session manifest                                          |
| Route commitment | Which route did Forge fix for one launch attempt?       | Launch journal plus `confirmed.route_commit` latest state |
| Live proxy truth | What does the reachable proxy map each tier to now?     | Proxy `GET /`                                             |
| Observed request | Which client tier/model is this status-line poll using? | Claude Code status-line stdin                             |

Normative limits:

- Proxy `runtime.active_tier` is the proxy's configured default, not the current tier of a particular session.
- `forge session model show` and `%session model show` have no status-line stdin. The shared report retains
  `current_request_tier: null` and `current_request_source: unavailable`; the direct command emits a fixed-size human
  summary of that report. Neither surface relabels the proxy default as the session's current tier.
- The opt-in status-line segment may report the observed request tier because that process receives Claude Code's
  current model id. It labels the source in documentation as request-observed, not session-persisted.
- `session model history` is launch routing history. It does not claim per-request model use, authorship, admission, or
  watermark presence.
- Backend identity uses the architecture's canonical `backend_id` term. `source_id` remains telemetry/reporting
  vocabulary and is not part of the M2 route schema.

## Goals

1. **Typed read surfaces**: `forge session model show [session] [--json]` renders a stable evidence vector containing
   session/runtime/active state, route intent, latest supported route commitment, live proxy identity and mappings when
   available, provider-declared marking, history support, and limitations. `%session model show [session]` is a
   fixed-size, read-only in-session summary derived from the same report; full maps and declaration arrays remain on the
   terminal `--json` surface. There is no mutating direct-command surface.
2. **Launch routing history**: `forge session model history [session] [--json]` reads
   `.forge/artifacts/<session>/routing/events.jsonl` strictly and reports `history_status: supported | unproven | null`.
   The direct command does not mirror history in v1, avoiding an unbounded hook response.
3. **Required prelaunch commitment**: every managed start, resume, fork, or incognito attempt that crosses the routing
   commitment boundary appends exactly one `launch_routing_committed` event before child invocation. Spawn failure,
   child failure, or cancellation after that boundary does not erase the route commitment or turn it into an authorship
   claim.
4. **Latest-state projection**: runtime-neutral `confirmed.route_commit` points to the newest effective route commit.
   The journal is history and the projection is only a pointer. Existing Claude-only `confirmed.launch` keeps its
   Anthropic auth/cost meaning and remains unset for Codex.
5. **Provider-declared text-marking metadata**: a separate repo-owned `src/forge/core/data/model_practices.yaml` stores
   temporal provider practices. The intrinsic model catalog remains free of them. V1 covers embedded text marking only,
   not signed-file provenance metadata.
6. **Opt-in status-line segment**: a default-off `marking` segment renders the observed request model's declared text
   marking as `mark:yes`, `mark:no`, or `mark:?`. `DEFAULT_ORDER` remains byte-compatible.
7. **Runtime-neutral route history, runtime-specific model detail**: Claude launches record direct/proxy/custom route
   detail. Codex launches record `route.kind: runtime_native`, unknown exact backend/model/billing, and an empty marking
   snapshot; this card adds no Codex model selection or observation claim.

### Command naming

`forge session model show|history` and `%session model show` use `model` because users are asking which model Forge
selected or mapped and which provider declaration applies. The journal, projection, source modules, and event names keep
the narrower `routing` domain vocabulary. The existing top-level `forge model` group remains the catalog/backend
namespace; nesting disambiguates the session-scoped read. V1 adds no `session route` alias.

## Required launch transaction

### Preparation boundary

The launcher mints the existing root `RunIdentity`, resolves routing, completes context-budget and runtime preflight,
and fixes the child argv/environment before the first routing event. A routing/context/runtime failure before the commit
boundary appends no routing event. Authority may still record its own failed preflight under M1's existing contract.

The transaction constructs one immutable routing payload after preparation. The commit event and any later routing abort
serialize that same object; compensation must not reread the catalog, proxy config, registry, or runtime or rebuild a
nominally equivalent payload. The snapshot and child argv/environment remain fixed for the remainder of the attempt. No
status-line or history option controls whether this transaction runs.

### Required state order

When M1 and M2 both apply, the order is:

1. M1 rereads authority intent under its session lock, appends successful `launch_preflight`, registers marked active
   state, and appends `run_started`.
2. M2 appends one `launch_routing_committed` event with the same root `run_id`.
3. M2 atomically writes `confirmed.route_commit = {event_id, run_id}`.
4. Forge invokes the child.
5. M1 records its normal `run_ended` result and clears marked active state.

This retains M1's shipped transaction seam. A later same-run authority `launch_aborted` that lands durably supersedes
`run_started` for pre-invocation presentation. The authority transaction clears marked active state but does not append
`run_ended` for an M2 pre-invocation abort.

Unmarked launches skip M1 events but use steps 2-4 under the existing launch/authority serialization boundary. Codex,
Claude host, and Claude sidecar paths reuse the same root `run_id`; no invoker remints it.

Legacy `confirmed.launch` remains best-effort and does not participate in required-state success. It may be refreshed
during launch preparation, but neither its success nor failure substitutes for the routing event/projection pair.

### Failure and compensation matrix

| Failure point                           | Routing journal                                                     | Authority journal when already touched              | Child        |
| --------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------------- | ------------ |
| Routing/context/runtime preparation     | No event                                                            | Existing M1 preflight semantics only                | Not invoked  |
| Required authority append/activation    | No event                                                            | Existing M1 abort semantics                         | Not invoked  |
| `launch_routing_committed` append       | No routing abort because no commit durably landed                   | One same-run `launch_aborted:routing_commit_failed` | Not invoked  |
| `confirmed.route_commit` projection     | Same-run `launch_aborted:route_projection_failed`                   | Same abort when the authority journal was touched   | Not invoked  |
| Compensating append                     | Primary failure remains; diagnostics name every failed compensation | Same                                                | Not invoked  |
| Child spawn after successful projection | Effective commit remains                                            | `run_ended:child_never_spawned` when M1 applies     | Spawn failed |
| Spawned child exits/cancels             | Effective commit remains                                            | Normal M1 terminal outcome                          | Invoked      |

Compensation runs in reverse touch order: routing first, then authority. Forge attempts every applicable compensation
even when an earlier one fails and aggregates the secondary diagnostics. Compensating appends are best-effort, but the
primary append/projection failure always aborts launch. A compensation failure cannot be converted into launch success
and may make history `unproven`.

The routing compensation event reuses the exact immutable payload object from `launch_routing_committed`. A catalog,
proxy, registry, or runtime change between commit and projection failure cannot alter the abort payload or turn a
successful compensation into a malformed journal.

### Authority-reader composition

M2 extends the existing advisory `launch_support` enum with `aborted`. `forge session authority show` applies this
precedence:

1. a statically unsupported advisory launch mode reports `unsupported`;
2. an advisory session without a live active entry reports `not_running`;
3. a live advisory entry whose active run/config/hook digests match a same-run authority `launch_aborted` reports
   `aborted`, whether or not active-state cleanup succeeded;
4. a live advisory entry with matching successful preflight and start evidence and no matching abort reports `verified`;
5. every other live advisory entry reports `unverified`.

Producer and unmarked sessions retain `launch_support: null`. The abort check precedes the existing verified predicate
and covers both M2 compensation and an M1 append that reports failure after a complete `run_started` record became
visible. M2 pre-invocation aborts never append `run_ended`.

If both the authority compensation append and active-state clear fail, the authority domain has no durable abort signal
and cannot honestly distinguish that attempt from its preceding start evidence without depending on routing state. The
launcher must report both secondary failures, authority limitations must disclose the temporary ambiguity while the
launcher remains live, and the routing reader follows its own available evidence. This residual does not permit child
invocation or turn the failed attempt into success.

## Routing journal contract

Each JSONL record uses the epic-owned schema-v1 envelope. Routing accepts exactly two event types:

- `launch_routing_committed`: `origin_surface=launcher`, launch operation, `outcome=success`, null reason code, and a
  required root `run_id`;
- `launch_aborted`: the same surface/operation/run id, `outcome=error`, reason `route_projection_failed`, and an exact
  payload match with its preceding same-run commit.

The routing journal never receives an abort for a failed routing append because no routing record was durably touched.
The authority journal uses `routing_commit_failed` for that case and `route_projection_failed` for projection failure.

The routing payload has this exact schema; every key is present:

```json
{
  "route": {
    "kind": "direct",
    "backend_id": null,
    "proxy_id": null,
    "template": null,
    "custom_route_fingerprint": null
  },
  "requested_model": null,
  "selected_tier": null,
  "selected_model": null,
  "default_tier": null,
  "direct_model": "claude-opus-5",
  "tier_mappings": {},
  "model_alternatives": {},
  "billing_mode": "unknown",
  "route_scope_tags": ["route:direct", "runtime:claude_code"],
  "marking_snapshots": [
    {
      "slot": "direct",
      "tier": null,
      "request_model": null,
      "route_model": "claude-opus-5",
      "canonical_model": "claude-opus-5",
      "declaration": {
        "status": "unknown",
        "basis": null,
        "source_url": null,
        "checked_at": null,
        "effective_from": null,
        "route_scope": []
      }
    }
  ]
}
```

Field contracts:

| Field                      | Contract                                                                                              |
| -------------------------- | ----------------------------------------------------------------------------------------------------- |
| `route.kind`               | One of `direct`, `proxy`, `custom`, or `runtime_native`                                               |
| `backend_id`               | Canonical backend instance id or null when not proven                                                 |
| `proxy_id`, `template`     | Concrete proxy identity when known; otherwise null                                                    |
| `custom_route_fingerprint` | Required only for `custom`; otherwise null                                                            |
| `requested_model`          | Canonical explicit user pin, otherwise null                                                           |
| `selected_tier`            | `haiku`, `sonnet`, or `opus` only for an explicit pin resolved to that tier                           |
| `selected_model`           | Exact effective route-model string for an explicit selection, otherwise null                          |
| `default_tier`             | Launch-time proxy default, otherwise null                                                             |
| `direct_model`             | Effective canonical direct Claude model after defaults and env are fixed, otherwise null              |
| `tier_mappings`            | Launch-time effective tier-to-route-model map                                                         |
| `model_alternatives`       | Launch-time tier-to-request-alias-to-route-model map                                                  |
| `billing_mode`             | `api`, `subscription_interactive`, `subscription_headless_credit`, `subscription_quota`, or `unknown` |
| `route_scope_tags`         | Sorted unique code-owned tags used for marking lookup                                                 |
| `marking_snapshots`        | One normalized declaration snapshot for every recorded model slot                                     |

Route invariants:

| Kind             | Required                                                                                                 | Forbidden/empty                                                               |
| ---------------- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `direct`         | Claude runtime; `direct_model` when Forge resolves the fixed default/pin                                 | Proxy fields, fingerprint, maps                                               |
| `proxy`          | Claude runtime; template, default tier, effective tier map; proxy/backend ids when proven                | Fingerprint, direct model                                                     |
| `custom`         | Claude runtime; secret-free fingerprint                                                                  | Proxy identity, backend id, direct model, maps                                |
| `runtime_native` | Codex runtime; `billing_mode=unknown`; scope tags are exactly `route:runtime_native` and `runtime:codex` | Model, proxy, and backend fields are null/empty; `marking_snapshots` is empty |

Unknown mapped models remain in the exact route maps. Their marking slot has `canonical_model: null` and an unknown
declaration rather than dropping the route fact.

### Secret-free custom-route fingerprint

Forge parses an HTTP(S) base URL with `urlsplit` and constructs identity bytes only from its origin:

`lowercase_scheme://lowercase_host[:non_default_port]`.

The host is normalized to IDNA ASCII (with IPv6 brackets retained), and default ports 80/443 are omitted. User
information, password, path, query, fragment, and headers are excluded before hashing. The stored form is
`sha256:<64 lowercase hex>`. A URL with another scheme, no host, an invalid port, or no secret-free canonical origin
fails routing preparation before any routing event. Forge never hashes or serializes credential-bearing URL bytes.
Different custom routes on the same origin intentionally share a fingerprint; the value is a secret-free diagnostic
correlator, not a unique route identifier.

### Marking snapshot slots

`marking_snapshots` contains one entry for:

- the effective direct model (`slot=direct`);
- every effective proxy tier default (`slot=tier_default`);
- every proxy model alternative (`slot=model_alternative`).

Entries remain separate even when they canonicalize to the same model because tier and request alias are route facts:

```json
{
  "slot": "model_alternative",
  "tier": "opus",
  "request_model": "claude-opus-5",
  "route_model": "anthropic/claude-opus-5",
  "canonical_model": "claude-opus-5",
  "declaration": {
    "status": "unknown",
    "basis": null,
    "source_url": null,
    "checked_at": null,
    "effective_from": null,
    "route_scope": []
  }
}
```

## Latest projection and history continuity

`confirmed.route_commit` is runtime-neutral and has exactly two fields:

```json
{
  "event_id": "sevt_0123456789abcdef0123456789abcdef",
  "run_id": "run_..."
}
```

The projection stores no route details and does not update `confirmed_by`. The manifest update is atomic; failure leaves
the previous projection intact. A route commit is **effective** when no later same-run `launch_aborted` exists. The
newest effective commit is selected by append order, not timestamp.

Domain continuity validation requires every event runtime to equal the manifest's immutable runtime. It treats duplicate
commits for one run, duplicate aborts, an abort without a prior same-run commit, an abort before its commit, payload
mismatch, a route-kind/runtime mismatch, or an invalid event-specific envelope as a malformed journal and a command
error.

After structural validation, history status is:

| Projection/journal state                                                               | Status        |
| -------------------------------------------------------------------------------------- | ------------- |
| No projection and routing journal path absent                                          | `null`        |
| No projection and an empty routing journal file exists                                 | `unproven`    |
| No projection; journal contains only valid aborted attempts                            | `supported`   |
| No projection; at least one effective commit exists                                    | `unproven`    |
| Projection exactly identifies the newest effective commit                              | `supported`   |
| Projection identifies an older effective commit and only newer aborted attempts follow | `supported`   |
| Projection has no exact event/run match                                                | `unproven`    |
| Projection identifies a commit that was later aborted                                  | `unproven`    |
| Projection identifies an older effective commit while a newer effective commit exists  | `unproven`    |
| Projection exists but no effective commit exists                                       | `unproven`    |
| Journal is unreadable, malformed, or newer-schema                                      | Command error |

Journal-path absence means no routing-history claim. Path presence means routing history was initiated; an existing
empty file contains no complete event with which to prove continuity and is therefore `unproven`, not `null`. Forge does
not infer whether the empty file came from a failed append, a crash, or external mutation.

The “newer aborted attempts” rule keeps a prior successful projection valid after a later pre-invocation projection
failure. A missing compensating abort leaves the newer commit effective, so the stale/missing projection correctly
yields `unproven`.

Existing manifests are not backfilled. When `confirmed.route_commit` is absent but Claude-only `confirmed.launch` is
present, `show` may render that legacy route summary with null run/event ids and
`evidence_source: legacy_confirmed_launch`; `history_status` follows the table and remains `null` when no routing
journal exists. It never synthesizes a journal or launch marking snapshot. After the first M2 event, `supported` covers
journaled attempts only and does not claim complete pre-feature history.

## Stable read contracts

### `session model show --json`

Every top-level key and every nested key shown below is stable and remains present. Nulls and empty maps/lists represent
unavailable or inapplicable facts; fields are not omitted.

```json
{
  "schema_version": 1,
  "session": "planner",
  "runtime": "claude_code",
  "active": true,
  "route_intent": {
    "kind": "proxy",
    "template": "openrouter-anthropic",
    "proxy_id": null,
    "custom_route_fingerprint": null,
    "requested_model": "claude-opus-5"
  },
  "route_commit": {
    "run_id": "run_...",
    "event_id": "sevt_...",
    "evidence_source": "route_commit",
    "kind": "proxy",
    "backend_id": "openrouter",
    "proxy_id": "or-anthropic-1",
    "template": "openrouter-anthropic",
    "custom_route_fingerprint": null,
    "requested_model": "claude-opus-5",
    "selected_tier": "opus",
    "selected_model": "anthropic/claude-opus-5",
    "default_tier": "sonnet",
    "direct_model": null,
    "tier_mappings": {"haiku": "...", "sonnet": "...", "opus": "..."},
    "model_alternatives": {"opus": {"claude-opus-5": "anthropic/claude-opus-5"}},
    "billing_mode": "unknown",
    "route_scope_tags": ["backend:openrouter", "route:proxy", "runtime:claude_code"]
  },
  "live_proxy": {
    "reachable": true,
    "evidence_source": "runtime",
    "proxy_id": "or-anthropic-1",
    "template": "openrouter-anthropic",
    "backend_id": "openrouter",
    "default_tier": "sonnet",
    "tier_mappings": {"haiku": "...", "sonnet": "...", "opus": "..."},
    "model_alternatives": {"opus": {"claude-opus-5": "anthropic/claude-opus-5"}}
  },
  "current_request_tier": null,
  "current_request_source": "unavailable",
  "history_status": "supported",
  "marking": {
    "scope": "text",
    "provider_declared": true,
    "launch_entries": [
      {
        "slot": "model_alternative",
        "tier": "opus",
        "request_model": "claude-opus-5",
        "route_model": "anthropic/claude-opus-5",
        "canonical_model": "claude-opus-5",
        "launch_snapshot": {
          "status": "unknown",
          "basis": null,
          "source_url": null,
          "checked_at": null,
          "effective_from": null,
          "route_scope": []
        },
        "current_declaration": {
          "status": "unknown",
          "basis": null,
          "source_url": null,
          "checked_at": null,
          "effective_from": null,
          "route_scope": []
        },
        "changed_since_launch": false
      }
    ],
    "live_proxy_entries": [
      {
        "slot": "model_alternative",
        "tier": "opus",
        "request_model": "claude-opus-5",
        "route_model": "anthropic/claude-opus-5",
        "canonical_model": "claude-opus-5",
        "evidence_source": "runtime",
        "declaration": {
          "status": "unknown",
          "basis": null,
          "source_url": null,
          "checked_at": null,
          "effective_from": null,
          "route_scope": []
        }
      }
    ]
  },
  "limitations": ["route commitment only", "no per-request or authorship attestation"]
}
```

Variant rules:

- `route_intent.kind` is derived only from manifest intent/runtime. Registry or live state cannot rewrite intent.
- A supported projection produces `evidence_source=route_commit` and journal-derived details.
- An inconsistent projection produces `evidence_source=unproven_projection`, preserves only its event/run ids, and sets
  all route-detail fields to null/empty. It never presents an unsupported event as current.
- Supported route commitments expose journal-owned `billing_mode` and `route_scope_tags` alongside the route/model maps.
  An inconsistent projection uses null billing and an empty tag list; clients do not reconstruct either value.
- A legacy summary uses `legacy_confirmed_launch`; absent route evidence uses null `route_commit`.
- `live_proxy.evidence_source` is one of `runtime | proxy_config | route_commit | not_applicable | unavailable`. Runtime
  is preferred; unreadable/unreachable auxiliary proxy state falls back without changing command success.
- A valid proxy-routed session with an unreachable proxy reports `reachable=false` and labels whichever fallback was
  usable. It never labels fallback mappings as runtime truth.
- Direct and runtime-native sessions use `reachable=false`, `evidence_source=not_applicable`, null identity/default, and
  empty maps.
- `marking.launch_entries` is derived only from journaled `marking_snapshots`. Each entry compares its immutable launch
  snapshot with the current catalog declaration under the launch route scope. Legacy and no-evidence routes use an empty
  list rather than synthesizing a launch claim.
- `marking.live_proxy_entries` is populated only from authoritative `live_proxy.evidence_source=runtime` mappings. Each
  entry carries `evidence_source=runtime` and resolves the current declaration under the live route scope. Config or
  route-commit fallback leaves the list empty even when `live_proxy` exposes labelled fallback maps.
- For launch entries, `changed_since_launch` compares the full normalized declaration object, including sorted scope
  tags and dates.
- Missing sessions, unreadable manifests, malformed active-session registry state, and malformed journals are command
  errors. Runtime/proxy fallback failures are successful reads with limitations.

### `session model history --json`

History returns the validated envelope and exact routing payload for every event in append order. V1 is intentionally
unbounded at the terminal CLI and has no direct-command mirror.

```json
{
  "schema_version": 1,
  "session": "new-session",
  "history_status": null,
  "events": []
}
```

A nonempty `events` item contains all schema-v1 envelope fields plus `payload` exactly as specified in the routing
journal contract. Human output may summarize, but it preserves append order, event/run ids, commit-versus-abort, route
kind, model slots, and evidence limitations.

## Declared text-marking metadata

`model_practices.yaml` is versioned, packaged internal data, not an intrinsic capability catalog or user edit surface.
The initial production file is deliberately:

```yaml
schema_version: 1
models: {}
```

Unknown is a derived absence state and is not stored as a declaration. A future source-reviewed entry has this shape:

```yaml
schema_version: 1
models:
  claude-opus-5:
    text_marking:
      - status: marked
        basis: provider_declaration
        source_url: https://provider.example/declaration
        checked_at: 2026-08-20
        effective_from: 2026-08-02
        route_scope:
          - backend:openrouter
          - route:proxy
          - runtime:claude_code
```

Catalog rules:

- top-level fields are exactly `schema_version` and `models`; model entries accept only `text_marking`;
- model keys must be canonical ids in `model_catalog.yaml`; aliases and provider-prefixed ids are invalid keys;
- stored status is `marked | unmarked`; output status additionally includes derived `unknown`;
- basis is exactly `provider_declaration`;
- every declaration requires an HTTPS source URL without user information, an ISO `checked_at` date, and a nonempty
  sorted unique route scope; `effective_from` is an ISO date or null when the provider stated no effective date;
- `unmarked` requires an affirmative provider declaration and is never inferred from silence, model age, failed
  detection, or absence of a known marking announcement;
- a future-dated `effective_from` declaration does not match until that UTC calendar date;
- unknown schema versions, unknown fields/tags, invalid models/dates/URLs, duplicate declarations, or more than one
  declaration matching the same derived route state make the packaged catalog invalid;
- launch/show catalog failure is an actionable command or launch-preparation error. The status line remains exit-zero
  and resolves the segment to `mark:?` for expected acquisition/catalog failures.

### Route-scope grammar

Route scope is a conjunction: every tag listed by the declaration must exist in the derived route tag set. Additional
derived tags do not prevent a match. Code owns four tag families:

- `runtime:claude_code | runtime:codex`;
- `route:direct | route:proxy | route:custom | route:runtime_native`;
- `backend:<canonical-backend-id>`;
- `billing:<BillingMode>`.

Every non-unknown declaration requires exactly one runtime tag, one route tag, and one backend tag. A billing tag is
optional and is used only when the provider declaration is billing-path-specific. Forge adds backend or billing tags
only when launch/runtime evidence proves them; missing or ambiguous evidence does not match a declaration that requires
that tag. Proxy upstream billing is normally `unknown`, but a declaration without a billing tag may still match an exact
runtime/route/backend scope.

For proxy routes, the effective proxy config/runtime response may prove `backend_id`; upstream billing remains unknown.
For direct Claude routes, M2 keeps `backend_id=null` and `billing_mode=unknown`: existing API-key availability is a
capability, not proof of whether Claude Code used API or subscription billing. Codex v1 also records neither exact model
nor exact backend. Direct Claude, Codex, and custom routes therefore resolve marking to unknown in M2 unless a future
separately designed evidence source closes those gaps.

### Model normalization

For marking lookup, Forge:

1. removes the Claude Code model-hint `[1m]` suffix through a shared runtime-neutral core-model helper;
2. tries the exact model-catalog id or alias;
3. for a provider-prefixed route model, removes one provider prefix and retries catalog resolution;
4. records the resulting canonical id or null without guessing.

The marking module does not add another literal suffix remover and does not call `resolve_direct_model_pin`, whose
Claude-only tier and environment validation is too narrow for proxy and unknown route models. M2 factors the common
suffix/catalog-lookup behavior at the neutral `forge.core.models` owner, reuses the catalog resolver and existing suffix
vocabulary, and repoints equivalent suffix-only lookup sites while preserving their caller-specific error and 1M-context
behavior.

Launch proxy slots use the effective runtime tier map plus the effective model-alternative map, including any runtime
ZDR substitution applied to either. The status line uses the authoritative live equivalents. Unknown or removed models
remain route facts but resolve to an unknown declaration.

Journal snapshots preserve the normalized declaration and scope used at launch. `show` resolves the current declaration
against the same canonical model and launch route-scope tags, so `changed_since_launch` reflects catalog declaration
change rather than unrelated current proxy drift.

Every surface labels the value as provider-declared. `mark:no` means “declared unmarked for this model and route,” not
“Forge proved this output has no mark.”

## Live proxy and status-line contract

M2 extends proxy `GET /` runtime truth with two secret-free fields sourced from the loaded effective proxy config:

- `runtime.backend_id`: canonical backend instance id or null;
- `runtime.model_alternatives`: effective tier-to-request-alias-to-route-model map.

The existing `runtime.tier_mappings`, `runtime.context_windows`, and `routing.default_tier` fields retain their prior
shape and remain authoritative for live defaults. Config/registry fallback may expose the same shape but is labelled
non-authoritative.

The default-off `marking` segment declares both proxy and session shared sources:

- stdin `model.id` supplies the observed request model;
- for proxy routes, explicit tier in `model.id` wins, then the proxy default, matching existing routing/drift
  precedence;
- a matching live model alternative wins before the tier default, matching proxy dispatch;
- non-unknown proxy output requires authoritative `GET /`; registry/config fallback renders `mark:?`;
- direct output performs no session or routing-journal read: because M2 deliberately leaves direct backend identity
  unproven, durable route facts cannot refine the result and direct output remains `mark:?` until a separately designed
  evidence source closes that gap;
- missing observed model omits only the marking segment;
- expected catalog/source/mapping failures render `mark:?`; unexpected producer failures drop only the segment;
- the status-line process always exits zero and `DEFAULT_ORDER` remains unchanged.

The statusline token is documented as provider-declared and remains separate from authority. It never changes a role,
color, enforcement decision, or admission outcome.

## Composition with artifact authority mode

- Route and marking reads never set, clear, inherit, or authorize an authority role.
- Reattaching an inactive session preserves its existing authority intent. Fresh/fork/forced children follow authority
  inheritance: advisory inherits; producer never does.
- A running producer cannot switch by opening a second attachment. The user must stop it and resume, or use `--force`
  and explicitly designate the resulting child as producer from the external control plane.
- The supported marking-sensitive flow remains a fresh, transfer-free producer in a distinct worktree. A declaration can
  inform the human's model choice but cannot replace that separation.
- A human can reduce configuration-local tier drift by inspecting a producer proxy whose current tier defaults and all
  `model_alternatives` entries appear in `marking.live_proxy_entries` and resolve to `unmarked` for the exact live route
  scope. This is guidance, not prevention or admission: an absent or `unknown` entry does not qualify, and
  custom/pass-through routes, later provider/proxy changes, and marked content already in context remain outside the
  claim.
- Authority and routing keep separate journals and typed reads. The epic owns their common envelope, `run_id`,
  origin/outcome vocabulary, compensation, lock/write helpers, and no-attestation language.
- V1 keeps authority role/tier out of the status line. `marking` remains a distinct default-off segment.

## Pre-M2 foundation

- Claude `--model` on start/resume/fork, including persisted direct and proxy-alternative pins.
- Persisted `resume --proxy` / `--no-proxy` routing overrides and template auto-start.
- Claude-only `confirmed.launch`, `session show --json`, session context model maps, status-line stdin model identity,
  and live proxy truth.
- Direct transcript model-transition reads and proxy downstream `mapped_model` evidence, retained as separate planes.
- Runtime-neutral `forge.session.events` envelope/path/lock/read/write primitives had the `routing` domain reserved for
  this member.
- M1's root-run launch transaction and authority abort vocabulary. M2 extends that seam; it does not fork it.

## Non-goals

- No generic model-to-route resolution; see the adjacent model-first routing card.
- No live route switch inside a running process.
- No per-request session correlation or duplication of downstream telemetry.
- No model allowlist, request refusal, authority decision, or admission gate.
- No watermark detection, removal, persistence testing, or content/authorship attestation.
- No signed-file provenance classification in v1.
- No proxy mutation or mutating `%session model` command.
- No provider-declaration population in M2's initial production catalog.

## V1 acceptance boundary

01. Existing Claude `--model`, `--proxy`, and `--no-proxy` behavior remains byte-compatible outside added provenance.
    Sidecar template resolution may populate the routing payload's proxy id but does not rebind the legacy
    `confirmed.launch`, runner, presentation callback, or launch-result proxy id.
02. Every managed attempt crossing the routing commitment boundary appends exactly one locked, complete routing commit
    before child invocation, regardless of requested read/status surfaces.
03. The exact D1 ordering and failure matrix hold with M1 active and inactive. Routing append failure compensates every
    authority journal already touched; projection failure compensates both routing and touched authority journals. A
    landed authority abort reports advisory `launch_support=aborted` even when active-state clear fails; simultaneous
    authority-abort and clear failure follows the documented residual limitation.
04. `confirmed.route_commit` contains only event/run ids and identifies the newest effective route commit. Spawn or
    child failure after successful projection does not append a routing abort.
05. Routing domain validation enforces the exact payload/invariants and cross-event continuity rules. Commit and abort
    serialize one immutable payload object; malformed journals are command errors.
06. History implements the complete status table, including prior projection plus newer aborted attempt and failed
    compensation cases.
07. `session model show --json` implements every stable variant rule, exposes committed billing/scope facts, keeps
    journal-derived launch marking separate from authoritative live-proxy marking, and never reports proxy default as
    current request tier.
08. `%session model show [session]` is read-only, mirrors the CLI leaf spelling, and emits a fixed-size human summary
    without history, mapping, or declaration-array dumps.
09. `session model history --json` returns validated full events in append order and distinguishes
    `supported | unproven | null`.
10. Proxy `GET /` additively exposes canonical backend id and model alternatives without credentials, preserving the
    existing tier-mapping/context-window shape; fallbacks remain labelled.
11. The package-owned marking catalog validates the exact schema, scope grammar, UTC-effective dates, URLs, and
    canonical model keys. Production data is intentionally all unknown; marked/unmarked fixtures exercise both output
    paths.
12. Claude status-line marking selects explicit request tier/alternative before proxy default, uses authoritative live
    proxy truth for non-unknown proxy output, remains default-off, and always fails open.
13. Codex route history is `runtime_native` with unknown exact backend/model/billing and empty marking snapshots.
14. No read or journal event claims per-request use, artifact authorship, watermark detection, or admission.
15. Design and end-user docs describe the shipped source/absence contracts; targeted unit, regression, managed-session
    and proxy integration tests pass; a clean wheel loads and validates `model_practices.yaml`.

## Risks

- **Stale declarations**: source/date/scope fields make age visible but cannot force a provider to announce changes.
- **False comfort**: even a currently declared-unmarked producer model may transcribe earlier marked context. User docs
  must preserve the transfer-free-flow warning.
- **Journal overclaim**: launch maps can diverge from later proxy configuration and per-request choices. Reads label
  snapshots and current runtime truth separately.
- **Status-line availability**: only the status-line process sees the current request model. Other reads return
  unavailable rather than guessing.
- **Operational-state trust**: local JSONL is mutable by humans and external processes and is not tamper-proof.
- **Launch availability**: routing durability and catalog validity are hard dependencies of every managed launch after
  M2 activation. Diagnostics name the failed path/operation; repair and retry replace silent degradation.
- **Dual authority-state failure**: if authority compensation and active-state clear both fail, the authority read
  cannot durably prove the pre-invocation abort while the launcher remains live. Diagnostics and authority limitations
  disclose this temporary ambiguity; routing evidence remains separately labelled.
- **Proxy response coupling**: status/read code must tolerate older or unreachable proxies by labelling fallback, while
  non-unknown live marking requires the new authoritative fields.
