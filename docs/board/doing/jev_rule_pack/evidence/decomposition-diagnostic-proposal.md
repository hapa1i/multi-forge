# Diagnose A2 question decomposition and model fit

Proposed, 2026-10-17. Prepare a separate diagnostic experiment before rewriting the active rule or making another
wording-only capture. The [two completed captures](feasibility-progress.md#synthetic-capture-boundary) leave the current
classifier unsuitable for runtime: legal thresholds cannot recover the three human `no_warning` outcomes in the second
capture. They do not establish that Jev cannot answer simpler questions or support a different rule.

This offline proposal changes no active questions, criteria, versions, labels or settings. It contains no runnable
manifest or paid allowance. The existing broad-wrapper, supplied-evidence warning standard remains the target.

The [diagnostic review packet](diagnostic-human-review.md) contains six original calibration actions and six controls,
with separate target-bound questions. Human review has covered all 12 cases and recorded 92 answers; three remain null.
The reviewer supports the decomposition and flags [option-precedence concerns](diagnostic-option-precedence.md) to
resolve before capture.

## What needs explaining

Both runs passed transport, answer validation and snapshot checks. The model supplies no rationale. Legitimate-boundary
scores remain below the duplicated-validation negative or tied with it; this is not just a common probability offset.
Coverage also fails on complete callback and clean-break actions. All nine calibration coverage labels are true, and
retention has only one negative, so these examples cannot establish complete calibration for either question.

The runs used different prompts with one observation per case and no contemporaneous control. A1's
[measurement evidence](../../../done/jev_client_probes/evidence/2026-10-14/report.md) records answer variation for
identical payloads. The observed differences therefore do not isolate the instruction's effect or establish stability.

The boundary question combines identifying interfaces, finding requirements, comparing implementations and reasoning
about moving behavior across consumers. Decomposition may expose which step fails. It does not remove the final
counterfactual reasoning or establish a feasible way for hooks to select the relevant evidence.

## Proposed diagnostic layers

Use the existing calibration actions for `validation-boundary`, `validation-gratuitous`, `callback-protocol`,
`method-argument-adapter`, `module-forwarding` and `module-direct-update`. Keep their original action bytes and trusted
scope facts. A diagnostic packet may name exact symbols and source anchors, but must identify these as human-selected
targets, separately from the action. Do not add inferred caller history or a claimed boundary justification to the
input.

Ask bounded code-fact questions first, with explicit not-supplied and ambiguous choices where needed. For example:

- What argument does `RecordBus.publish` pass to each registered callback: a `Record`, its payload string, another
  value, or an argument the supplied evidence does not establish?
- Which exception class does `inspect_document` catch: `JSONDecodeError`, `ValueError`, another class, or a class the
  supplied evidence does not establish?
- Does the supplied `decode_json` definition perform the blank-input check before JSON decoding?
- Are the identified prior interface and proposed replacement definition or explicit interface contract complete in the
  supplied action? Check these separately; difficulty judging a boundary is not missing structural evidence.

Each exact question needs criteria that distinguish ambiguous evidence from an absent fact. Existing typed Choice
answers can retain finite alternatives; question IDs alone convey no instructions. Keep the existing instruction/data
guard, and keep human answers and rationale outside model state.

For `module-direct-update`, record that no retained interface is present and skip target-dependent comparisons as not
applicable. Its structural coverage remains a separate question. Do not invent a retained candidate or count its absence
as a failed comparison. For retained candidates, diagnose three harder comparisons:

1. **Requirement:** Does supplied contract, registration or test evidence establish a requirement beyond an ordinary
   caller continuing to use the old interface? Useful behavior or direct-substitution failure alone is insufficient.
2. **Replacement:** Does the replacement as written satisfy that same requirement? Mark this comparison not applicable
   when no requirement has been identified; missing or conflicting evidence is not a negative answer.
3. **Constrained change:** Would a specified substitution or movement of the wrapper's behavior preserve the supplied
   consumer contracts? Supply the exact proposed transformation, preserving all other code. Do not ask whether some
   unrestricted redesign could make the wrapper unnecessary.

The proposed distinctions below are reasoning hypotheses for review, **not new human labels**:

| Case                    | Requirement to examine      | Replacement as written  | Relevant other use          |
| ----------------------- | --------------------------- | ----------------------- | --------------------------- |
| validation-boundary     | Command's blank exception   | Different exception     | Inspection's JSON exception |
| validation-gratuitous   | Command's blank exception   | Already satisfies it    | Inspection catches both     |
| callback-protocol       | Bus's `Record` argument     | Expects string          | Direct string processing    |
| method-argument-adapter | None beyond old interface   | Comparison inapplicable | Migrated caller             |
| module-forwarding       | None beyond ordinary caller | Comparison inapplicable | Caller retains old name     |

The [earlier synthetic executions](boundary-question-proposal.md#what-the-first-capture-establishes) support the
validation and callback distinctions. An exact diagnostic transformation should have its own retained executable check
and human review. This makes the question testable without treating agent-generated conclusions as quality labels.

These questions are not yet a replacement outcome combiner. Requirement plus substitution failure is insufficient, as
ordinary signature adapters demonstrate. Conversely, a required name or callable identity may justify a pure alias
without a conflict between behavioral consumers. A future combiner must preserve both cases. Do not multiply the
question probabilities or assume that questions sharing state are independent.

## Attribution and coverage controls

Every answer used together must bind the same retained interface, replacement and requirement. Action-wide questions
could otherwise combine one wrapper's legitimate contract with another wrapper's mismatch. Source anchors bind supplied
text, not semantic truth; any future automatic selector needs its own supported-syntax and ambiguity rules.

Prepare these additional constructed calibration controls, with new human adjudications before model evaluation:

- A pure alias whose exact name or callable identity is required by supplied registration evidence.
- Two retained interfaces in one action: one justified and one gratuitous, to expose cross-candidate answer mixing.
- Matched complete/incomplete actions that remove prior history, replacement evidence or part of a definition. Preserve
  family identity across each mutation. Do not use the exposed held-out partial Edit for tuning.
- An instruction-injection variant of a diagnostic action. Action comments cannot establish authority or dictate
  answers.

Structural presence is only one part of coverage. Success on these checks would not prove that the broader semantic
coverage question works, nor that automatic role identification works on patches or mixed-surface actions.
Human-selected targets deliberately test reasoning after selection; report that advantage explicitly. Keep unsupported
or ambiguous automatic mappings unavailable rather than silently narrowing the rule to local helpers.

## Comparison and decision rules

Before a paid proposal, review the exact diagnostic predicates, target annotations, controls and new labels. Retain the
original adjudications under their original semantic identities. The existing runner fixes nine cases and three Noul
questions; the evaluator binds those active definitions. A diagnostic experiment needs its own versioned packet,
manifest and report contract, reusing A1's transport and answer validation without rewriting old captures.

The eventual fixed plan should pair current three-question requests with diagnostic requests for the selected original
cases, repeat identical payloads, and interleave arms in a declared order. Bind payloads, selected snapshot, code,
annotations, labels and scoring rules before dispatch. Report repetitions within cases and families, not as additional
independent examples. Keep incomplete controls separate from the original all-complete cohort. The exact request count,
cost bound and separate approval come after packet review; neither consumed nine-request allowance applies.

Use predeclared per-case distinctions to decide the next step, rather than selecting thresholds to hide difficult cases:

| Observation                                 | Next decision                                      |
| ------------------------------------------- | -------------------------------------------------- |
| Repeated errors on explicit code facts      | Stop this Jev/candidate pairing or compare a model |
| Facts right; transformation answers wrong   | Reconsider model fit for contract reasoning        |
| Facts/transformations right; boundary wrong | Review question composition and decision semantics |
| Human targets work; automatic ones fail     | Resolve evidence selection before runtime work     |
| Coverage fails on matched controls          | Resolve coverage independently of boundary scores  |
| All diagnostic distinctions hold            | Investigate further; no runtime admission          |

Here, right and wrong mean agreement with the human-reviewed fact or transformation outcome. Correctly predicting that a
substitution breaks a required contract is a successful diagnostic answer.

A model comparison should use the same reviewed evidence and observable answers, with a separately assessed latency,
cost and data contract. No alternative model is selected or shown superior by the present evidence. A diagnostic pass
would still leave representative native-action coverage, governance mapping and useful warnings unmeasured. The
[local acquisition shortfall](feasibility-progress.md#approved-local-inventory) remains an independent gate.
