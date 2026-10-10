# Jev rule pack, warnings only

Epic: [Jev support](../epic_jev_support/card.md). Member **A2**. Depends on
[A1: Jev client and probes](../jev_client_probes/card.md). Codex-visible delivery also depends on
[B3: warnings Codex can see](../../doing/codex_policy_warnings/card.md).

## Problem and outcome

Literal coding-standards checks miss semantic patterns, such as a compatibility shim without a matching marker comment.
Add a Jev-backed policy type whose rule packs evaluate fixed atomic questions over supplied action evidence and return
warnings. It works without a plan or supervisor and provides measurable evidence before considering model decisions that
block actions.

[Workflow design §1.1](../../../design_workflows.md#11-deterministic-policy-forge-policy) motivates this use. The
[research](../epic_jev_support/research.md#rule-packs-backed-by-jev-fixed-semantic-checks) explains the boundary between
stable rule citations, action evidence and semantic correctness.

## Scope

- Define a rule pack with stable rule IDs/versions, source text and intent, applicability, atomic questions, true/false
  criteria and consumer thresholds. Treat the pack as a policy concept; keep existing exact syntax checks deterministic.
  Begin with a small reviewed pack rather than a general rule-authoring framework.
- Batch applicable questions over one bounded action state where they fit. Define an action as the engine's normalized
  context and account for Codex multi-file patches so request counts and warning attribution are explicit. Do not
  discard uncovered files or silently split into unbounded paid fan-out.
- Construct warning diagnostics from known rule text and supplied action evidence. Record rule provenance, raw answer,
  model, input identity and evaluated excerpt; mark insufficient evidence explicitly. Jev does not generate free-form
  justifications, and a selected rule citation alone does not prove a violation.
- Register the new policy type through the existing engine/configuration contract with atomic validation of bad pack
  settings. Respect per-session activation, deadlines, cache identity and A1's paid opt-in/ZDR requirements.
- Return non-blocking warnings only. Service failure or malformed/incomplete evidence must not introduce a new Jev
  denial or unresolved `needs_review`; display an unavailable-check diagnostic. Existing independent denials remain
  intact. This card does not invoke a supervisor, even when one is configured.
- Deliver attributed warnings through an extended Claude formatter and B3's verified Codex path. Extend the existing
  `policy_summary_feedback` setting to substantive Claude feedback, matching B3's Codex contract: when enabled, send
  bounded rule text/citation and action evidence in `additionalContext`; when disabled, omit model feedback while
  retaining operator diagnostics and audit records. Claude keeps its generic summary until this card ships; B3 alone
  changes Codex. Update runtime configuration help and end-user config/policy docs with that staged contract. Respect
  B3's audience, bounds, and provenance rules, including its Codex-only source-only preference; keep evidence-inspection
  commands in operator output in that mode. Distinguish Codex operator `systemMessage` from model context and do not
  claim model visibility from stderr alone. Keep Jev disabled for everyday no-API-spend supervision.

## Acceptance and validation

- Use a labeled historical-diff corpus with compliant examples and violations, held-out changes, rule versions and
  reconstructed context. Evaluate per-rule false positives and misses, insufficient evidence, calibration, pack-wide
  warning frequency, latency and API cost against existing deterministic checks. Human adjudication supplies labels;
  merged history and another model's verdict are not automatic ground truth.
- Unit/regression tests cover pack validation, applicability, deterministic-policy coexistence, batched answer mapping,
  multi-file attribution, stale cache, incomplete state, injected instructions and timeout/malformed-result warnings.
- Targeted hook integration tests with `policy_summary_feedback` enabled prove the actual rule/evidence warning reaches
  the model and the action remains allowed. With it disabled, assert absent model feedback, retained operator/audit
  diagnostics and the same action outcome. Cover Claude and B3's Codex path. Use client fixtures for ordinary tests; any
  live Jev run is explicitly selected and budgeted.
- Publish the corpus/evaluation method with suitable sanitized fixtures and update workflow and end-user policy docs. A
  later opt-in warning trial assesses real warning burden and adoption; do not claim quota savings from this card.

## Boundary

Direct blocking and escalation of fixed-rule findings are deferred. The existing plan supervisor cannot adjudicate rule
findings merely because it is configured; that extension would need an explicit rule/evidence handoff.
[A3](../jev_cascade/card.md) is plan-check cascade work, not a shortcut around that requirement.
