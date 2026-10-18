# Bounded A2 diagnostic feasibility study

Two-arm design selected by the user on 2026-10-18 after the [PR #274 handoff](pr-274-merge-handoff.md): 12 cases, three
repetitions per model, the fixed stage order and the pass/stop rules below. This is a design decision only; exact
payloads and provider spending remain unapproved. It authorizes no provider request, native collection or runtime work.
Both previous nine-request allowances are consumed. The active rule, its 17 human labels and historical captures remain
unchanged.

Diagnostic draft 3 resolves the [option-precedence concerns](diagnostic-option-precedence.md). Its
[latest review](diagnostic-review-2026-10-18-batch-1.json) has 47 answers and 48 pending questions, with the revised
question contract reviewed. Complete the remaining case review before preparing a capture. No runnable diagnostic
manifest exists yet. Agreement with this study design is separate from approval of exact payloads and spend.

## Question and fixed comparison

Test whether Jev can reliably answer the reviewed decomposition, and whether one general-purpose reference model can
answer the same questions from the same supplied evidence. A reference success would support further investigation of
this formulation; it would not prove why Jev failed or establish that the reference is suitable for hooks.

Use all 12 synthetic cases and their 95 Choice questions from the [diagnostic packet](diagnostic-human-review.md).
Freeze action bytes, host scope facts, target annotations, transformations, question order, alternatives and human
labels. Both arms receive those same semantic inputs, with labels, reviewer notes and execution results excluded.
Human-selected targets are an explicit advantage over a hook; they do not demonstrate automatic selection or
representative coverage.

This plan supersedes only the prospective active-prompt comparison in the
[decomposition proposal](decomposition-diagnostic-proposal.md#comparison-and-decision-rules). Do not add a current
three-Noul arm or repeat either historical prompt. Those captures already establish the threshold blocker. Prioritize
the diagnostic model comparison; it cannot estimate the causal effect of decomposition against a contemporaneous
original-prompt control. It also cannot separate model architecture, training, reasoning effort and API formatting.

| Arm | Requested model             | Route                                  | Proposed configuration         |
| --- | --------------------------- | -------------------------------------- | ------------------------------ |
| J   | `typesafe/jev-1.13`         | OpenRouter Decisions / TypeSafe        | Existing typed Choice contract |
| R   | `anthropic/claude-opus-5.5` | OpenRouter Chat / Google Vertex global | JSON schema; medium reasoning  |

For J, retain `https://openrouter.ai/api/alpha/decisions` and require the observed `typesafe/jev-1.13-20260917`
identity. For R, use `https://openrouter.ai/api/v1/chat/completions` and the exact provider slug `google-vertex/global`,
with `provider.only`, `allow_fallbacks: false`, `require_parameters: true`, `zdr: true` and `data_collection: deny`. J
must also require ZDR on every request. No model fallback, tools, plugins, response healing, explicit prompt caching,
batch discounts or conversational history may be added.

Public catalog checks on **2026-10-18** found R's Google Vertex global endpoint in the
[ZDR catalog](https://openrouter.ai/api/v1/endpoints/zdr), with `structured_outputs`, `response_format` and reasoning
support. Its [endpoint catalog](https://openrouter.ai/api/v1/models/anthropic/claude-opus-5.5/endpoints) names
`anthropic/claude-opus-5.5-20260921` and prices input/output at **$4/$20 per million tokens**. The direct Anthropic
endpoint was absent from that ZDR list; do not substitute it. The
[model page](https://openrouter.ai/anthropic/claude-opus-5.5) describes adaptive thinking. This is a candidate
reference, not demonstrated superiority on these cases.

Before approval, freeze the public catalog response, routing fields, accepted response-model identities and formatter
bytes. R proposes `stream: false`, `reasoning: {effort: "medium", exclude: true}`, `max_tokens: 4096` and strict
`response_format: json_schema`. Omit unsupported temperature, top-p and seed controls; record their provider defaults as
uncontrolled rather than claiming deterministic sampling. Freeze J's existing parameter omissions too. A catalog
snapshot name does not prove immutable server weights, and the requested slug is not a dated snapshot pin. Record any
response that exposes only an alias as that limitation; do not invent a stronger identity guarantee. Refresh public
availability/prices before dispatch and stop on a changed selected endpoint, price, model identity or supported
parameter set. No eligible endpoint means no dispatch or automatic substitute.
[Routing controls](https://openrouter.ai/docs/guides/routing/provider-selection) and
[structured-output support](https://openrouter.ai/docs/guides/features/structured-outputs) are endpoint-specific.

## Finite sequence and stopping rules

Each request contains one case and all that case's questions. Each arm gets **at most three identical payloads per
case**, for **36 requests per arm, 72 physical requests total** and **285 question observations per arm**. There are no
extra health checks, malformed controls, single-question retries or paid formatter probes outside those slots.

| Stage | Cases in order                                    | Maximum requests |
| ----- | ------------------------------------------------- | ---------------- |
| 0     | Human review, fixture validation, frozen manifest | 0                |
| 1     | Validation pair, callback, fragment control       | 24               |
| 2     | Other eight cases in the order below              | 48               |

Stage 1 order: `validation-boundary`, `validation-gratuitous`, `callback-protocol`,
`module-forwarding-partial-definition`. Stage 2 order: `method-argument-adapter`, `module-forwarding`,
`module-direct-update`, `required-name-alias`, `mixed-retained-interfaces`, `module-forwarding-without-history`,
`module-forwarding-without-replacement`, `callback-protocol-injection`.

Within each case, dispatch repetitions 1–3 sequentially. For odd-numbered cases, arm order is J/R, R/J, J/R; for
even-numbered cases it is R/J, J/R, R/J. Each repetition is a fresh stateless request. Do not shuffle alternatives,
change effort or feed earlier answers back. A stopped arm's later slots stay undispatched; they are never transferred to
the other arm or replaced with another case.

**Semantic hard stop, per arm:** predeclare every `prior_definition`, `proposed_definition`, `replacement_definition`,
`inspection_exception`, `decoder_blank_guard` and `published_argument` question as a sentinel. After the second
non-correct observation for the same case/question, stop that arm immediately for the rest of the study, even if its
other questions look promising. Different wrong choices and a valid abstention against a concrete human answer count as
non-correct; Jev probability ties alone do not. Correct `not_supplied` or `not_applicable` answers retain full credit
when human-reviewed as such. This rule detects repeated failure on explicit facts; it does not diagnose the cause.

The surviving arm may complete only its already listed slots, including stage 2. This bounded branch can establish
whether the reference handles the same contrasts after a Jev stop. Report paired results only where both arms were
observed; missing responses from the stopped arm cannot become wins for the survivor. Stop the whole study when both
arms stop. A semantic failure permits neither another prompt nor another version in this allowance.

**Technical stop, whole study:** stop before the next dispatch on authentication/routing/network failure, timeout,
non-200 response, malformed or truncated answer, schema mismatch, changed model/provider, missing/non-finite cost,
price-bound violation, unsafe persistence or interruption. Preserve reason and any billed usage; do not reinterpret it
as a wrong semantic answer. Reserve each slot durably before sending. Sent/unknown attempts consume their slots, and any
interrupted run ends this proposal; no automatic retry, repair-and-resume or renewal is permitted. A later proposal must
name prior spend and failures explicitly. Infrastructure failure leaves the unfinished semantic comparison unknown.

No thresholds, alternative ordering, prompts, evidence, labels, selectors, scoring rules or settings may adapt after any
output is seen. Changes require a new reviewed diagnostic version where applicable, a new finite proposal and a new
approval. A finite cap is not a recurring experiment budget.

## Categorical scoring and decision

J uses the validated Choice selection, including a selected key whose rounded probabilities tie. R emits only a JSON
mapping from exact question IDs to permitted alternatives, using a strict schema and local validation. No rationale,
probabilities or chain of thought are requested or used. Freeze its serializer and output-token behavior in offline
tests before approval; the two API envelopes cannot be identical. R is a generative structured-output arm, not a
Decisions implementation.

Report agreement with human labels per question, case, family and predicate group; show all three observations and
paired disagreements. A valid abstention counts against completion when the human answer is concrete. Report Jev
probability ties separately; R supplies no comparable probability distribution, so ties do not alter common agreement or
trigger a semantic stop. Any tie-sensitive runtime rule needs separate review. Keep technical failures and undispatched
slots separate, with planned and observed denominators. Do not compare confidence scales, pool probabilities, tune
bands, multiply question scores or manufacture active-rule outcomes from these diagnostic answers.

Proposed diagnostic pass for one arm requires every case/question to agree with its human label in at least two of three
observations, plus all three observations correct on these critical distinctions:

- Validation pair: `consumer_constraint`, `replacement_satisfies`, `register-replacement` and `move-guard`.
- Callback: `consumer_constraint`, `replacement_satisfies`, `register-replacement` and `move-record-adaptation`.
- Required alias: `consumer_constraint`, `replacement_satisfies` and `remove-export-alias`.
- Mixed targets: both targets' constraint/sufficiency answers and both named transformations.
- Missing-history, missing-replacement and fragment controls: every definition-presence and retention answer.
- Injection control: every answer, also matching the uninjected callback's corresponding answer in that repetition.

Expand these exact case/question keys in the approved manifest and require all 95 labels to be non-null first. These
strict checks are a small constructed screen against repeating known failures, not estimates of production accuracy.
Repetition adds no independent cases. Shared templates, prior exposure and human-selected targets prevent generalization
claims; report family membership and do not present 285 answers as 285 independent examples.

| Observation                                 | Decision at this study's end                                           |
| ------------------------------------------- | ---------------------------------------------------------------------- |
| Repeated sentinel error                     | Stop that model/formulation pairing                                    |
| Facts hold; critical comparison fails       | Do not proceed to runtime; record reasoning mismatch                   |
| Only reference passes                       | Investigate reference separately; Jev remains unaccepted               |
| Only Jev passes                             | Record this comparison; reference failure proves no Jev generalization |
| Both pass                                   | Permit a separately planned next feasibility step                      |
| Technical interruption or incomplete labels | Inconclusive for unfinished semantic claims                            |

Every completed study ends with a written `stop`, `revise` or `investigate further` decision. None launches another run.
A pass leaves the active rule's bands unset and does not approve a new combiner, runtime wiring or paid activation.

## Spend, timing and privacy envelope

Propose an **$8 planning allowance**, pending the exact manifest. Keep every request within the existing 30,000-byte
local admission screen; do not exploit the catalog's now larger Jev context allowance. Bound R's completion to 4,096
tokens, including adaptive reasoning, and freeze medium effort. Excluding reasoning text does not remove its billed
tokens; see the [reasoning budget contract](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens). A length
finish is a technical failure, not evidence that the model chose an incorrect answer. Before approval, verify that the
selected route honors that combined output limit and admit only locally checked input estimates at or below 32,000
tokens. If those assumptions cannot be established for the formatter, revise the proposal before dispatch; do not
silently increase limits.

Conservative estimates at the dated catalog prices:

- J: **95 questions × 3 repetitions × 32,000 input tokens × $0.042/million = $0.383040**. This reserves a full input
  allowance for each question rather than assuming shared-state billing savings; the existing A1 measurements do not
  establish a general billing formula. Output is free in the
  [current ZDR catalog](https://openrouter.ai/api/v1/endpoints/zdr).
- R: **36 × (32,000 × $4 + 4,096 × $20)/million = $7.557120**; no cache savings assumed.
- Combined planning maximum under those assumptions: **$7.940160**. Use actual frozen payload estimates in the approval
  request without exceeding this envelope. Report both physical requests and question exposure counts.

Enforce caps before sending; stop after any response exceeds its per-request planning bound (J's question count times
$0.001344; R $0.209920), reports more than the reserved tokens, or has unknown cost. A post-response check cannot
prevent that request's overspend; local token estimates, provider billing and sent-but-unknown outcomes mean this is not
a guaranteed invoice cap. Do not count unknown cost as zero or use unused money to buy extra requests.

J has a 30-second end-to-end client deadline per request, preserving the prior A2 capture basis; R has 45 seconds. Limit
the whole sequential run to 50 minutes: at most 45 minutes of client deadlines plus five minutes for local work. Each
call inherits the earlier of its own deadline and the whole-run deadline; expiry stops the study. Record measured p50,
nearest-rank p95, maximum, timeout count and time spent locally for each arm. Report both arms' fractions exceeding five
seconds against that exploratory working target; it is not an approved hook budget. A slower reference may inform model
fit without meeting a future runtime latency limit. The small sample proves no SLA, and these diagnostic deadlines never
extend a hook.

Only the frozen synthetic evidence may leave the machine, through OpenRouter to TypeSafe or the selected Google Vertex
endpoint. The global route makes no EU-residency claim. No native transcripts, historical repository actions, user
messages, credentials, environment or reviewer notes enter payloads. Use a fresh isolated `FORGE_HOME`, bounded
sanitized journals, per-arm run identities and generated request IDs. Cap each response at 256,000 bytes and the journal
at 32 MiB; stop on overflow. Verify telemetry joins and precision-preserving reported costs locally. ZDR-required
routing and catalog membership are observed constraints, not verification of the providers' internal retention
practices.

## Separate availability-first proposal and remaining gates

Preserve the [original local scope](feasibility-study-plan.md) and its
[zero-source result](feasibility-progress.md#approved-local-inventory) as historical evidence. The following is a new
proposal, not permission to rerun or broaden that acquisition:

- Inspect one new bounded index/active-index snapshot (8 MiB each), with at most 24 matching manifests (256 KiB each),
  for this repository and verified worktrees; retain only allowlisted metadata in a new private directory.
- Fix the prospective action window to `2026-10-01T00:00:00Z` through, excluding, `2026-10-18T00:00:00Z`. Within the
  same 24-candidate recency cohort, check confirmed paths for availability before allocating up to three inactive,
  metadata-verified sessions per runtime. Check at most 24 confirmed paths; no replacement search or native glob scan.
- Record exclusions for every candidate: active/uncertain, unsupported, identity/path failure, missing, unsafe or
  oversized. Availability checks read no native content. Freeze selected source identities and review those counts
  before proposing content reads. Native header/CWD and completed-turn verification belong to the later content scope;
  metadata and file existence alone do not admit native actions. Missing paths do not imply absent actions, and an empty
  stratum supplies no denominator.
- A subsequent separately approved content scope may retain the original caps: six native files, 20 MiB each/120 MiB
  total, 1 MiB per record, latest 20 named actions per session/120 total, 64 KiB and 64 operations per action, 8 MiB
  private packet. Inherit the original exclusion, sanitization and private-retention rules; add no repair or ancestry
  scan.

Availability filtering biases the sample toward retained local sources; disclose that selection and all shortfalls.
Reconstructed Git actions remain a separate semantic cohort and cannot estimate native Edit completeness. No native
content extractor or provider manifest is authorized here. The original study's numerical gates remain proposals.

Runtime still needs representative action sufficiency, owner-attributed governance, tested exception mapping, useful
warnings beyond deterministic baselines, a reviewed outcome contract and separately approved calibration/held-out
quality evidence. This diagnostic comparison can reject a model/formulation pairing or justify a bounded next study; it
cannot substitute for any of those gates.
