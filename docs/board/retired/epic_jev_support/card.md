# Retired epic: Jev support

The subsequent code cleanup removed A2/A3 implementation and dedicated tests. The [source archive](source-archive.md)
identifies the revision for historical commands and verification below; A1 and retained evidence remain.

Status: **retired**. Outcome: **cancelled** by owner decision on 2026-10-19 after
[PR #276](https://github.com/hapa1i/multi-forge/pull/276) merged as `ca943b6c`. No replacement is selected. A1 remains
[done](../../done/jev_client_probes/card.md); A2 and A3 are retired with their experimental evidence retained. The
[retirement closeout](checklist.md#retirement-closeout) records the final disposition.

A2's tested wrapper policy did not pass its feasibility gates. A3's first synthetic packet supplied no incremental
positive beyond deterministic controls, so it stopped before model capture. The epic's useful warnings and avoided
Claude reviews did not ship. These results do not establish that every future Jev use case is infeasible.

This is a terminal reference, not an executable roadmap. Reconsideration requires a new `proposed/` card with a concrete
use case, representative evidence and a bounded comparison. The original goals and contracts below preserve context; the
[source archive](source-archive.md) preserves the removed tooling and design at a fixed revision.

## Original problem and outcome

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

| ID  | Card                                                      | Final lane | Retained outcome                              |
| --- | --------------------------------------------------------- | ---------- | --------------------------------------------- |
| A1  | [Client and probes](../../done/jev_client_probes/card.md) | Done       | Typed transport and measured route/accounting |
| A2  | [Warning rule pack](../jev_rule_pack/card.md)             | Retired    | Failed feasibility evidence and archived code |
| A3  | [Cascade first tier](../jev_cascade/card.md)              | Retired    | Human reviews and offline comparison          |

No member remains active. A1's shipped outcome remains independently verified; retiring A2/A3 does not satisfy the
epic's original consumer acceptance or economic goals. B1 and B3 remain shipped members of the separate
[Codex supervisor epic](../../done/epic_codex_supervisor/card.md). [Jev Router](../../proposed/jev_router/card.md)
remains independently proposed and is not a replacement for this epic.

The independent [Claude feedback-permissions fix, PR #269](https://github.com/hapa1i/multi-forge/pull/269), shipped as
`e9c144eb` and is included on `main`. Its
[closeout](../../done/claude_policy_feedback_permissions/checklist.md#merged-closeout) records the decision to merge
with native testing skipped. It remains outside this epic's membership, and A2's native delivery gate was never
satisfied.

## Shared contract

Historical member contract; unfinished consumer work was cancelled and its implementation removed. A1 remains governed
by the current design documents and code.

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

Direct TypeSafe was an intended later access path. Its distinct System One transport and limits are documented in the
research, but implementation is outside these three cards; the epic does not claim both routes at closeout. Standalone
Jev blocking, team classification, search and memory selection remain research avenues.
[Jev Router](../../proposed/jev_router/card.md) stays a separate card because it chooses a generative model and
reasoning effort, with different routing and identity contracts. Codex runtime supervision is owned by its own epic.

## Original completion requirements (unmet)

A1 begins with a small authorized synthetic capture after the minimal transport, then establishes the usable route
contract and measures latency, request size and multi-question accounting. A2 must show useful, visible warnings with a
labeled per-rule evaluation. A3 must demonstrate avoided Claude calls at an acceptable measured false-allow rate,
including hard cases, failures, evidence gaps and real escalation.

Report calls avoided, reviewer model/tokens, latency, warning burden and escalation rate alongside Jev's reported API
cost. Record quota measurements only when usable provider evidence exists; tokens are not an exact quota conversion.
Model agreement is not correctness, and low Jev price is not proof of savings. Sync design and end-user documentation as
the member behavior ships.
