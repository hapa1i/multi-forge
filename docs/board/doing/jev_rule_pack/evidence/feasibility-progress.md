# A2 feasibility progress

2026-10-17 continuation from PR #272 (`64317485`). The 17 constructed human judgments and semantic criteria are
unchanged. This checkpoint records preparation, an acquisition shortfall and two synthetic captures; it does not
establish runtime feasibility.

Current follow-up: the [bounded offline review](offline-retention-admission.md) compares the existing AST baseline with
the 12 diagnostic and 17 constructed cases, separating structural candidates, evidence admission and semantic retention.
It preserves the [completed study's failed result](bounded-diagnostic-2026-10-18/README.md) and frozen labels. No new
judgment call or native collection ran. The offline review records the size-checker's unintended document-count request.
The historical checkpoints below describe their own revisions; the offline review owns the current proposed
responsibility split and next evidence gate.

## Approved local inventory

The user approved the [local study scope](feasibility-study-plan.md) before collection. The corrected metadata inventory
found 88 matching session-index rows. The fixed recency cap considered 24 and left 64 untouched. Five active-registry
entries were excluded; the other 19 candidates were eligible, all Claude. The newest three consumed the Claude source
slots. No Codex source was eligible within the cap.

Independent review caught an initial exclusion of supported version-1 manifests. The correction required unchanged index
and active-index hashes before rereading the same candidate cohort. It raised eligible metadata rows from nine to 19;
both the original and corrected ledgers are retained. No native content was read during either pass.

All three corrected selected confirmed native paths were missing. The study did not search for replacements, expand its
date window or inspect older candidates. It read zero native transcript bytes and collected zero actions. The metadata
and source-admission ledgers remain in a private local directory with no source identities or payloads committed here.
`rule-pack-inventory.py` implements only this metadata and source-admission stage; a native action extractor was not
built without an admitted source.

Consequently, action coverage, governance, exception mapping and practical usefulness are **unmeasured**. A zero-action
sample supplies no denominator and cannot pass or fail those gates. The next real-evidence step needs a revised,
concrete acquisition scope, such as another bounded metadata cohort or explicitly selected available native sources.
Missing sources do not authorize a broader scan. The proposed numerical gates remain unratified.

## Constructed baseline comparison

The [retained baseline report](constructed-baselines.json) binds the same case/payload identities and input admission as
Jev. Across the 13 model candidates, existing compatibility-marker patterns flag none. The bounded AST detector flags
eight cases, finds no recognized retention shape in three, and reports two unsupported cases: a partial Edit and a
multi-file patch. Both preserve the other four host decisions.

The AST candidates include the required callback and validation boundaries as well as retained shims. These are
structural signals, not semantic warnings, and their absence does not prove compliance. Parameters, imports and other
supplied bindings that make target identity ambiguous remain unavailable. No caller inventories or file reads extend the
supplied action. Baseline supported syntax and source digests are recorded before any held-out model output.

## Synthetic capture boundary

The user separately approved the [calibration plan](calibration-run-plan.md), and its nine constructed requests
completed on the expected Jev 1.13 snapshot with ZDR required, no retries and isolated telemetry. The
[capture result](calibration-2026-10-16/README.md) records $0.000461370 reported cost and a 523.75 ms median latency.

The semantic calibration decision is **revise**: neither legitimate-boundary case can produce its human `no_warning`
outcome under any allowed threshold bands. Boundary-positive scores are 0.14 and 0.16, below every allowed true cutoff.
Threshold settings remain unset; no held-out manifest is prepared. Constructed observations cannot replace the missing
representative evidence or justify runtime implementation.

The user approved an
[instruction-only boundary clarification](boundary-question-proposal.md#adopted-boundary-instruction) on 2026-10-17,
keeping coverage, retention, all semantic criteria and human labels unchanged. A separately approved
[second capture](calibration-boundary-2026-10-17/README.md) completed the same nine constructed requests at `970de77a`.
All returned HTTP 200 from the expected snapshot; reported cost was $0.000516936, with 539.679 ms median and 742.992 ms
maximum latency. Both nine-request approvals are now consumed; no further provider requests are authorized.

The active boundary instruction did not resolve the blocker. Boundary-positive scores were 0.15 and 0.28, while the
negative duplicated-validation case also scored 0.28. Callback coverage was 0.48 and direct-update coverage was 0.47,
despite true human labels. All three human `no_warning` cases are now unrecoverable under the allowed bands. The
decision remains **revise**, settings remain unset, and held-out capture and runtime work remain gated. The historical
comparison has no contemporaneous control or repetitions, so it cannot establish causation or stability.

The [offline decomposition review](decomposition-diagnostic-proposal.md) recommends a separate diagnostic experiment:
check explicit code facts, then constrained substitutions, while testing structural coverage independently.
Human-selected targets would isolate reasoning after selection, not demonstrate a feasible hook selector. New predicates
and controls need human review and separate identities; the active contract and labels remain unchanged. No further
capture is prepared or authorized.

The [blank diagnostic packet](diagnostic-human-review.md) contains 12 synthetic cases and 95 Choice questions. It
preserves the six original action inputs and adds six controls, including a two-target action and matched missing
evidence. Target hints, selector bindings and exact transformations are hash-bound for human review. The offline
validator reports partial answers and contract status without importing labels or accepting quality. No diagnostic
capture manifest or provider run is included.

The walkthrough exposed ambiguous direct-replacement and completeness wording. Diagnostic `draft-2` permits only the
named registration edit for the selected target, preserves required lookup names, and distinguishes attributable
fragments from absent or ambiguously attributed evidence. The packet and all worksheets are regenerated with new
identities. At regeneration, all 95 answers and contract review remained pending; agreement on the interpretation was
not imported as labels. Action evidence, transformations, active rule criteria and existing adjudications are unchanged.

The [cumulative diagnostic ledger](diagnostic-review-2026-10-17-batch-6.json) records the user's review of all 12 cases,
including the missing-history, missing-replacement, fragment and instruction-injection controls. All 92 supplied answers
match the draft-2 identities and validate; earlier answers and notes are preserved. Both validation cases establish
consumer constraints; the replacement satisfies them directly only in the gratuitous case. The callback replacement
fails the supplied protocol, while the method's historical-call probe establishes a changed call shape without
establishing a current consumer requirement. The forwarding case shows ordinary continued use; the direct update
establishes no retention despite the old name's absence from the proposed image. The user reviewed the direct update's
four-question routing. The alias control requires the retained lookup name; the mixed case keeps each target's consumer
constraints separate. The injection review preserves the callback answers because action comments cannot supply
authority. The missing-history control records absent prior definition and retention evidence; the missing-replacement
control records absent replacement and retention evidence despite complete prior/proposed definitions and ordinary
consumer use. Their remaining three answers are explicitly null pending clarification of consumer evidence requirements
and replacement-comparison precedence.

The contract status is `reviewed`, retaining the user's approval of decomposition and no-retention routing alongside two
unresolved [option-precedence concerns](diagnostic-option-precedence.md). The later missing-history review also flags
the consumer question's reference to continued use of an old interface as an unclear history prerequisite. The
fragment's explicit `not_supplied` choices are recorded with its caveat: prior/proposed presence also fits the current
`ambiguous` wording. Those two answers are not uniquely determined by the current criteria. The proposed clarification
changes no question or label; adoption would require a new diagnostic version and renewed review of changed questions
and the contract. Supplied evidence, active-rule labels and the paid-call boundary are unchanged, and quality remains
unaccepted. The review-identity tooling update below preserves the original ledger while separating its provenance.

The earlier direct-update coverage score of 0.47 does not establish why the model failed. Coverage already explicitly
allowed a complete clean break, and the provider supplied no rationale. Confusion between an absent proposed symbol and
missing history remains a diagnostic hypothesis, not a demonstrated cause.

## Verification

The combined rule-pack, A1 probe, evaluation/review, capture, baseline, inventory and regression selection passed 347
tests. These tests use synthetic metadata and injected transports. The first retained manifest reproduces from its
recorded source; current preparation artifacts use the revised boundary instruction. The first capture's nine response
contracts, model/accounting guards and telemetry request-ID joins pass; numerical quality gates and runtime admission
remain open.

The instruction revision preserves all 17 adjudication hashes and the human-review packet. The refreshed preparation and
baseline reports bind the new prompt/payload identities; baseline signals remain unchanged. The new nine-request
manifest reproduces from its capture revision and changes only boundary instructions within its payloads. The second
capture completed all nine attempts without transport, answer-contract, model or accounting guard failures.

Diagnostic preparation passed 398 focused tests, including 51 new packet/identity/validator and executable-fixture
checks. The JSON packet reproduces exactly; all 12 worksheets preserve its evidence, criteria, targets and pending
answers. Executable transformation results remain test evidence, separate from human adjudications.

The draft-2 clarification passed 406 focused tests, including eight regressions for exact registration substitutions,
fixed consumer behavior, required-alias and target isolation, stale-packet rejection, and pending review labels.

The PR review follow-up passed 453 focused tests. Diagnostic answer identity now excludes unrelated active-rule
provenance, and explicit carry-forward retains only unchanged question contexts with source receipts. The original
92-answer ledger remains byte-identical and validates directly; three answers remain null. Schema-2 template identities
were regenerated without changing any of the 95 questions or 12 actions/annotation sets. The
[compact history](diagnostic-review-history.json) reconstructs every original batch byte-for-byte from the final ledger,
replacing five full snapshots and saving 1,001,324 bytes net.

Capture proposals now retain identity across implementation-only edits. A dispatch recorded in retained A2 journals
prevents accidental replay before credential access; deliberate repeats need a separately reviewed new proposal ID. New
journals also record checkout dirtiness. The guard covers retained journals, not unretained/deleted evidence or
concurrent launches, and cannot grant spending authority. Historical captures and approved manifests remain unchanged.
No additional paid call or native acquisition ran. The next study still needs a bounded stopping rule, a separately
approved model comparison and a revised availability-first acquisition scope with source-exclusion counts.

## 2026-10-18: resolved wording and bounded follow-up

Diagnostic `draft-3` applies the [definition/consumer/sufficiency precedence](diagnostic-option-precedence.md). The
[carried review](diagnostic-review-2026-10-18-carried.json) retains 32 unchanged answers and leaves 63 pending,
including the three original nulls; overall contract review is pending. Its packet identity is
`05281aaa9120e749f576180af62e9ba17096df1a079dae8bd3b8a84fbe331033`. The draft-2 human ledger remains byte-identical,
with its original answers and caveats. Actions, scope, annotations, transformations and the instruction guard are
unchanged; no human answer was inferred from the wording decision.

The [bounded follow-up plan](bounded-feasibility-plan.md) proposes a finite paired diagnostic comparison, per-arm
semantic hard stops and a whole-study technical stop. It replaces the prospective active-prompt control, not historical
evidence. The stronger-model candidate and revised availability-first acquisition remain proposals requiring separate
review and authorization. No capture manifest, provider request or new native collection is part of this change.

The combined rule-pack, probe, evaluation/review, capture, baseline, inventory and regression selection passed 454
tests, including the changed question groups and exact review carry boundary. The active rule, its 17 labels, settings
and historical captures remain unchanged. Runtime feasibility is still open.

## 2026-10-18: incomplete-evidence controls reviewed

The human confirmed all five revised questions in each of `module-forwarding-without-history`,
`module-forwarding-without-replacement` and `module-forwarding-partial-definition`, against the current packet and case
hashes. The [new ledger](diagnostic-review-2026-10-18-batch-1.json) records those 15 answers and verbatim case notes,
retains 32 inherited answers with their source bindings, and leaves 48 questions pending. The reviewer confirms that
draft 3 resolves all three precedence concerns; question-contract review is `reviewed`, while quality remains
unaccepted. The original draft-2 and initial draft-3 carried ledgers remain unchanged.

The validation pair is next for renewed case review. The study design and provider spending remain separate decisions;
no manifest, paid inference or native acquisition was added.

## 2026-10-18: two-arm study design selected

The user retained the [bounded plan](bounded-feasibility-plan.md): Jev and Opus answer the diagnostic questions only,
with 12 cases and three repetitions per model, up to 72 requests. The fixed stage order, per-arm repeated-sentinel stop,
whole-study technical stop and two-of-three/all-three agreement rules remain as written. The conservative arithmetic is
$0.383040 for Jev plus $7.557120 for the reference, totaling $7.940160 under the stated assumptions. This preserves the
$8 planning allowance; it does not guarantee an invoice ceiling or establish a lower expected-spend estimate.

This selects the experiment design without authorizing dispatch, provider spending or revised native acquisition. The 48
pending case answers, exact payloads, route checks and separate capture approval remain required. No labels, manifest or
provider calls were added.

## 2026-10-18: validation pair reviewed

The human confirmed the five revised parser questions in each validation case against the current packet and case
hashes. Both cases establish consumer constraints; the replacement fails the required blank-input exception contract in
`validation-boundary` and already satisfies it in `validation-gratuitous`. The
[new ledger](diagnostic-review-2026-10-18-batch-2.json) records those ten answers and verbatim notes. It retains all 32
inherited answers and source bindings, bringing the total to 57 answers with 38 pending across seven cases. Contract
review remains `reviewed`; quality remains unaccepted. Earlier ledgers and diagnostic evidence are unchanged.

The callback and method-adapter pair is next. No paid capture, manifest or native acquisition was added.

## 2026-10-18: callback and method adapter reviewed

The human confirmed all ten revised questions in the callback and method-adapter pair against the current case hashes.
The callback's selected consumers establish a Record protocol that the replacement cannot satisfy under the permitted
wiring edit. The method's selected consumer has already migrated to the replacement, leaving no independent constraint
to compare; its historical-call probe supplies no current consumer requirement.

The [new ledger](diagnostic-review-2026-10-18-batch-3.json) records the answers and verbatim notes, preserving all 32
inherited answers and their source bindings. It has 67 answers and 28 pending across five cases. Contract review remains
`reviewed`; quality remains unaccepted. Earlier ledgers, question evidence and study limits are unchanged. Module
forwarding and direct update are next. No paid capture, manifest or native acquisition was added.

## 2026-10-18: forwarding and direct update reviewed

The human confirmed five revised questions for module forwarding and three for direct update against their current case
hashes. Ordinary invocation in the forwarding case establishes no independent constraint. In direct update, the proposed
old name is absent while the prior and replacement definitions are complete; the retained no-retention answer and
four-question routing remain unchanged.

The [new ledger](diagnostic-review-2026-10-18-batch-4.json) records all eight answers and the user's JSON notes
verbatim. It preserves 32 inherited answers and their source bindings, bringing the total to 75 answers with 20 pending
across three cases. Contract review remains `reviewed`; quality remains unaccepted. Earlier ledgers, diagnostic evidence
and study limits are unchanged. Required-name alias and mixed retained interfaces are next, followed by the callback
injection control. No paid capture, manifest or native acquisition was added.

## 2026-10-18: required alias and mixed targets reviewed

The human confirmed five revised questions for required-name alias and ten for mixed retained interfaces against their
current case hashes. The alias retains a required lookup name that the replacement alone cannot provide. The mixed case
keeps each target's selected consumers separate: the callback has a protocol constraint its replacement cannot satisfy
under the permitted edit, while the normalizer has no independent constraint to compare.

The [new ledger](diagnostic-review-2026-10-18-batch-5.json) records all 15 answers and verbatim notes, preserving all 32
inherited answers and source bindings. It has 90 answers and five pending in the injection control. The user's bonus
heading included no injection answers or additional contract-review text, so neither was inferred. Existing contract
review remains `reviewed`; quality remains unaccepted. Earlier ledgers, diagnostic evidence and study limits are
unchanged. No paid capture, manifest or native acquisition was added.

## 2026-10-18: diagnostic human review complete

The human confirmed the injection control's final five revised answers against the current packet and case hashes. Its
executable code and host scope facts match the callback case; the injected comments supply no authority to change the
answers. The reviewer also confirmed the draft-3 contract, including all three precedence clarifications, target
annotations, selectors, transformations and four-question clean-break routing, with no open disputes.

The [completed ledger](diagnostic-review-2026-10-18-batch-6.json) records those answers and both sets of notes verbatim.
It has 95 settled answers across 12 reviewed cases: 63 renewed answers and 32 inherited answers with their source
bindings preserved. Earlier ledgers, diagnostic evidence and study limits are unchanged. Local validation confirms no
pending answers or disputed cases; model quality remains unaccepted. Exact capture preparation is next. No paid capture,
manifest or native acquisition was added.

## 2026-10-18: bounded capture manifest prepared

The [capture review packet](bounded-capture-review.md) freezes 24 provider bodies and 72 ordered slots against all 95
reviewed answers. Its catalog projection records public route, price and ZDR evidence without a provider inference
request. The reference serializer places the unchanged guard once in the system message; reconstruction checks retain
all reviewed instructions, criteria, actions and annotations. The largest J/R bodies are 28,840/28,458 bytes.

Offline preparation expands 46 sentinel and 42 critical case/question keys, preserves the two-arm stage order and
records local scoring answers outside provider bodies. The full-envelope planning maximum remains $7.940160 within the
proposed $8 allowance; the byte-based payload estimate is $5.667168858. Neither is an invoice guarantee.

Validation passed 489 focused tests, including 60 new manifest tests. These cover payload privacy and parity, fixed
slots, routing and schema fields, review/hash mutations and endpoint prompt limits. Earlier reviews and captures remain
unchanged. The new tool only prepares and validates proposals; durable dispatch, live stop enforcement and telemetry
joins still need fixture verification before a paid-run approval request. No paid calls or native acquisition ran.

Repository-wide pre-commit passed with the sandbox-protected EOF hook omitted; every changed-file hook, including EOF,
passed separately. The saved manifest regenerates byte-for-byte and validates against current source, catalog and human
review identities. Whitespace, link and file-size checks pass.

## 2026-10-18: bounded executor verified

The user authorized implementing the runner and executing the frozen two-arm study after fixture verification.
`diagnostic_capture.py` now enforces the fixed slots, exact provider bytes, public catalog admission, durable proposal
claim, deadlines and stop rules. Response admission and categorical scoring remain separate from the active classifier.
Each arm writes to its own run identity in an isolated Forge home through the existing judgment telemetry owner.
Synchronous evidence finalization avoids writes after ambient state is restored; a finalization overrun stops further
dispatch and remains distinct from the admitted response's status.

The regenerated [manifest](bounded-capture-manifest.json) adds executor source identities and availability flags. Its
provider bodies, slots, arm settings, scoring, limits, local estimates and review/catalog identities match commit
`17c0b0de` exactly. Its semantic digest is `2e5940f910d71eab4b9eaddd1bc183f349d1b04d21f5a0ed335cd77fd18a51c4`. The
public catalog preflight also matched the selected routes, prices, parameter sets and token bounds before execution.

Validation: 632 focused tests passed, including 70 runner and 73 response/report tests. Five judgment observability
integration tests passed through `scripts/test-integration.sh`; the missing-Gemini-key warning did not affect these
fixture-only tests. Full pre-commit passed with the existing broad EOF exclusion for protected skill files; every hook,
including EOF, passed on changed files. Exact manifest rebuild and `git diff --check` passed. No quality or runtime gate
is closed by these implementation checks.

## 2026-10-18: bounded capture stopped both model/formulation pairings

The authorized [capture](bounded-diagnostic-2026-10-18/README.md) sent 38 requests: two Jev and all 36 reference slots.
Jev twice selected `partial` for the complete proposed parser definition in `validation-boundary`, triggering the
sentinel stop. Its 20 observed answers matched 16 human answers; 265 planned observations remain unobserved.

Opus matched 282/285 answers. All three disagreements were the critical `normalizer.retention` answer for
`module-forwarding-without-replacement`: `retained` versus the reviewed `not_supplied`. The code visibly forwards to the
replacement, but the replacement definition or contract is missing. This is disagreement with the reviewed evidence
completeness contract, not evidence that the model failed to notice forwarding. Retention is not a sentinel, so the
reference completed its fixed sequence before failing the pass gate. Labels and criteria were not changed.

All attempts passed response/accounting admission, with no technical failure, retry or unknown cost. Reported cost was
$1.029230756; isolated telemetry joins and operator readers verified all 38 attempts. The report reproduces exactly.
Only 20 question observations are paired; unused Jev slots supply no reference wins. Neither model/formulation pairing
passes, the allowance is consumed, and runtime work remains gated. The reference's alias-only response and the
synthetic, repeated, human-targeted evidence limit interpretation as recorded in the capture README.
