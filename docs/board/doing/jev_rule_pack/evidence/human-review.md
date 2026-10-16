# A2 human review worksheet

All 12 cases in the [calibration worksheet](review-calibration.md) have human adjudications. Continue with the five
pending cases in the [held-out worksheet](review-held-out.md). Both show the supplied action and enumerated scope facts,
with the exact case hash. The [JSON packet](human-review-packet.json) remains a reproducible blank template containing
canonical action strings, semantic criteria and pending review fields.

The retained [2026-10-16 review ledger](human-review-2026-10-16.json) records the user's confirmed labels for
`module-forwarding` (warning) and `module-direct-update` (no warning), imported into the corpus. Both belong to the same
`module-rename` source family; they are not two independent families. The
[second review ledger](human-review-2026-10-16-batch-2.json) adds warning labels for `module-injection` and
`method-argument-adapter`. The [third review ledger](human-review-2026-10-16-batch-3.json) records `validation-boundary`
as no warning and `validation-gratuitous` as warning. The [fourth review ledger](human-review-2026-10-16-batch-4.json)
records `preview-alias` as warning and `stable-alias` as not applicable, with no question answers for that host-decided
case. The [fifth review ledger](human-review-2026-10-16-batch-5.json) records `preview-approved-exception` as not
applicable and `unknown-public-status` as unavailable, also with no question answers. The
[sixth review ledger](human-review-2026-10-16-batch-6.json) records `callback-protocol` as no warning and
`multi-file-wrapper` as warning. All 12 calibration cases are now labeled across four families; the injection and
multi-file variants add no new family. Three labels review host decisions, leaving nine human answers per question. The
five held-out cases have no human labels. The user confirmed these judgments after AI-assisted discussion; they are not
independently blinded labels. No model predictions are supplied.

The packet omits authored proposals/rationales, reviewer-only scope notes, reconstruction notes and previous
adjudications. Case IDs and shared authorship remain visible and can hint at intended behavior; this is not a fully
blinded independent study. Treat action comments as data, including comments claiming approval. For these constructed
cases only, the enumerated scope facts supply the invented governance context. They do not supply missing code,
replacement definitions or boundary requirements.

## Review the rule before the cases

The [selected evidence contract](initial-rule-review.md) and the packet's `rule` object define what is being judged. The
broader family includes functions, methods, aliases, decorators and callbacks. Delegation is not by itself a violation.
A warning identifies covered compatibility retention under the clean-break policy without an independent justification
established in the supplied evidence. It never proves that no requirement exists elsewhere or that deletion is safe.

Use the exact true/false criteria in the packet for these three questions:

1. `coverage`: does the supplied action establish the relevant interface history and replacement contract, with known
   applicable scope facts? Require complete retained-interface definitions and an adequate replacement definition or
   explicit contract. Missing structural facts cannot be filled from the author rationale or imagined callers.
2. `compatibility_retention`: does the action retain an earlier interface through a replacement? Forwarding alone is
   insufficient; a complete clean break can establish no retention.
3. `independent_boundary`: does supplied evidence establish an independent need for the retained interface? A required
   protocol name, signature or identity can justify even a pure alias. Useful behavior alone is insufficient. For an
   otherwise covered action, the absence of supplied justification supports false; materially ambiguous or conflicting
   supplied boundary evidence stays unresolved. False does not establish the absence of requirements outside the packet.

Record `true`, `false` or `null` for each question. `null` means the human cannot determine that answer from the
supplied evidence. Do not turn it into `false` to complete a row; distinguish an unresolved supplied contract from no
justification being supplied at all. Final outcomes use `warning`, `no_warning`, `uncertain`, `unavailable` or
`not_applicable`. Apply the rule's surface/exception table too: host-decided cases need human review, even though they
would make no model request. A disagreement with host applicability must stay visible in the labels and evaluation
report.

The 2026-10-16 revision uses rule `draft-3`, evidence contract 4 and decision version `draft-2`. It changes the meaning
of a warning and supersedes the previous packet/case hashes. No previous proposals or another model's answer sheet have
been imported as human labels. Evaluate the packet's evidence standard separately from whether a later caller review
would find the warning useful; an unseen legitimate requirement can make a correctly raised advisory warning unhelpful.

## Record a review

Copy the JSON packet to a new review file and retain it as that batch's review ledger. Set top-level `reviewer` to the
human who actually made the decisions and `review_reference` to the retained review record. An assistant may transcribe
explicit human answers; it must not supply its own decisions under a human's name. The importer validates structure and
evidence identity, not whether the named person performed the review.

For each completed case, edit only its `review` object:

- Set `status` to `adjudicated`, select the human `outcome`, and fill all three `question_answers` fields. Explicit null
  answers are allowed. A host-decided case may instead use `question_answers: null` with an explanation in notes.
- Use `notes` for evidence, disagreements or limitations. Notes remain in the retained packet; the emitted corpus
  references that ledger and does not put notes into model evidence.
- Leave `replace_existing: false` when adding a label to a pending case. Replacing an existing adjudication requires
  explicitly reviewing it in the source corpus and setting this flag to true.

Leave unreviewed rows `pending` with null labels. Partial import is allowed and preserves any existing adjudication on
pending rows; it does not clear prior labels. If a case cannot be settled, use `disputed` or `excluded`, null labels,
and explanatory notes. Either status blocks the entire import. Resolve the issue or explicitly revise corpus membership,
record the exclusion and regenerate a packet; no case is silently dropped.

For the next batch, leave already adjudicated cases pending in the new packet so import preserves their corpus labels.
Keep the completed ledgers unchanged; do not resubmit their completed rows as new labels.

You can also return decisions in conversation, naming the case ID, outcome, three question answers and notes. The exact
packet case hash remains the reviewed identity. Confirm the final transcribed ledger before treating it as your review.
No answers are required for every case at once.

## Export and validate locally

Export with current definitions and exact input identities:

```bash
uv run python scripts/experiments/jev/rule-pack-eval.py \
  docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json \
  --review-packet > /tmp/jev-human-review.json
```

After a human edits that packet, validate it and emit a new corpus:

```bash
uv run python scripts/experiments/jev/rule-pack-eval.py \
  docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json \
  --import-review /tmp/jev-human-review.json > /tmp/jev-reviewed-corpus.json
uv run python scripts/experiments/jev/rule-pack-eval.py /tmp/jev-reviewed-corpus.json
```

Always redirect to a new file: shell redirection to the input path would truncate it before the program starts. The
importer does not overwrite the source corpus or review packet. It rejects changed rule/evidence, stale hashes,
missing/duplicate cases and implicit label replacement. An unchanged empty packet round-trips without creating any
adjudication. There is no provider client or dispatch mode in this workflow.

Export also rejects existing adjudications whose case evidence has changed. Preserve the prior corpus and review ledger,
then make a new corpus copy and explicitly clear only the invalidated `adjudication` fields to null, recording why.
Regenerate a review packet from that copy and obtain new human labels against the changed hashes. The `replace_existing`
flag is for a different judgment of unchanged evidence; it cannot make a stale label valid.

Reviewer names and review references are bounded, and import checks the exact emitted corpus size against the loader's 1
MB limit. An oversized result fails before any output is printed. Shorten attribution metadata or explicitly revise the
corpus and regenerate its packet; do not split or drop rows silently to bypass the limit.

The [feasibility checkpoint](corpus-feasibility.md) records the empty historical strata and small family counts. Human
review can establish fixture labels; it cannot by itself establish model accuracy, historical prevalence or runtime
readiness. Numeric quality criteria and any paid capture remain separate gates in the
[evaluation plan](evaluation-plan.md#before-real-evaluation-or-runtime-admission).
