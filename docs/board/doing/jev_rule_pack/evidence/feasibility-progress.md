# A2 feasibility progress

2026-10-17 continuation from PR #272 (`64317485`). The 17 constructed human judgments and semantic criteria are
unchanged. This checkpoint records preparation, an acquisition shortfall and two synthetic captures; it does not
establish runtime feasibility.

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

The [diagnostic packet](diagnostic-human-review.md) now contains 12 synthetic cases and 95 unanswered Choice questions.
It preserves the six original action inputs and adds six controls, including a two-target action and matched missing
evidence. Target hints, selector bindings and exact transformations are hash-bound and await human review. The offline
validator reports partial answers and contract status without importing labels or accepting quality. No diagnostic
capture manifest or provider run is included.

The walkthrough exposed ambiguous direct-replacement and completeness wording. Diagnostic `draft-2` permits only the
named registration edit for the selected target, preserves required lookup names, and distinguishes attributable
fragments from absent or ambiguously attributed evidence. The packet and all worksheets are regenerated with new
identities. All 95 answers and contract review remain pending; the user's agreement on the interpretation is not
imported as labels. Action evidence, transformations, active rule criteria and existing adjudications are unchanged.

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
