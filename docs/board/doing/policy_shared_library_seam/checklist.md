# Checklist: policy_shared_library_seam

**Branch**: `policy-shared-library-seam` | **Card**: [card.md](card.md)

## Current focus

Slice 1 is complete: the provider-aware transport helper is covered directly, tagger and plan-check delegate without
changing their telemetry contracts, and 83 focused tests pass. **Current: Slice 2.**

## Slice 0: Re-verify audit findings -- DONE 2026-07-24, corrected after review rounds 1-2

Verified against `main` at `0435e561`; review corrections are marked CORRECTED.

- [x] Block-bar duplication confirmed: `src/forge/policy/workflow/stages.py:25` local `CONFIDENCE_THRESHOLD = 0.8` +
  `_map_verdict` (`stages.py:255-302`) reimplement the gate owned by `src/forge/policy/semantic/verdict.py:19` /
  `verdict_to_decision` (`verdict.py:161`). Values match today; nothing enforces it.
- [x] Five direct-LLM transport copies confirmed: `core/reactive/tagger.py:41-117`,
  `policy/semantic/plan_check.py:394-479`, `policy/workflow/stages.py:183-238` (`_complete_with_usage`, already shared
  by checker + reviewer since the audit), `policy/team/handlers.py:163-221` (`_classify_event`),
  `session/transfer.py:611-657` (`_call_llm_for_curation_prompt` -- note: no X-Request-ID gate; OpenRouter-direct).
- [x] Emission/telemetry is **deliberately divergent per site** -- see the normative matrix below. This shrinks the seam
  from the original card's "call + emission recipe" to a **transport core** (D1); emission stays site-owned.
- [x] Supervisor lane inline confirmed but small: `supervisor.py:802-804` duplicates `resolve_supervisor_lane`'s
  two-line body (`supervisor.py:731-732`). Slice 3 is a two-line delegation.
- [x] UUID regex duplication confirmed: `supervisor.py:41` vs `policy/queries.py:16`.
- [x] CORRECTED -- team block bar is **not an established defect**. The team design card
  (`docs/board/proposed/team_orchestration/card.md:127-146,158-163`) documents `divergent -> exit 2` and the minimal
  `{verdict, confidence, feedback}` schema as current design; design_workflows.md §1.2's bar is scoped to the semantic
  supervisor. That card is `proposed/` (non-normative per board_contract), so no authority exists either way -- the
  prompt requests a `confidence` the handler never reads (`prompts.py:38`, `handlers.py:289-294`). Reclassified as
  policy decision **D7, resolved by the user 2026-07-24** (confidence-only gate + exit-0 warn channel).
- [x] Defect B (model-pin leak) stands: semantic scrubs `_CLAUDE_MODEL_PIN_ENV_VARS` when a base_url resolves
  (`supervisor.py:567,593`); team passes no `unset_env_vars` (`handlers.py:266-274`).
- [x] CORRECTED -- `lookup_proxy_base_url` importers are `policy/team/handlers.py:21`, `core/reactive/env.py:574`, and
  `core/reactive/cost_tracking.py:117` (plus direct tests incl. `check_proxy_reachable` in
  `tests/src/core/reactive/test_proxy.py`). The round-1 "sole importer" claim came from a two-file, then head-truncated
  grep. Module deletion is off the table; D6 is a docstring correction only.
- [x] CORRECTED -- routing has two layers today: `handlers.py:245` resolves only explicit team config, then
  `run_claude_session` -> `build_claude_env` resolves ambient `FORGE_SUBPROCESS_PROXY`, `FORGE_SUBPROCESS_BASE_URL`, and
  inherited `ANTHROPIC_BASE_URL` (`env.py:253-275`). The ambient routes already reach the proxy; the team handler lacks
  their resolved `base_url` for pre-dispatch validation, cost snapshots, and model-pin scrubbing. The shared resolver
  also adds strict named-proxy reachability before dispatch commitment. The D3 matrix below records the actual
  destination, validation, and observability deltas.
- [x] Card correction: design_workflows.md §2.1's shared-library table has **no** direct-LLM-call row -- the "LLM call"
  node exists only in §1.2's node-type taxonomy. The Slice-1 helper is a proposed §2.1 **addition** (design task below),
  not an existing design promise.
- [x] Verification reality: no team-hook integration coverage exists anywhere under `tests/integration/`;
  `test_supervisor_e2e.py` is a deterministic harnessed `claude -p` (explicitly not real LLM). Acceptance table
  corrected; team-wire integration added to Slice 4.
- [x] Active `card.md` synchronized after review round 2: transport-only seam, ordered slice dependencies, D7 policy
  change, and D3 early-resolution semantics now match this checklist.

## Telemetry contract (normative for this card -- byte-identical before/after)

| Caller (command)                                     | Success                                                                             | Parse failure                                   | Transport exception                                                          |
| ---------------------------------------------------- | ----------------------------------------------------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------------- |
| tagger (`tagger`)                                    | 1 usage event (untagged, emitted pre-parse) + upstream `action.tag` success/skipped | n/a (total parser; empty -> upstream `skipped`) | **0 usage events**; 1 upstream error (`tagger.py:102-117`)                   |
| plan-check (`plan-check`)                            | 1 usage success (session-tagged)                                                    | 1 usage error/`parse_error`                     | 1 usage error/`exception`                                                    |
| workflow stages (`policy-checker`/`policy-reviewer`) | 1 usage success (session-tagged)                                                    | 1 usage error/`parse_error`                     | 1 usage error/`exception` (`_emit_stage_error`, callers `stages.py:114,150`) |
| team tagger (`team-tagger`)                          | 1 usage (default success; `$FORGE_SESSION` best-effort)                             | n/a (first-word fallback `routine`)             | 1 usage error/`exception`                                                    |
| transfer curation (`transfer-curate`)                | 1 usage success + identity-gated upstream                                           | 1 usage error/`unparseable_output`              | **0 usage events** (fallback only; `transfer.py:965-967`)                    |

Failure-type vocabularies (`parse_error` vs `unparseable_output`) are per-site and preserved. "Single emitter" means
*this matrix exactly*, never "one event on every path". Characterization tests pin each row BEFORE its site is
repointed.

## Slice 1: transport-core helper; repoint tagger + plan_check

**Scope (D1)**: the helper accepts `model`, optional explicit `provider`, `messages`, and site-composed `hyperparams`.
It owns client + `SyncAdapter` construction, provider-aware target resolution (explicit provider uses
`resolve_provider_base_url(provider)`; otherwise use `resolve_client_base_url(model)`), the proxy-detection X-Request-ID
gate (`target_is_forge_proxy` -> `mint_request_id` -> `with_forge_request_id` chained last), latency timing, and
`.complete()`. It returns `(response, latency_ms, request_id)`. Parsing, status determination, usage emission, and
upstream recording all stay at call sites per the matrix.

- [x] Characterization tests pin the tagger + plan-check matrix rows (pre-repoint).
- [x] Helper module `core/reactive/llm_call.py` (working name); call sites lazy-import inside function bodies
  (impl_notes `core/reactive/__init__` eager-import trap).
- [x] `tag_action` delegates; matrix row byte-identical; `[]` fail-open unchanged.
- [x] `run_plan_check` delegates; explicit-provider client construction and request-ID target resolution remain
  provider-aware; site-composed `reasoning_effort` + `with_openrouter_user` hyperparams are preserved;
  `None`-on-any-error contract unchanged; `PlanCheckPolicy` throttle key (incl. `checker_effort`) untouched.
- [x] Design sync (per-phase, board_contract): design_workflows.md §2.1 table gains the transport-core helper row.

## Slice 2: repoint stages + transfer; fold the block bar onto verdict.py

- [ ] Characterization tests pin the stages + transfer matrix rows (pre-repoint).
- [ ] `_complete_with_usage` (`stages.py`) delegates transport; emission/parse split and the "verdict mapping outside
  the emit try" no-double-emit contract stay in stages.
- [ ] `_call_llm_for_curation_prompt` (`transfer.py`) delegates transport; provider-user role + max_tokens/temperature
  composed at site; the no-request-id behavior stays inert (gate is a no-op off-proxy -- assert it); exception ->
  no-emit fallback unchanged.
- [ ] Block-bar fold (D2): add `meets_block_bar(confidence, has_citations)` to `verdict.py`, reading
  `CONFIDENCE_THRESHOLD` at **call time** (no import-time value binding by consumers); `verdict_to_decision` and stages'
  `_map_verdict` both call it; stages' local constant deleted; message/violation shaping stays local.
- [ ] Move-together test: monkeypatch `verdict.CONFIDENCE_THRESHOLD`; assert the semantic decision AND the workflow
  reviewer flip together.

## Slice 3: lane delegation + one UUID constant

- [ ] `run_supervisor_check` calls `resolve_supervisor_lane(lane_record)` inside its existing fail-open try
  (`supervisor.py:802-804` collapses); `LaneError` posture byte-identical.
- [ ] D5: promote `queries.py:_UUID_RE` to public `RESUME_ID_UUID_RE`; `supervisor.py` imports it from
  `forge.policy.queries`, matching the existing supervisor -> queries dependency (never the reverse). Characterize
  canonical lowercase/uppercase UUIDs as accepted and compact, braced, and non-hex forms as rejected in both consumers;
  repo grep returns one production definition.

## Slice 4: team handler -- confidence gate (D7), model-pin fix, routing, fifth caller, wire coverage

- [ ] Characterization tests pin the team-tagger matrix row + current `_run_supervisor` contract (pre-change).
- [ ] **D7a gate (decided)**: parse the verdict; block `(2, feedback)` only when
  `confidence >= verdict.CONFIDENCE_THRESHOLD` (call-time read of the shared constant -- the two-arg citation predicate
  is NOT used here; the team bar is confidence-only by decision). Divergent below bar -> `(0, feedback)`.
  Malformed/missing confidence degrades to `0.0` (warn, never block -- mirrors `stages.py:262-268`).
- [ ] **D7b warn channel (decided)**: `_team_supervisor_hook` (`cli/hooks/commands.py:1865`) also prints feedback on
  exit 0 (log/verbose visibility; teammate delivery is only guaranteed on exit 2 per the hook contract). Update both
  hook command docstrings.
- [ ] **Defect B fix**: scrub model pins whenever a `base_url` resolved from ANY source (same rule as
  `supervisor.py:567`); direct/unresolved dispatch keeps env. D4: promote `_CLAUDE_MODEL_PIN_ENV_VARS` to
  `core/reactive/session_runner.py`. Deliberate divergence from the semantic arm: **no** `model="opus"` pin for the team
  supervisor (the team design targets cheap proxies; forcing opus would change cost posture) -- documented in the design
  sync.
- [ ] **Routing migration (D3 matrix below)**: `_run_supervisor` resolves via
  `resolve_subprocess_routing(explicit_base_url=config.base_url, explicit_proxy=config.proxy, require_route=False)`
  mirroring `supervisor.py:554`. A resolver exception fails open before dispatch; an unresolved result dispatches
  direct. Ambient destinations are unchanged, but their route becomes visible before dispatch for cost tracking,
  model-pin scrubbing, usage attribution, and lane-freeze commitment.
- [ ] **Fifth caller**: `_classify_event` delegates transport to the Slice-1 helper; matrix row byte-identical.
- [ ] D6: after removing the team-handler import, correct `core/reactive/proxy.py:4` to name the remaining
  `lookup_proxy_base_url` consumers (`core/reactive/env.py`, `core/reactive/cost_tracking.py`); no module deletion
  (`check_proxy_reachable` co-resides).
- [ ] Consumer-lane freeze keeps its commitment rule: `on_dispatch` fires only past depth + routing guards
  (`handlers.py:261-264`). Missing/corrupt named proxies already fail before that boundary. D3 intentionally moves
  present-but-unreachable named proxies and invalid ambient routes in front of it, so those paths no longer freeze a
  lane or emit a dispatch usage event; characterize the old paths and assert the new ones.
- [ ] D7 unit coverage in `tests/src/policy/team/test_handlers.py` and a CLI-hook feedback test: low-confidence and
  malformed-confidence divergent -> exit 0 + stderr feedback; high-confidence divergent -> exit 2.
- [ ] Defect-B regression carries `pytestmark = pytest.mark.regression`:
  `tests/regression/test_bug_team_supervisor_model_pin_leak.py`. Assert scrub for explicit base URL, explicit named
  proxy, ambient `FORGE_SUBPROCESS_PROXY`, inherited `ANTHROPIC_BASE_URL`, and sidecar-injected base URL; direct and
  truly unresolved dispatches keep the pins.
- [ ] **Team wire integration (new -- none exists today)**: Docker harnessed-claude coverage for
  `forge hook teammate-idle` / `task-completed` asserting exit codes + stderr on both the exit-0 warn and exit-2 block
  paths. The fixture installs (1) an OpenAI-compatible `/v1/chat/completions` stub wired through
  `LITELLM_LOCAL_BASE_URL` that deterministically returns `needs-review`, (2) a `claude` harness that returns selectable
  low/high-confidence verdicts, and (3) an enabled team-supervisor manifest with isolated session/cache ids. File:
  `tests/integration/docker/test_team_hooks.py`.
- [ ] Design sync (per-phase): design_workflows.md §1.2 team-extension note documents the confidence-only team bar +
  exit-0 warn channel as the team contract; design.md §3.6.12 fail-behavior table gains a team-supervisor row
  (fail-open; unresolved -> direct), the D3 early-resolution/strict-validation deltas, and the no-opus-pin divergence.
  Update the linked `docs/board/proposed/team_orchestration/card.md` "current implementation" reference when the code
  ships so it does not contradict the normative design.

## D3 routing matrix (decided contract)

| Team config / environment state                                           | Today (handler + runner env)                                                                                                            | After (shared resolver before runner)                          | Contract delta                                                                        |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `direct=True`                                                             | direct; ambient routing scrubbed                                                                                                        | unchanged; chain skipped                                       | none                                                                                  |
| explicit `base_url`                                                       | proxied; handler sees URL                                                                                                               | unchanged (step 1 explicit)                                    | none                                                                                  |
| explicit named proxy, registry entry reachable                            | proxied; no preflight health check                                                                                                      | proxied after strict reachability check                        | same target; new preflight                                                            |
| explicit named proxy missing/corrupt                                      | handler lookup raises; warn + `(0, "")`, no dispatch                                                                                    | resolver raises; same outcome                                  | none                                                                                  |
| explicit named proxy present but unreachable                              | dispatch attempted; lane freezes; failed usage emitted                                                                                  | resolver raises; warn + `(0, "")`, no dispatch                 | **intentional** pre-dispatch fail-open; no freeze/usage                               |
| no team proxy config; reachable `FORGE_SUBPROCESS_PROXY`                  | proxied late by `build_claude_env`; handler tracks as direct/unknown                                                                    | proxied early (step 3 strict)                                  | same target; correct cost/pin/route visibility                                        |
| no team proxy config; `FORGE_SUBPROCESS_PROXY` missing/unregistered       | silent env-layer fallback to direct (`_resolve_subprocess_proxy` swallows, `env.py:580-582`); dispatch succeeds; freeze + success usage | resolver raises (strict step 3); warn + `(0, "")`, no dispatch | **intentional** -- silent direct becomes fail-open skip (matches semantic supervisor) |
| no team proxy config; `FORGE_SUBPROCESS_PROXY` registered but unreachable | dead URL set late by `build_claude_env`; runner errors after commitment; lane freezes; failed usage emitted                             | resolver raises before commitment                              | **intentional** pre-dispatch fail-open; no freeze/usage                               |
| no team proxy config; inherited `ANTHROPIC_BASE_URL`                      | proxied late by inherited env; handler tracks as direct/unknown                                                                         | proxied early (step 6 session proxy)                           | same target; correct cost/pin/route visibility                                        |
| sidecar with injected `FORGE_SUBPROCESS_BASE_URL`                         | proxied late by `build_claude_env`                                                                                                      | proxied early from injected metadata                           | same target; correct cost/pin/route visibility                                        |
| nothing anywhere                                                          | direct                                                                                                                                  | direct (`source="unresolved"`, `base_url=None`)                | none                                                                                  |

`preferred_proxy`/`route_scan` no-op because team passes no `ModelRoute`s. `FORGE_SUBPROCESS_PROXY` wins over inherited
`ANTHROPIC_BASE_URL` in both layers. Unit tests pin every row, including `on_dispatch`, usage-emission, resolved
`base_url`, and `unset_env_vars` effects. Design.md §3.6.12 is the migration authority.

## Decisions (all resolved)

- **D1 -- transport core only** (resolves review round 1's emission-ownership conflict): emission is deliberately
  per-site (matrix above); the helper never emits. Honest scope note: the seam shrank from the original card's "call +
  emission recipe" to transport; the falsifiable prediction adjusts -- a *transport* change (request-id gate, timing,
  client construction) touches 1 helper; emission contracts intentionally stay per-site.
- **D2 -- call-time predicate in `verdict.py`** (`meets_block_bar`), single rule for semantic + workflow; consumers
  never bind the threshold at import time (makes the move-together monkeypatch test valid).
- **D3 -- early shared routing resolution**: the matrix above distinguishes unchanged subprocess destinations from the
  intentional strict-validation, attribution, model-pin, usage, and freeze-timing deltas. Authority is design.md
  §3.6.12.
- **D4 -- `_CLAUDE_MODEL_PIN_ENV_VARS`** promoted to `core/reactive/session_runner.py` (home of `unset_env_vars`).
- **D5 -- UUID regex owner**: `policy/queries.py` promotes `_UUID_RE` to public `RESUME_ID_UUID_RE`;
  `semantic/supervisor.py` imports it in the already-existing supervisor -> queries direction.
- **D6 -- docstring correction only**; deletion retracted (two production importers remain after team migration, and
  `check_proxy_reachable` co-resides).
- **D7 -- user decision 2026-07-24**: confidence-only team gate + stderr-on-exit-0 warn channel. This is a **decided
  policy change** to the team contract (recorded in the Slice-4 design sync), not a conformance fix; citation gating
  remains specific to the semantic supervisor.

## Acceptance tests

| Test                              | Fixture                                                                | Assertion                                                                | Test File                                                                                        |
| --------------------------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| Telemetry matrix characterization | mocked `SyncAdapter.complete` + captured emit/upstream                 | all 5 matrix rows byte-identical pre/post repoint                        | `test_tagger.py`, `test_plan_check.py`, `test_stages.py`, `test_transfer.py`, `test_handlers.py` |
| plan-check contract intact        | existing plan-check fixtures                                           | effort + provider-user composition; `None` on error; throttle key        | `tests/src/policy/semantic/test_plan_check.py`                                                   |
| Bar moves together                | monkeypatched `verdict.CONFIDENCE_THRESHOLD`                           | `verdict_to_decision` AND workflow reviewer flip together                | `tests/src/policy/semantic/test_verdict.py`, `tests/src/policy/workflow/test_stages.py`          |
| Team gate: warn path              | divergent, confidence 0.3; divergent, malformed confidence             | `(0, feedback)`; feedback printed on stderr at exit 0                    | `tests/src/policy/team/test_handlers.py`, `tests/src/cli/hooks/test_team_hook_feedback.py`       |
| Team gate: block path             | divergent, confidence 0.9                                              | `(2, feedback)`                                                          | `tests/src/policy/team/test_handlers.py`                                                         |
| Model-pin scrub                   | pins + every resolved-source row; direct/unresolved controls           | every resolved proxy source scrubs; direct/unresolved keep pins          | `tests/regression/test_bug_team_supervisor_model_pin_leak.py`                                    |
| Routing matrix rows               | named proxy, ambient env, sidecar injection, no-route controls         | target + pre-dispatch/freeze/usage effects match D3 matrix               | `tests/src/policy/team/test_handlers.py`                                                         |
| `_classify_event` migrated        | mocked complete                                                        | team-tagger matrix row byte-identical                                    | `tests/src/policy/team/test_handlers.py`                                                         |
| Lane delegation                   | drifted `LaneRecord`                                                   | fail-open decision identical pre/post Slice 3                            | `tests/src/policy/semantic/test_supervisor.py`                                                   |
| UUID matcher consolidation        | canonical lower/uppercase plus compact, braced, and non-hex forms      | both consumers preserve the anchored matcher behavior; one definition    | `tests/src/policy/test_queries.py` (new), `tests/src/policy/semantic/test_supervisor.py`         |
| Team wire (integration, NEW)      | deterministic tagger HTTP stub + harnessed `claude` + enabled manifest | both hooks reach supervisor; exit 0 + stderr warn; exit 2 + stderr block | `tests/integration/docker/test_team_hooks.py`                                                    |
| Policy hook path (integration)    | Docker harnessed deterministic `claude -p` (NOT real LLM)              | supervisor + policy-check flows pass post-seam                           | `tests/integration/docker/test_policy_hooks.py`, `test_supervisor_e2e.py`                        |

## Blockers / notes

- None blocking. Slices are ordered: Slice 2 and Slice 4 consume the Slice-1 helper. Each slice is shippable once its
  predecessors have landed.
- Intentional changes are D7 plus D3's strict pre-dispatch handling and early route visibility (which corrects
  attribution/model-pin/freeze behavior). Everything else is behavior-preserving and matrix-pinned.

## Closeout

- [ ] Focused suites; `make test-unit`; `make test-regression`; targeted integration:
  `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py tests/integration/docker/test_supervisor_e2e.py tests/integration/docker/test_team_hooks.py`
- [ ] `make pre-commit` clean
- [ ] Verify the per-slice design-sync tasks landed (design_workflows.md §1.2 + §2.1; design.md §3.6.12; linked
  `team_orchestration` current-implementation reference); no end-user doc changes expected (team feature has no end-user
  guide yet)
- [ ] Compact `docs/board/change_log.md` entry (Goal / Key changes / Verification; name D7 + D3 strict-preflight and
  early-visibility deltas as the behavior changes)
- [ ] Durable lessons proposed via `.forge/memory/shadow_impl_notes.md` for human promotion
- [ ] Card `doing/` -> `done/`; no inbound links to repoint (verified 2026-07-24)
