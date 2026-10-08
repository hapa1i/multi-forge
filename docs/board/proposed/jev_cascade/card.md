# Jev as the cascade's first tier

Epic: [Jev support](../epic_jev_support/card.md). Member **A3**. Depends on
[A1: Jev client and probes](../jev_client_probes/card.md) and
[B1: plan-file Claude supervision](../../doing/plan_file_supervision/card.md). A2 is not a dependency.

## Problem and outcome

On projects where Jev API spend is accepted, settle clearly covered plan/action checks before invoking the Claude
supervisor. Reserve Claude subscription calls for uncertain, unsupported or divergent cases, while retaining the current
cascade's conservative allow-or-escalate boundary.

Only an actual avoided Claude invocation preserves reviewer quota. Jev's request price is an additional API charge, and
sampled audits/retries/escalations consume resources too. Everyday subscription-only supervision keeps this tier
disabled. See the [economics research](../epic_jev_support/research.md#economics-protecting-claude-quota).

## Scope

- Add a typed Jev implementation of the plan-check tier using A1. Keep the existing generative checker available and
  make selection explicit. Do not pass a Jev ID into the existing chat client and parse manufactured completion text.
- Supply an approved, versioned plan and canonical action evidence. Decompose relevant constraints into atomic questions
  with reviewed coverage; account for the cost and errors of any assisted decomposition. A broad question asking whether
  the whole action aligns with the plan is outside the proposed contract.
- Allow only when the validated composition rule establishes sufficient evidence and coverage for the supported case.
  Unmapped constraints, unsupported reasoning, truncation, ambiguity, service failure and suspected divergence escalate
  to B1's Claude reviewer. A probability threshold cannot repair missing coverage. Jev does not directly deny here.
- Preserve deterministic deny precedence, complete-action cache identity, plan/question/model/threshold invalidation,
  timeout budget and resolver behavior. Escalation uses the authoritative plan and action evidence; Jev's allow must not
  clear unrelated unresolved rule findings. Preserve the supervisor's existing failure semantics visibly.
- Consume B1's shared hook deadline across Jev, retries, all files and Claude escalation, reserving time to record the
  outcome. If the remaining budget cannot support escalation, record unavailable review using B1's status/activity
  contract; do not start a fresh full timeout or report the action as reviewed.
- Extend observation/shadow evidence to include hard cases and failures, not just sampled Jev allows. Record all
  reviewer attempts once, and attribute Jev cost separately from Claude usage. Keep audit volume explicitly bounded so
  it does not silently consume the quota being protected.
- Require offline evaluation and an opt-in observation phase before enabling Jev to skip reviews. Select thresholds from
  Forge data; neither the supervisor's 0.8 bar nor a vendor example is a valid default acceptance threshold.

## Acceptance and validation

- Build human-adjudicated examples covering aligned/divergent actions, missing/changed plans, omitted constraints,
  oversized or adversarial state, unknown rule coverage, and cases already escalated by the existing checker. Evaluate
  false allows, escalation rate and review quality on held-out data; record the activation decision and its evidence
  before short-circuiting any review.
- Compare full supervision with and without Jev, keeping the configured cascade baseline explicit. Report Claude calls
  actually avoided, model/tokens, available quota evidence, p50/p95 total latency, Jev spend, retries and sampled
  audits. Token counts are not an exact conversion into subscription quota or dollar savings.
- Unit/regression tests prove only covered validated allows bypass the reviewer; all failure/unknown paths escalate,
  stale cache cannot allow, and deterministic denials win. Test suspension, unavailable reviewer and no-paid-fallback
  behavior without live API calls.
- A budgeted, explicitly selected integration run demonstrates a skipped Claude call and a real escalation from a Codex
  action to the configured plan-file supervisor. Verify the action decision, checkout and telemetry chain.
- Update workflow, telemetry and end-user cascade documentation, including the paid opt-in and quality limits.

## Boundary

This is not a standalone Jev supervisor or a blocking rule pack. Warnings for fixed rules are A2; independently
adjudicating those findings would require its own rule-aware resolver contract. Native Codex forks and Stop review stay
in the Codex supervisor epic.
