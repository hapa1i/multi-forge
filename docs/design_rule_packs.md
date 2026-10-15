# Rule-pack design

Normative ownership for the implemented rule-pack foundations. Policy engine composition remains in
[workflow design](design_workflows.md); this foundation does not add a runnable policy bundle.

## Evaluation foundations

`policy/rule_pack/definitions.py` owns the provisional compatibility-wrapper rule, applicability table and three atomic
Noul questions. `outcomes.py` applies that host applicability table and owns fixed diagnostics for every host and model
outcome. It requires explicit per-question threshold bands and composes covered answers into warning, no-warning,
uncertain or unavailable assessments with fixed diagnostics. Contradictory answers remain uncertain; missing coverage
cannot establish compliance. These modules do not register or activate a bundle and do not dispatch requests.

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
adjudication. Named reviewers are provenance supplied by the operator, not authenticated identities. This workflow
cannot establish that a human performed the review or turn fixture proposals into quality evidence.

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
