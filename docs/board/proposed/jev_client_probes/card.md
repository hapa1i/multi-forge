# Jev client and test scripts: OpenRouter Decisions

Epic: [Jev support](../epic_jev_support/card.md). Member **A1**. No new-card dependencies. Provides the client and
evidence consumed by A2 and A3.

## Problem and outcome

Forge has no typed Jev transport. OpenRouter's Decisions API is alpha, and there is no measured Forge latency or
multi-question cost baseline. Add a thin client over existing `httpx` and reproducible scripts in
`scripts/experiments/jev/` to establish the route contract before policy consumers rely on it.

Use the [research](../epic_jev_support/research.md#access-paths-and-their-implications) as the starting evidence, not as
a substitute for live probes. Vendor speed claims do not establish this deployment's p50/p95 latency.

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
- Enforce a conservative 32,000-token total request budget with estimation headroom. Own timeout, bounded retries,
  rate-limit handling and total deadline. Attribute physical attempts and returned usage/cost through existing telemetry
  conventions; absent cost remains unknown.
- Build opt-in probes for authentication, schema errors, ZDR-only routing/refusal, context boundaries, one versus many
  questions over fixed state, rate limits, retry behavior, and latency by request size/question count. Inspect returned
  provider identity and public catalog evidence; do not claim an API response proves an internal retention practice.
- Store sanitized results with endpoint, model, date, parameters, call count and available billed usage. Distinguish
  estimated prices from reported cost. Default scripts to fixture/dry-run behavior; live runs require explicit paid
  opt-in and a bounded request/spend budget. Use synthetic state before any authorized repository examples.

## Acceptance and validation

- Fixture-based unit/regression tests cover wire shaping, ZDR override attempts, bad responses, absent optional
  metadata, redaction, deadlines and retries without live API spend.
- The documented live probe matrix yields reproducible results or explicit unresolved/unsupported outcomes. A valid
  request with ZDR enabled must succeed before A2/A3 are advertised as available; inability to establish that contract
  remains a dependency blocker.
- Report end-to-end p50/p95 with sample counts and request shapes, size-limit failures and multi-question usage
  comparisons. Do not turn a small probe into an SLA or assume state billing scales linearly with question count.
- Exercise relevant telemetry trace/cost/activity surfaces and targeted integration tests. Update runtime/telemetry
  design and end-user credential/readiness guidance as the client ships.
