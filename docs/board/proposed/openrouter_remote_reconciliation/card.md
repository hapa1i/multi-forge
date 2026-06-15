# OpenRouter Remote Reconciliation -- generation API joins and account-side views

**Status**: Proposed. Depends on the local provider-trace foundation in
`docs/board/proposed/openrouter_observability/card.md` and the Phase 0 OpenRouter probes recorded there.

**References**: OpenRouter `/api/v1/generation`, `/api/v1/activity`, `/api/v1/analytics/query`, management-key
requirements, Forge provider trace records, cost logs, usage ledger, and run-tree headers.

## Problem

After Forge has a local provider trace, operators still need a way to ask OpenRouter what the account saw: final token
counts, cost, upstream provider, cancellation status, and activity grouped by session or time window.

Remote reconciliation is useful, but it is contingent. The motivating incident involved streams cancelled by a local
supervisor timeout before final usage arrived. OpenRouter may not expose those aborted generations through dashboard,
activity, analytics, or generation lookup. In that case the correct answer is a local one: Forge saw the stream start,
then lost the final usage/cost evidence when the client/subprocess disconnected.

This card should therefore enhance local trace, not replace it.

## Preconditions

Do not start implementation until the provider-trace card has recorded Phase 0 answers for:

- where OpenRouter exposes generation ids for Forge's streaming and non-streaming paths
- whether cancelled-before-final-usage streams appear in `/generation`, `/activity`, dashboard logs, or analytics
- which endpoints require a normal API key vs a management key
- whether sticky `session_id` changes latency/cache/provider behavior enough to affect the operator story

## Proposal

Add a small OpenRouter REST client and CLI read surfaces that join local provider trace records to remote OpenRouter
records when possible.

### 1. REST client

Implement a small client rather than adding a broad SDK dependency:

- `GET /api/v1/generation?id=<generation_id>` for per-generation metadata
- `GET /api/v1/activity` for account activity when a management key is configured
- `POST /api/v1/analytics/query` for grouped metrics over a selected time range when a management key is configured

The client must record endpoint provenance and key class without exposing secrets.

### 2. CLI namespace

Prefer a provider namespace so provider-neutral trace concepts can generalize later:

```bash
forge provider openrouter generation gen_...
forge provider openrouter reconcile --session neat-bloodhound-executor --since today
forge provider openrouter activity --date 2026-06-14
forge provider openrouter analytics --session neat-bloodhound-executor --since today
```

Provider-neutral local trace commands remain separate:

```bash
forge provider trace list --session neat-bloodhound-executor --since today
forge provider trace explain req_...
```

### 3. Reconciliation taxonomy

Output should clearly distinguish:

- **local**: what Forge provider trace/cost/audit/usage records saw
- **remote**: what OpenRouter reports
- **joined**: local request ids matched to remote generation ids
- **missing-local**: OpenRouter activity with no matching local record in the selected window
- **missing-remote**: local provider ids that OpenRouter cannot find or the key cannot access
- **not-queryable**: local traces that never received a provider generation id, or endpoints unavailable for the
  configured key/account

Do not silently replace local cost evidence with remote evidence. Show provenance, for example
`local proxy final usage`, `OpenRouter generation API`, or `OpenRouter analytics aggregate`.

### 4. Credential handling

Reuse Forge's credential resolver where possible:

- normal OpenRouter API key for generation lookup if supported
- optional `OPENROUTER_MANAGEMENT_KEY` or credentials-file equivalent for activity/analytics
- actionable errors when management access is missing
- no API key echoing in logs, JSON output, or tracebacks

### 5. View integration

After the standalone CLI works, integrate carefully:

- `forge activity` can show provider trace ids and a remote reconciliation hint for supervisor, curation, and memory
  events.
- `forge proxy costs show` can display remote-reconciled values separately from local proxy-reported values.
- Session closeout can mention an OpenRouter provider session id and whether local traces have unresolved remote status.

All integrations must retain provenance labels and avoid implying that a missing remote record means a request never
happened.

## Open questions

- Is `/api/v1/generation` available with ordinary API keys for generations created by that key, or does it require
  management access?
- Does OpenRouter use `gen-...`, `gen_...`, OpenAI-compatible ids, or endpoint-specific ids for the records Forge can
  query?
- How far back can activity/analytics look, and does the API expose enough filters for Forge session ids?
- Should reconciliation cache remote records locally under the provider trace plane, or query on demand only?
- Should JSON output be optimized for scripts from the first implementation?

## Risks

- Remote APIs may not expose cancelled streams. The CLI must render this as "missing remote evidence" rather than
  implying no request was sent.
- Account/key mismatches can produce false `missing-remote` results. Output should include key provenance class and
  selected account context when the API exposes it.
- Remote cost and local proxy cost may differ in timing or aggregation. Preserve both values with provenance.
- Content endpoints can expose prompts/completions. Do not fetch content unless a later card adds an explicit,
  privacy-reviewed flag.

## Acceptance sketch

- **Generation lookup joins**: a local trace with a mocked generation id and OpenRouter response shows remote
  tokens/cost/provider/status alongside the local request id.
- **Missing remote is explicit**: a generation id not returned by the API renders `missing-remote` with possible
  key/account/cancelled explanations.
- **Missing management key actionable**: `activity` without a management key explains the required credential without
  traceback or key leakage.
- **Local evidence preserved**: differing remote and local cost/token values are both shown with provenance labels.
- **Not-queryable local trace**: a trace with no provider generation id renders `not-queryable`, not failure.
- **Activity missing-local**: activity without a local trace in the selected window renders `missing-local` with
  model/time/session context.
- **Content not fetched**: generation lookup does not request prompt/completion content.
- **JSON mode stable**: `--json` output has local/remote/joined/missing arrays and no secrets.
