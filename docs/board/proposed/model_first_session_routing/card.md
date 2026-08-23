# Model-First Interactive Session Routing

**Status**: Proposed (2026-08-20). Adjacent to, but not a member of,
[Epic: Session Authority and Provenance](../../doing/epic_session_authority_provenance/card.md).

**Relationship**: [Session Route Provenance and Marking](../../doing/session_route_provenance/card.md) reports launch
decisions without changing them. This card adds an explicit model-first route-selection command for interactive Claude
sessions. It neither depends on authority mode nor changes authority inheritance.

**References**: [design.md §3.4](../../../design.md#34-proxy-vs-no-proxy-mode),
[design.md §3.6.12](../../../design_runtime.md#3612-subprocess-routing-resolution-normative),
[design.md §3.9](../../../design_sessions.md#39-session-resume-context-management),
[design_runtime.md §A.5](../../../design_runtime.md#a5-model-catalog-368),
[design_runtime.md §G](../../../design_runtime.md#g-subprocess-routing-reference),
`src/forge/core/models/direct_model.py`, `src/forge/backend/sources.py`, `src/forge/session/model_pin.py`,
`src/forge/review/models.py`, `src/forge/review/routing.py`, and `src/forge/core/reactive/routing.py`.

## Problem

Interactive Claude sessions already accept `--model`, but that flag is a Claude model pin:

- without `--proxy`, it selects a direct Anthropic model through Claude Code environment variables;
- with an explicit proxy, it selects a supported Claude tier default or `model_alternatives` entry;
- `resume --model` and `fork --model` persist the pin;
- non-Claude catalog models are rejected.

Changing that established flag into an ambient proxy selector would be a breaking change. The same command could switch
provider, auth, billing, cache behavior, or wire shape merely because a matching proxy happened to be running. Users do
still need an opt-in way to request a catalog model such as `gpt-5.6-sol` without first translating it into proxy and
tier vocabulary.

The workflow resolver is prior art but not a drop-in implementation. Its `provider_refs` live on a limited review-worker
registry, `derive_model_routes()` does not inspect the proxy registry, and `resolve_subprocess_routing()` scans running
proxies without auto-starting a derived template. Interactive routing needs a shared route catalog, explicit
persistence, and stricter failure semantics.

## Existing behavior protected

- `--model` remains the Claude pin flag with its current direct/proxy-alternative semantics.
- `--proxy` and `--no-proxy` remain explicit route controls and retain their current persistence behavior.
- No running proxy changes the meaning of a command that omits the new flag.
- Codex continues to reject Claude-only session routing flags and resolves its model natively.
- Existing manifests with only `LaunchIntent.direct_model` retain their current behavior without migration writes.

## Goal

1. Add `--route-model <catalog-id>` to Claude-runtime `session start`, `resume`, and `fork` as the explicit opt-in
   model-first selector.
2. Add optional `--tier <haiku|sonnet|opus>` for cases where a selected proxy can serve the model through multiple tiers
   with different hyperparameters.
3. Preserve deterministic route preference in a new packaged, non-user-editable `src/forge/core/data/model_routes.yaml`.
   It owns ordered source/template/model references; the intrinsic `model_catalog.yaml` continues to own model
   capabilities, while the existing backend-source registry continues to own credentials and source lifecycle.
4. Extract workflow `provider_refs` and preferred-proxy metadata into the shared route catalog. Workflow-specific
   prompts, roles, labels, and runtime selection remain in `forge.review.models`.
5. Persist neutral model-route intent so a later bare resume uses the same source/template/tier rather than rerunning
   ambient route selection.
6. Reuse the existing context-budget preflight against the selected route's effective context window before committing
   the switch.

## CLI contract

```bash
forge session start analyst --route-model gpt-5.6-sol
forge session resume analyst --route-model gemini-3.1-pro-preview
forge session fork planner --name reviewer --route-model gpt-5.6-sol --tier opus
forge session resume analyst --route-model gpt-5.6-sol --proxy openrouter-openai
```

Rules:

- `--route-model` is mutually exclusive with legacy `--model` and `--no-proxy`.
- It may combine with `--proxy`; that proxy is a strict route constraint, not a preference.
- `--tier` requires `--route-model`.
- For a direct Claude candidate, `--tier` must match the canonical model's intrinsic Claude tier; it does not retier a
  direct model.
- V1 rejects `--route-model` with `--runtime codex` or either explicit launch-mode override flag, `--sidecar` and
  `--host-proxy`. Ordinary host-mode proxy routing remains supported when host mode comes from the default `proxy_mode`.
  Mirroring the existing `--model` flag guards is v1 scope control, not an inherent incompatibility between a selected
  proxy route and host proxying.
- An active session follows existing resume behavior: ordinary resume refuses; `--force` creates a child. Authority
  inheritance is unchanged, so a producer designation never follows that forced child automatically.
- A user who wants a direct Claude pin continues to use `--model`. A direct candidate in the new route catalog is
  permitted, but the new flag never changes the legacy flag's meaning.

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

Route order is a reviewed product decision. Runtime registry state does not reorder candidates. Route entries use
canonical ids from `model_catalog.yaml`; source-specific refs and templates are operational metadata and therefore stay
outside the intrinsic catalog. A proxy candidate's `source_id` must resolve through the backend-source registry, and its
template must belong to that source. Credential ids, environment requirements, and local lifecycle are read from that
registry rather than copied into the route catalog.

A direct interactive Claude candidate names the `claude_code` runtime, not `anthropic-api`: existing interactive auth
resolution may expose an API key or let Claude Code use its own login. The route selector does not change that payer
decision, and `confirmed.launch` continues to report its result separately.

## Resolution algorithm

Resolution is deterministic and fail-closed:

1. Resolve aliases to one canonical catalog id. Unknown ids fail before proxy startup.
2. If `--proxy` was supplied, call `ensure_proxy()` for that exact id/template and validate that its instance config and
   live runtime, when reachable, can serve the requested model. Incompatibility is an error; no other route is tried.
3. Otherwise inspect ordered route candidates without side effects. A proxy candidate is admissible only when its
   backend-source credentials and template prerequisites are available. A direct candidate requires the named runtime;
   runtime-owned authentication remains subject to that runtime's existing launch behavior.
4. Select the first admissible candidate. For a proxy candidate, call `ensure_proxy(candidate.template)`, which may
   reuse a live instance of that template or start one. Once selected, startup, identity, health, or compatibility
   failure is a hard error; Forge does not silently fail over to another source. For a selected direct candidate, an
   explicit tier that differs from the model's intrinsic Claude tier is likewise a hard error.
5. Validate the concrete proxy's tier defaults and `model_alternatives` against the canonical requested model and the
   candidate's provider-specific model ref.
6. For a proxy route, resolve the tier: explicit `--tier` first; otherwise the proxy default if it serves the model;
   otherwise the only serving tier; otherwise fail with the candidate tiers and a `--tier` recovery command. A direct
   route uses the canonical Claude tier already validated above.
7. Resolve the target context window, run resume/fork budget preflight, and only then persist intent and launch.

"Running-proxy reuse" therefore means reuse within the already selected template. Forge never scans unrelated running
proxies and lets ambient process state choose a source.

## Launch and persistence contract

Add neutral session intent alongside the existing Claude pin:

```yaml
intent:
  proxy:
    template: openrouter-openai
    base_url: http://localhost:8085
  launch:
    model_route:
      requested_model: gpt-5.6-sol
      selected_tier: opus
      kind: proxy
      source_id: openrouter
```

The proxy template and base URL remain in `ProxyIntent`; `model_route` records only the session-owned request needed for
a reproducible relaunch. It does not copy proxy-owned tier maps or hyperparameters into session intent.

Transition rules:

- `--route-model` replaces the complete prior `model_route` atomically.
- A selected proxy route sets `intent.proxy` and clears a stale `launch.direct_model` pin before launch.
- A selected direct Claude route clears `intent.proxy`, stores the normalized legacy `direct_model` pin, and records the
  neutral `model_route` request.
- Explicit legacy `--model` clears `model_route` and otherwise retains its current behavior.
- Explicit `--proxy` / `--no-proxy` without `--route-model` clears stale neutral `model_route` intent but preserves the
  existing legacy model-pin rules.
- A bare resume with `model_route` re-materializes the stored source/template/tier. It does not choose a different
  source because credentials or running proxies changed; unavailable stored routing is an actionable error.
- Fresh and fork children inherit `model_route` unless the child supplies an explicit routing/model flag, matching
  existing launch-intent inheritance.

For direct Claude routes, existing `direct_model_env()` and interactive auth resolution remain authoritative. For proxy
routes serving Claude alternatives, existing model-pin validation remains authoritative. For a non-Claude backend, the
launcher supplies the resolved tier word to Claude Code, clears inherited direct-model defaults, and applies the
existing proxy context-model defaults from the route's effective context window; it never passes a raw OpenAI/Gemini
provider model ref as a direct Claude model.

If the provenance card is installed, the launch records the same requested model, selected tier, source id, and route in
its committed routing event. This integration adds evidence only and does not alter selection.

## Non-goals

- No change to the meaning of `--model`.
- No Codex model pinning or observation.
- No live route switch inside a running process.
- No per-request session routing or proxy-owned tier-map mutation.
- No marking, authority, watermark, or authorship decision.
- No raw provider refs on the CLI in v1; input is a catalog id or alias.
- No silent provider fallback after a route has been selected.

## V1 acceptance boundary

01. Every existing `--model`, `--proxy`, and `--no-proxy` unit/integration contract remains unchanged.
02. `--route-model` is explicit and cannot be activated by ambient proxies, config defaults, or old manifests.
03. The route catalog is the only source of source/template/model-ref ordering for both interactive selection and
    workflow route derivation.
04. Explicit `--proxy` is strict; implicit selection follows catalog order and reuses only the selected template.
05. Selection failure after a candidate is chosen does not fall through to another source.
06. Multi-tier matches use explicit tier, then a serving proxy default, then a unique serving tier; unresolved ambiguity
    fails with a recovery command.
07. Neutral `model_route` intent and stale legacy fields follow the transition matrix, and a bare resume reproduces the
    stored route rather than rerunning selection.
08. Context-budget preflight evaluates the target route before intent is committed or a child process is invoked.
09. Codex and the explicit `--sidecar`/`--host-proxy` override flags, raw provider refs, and invalid flag combinations
    fail with contextual CLI errors; default host-mode proxy routing remains supported.
10. Fresh/fork/forced-child behavior preserves existing session and authority inheritance semantics.
11. Clean-wheel verification covers the new packaged route catalog and at least one direct and one proxy model route.
12. User documentation distinguishes Claude-native `/model`, legacy Forge `--model`, and model-first `--route-model`.
13. Activation updates `design.md` session routing semantics and replaces `design_runtime.md` §G.4's workflow
    `preferred_proxy`/`provider_refs` derivation order with the shared route catalog's authoritative order.

## Risks

- **Route catalog drift**: source model refs and template support change. Shared workflow consumption removes one
  duplicate registry but requires catalog validation and packaging tests.
- **Unexpected billing**: model-first selection can start a paid proxy route. Deterministic catalog order and a printed
  prelaunch route line make the provider explicit before invocation.
- **Tier semantics**: the same backend under two tiers may receive different reasoning defaults. Ambiguity requires
  `--tier` rather than guessing.
- **Cold replay**: switching provider/template invalidates prompt caches and may degrade translated thinking blocks.
  Resume output retains the existing warning and target-window preflight.
- **Persisted route unavailable**: reproducibility intentionally wins over automatic recovery. The error names the
  stored route and the explicit command needed to choose another.
