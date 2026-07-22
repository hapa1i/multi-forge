# Checklist: Runtime-Neutral Workflow Workers

**Card**: [card.md](card.md) -- the normative contract. This checklist sequences it; where they disagree, the card wins.

**Branch**: `runtime-neutral-workflow-workers` (from `main` at `c4950865`)

## Current Focus

Implementation and pre-merge verification are complete. The runtime-neutral worker contract, grouped dispatcher, Codex
worker, four portable workflow frontends, durable docs, QA coverage, and wheel-installed package lifecycle have all
passed their acceptance gates. The card remains in `doing/` only for review and merge; Phase 5.5 is intentionally
post-merge.

## Baseline (verified at acceptance; extended in round 1)

Where the Claude coupling actually lives today -- the seams this card changes:

- `src/forge/review/engine.py:64` -- `preflight_check` hard-requires `claude` on PATH for any worker fan-out.
- `src/forge/review/engine.py:283-292` -- `_prepare_worker` builds `claude -p` argv (`--bare`, `--resume`, `--model`,
  `--effort`) for every worker, via `build_claude_env`.
- `src/forge/review/engine.py:214` -- `run_multi_review` dispatches every spawnable request through one
  `ClaudeHeadlessInvoker().run_parallel` call.
- `src/forge/review/engine.py:316-367` -- `_to_review_result` never consults `HeadlessResult.runtime_is_error`: an
  exit-0 runtime-reported failure maps to `success=True` while `_status()` records the usage event as `error`. With
  `_JSON_IS_ERROR_RELIABLE = True` (`core/reactive/headless_json.py:45`) this inconsistency is live for Claude
  `is_error` envelopes today and would silently pass a failed codex turn into synthesis (impl_notes T6b rule).
- The lifecycle seam is already runtime-neutral: `core/invoker/_lifecycle.py` (shared process groups, cancellation,
  ordering) plus `CodexHeadlessInvoker` and `prepare_codex_request` (`core/invoker/codex.py:153`) exist and are proven
  by the supervisor/shadow-curation/memory-writer codex arms (T4/T6b/T6c). Each `run_parallel` call owns its own 5-wide
  pool and cancellation registry (`_lifecycle.py:275-470`) -- naive nesting of two calls would double the global child
  cap and break prompt cancellation (KeyboardInterrupt lands on the main thread, not in outer-executor workers).
- Codex telemetry contracts already exist and must not be contradicted: `emit_codex_usage` (`core/usage/emit.py:342`)
  writes BOTH the worker `UsageEvent` (route `codex_exec`, tokens exact, cost `None`) AND one downstream direct-provider
  attempt (`source_kind="provider"`, `provider="openai"`, `backend_id=None` per `_backend_id_for_direct_usage`, cost
  `None`) -- design.md §3.14 "native Codex token evidence". Auth/billing are preflight-owned: the `chatgpt` backend
  instance is `runtime_native` with `credential_ids=()` (`backend/sources.py:449`), so no static credential describes a
  codex worker.
- `ModelRoute.provider/credential/model_ref` are non-nullable `str` (`core/reactive/routing.py:44`), and
  `prepare_codex_request` records `provider="openai"` / `runtime="codex"` -- a route claiming `provider="codex"` or
  `credential="codex-api"` would contradict both the type contract's semantics and worker telemetry.
- `adversarial.py` and `consensus.py` delegate to `run_multi_review`, so engine changes cover all four verbs
  (panel/analyze/debate/consensus) without per-verb dispatch code. Both reconstruct prompt-specialized `ModelSpec`
  instances (`adversarial.py:83`, `consensus.py:174,210`) and therefore must propagate the new `runtime` field;
  otherwise a selected codex worker silently reverts to the field default (`claude_code`). When no plan is injected,
  consensus also resolves independently for both rounds (`consensus.py:188,222`), which would read Codex readiness twice
  instead of preserving one invocation snapshot.
- The four frontends are legacy `SKILL.md` sources (`src/skills/{panel,analyze,debate,consensus}/`), structurally
  Claude-only in the compiler; Codex package eligibility requires authoring neutral sources (Phase 4).

## Phase 0: Acceptance and design ratification

- [x] Execution branch `runtime-neutral-workflow-workers` created from `main` at `c4950865`
- [x] Card moved `proposed/` -> `doing/` via `git mv`; `**Lane**` header updated; the one inbound link
  (`done/cross_runtime_skills/card.md:111`) repointed
- [x] Checklist written; revised through review round 2 (all findings verified in code and incorporated)
- [x] Normative card wording aligned in Phase 0 with D2b's runtime-owned auth/backend boundary and D9's deliberate
  Claude result-mapping exception
- [x] Checklist reviewed by user; D1-D9 ratified or amended

Ratification note (2026-07-22): runtime is a per-worker execution axis; native Codex routing carries no fabricated
`ModelRoute` or backend identity; mixed dispatch retains one five-wide cancellation domain; cached readiness is frozen
once per invocation; Claude request construction/dispatch remains unchanged while D9 deliberately corrects shared
runtime-error result mapping.

Decisions needing ratification (recommendation stated first; rejected alternatives noted):

- [x] **D1 -- Worker runtime declaration.** Add `runtime: str = "claude_code"` to `ModelSpec`, validated as: known in
  `core/runtime/registry.RUNTIMES` AND `RUNTIMES[runtime].headless is True`. Codex-native workers are NEW opt-in entries
  in `AVAILABLE_MODELS`; existing spec names keep their exact current resolution (no codex refs added to existing
  specs). Rejected: consumer-lane binding -- lanes bind one consumer to one lane, but a quorum needs per-worker
  runtimes.

- [x] **D2 -- Runtime-native routing representation.** Runtime-native workers do NOT derive a `ModelRoute` (its
  `provider`/`credential`/`model_ref` are non-nullable and semantically wrong for a runtime-owned path -- no field
  widening). A resolver branch beside `_resolve_direct_spec` yields
  `RoutingResult(base_url=None, proxy_id=None, template=None, source="runtime_native", route=None, credential=None)`,
  with `"runtime_native"` added as an additive `RoutingSource` literal in `core/reactive/routing.py`. `preflight_check`
  and `_prepare_worker` branch on `source == "runtime_native"` BEFORE their route-is-None failure paths. Axes stay
  separate: `runtime="codex"` (spec/attribution), upstream `provider="openai"` (single-sourced with
  `prepare_codex_request`), auth/billing preflight-owned (env -> credential_file -> codex_store; `codex-api` is one
  possible resolution, never a static route field). `resolve_model_flag` is never consulted for runtime-native workers.
  This adds one sanctioned route-null success to the WORKFLOW-plan contract: within a `WorkerRoutingPlan`,
  `source="runtime_native"` plus `route=None` is valid intentional execution, `source="unresolved"` plus `route=None`
  remains failure, and every other plan entry requires a non-null route (today's `_raise_no_route_error` behavior).
  Scope honesty: this matrix is a plan-level invariant, NOT a global `RoutingResult` contract -- the shared resolver
  already returns successful route-null results for opaque routing (`source="explicit"` base-URL passthrough,
  `core/reactive/routing.py:315-323`; `require_route=False` opaque session-proxy acceptance, design_appendix §G.1). The
  core type docstring documents only the additive `runtime_native => route=None by design`; the plan-level matrix is
  pinned in `resolve_invocation_routing` tests.

- [x] **D2b -- Card wording vs backend identity.** The normative card now says selection uses the runtime registry and
  runtime-native auth/billing posture is preflight-resolved without asserting a static backend identity. Applied during
  Phase 0 after review round 2, rather than deferred until docs closeout. Rationale: codex worker auth is dynamic
  (ChatGPT store vs `CODEX_API_KEY` vs enterprise token), and the shipped downstream emitter deliberately records
  `backend_id=None` for codex runs (`_backend_id_for_direct_usage`, emit.py:54 -- v1 maps only unambiguous cases).
  Alternative (not recommended): attribution-only static `backend="chatgpt"` consult with a `reachable_via` check --
  rejected because an API-key codex run would then carry a subscription backend label the telemetry plane deliberately
  declines to assert.

- [x] **D3 -- Engine dispatch and concurrency.** Extract the `run_parallel` pool machinery in `_lifecycle.py` into a
  grouped dispatcher that accepts (invoker, request) pairs sharing ONE 5-wide pool, ONE children registry, and ONE
  cancellation domain; per-request template hooks are called on the paired invoker. `run_parallel(self, requests)`
  becomes a thin single-group delegation (single-runtime call sites and behavior unchanged); the engine's mixed path
  passes per-request invokers. Global concurrency cap stays `min(total, 5)` across runtimes. Interrupt semantics
  unchanged and now stated: only jobs that never started (or lost the spawn race) are `cancelled=True` and suppress
  emission; an already-running job killed by cleanup is classified as an error for emission while the interrupt still
  propagates (today's behavior). Rejected: nesting two `run_parallel` calls in an outer executor (10-child cap, and
  KeyboardInterrupt cannot reach the inner cleanup promptly); per-request `invoker.run()` in a shared pool (no shared
  children registry).

- [x] **D4 -- Codex readiness posture and ownership.** Fail closed on cold/stale/unready readiness with a
  `forge runtime preflight codex` tip (T6b user-invoked precedent; no ~20s inline `codex doctor`, no silent fallback to
  Claude workers). Single read per invocation: `resolve_invocation_routing` reads `read_fresh_codex_preflight` once iff
  any spec is runtime-native and carries the frozen `CodexPreflight` on a new optional
  `WorkerRoutingPlan.codex_preflight` field; `preflight_check` validates from the plan; `_prepare_worker` passes it to
  `prepare_codex_request`. The engine's internal-resolve path (routing_plan=None) gets the same single read; a codex
  worker reaching `_prepare_worker` without a preflight becomes a failed ReviewResult (defensive, no spawn). A two-round
  consensus invocation reuses its round-1 `WorkerRoutingPlan` for round 2 even when the caller did not inject a plan, so
  both rounds share the same preflight snapshot and route decisions.

- [x] **D5 -- Resume-context.** `--context resume:<uuid>` combined with any codex worker fails closed at preflight,
  naming `--context blind` as the fix (codex cannot resume a Claude conversation; silently downgrading one worker to
  blind would misrepresent the review basis). `preflight_check` gains a `resume_id` input; `run_multi_review` also
  checks defensively (library entry point).

- [x] **D6 -- Codex worker sandbox.** Fixed `--sandbox read-only` for workflow workers (reviewers read; T6b precedent).
  No workspace-write workers in this card.

- [x] **D7 -- Flag semantics.** `--effort` applies to Claude workers only (documented in help text; matches
  design_workflows.md §3.4 "affects only the Claude dispatch" for dual-arm consumers) -- codex argv never receives it.
  `--proxy`/`via` with a codex worker emits the same "uses direct routing; --proxy ignored" warning shape that
  direct-Anthropic workers get today.

- [x] **D8 -- Shipped codex spec, naming, and model reporting.** One opt-in worker spec (recommendation: name `codex`),
  with exact identity fields `model_id="codex-default"`, `family="openai"`, `provider_refs=()`, and `runtime="codex"`.
  The empty provider refs are intentional because D2 bypasses model-route derivation; Codex selects its own model and no
  `-m` pin is sent (consumer-lane precedent: the model is placement metadata). Reporting stays honest:
  `resolved_models.resolved_model = null` (the field means "the model that actually ran"; an unpinned selection state is
  not a resolved model), plus an additive `model_selection: "runtime_default"` field on runtime-native entries; human
  output renders `resolved=(runtime default)`. Entry `provider` mirrors the worker request (`openai`); `runtime` field
  per Phase 1.4. `DEFAULT_MODELS` unchanged.

- [x] **D9 -- Runtime-error folding (deliberate Claude-visible change).** `_to_review_result` folds
  `outcome.runtime_is_error` into failure, aligning ReviewResult with `_status()`'s existing usage-event mapping and the
  impl_notes T6b rule. The failure shape is exact: preserve `outcome.stdout` and `outcome.stderr`, set `success=False`,
  and prefer `outcome.stderr.strip()` then `outcome.stdout.strip()`. With neither, a non-zero exit retains
  `"Exit code N"`; exit zero uses `"Runtime reported error"`. Codex normally takes the effective-stderr arm; Claude's
  parsed envelope text normally takes the stdout arm. Scope honesty: because `_JSON_IS_ERROR_RELIABLE = True`, this
  changes today's Claude behavior for exit-0 `is_error` envelopes (they currently reach synthesis as `success=True`
  while the ledger says `error`). A non-zero reliable envelope was already a failure; D9 only refines its error text,
  while preserving its streams and numeric exit fallback. Characterize the current Claude behavior first, then flip with
  a regression test for both runtimes. This is the one intended exception to the "all-Claude unchanged" scope, which
  otherwise covers request construction + dispatch only (Phase 1.4 output fields are the other deliberate, additive
  change).

- [x] 0.1 De-risk probe (after ratification, before Phase 2): shape one review-style prompt through
  `prepare_codex_request` (read-only sandbox) and run it via `CodexHeadlessInvoker.run_parallel` on the host ChatGPT
  login; confirm the reduced final text lands on `HeadlessResult.stdout`, exact tokens on the event, and the read-only
  sandbox permits repo reads.

  - Assertion: probe command + observed result recorded under this item. Trap (impl_notes "Codex E2E trap"): restore the
    host `CODEX_HOME` captured at import, clear `CODEX_API_KEY`/`CODEX_ACCESS_TOKEN`.
  - Observed 2026-07-22: `uv run forge runtime preflight codex --json`, followed by a direct `prepare_codex_request` ->
    `CodexHeadlessInvoker.run_parallel` probe, shaped `codex exec --json --sandbox read-only`. The prompt read
    `pyproject.toml` and returned exact final stdout `multi-forge`; `success=True`, `runtime_is_error=False`,
    input/output/cached tokens were `38118`/`140`/`29184`, and the run id was `run_7420367c329a`. The worker event
    recorded `runtime=codex`, `route=codex_exec`, `provider=openai`, `billing_mode=subscription_quota`, exact tokens,
    and null model/proxy/cost. Exactly one downstream direct-provider attempt recorded `provider=openai`, null
    backend/proxy/request ids, the same tokens, and null cost. The host Codex home was restored and API/access-token
    overrides were cleared for the child.

## Phase 1: Worker runtime contract (types + routing)

- [x] 1.1 `ModelSpec.runtime` field (default `"claude_code"`), validated per D1 (registry membership AND
  `headless=True`).
  - Assertion: unknown runtime raises `ValueError`; a registered non-headless runtime is rejected (synthetic registry
    entry in the test); every existing `AVAILABLE_MODELS` entry carries `claude_code`; `DEFAULT_MODELS` names and
    resolution are unchanged (golden). `tests/src/review/test_models.py`.
- [x] 1.2 New codex worker spec (name per D8) in `AVAILABLE_MODELS`, excluded from `DEFAULT_MODELS`.
  - Assertion: `resolve_model_specs("codex")` returns the exact D8 identity (`model_id="codex-default"`,
    `family="openai"`, `provider_refs=()`, `runtime="codex"`); `resolve_model_specs(None)` excludes it; the
    unknown-model error's available list includes it.
- [x] 1.3 Routing per D2: runtime-native resolver branch in `resolve_invocation_routing` (no `ModelRoute`, no proxy
  registry read, no template scan); additive `RoutingSource` literal `"runtime_native"`; core docstring documents the
  additive `runtime_native => route=None` semantics, while the plan-level route-nullability matrix is pinned in
  `resolve_invocation_routing` tests (per D2 scope: opaque `explicit`/session-proxy successes keep `route=None` in the
  shared resolver).
  - Assertion: codex spec yields
    `RoutingResult(base_url=None, proxy_id=None, source="runtime_native", route=None, credential=None)`; a mixed plan
    keeps positional alignment with specs; `derive_model_routes` is not consulted for runtime-native specs;
    `runtime_native + route=None` is accepted while `unresolved + route=None` still fails.
    `tests/src/review/test_routing.py`, `tests/src/review/test_engine.py`.
- [x] 1.4 `_resolved_models_summary` + `_format_resolved_models` (`cli/workflow.py:139,172`) carry an explicit `runtime`
  per worker (additive JSON field; human line gains `runtime=`). Runtime-native entries per D8: `resolved_model=null`,
  `model_selection="runtime_default"`, `provider="openai"`, `proxy`/`template` null; human renders
  `resolved=(runtime default)`.
  - Assertion: JSON and text goldens updated deliberately in `tests/src/cli/test_workflow.py`; summary
    `provider`/`runtime` byte-equal the emitted worker event's `provider`/`runtime` (attribution consistency).
- [x] 1.5 `forge workflow list-models` availability for the codex worker keys on cached preflight readiness (per D4),
  not on `ANTHROPIC_API_KEY` or proxy scan (`check_model_availability`, `review/models.py:288`).
  - Assertion: ready iff a fresh ready preflight exists; unavailable reason names 'forge runtime preflight codex'.
- [x] 1.6 Prompt-specialized worker specs preserve runtime. `run_adversarial` and both `run_consensus` rounds copy
  `ModelSpec.runtime` when reconstructing stance/role-specific specs; no transform may silently take the field default.
  - Assertion: a codex stance remains `runtime="codex"`; a codex role remains `runtime="codex"` in both consensus rounds
    and resolves/dispatches through the runtime-native path. `tests/src/review/test_adversarial.py`,
    `tests/src/review/test_consensus.py`.
  - Note: panel `--roles` needs no change -- `_apply_panel_roles` uses `dataclasses.replace` (`cli/workflow.py:636`),
    which preserves `runtime` by construction. The hazard is confined to field-by-field `ModelSpec(...)` reconstruction;
    do not "harmonize" the replace-based site into reconstruction.

## Phase 2: Engine dispatch and preflight

- [x] 2.1 Characterization FIRST: golden test pinning the exact `HeadlessRequest` list (argv, env keys, prompt,
  attribution) an all-Claude default-quorum `run_multi_review` produces today, via a stubbed invoker. Separately
  characterize today's `_to_review_result` mapping for an exit-0 `is_error` envelope (pre-D9 behavior).
  - Assertion: request-construction golden passes before and after every Phase 2 change; the D9 flip updates the
    result-mapping characterization deliberately in the same commit as its regression test.
- [x] 2.2 `_prepare_worker` branches on the resolved runtime: the Claude branch is untouched; the codex branch shapes
  via `prepare_codex_request` (prompt/label/timeout/cwd passthrough; `Attribution` preserved so
  `operation="workflow.worker"` and the invoker's per-worker upstream row come free; sandbox per D6; preflight from the
  routing plan per D4, failed ReviewResult without one).
  - Assertion: codex request argv starts `codex exec --json --sandbox read-only`; env is sanitized (no
    `ANTHROPIC_*`/proxy vars); `base_url=None`; `attribution.runtime == "codex"`, `billing_mode` = preflight-resolved.
    `tests/src/review/test_engine.py`.
  - Note: `prepare_codex_request` expects `cwd` to be a git worktree; a non-git cwd surfaces codex's own refusal as that
    worker's error -- no Forge bypass (documented, not special-cased).
- [x] 2.3 Grouped dispatch per D3: lifecycle refactor to (invoker, request) pairs; `run_parallel` delegates as a single
  group; engine passes per-request invokers.
  - Assertion: all-Claude -> identical behavior via the single-group delegation (characterization 2.1 plus existing
    `tests/src/core/invoker/test_claude_invoker.py` lifecycle suite green unchanged); all-codex -> codex invoker hooks
    used; mixed -> results merged in input order; at most 5 concurrent children across both runtimes (fake slow Popen
    counting live children).
- [x] 2.4 `preflight_check` becomes per-runtime: the `claude`-binary error fires only when >=1 Claude-runtime worker is
  selected; >=1 codex worker validates the plan's frozen preflight per D4; D5 `resume_id` rejection;
  `_credential_preflight_error` stays scoped to direct-Anthropic routes. `_run_preflight`'s tip line
  (`cli/workflow.py:115`) becomes runtime-aware.
  - Assertion: codex-only spec list with no `claude` on PATH produces no claude error; cold/absent preflight fails
    closed with the refresh tip; `resume_id` + codex worker fails closed naming blind.
    `tests/src/cli/test_workflow_preflight.py`, `tests/src/review/test_engine.py`.
- [x] 2.5 Consensus owns one routing/preflight snapshot across both rounds. When no `routing_plan` is injected,
  `run_consensus` resolves once from the round-1 specs and reuses that plan for the prompt-only round-2 specs; supplied
  plans keep today's reuse behavior.
  - Assertion: direct `run_consensus(..., routing_plan=None)` calls `resolve_invocation_routing` exactly once; both
    `run_multi_review` calls receive the same plan object and frozen `codex_preflight`.
    `tests/src/review/test_consensus.py`.
- [x] 2.6 D9 runtime-error folding in `_to_review_result` with regression coverage for both runtimes.
  - Assertion: codex exit-0 + `runtime_is_error=True` (empty final text, provider message on effective stderr) ->
    `success=False`, stdout stays empty, and error carries the provider message; Claude exit-0 `is_error` envelope with
    empty stderr -> `success=False`, parsed stdout is preserved and also supplies the error text; both streams empty ->
    exact fallback `Runtime reported error`. Synthesis never sees any of them as successes; usage-event status and
    ReviewResult agree. For non-zero runtime-error envelopes, stream text takes precedence and empty streams retain the
    exact `Exit code N` fallback.
- [x] 2.7 Cancellation and mid-flight-kill semantics under the grouped dispatcher (D3): interrupt mid-fan-out terminates
  children of BOTH runtimes from the single registry; never-started jobs are `cancelled=True` (no emission); killed
  in-flight jobs emit error events (unchanged).
  - Assertion: fake-Popen mixed-dispatch test drives cleanup and asserts both partitions' children are reaped and the
    cancelled/killed emission split holds.

## Phase 3: Verb CLI and telemetry truthfulness

- [x] 3.1 Four verbs accept codex workers through the existing selection surfaces (`--models`, debate/consensus worker
  args); D7 flag semantics implemented; help text names the runtime axis and the `--effort` Claude-only rule.
  - Assertion: `--effort high` with a mixed quorum reaches only Claude argv; `--proxy` with a codex worker warns and is
    ignored for that worker; codex selections on debate and both consensus rounds retain `runtime="codex"` through
    prompt specialization and reach Codex argv. `tests/src/cli/test_workflow.py`, `test_workflow_consensus.py`.
- [x] 3.2 Telemetry truthfulness (the card's boundary list), matching the shipped emitter contracts:
  - Per-worker codex usage event: `route=codex_exec`, `runtime=codex`, `billing_mode` preflight-resolved
    (`subscription_quota` on ChatGPT), exact tokens, `cost_micro_usd=None` -- via the invoker's existing
    `emit_codex_usage`; asserted end-to-end from the engine, not just the invoker.
  - Downstream plane: the SAME emit writes exactly one direct-provider downstream attempt (`source_kind="provider"`,
    `provider="openai"`, `backend_id=None` per v1 mapping, exact tokens, `cost_micros` null, run-tree ids stamped) --
    design.md §3.14 native Codex token evidence. Assert presence WITH the boundary: no proxy-origin record, no
    `proxy_id`, no request-id correlation to any proxy cost record, no proxy-owned lifecycle/audit fields.
  - Verb aggregate unchanged: `track_verb_cost` snapshots proxy spend only; a codex worker (direct) contributes no
    verb-level cost and its tokens appear only on its worker event + downstream attempt (no double count).
  - Upstream: per-worker row (`workflow.worker`) for codex workers matches the Claude shape; `_record_workflow_outcome`
    verb row unchanged.
  - Assertion: ledger + downstream fixture tests in `tests/src/review/test_engine.py` /
    `tests/src/cli/test_workflow.py`.
- [x] 3.3 Synthesis-input equivalence: given identical final text, a codex worker's `ReviewResult.stdout` is byte-equal
  to a Claude worker's, and `format_synthesis_prompt`, `_evaluate_verdicts`, and `_build_reconciliation_brief` consume
  it unchanged.
  - Assertion: same-fixture comparison test; `tests/src/review/test_synthesis.py` or `test_engine.py`.
- [x] 3.4 **PARITY GATE (blocks Phase 4).** Unit suites green plus real-runtime integration:
  - New real-codex worker smoke: one-codex-worker panel run on the host ChatGPT login asserting success,
    synthesis-usable stdout, and a `runtime=codex` worker event (new
    `tests/integration/cli/test_workflow_codex_smoke.py`, fixtures/traps per `tests/integration/session/conftest.py` and
    impl_notes).
  - One mixed run (direct Claude + codex) asserting both worker events and input-order results -- single small prompt,
    cost-conscious.
  - Claude parity re-run: `./scripts/test-integration.sh tests/integration/cli/test_workflow_integration.py` and
    `tests/integration/docker/test_real_claude_workers.py` green.

## Phase 4: Frontend skill eligibility (gated on 3.4)

- [x] 4.1 Author neutral sources (`forge-skill.yaml` + `content.md`) for `panel`, `analyze`, `debate`, `consensus`;
  migrate `resources/`; bind capabilities (CLI, task args, resource loading) per the compile vocabulary; typed
  invocation policy.
- [x] 4.2 Content is runtime-honest: a Codex-hosted frontend drives `forge workflow ...`, and worker availability
  depends on worker runtimes (Claude binary for Claude workers, codex readiness for the codex worker) -- the skill never
  implies codex-native workers by default. Model-family selection stays host-runtime-owned (design_workflows.md §3.1
  rules).
- [x] 4.3 Install planning: the four packages become codex-eligible; duplicate scans, schema-v2 tracking, whole-tree
  validation, and the provenance sentinel all pass for both runtimes.
  - Assertion: `--runtime codex` skills planning includes the four packages; compiled Claude output remains equivalent
    for unchanged behavior. `tests/src/install/test_cross_runtime_skills.py` + compiler/validation suites.
- [x] 4.4 Compiled-package smoke: verify the emitted Codex package instructions invoke the verbs correctly (content
  review; a live codex-host `$panel` smoke if cheap).

## Phase 5: Docs sync and closeout

- [x] 5.1 Design docs updated with the shipped contract: `design_workflows.md` §3.5 (replace the "Portable frontend
  boundary (Axis 1 vs Axis 2)" paragraph), `design.md` §5.1 portable-set sentence, `design_appendix.md` §C.5 portable
  list and §G (`runtime_native` RoutingSource literal), `cli_reference.md` workflow section (runtime axis, D7 semantics,
  `model_selection` output field), CLAUDE.md skills/portability paragraph. The normative card wording was already
  aligned in Phase 0 (D2b/D9); closeout verifies the durable design docs match it.
- [x] 5.2 End-user docs (`docs/end-user/skills.md` and any workflow guide); QA checklist sections +
  `test-count`/`last-updated` header; walkthrough checklist if it exercises workflow verbs.
- [x] 5.3 Verification recorded: focused suites, `make test-unit`, targeted integration from 3.4, `make pre-commit`.
  - `uv run pytest` focused post-format suite: `731 passed`.
  - `make test-unit`: `8277 passed, 1 skipped, 117 deselected`.
  - Real Codex-only + mixed worker integration: `2 passed in 21.71s`.
  - Existing Claude workflow parity integration: `13 passed`.
  - `make pre-commit`: all hooks passed; `uv build` produced the 0.9.0 wheel and sdist.
  - Clean wheel install: `forge runtime list --json` found Claude and Codex; project skill installs for
    `--runtime claude`, `codex`, and `all` succeeded; Codex installed exactly nine healthy packages; sync was
    idempotent; disable removed all nine packages and its tracking row.
- [x] 5.4 `docs/board/change_log.md` entry; durable lessons proposed via `.forge/memory/shadow_impl_notes.md`.
- [ ] 5.5 After merge to `main`: card `doing/` -> `done/`, inbound links repointed, checklist preserved.

## Acceptance tests

| Test                            | Fixture                                                     | Assertion                                                                                                                                                                                                               | Test File                                                   |
| ------------------------------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| All-Claude requests unchanged   | default specs, stubbed Claude invoker                       | `HeadlessRequest` list byte-identical to pre-change golden (argv/env/prompt/attribution)                                                                                                                                | `tests/src/review/test_engine.py`                           |
| Codex worker request shape      | codex spec, frozen fake `CodexPreflight`                    | argv `codex exec --json --sandbox read-only`; sanitized env; `base_url=None`; attribution runtime/billing correct                                                                                                       | `tests/src/review/test_engine.py`                           |
| Runtime-native routing          | codex spec                                                  | `source="runtime_native"`, `route=None`, no proxy-registry/template read; positional plan alignment; unresolved route-null remains failure                                                                              | `tests/src/review/test_routing.py`                          |
| Runtime survives specialization | codex stance + codex role                                   | adversarial spec and both consensus-round specs retain `runtime="codex"` and dispatch through Codex                                                                                                                     | `tests/src/review/test_adversarial.py`, `test_consensus.py` |
| Consensus preflight snapshot    | `run_consensus` with no injected plan                       | routing resolves once; both rounds receive the same plan object and frozen Codex preflight                                                                                                                              | `tests/src/review/test_consensus.py`                        |
| Mixed fan-out ordering + cap    | 6 Claude + 2 codex specs, fake slow Popen                   | results align to spec input order; at most 5 concurrent children across runtimes                                                                                                                                        | `tests/src/review/test_engine.py`                           |
| Per-runtime binary preflight    | codex-only specs, `claude` absent from PATH                 | no claude-binary error; cold/absent codex preflight fails closed with refresh tip                                                                                                                                       | `tests/src/cli/test_workflow_preflight.py`                  |
| Resume-context rejection        | codex spec + `--context resume:<uuid>`                      | fail-closed error naming `--context blind`                                                                                                                                                                              | `tests/src/cli/test_workflow_preflight.py`                  |
| Runtime attribution in output   | mixed plan, `panel --json`                                  | entries carry `runtime`; runtime-native entry has `resolved_model=null` + `model_selection="runtime_default"` + `provider="openai"`; human shows `(runtime default)`; summary provider/runtime equal the worker event's | `tests/src/cli/test_workflow.py`                            |
| Codex worker telemetry          | ledger + downstream fixtures, codex worker result           | usage event `route=codex_exec`/`runtime=codex`/preflight billing/exact tokens/cost `None`; exactly one downstream direct-provider attempt (`backend_id=None`), no proxy correlation                                     | `tests/src/review/test_engine.py`                           |
| No verb/worker double count     | proxied Claude + codex worker, ledger fixture               | codex tokens absent from verb aggregate; present only on its worker event + downstream attempt                                                                                                                          | `tests/src/cli/test_workflow.py`                            |
| Runtime-error folding (D9)      | Codex/Claude `is_error` envelopes at exit zero and non-zero | `success=False`; stdout/stderr preserved; precedence is stderr, stdout, then generic exit-zero or numeric non-zero fallback; ReviewResult and usage status agree; synthesis excludes it                                 | `tests/src/review/test_engine.py`                           |
| Cancellation + kill semantics   | mixed requests, cleanup mid-fan-out                         | one registry reaps both runtimes' children; never-started -> `cancelled=True` (no emission); killed in-flight -> error event                                                                                            | `tests/src/review/test_engine.py`                           |
| Synthesis-input equivalence     | same final text via fake Claude + fake codex                | `ReviewResult.stdout` byte-equal; synthesis prompt identical                                                                                                                                                            | `tests/src/review/test_synthesis.py`                        |
| Real codex worker E2E           | host ChatGPT login, read-only sandbox                       | one-codex-worker panel succeeds; `runtime=codex` event recorded                                                                                                                                                         | `tests/integration/cli/test_workflow_codex_smoke.py` (new)  |
| Codex frontends compile         | neutral sources for the four verbs                          | `--runtime codex` plans 4 packages; whole-tree validation passes                                                                                                                                                        | `tests/src/install/test_cross_runtime_skills.py`            |

## Out of scope / deferred (recorded, not blocking)

- Proxied codex workers: every shipped codex consumer arm runs direct to OpenAI; routing headless workers through a
  Responses-capable proxy is a separate transport feature.
- Codex-thread resume as workflow context (`--context` is Claude-conversation resume; a codex analog is a different
  concept).
- Static backend identity for codex workers (see D2b): downstream `backend_id` stays null per the shipped v1 mapping;
  revisit only with a backend-catalog decision that survives API-key auth honestly.
- Team-supervisor runtime neutrality (separate card: `proposed/team_supervisor_plan_context`).
- Workspace-write codex workers; changing `DEFAULT_MODELS`; making codex workers default on codex hosts.

## Blockers

- None. D1-D9 are ratified and the D2b/D9 normative-card wording is aligned.
