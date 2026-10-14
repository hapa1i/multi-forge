# Jev client and test scripts: OpenRouter Decisions

Epic: [Jev support](../../doing/epic_jev_support/card.md). Member **A1**. No new-card dependencies. Provides the client
and evidence consumed by A2 and A3.

Status: **done**, shipped 2026-10-14 through [PR #268](https://github.com/hapa1i/multi-forge/pull/268), merged as
`9778007a`. The [merged closeout](checklist.md#merged-closeout) records verification and the
[results](evidence/2026-10-14/report.md) account for all 29 approved synthetic requests. The Jev epic remains active;
A2/A3 are separate consumers.

## Problem and outcome

Before A1, Forge had no typed Jev transport or measured latency/multi-question cost baseline. OpenRouter's Decisions API
is alpha. This card added a thin client over existing `httpx` and reproducible scripts in `scripts/experiments/jev/` to
establish the route contract before policy consumers rely on it.

Use the [research](../../doing/epic_jev_support/research.md#access-paths-and-their-implications) as the starting
evidence, not as a substitute for live probes. Vendor speed claims do not establish this deployment's p50/p95 latency.

Start with the minimal credential, URL, ZDR and timeout path, then a separately authorized small synthetic capture.
Reconcile those responses before finalizing retries, telemetry and estimator assumptions; the larger latency and
accounting matrix follows later. The [evidence index](evidence/README.md) distinguishes public documentation from live
results.

## Scope

- Implement the typed question/result boundary and OpenRouter Decisions adapter. Resolve OpenRouter credentials through
  Forge's existing owner, including the no-`.env` path. Pin the selected model and retain returned model/provider
  identity. Direct TypeSafe and its SDK are outside this card.
- Require `provider.zdr: true` after combining request options and on every retry. Preserve supported user/session/trace
  attribution without leaking raw content into identifiers. Unsupported routing must fail visibly, never retry with
  weaker retention requirements.
- Emit complete true/false criteria for Noul and validate supported question/result types, IDs, probabilities, counts
  and required fields. Reject invalid or mismatched answers. Preserve raw probabilities and distinguish model confidence
  from telemetry measurement confidence.
- Screen requests at 30,000 serialized bytes below the documented 32,000-token prompt ceiling, without claiming exact
  token counting or guaranteed provider admission. Own timeout, bounded retries, rate-limit handling and total deadline.
  Attribute physical attempts and returned usage/cost through existing telemetry conventions; absent cost remains
  unknown.
- Build opt-in probes for authentication, schema errors, ZDR-only routing/refusal, context boundaries, one versus many
  questions over fixed state, rate limits, retry behavior, and latency by request size/question count. Inspect returned
  provider identity and public catalog evidence; do not claim an API response proves an internal retention practice.
- Store sanitized results with endpoint, model, date, parameters, call count and available billed usage. Distinguish
  estimated prices from reported cost. Default scripts to fixture/dry-run behavior; live runs require explicit paid
  opt-in and a bounded request/spend budget. Use synthetic state before any authorized repository examples.

## Acceptance and validation

- Fixture-based unit/regression tests cover wire shaping, ZDR override attempts, bad responses, absent optional
  metadata, redaction, deadlines and retries without live API spend.
- Decisions token/cost fields and local trace IDs map into the existing downstream v2 and usage v1 schemas. Existing
  history remains readable, and baseline strict readers accept new records without new fields or route literals.
- The documented live probe matrix yields reproducible results or explicit unresolved/unsupported outcomes. A valid
  request with ZDR enabled must succeed before A2/A3 are advertised as available; inability to establish that contract
  remains a dependency blocker.
- Report end-to-end p50/p95 with sample counts and request shapes, size-limit failures and multi-question usage
  comparisons. Do not turn a small probe into an SLA or assume state billing scales linearly with question count.
- Exercise relevant telemetry trace/cost/activity surfaces and targeted integration tests. Update runtime/telemetry
  design and end-user credential/readiness guidance as the client ships.
