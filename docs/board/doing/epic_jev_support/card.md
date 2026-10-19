# Epic: Jev support

Status: **doing**, activated 2026-10-14 with A1. The [coordination checklist](checklist.md) tracks member gates and
handoffs. A1 shipped through [PR #268](https://github.com/hapa1i/multi-forge/pull/268), merged as `9778007a` on
2026-10-14. A2's foundations shipped through [PR #270](https://github.com/hapa1i/multi-forge/pull/270) as `9442c1e5` on
2026-10-15. Its offline outcomes and evaluation shipped through
[PR #271](https://github.com/hapa1i/multi-forge/pull/271) as `791d9872` on the same day. A2 is paused by owner decision
on 2026-10-19 after the bounded investigation failed to establish a viable hook policy. Its
[pause handoff](../../paused/jev_rule_pack/evidence/pr-275-pause-handoff.md) preserves the tools, negative results and
unmet gates. A3 is selected next for a separate feasibility branch and checklist. The epic remains active; no consumer
quality or quota-saving outcome has shipped.

## Problem and outcome

Add Jev-backed policy evaluation to Multi-Forge, beginning with OpenRouter Decisions. Fixed semantic rule packs provide
warnings; a separately validated cascade can settle covered actions and reserve Claude supervisor calls for the cases
that need them. Preserve typed judgments, source evidence and consumer-owned decisions rather than treating Jev as a
chat model.

The primary economic objective is protecting Claude subscription quota on projects where the user accepts Jev's API
cost. Everyday supervision must incur no API spend, so Jev is explicitly opt-in. Warning-only packs do not by themselves
avoid Claude calls. The [research](research.md) records pricing, schema differences, model limitations and the measured
absence of configured supervisors/policy enforcement across 78 local session manifests. A1's
[synthetic measurements](../../done/jev_client_probes/evidence/2026-10-14/report.md) establish transport latency and
reported cost for the captured shapes; quota savings and decision quality remain unmeasured.

## Members and dependencies

| ID  | Card                                                                  | Independently shippable outcome                                               | Depends on                        |
| --- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------- | --------------------------------- |
| A1  | [Jev client and probes](../../done/jev_client_probes/card.md)         | Typed OpenRouter transport and reproducible contract/latency/billing evidence | None                              |
| A2  | [Jev rule pack, warnings only](../../paused/jev_rule_pack/card.md)    | Opt-in semantic policy type over fixed atomic rules                           | A1; B3 for Codex-visible warnings |
| A3  | [Jev as the cascade's first tier](../../proposed/jev_cascade/card.md) | Validated covered allows avoid a Claude review; other cases escalate          | A1, B1                            |

[B1](../../done/plan_file_supervision/card.md) and [B3](../../done/codex_policy_warnings/card.md) belong to the separate
[Codex supervisor epic](../../done/epic_codex_supervisor/card.md). A2 and A3 can proceed independently after their
prerequisites; A2's fixed-rule quality evidence does not validate A3's plan-alignment questions. Cards use separate
execution branches when activated.

Next selected member: [A3](../../proposed/jev_cascade/card.md), for feasibility before runtime work. Activate it on its
own branch after PR #275 merges. A2 remains paused; neither its failures nor its shipped tooling settle A3's independent
plan/action coverage and false-allow questions. A3 must justify review-skipping against full supervision and
deterministic baselines before implementation. No further A2 capture is planned.

The independent [Claude feedback-permissions fix, PR #269](https://github.com/hapa1i/multi-forge/pull/269), shipped as
`e9c144eb` and is included on `main`. Its
[closeout](../../done/claude_policy_feedback_permissions/checklist.md#merged-closeout) records the decision to merge
with native testing skipped. It remains outside this epic's membership, and A2's native delivery gate stays open.

## Shared contract

- OpenRouter first: `POST /api/alpha/decisions`, with `provider.zdr: true` on every attempt. Fail rather than retry
  without that requirement. The alpha route needs empirical checks before real policy payloads depend on it.
- Use Forge's existing `httpx`, credential resolution and attributable request/usage conventions. Introduce a typed
  judgment boundary for named questions, distributions, resolved model and usage; do not force it through generated
  completion text. Missing provider cost stays unknown, not a fabricated invoice.
- Start with a conservative 32,000-token total budget including all questions and explicit Noul true/false criteria.
  Surface missing, truncated, oversize or unsupported evidence to the consumer. Validate response shape, question
  identity and probability values, with bounded retries inside an overall deadline.
- Questions must be atomic and appropriate to the supplied evidence. Fixed packs own their reviewed rules; plan checking
  also owns decomposition and coverage. No blanket multi-judgment alignment question or transferred 0.8 confidence
  threshold. Calibrate the decision rule on Forge examples.
- Keep action choice in the policy consumer. A2 warns only; A3 allows only validated covered cases and otherwise
  escalates. Deterministic denials retain priority. A rule's source citation and evidence of a violation are separate.
- Cache and audit identity include canonical action/state, rule/question/plan version, route/model and decision rule.
  Record Jev attempts and any reviewer escalation separately, including retries and sampled audits. A1's `judge()`
  accepts an optional explicit evaluation `RunIdentity` so consumers do not reuse the whole interactive run as one
  invocation. A2/A3 own their evaluation runs; existing callers retain the ambient fallback and telemetry schemas are
  unchanged.
- Paid calls require explicit opt-in. Probes start with synthetic data, bounded requests and a declared budget; ordinary
  tests use fixtures. Do not automatically send repository history to a new provider.

## Deferred scope

Direct TypeSafe remains an intended later access path. Its distinct System One transport and limits are documented in
the research, but implementation is outside these three cards; the epic does not claim both routes at closeout.
Standalone Jev blocking, team classification, search and memory selection remain research avenues.
[Jev Router](../../proposed/jev_router/card.md) stays a separate card because it chooses a generative model and
reasoning effort, with different routing and identity contracts. Codex runtime supervision is owned by its own epic.

## Completion evidence

A1 begins with a small authorized synthetic capture after the minimal transport, then establishes the usable route
contract and measures latency, request size and multi-question accounting. A2 must show useful, visible warnings with a
labeled per-rule evaluation. A3 must demonstrate avoided Claude calls at an acceptable measured false-allow rate,
including hard cases, failures, evidence gaps and real escalation.

Report calls avoided, reviewer model/tokens, latency, warning burden and escalation rate alongside Jev's reported API
cost. Record quota measurements only when usable provider evidence exists; tokens are not an exact quota conversion.
Model agreement is not correctness, and low Jev price is not proof of savings. Sync design and end-user documentation as
the member behavior ships.
