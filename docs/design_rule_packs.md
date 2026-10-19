# Rule-pack design

Normative ownership for the implemented rule-pack foundations. Policy engine composition remains in
[workflow design](design_workflows.md); this foundation does not add a runnable policy bundle.

The [Jev epic](board/retired/epic_jev_support/card.md), [A2](board/retired/jev_rule_pack/card.md) and
[A3](board/retired/jev_cascade/card.md) were cancelled and retired on 2026-10-19 with no replacement. Their tools and
evidence remain available for offline inspection. A1's client remains shipped; no warning policy or review-skipping
cascade was activated. Reconsideration requires a new proposed card rather than resuming the retired plans.

## Evaluation foundations

`policy/rule_pack/definitions.py` owns the provisional compatibility-wrapper rule, applicability table and three atomic
Noul questions. `outcomes.py` applies that host applicability table and owns fixed diagnostics for every host and model
outcome. It requires explicit per-question threshold bands and composes covered answers into warning, no-warning,
uncertain or unavailable assessments with fixed diagnostics. Contradictory answers remain uncertain; missing coverage
cannot establish compliance. These modules do not register or activate a bundle and do not dispatch requests.

The provisional warning contract is advisory: complete supplied interface history and replacement evidence establish
retention, but the supplied action does not establish an independent justification for keeping that interface. No
repository-wide proof of absence is required. A named protocol, signature or callable identity can justify a pure alias;
extra behavior alone does not. Missing structural/policy evidence remains unavailable, and materially ambiguous or
conflicting supplied boundary evidence remains uncertain. Warnings ask for caller and compatibility review rather than
claiming deletion is safe. Packet-label accuracy and practical warning usefulness are separate evaluation claims.

The development harness `scripts/experiments/jev/rule-pack-eval.py` prepares bounded inputs or evaluates saved responses
offline. Corpus/split, semantic evidence, prompt, prediction, settings and adjudication identities remain distinct.
Reports compare host decisions with human labels, separate source cohorts and repetitions, preserve abstentions and
unknown costs, and use only human adjudications for error/calibration metrics. Fixture reports cannot establish rule
quality; no release verdict is implemented. A2 retired without selecting thresholds or admitting runtime use; its
unfinished calibration, data and acceptance plans are historical references, not runtime contracts. Session consent is
described in [session design](design_sessions.md).

The same harness exports human-review packets containing rule criteria and exact case evidence while withholding
proposals, reviewer-only notes and existing labels. Import verifies contract, membership and content identity before
emitting a new corpus. Pending rows preserve prior adjudications; replacements are explicit. Disputed/excluded rows
block import instead of silently removing cases. The retained packet owns review notes, referenced by each imported
adjudication. Review references are paths relative to the retained corpus directory; keep the corpus and ledgers
together when relocating evidence. The importer stores the reference without opening or hashing that file, so retain the
reviewed Git revision to identify ledger contents. Named reviewers are provenance supplied by the operator, not
authenticated identities. This workflow cannot establish that a human performed the review or turn fixture proposals
into quality evidence.

`scripts/experiments/jev/rule-pack-baselines.py` shares the evaluator's action admission and compares existing marker
patterns with bounded Python AST retention signals. A candidate is a structural observation, not a warning or evidence
that no independent boundary exists. Unsupported shapes remain explicit, and no repository reads supplement an action.

`scripts/experiments/jev/rule-pack-offline.py` compares that unchanged baseline on the fixed diagnostic review and
constructed corpus. It records host applicability, raw candidates, syntax spans and differences from human-selected
targets with input/source identities. It does not implement evidence admission, infer semantic completeness from syntax,
score candidate quality or change reviewed labels. The shared rule's coverage requirement remains authoritative for
offline assessments.

`scripts/experiments/jev/rule-pack-capture.py` prepares the fixed constructed-calibration manifest. Its separately
authorized live mode uses A1's credential/client owner with mandatory ZDR, one attempt per case, exact wire-payload
checks and a physical request cap. It isolates Forge telemetry, records interrupted attempts before dispatch and exports
the evaluator's saved-response schema. A proposal identity survives implementation-only changes; any dispatch recorded
for it in retained A2 journals prevents replay before credentials are read. A deliberately repeated proposal needs a new
identity and separate approval. This local guard does not track unretained or concurrent runs. Journals record the Git
revision and dirty state alongside authoritative source-byte digests. A changed manifest or implementation requires
renewed review; this experiment does not implement runtime admission or authorize later held-out captures.

`scripts/experiments/jev/rule-pack-inventory.py` owns the bounded development-only metadata inventory. It reads the
approved default stores directly without invoking session repair, retains only allowlisted metadata privately and checks
selected source paths without replacement scans. Its separate availability-first mode checks at most the same 24 recency
candidates' confirmed paths before allocating three slots per runtime; the original mode allocates slots first. Both
retain selection and exclusions privately without extracting native actions or establishing governance, semantic
coverage or usefulness. Runtime evidence acquisition remains separate.

`scripts/experiments/jev/rule-pack-source-audit.py` audits the frozen availability selection under a separate content
scope. It checks active state and stable bounded sources, then counts allowlisted Claude identity, timestamp, record,
stop-reason and tool-name fields. Raw identities and source hashes stay private; no message text or tool arguments are
retained. This is a schema audit, not a completed-turn validator or action extractor, and it admits no native actions.

`scripts/experiments/jev/rule-pack-diagnostic.py` prepares a separate versioned human-review packet and renders exact
synthetic evidence, reviewable target hints and proposed transformations. Its development-only `diagnostic_review.py`
helper owns semantic identities, source receipts, validation and explicit answer carry-forward. It validates partial
review ledgers against the current packet without importing labels into the wrapper corpus. Diagnostic semantic
identities exclude shared-rule provenance but bind supplied evidence, scope facts, guard, targets, transformations and
question text. An explicit carry-forward command reuses unchanged question reviews, retains source attribution and
reopens changed answers and overall contract review when needed. It validates retained schema-1 ledgers without
rewriting their human evidence. Diagnostic answers remain distinct from policy outcomes; this tool has no provider
dispatch or quality-scoring mode. Target selection and new predicates require human review, and successful diagnostic
reasoning would not establish runtime evidence acquisition.

`scripts/experiments/jev/diagnostic_manifest.py` prepares and validates a bounded two-model diagnostic proposal from a
completed review and a frozen public catalog. It owns provider-envelope formatting, exact wire identities, the fixed
request sequence and expanded scoring/stop keys. Human answers remain local scoring data. The reference envelope places
the unchanged shared instruction guard once in its system message; reconstruction checks preserve each reviewed
question's full meaning. This tool has no credentials, network or live mode; a manifest cannot grant paid approval.

`diagnostic_capture.py` executes a separately authorized manifest through injected or live HTTP transports.
`capture_io.py` owns private output, durable slot reservations, proposal claims and public catalog refresh.
`capture_evidence.py` reads embedded manifests or bounded, hash-verified local publication references for both capture
replay guards. Published diagnostic receipts remain consumption evidence when the machine-local claim is absent.
`diagnostic_results.py` admits bounded responses, retains reported accounting and scores the fixed observations.
Requests use the exact frozen bodies, with no retries, resumption or replacement slots. Technical failures stop both
arms; two wrong observations on the same sentinel stop that arm. A proposal claim survives interruption and source-only
changes. Each arm has its own run identity in an isolated Forge home; existing judgment telemetry owns the v2 attempt
records. Exact decimal costs remain in the capture alongside rounded ledger amounts. Diagnostic reports never admit
model quality or runtime activation.

Diagnostic definition presence distinguishes absent attribution from competing evidence; target hints cannot supply
attribution. Consumer questions examine the proposed target and selected consumers independently of missing history.
Replacement sufficiency checks behavior only after an independent consumer constraint is established. Separate
structural and retention questions still record missing evidence, so an inapplicable comparison does not establish
coverage.

## Cascade feasibility tools

`scripts/experiments/jev/cascade-offline.py` owns A3's synthetic corpus validation, human-review packet and declared
evidence-admission report. It binds complete plan/question/action context to case identities and separates authored
metadata from human confirmation. Missing mappings, unsupported actions and non-current authority escalate; confidence
cannot fill an evidence gap. Its prospective fixture combiner requires an explicit threshold and reviewed evidence,
preserves existing denials and unrelated review, and never uses human answer values to choose the candidate outcome.

The same script owns the bounded deterministic comparison. Four complete algorithm certificates bind the exact normative
plan and question contract. AST comparison ignores comments and local variable names; it preserves public signatures and
executable structure. Unsupported contracts or structures escalate. Parsing alone establishes no semantic coverage, and
human answer values do not choose the prediction. Reports separate host exclusions, evidence readiness, control outcomes
and human labels, with per-family and per-split counts. A capture preflight stops when a required family has no
human-positive candidate beyond the deterministic control.

This tool has no provider dispatch, native acquisition, action-code execution or runtime wiring. Reports never accept
model quality or select a threshold. Calibration scoring and automatic plan-clause discovery remain unimplemented.
Workflow design continues to own the shipped generative checker, resolver and reviewer. The
[A3 closeout](board/retired/jev_cascade/checklist.md) records the offline stop: deterministic controls cover all six
human-positive cases, leaving no incremental benefit to test on this packet. Its
[calibration procedure](board/retired/jev_cascade/evidence/calibration-procedure.md) retains the unused finite selection
proposal. Retirement cancels further work under that plan; it does not establish A3's general infeasibility.

## Consent and runtime boundary

`policy/rule_pack/consent.py` binds the paid repository-data acknowledgment to the session instance and pack settings.
Derived sessions discard the grant, and policy disable revokes both intent and override grants. See
[session design](design_sessions.md) for manifest ownership and the trusted-writer boundary.

The definitions, outcome combiner and offline harness do not resolve credentials or construct a judgment client. Saved
response evaluation uses the existing typed Decisions answer validator and never treats model output as a human label.
Threshold settings are explicit calibration inputs; accepting a settings file does not authorize runtime admission.

## Evidence and report identity

Semantic annotations bind rule/contract versions, question criteria, action bytes, enumerated scope facts and source
provenance. Reviewer notes and proposed labels stay outside model evidence. Separate hashes track prompt wording, corpus
membership/families/splits, saved observations, decision settings and human adjudications.

Corpus identity excludes case content; scored observations bind their own evidence and payload hashes. Saved manifests
declare one expected resolved model and preserve response status/size, preventing cross-snapshot pooling and admission
of responses A1 would reject. Reports also identify the evaluator and shared rule/client source bytes.

A report retains the selected source cohort and split, planned versus observed responses, per-repetition confusion
counts and abstentions, question calibration, known latency and reported cost. Host decisions never count as model
successes. Missing observations and zero-denominator rates remain explicit; repeated cases do not inflate unique case or
family counts. Nominal binomial intervals do not establish independence across shared templates or source commits.

All reports retain `quality_accepted=false`. Runtime evidence acquisition, trusted scope-fact resolution, rule
admission, hook delivery and approved quality gates are not implemented by these foundations.
