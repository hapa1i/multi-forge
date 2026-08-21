# Session Route Provenance and Marking

**Status**: Proposed (2026-08-20).

**Epic**: M2 member of [Epic: Session Authority and Provenance](../../doing/epic_session_authority_provenance/card.md),
which owns the shared event envelope, run correlation, and presentation boundaries with
[Artifact Authority Mode](../../done/artifact_authority_mode/card.md), the epic's shipped M1 member.

**Relationship**: authority mode decides which managed session may mutate project artifacts. This card reports how a
managed session was routed and the provider-declared text-marking posture of the selected or mapped model. It adds no
authority, enforcement, authorship attestation, or content guarantee. Generic model-to-route selection is separate in
[Model-First Interactive Session Routing](../model_first_session_routing/card.md); this card does not depend on it.

**References**: [design.md §3](../../../design.md#3-shared-contracts-file-based-state-system) (session state),
[design.md §3.4](../../../design.md#34-proxy-vs-no-proxy-mode) (routing ownership),
[design.md §3.7](../../../design.md#37-proxy-runtime-truth) (live proxy facts),
[design.md §3.9](../../../design.md#39-session-resume-context-management) (launch lifecycle),
[design_appendix.md §A.5](../../../design_appendix.md#a5-model-catalog-368) (intrinsic model catalog),
[design_appendix.md §A.8](../../../design_appendix.md#a8-status-line-guidance-3611) (status-line sources),
`src/forge/session/launch_confirmation.py` (existing Claude-only route/auth confirmation),
`src/forge/core/ops/session_context.py` (current model context), and the sibling authority card.

## Problem

Forge already supports Claude model pins on `session start`, `resume`, and `fork`; `resume --model` persists the new
pin, and `resume --proxy` / `--no-proxy` persist route intent. Existing reads expose pieces of the result:

- `forge session show --json` includes the direct pin or proxy tier map;
- `confirmed.launch` records the latest route and API-key posture;
- the status line sees Claude Code's current request model through stdin and can combine it with live proxy mappings;
- copied direct-session transcripts retain observed assistant model transitions;
- proxy downstream telemetry records `mapped_model` per attempt.

What is missing is one session-scoped history of launch routing decisions, a typed read that distinguishes intent from
confirmed and live facts, and carefully scoped provider-declared text-marking metadata. The current evidence cannot
honestly answer which backend authored every turn: live `/model` changes happen per request, proxy requests from the
main interactive harness are not session-correlated, and earlier model content can remain in conversation context.

The provider-marking scenario sharpens the need for honest labels. An operator may want to know whether the model
selected for a producer launch is declared to embed text marks, but that declaration is not detection and does not prove
the provenance of an artifact.

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
- `forge session model show` and `%session model show` have no status-line stdin. They report
  `current_request_tier: null` and `current_request_source: unavailable`; they never relabel the proxy default as the
  session's current tier.
- The opt-in status-line segment may report the observed request tier because that process receives Claude Code's
  current model id. It labels the source as request-observed, not session-persisted.
- `session model history` is launch routing history. It does not claim per-request model use, authorship, admission, or
  watermark presence.

## Goal

1. **Typed read surfaces**: `forge session model show [session] [--json]` renders a stable evidence vector containing
   session/runtime/active state, route intent, latest committed route, live proxy identity and tier mappings when
   reachable, requested or pinned model, proxy default tier, unavailable current-request state, declared text-marking
   posture, and limitations. `%session model show [session]` is the read-only in-session mirror. There is no mutating
   direct-command surface.
2. **Launch routing history**: `forge session model history [session] [--json]` reads
   `.forge/artifacts/<session>/routing/events.jsonl`. It reports `history_status: supported | unproven | null` using the
   same absence-of-evidence posture as authority history. The direct command does not mirror history in v1, avoiding an
   unbounded hook response.
3. **One committed routing event per successful managed launch**: after routing, context-budget, and runtime preflight
   succeed and after child argv/env are fixed, but before invoking the child, Forge appends `launch_routing_committed`.
   An append failure aborts the launch; failures before that boundary do not create history. The event says the launch
   decision was committed, not that the child completed successfully. If the later required route projection fails,
   Forge attempts a compensating `launch_aborted` append for the same attempt. The journal is mandatory session state,
   not opt-in telemetry: launching and degrading later to `unproven` would violate this card's evidence contract. This
   intentionally strengthens the current best-effort `confirmed.launch` posture.
4. **Latest-state projection**: add runtime-neutral `confirmed.route_commit` and write the routing commit's `event_id`
   and existing root `run_id` after every required prelaunch journal append succeeds. The journal is history and
   `confirmed.route_commit` is the latest projection. A projection failure aborts child invocation and triggers the
   epic's compensating events. The projection never substitutes for a missing or malformed journal when continuity is
   claimed. Existing Claude-only `confirmed.launch` keeps its Anthropic auth/cost meaning and remains unset for Codex.
5. **Provider-declared text-marking metadata**: add a separate repo-owned `src/forge/core/data/model_practices.yaml`.
   The intrinsic model catalog remains free of temporal provider practices. V1 covers embedded text marking only, not
   signed file provenance metadata.
6. **Opt-in status-line segment**: a default-off `marking` segment renders the observed request model's declared text
   marking as `mark:yes`, `mark:no`, or `mark:?`. It uses Claude stdin plus the proxy source like the existing `model`
   and `drift` segments. `DEFAULT_ORDER` is unchanged.
7. **Runtime-neutral route history, runtime-specific model detail**: Claude launches record direct/proxy/custom route
   detail. Codex launches record `route.kind: runtime_native`, `requested_model: null`, and marking `unknown`; this card
   does not add Codex model selection or claim that Forge observes Codex's exact model.

## Stable read shape

Human output may be compact, but `session model show --json` keeps this semantic shape stable:

```json
{
  "schema_version": 1,
  "session": "planner",
  "runtime": "claude_code",
  "active": true,
  "route_intent": {
    "kind": "proxy",
    "template": "openrouter-anthropic",
    "requested_model": "claude-opus-5"
  },
  "route_commit": {
    "run_id": "run_...",
    "event_id": "sevt_...",
    "evidence_source": "route_commit",
    "kind": "proxy",
    "source_id": "openrouter",
    "proxy_id": "or-anthropic-1",
    "requested_model": "claude-opus-5",
    "selected_tier": "opus"
  },
  "live_proxy": {
    "reachable": true,
    "evidence_source": "runtime",
    "source_id": "openrouter",
    "default_tier": "sonnet",
    "tier_mappings": {"haiku": "...", "sonnet": "...", "opus": "..."}
  },
  "current_request_tier": null,
  "current_request_source": "unavailable",
  "history_status": "supported",
  "marking": {
    "scope": "text",
    "entries": [
      {
        "tier": "opus",
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
    ]
  },
  "limitations": ["route commitment only", "no per-request or authorship attestation"]
}
```

Unavailable or inapplicable fields remain present as `null`, `false`, or empty objects/lists. A valid session with an
unreachable proxy is a successful read with `live_proxy.reachable: false` and a clearly labelled manifest/config
fallback. Missing sessions, unreadable manifests, and malformed journals are command errors.

`session model history --json` returns an object, not a bare array:

```json
{
  "schema_version": 1,
  "session": "new-session",
  "history_status": null,
  "events": []
}
```

## Routing journal contract

Each JSONL event uses the epic-owned envelope and contains:

- `schema_version`, event id, timestamp, session, runtime, `event_type`, `run_id`, `origin_surface`, operation, outcome,
  and optional reason code;
- route kind (`direct | proxy | custom | runtime_native`), backend source id and proxy id/template when known, and a
  secret-free custom-route fingerprint rather than a credential-bearing URL;
- requested model and selected tier when explicitly pinned, otherwise `null`;
- direct model pin or the launch-time resolved tier map;
- a marking snapshot per recorded canonical model, including status, basis, source URL, checked date, effective date,
  and route scope.

The normal event is `launch_routing_committed` with outcome `success`. When the required route projection fails after
that commit, Forge best-effort appends `launch_aborted` with outcome `error` and a stable reason code. The epic's
preallocated root `run_id` is required on the commit, and the compensating event reuses it. `origin_surface` identifies
the observing layer; `operation` distinguishes start, resume, fork, and incognito while `runtime` distinguishes Claude
and Codex launch paths. Appends are serialized under a dedicated journal lock and write one complete record per
acquisition. The file contains no prompts, transcript text, generated content, patches, credentials, or
credential-bearing route URLs.

The file is append-only by Forge convention, not tamper-proof evidence. If `confirmed.route_commit.event_id` has no
exact matching `launch_routing_committed` event with the same `run_id`, history is `unproven`. A session with neither a
route commitment nor a journal uses `null`. Malformed or unreadable journal state is a command error. Routing and
authority journals follow epic C3 retention: session deletion and cleanup preserve them with the containing
`.forge/artifacts/<session>` tree regardless of `--keep-transcripts`.

Existing manifests are not backfilled. When `confirmed.route_commit` is absent but Claude-only `confirmed.launch` is
present, `show` may render that legacy route summary with `run_id: null`, `event_id: null`, and
`evidence_source: legacy_confirmed_launch`; `history_status` remains `null`. It never synthesizes a journal or upgrades
legacy state into continuity evidence, and its marking `launch_snapshot` is `null`. After the first new route commit,
`supported` covers journaled commitments only; it does not claim a complete pre-feature session history.

## Declared text-marking metadata

`model_practices.yaml` is versioned, packaged internal data but not an intrinsic-capability catalog or user edit
surface. Each non-unknown declaration has this shape:

```yaml
text_marking:
  status: marked # marked | unmarked | unknown
  basis: provider_declaration
  source_url: https://...
  checked_at: 2026-08-20
  effective_from: 2026-08-02
  route_scope: ["runtime:claude_code:subscription", "source:anthropic-direct"]
```

Rules:

- omitted entries and omitted fields resolve to `unknown`;
- `marked` and `unmarked` require a source URL, checked date, and explicit route scope;
- `unmarked` requires an affirmative provider declaration and is never inferred from silence, model age, failed
  detection, or absence of a known marking announcement;
- route scopes are code-owned tags derived from the runtime, backend source id, and auth/billing posture; a launch that
  cannot be mapped to an exact listed scope resolves to `unknown`;
- the first release initializes every model to `unknown`; individually supported declarations are populated only after
  source review;
- journal snapshots preserve the declaration used at launch, while `show` reports both the launch snapshot and current
  declaration if they differ.

Every surface labels the value as provider-declared. `mark:no` means "declared unmarked for this model and route," not
"Forge proved this output has no mark."

## Composition with artifact authority mode

- Route and marking reads never set, clear, inherit, or authorize an authority role.
- Reattaching an inactive session preserves its existing authority intent. Fresh/fork/forced children follow authority
  inheritance: advisory inherits; producer never does.
- A running producer cannot switch by opening a second attachment. The user must stop it and resume, or use `--force`
  and explicitly designate the resulting child as producer from the external control plane.
- The supported watermark-sensitive flow remains a fresh, transfer-free producer in a distinct worktree. A marking
  declaration can inform the human's model choice but cannot replace that separation.
- Operators can prevent configuration-local tier drift from reaching a known-marked model by using a producer proxy
  whose every tier and every `model_alternatives` entry maps to a model declared `unmarked` for the exact route scope.
  This is configuration guidance, not an attestation: `unknown` does not qualify, and custom/pass-through routes,
  provider or proxy-config changes, and marked content already in context remain outside the claim.
- Authority and routing keep separate journals and separate typed reads. The epic owns their common envelope, `run_id`,
  origin/outcome vocabulary, lock/write helpers, and no-attestation language.
- V1 keeps authority role/tier out of the status line. `marking` remains a distinct default-off segment; it is never
  merged into a badge that could imply marking changes authority.

## Existing foundation

- Claude `--model` on start/resume/fork, including persisted direct and proxy-alternative pins.
- Persisted `resume --proxy` / `--no-proxy` routing overrides and template auto-start for explicitly named templates.
- Claude-only `confirmed.launch`, `session show --json`, session context model maps, status-line stdin model identity,
  and live proxy truth. The new runtime-neutral route projection does not widen `confirmed.launch`, whose Anthropic
  key/cost meaning intentionally excludes Codex.
- Direct transcript model-transition reads and proxy downstream `mapped_model` evidence, retained as separate evidence
  planes.
- Session artifact paths, locked JSONL patterns, and runtime-neutral managed session lifecycle entry points.

## Non-goals

- No generic model-to-route resolution; see the adjacent model-first routing card.
- No live route switch inside a running process.
- No per-request session correlation or duplication of downstream telemetry.
- No model allowlist, request refusal, authority decision, or admission gate.
- No watermark detection, removal, persistence testing, or content/authorship attestation.
- No signed-file provenance classification in v1.
- No proxy mutation or mutating `%session model` command.

## V1 acceptance boundary

01. Existing Claude `--model`, `--proxy`, and `--no-proxy` behavior remains byte-compatible outside added provenance.
02. Every successfully invoked managed launch appends exactly one locked, complete routing-commit event before child
    invocation. Required journal or route-projection failure prevents launch; a projection failure attempts one
    best-effort, same-`run_id` abort event. This requirement applies even when no history read or status-line segment
    was requested.
03. `confirmed.route_commit.event_id` and `.run_id` identify the corresponding routing event without replacing history;
    existing `confirmed.launch` semantics do not change and legacy manifests are not backfilled.
04. Failed preflight and context-budget checks append no committed-launch event.
05. `session model show --json` has the stable evidence-vector shape and never reports proxy default as current request
    tier.
06. `%session model show [session]` is read-only, mirrors the CLI leaf spelling, and emits no history dump.
07. `session model history --json` distinguishes `supported`, `unproven`, and `null`; malformed journals fail closed as
    command errors.
08. Claude status-line marking selects the request tier from stdin before consulting the proxy default, matching the
    existing drift segment's precedence.
09. Codex route history is `runtime_native` with unknown exact model/marking and no new selection flag.
10. Non-unknown marking declarations require source, date, effective scope, and route coverage; the initial catalog is
    all unknown until entries are reviewed individually.
11. No read or journal event claims per-request use, artifact authorship, watermark detection, or admission.
12. Authority and routing events use the epic-owned envelope and shared `run_id` without combining the two journals or
    presentation meanings.

## Risks

- **Stale declarations**: source/date/scope fields make age visible but cannot force a provider to announce changes.
- **False comfort**: even a currently declared-unmarked producer model may transcribe earlier marked context. User docs
  must preserve the transfer-free-flow warning.
- **Journal overclaim**: launch maps can diverge from later proxy configuration and live `/model` choices. Reads label
  snapshots and current runtime truth separately.
- **Status-line availability**: only the status-line process sees the current request model. Other reads return
  unavailable rather than guessing.
- **Operational-state trust**: local JSONL is mutable by humans and external processes and is not an evidence ledger
  against tampering.
- **Launch availability**: routing durability is a hard dependency of every managed launch after M2 activation. A full
  filesystem, unwritable or invalid routing directory, failed append, or failed manifest projection blocks launch even
  when provenance is not being displayed. Diagnostics name the failed path and operation; the operator repairs storage,
  permissions, or session state and retries rather than degrading the launch to `unproven`.
