# A2 diagnostic human review

Review whether the proposed questions isolate code facts, consumer constraints and concrete transformations. This is a
separate `draft-2` diagnostic contract, following the [decomposition proposal](decomposition-diagnostic-proposal.md).
The active rule, its 17 human labels and both captures remain unchanged. No provider call or runtime admission is part
of this packet.

The [blank JSON packet](diagnostic-review-packet.json) contains the exact evidence, lookup annotations, transformations,
questions and pending fields. Each worksheet below renders one case. There are six original calibration actions and six
new controls; all source actions are synthetic. No held-out case, native session content or repository history is added.
Case names, shared authorship and prior discussion can reveal intended contrasts; this is not blinded independent
review.

The [latest partial ledger](diagnostic-review-2026-10-17-batch-6.json) records 92 answers across all 12 reviewed cases
and preserves the [previous ledger](diagnostic-review-2026-10-17-batch-5.json). Three answers remain null: the
missing-history control's consumer constraint and replacement sufficiency, and the missing-replacement control's
replacement sufficiency. The fragment review explicitly selects `not_supplied` but flags overlapping criteria for two
presence answers. The contract is `reviewed` with unresolved
[option-precedence concerns](diagnostic-option-precedence.md); this is not a completed or accepted-quality packet. The
blank packet and worksheets remain unchanged for further review.

## Start with the validation pair

Read [validation-boundary](diagnostic-review/validation-boundary.md) and
[validation-gratuitous](diagnostic-review/validation-gratuitous.md) first. Review the criteria and target annotations
before selecting answers. The requirement question asks whether a consumer imposes a constraint; it does not ask whether
that constraint already justifies keeping the wrapper. The replacement question then asks whether the replacement
satisfies that same constraint. Transformations ask about exact supplied code changes, not an unrestricted redesign.

For `replacement_satisfies`, the validation cases explicitly permit the callable-argument edit in
`register-replacement`: pass `decode_json` instead of `parse_document` to `InputCommand`. Consumer behavior and tests
stay fixed. Each permitted registration edit is bound to its own target; unrelated transformation observations add no
boundary evidence. Required lookup names and keys cannot be rewritten, so the alias control still requires
`export_model`. Where complete evidence shows no independent constraint, the answer is `not_applicable`; missing
structural evidence remains `not_supplied`.

| Review group       | Cases                                                                                                                                              |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Consumer contracts | [callback](diagnostic-review/callback-protocol.md), [method adapter](diagnostic-review/method-argument-adapter.md)                                 |
| Retention          | [forwarding](diagnostic-review/module-forwarding.md), [direct update](diagnostic-review/module-direct-update.md)                                   |
| Required identity  | [registered alias](diagnostic-review/required-name-alias.md)                                                                                       |
| Target attribution | [two retained interfaces](diagnostic-review/mixed-retained-interfaces.md)                                                                          |
| Missing evidence   | [prior history](diagnostic-review/module-forwarding-without-history.md), [replacement](diagnostic-review/module-forwarding-without-replacement.md) |
| Partial evidence   | [definition fragment](diagnostic-review/module-forwarding-partial-definition.md)                                                                   |
| Instruction guard  | [callback comments](diagnostic-review/callback-protocol-injection.md)                                                                              |

`module-direct-update` has structural and retention questions only. Review this routing explicitly: a complete clean
break does not need a fictional retained target or consumer comparison. The incomplete controls deliberately remove
evidence from `module-forwarding`; the empty before-image and body-only fragments are diagnostic mutations, not claims
about runtime-admitted tool calls. An absent named definition differs from a supplied but incomplete definition. In a
complete clean break, the proposed old name can be absent while the before/after history is still complete; do not turn
that absence into a missing-history judgment.

`partial` requires an attributable definition fragment with required portions missing and no adequate explicit contract
filling the gap. `not_supplied` means neither an attributable fragment nor an adequate contract is present. `ambiguous`
covers unresolved attribution or completeness. A case name or target hint cannot establish that a bare return line
belongs to the named function. The later fragment control still needs human review on that point.

Targets, selectors and source anchors are assistant-prepared lookup hints awaiting human review. They do not assert that
a named symbol or requirement exists. The original actions are preserved, including definitions that do not match the
requested lookup. Questions combined for one target must concern that target's selected consumers; a second wrapper's
contract cannot justify the first one. The mixed action joins `argument-adaptation` and `module-rename`, and all their
variants remain dependent examples rather than independent families.

## What to decide

1. Review the contract: whether these questions, criteria, target hints and no-retention routing are appropriate. Record
   agreement or a dispute in the packet's `contract_review` status and notes. A successful local validation does not
   approve the contract.
2. Review each case's full before/after action, host scope facts, target anchors and exact transformations. Flag an
   incorrect annotation rather than answering a different implied question. `selector_id` names a group of supplied
   consumers; it is not a declaration of an independent requirement.
3. Answer the listed question IDs using their exact option keys. `not_supplied`, `ambiguous` and `not_applicable` have
   different criteria. A JSON `null` means the human has not settled the answer; do not convert it to a negative.

The method's historical call-shape transformation is a mechanical diagnostic. Its invocation and fixed string-returning
path are explicitly supplied probe inputs, not evidence of a current consumer requirement. Other transformations name
supplied tests or explicit observations. Predicting that a transformation breaks a contract can be the correct answer.
Local executable checks support reproducibility of these examples; their results are withheld from the packet and are
not human adjudications.

The annotations supply a selection advantage that a runtime hook does not yet have. Even correct diagnostic answers
would not establish automatic target selection, representative-action coverage or useful policy warnings.

## Record answers

Copy the JSON template to a new ledger alongside it. Set `reviewer` to the human who makes the judgments and
`review_reference` to that ledger's relative path, such as `diagnostic-review-2026-10-17.json`. These fields record
attribution; the validator cannot authenticate the reviewer or determine whether an answer came from a human.

Edit only top-level `reviewer`, `review_reference`, `contract_review`, and each case's `review` object. Set a case
status to `reviewed`, fill the settled entries in `answers`, and explain evidence or unresolved answers in `notes`.
Partial answers may remain null. Leave untouched cases `pending` with null answers. Mark a problem `disputed`, with
explanatory notes and null answers, so it remains visible. Retain every case; no import into the active corpus is
implemented.

You can instead return answers in conversation, naming the case ID and hash, question IDs, option keys and notes. An
assistant may transcribe explicit human decisions into a new ledger; it must not supply its own answers under the
human's name. No case needs to be completed just to fill the packet.

## Offline commands

Regenerate the JSON template without accessing credentials:

```bash
uv run python scripts/experiments/jev/rule-pack-diagnostic.py > /tmp/jev-diagnostic-review.json
```

Render one worksheet:

```bash
uv run python scripts/experiments/jev/rule-pack-diagnostic.py --case validation-boundary \
  > /tmp/jev-diagnostic-validation.md
```

Validate a retained partial ledger:

```bash
uv run python scripts/experiments/jev/rule-pack-diagnostic.py \
  --validate-review /tmp/jev-diagnostic-completed.json
```

Validation compares exact evidence, annotations, criteria, transformations and membership with a newly generated packet,
then reports case status, fully answered cases, answered/unanswered questions and contract status. A case marked
`reviewed` may still have unresolved questions; that status does not mean all its answers are complete. Changing
immutable material requires regeneration and new review; old labels are not migrated. `quality_accepted` remains false
even for a completed ledger. The script has no provider, capture, scoring or active-corpus import command. Human review
precedes any separate paid-run proposal.
