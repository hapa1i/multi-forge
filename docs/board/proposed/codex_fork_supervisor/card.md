# Codex fork supervisor

Epic: [Codex supervisor](../../doing/epic_codex_supervisor/card.md). Member **B5**. Depends on
[B1: plan-source/configuration contract](../../done/plan_file_supervision/card.md) and
[B2: Codex 0.160.1 test round](../codex_0160_validation/card.md).

## Problem and outcome

The current Codex reviewer receives a fresh prompt with a plan snapshot. For complex projects, allow an explicitly
selected supervisor to fork a Codex source conversation and inspect the executor's work with that native context. Use
`codex exec fork` only after B2 establishes its required runtime behavior.

This consumes ChatGPT subscription quota or an explicitly selected API route. It is optional and does not replace the
everyday Claude subscription path. Native context means what Codex actually retains and loads, including compaction; it
is not a guarantee of complete original conversation history.

A separate planning conversation is the clearest independent source, but planning and implementation can share a thread.
Support that case only with an explicit approved plan file taking precedence and reduced independence recorded: the fork
inherits later executor reasoning too. Installed 0.160.1 help exposes no option to fork from an earlier turn; this card
must not imply a planning-only snapshot.

## Scope

- Extend the shared supervisor source contract to identify a verified Codex source thread independently of the executor
  runtime and reviewer route. Resolve managed names to confirmed Codex IDs with provenance; reject missing, ambiguous or
  incompatible sources. Do not reuse a Claude UUID slot without runtime identity.
- Fork the source without appending to or rebinding it. Use the B2-validated ephemeral and structured-output options,
  and record returned fork/source identity where available. Inspect the action's checkout read-only, even when the
  planning thread was created elsewhere.
- Carry the action evidence and authoritative approved plan into the review. A later approved plan overrides stale
  conversation instructions. Identify unavailable context; do not describe a successful fork command as proof that all
  planning material reached the model.
- Detect when source and executor resolve to the same confirmed thread. Require the approved plan file, record its
  identity and the observed fork boundary, and label reduced review independence in status/JSON and review records. Do
  not treat the executor's own assertions as independent corroboration. If B2 cannot establish safe concurrent-source
  forking, report that case unsupported before dispatch rather than silently substituting a different source.
- Suppress recursive supervision and unintended Forge session adoption inside the reviewer using tested hook/depth
  controls. Preserve parent session ownership and record reviewer usage exactly once.
- Respect explicit model, backend, effort capabilities, lane freeze, readiness and timeout contracts. Detect quota
  failure and runtime error events even when the process exits zero. Never change to an API route without explicit
  paid-route selection; make any supported fallback and its different context visible.
- Validate the structured verdict and citations before applying existing allow/warn/deny rules. Native context does not
  make the model's confidence a calibrated probability. Update stale comments in touched code to describe the supported
  dispatch modes.

## Acceptance and validation

- Tests prove parent immutability, correct source and working directory, read-only behavior, structured output,
  timeout/cancellation handling, no recursive hook calls and one attributed review event.
- A real Codex integration test uses a planning-only sentinel to prove useful context survives the fork, while checking
  that no review content is appended to the planner. Repeat with a different executor checkout and a newer approved
  plan. Record the exact tested CLI version and any compaction limits.
- Test planning and implementation in one thread, including later reasoning that contradicts the approved plan. Verify
  plan precedence, rejection when the required plan file is absent, reduced-independence reporting, source immutability
  and B2's observed concurrent-source limits. Preserve these qualifications when evaluating review quality.
- Exercise explicit subscription and API configurations separately; default tests must not silently select paid
  credentials. Unavailable sources or unsupported binaries produce an actionable result without a misleading allow.
- Verify status/JSON and relevant lane/activity surfaces, and update workflow, runtime and end-user supervision docs.

## Boundary

This extends semantic supervision, not native team orchestration or general session fork/resume. Broader Codex source
capture remains with [codex_source_adapter](../codex_source_adapter/card.md); reuse shipped identity contracts without
making this card depend on an unshipped transcript-import framework.
