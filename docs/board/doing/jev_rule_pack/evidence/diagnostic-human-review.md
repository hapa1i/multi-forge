# A2 diagnostic human review

Review whether the proposed questions isolate code facts, consumer constraints and concrete transformations. This is a
separate `draft-3` diagnostic contract, following the [decomposition proposal](decomposition-diagnostic-proposal.md).
The active rule, its 17 human labels and both captures remain unchanged. No provider call or runtime admission is part
of this packet.

The [blank JSON packet](diagnostic-review-packet.json) contains the exact evidence, lookup annotations, transformations,
questions and pending fields. Each worksheet below renders one case. There are six original calibration actions and six
new controls; all source actions are synthetic. No held-out case, native session content or repository history is added.
Case names, shared authorship and prior discussion can reveal intended contrasts; this is not blinded independent
review.

The [completed draft-3 ledger](diagnostic-review-2026-10-18-batch-6.json) has **all 95 answers settled across 12
cases**. The human confirmed 63 revised answers; 32 unchanged answers retain their original source bindings. The
reviewer also confirmed the three [precedence clarifications](diagnostic-option-precedence.md), target annotations,
selectors, transformations and four-question clean-break routing. Contract review is `reviewed`, with no open disputes.
This completes human review; it does not accept model quality or admit runtime use. The initial
[carried ledger](diagnostic-review-2026-10-18-carried.json) remains unchanged with its original 32 answers and 63 nulls.

The unchanged [draft-2 source ledger](diagnostic-review-2026-10-17-batch-6.json) preserves all 92 original answers,
three nulls, notes and caveats. Its [compact history](diagnostic-review-history.json) reconstructs all six original
batches. It is historical evidence, not a valid completed review of draft 3. Carry receipts retain its attribution and
notes; do not edit that source file. Blank worksheets show pending placeholders for every question; use the latest
ledger for the completed judgments and their provenance.

The changed fields are each target's three `*_definition` questions, plus `consumer_constraint` and
`replacement_satisfies` where present. Retention, literal-fact and exact-transformation answers carry unchanged. Review
the new criteria against the evidence; the original answers in receipts are provenance, not suggested replacements.

The human-review prerequisite in the [bounded feasibility plan](bounded-feasibility-plan.md) is now satisfied. Preparing
the exact capture manifest is next; provider spending still requires separate approval.

## Reading the validation pair

Read [validation-boundary](diagnostic-review/validation-boundary.md) and
[validation-gratuitous](diagnostic-review/validation-gratuitous.md) together. Review the criteria and target annotations
before selecting answers. The requirement question asks whether a consumer imposes a constraint; it does not ask whether
that constraint already justifies keeping the wrapper. The replacement question then asks whether the replacement
satisfies that same constraint. Transformations ask about exact supplied code changes, not an unrestricted redesign.

For `replacement_satisfies`, the validation cases explicitly permit the callable-argument edit in
`register-replacement`: pass `decode_json` instead of `parse_document` to `InputCommand`. Consumer behavior and tests
stay fixed. Each permitted registration edit is bound to its own target; unrelated transformation observations add no
boundary evidence. Required lookup names and keys cannot be rewritten, so the alias control still requires
`export_model`. Apply the branches in order: complete history proving no retention makes the comparison
`not_applicable`; otherwise establish whether the selected consumers impose a constraint. Missing or conflicting
consumer/interface evidence stays `not_supplied` or `ambiguous`. Complete relevant evidence showing no constraint makes
the comparison `not_applicable` without requiring replacement behavior. An established constraint requires enough
replacement and binding evidence for comparison. Missing history alone does not block a current-consumer question;
missing replacement evidence matters only when there is a constraint to compare. These answers do not establish overall
coverage or admit a warning.

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
filling the gap. `not_supplied` includes an unattributed body fragment or a call with no definition/contract for the
named symbol. `ambiguous` requires competing or conflicting supplied evidence about attribution or completeness; a
missing attribution link alone is `not_supplied`. Case names and target hints cannot attribute a bare return line. The
original fragment answers keep their historical caveat; the current ledger records renewed review of the changed
criteria.

Targets, selectors and source anchors are assistant-prepared lookup hints reviewed in the current ledger. They do not
assert that a named symbol or requirement exists. The original actions are preserved, including definitions that do not
match the requested lookup. Questions combined for one target must concern that target's selected consumers; a second
wrapper's contract cannot justify the first one. The mixed action joins `argument-adaptation` and `module-rename`, and
all their variants remain dependent examples rather than independent families.

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
`review_reference` to that ledger's relative path, such as `diagnostic-review-next.json`. These fields record
attribution; the validator cannot authenticate the reviewer or determine whether an answer came from a human.

For a fresh packet, edit only top-level `reviewer`, `review_reference`, `contract_review`, and each case's `review`
object. Set a case status to `reviewed`, fill the settled entries in `answers`, and explain evidence or unresolved
answers in `notes`. Partial answers may remain null. Leave untouched cases `pending` with null answers. Mark a problem
`disputed`, with explanatory notes and null answers, so it remains visible. Retain every case; no import into the active
corpus is implemented.

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

Repository worksheets use the pinned Markdown formatter and plugins in `.pre-commit-config.yaml`. When regenerating a
tracked worksheet, format it with the configured hook before comparing bytes:

```bash
uv run pre-commit run mdformat --files \
  docs/board/doing/jev_rule_pack/evidence/diagnostic-review/validation-boundary.md
```

Validate a retained partial ledger:

```bash
uv run python scripts/experiments/jev/rule-pack-diagnostic.py \
  --validate-review /tmp/jev-diagnostic-completed.json
```

Validation checks the ledger's own identities and compares diagnostic evidence, annotations, criteria, transformations
and membership with the current packet. Active-rule references and source-case hashes are provenance, so an unrelated
active prompt change does not invalidate diagnostic answers. A case marked `reviewed` may still have unresolved
questions.

When diagnostic wording or evidence changes, explicitly prepare a new partial ledger:

```bash
uv run python scripts/experiments/jev/rule-pack-diagnostic.py \
  --carry-review docs/board/doing/jev_rule_pack/evidence/diagnostic-review-2026-10-17-batch-6.json \
  > /tmp/jev-diagnostic-carried.json
```

Only answers with unchanged question context carry forward. That context binds supplied action and scope facts, the
instruction guard, targets/selectors, transformations/observations, and the question's instructions and criteria.
Changed answers return to null; changed overall semantics or routing also reopens contract review. Source attribution
and notes remain available in the carry receipt, which records reuse rather than a new human judgment. Preserve the
source ledger. Review the emitted packet before recording new judgments and set its `review_reference` to the new
ledger's relative path.

Partially reused cases have status `carried`; their original notes live in the referenced receipt. After a human reviews
the revised case, set status `reviewed`, record that person's notes and attribution, and clear `review_source` for that
case. If the human corrects a previously carried answer, also remove its `answer_sources` entry; keep bindings for
unchanged inherited answers. A new overall contract review clears `contract_review_source`. Remove a receipt from
`review_sources` only when no answer, case or contract still references it. These explicit changes distinguish new human
judgments from reused ones; they do not authorize changing question evidence or criteria.

`quality_accepted` remains false even for a completed ledger. The script has no provider, capture, scoring or
active-corpus import command. Human review precedes any separate paid-run proposal.
