# Checklist: Model-First Interactive Session Routing

**Card**: [card.md](card.md) -- the accepted contract. This checklist sequences execution; where they disagree, the card
wins.

**Branch**: `feat/model-first-session-routing`, created from `main` at `46bb9e4b` on 2026-08-23.

## Current focus

Implement the package-owned route catalog and its strict loader first. No lifecycle caller should change until the
catalog, model normalization, and side-effect-free resolution types are independently tested.

## Activation and review

- [x] Review the complete proposal against the board contract, shipped design docs, model catalog, backend-source
  registry, session manifest/store, route-provenance producer, and workflow resolver.
- [x] Resolve the review blockers in the card: normative docs update only with shipped behavior; session manifests use
  an explicit v2 transition; workflow model names normalize without losing the 1M worker; route compatibility is
  distinct from automatic-candidate credential admission; opaque custom routes fail closed for explicit model changes;
  `billing_mode=unknown` remains truthful evidence.
- [x] Accept the card, create this per-card branch, move the directory `proposed/` -> `todo/` -> `doing/` with `git mv`,
  and repoint inbound board links.
- [x] Validate the activation-only document diff with `git diff --check`, Markdown link checks, and
  `make pre-commit-md`; record the clean commit before implementation starts.

## Ratified decisions

- [x] **D1 -- One model selector.** Widen the existing interactive `--model`; do not add `--route-model`. Keep
  `default_direct_model` and `session adopt --model` Claude-only.
- [x] **D2 -- Explicit activation only.** Fresh model-first selection requires an explicit interactive `--model`. Bare
  commands, config defaults, legacy manifests, and unrelated running proxies cannot activate it.
- [x] **D3 -- Deterministic route order.** `model_routes.yaml` is the only automatic source/template/model-ref order.
  Runtime registry state never reorders candidates, and selection never falls through after choosing one.
- [x] **D4 -- Compatibility versus admission.** Tier/model declarations decide whether a route can serve a model.
  Credentials and prerequisites admit a new automatic candidate or a selected route that needs startup; they do not
  displace a compatible already-running explicit or persisted proxy.
- [x] **D5 -- Durable intent and schema.** `ModelRouteIntent` is a strict v2 session-manifest field. Readers accept v1
  and v2, writes emit v2, and v1 conversion supplies only `model_route=null` without selecting a route.
- [x] **D6 -- Claude 1M identity.** Canonical `*-1m` variants and `[1m]` spellings share the base route candidates while
  retaining the transport modifier in `direct_model`; the workflow `claude-opus-4.6-1m` selector remains public.
- [x] **D7 -- Runtime-native exclusion.** Non-runtime-native workflow specs normalize to a canonical catalog model and
  consume the shared route catalog. Codex remains runtime-owned and route-null.
- [x] **D8 -- Evidence boundary.** The prelaunch route line is rendered from the immutable provenance payload. Current
  interactive routing reports truthful `billing_mode=unknown`; it never infers payer identity from family or source.
- [x] **D9 -- Transaction boundary.** Resolve, start any selected proxy, run target-context preflight, and persist the
  complete intent transition before the existing route-journal/child transaction. A selected proxy remains independently
  managed even if a later preflight or launch step fails.

## Phase 1 -- Shared route catalog and normalization

- [ ] Add packaged `src/forge/core/data/model_routes.yaml` with schema version 1 and explicit ordered candidates for all
  interactive and non-runtime-native workflow models in scope.
- [ ] Add dependency-light frozen route-catalog types and one cached loader under `forge.core.models`; use
  `importlib.resources`, a dedicated domain error, and an explicit cache reset for tests.
- [ ] Strictly validate exact fields, supported schema version, canonical model keys, unique ordered candidates, route
  kinds, runtime ids, source ids, source/template ownership, source-specific model refs, and the direct-first invariant
  for every existing Claude direct pin.
- [ ] Define one normalization result carrying canonical requested model, route lookup key, Claude tier, and the
  optional 1M transport modifier. Reject unknown ids, non-Claude `[1m]`, and unsupported direct tiers contextually.
- [ ] Prove that every non-runtime-native workflow spec resolves to one catalog key, while runtime-native specs bypass
  catalog validation deliberately.
- [ ] Add package-resource tests and fail-loud coverage for missing, malformed, newer-schema, unknown-field, duplicate,
  source/template mismatch, missing-workflow-model, and direct-order violations.

## Phase 2 -- Manifest v2 and pure intent transitions

- [ ] Add strict `ModelRouteIntent(requested_model, selected_tier, kind, source_id)` validation and optional
  `LaunchIntent.model_route` storage.
- [ ] Bump the session manifest to v2; accept v1/v2 on read, convert v1 with only the new null default, write only v2,
  and keep unknown versions/fields strict and actionable.
- [ ] Cover clean v1 reads, v1 ordinary-write upgrade, complete v2 round trips, missing/extra/invalid nested fields,
  direct `source_id=null`, automatic proxy source ids, and manually constrained proxy `source_id=null`.
- [ ] Define one pure transition planner for direct Claude, proxied Claude, and proxied non-Claude requests. It must set
  or clear `ProxyIntent`, `direct_model`, and `model_route` as one complete result rather than mutating piecemeal.
- [ ] Pin no-model transitions: explicit `--proxy`/`--no-proxy` clear neutral route intent while preserving existing
  Claude-pin behavior; fresh/fork/forced children inherit route intent unless explicitly overridden.
- [ ] Keep `default_direct_model`, adoption, legacy direct pins, and Codex manifests on their existing paths without
  synthesizing `model_route`.

## Phase 3 -- Side-effect-free route planning and tier resolution

- [ ] Build an interactive route plan that applies strict explicit proxy/no-proxy precedence, then compatible
  persisted/inherited routing, then new-Claude direct routing, then catalog selection for an explicit incompatible or
  unbound non-Claude request.
- [ ] Validate explicit and persisted routes from their concrete template tier maps. Treat a template-less custom base
  URL as unverifiable for explicit `--model`, while leaving bare custom-route relaunch unchanged.
- [ ] Inspect automatic candidates without starting a proxy. Resolve source prerequisites through the backend-source and
  credential registries; do not duplicate credential ids or lifecycle metadata in the route catalog.
- [ ] Select the first admissible candidate and call `ensure_proxy()` exactly once for that candidate. Reuse/start
  failures, health or identity mismatches, and post-selection compatibility errors are hard failures with no fallback.
- [ ] Resolve tiers in the accepted order: explicit tier; serving intrinsic Claude tier; serving proxy default; unique
  serving tier; otherwise an ambiguity error naming candidates and a usable `--tier` command.
- [ ] Reject `--tier` without `--model`, direct-tier mismatch, non-serving explicit tiers, raw provider refs, non-Claude
  direct/no-proxy requests, and unsupported custom routes before intent mutation or child invocation.
- [ ] Resolve the selected tier's effective context window and run resume/fork context-budget preflight before
  committing intent. A failure leaves prior session intent byte-equivalent; any already-started proxy follows ordinary
  lifecycle.

## Phase 4 -- Interactive CLI and launch transaction

- [ ] Widen `session start|resume|fork|incognito --model` and add `--tier` with shared help text and contextual recovery
  errors; keep `session adopt --model` unchanged.
- [ ] Route all Claude host-mode lifecycle paths through the same planner without duplicating precedence or transition
  logic. Preserve Codex and explicit `--sidecar`/`--host-proxy` guards.
- [ ] Preserve all currently successful Claude direct/proxy model-pin cases, aliases, `[1m]`, explicit proxy/no-proxy,
  active-session refusal, forced-child inheritance, and incognito cleanup.
- [ ] Reject a non-Claude main-session route combined with `--subprocess-proxy` before either proxy or child startup;
  preserve direct Claude plus subprocess-proxy behavior.
- [ ] Make `--no-launch --model` resolve/start and persist coherent intent without invoking a child or appending a route
  event. Keep an auto-started proxy independently managed.
- [ ] Build the immutable routing payload from updated intent, including the canonical request and selected tier, while
  preserving route-provenance event schema, backend proof rules, marking snapshots, and legacy `direct_model` fallback.
- [ ] Render one stderr prelaunch route line from that exact payload whenever explicit `--model` selects or changes a
  route. Keep result streams and child stdout unchanged.
- [ ] Verify required route-journal commitment remains after payload construction and before child invocation; later
  payload/projection/spawn/child failure retains the successfully persisted explicit route choice per the card.

## Phase 5 -- Workflow migration

- [ ] Remove workflow-owned `provider_refs` and `preferred_proxy` ordering after shared catalog lookup is available;
  retain worker names, aliases, descriptions, prompts, prompt modes, worker ids, families, and runtimes.
- [ ] Derive workflow `ModelRoute` values from catalog candidates plus template/source metadata without inspecting or
  mutating the proxy registry.
- [ ] Preserve explicit workflow `--proxy`, preferred automatic ordering, route scanning, direct-only Claude behavior,
  availability reporting, sidecar constraints, and fail-closed no-route diagnostics.
- [ ] Preserve `claude-opus-4.6-1m` as a direct worker with `[1m]` execution ref and preserve Codex as
  `source=runtime_native`, `route=None`, with no catalog entry.
- [ ] Update all reconstructed/specialized `ModelSpec` callers and tests atomically; no compatibility adapter or second
  metadata source remains.

## Phase 6 -- Documentation, release proof, and closeout

- [ ] Once each behavior ships, update `docs/design.md`, `docs/design_sessions.md`, and `docs/design_runtime.md` §A.5/G
  to describe the implemented catalog ownership, precedence, manifest v2, workflow derivation, and evidence boundary.
- [ ] Update CLI help, `docs/cli_reference.md`, and `docs/end-user/session.md`, `model_selection.md`, and `proxy.md` to
  distinguish Forge `--model` from Claude-native `/model`, explain route constraints, and disclose possible paid-proxy
  startup and independent lifecycle.
- [ ] Run focused catalog, manifest, session-model, lifecycle, routing, output-stream, workflow, and regression suites.
- [ ] Run the required targeted Docker/integration coverage for session, proxy, and workflow changes before closeout.
- [ ] Run `make test-unit`, `make test-regression`, `make pre-commit`, board/link checks, and `uv build` on the
  integrated branch head; record any skips or non-passing results.
- [ ] Install the built wheel in a clean environment and prove `model_routes.yaml` loads plus one direct and one proxy
  route resolve from packaged resources.
- [ ] Review the complete diff for architecture consistency and update durable implementation notes only for genuinely
  reusable invariants.
- [ ] Add the compact completed-work change-log entry, mark verification evidence below, move the card to `done/`,
  repoint inbound links, and commit the closeout only after the implementation is shipped.

## Acceptance test matrix

| Test                                               | Fixture                                                                | Assertion                                                                          | Planned test file                                                                     |
| -------------------------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Route catalog strict load                          | packaged valid/invalid YAML variants                                   | exact schema and cross-catalog/source/template invariants; failures name the field | `tests/src/core/models/test_model_routes.py`                                          |
| Claude direct-first guard                          | every direct-pin-capable Claude catalog id                             | normalized route list starts direct and preserves its model ref                    | `tests/src/core/models/test_model_routes.py`                                          |
| 1M normalization                                   | `[1m]`, canonical `-1m`, workflow dotted selector                      | one base route list; direct execution ref restores `[1m]`                          | `tests/src/core/models/test_model_routes.py` / `tests/src/review/test_models.py`      |
| Manifest v1 compatibility                          | v1 direct/proxy/empty launch intents                                   | strict read succeeds with `model_route=None`; no selection occurs                  | `tests/src/session/test_store.py`                                                     |
| Manifest v2 strictness                             | valid and malformed `ModelRouteIntent` objects                         | exact round trip; invalid/extra fields fail contextually                           | `tests/src/session/test_models.py` / `tests/src/session/test_store.py`                |
| Automatic deterministic selection                  | two admissible catalog proxy routes plus unrelated running proxies     | first catalog candidate selected; registry state does not reorder it               | `tests/src/core/ops/test_session_model_routing.py`                                    |
| No post-selection fallback                         | first candidate selected, then startup/health fails                    | hard error; second candidate and child never invoked                               | `tests/src/core/ops/test_session_model_routing.py`                                    |
| Running persisted proxy without launch credentials | compatible healthy persisted proxy, credential absent in current shell | route preserved and reused; no automatic reselection                               | `tests/src/cli/test_session_resume.py`                                                |
| Bare unavailable persisted route                   | v2 intent names stopped/unavailable route                              | actionable failure; no catalog scan or replacement                                 | `tests/src/cli/test_session_resume.py`                                                |
| Explicit incompatible model on resume              | persisted Gemini route plus explicit GPT model                         | catalog replacement occurs only after compatibility rejection                      | `tests/src/cli/test_session_resume.py`                                                |
| Tier ambiguity                                     | requested model served by multiple non-default tiers                   | error names candidate tiers and exact `--tier` recovery                            | `tests/src/session/test_model_pin.py`                                                 |
| Context preflight atomicity                        | target tier below current context budget                               | prior intent unchanged; child and route journal untouched                          | `tests/src/core/ops/test_session_fork_preflight.py`                                   |
| Existing Claude matrix                             | current direct/proxy aliases and `[1m]` fixtures                       | effective route, model, tier, and `direct_model` projection unchanged              | `tests/src/cli/test_session_model_pins.py`                                            |
| Opaque custom route                                | base URL without template plus explicit model                          | contextual incompatibility error; bare relaunch unchanged                          | `tests/src/cli/test_session_resume.py`                                                |
| No-launch boundary                                 | explicit non-Claude model with `--no-launch`                           | proxy may start and v2 intent persists; no child/event                             | `tests/src/cli/test_session_start_delete.py`                                          |
| Route line/provenance identity                     | explicit request causes route selection                                | stderr line and committed payload share provider/proxy/tier/model/billing values   | `tests/src/core/ops/test_session_routing.py` / `tests/src/cli/test_output_streams.py` |
| Workflow migration parity                          | current direct, proxy, alias, 1M, and Codex specs                      | routes/order/output remain stable; metadata comes only from route catalog          | `tests/src/review/test_models.py` / `tests/src/review/test_routing.py`                |
| Clean-wheel resource                               | installed wheel, one direct and one proxy lookup                       | packaged catalog loads and resolves both routes without source checkout            | `tests/integration/cli/test_session_commands_integration.py`                          |
| Managed launch integration                         | Docker session resume/fork across direct and proxy model requests      | intent, effective route, preflight, journal, and child boundary agree              | `tests/integration/docker/test_session_routing.py`                                    |

## Verification record

- Activation documents: `git diff --check` clean; `make pre-commit-md` passed, including repository Markdown links
  (2026-08-23).
- Focused implementation tests: pending.
- Required targeted integration: pending.
- Aggregate unit/regression/pre-commit: pending.
- Build and clean-wheel smoke: pending.
