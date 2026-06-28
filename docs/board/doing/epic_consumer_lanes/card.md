# Epic: Consumer Lanes -- bind Forge's LLM-work to a chosen (runtime x backend x model) lane

**Type**: Epic (coordinating card). Members are independently-shippable tickets that share the lane contract below. The
first wave is split into member cards (linked beneath the member table): **T1a, T3, T2, T4, and T5 are all done** -- the
spine T1a+T3, the T2 backend axis, the T4 codex-exec supervisor lane, and T5's lane observability have landed on `main`.
The **first wave is complete**; the epic stays in `doing/` coordinating T1b (next cursor), T6, and T7 (added in
`proposed/subscription_exhaustion_failopen/`). T1b is now a member card (`doing/consumer_lane_binding/`, 2026-06-27); T6
stays an inline sketch (board_contract "Epics").

**Status**: Accepted; coordinating in `doing/` (2026-06-25). First wave complete on `main`: T1a (PR #51,
`src/forge/core/lanes.py`) and T3 (PR #52, supervisor lane-driven, byte-identical) are both **done** in `done/`; T2 (PR
#54, runtime-native subscription sources) is **done** in `done/` (2026-06-26); T4 (PR #55, codex-exec supervisor lane,
the headline capability demo) is **done** in `done/` (2026-06-27); **T5 (PR #56, lane observability) is done in `done/`
(2026-06-27)**. Converged from a 2026-06-25 design session; this card is the durable record of that model. Coordination
is tracked in `checklist.md`.

**One-line motivation**: Make "use a different runtime/backend/model for part of what Forge does" -- Codex on a
subscription today, a local Ollama tomorrow -- a *registration + a consumer's lane choice*, not a bespoke rewrite each
time.

**References**: design.md §3.6 (config ownership), §3.6.12 + design_appendix.md §G (subprocess routing -- the resolver
to lift), design_workflows.md §3.5 (runtime registry + invoker seam), design_appendix.md §A.2.1 (ModelSource catalog =
the "backend"), impl_notes.md (unified-backend invariants; runtime seam = capability half + lifecycle half).

---

## Problem

Forge performs ~15 distinct units of LLM-backed work on the user's behalf (supervisor, memory writer, review fan-out,
taggers, plan-check, transfer curation, ...). A 2026-06-25 codebase sweep found that **each resolves its model, backend,
runtime, and billing in a different ad-hoc way** -- ~6 routing mechanisms, inconsistent usage emission, several
hardcoded models. Two structural gaps follow:

1. **Runtime is hardwired.** The supervisor calls `run_claude_session` unconditionally (`supervisor.py:507` ->
   `session_runner.py:184` builds `["claude","-p"]`); the review fan-out hardwires `ClaudeHeadlessInvoker.run_parallel`
   (`engine.py:214`). `SupervisorConfig` has no `runtime` field (`supervisor.py:237`). A `CodexHeadlessInvoker` exists
   and is proven in the session/bridge paths, but no aux consumer can reach it.
2. **No placement primitive.** Billing is *observed* (`billing_mode` telemetry) but never *chosen*. There is no clean
   way to place a consumer on a cheaper capacity pool (a subscription you already pay for, a local model), and no clean
   way to swap when a new arbitrage appears.

## Why now -- the motivating arbitrage (and why it is not the *only* justification)

A Claude Max 20x user hits the weekly quota wall. Aux `claude -p` work (the supervisor fires on every Write/Edit) is
billed API-or-quota; `infer_billing_mode` "never guesses subscription modes" (`billing.py:14-28`). Meanwhile
`codex exec` can ride a ChatGPT subscription the user already pays for -- verified: `codex_preflight.py` resolves
`chatgpt_tokens -> subscription_quota` (`CodexAuthMethod`, ~line 98/402), needs no key injection. Offloading the
supervisor to Codex is zero-incremental-dollar.

**But the arbitrage is transient** (vendors change billing; "codex exec rides a subscription" may close like `claude -p`
did). So the **durable** value is *churn-resilience*: a clean placement seam that survives a policy shift. The
Codex-cost win is the motivating first instance, not the load-bearing rationale -- the seam is also justified by
fidelity (Codex-native reasoning vs the proxy's thinking-strip), decorrelation (different harness+model for
review/supervision), and future local/free backends.

## The model (shared contract -- the durable value)

| Concept      | Definition                                                                                                                                                                                                                                                                                                              | Reuses                                                                         |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **Runtime**  | the *execution engine* -- single-shot `core.llm` -> tool-agent `claude -p` / `codex exec` / future. Carries a capability attr (single-shot vs tool-agent).                                                                                                                                                              | `RuntimeSpec` / `RUNTIMES`, widened to admit `core.llm` as the cheapest engine |
| **Backend**  | a *billable capacity source* -- the catalog `ModelSource` (a source id like `openrouter`/`chatgpt`), **not** the runtime `BackendInstance` (a local process like `litellm-4000`). Auth + billing posture (per-token / subscription-quota / free) + reachability are **properties of the backend**, not a separate axis. | `ModelSource` (`sources.py`); distinct from `BackendInstance` (`registry.py`)  |
| **Model**    | the model id.                                                                                                                                                                                                                                                                                                           | model catalog                                                                  |
| **Lane**     | a concrete **(runtime x backend x model)** tuple. Transport (direct vs proxy) is a *derived/constrained* property, not a chosen axis.                                                                                                                                                                                   | lifts `RoutingResult`                                                          |
| **Consumer** | a unit of Forge LLM-work (the ~15 below + the main session). Declares a **capability floor** + a **valid-lane set** (floor ∩ reachable) + a **chosen lane** (override or default).                                                                                                                                      | new                                                                            |
| **Binding**  | each consumer -> **one** chosen lane, resolved **once at session start** and **frozen**. Policy in `intent`; resolved binding in immutable `confirmed`.                                                                                                                                                                 | `WorkerRoutingPlan` ("resolve once, frozen") + manifest `intent`/`confirmed`   |

**Capability lattice (formalizes the headless-vs-direct cost/capability tradeoff).** Runtimes order by capability:
`core.llm` (single-shot) \<= `claude -p` / `codex exec` (tool-agent). Each consumer has a **capability floor** below
which it cannot drop (a reviewer that must read files cannot become a single `core.llm` call; a tagger that judges
provided text can). Upward is **not** automatic: a stronger runtime brings hooks, filesystem access, different prompt
framing, a different output envelope, and side effects -- so a consumer can be **adapted upward only when it declares an
adapter** (prompt framing + output-envelope normalization + side-effect/hook gating). One adapter half already exists:
the invoker normalizes both runtimes' output to `HeadlessResult.stdout` (`codex.py:96`), which is exactly why
`parse_supervisor_verdict(str)` works for Claude and Codex alike; prompt-framing and hook-gating are the per-consumer
halves still owed. The **gating** half scales with a second axis orthogonal to the floor -- **harness thickness**: how
much native opinionation (hooks, plan mode, policy, MCP) Forge must suppress to keep a lane coherent. On it `core.llm`
(none) < a thin-harness tool-agent like pi (read/write/edit/bash only) < `claude -p` / `codex exec` (thick); thinner
harness -> cheaper adapter, so the leanest runtime is the cleanest lane to admit (see *Prior art: pi*). Resolution =
intersect the floor with the legal lanes that have an adapter, pick per the consumer's choice/default.

**Backend carries billing -- no `account`/auth axis.** The same provider can appear as two backends differing only by
billing: `openai-api` (per-token) vs `openai-chatgpt` (subscription quota); `anthropic-api` vs `claude-max`. "Use my
subscription" = pick that backend. Auth is the backend's *mechanism*, never role-facing config. **Caveat (verified):**
today's `ModelSource` carries no billing posture (it is *inferred* in `infer_billing_mode` / codex preflight), and its
access vocabulary `EndpointKind = {literal_url, connection_value, local_backend}` (`sources.py:19`) is endpoint-only --
a subscription is runtime-native auth with **no endpoint**. T2 makes both first-class.

**Reachability is sparse, not a full cross-product.** A subscription backend pins its runtime (`claude-max` only via
`claude`; `chatgpt` only via `codex`); a foreign model pins a proxy transport; a capability floor excludes agent
runtimes. So the resolver reads a **(runtime, backend) reachability table** (the catalog + `RuntimeSpec` already imply
most of it); a consumer's valid lanes = legal ∩ floor. Do NOT build a generic combinatorial engine.

**No fallback (de-scoped).** A consumer binds to one chosen lane, frozen for the session. The valid-lane set is for
*validation + option-listing*, not failover. Mid-session capacity exhaustion is out of scope.

**Default = current behavior.** Every consumer defaults to its present lane (no config required); the abstraction kicks
in only where the user *overrides*. Non-negotiable for adoption -- you never configure all 15.

## Prior art: pi (validates the primitive, by contrast)

pi (`earendil-works/pi`) -- a deliberately minimal terminal coding agent (read/write/edit/bash + a sub-1000-token
prompt; MCP, sub-agents, plan mode, permissions, and hooks are opt-in extensions, *not* core) -- is the closest shipping
thing to a pure lane, and it sharpens this epic two ways:

- **The runtime axis can be thin.** pi is BYOK across ~28 providers + Ollama, exposes backend and model as first-class
  flags (`pi --provider openai --model gpt-4o`), and runs headless (`pi -p`). Its near-zero harness makes the adapter's
  **gating** half ~a no-op -- a tool-agent barely above `core.llm` + a loop, and the cheapest possible upward target.
  Two of our three axes (backend x model) are already its native vocabulary.
- **Model-swap-alone is not orchestration -- the gap this epic fills.** pi's whole answer to heterogeneity is **one axis
  (model), varied temporally**. It collapses **runtime** to a constant (every unit of work is *pi*), is
  **billing-blind** (a claude->gpt swap silently crosses subscription-quota to per-token), and **punts orchestration to
  extensions** -- where each user rebuilds an ad-hoc consumer->lane map, and every sub-agent is still pi, so the runtime
  axis never reopens. This epic is **N consumers x (runtime x backend x model), resolved once and frozen** -- a
  structural map, not a live knob. pi is the ideal lane *implementation* and a non-answer to lane *orchestration*.

**Caveat (unverified)**: pi's subscription `/login` (Claude Max, ChatGPT, Copilot) is confirmed *interactive*; the docs
do not confirm it in headless `pi -p`. That one fact decides whether a future pi runtime is a real *subscription cost
lane* or just another BYOK/API + local-Ollama lane -- verify before promoting pi from reference to lane.

## Prior art: workweave/router + Avengers-Pro (validates two bets; diverges on mechanism)

`workweave/router` (Go, Elastic-licensed) productionizes Avengers-Pro (arXiv:2508.12631) as a drop-in proxy that picks
the **model + provider per request** via an on-box embedding cluster-scorer. It sits **one layer below** this epic: it
varies the model *beneath a fixed harness*, where consumer-lanes choose the harness (runtime) + backend + model per
known consumer, resolved once and frozen. Forge's `(backend x model)` sub-tuple is the router's *entire* domain; the
**runtime axis is above it** -- the router never chooses the harness (the user installs it under Claude Code / Codex /
opencode).

- **Independently validates two bets.** (1) *Subscription billing-as-backend*: it detects OAuth-served turns (Claude Max
  `sk-ant-oat`, Codex/ChatGPT JWT), bills them 0% with a full-cost *shadow* ledger, and discounts covered models by
  *observed rate-limit headroom* -- validating T2's **economic/billing** shape (`billing_posture="subscription_quota"`,
  plus headroom as a future extension). But it reaches that through a **different access shape** than T2: a
  credential-forwarding passthrough proxy (the future shape flagged in the transport risk note below), not Forge's
  endpoint-less `runtime_native`. (2) *Capability gating*: a distinct `AgenticLow` ("harness-capable") flag, separate
  from tool-use quality, filters the eligible pool on tool turns -- an **analog** of this epic's capability floor, not
  an instance: it is a model/harness *fitness* gate (is this model fit to drive an agentic loop?), where Forge's floor
  is a runtime-tier minimum. Same instinct -- "emits tool calls" != "can drive the loop".
- **Diverges on mechanism -- justified by problem shape.** It is *learned + dynamic per-request* (embed -> k-means
  cluster -> per-cluster quality/cost blend, with a price\<->quality dial = the paper's `alpha`); consumer-lanes is
  *declarative + frozen*. Dynamic content-aware routing pays on the router's **open user-query stream**; it is the wrong
  tool for Forge's **closed set of ~15 known consumers**, whose role Forge knows by construction (the router has to
  reconstruct it from the request). A frozen lane is also structurally immune to the router's dominant practical problem
  -- the prompt-cache penalty from switching models mid-loop (its top HN critique).
- **Two borrowable ideas (later, narrow).** (a) A **subscription-exhaustion fail-open** ("sub spent -> degrade to the
  default lane") narrowly **reopens the "No fallback (de-scoped)" line** above for the "Why now" quota wall -- now **its
  own ticket, T7** (downstream of T4), not a silent reversal or general dynamic routing. Distinct from **T4**, which
  settles the *unsupported-lane* fail-open (a bad/unimplemented lane -> default); T7 handles a *spent subscription*.
  Subscription **headroom** is the related read surface, routed to **T5** (see Discussion-derived backlog). (b)
  Cache-aware model switching (their session-pin + EV planner) is worth it **only** for the long-lived main loop, never
  the single-shots (which hold no durable cache to preserve).

## Discussion-derived backlog (workweave/Avengers-Pro, 2026-06-26)

The prior-art review produced exactly one *new* ticket -- validations build confidence, not backlog; a ticket falls out
only where the comparison **challenged** a recorded decision:

- **T7 (new) -- subscription-exhaustion fail-open** -> `docs/board/proposed/subscription_exhaustion_failopen/`: the
  narrow, one-hop exception to "No fallback" for the "Why now" quota wall. Depends on T4.
- **T4 decision resolved**: the unsupported-lane failure mode is **catch + fail-open** (consistent with
  `proxy_not_found`), settling the open T3 -> T4 carry-forward seam.
- **T5 += two reads**: surface subscription **headroom** (the perishable rate-limit budget workweave reads via
  `usage.Snapshot.Exhausted()`), and an **"explain the resolved lane" dry-run** (workweave's `/v1/route` analog -- show
  what lane a consumer resolves to without dispatching).
- **T0 corroborated**: workweave detects OAuth subscriptions (`sk-ant-oat`) as a real, working signal, so the
  `claude-max` "does `claude -p` ride the Max subscription?" question is empirically answerable, not speculative.

## Inventory this serves (2026-06-25 sweep)

- **M1 `claude -p` agents (6)**: semantic supervisor, memory writer, shadow curation, supervisor shadow replay, review
  fan-out (panel/analyze/debate/consensus), team supervisor.
- **M2 `codex exec` agents (via `CodexHeadlessInvoker`)**: codex session turns, codex bridge turn, enrollment probe.
- **M3 `core.llm` single-shot (6)**: action tagger, tier-1 plan-check, transfer curation, WorkflowPolicy
  Checker/Reviewer stages, team event tagger.
- **M4 interactive (anchor, user-pinned lane)**: interactive Claude (host/bare/sidecar), Codex TUI, bare Codex proxy.

The M1/M3 routing diversity (~6 mechanisms) + the no-emission gaps (WorkflowPolicy stages, team tagger --
agent-reported, verify) are the same "ad-hoc resolution paths" smell `resolve_subprocess_routing` already collapsed
once.

## Member tickets

| Ticket                                                                     | Scope                                                                                                                                                                                                                                                                                                                | Depends on | Proves                                       |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | -------------------------------------------- |
| **T1a -- Pure lane/consumer resolver** (spine)                             | `Lane`/`Consumer` types, default-lane computation, capability-floor + (runtime,backend) reachability gating, valid-lane listing/validation. **No manifest persistence.** No consumer rewired.                                                                                                                        | --         | the seam fits the code                       |
| **T3 -- Supervisor becomes lane-driven** (Claude default)                  | Refactor `run_supervisor_check` to resolve a lane + dispatch; default lane = `claude -p`, **byte-identical to today**. No durable schema yet.                                                                                                                                                                        | T1a        | resolver on the existing case                |
| **T2 -- Backend: runtime-native subscription sources**                     | Extend the existing source-access enum (`EndpointKind` today -- rename if `runtime_native` makes "endpoint" a misnomer, but keep **one** enum) with a `runtime_native` shape + add a first-class billing posture; encode (runtime,backend) reachability. **Explicit access/billing vocabulary; no faked endpoints.** | T1a        | billing-as-backend, honestly shaped          |
| **T4 -- Codex-exec supervisor lane** (capability demo, the headline)       | Wire `CodexHeadlessInvoker` as a supervisor dispatch target; the choice rides a **narrow `SupervisorConfig` field**. **Acceptance: blind/transfer-fed only -- MUST NOT use Codex hooks or policy enforcement as part of the claim.**                                                                                 | T1a,T2,T3  | a real new lane, swappably                   |
| **T5 -- Observability**                                                    | Surface the chosen lane + resulting `billing_mode` (telemetry/status); close the M3 no-emission gaps so every lane is measurable.                                                                                                                                                                                    | T3,T4      | you can *see/verify* the arbitrage           |
| **T1b -- Generalize + freeze**                                             | Promote the narrow supervisor field to a uniform consumer-lane binding; persist the `intent` override + immutable `confirmed` binding (**durable-state rules: schema version, strict deser, reset path -- coding_standards §5**).                                                                                    | T4         | a durable contract, shape-proven             |
| **T6 -- Generalize to other consumers** (optional, later)                  | Lane-drive the fan-out workers, taggers, memory writer.                                                                                                                                                                                                                                                              | T1b        | spans consumers, not just supervisor         |
| **T7 -- Subscription-exhaustion fail-open** (new, the discussion's ticket) | When a consumer's subscription lane hits the quota wall, degrade **once** to its default lane (sticky, fail-open) -- the single deliberate exception to "no fallback".                                                                                                                                               | T4         | the "Why now" quota wall is actually handled |

**Member cards (first wave)**: T1a -> `docs/board/done/consumer_lane_resolver/` (done, PR #51); T2 ->
`docs/board/done/backend_subscription_sources/` (done, PR #54); T3 -> `docs/board/done/supervisor_lane_driven/card.md`
(done, PR #52); T4 -> `docs/board/done/codex_exec_supervisor_lane/` (done, PR #55); T5 ->
`docs/board/done/lane_observability/` (done, PR #56); T7 -> `docs/board/proposed/subscription_exhaustion_failopen/`
(authored 2026-06-26, depends on T4); T1b -> `docs/board/doing/consumer_lane_binding/` (active cursor, 2026-06-27). The
rows above stay the durable sketch; the cards carry verified touchpoints + fixture-grounded acceptance. **Correction
(verified 2026-06-25):** the `ModelSource` catalog is code-defined (`BUILTIN_MODEL_SOURCES`, validated at import in
`backend/sources.py`), so T2 is an *internal-surface clean break* -- **not** Forge-owned durable state. Schema
version/strict-deser/reset rules apply only to T1b's session-manifest binding.

**T0 -- sibling billing cleanup**: revisit the `claude -p` `unknown`/OAuth billing assumption (`billing.py`) against
current Anthropic `-p` billing -- likely stale on the Claude side. **Non-blocking for the proven `chatgpt` path (T2/T4),
but load-bearing for `claude-max`**: a `claude-max` subscription source must not claim `subscription_quota` until T0
proves `claude -p` actually rides the Max subscription.

**Assembly is cheap (verified).** The Codex supervisor (T4) reuses shipped pieces: the verdict parser takes a plain
string (`verdict.py:86 parse_supervisor_verdict(response: str)`); `CodexHeadlessInvoker` already returns its final text
in the same `HeadlessResult.stdout` (`codex.py:96`); `compose_codex_initial_message(transfer_body, task)`
(`codex_bridge.py`) already frames a curated transfer + task into a `codex exec` prompt; the supervisor prompt is
already text-composition with precedent for context injection (`supervisor.py:458-466`).

## Sequencing

T1a -> T3 -> T2 -> T4 -> T5 -> T1b; T6 and the sibling cleanup follow. **T1a+T3 prove the abstraction fits the current
code with zero durable-schema commitment** (a pure resolver + the byte-identical Claude default). T4's Codex choice
rides a **narrow `SupervisorConfig` field** (already session-owned and persisted), so it needs no general schema. **T1b
lands last**, generalizing that narrow field into the uniform consumer-lane binding + immutable `confirmed` record once
the shape is proven -- deferring durable state until a real override exists.

## Risks / open questions

- **Backend stretch (verified, T2)**: `EndpointKind` (`sources.py:19`) is
  `{literal_url, connection_value, local_backend}` -- all endpoint-shaped; a subscription is runtime-native auth with no
  endpoint, and `ModelSource` has no billing posture (inferred in `infer_billing_mode` / codex preflight). T2 must
  extend the existing source-access enum (`EndpointKind` today) with a `runtime_native` shape and add a first-class
  billing posture -- **not** fake an endpoint to satisfy the existing dataclass. The type name may change (the
  "endpoint" label becomes a misnomer once `runtime_native` exists), but there must stay **one** source-access enum --
  do not add a second, parallel one alongside it.
- **Durable state lands late (T1b)**: the `intent` override + immutable `confirmed` binding are Forge-owned durable
  state; when T1b lands they need a schema version, strict deserialization, and a reset/migration path (coding_standards
  §5). Deferring T1b avoids committing that schema before the shape is proven.
- **Transport is derived, not chosen**: proxy-vs-direct is forced by (runtime, backend) reachability. The subscription
  constraint is *key-auth-specific*, not "no proxy at all": a **key-auth** proxy injects its own bearer key, so it
  cannot present a runtime-native subscription -- hence T2 rejects a `runtime_native` source backing today's proxy
  templates (`config/loader.py`). A **same-surface passthrough** that *forwards* the runtime's native subscription
  credential upstream (as `workweave/router` does for Claude Max / Codex) would be a **distinct future access shape**,
  not a relaxation of `runtime_native`, and carries a heavier trust posture -- Forge's proxy process would transit the
  subscription token, which `runtime_native` deliberately avoids today (the runtime owns auth; Forge never sees it).
  Model transport as resolver-computed, not a user knob.
- **Codex's hard problems are avoided by scope**: T4 is *headless* (`codex exec` needs no enrollment-gated hooks) and
  *transfer-fed/blind* (no Claude-UUID resume). Do not expand T4 to supervised-Codex-executor-with-enforcement.
- **Naming**: unit = `consumer` (vs `service`/`client`); `lane`; keep `runtime` narrow. Confirm before code.
- **Decision recorded**: no *general* fallback (subscription-exhaustion fail-open to the default lane is **T7**,
  downstream of T4 -- the single exception; T4 owns only the *unsupported-lane* fail-open); default-to-current-behavior;
  first new lane = codex-exec supervisor.

## T3 -> T4 carry-forward seams (fail-open boundary)

Recorded during T3 local review. None are bugs in shipped T3: `resolve_lane(SUPERVISOR_CONSUMER)` takes no override, so
it always returns the `claude_code` default lane and the non-claude dispatch arms are unreachable via
`run_supervisor_check`. Each flips live the instant T4 adds the `SupervisorConfig` override / `codex` arm. The
supervisor's contract is **fail-open** (a policy-eval failure degrades to "aligned" -- design_workflows §1.2), so a lane
misconfig must not crash the policy hook.

- **Move `resolve_lane` inside the fail-open guard (T4).** `run_supervisor_check` calls
  `resolve_lane(SUPERVISOR_CONSUMER)` *outside* the `try/except _SupervisorRoutingError` (`supervisor.py:603`). With no
  override it cannot raise; once T4 passes `override=...`, a bad override raises `LaneError` uncaught and crashes the
  hook -- the opposite of fail-open. T4: pre-validate and degrade to the default lane, or move the `resolve_lane` call
  inside the guard.
- **Unsupported-lane failure mode is a decision, not an accident (T4).** `_dispatch_supervisor` raises
  `NotImplementedError` (codex) / `LaneError` (unknown) (`supervisor.py:463-464`); the caller catches only
  `_SupervisorRoutingError`, so an unimplemented/unknown runtime propagates and bricks the hook. Loud is defensible in
  dev; a misconfigured production lane should not brick a session. Decide deliberately (catch + fail-open, consistent
  with `proxy_not_found`, vs. intentional loud) -- tracked as a Decision owed in the epic checklist.
- **`SUPERVISOR_CONSUMER` validates at import.** It is a module-level `Lane`, so `__post_init__` (`lanes.py:59-64`) runs
  `runtime_execution` + `resolve_model_source_id` at import: renaming `claude_code` out of `RUNTIMES` or
  `anthropic-direct` out of the catalog crashes `supervisor.py` import (cascading to CLI/hooks), not just supervisor
  execution. Reasonable fail-fast, but a sharper blast radius than a runtime config error -- a note for whoever
  maintains the runtime/backend catalogs.

## Out of scope

Mid-session failover / capacity forecasting; making *every* consumer configurable on day one; runtime-mixing for the
interactive session beyond what already exists; supervised Codex *executor* enforcement.
