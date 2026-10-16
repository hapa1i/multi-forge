# Rule-pack design

Normative ownership for the implemented rule-pack foundations. Policy engine composition remains in
[workflow design](design_workflows.md); this foundation does not add a runnable policy bundle.

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
quality; no release verdict is implemented. Calibration, data and acceptance decisions remain pending in the A2 card;
they are not runtime contracts. Session consent is described in [session design](design_sessions.md).

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

`scripts/experiments/jev/rule-pack-capture.py` prepares the fixed constructed-calibration manifest. Its separately
authorized live mode uses A1's credential/client owner with mandatory ZDR, one attempt per case, exact wire-payload
checks and a physical request cap. It isolates Forge telemetry, records interrupted attempts before dispatch and exports
the evaluator's saved-response schema. A changed manifest or implementation requires renewed review; this experiment
does not implement runtime admission or authorize later held-out captures.

`scripts/experiments/jev/rule-pack-inventory.py` owns the bounded development-only metadata inventory. It reads the
approved default stores directly without invoking session repair, retains only allowlisted metadata privately and checks
selected source paths without replacement scans. It does not extract native actions or establish governance, semantic
coverage or usefulness. Runtime evidence acquisition remains separate.

`scripts/experiments/jev/rule-pack-diagnostic.py` prepares a separate versioned human-review packet and renders exact
synthetic evidence, reviewable target hints and proposed transformations. It validates partial review ledgers against
the current packet without importing labels into the active corpus. Diagnostic answers remain distinct from policy
outcomes; this tool has no provider dispatch or quality-scoring mode. Target selection and new predicates require human
review, and successful diagnostic reasoning would not establish runtime evidence acquisition.

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
