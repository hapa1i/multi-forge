# Diagnostic option-precedence review

Adopted for diagnostic `draft-3` on 2026-10-18. The original [human review](diagnostic-review-2026-10-17-batch-6.json)
supports decomposition and clean-break routing while identifying choice boundaries. The changes below resolve those
boundaries in the separate diagnostic questions. The original ledger, active rule and captures remain unchanged. Revised
questions need renewed human answers; this wording decision authorizes no capture.

## Definition presence

Draft 2 describes an unattributed body fragment both as lacking an attributable definition (`not_supplied`) and as
unclear attribution (`ambiguous`). The fragment control contains only return statements. Neither identifies the
enclosing function; target hints cannot supply that identity. The reviewer explicitly selected `not_supplied` while
preserving this overlap in the notes. Those two choices remain recorded against draft 2, whose criteria did not uniquely
determine them.

Draft-3 distinctions:

- `not_supplied`: no supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: supplied code or contract provides competing or conflicting evidence about attribution or completeness.
  Merely lacking an attribution link is `not_supplied`.
- `partial`: attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `complete`: the named definition or adequate explicit interface contract is supplied in full for this comparison.

This keeps `partial` for attributable fragments. A case name containing `partial-definition` cannot determine the
answer.

## Consumer evidence

The missing-history review leaves `consumer_constraint` null because the prompt asks about "ordinary continued use of
the old interface." That wording can imply that prior history is required even when the proposed target and selected
consumer are supplied in full. The criteria do not explicitly impose that prerequisite.

Ask about the named target's selected consumers in the proposed image, without presuming the target is an old interface.
When complete history establishes no retention, keep `not_applicable`. Otherwise, require enough evidence of those
consumers and the target interface to distinguish a concrete constraint from ordinary invocation. Missing prior history
or replacement implementation alone should not block that determination. Missing relevant consumer/interface evidence
remains `not_supplied`; conflicting evidence remains `ambiguous`. This clarification does not fill the user's pending
review field.

## Replacement sufficiency

Draft 2 says both to choose `not_applicable` before comparing implementations when complete evidence establishes no
independent constraint, and to use `not_supplied` for missing structural evidence. It does not specify which structural
facts this comparison needs. Requiring every definition would combine the separate completeness questions with a
question about present consumer requirements.

The [decomposition proposal](decomposition-diagnostic-proposal.md#proposed-diagnostic-layers) makes the replacement
comparison inapplicable when no requirement has been identified. Preserve that separation with explicit precedence:

1. If complete supplied history establishes no retained interface, use `not_applicable`.
2. Otherwise, determine the selected consumer requirement from the supplied evidence. Missing evidence needed for that
   determination yields `not_supplied`; conflicting or materially unclear evidence yields `ambiguous`.
3. If complete evidence relevant to those selected consumers establishes no independent constraint, use
   `not_applicable`. Replacement behavior does not need comparing in this branch.
4. If an independent constraint is established, require enough replacement and binding evidence to compare it under the
   permitted wiring edit. Missing comparison evidence yields `not_supplied`, conflicting evidence yields `ambiguous`,
   and a supported comparison yields `satisfies` or `does_not_satisfy`.

These branches derive from supplied evidence, not another model answer. Missing prior history alone does not prevent a
question about current consumer requirements. Missing replacement evidence matters when an established requirement needs
comparison. The separate structural and retention answers still record those gaps; `not_applicable` on this one question
does not establish coverage or admit a policy warning.

## Review and version boundary

These are adopted diagnostic criteria, not human labels for the unsettled answers in the missing-history and
missing-replacement controls. All 12 draft-2 cases were reviewed; the original ledger has 92 recorded answers, including
the two presence choices with the overlap caveat, and three null answers. Its `contract_review.status` is `reviewed`
with the original two issues recorded, and the missing-history case adds the consumer wording concern; that status does
not mean the packet is complete, quality is accepted or an experiment is approved.

Draft 3 regenerates identities and reopens review of changed questions and the overall contract. The explicit carry
command retains 32 retention, fact and transformation answers with unchanged complete question context and original
attribution. It reopens 60 recorded answers; together with the three original nulls, 63 questions need human review in
the [carried ledger](diagnostic-review-2026-10-18-carried.json). No new human answer is inferred from this change. The
original draft-2 ledger and its compact batch history remain intact. The active three-question contract and its prior
captures remain unchanged. The [bounded plan](bounded-feasibility-plan.md) owns the next experiment proposal; reviewing
wording does not approve that plan or provider spending.
