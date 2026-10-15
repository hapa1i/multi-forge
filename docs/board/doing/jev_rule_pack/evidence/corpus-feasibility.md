# A2 corpus feasibility checkpoint

2026-10-15. Inventory of the existing [constructed corpus](wrapper-corpus.json), at source SHA-256
`a2e3f931a17b400f0f4422bd329ca793ebe6916e5b437083c1ae6a9c280c018d`. No historical examples or native transcripts were
collected for this checkpoint. Counts describe the authored fixtures, not independently established semantic truth.

## Evidence available

| Cohort and split        | Cases | Families | Model candidates | Host decisions | Human labels |
| ----------------------- | ----- | -------- | ---------------- | -------------- | ------------ |
| Constructed calibration | 12    | 4        | 9                | 3              | 0            |
| Constructed held-out    | 5     | 3        | 4                | 1              | 0            |
| Historical calibration  | 0     | 0        | 0                | 0              | 0            |
| Historical held-out     | 0     | 0        | 0                | 0              | 0            |

All three questions have zero human answers in both splits. The host resolves calibration's stable surface and approved
preview exception as not applicable, and its unknown surface as unavailable. It resolves the held-out Write without
prior-interface evidence as unavailable. These are applicability/preparation results, not measured model outcomes.

For corpus planning only, the authored proposals contain six warnings in four calibration families and one warning in
one held-out family. Proposed no-warning examples span three calibration families and two held-out families. The
remaining model-candidate proposal is an unavailable held-out partial Edit. These proposals must not populate a review
packet's human labels or establish a positive/negative sample count.

Calibration contains 11 Claude Edits and one two-file Codex patch; held-out contains four Claude Edits and one Claude
Write. All Edits use `replace_all=false`. The injection variant contains English and Japanese instructions but shares
the module-rename seed family. That single variant does not establish multilingual or injection-resistance quality. The
corpus contains method, alias, validation, callback, decorator and return-shape examples; naming those scenarios does
not establish that their proposed judgments are correct.

## Limits on a quality claim

The seven declared source families do not overlap between splits, and related module/multi-file variants remain
together. Family separation prevents that direct leakage; it does not prove independence. All examples were authored in
one assistant-created collection with common conventions. The held-out candidate-positive count is especially sparse:
its one proposed warning is a return-shape adaptation. No observed precision, miss rate, warning burden or real-world
prevalence follows from this inventory.

No historical positive or negative has been adjudicated. Earlier marker/delegation searches are discovery hints, not
semantic labels or evidence that all unmarked wrappers were found. They cannot fill an empty historical stratum.
Repetitions of a constructed input would measure variation, not add independent examples.

The present corpus can support reviewed behavioral fixtures once a human resolves its labels. It cannot support a
production-quality or historical-accuracy claim, even if every constructed prediction were correct. Keep the broader
wrapper family selected by the user; narrow the evidence claim to these constructed actions until representative
evidence exists. Do not treat this limitation as permission to activate the bundle.

## Next gate

Use the blind [human review worksheet](human-review.md) to adjudicate exact case hashes, including host-decided cases.
Record per-question answers, uncertainty and disagreements before inspecting predictions. An unresolved disagreement or
proposed exclusion remains visible and blocks importing that packet; revising membership requires a new packet and
explicit accounting for the excluded cases.

After adjudication, recount positive/negative families in each split. If independent historical evidence is still
absent, either prepare a separately reviewed acquisition scope or retain the constructed-only claim. A future
acquisition plan must name the repository revision range, reconstruction method, local data to retain and exclusions;
native transcripts and provider dispatch require their own explicit decisions. This checkpoint does not collect or
authorize either.

Minimum sample counts, acceptable false-positive/miss rates, coverage and warning-rate limits remain unset. Propose
those choices against the reviewed inventory, freeze them before held-out model results, and follow the
[evaluation plan](evaluation-plan.md#before-real-evaluation-or-runtime-admission). A blank review packet, a fixture
report or a merged implementation PR does not satisfy that gate.
