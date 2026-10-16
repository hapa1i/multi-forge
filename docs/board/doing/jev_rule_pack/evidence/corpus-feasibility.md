# A2 corpus feasibility checkpoint

2026-10-16. Inventory of the existing [constructed corpus](wrapper-corpus.json), at source SHA-256
`737dc6f3e3fa7392d1d73fa3703013a37592555a2426b7d6f2a232678b585011`. No historical examples or native transcripts were
collected for this checkpoint. The counts distinguish authored fixtures and preparation results from the 17 confirmed
human adjudications.

## Evidence available

| Cohort and split        | Cases | Families | Model candidates | Host decisions | Human labels |
| ----------------------- | ----- | -------- | ---------------- | -------------- | ------------ |
| Constructed calibration | 12    | 4        | 9                | 3              | 12           |
| Constructed held-out    | 5     | 3        | 4                | 1              | 5            |
| Historical calibration  | 0     | 0        | 0                | 0              | 0            |
| Historical held-out     | 0     | 0        | 0                | 0              | 0            |

The [first 2026-10-16 ledger](human-review-2026-10-16.json) records `module-forwarding` as warning and
`module-direct-update` as no warning. The [second ledger](human-review-2026-10-16-batch-2.json) adds warning labels for
`module-injection` and `method-argument-adapter`. The [third ledger](human-review-2026-10-16-batch-3.json) records
`validation-boundary` as no warning and `validation-gratuitous` as warning. The
[fourth ledger](human-review-2026-10-16-batch-4.json) records `preview-alias` as warning and `stable-alias` as not
applicable. The [fifth ledger](human-review-2026-10-16-batch-5.json) records `preview-approved-exception` as not
applicable and `unknown-public-status` as unavailable. The [sixth ledger](human-review-2026-10-16-batch-6.json) records
`callback-protocol` as no warning and `multi-file-wrapper` as warning. The
[seventh ledger](human-review-2026-10-16-batch-7.json) records `decorator-instrumentation` as no warning and
`write-without-history` as unavailable. The [eighth ledger](human-review-2026-10-16-batch-8.json) completes held-out
review: `partial-edit` is unavailable, `return-shape-adapter` is warning and `return-shape-direct-update` is no warning.
All 17 cases are labeled across seven families. The user confirmed these judgments after AI-assisted discussion; they
are not independently blinded labels.

The six calibration warning labels span four families: `module-rename`, `argument-adaptation`, `validation-adaptation`
and `public-alias`. The three no-warning calibration labels span `module-rename`, `validation-adaptation` and
`argument-adaptation`. Held-out has one warning in `return-shape-adaptation` and two no-warning labels across
`decorator-instrumentation` and `return-shape-adaptation`. The injection, multi-file and paired return-shape variants
add no independent families.

The four host-decided cases have no question answers: two not-applicable labels and two unavailable labels review host
applicability/history, not model outcomes. Every question has nine known calibration answers. The four held-out model
candidates have four known coverage answers and three known answers for retention and boundary. `partial-edit` is
unavailable with coverage false and both remaining answers unknown; it supplies an answer object, unlike the
host-decided Write. Neither type of unavailable human label measures model abstention.

The host resolves calibration's stable surface and approved preview exception as not applicable, and its unknown surface
as unavailable. It resolves the held-out Write without prior-interface evidence as unavailable. These are
applicability/preparation results, not measured model outcomes.

The authored proposals remain separate from human adjudications and supply neither independent review evidence nor
additional positive/negative samples.

Calibration contains 11 Claude Edits and one two-file Codex patch; held-out contains four Claude Edits and one Claude
Write. All Edits use `replace_all=false`. The injection variant contains English and Japanese instructions but shares
the module-rename seed family. That single variant does not establish multilingual or injection-resistance quality. The
corpus contains method, alias, validation, callback, decorator and return-shape examples; naming those scenarios does
not establish that their proposed judgments are correct.

## Limits on a quality claim

The seven declared source families do not overlap between splits, and related module/multi-file variants remain
together. Family separation prevents that direct leakage; it does not prove independence. All examples were authored in
one assistant-created collection with common conventions. The held-out positive count is especially sparse: its one
confirmed warning is a return-shape adaptation. No observed precision, miss rate, warning burden or real-world
prevalence follows from this inventory. The revised advisory rule measures whether supplied evidence justifies a
warning; its packet labels cannot establish whether caller review would find the warning useful.

No historical positive or negative has been adjudicated. Earlier marker/delegation searches are discovery hints, not
semantic labels or evidence that all unmarked wrappers were found. They cannot fill an empty historical stratum.
Repetitions of a constructed input would measure variation, not add independent examples.

All 17 constructed cases are reviewed. This corpus cannot support a production-quality or historical-accuracy claim,
even if every constructed prediction were correct. Keep the broader wrapper family selected by the user; narrow the
evidence claim to these constructed actions until representative evidence exists. Do not treat this limitation as
permission to activate the bundle.

## Next gate

Constructed adjudication is complete, with the partial Edit's two unknown semantic answers retained. The reviewed
inventory has only one held-out positive family and no historical evidence. Either prepare a separately reviewed
acquisition scope or retain the constructed-only claim. A future acquisition plan must name the repository revision
range, reconstruction method, local data to retain and exclusions; native transcripts and provider dispatch require
their own explicit decisions. This checkpoint does not collect or authorize either.

Minimum sample counts, acceptable false-positive/miss rates, coverage and warning-rate limits remain unset. Propose
those choices against the reviewed inventory, freeze them before held-out model results, and follow the
[evaluation plan](evaluation-plan.md#before-real-evaluation-or-runtime-admission). A blank review packet, a fixture
report or a merged implementation PR does not satisfy that gate.
