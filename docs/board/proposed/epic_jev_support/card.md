# Epic: Jev support

Status: proposed. Scope drafted 2026-10-06; implementation has not started.

## Problem and outcome

Add Jev-backed policy evaluation to Multi-Forge, beginning with OpenRouter Decisions. Fixed semantic rule packs provide
warnings; a separately validated cascade can settle covered actions and reserve Claude supervisor calls for the cases
that need them. Preserve typed judgments, source evidence and consumer-owned decisions rather than treating Jev as a
chat model.

The primary economic objective is protecting Claude subscription quota on projects where the user accepts Jev's API
cost. Everyday supervision must incur no API spend, so Jev is explicitly opt-in. Warning-only packs do not by themselves
avoid Claude calls. The [research](research.md) records pricing, schema differences, model limitations and the measured
absence of configured supervisors/policy enforcement across 78 local session manifests. No quota saving, latency or
decision-quality result has been measured.

## Members and dependencies

| ID  | Card                                                      | Independently shippable outcome                                               | Depends on                        |
| --- | --------------------------------------------------------- | ----------------------------------------------------------------------------- | --------------------------------- |
| A1  | [Jev client and probes](../jev_client_probes/card.md)     | Typed OpenRouter transport and reproducible contract/latency/billing evidence | None                              |
| A2  | [Jev rule pack, warnings only](../jev_rule_pack/card.md)  | Opt-in semantic policy type over fixed atomic rules                           | A1; B3 for Codex-visible warnings |
| A3  | [Jev as the cascade's first tier](../jev_cascade/card.md) | Validated covered allows avoid a Claude review; other cases escalate          | A1, B1                            |

[B1](../plan_file_supervision/card.md) and [B3](../codex_policy_warnings/card.md) belong to the separate
[Codex supervisor epic](../epic_codex_supervisor/card.md). A2 and A3 can proceed independently after their
prerequisites; A2's fixed-rule quality evidence does not validate A3's plan-alignment questions. Cards use separate
execution branches when activated.

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
  Record Jev attempts and any reviewer escalation separately, including retries and sampled audits.
- Paid calls require explicit opt-in. Probes start with synthetic data, bounded requests and a declared budget; ordinary
  tests use fixtures. Do not automatically send repository history to a new provider.

## Deferred scope

Direct TypeSafe remains an intended later access path. Its distinct System One transport and limits are documented in
the research, but implementation is outside these three cards; the epic does not claim both routes at closeout.
Standalone Jev blocking, team classification, search and memory selection remain research avenues.
[Jev Router](../jev_router/card.md) stays a separate card because it chooses a generative model and reasoning effort,
with different routing and identity contracts. Codex runtime supervision is owned by its own epic.

## Completion evidence

A1 must establish the usable route contract and measure latency, request size and multi-question accounting. A2 must
show useful, visible warnings with a labeled per-rule evaluation. A3 must demonstrate avoided Claude calls at an
acceptable measured false-allow rate, including hard cases, failures, evidence gaps and real escalation.

Report calls avoided, reviewer model/tokens, latency, warning burden and escalation rate alongside Jev's reported API
cost. Record quota measurements only when usable provider evidence exists; tokens are not an exact quota conversion.
Model agreement is not correctness, and low Jev price is not proof of savings. Sync design and end-user documentation as
the member behavior ships.
