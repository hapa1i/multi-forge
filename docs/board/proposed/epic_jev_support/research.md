# Jev research for Multi-Forge

Research date: 2026-10-06. Forge checkout: `c2638510`. This note records external findings, current Forge integration
points, and design avenues. The [epic](card.md) has a draft scope and three member cards. No inference benchmarks were
run or repository content sent to Jev.

Selected scope: OpenRouter Decisions first, then warning-only rule packs and a Jev first-tier cascade that escalates to
Claude. Direct TypeSafe remains a later access path; standalone Jev enforcement remains a research avenue. Use Forge's
existing `httpx`, a conservative 32,000-token total request budget and explicit yes/no criteria. Both policy consumers
need atomic questions and calibrated decision rules; plan checking also needs decomposition and coverage. Codex
supervision has a [separate epic](../../doing/epic_codex_supervisor/card.md). Jev Router remains separate work in its
[own card](../jev_router/card.md).

## Initial assessment

Jev supplies bounded judgments over text: classifications, probabilities, and rubric scores. That makes it relevant to
Forge's supervisor, semantic rule packs, policy cascade, event classification, and context selection. A useful
integration would preserve these typed results and let each consumer decide what they mean. Forge's current
chat-completion interface does not express that contract. Supervision is a role Jev could perform; using it only as the
cheap checker is one possible scope.

The primary economic opportunity is preserving Claude subscription quota by avoiding supervisor calls on cases Jev can
settle reliably. Fixed rule packs are a more bounded first policy experiment: stable questions, named rules and per-rule
evaluation without requiring an approved plan. Warning-only packs do not automatically avoid Claude calls. Jev remains
API-billed, so the user's no-API-spend everyday workflow leaves it disabled; complex projects can opt in.
[Current supervision and cascade](../../../end-user/policy.md#cascade-a-cheap-first-pass-before-the-supervisor-opt-in)

A read-only measurement on 2026-10-06 found **78 local session manifests, zero configured supervisors and zero sessions
with effective policy enforcement enabled**. All 78 parsed through Forge's reader and effective-intent resolver without
error. No confirmed supervisor lane bindings were present. The scope was this checkout's `.forge/sessions/`, not a
historical usage ledger or other workspaces; the
[audit details](../../doing/epic_codex_supervisor/research.md#measured-local-usage) record the method. This makes
adoption and useful warning/review quality part of the evaluation, alongside possible quota savings once supervision is
used.

OpenRouter also offers **Jev Router**, which selects a generative model and reasoning effort per request. Its routing
and effort contracts are outside this epic's typed-judgment scope.
[OpenRouter Jev guide](https://openrouter.ai/docs/guides/community/jev)

## What the model exposes

TypeSafe introduced Jev as a hosted “System One” model for decisions within larger workflows. Its launch benchmarks
report large latency and cost reductions on selected tasks, but their workflow labels use frontier-model consensus.
Those results motivate a Forge-specific evaluation; they do not establish correctness on repository policy decisions.
[Launch article](https://typesafe.ai/blog/introducing-system-one-models-and-jev)

| Primitive | Result                                        | Possible Forge use                                    |
| --------- | --------------------------------------------- | ----------------------------------------------------- |
| Choice    | Selected option, probabilities, confidence    | Event category or evidence sufficiency                |
| Noul      | Probability of “yes”                          | Whether a proposed action matches a stated constraint |
| Score     | Rubric score, level probabilities, confidence | Relevance of a transcript excerpt                     |

The native API takes `model`, shared `state`, and named `questions` at `POST /v1/systemone`. Question IDs are
caller-side identifiers; their names do not convey instructions to the model. Choice supports up to 255 options; Score
uses 2–10 descriptive levels. Responses contain typed answers, the resolved model, and token usage.
[API reference](https://docs.typesafe.ai/api)

Several atomic questions can share one state and be evaluated in parallel. The application composes their answers into a
supervisory decision; each question must name one concrete condition. Shared input does not establish statistical
independence, so multiplying answer probabilities would need separate justification. Parallel evaluation is a latency
property; current-route billing still needs the separate checks described below.
[Fan-out pattern](https://docs.typesafe.ai/patterns/fan-out)

As researched, the direct model is `jev-1.13.0`; both `jev-latest` and `jev-preview` resolve to it. Input is text,
including JSON text structures. Pricing is $0.042 per million input tokens, with free output. Two limits apply: 64k
tokens for the whole request, and 32k for the state plus the longest question. Published rate limits are 100k
tokens/second and 80 requests/second, explicitly subject to change. Calibrated consumers should pin a version and record
the resolved model. [Models and limits](https://docs.typesafe.ai/models)

Jev does not supply free-form explanations, generated memory documents, or an interactive coding-agent session. TypeSafe
explicitly describes integration into coding agents through API calls rather than replacement of the agent runtime.
[Coding-agent guidance](https://docs.typesafe.ai/introduction/coding-agents)

### Reliability limits that matter here

Choice and Score confidence summarize the returned probability distribution, not independently measured correctness.
Forge's current 0.8 supervisor threshold does not transfer. For a binary Choice, confidence above 0.9 means a winning
probability above 0.95. Noul returns only `p(yes)`; its optional derived confidence is `abs(2p - 1)`, so confidence
above 0.9 includes both `p > 0.95` and `p < 0.05`.

The current confidence page gives risk-dependent guidance, not a universal numerical automatic-action band. Its
`confidence > 0.9` transfer example still asks for confirmation. The launch article's calibration claim does not
validate Forge's questions or composed verdicts. Measure calibration, false allows, and false blocks on Forge data
before choosing thresholds; preserve raw probabilities and question identity.
[Confidence semantics](https://docs.typesafe.ai/confidence)

TypeSafe's Jev 1.13 limitations page, reviewed by the vendor on 2026-10-02, reports sensitivity to irrelevant context,
literal interpretation, option order, and adversarial instructions inside state. Numerical reasoning, counting, and date
comparisons are also weak areas. Repository text and transcripts can contain instructions that compete with the
classification task. Schema validity therefore does not establish semantic correctness or prompt-injection resistance.
Exact arithmetic, permissions, path boundaries, and mechanically decidable policy checks belong in deterministic code.
[Documented limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13)

The limitations page also explicitly advises against hiding multiple judgments inside one question and against System
Two tasks involving further indirection. A general “is this action aligned with the plan?” question bundles retrieval,
interpretation, scope, and compliance judgments for a realistic plan. Decomposition is a requirement for this design.
Small wording changes alone do not make a task requiring extended reasoning suitable for Jev.

## Access paths and their implications

OpenRouter is the first implementation route. Direct TypeSafe is an intended later path behind the same typed-judgment
interface, outside the initial three cards. Policy consumers would use the same answer types; credentials, model IDs,
reported usage/cost and privacy capabilities retain their provider identity. Provider selection is explicit.

| Route                     | API surface                         | Credential           |
| ------------------------- | ----------------------------------- | -------------------- |
| Direct TypeSafe judgments | `api.typesafe.ai/v1/systemone`      | `TYPESAFE_API_KEY`   |
| OpenRouter judgments      | `openrouter.ai/api/alpha/decisions` | `OPENROUTER_API_KEY` |

OpenRouter's judgment model is `typesafe/jev-1.13`, with alias `~typesafe/jev-latest`. Select its **alpha Decisions
API** and set `provider.zdr: true` on every Forge-owned request. It accepts `user`, `session_id`, and `trace`, and can
return `id`, `provider`, and `usage.cost`. These fields need Forge's existing attribution and reported-cost handling;
missing cost remains unavailable. The alpha designation makes schema compatibility an explicit integration risk.
[OpenRouter integration](https://openrouter.ai/docs/guides/community/jev),
[Decisions API](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request)

The endpoint choice is a design preference, not proof that System One cannot express ZDR. In the live OpenRouter
[OpenAPI document](https://openrouter.ai/openapi.json), both `/api/alpha/decisions` and `/systemone` reference
`DecisionsRequest`, including `provider.zdr` and the observability fields. The latter uses the default
`https://openrouter.ai/api/v1` server. Its compatibility guide is less explicit than the schema. Actual enforcement
remains a probe requirement for the chosen route.

Implement the OpenRouter wire adapter over the existing `httpx` runtime dependency. A later direct adapter would share
validation and result types while retaining its distinct transport. The TypeSafe SDK's inference method targets System
One rather than Decisions. It supports `extra_body`, so it could pass provider settings through the compatible route;
the reason to avoid it here is the selected endpoint and dependency footprint, not an inability to send additional
fields. [SDK method](https://docs.typesafe.ai/sdk/python/api/clients/sync),
[OpenRouter compatibility](https://openrouter.ai/docs/guides/community/typesafe-sdk)

SDK 0.7.2 requires `httpx2>=2.0`, `pydantic>=2.12`, and `tenacity>=9`. Forge declares `httpx2` only in its dev group and
runtime floors of `pydantic>=2.0` and `tenacity>=8`. Adding the SDK would expand runtime dependencies and tighten
declared constraints. The current lock already resolves Pydantic 2.13.5 and Tenacity 9.1.4, so this does not necessarily
upgrade those installed versions. The HTTP adapters would own bounded retries, a total hook deadline, schema validation,
and attempt attribution. [SDK metadata](https://github.com/typesafe-ai/typesafe-sdk-python/blob/main/pyproject.toml),
[Forge dependencies](../../../../pyproject.toml)

### Request compatibility and budgets

Always emit Noul `criteria` with explicit `true` and `false` descriptions. OpenRouter's current `DecisionsNoulQuestion`
requires `type` and `instructions`; `criteria` itself is optional, but both keys are required when it is supplied.
TypeSafe's direct schema makes criteria optional too. Requiring complete criteria in Forge is a deliberate contract
stronger than those minimums. [OpenRouter schema](https://openrouter.ai/openapi.json),
[TypeSafe schema](https://api.typesafe.ai/openapi.json)

Start with at most **32,000 total input tokens**, covering state and all questions, with estimation headroom.
OpenRouter's ZDR catalog lists a 32,000-token Jev context. TypeSafe documents 64k total and a separate 32k limit for
state plus the longest question. Preserve separate route limits rather than treating direct's 64k as portable. Raising a
budget needs route-specific boundary probes, including multi-question requests and oversize failure behavior.
[OpenRouter catalog](https://openrouter.ai/api/v1/endpoints/zdr), [TypeSafe limits](https://docs.typesafe.ai/models)

TypeSafe also publishes an agent skill for using its API. Offering that skill is a possible lightweight user-facing
integration, but would leave Forge-owned routing, audit, and policy behavior to a separate integration.
[Official skill](https://docs.typesafe.ai/agent-skill)

## Where it fits the current Forge code

### Rule packs backed by Jev: fixed semantic checks

[Workflow design §1.1](../../../design_workflows.md#11-deterministic-policy-forge-policy) already motivates detecting
coding-standard violations in diffs and describes this as a pattern-matching task that Haiku can handle. That supports
investigating semantic rule packs; it is not accuracy evidence. The shipped
[coding-standards bundle](../../../../src/forge/policy/deterministic/coding_standards.py) uses deterministic pattern and
character checks, including comment patterns for backward compatibility. It does not currently invoke Haiku.

A rule pack would own a fixed, reviewed set of atomic rules, their intent, applicability, question criteria, and stable
IDs and versions. For each applicable action, Forge would assemble bounded action evidence and send the applicable
questions together over shared state. Each question must describe its rule explicitly; the question ID is only a lookup
key. Jev would return probabilities, and Forge would compose warnings or requests for review. This uses the documented
[parallel-question pattern](https://docs.typesafe.ai/patterns/fan-out), subject to the request and billing limits above.
A pack needs no planning session to provide its rules; it is a separate consumer from plan supervision.

The useful target is meaning that existing literal checks miss, such as a compatibility shim without a matching comment.
Exact syntax checks should remain deterministic. A fixed rule can still require unavailable repository context or
extended reasoning: those cases need an explicit insufficient-evidence outcome, further decomposition, or another
reviewer. A stable question does not make every coding standard suitable for Jev.

Rule text gives a stable policy citation when bound to a rule version and source. It does not establish that the action
violates that rule. Findings should retain the rule citation and separately identify the assessed file, action, and
supplied code excerpt. Jev does not generate an explanation or evidence quote; Forge must assemble feedback from known
inputs, with any selection of supporting evidence validated separately. Pack versions belong in cache and evaluation
identity so a changed rule cannot reuse an old verdict.

Warning mode would return `warn` with a fixed diagnostic, independently of a supervisor. Escalation is a distinct mode
requiring a supervisor able to adjudicate the flagged rules. The current
[engine](../../../../src/forge/policy/engine.py) calls its resolver with `ActionContext`, not the earlier policy
findings; the [supervisor prompt](../../../../src/forge/policy/semantic/supervisor.py) checks plan alignment. A
configured supervisor therefore does not yet provide rule-pack adjudication. The handoff would need the rule versions,
flagged questions, probabilities, and action evidence, and a result that explicitly resolves those findings. A
plan-alignment allow alone must not clear an unrelated rule finding. Without a resolver, `needs_review` currently
blocks, so it cannot implement the proposed warning fallback. Existing deterministic denials still take precedence.

Warning delivery is conditional. Claude's [policy hook](../../../../src/forge/cli/hooks/commands.py) only emits
`additionalContext` when [policy_summary_feedback](../../../../src/forge/runtime_config.py) is enabled (the default),
and currently sends a generic summary/count rather than substantive rule text. A2 extends that formatter but respects
the setting: enabled delivers bounded rule/evidence feedback; disabled retains operator diagnostics and audit without
model injection. B3 applies the same model-feedback contract to Codex and separately tests operator `systemMessage`
visibility. A warning written to stderr alone does not prove either model or Codex UI delivery.

Repository history can supply candidate diffs for an offline evaluation against the existing deterministic checks. Human
labels are needed for violations and clean examples; merged code is not automatically compliant, and commits omit
rejected actions and often combine several edits. Reconstruct the context the check would have seen, record the rule
version used for labeling, and reserve held-out changes. Measure per-rule false positives and misses, insufficient
evidence, and the fraction of actions producing any warning: adding rules can make the pack noisy even when individual
rates look acceptable. A later opt-in observation or warning trial would establish actual hook-context behavior, warning
burden, escalation cost, and adoption. No historical evaluation or live trial has been run.

### Direct supervision: Jev can make enforcement judgments

Jev's typed API can evaluate atomic semantic conditions drawn from an approved plan. A Jev-backed supervisor would
compose those judgments in code into allow, warn, or deny decisions. A blanket alignment question is not the proposed
model contract. This is an architectural possibility, not a demonstrated equivalence to Forge's current reviewers.
[Typed judgments](https://docs.typesafe.ai/introduction)

The current [supervisor consumer](../../../../src/forge/policy/semantic/supervisor.py) requires a `tool_agent` lane. Its
Claude arm resumes planning context; its Codex arm receives an approved snapshot and can inspect the action's checkout.
The response includes a verdict, confidence, violation evidence, suggested fixes, and quoted plan sections. The
[decision mapper](../../../../src/forge/policy/semantic/verdict.py) blocks divergent actions only when confidence meets
the block bar and a violation includes citations. Jev cannot enter that implementation merely by changing the model ID.

One design would separate evidence assembly, judgment, and feedback:

1. Forge supplies approved plan clauses, the proposed action/diff, and relevant repository evidence with stable source
   references. Plan clauses need atomic questions with reviewed coverage; missing, unmapped, or truncated evidence stays
   explicit. Any model-assisted decomposition has its own cost and error risk.
2. Jev evaluates one concrete condition per question against the relevant evidence. Sufficiency is a separate judgment;
   tasks needing extended reasoning go to another reviewer. Questions and candidate evidence refer to supplied clauses.
3. Forge applies a validated decision rule and constructs a finding from the assessed clause and action evidence. It can
   quote the original sources and render a fixed diagnostic. Rich explanations or repair advice could use a generative
   reviewer when needed.

This can support direct enforcement for covered judgments. Passing all generated questions does not prove that every
relevant plan constraint was represented. Selecting an existing citation establishes its provenance, not that the cited
rule supports the verdict. Coverage and semantic support both need evaluation, separately from confidence calibration.

Two variants deserve discussion: a standalone supervisor over an explicit, bounded evidence set; and a hybrid supervisor
that handles covered cases with Jev and delegates evidence gathering or difficult judgments to a tool-capable reviewer.
The former needs an explicit policy for insufficient evidence and service failure. The latter needs explicit escalation
conditions and separate attribution for each reviewer. Both need evaluation of false blocks as well as false allows. The
observation-only experiment proposed below is a way to gather that evidence, not a permanent ceiling on Jev's role.

### Economics: protecting Claude quota

The selected goal is to reserve Claude subscription quota for cases that need its review. Existing Claude checks can
revisit planning context and incur tool turns; the new plan-file path will run fresh. Avoiding either call can reduce
quota use and executor waiting time. Call count and token usage are measurable, but are not an exact conversion into
subscription quota. Only report a quota decrement if the provider exposes usable evidence.
[Supervisor behavior and billing](../../../end-user/policy.md#semantic-supervisor-advanced)

The everyday constraint is no API spend: [B1](../../doing/plan_file_supervision/card.md) proposes independent direct
subscription supervision, with [B4](../codex_stop_review/card.md) reducing review frequency. Jev is a separate paid
opt-in. A warning-only pack adds checks and API cost; the cascade preserves quota only for requests where it actually
skips the Claude supervisor. Subscription terms and the difference between a lane label and a guaranteed unbilled route
are covered in the
[Codex research](../../doing/epic_codex_supervisor/research.md#subscription-use-credentials-and-spending).

At the researched Jev price, a request with 20,000 billed input tokens costs $0.00084; 1,000 such requests cost $0.84.
This arithmetic concerns **reported billable tokens**, not a 20k state with arbitrarily many questions. It is not a
measured Forge workflow price. Questions, evidence preparation, retries, and other reviewers add cost.
[Jev pricing](https://docs.typesafe.ai/models)

Multi-question billing is not wholly undocumented: TypeSafe's batching cookbook says the shared document is paid for
once per batched request and reports a 13-question example. That example uses Jev 1.12 and computes costs from usage at
the published rate; it is not an invoice or a current OpenRouter guarantee. Do not assume either free extra questions or
an automatic N-fold state charge. Compare one, several, and many questions over fixed state on each route, recording
reported input tokens and actual available cost/billing evidence.
[Batching evidence](https://docs.typesafe.ai/cookbooks/parallel_questions)

Measure Claude calls actually avoided, reviewer model/tokens, available quota evidence, escalation and audit calls,
total latency and Jev API cost at comparable decision quality. When the existing cascade is enabled, its remaining
supervisor calls are already selected for uncertainty or checker failure. Their replaceability cannot be inferred from
Jev doing well on easy aligned actions. Question preparation, retries and audits must be included in the resource
comparison; adding a cheap call on every action does not by itself protect quota.

Separate cascade-on and cascade-off baselines. For explicitly API-billed complex-project routes, also compare total
reported spend including cached usage and retries. That is a different economic case from preserving spare subscription
quota; lower request prices alone establish neither benefit.

### Cheap plan checking: an existing integration point

The [plan checker](../../../../src/forge/policy/semantic/plan_check.py) currently sends a bounded approved-plan/action
prompt through a generative model and parses an alignment verdict plus reason. Within the supervisor cascade, a clean
allow can avoid a frontier call; uncertainty or checker failure escalates. Only clean allows are cached. Fresh allows
can be sampled for later frontier audit with frozen evidence. [Policy contract](../../../design_workflows.md)

Jev could answer atomic plan-clause questions over canonical inputs; Forge would compose alignment and evidence
sufficiency outcomes. Illustrative application outcomes are `aligned`, `needs_review`, and `insufficient_evidence`;
these are not a blanket model question or a selected schema. Only a separately validated aligned outcome could
eventually short-circuit the cascade. Feedback would identify known categories and evidence or come from another
reviewer.

The costly mistake is a false allow: a high-confidence mistake can prevent the frontier review that would have caught
it. Existing shadow capture is useful groundwork, but it samples allowed actions rather than providing a complete
labeled dataset. An observation-only comparison would need broader coverage. Frontier disagreement is evidence for
inspection, not automatic ground truth.

### Team event classification: simple output, limited evidence

The live [team handlers](../../../../src/forge/policy/team/handlers.py) classify events into `routine`, `trivial`, or
`needs-review` before optionally invoking a supervisor. That output maps naturally to Choice. However, the current
[classification prompts](../../../../src/forge/policy/team/prompts.py) mostly see teammate/team names and, for
completion, the task subject. A different classifier cannot infer implementation quality from absent evidence.

The existing [team supervisor plan-context proposal](../team_supervisor_plan_context/card.md) is related context work.
Separately, `core/reactive/tagger.py` defines a generic tagging helper, but the inspected checkout has no production
caller; changing it alone would not improve a live path.

### Search and transfer selection: useful without generation

Forge's [search engine](../../../../src/forge/search/engine.py) ranks transcript documents with local BM25. Jev could
score a bounded shortlist for relevance while retaining document identity and the original search results as fallback.
This adds remote disclosure, latency, and cost to a currently local operation. The
[semantic-search proposal](../semantic_search/card.md) already considers local retrieval and optional reranking; its
scope should be reconciled before choosing another search direction.

For transfer and memory, judgments could select relevant source excerpts or flag candidate decisions for review. The
existing [transfer curation](../../../../src/forge/session/transfer.py) and [memory writer](../../../design_memory.md)
still own prose generation and publication. A Jev answer cannot create an evidence reference: source IDs and existing
citation checks would remain attached to the actual input excerpts. The
[windowed curation proposal](../windowed_incremental_curation/card.md) is relevant to bounded inputs, but is not shipped
infrastructure that this research can assume.

### Review triage: prioritize within explicit bounds

Judgments could help prioritize review questions or select specialist attention. They should operate within the caller's
requested coverage and deterministic budget rather than silently deciding that requested review is unnecessary. The
[adaptive-review proposal](../adaptive_review_behavior/card.md) already covers budgeted review behavior. An integration
would need to distinguish prioritization from permission to omit a check.

### Jev Router: separate card

OpenRouter documents Jev Router on Chat Completions, Responses, and Messages, including streaming. It chooses a
generative model and reasoning effort per request; its response and price belong to that selected model. Its inclusion
filter has a surprising behavior: if no models match, the inclusion list is ignored. Exclusions still apply; an empty
resulting pool returns 404. An inclusion list therefore cannot be treated as a strict allowlist. Optional response
metadata exposes resolved models and routing fallback information.
[Router behavior](https://openrouter.ai/docs/guides/routing/routers/jev-router)

This belongs in the [Jev Router card](../jev_router/card.md), outside this epic. Forge's shipped
[launch-effort change](../../done/session_launch_effort/card.md) gives explicit client effort precedence on opted-in
translated requests and clamps it against the mapped model. Per-request router effort selection creates an unresolved
precedence and capability conflict with that contract; the router docs do not establish what happens to an explicit
caller effort. Requested versus selected model identity, safe context limits, ZDR, replay, and sampling also need their
own design. [Effort resolution](../../../../src/forge/proxy/reasoning.py),
[runtime architecture](../../../design_runtime.md)

## Shared design questions

- **Typed capability and ownership.** The existing [LLMClient](../../../../src/forge/core/llm/protocols.py) accepts
  messages and returns text/tool calls or stream events. A sibling typed-judgment contract could expose state,
  questions, distributions, model identity, and usage without manufacturing completion text. The
  [lane](../../../../src/forge/core/lanes.py) and [model-source](../../../../src/forge/backend/sources.py) abstractions
  would need to distinguish judgment support from generative support. The exact public surface is undecided.
- **Consumer-owned action and fallback.** A shared client should report judgments and failures; the policy cascade, rule
  pack, supervisor, search, or curation consumer determines the action. In a cascade or hybrid supervisor, missing
  evidence or service failure can route to another reviewer. A standalone Jev supervisor would need its own explicit
  failure policy. Search can retain its original ranking. Memory selection needs a fallback that does not silently
  discard evidence. These consequences should not be hidden behind one global confidence threshold.
- **Reproducibility and budgets.** Cache identity would need the canonical state, complete question/rubric version,
  model/route, and decision rule. Both token limits matter, and truncation must be visible to the consumer. A pinned
  model does not remove the need to reevaluate changed prompts, option order, or input construction.
- **Usage and provenance.** Forge already separates physical provider attempts from session-level operations and uses
  reported cost, not catalog-price estimates. OpenRouter's returned cost is promising; direct TypeSafe token usage alone
  cannot establish an actual dollar charge. The current [direct usage helper](../../../../src/forge/core/usage/emit.py)
  leaves cost null, so existing credentials do not imply that typed-call accounting works automatically. Retries also
  need attributable attempts. Jev answer confidence must stay distinct from telemetry measurement confidence.
  [Telemetry authority](../../../design_telemetry.md)
- **Credentials and data handling.** Direct TypeSafe would add credential resolution and readiness behavior; OpenRouter
  can reuse an existing [credential owner](../../../../src/forge/core/credential_registry.py). TypeSafe states that
  customer requests are not used for training and offers enterprise ZDR. A read-only query of OpenRouter's public ZDR
  catalog on the research date listed `typesafe/jev-1.13` under provider `TypeSafe`. That supports investigating an
  OpenRouter route, but does not prove ZDR enforcement on its typed endpoint. The selected Decisions route would send
  `provider.zdr: true`, matching Forge's [existing policy](../../../../src/forge/core/llm/openrouter_policy.py). Verify
  enforcement and failure behavior before using real plan payloads. Observability metadata should follow Forge's
  existing identity rules; endpoint support does not authorize copying raw session content into `trace`.
  [TypeSafe data terms](https://docs.typesafe.ai/legal),
  [OpenRouter ZDR catalog](https://openrouter.ai/api/v1/endpoints/zdr)

## Selected cards and remaining design avenues

The draft scope is [A1: client and probes](../jev_client_probes/card.md),
[A2: warning-only rule packs](../jev_rule_pack/card.md), and [A3: cascade](../jev_cascade/card.md). A2 needs
[B3](../codex_policy_warnings/card.md) for Codex-visible warnings; A3 needs
[B1](../../doing/plan_file_supervision/card.md) for fresh plan-file Claude supervision. Those cards belong to the
separate Codex supervisor epic. The broader avenues below remain research context, not additional committed members.

| Avenue                           | Main purpose                                   | First useful evidence                          |
| -------------------------------- | ---------------------------------------------- | ---------------------------------------------- |
| Agent skill or explicit utility  | Let users invoke Jev judgments                 | Real user tasks and API ergonomics             |
| One opt-in internal consumer     | Test a concrete Forge benefit                  | Comparison with the current consumer           |
| Rule packs backed by Jev         | Check fixed semantic rules on each action      | Labeled diffs, per-rule errors, warning burden |
| Jev supervisor backend           | Enforce plan alignment directly or in a hybrid | Cited judgments, false allows, false blocks    |
| Shared typed-judgment capability | Support several Forge consumers consistently   | Common semantics across two consumers          |

The selected first policy consumer is a small warning-only pack; its fixed questions make correctness easier to test
than arbitrary plan decomposition. A3 is a separate consumer with its own evidence requirements and conservative
allow-or-escalate behavior. Full standalone Jev supervision remains deferred, and Jev Router stays outside this epic.

A useful comparison would include clear alignment, clear divergence, missing plan evidence, ambiguous instructions,
truncated state, irrelevant text, embedded adversarial instructions, and reordered options. Human-adjudicated examples
would distinguish model agreement from correctness. Measurements should include false-allow rate, false-block rate,
escalation rate, quality at each proposed threshold, total p50/p95 latency, timeout behavior, and reported cost
including retries. For supervision, the current supervisor path, with its configured cascade, is the baseline; comparing
individual checker and frontier judgments helps explain differences. No suitable threshold or performance target has
been established by this research.

The remaining decisions belong to the member cards:

1. Which fixed semantic rules can be judged from supplied action evidence, and what warning burden is useful locally?
2. Who creates and validates atomic questions from approved plans, and how is missing coverage identified?
3. What do the OpenRouter probes establish about ZDR routing, size limits, billing, latency and alpha-schema stability?
4. What held-out quality evidence justifies A3 allowing a covered action without a Claude judgment?

Rule-pack escalation, standalone Jev blocking and the direct TypeSafe adapter need later scope decisions. They are not
implicitly authorized by the first three cards.
