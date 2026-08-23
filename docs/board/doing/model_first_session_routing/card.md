# Model-First Interactive Session Routing

**Status**: Active (accepted and moved to `doing/` on 2026-08-23 after documentation review). **Branch**:
`feat/model-first-session-routing`, based on `main` at `46bb9e4b`. Adjacent to, but not a member of,
[Epic: Session Authority and Provenance](../../done/epic_session_authority_provenance/card.md).

**Relationship**: [Session Route Provenance and Marking](../../done/session_route_provenance/card.md) reports launch
decisions without changing them. This card widens the existing `--model` option into an explicit model-first selector
for interactive Claude sessions. It neither depends on authority mode nor changes authority inheritance.

**References**: [design.md §3.4](../../../design.md#34-proxy-vs-no-proxy-mode),
[design_runtime.md §3.6.12](../../../design_runtime.md#3612-subprocess-routing-resolution-normative),
[design_sessions.md §3.9](../../../design_sessions.md#39-session-resume-context-management),
[design_runtime.md §A.5](../../../design_runtime.md#a5-model-catalog-368),
[design_runtime.md §G](../../../design_runtime.md#g-subprocess-routing-reference),
`src/forge/core/models/direct_model.py`, `src/forge/backend/sources.py`, `src/forge/session/model_pin.py`,
`src/forge/core/ops/session_routing.py`, `src/forge/core/ops/session_model.py`, `src/forge/runtime_config.py`,
`src/forge/review/models.py`, `src/forge/review/routing.py`, and `src/forge/core/reactive/routing.py`.

## Problem

Interactive Claude sessions already accept `--model`, but that flag is currently a Claude model pin:

- on a new session without `--proxy`, it selects a direct Anthropic model through Claude Code environment variables;
- with an explicit or persisted proxy, it selects a supported Claude tier default or `model_alternatives` entry;
- `resume --model` and `fork --model` persist the pin without otherwise changing a compatible route;
- `incognito --model` applies the pin for that temporary session;
- non-Claude catalog models are rejected.

The user-facing request is nevertheless the same for Claude and non-Claude models: choose the model the interactive
session should use. Requiring `--model` for Claude but a second `--route-model` spelling for every other catalog model
would force users to know whether Forge considers the request a pin or a routing operation before they can issue it.

Widening `--model` does not require ambient selection. Existing successful invocations can retain their effective route,
explicit route flags can remain strict, and only an explicit model request that the applicable route cannot serve needs
deterministic catalog resolution. A bare command, a config default, an unrelated running proxy, or an old manifest must
never activate model-first proxy selection.

The workflow resolver is prior art but not a drop-in implementation. Its `provider_refs` live on a limited review-worker
registry, `derive_model_routes()` does not inspect the proxy registry, and `resolve_subprocess_routing()` scans running
proxies without auto-starting a derived template. Interactive routing needs a shared route catalog, explicit
persistence, and stricter failure semantics.

## Existing behavior protected

- Every currently successful `session start|resume|fork|incognito --model <claude-id-or-alias>` invocation, including
  Claude's transport-only `[1m]` suffix, retains its effective direct/proxy route, Claude model, tier, and existing
  `direct_model` execution projection.
- A new Claude session with `--model` and no explicit proxy route remains direct. Catalog ordering or a running proxy
  cannot change that result.
- Explicit `--proxy` remains an exact route constraint; explicit `--no-proxy` remains a direct-only constraint.
- Resume/fork first tries the persisted or inherited route. If it can serve the explicit model, `--model` does not move
  the session to a different provider or template.
- `default_direct_model` remains a Claude-only direct pin. It never invokes model-first route selection or starts a
  proxy for a bare command.
- `session adopt --model` remains Claude-only because it records a pin for an adopted native conversation rather than
  selecting an interactive launch route.
- Codex continues to reject Claude-runtime routing flags and resolves its model natively.
- Existing v1 manifests with only `LaunchIntent.direct_model` retain their current behavior without a standalone
  migration command. A current Forge reader accepts them; the first ordinary manifest mutation upgrades the complete
  document to v2.

Changing a previously rejected explicit non-Claude `--model` input into a supported routed launch is the intentional
capability expansion. No currently successful input changes provider, auth, billing, cache behavior, or wire shape.

## Goal

1. Widen `--model <catalog-id>` on Claude-runtime `session start`, `resume`, `fork`, and `incognito` to accept any
   canonical model id or alias while preserving the successful Claude-pin behavior above, including `[1m]`. Do not add
   `--route-model`.
2. Add optional `--tier <haiku|sonnet|opus>` for cases where a selected proxy can serve the model through multiple tiers
   with different hyperparameters.
3. Preserve deterministic route preference in a new packaged, non-user-editable `src/forge/core/data/model_routes.yaml`.
   It owns ordered source/template/model references; the intrinsic `model_catalog.yaml` continues to own model
   capabilities, while the existing backend-source registry continues to own credentials and source lifecycle.
4. Extract workflow `provider_refs` and preferred-proxy metadata into the shared route catalog. Workflow selectors keep
   their current user-facing names, but every non-runtime-native `ModelSpec.model_id` normalizes through
   `model_catalog.yaml` before route lookup. Workflow-specific prompts, roles, labels, and runtime selection remain in
   `forge.review.models`.
5. Persist neutral model-route intent so a later bare resume uses the same source/template/tier rather than rerunning
   selection.
6. Reuse the existing context-budget preflight against the selected route's tier-specific effective context window
   before committing the switch.
7. Print the resolved provider, template/proxy, tier, effective model, and `billing_mode` evidence before child
   invocation whenever an explicit `--model` changes or selects a route.

## CLI contract

```bash
forge session start analyst --model gpt-5.6-sol
forge session resume analyst --model gemini-3.1-pro-preview
forge session fork planner --name reviewer --model gpt-5.6-sol --tier opus
forge session resume analyst --model gpt-5.6-sol --proxy openrouter-openai
forge session incognito --model gpt-5.6-sol
forge session start analyst --model claude-opus-5 --no-proxy
```

`--model` names the desired canonical model. Aliases normalize before routing. For route lookup, the existing Claude
`*-1m` catalog variants and Claude Code `[1m]` spellings normalize to the base Claude route key plus the current
transport modifier; candidate lists are not duplicated for `[1m]`. The modifier survives in the `direct_model` execution
projection, and a non-Claude model with `[1m]` is invalid. Route controls constrain how Forge may reach the canonical
model:

| Invocation context                                                       | Resolution rule                                                                               |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| Explicit `--proxy <id-or-template>`                                      | Use only that proxy; incompatibility is an error                                              |
| Explicit `--no-proxy`                                                    | Use only a direct Claude candidate; a non-Claude model is an error                            |
| Resume/fork with a persisted or inherited route that can serve the model | Preserve that route                                                                           |
| Resume/fork with an incompatible route and explicit `--model`            | Resolve a replacement through deterministic catalog order                                     |
| New session, no route flag, Claude model                                 | Use direct Claude regardless of running proxies                                               |
| New session, no route flag, non-Claude model                             | Resolve through deterministic catalog order                                                   |
| No explicit `--model`                                                    | Preserve existing launch, resume, inheritance, and `default_direct_model` behavior completely |

For precedence purposes, a route “can serve” the request when its config declares the canonical model at the
requested/resolved tier. Source credentials and template prerequisites are an admission check for a new automatic
candidate, or for a selected route that must be started; they do not make a compatible, already-running explicit or
persisted proxy ineligible merely because the launching shell lacks its original credentials. Once a route is selected,
proxy startup or live identity/health failure is hard; it does not reopen catalog selection. A bare resume of an
unavailable stored route fails rather than selecting a replacement.

Additional rules:

- `--tier` requires `--model`.
- For a direct Claude candidate, `--tier` must match the canonical model's intrinsic Claude tier; it does not retier a
  direct model.
- For a proxy candidate, the selected tier must actually serve the requested canonical model through its tier default or
  `model_alternatives`.
- Without explicit `--tier`, a Claude model first uses its intrinsic Claude tier when the proxy serves it, preserving
  current pin behavior. Non-Claude models, and Claude models unavailable at their intrinsic tier, then use a serving
  proxy default, then a unique serving tier; remaining ambiguity is an error.
- V1 rejects `--model` with `--runtime codex` or either explicit launch-mode override flag, `--sidecar` and
  `--host-proxy`, preserving the existing guards. Ordinary host-mode proxy routing remains supported when host mode
  comes from the default `proxy_mode`.
- `--subprocess-proxy` may still combine with a direct Claude `--model`; a non-Claude model that requires main-session
  proxy routing is incompatible with `--subprocess-proxy` and fails before either proxy or child startup.
- `session adopt --model` retains its current Claude-only contract and does not consult the route catalog.
- `session start --no-launch --model ...` resolves and persists coherent intent and retains the current `ensure_proxy()`
  behavior, but invokes no child and crosses no routing-journal commitment boundary.
- A proxy auto-started for model-first routing follows the ordinary proxy lifecycle. Session or incognito cleanup does
  not stop it.
- An active session follows existing resume behavior: ordinary resume refuses; `--force` creates a child. Authority
  inheritance is unchanged, so a producer designation never follows that forced child automatically.
- An explicit `--model` is authorization to replace an incompatible persisted route. A bare resume is not: it must
  reproduce stored model-route intent or fail with recovery instructions.

## Shared route catalog

The route catalog maps a canonical model id to ordered candidates:

```yaml
schema_version: 1
models:
  gpt-5.6-sol:
    routes:
      - kind: proxy
        source_id: openrouter
        template: openrouter-openai
        model_ref: openai/gpt-5.6-sol
      - kind: proxy
        source_id: litellm-remote
        template: litellm-openai
        model_ref: openai/gpt-5.6-sol
  claude-opus-5:
    routes:
      - kind: direct
        runtime: claude_code
        model_ref: claude-opus-5
      - kind: proxy
        source_id: openrouter
        template: openrouter-anthropic
        model_ref: anthropic/claude-opus-5
```

Route order is a reviewed product decision. Runtime registry state does not reorder candidates. The catalog must retain
the direct Claude candidate first for every model covered by the existing direct-pin contract; validation pins that
compatibility invariant rather than leaving it to convention.

The route-catalog lookup key is a canonical intrinsic model id after the Claude 1M normalization above. The selectable
workflow worker `claude-opus-4.6-1m` keeps that public name, but its internal `ModelSpec.model_id` becomes the canonical
`claude-opus-4-6-1m`; route derivation resolves the base `claude-opus-4-6` candidate list and restores `[1m]` on the
direct execution ref. Other workflow aliases similarly normalize to a canonical model id without duplicating route
metadata. Runtime-native workers such as Codex have no route-catalog entry and retain their route-null runtime-owned
resolution.

Route entries use canonical ids from `model_catalog.yaml`; source-specific refs and templates are operational metadata
and therefore stay outside the intrinsic catalog. A proxy candidate's `source_id` must resolve through the
backend-source registry, and its template must belong to that source. Credential ids, environment requirements, and
local lifecycle are read from that registry rather than copied into the route catalog. An explicit `--proxy` may use a
compatible user-edited instance even when it is not an implicit catalog candidate; the catalog owns automatic
preference, not the complete set of manually constrained routes.

An opaque custom base URL with no template and tier-map identity cannot prove model compatibility. An explicit `--model`
against that route fails with a contextual error instead of guessing; a bare relaunch of the same custom route retains
its existing behavior. A user-edited proxy with a known template is not opaque and follows the explicit-route rule above
even when its backend source cannot be proven.

A direct interactive Claude candidate names the `claude_code` runtime, not `anthropic-api`: existing interactive auth
resolution may expose an API key or let Claude Code use its own login. The route selector does not change that payer
decision, and `confirmed.launch` continues to report its result separately. Failure of that existing direct-auth launch
does not fall through to a proxy candidate.

## Resolution algorithm

Resolution is deterministic and fail-closed:

1. Resolve the explicit `--model` alias to one canonical catalog id. Unknown ids fail before proxy startup.
2. Apply the route-precedence table above. Explicit `--proxy` and `--no-proxy` are strict. A compatible persisted or
   inherited route wins before automatic selection. A new Claude request without a route flag uses its validated direct
   candidate.
3. When automatic selection is required, inspect ordered route candidates without side effects. A proxy candidate is
   admissible only when its backend-source credentials and template prerequisites are available. This admission scan is
   distinct from the compatibility check for an explicit or persisted route. A direct candidate requires the named
   runtime; runtime-owned authentication remains subject to that runtime's existing launch behavior.
4. Select the first admissible candidate. For a proxy candidate, call `ensure_proxy()` for the exact id/template, which
   may reuse or start an instance. Once selected, startup, identity, health, or compatibility failure is a hard error;
   Forge does not silently fail over to another source.
5. For a proxy route, resolve the tier: explicit `--tier` first; otherwise a serving intrinsic tier for a Claude model;
   otherwise the proxy default if it serves the model; otherwise the only serving tier; otherwise fail with the
   candidate tiers and a `--tier` recovery command. A direct route uses the canonical Claude tier already validated
   above.
6. Validate the concrete proxy's tier defaults and `model_alternatives` against the canonical requested model and the
   candidate's provider-specific model ref.
7. Resolve the selected tier's target context window and run resume/fork budget preflight.
8. Only after successful resolution and preflight, persist the complete intent transition atomically.
9. Build the immutable provenance payload from the updated state, render the resolved route line from that same object
   on stderr, and enter the existing launch transaction. The line names any provider/template change and the route's
   current `billing_mode` evidence using the provenance domain's existing enum; it does not infer payer identity from
   model family alone.

"Running-proxy reuse" means reuse within an explicit, preserved, or already selected template. Forge never scans
unrelated running proxies and lets ambient process state choose a source.

## Launch and persistence contract

Add neutral session intent alongside the existing Claude execution pin:

```yaml
intent:
  proxy:
    template: openrouter-openai
    base_url: http://localhost:8085
  launch:
    direct_model: null
    model_route:
      requested_model: gpt-5.6-sol
      selected_tier: opus
      kind: proxy
      source_id: openrouter
```

The proxy template and base URL remain in `ProxyIntent`; `model_route` records only the session-owned request and
resolved choice needed for a reproducible relaunch. It does not copy proxy-owned tier maps or hyperparameters into
session intent. The strict object contains exactly canonical `requested_model`, required `selected_tier`, `kind`
(`direct | proxy`), and nullable `source_id`. Direct intent requires `source_id=null`. An automatically selected proxy
requires its catalog source id; an explicit or preserved proxy records a canonical source only when that identity is
proven, otherwise null. The selected proxy template and base URL remain single-sourced in `ProxyIntent`, so a manually
configured proxy with unknown backend identity can still be reproduced without inventing provenance.

This is a session-manifest schema change, not an unversioned additive field. Bump `SCHEMA_VERSION` to 2, accept both v1
and v2 on read, and write only v2. The v1-to-v2 conversion supplies `model_route=null`; it performs no route selection
and preserves legacy `direct_model` behavior. Reads alone do not rewrite a manifest, while the first ordinary mutation
persists the v2 shape. Newer/unknown versions and unknown fields remain strict errors under the durable-state contract.

Transition rules:

- Explicit interactive `--model` replaces the complete prior `model_route` atomically after resolution and context
  preflight succeed.
- A selected non-Claude proxy route sets `intent.proxy`, clears a stale `launch.direct_model` pin, and records neutral
  `model_route` intent. Claude Code receives the resolved tier word, never the raw OpenAI/Gemini provider model ref.
- A selected Claude proxy route sets `intent.proxy`, retains the normalized `launch.direct_model` execution pin needed
  by existing Claude alternative validation, and records the neutral `model_route` request.
- A selected direct Claude route clears `intent.proxy`, stores the normalized `launch.direct_model` execution pin, and
  records the neutral `model_route` request.
- Explicit `--proxy` / `--no-proxy` without `--model` clears stale neutral `model_route` intent but preserves the
  existing Claude-pin transition rules.
- A bare resume with `model_route` re-materializes the stored source/template/tier. It does not choose a different
  source because credentials or running proxies changed; unavailable stored routing is an actionable error.
- Fresh and fork children inherit `model_route` unless the child supplies an explicit routing/model flag, matching
  existing launch-intent inheritance. Incognito records the same coherent state for its temporary lifetime.
- `default_direct_model` and `session adopt --model` populate only the existing Claude `direct_model` field; they never
  create `model_route` intent or invoke automatic route selection.
- Existing manifests with `direct_model` and no `model_route` remain valid and follow the pre-card launch path.

Resolution, selected-tier context preflight, and any required proxy startup complete before the atomic intent mutation.
The existing launch transaction then commits route provenance and invokes the child. A later payload-preparation,
required-journal, projection, or child failure does not roll back the successfully persisted explicit model/route
choice, matching the current persistence of explicit resume/fork overrides; a retry reuses that intent.

For direct Claude routes, existing `direct_model_env()` and interactive auth resolution remain authoritative. For proxy
routes serving Claude alternatives, existing model-pin validation remains authoritative. For a non-Claude backend, the
launcher supplies the resolved tier word to Claude Code, clears inherited direct-model defaults, and applies the
existing proxy context-model defaults from the selected tier's effective context window.

The shipped provenance producer prefers `model_route.requested_model` and `.selected_tier` for a newly resolved launch,
then falls back to `direct_model` for legacy intent. It records the resolved route through the existing route,
requested/selected-model, tier, and marking-snapshot fields; `route.backend_id` remains a proven runtime/config fact and
is not copied blindly from intent's `source_id`. This card adds no routing-event field and requires no historical
journal migration. `confirmed.route_commit` remains only the exact event/run projection. Selection consumes no
provenance read.

The current routing payload proves `billing_mode=unknown` for these interactive routes. The prelaunch line must render
that value rather than deriving payer identity from the model or source. If a separately evidenced billing resolver is
added in scope, the payload and line may expose its existing enum value together; the line never has an independent
inference path.

## Non-goals

- No second `--route-model` option or deprecated flag alias.
- No fresh model-first resolution from `default_direct_model`, `session adopt --model`, a bare command, or an old
  manifest. A bare resume may only re-materialize already stored `model_route` intent.
- No Codex model pinning or new exact-model observation; existing runtime-native unknown route evidence remains.
- No live route switch inside a running process.
- No per-request session routing or proxy-owned tier-map mutation.
- No marking, authority, watermark, or authorship decision.
- No raw provider refs on the CLI in v1; input is a catalog id or alias.
- No silent provider fallback after a route has been selected.

## V1 acceptance boundary

01. Every currently successful Claude `--model`, `--proxy`, and `--no-proxy` start/resume/fork/incognito contract,
    including `[1m]`, retains the same effective route, model, tier, and legacy execution projection; additive
    `model_route` intent and provenance are allowed only after an explicit interactive `--model` request.
02. An explicit non-Claude `--model` changes from a contextual rejection to deterministic model-first resolution; no
    unrelated running proxy, bare command, old manifest, or config default can activate fresh selection.
03. `default_direct_model` validates as a Claude direct pin. A non-Claude value fails with a field-specific
    configuration error and never starts a proxy or child.
04. `--model` is the only interactive model selector. Explicit `--proxy` is strict, `--no-proxy` is direct-only,
    compatible persisted/inherited routing wins, and a new unproxied Claude model remains direct.
05. An explicit model that an inherited route cannot serve invokes catalog selection; the stderr route line renders
    provider, template/proxy, tier, effective model, and `billing_mode` (including truthful `unknown`) from the same
    immutable payload later committed as provenance.
06. The route catalog is the only source of automatic source/template/model-ref ordering for both interactive selection
    and workflow route derivation. Workflow names normalize to canonical model ids, the 1M worker preserves its
    transport modifier, runtime-native workers remain catalog-free, and direct-first Claude invariants are
    schema-validated.
07. Selection failure after a candidate is chosen does not fall through to another source.
08. Multi-tier matches use explicit tier, then a serving intrinsic tier for Claude compatibility, then a serving proxy
    default, then a unique serving tier; unresolved ambiguity fails with a recovery command.
09. Neutral `model_route`, `direct_model`, and proxy intent follow the transition matrix. Manifest v2 owns the new
    field; v1 reads preserve legacy behavior and upgrade only on an ordinary write. A bare resume reproduces the stored
    route rather than rerunning selection. A manually configured explicit proxy with no proven backend source remains
    reproducible with `source_id=null`.
10. Route provenance reports the explicit canonical request and resolved route without changing its event schema,
    historical-read contract, or no-attestation boundary.
11. Tier-specific context-budget preflight evaluates the target route before intent is committed or a child process is
    invoked.
12. Codex, `session adopt --model`, and the explicit `--sidecar`/`--host-proxy` override flags retain their scoped
    behavior; raw provider refs and invalid combinations fail with contextual CLI errors.
13. A direct Claude model retains current `--subprocess-proxy` behavior; a non-Claude main-session route rejects that
    combination before startup. `--no-launch` may resolve/start a proxy and persist intent, but invokes no child and
    appends no routing event.
14. Fresh/fork/forced-child behavior preserves existing session and authority inheritance semantics; incognito exercises
    the same resolver and leaves no durable session after its ordinary cleanup. Any auto-started proxy follows ordinary
    lifecycle and remains independently managed.
15. Clean-wheel verification covers the new packaged route catalog and at least one direct and one proxy model route.
16. CLI help, `docs/cli_reference.md`, and `docs/end-user/session.md`, `model_selection.md`, and `proxy.md` distinguish
    Claude-native `/model` from Forge `--model`, explain route constraints and possible paid-proxy startup, and
    introduce no second model flag.
17. Implementation and closeout update `design.md` and `design_sessions.md` as the session-routing behavior ships, and
    replace `design_runtime.md` §G.4's workflow `preferred_proxy`/`provider_refs` derivation order when the shared route
    catalog becomes authoritative. Board activation does not put unshipped target behavior into normative design docs.

## Risks

- **Rejected input becomes a paid launch**: non-Claude `--model` currently fails but may select a paid proxy after this
  card. Only an explicit CLI model request can cross that boundary, and the resolved prelaunch line makes the provider,
  route, and known billing posture visible before invocation. An auto-started proxy remains under ordinary proxy
  lifecycle even after an incognito or ordinary session exits.
- **Route change on resume**: an explicit model that the persisted route cannot serve may change provider/template,
  invalidating prompt caches or degrading translated thinking blocks. The route line and existing cold-replay warning
  name the change; a bare resume never reselects.
- **Config escalation**: widening `--model` must not widen `default_direct_model`; field validation keeps bare launches
  direct-only.
- **Route catalog drift**: source model refs and template support change. Shared workflow consumption removes one
  duplicate registry but requires catalog validation and packaging tests.
- **Tier semantics**: the same backend under two tiers may receive different reasoning defaults. Ambiguity requires
  `--tier` rather than guessing.
- **Persisted route unavailable**: reproducibility intentionally wins over automatic recovery. The error names the
  stored route and the explicit `--model` command needed to choose another.
- **Manifest version transition**: the first ordinary write by the implementing Forge upgrades a v1 session manifest to
  v2. The reader accepts both versions, writes only v2, and never silently interprets an unknown shape.
