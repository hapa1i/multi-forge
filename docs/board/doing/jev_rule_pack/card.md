# Jev rule pack, warnings only

Epic: [Jev support](../epic_jev_support/card.md). Member **A2**. Depends on
[A1: Jev client and probes](../../done/jev_client_probes/card.md). Codex-visible delivery also depends on
[B3: warnings Codex can see](../../done/codex_policy_warnings/card.md), shipped through PR #262 and closed on
2026-10-11.

The independent [feedback-permissions fix, PR #269](https://github.com/hapa1i/multi-forge/pull/269), shipped as
`e9c144eb` and is included on `main`. Its
[closeout](../../done/claude_policy_feedback_permissions/checklist.md#merged-closeout) records the user's decision to
merge with paid native testing skipped. A2 still needs its own native warning-delivery evidence.

Status: **doing**. The foundations shipped through [PR #270](https://github.com/hapa1i/multi-forge/pull/270), merged as
`9442c1e5` on 2026-10-15. Offline outcomes and saved-response evaluation shipped through
[PR #271](https://github.com/hapa1i/multi-forge/pull/271) as `791d9872` on the same day. The
[execution checklist](checklist.md) records the outstanding quality and activation gates. The
[wrapper evidence contract](evidence/initial-rule-review.md) follows the user's 2026-10-15 choice to keep broader
wrappers. All 17 constructed hook-shaped examples now have human adjudications. Representative action coverage, warning
usefulness and numerical quality gates remain open. The
[first calibration capture](evidence/calibration-2026-10-16/README.md) and
[boundary-instruction follow-up](evidence/calibration-boundary-2026-10-17/README.md) are complete. The follow-up still
cannot recover any of the three human no-warning labels under allowed thresholds. Settings remain unset and the bundle
is not registered for activation. The [merge handoff](checklist.md#offline-evaluation-merge-and-next-gate) records
shipped scope and the next gate without closing A2. Implemented ownership is described in
[rule-pack design](../../../design_rule_packs.md).

Human review shipped through [PR #272](https://github.com/hapa1i/multi-forge/pull/272) as `64317485`. The
[PR #274 experimental checkpoint](evidence/pr-274-merge-handoff.md) merged as `09984440` on 2026-10-17. A2 remains
active at the [pre-runtime feasibility gate](checklist.md#slice-2-feasibility-before-runtime-work). The
[completed bounded study](evidence/bounded-diagnostic-2026-10-18/README.md) followed review of all 95 diagnostic answers
and separate capture approval. Jev triggered its repeated-sentinel stop; Opus failed the critical missing-replacement
retention answer. Neither arm passed, and the allowance is consumed. The
[bounded offline review](evidence/offline-retention-admission.md) separates structural candidates from evidence
admission and semantic retention, preserving the failed study and its labels. Native coverage and usefulness remain
unmeasured. The [runtime evidence proposal](evidence/runtime-evidence-contract.md) remains unimplemented;
constructed-only evidence cannot establish runtime quality or activate the policy.

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
  settings. Require an explicit acknowledgment of API cost and repository-data sharing. The 2026-10-14 user decision
  requires a new acknowledgment in every fork, fresh-resume or relaunch child; same-session resume retains it. Raw
  overrides and inherited configuration cannot supply consent. Respect the existing hook deadline, cache identity and
  A1's ZDR requirements.
- Run A2 after existing policy checks finish for the whole action. An already blocked action makes no Jev request;
  otherwise use only the remaining shared hook budget, with the bounded A2 stage specified in the checklist.
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

- Establish corpus feasibility and quality limits for the selected wrapper family before further runtime implementation.
  Measure real-action evidence sufficiency, governance/exception mapping and practical warning usefulness first.
  Reconstruct historical changes into the Write/Edit or apply_patch actions the hook sees, with documented assumptions.
  Include constructed positives when needed, labeled and measured separately; any native transcript cohort requires its
  own data decision. Keep originating changes and mutation families within one calibration/held-out split. Evaluate
  per-rule false positives and misses, insufficient evidence, calibration, pack-wide warning frequency, latency and API
  cost against existing marker checks and a bounded AST baseline using the same supplied evidence. Review warning
  usefulness separately against caller/contract evidence that never enters the model payload. Human adjudication
  supplies labels; merged history and another model's verdict are not automatic ground truth. Freeze question bands on
  calibration responses only. The existing held-out scenarios were visible during draft-3 development and cannot
  demonstrate generalization to unseen scenarios.
- Unit/regression tests cover pack validation, applicability, deterministic-policy coexistence, batched answer mapping,
  multi-file attribution, consent/override boundaries, blocked-action suppression, stale cache, incomplete state,
  injected instructions and consumer-specific timeout/malformed-result diagnostics. Evaluation runs need distinct
  identities and bounded audit artifacts outside the session manifest.
- Targeted hook integration tests with `policy_summary_feedback` enabled prove the actual rule/evidence warning reaches
  the model and the action remains allowed. With it disabled, assert absent model feedback, retained operator/audit
  diagnostics and the same action outcome. Cover Claude and B3's Codex path. Use client fixtures for ordinary tests; any
  live Jev run is explicitly selected and budgeted.
- Publish the corpus/evaluation method with suitable sanitized fixtures and update workflow and end-user policy docs. A
  later opt-in warning trial assesses real warning burden and adoption; do not claim quota savings from this card.

## Boundary

Direct blocking and escalation of fixed-rule findings are deferred. The existing plan supervisor cannot adjudicate rule
findings merely because it is configured; that extension would need an explicit rule/evidence handoff.
[A3](../../proposed/jev_cascade/card.md) is plan-check cascade work, not a shortcut around that requirement.

## B3 formatter handoff (2026-10-10)

B3's [results](../../done/codex_policy_warnings/evidence/README.md) and
[workflow contract](../../../design_workflows.md#11-deterministic-policy-forge-policy) supply the Codex delivery path.
Supply structured `warning_findings` with stable rule/path attribution while retaining legacy warning strings and
deny-only `violations` semantics. Only known policy-authored text may claim `provenance=policy`; model-generated prose
must not acquire that classification. Verified supervisor quotations carry source/digest/character spans from the
reviewed snapshot. Rule-pack findings still need their own source/evidence provenance; selecting a rule does not verify
a violation or authorize a fabricated plan quotation.

Respect `policy_summary_feedback=off`, independent operator/audit output, and the Codex-only source-only preference. The
model/operator string budgets are 12,000/5,000 JSON-encoded bytes, with a 20,000-byte wire ceiling, 600-character
fields, 2,400-byte findings, and at most 12 findings per channel. Use the shared formatter and visible omission
counters; do not reintroduce explicit `permissionDecision=allow`. The real 0.162.1 operator surface is an inline
`Hook ·` notice. Claude's substantive warning formatter remains A2 work; this handoff does not activate Jev or authorize
a paid call.
