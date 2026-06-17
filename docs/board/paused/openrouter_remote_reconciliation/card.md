# OpenRouter Remote Reconciliation -- generation API joins and account-side views

**Status**: Paused after Phase 0. Depends on the shipped local provider-trace foundation in
`docs/board/done/openrouter_observability/card.md` and the Phase 0 OpenRouter probes recorded there. The active
telemetry epic chose `upstream_downstream_ledgers` as the next foundation, so this card remains paused until remote
reconciliation can return as a general downstream consumer rather than a second OpenRouter-specific telemetry path.

**Epic**: [`epic_telemetry_architecture`](../../doing/epic_telemetry_architecture/card.md).

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

Phase 0 answers are locked in [checklist.md](checklist.md). Implementation should stay within these boundaries:

- OpenRouter exposes generation metadata at `/api/v1/generation?id=gen-...`; content lives behind the separate
  `/api/v1/generation/content` endpoint and is out of scope.
- Generation metadata lookup uses the normal `openrouter` credential path; activity and analytics use the separate
  management credential path.
- Activity/analytics are management-key-gated, and activity is limited to the last 30 completed UTC days.
- Proxied OpenRouter grouping uses the standard `user` field. Direct `core.llm` `user` injection remains the separate
  `docs/board/todo/openrouter_user_direct_callers/` card.

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
forge provider openrouter generation gen-...
forge provider openrouter reconcile --session neat-bloodhound-executor --period today
forge provider openrouter activity --period today
forge provider openrouter analytics --session neat-bloodhound-executor --period today
# activity/analytics may also accept explicit --from/--to UTC bounds when OpenRouter requires exact ranges
```

Provider-neutral local trace commands remain separate:

```bash
forge provider trace list --session neat-bloodhound-executor --period today
forge provider trace explain req_...
```

The examples intentionally mirror the shipped local trace surface (`--period today|week|month|all`). Explicit
`--from`/`--to` UTC bounds are the planned escape hatch for activity/analytics endpoints that require concrete ranges.

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

## Phase 0 Decisions

- Query remote records on demand only in the first implementation; do not add a remote cache or schema yet.
- Treat `gen-...` as the canonical documented OpenRouter generation id, while accepting `gen_...` defensively if local
  traces contain it.
- Use `openrouter` / `OPENROUTER_API_KEY` for generation metadata lookup and `openrouter-management` /
  `OPENROUTER_MANAGEMENT_KEY` for activity and analytics.
- Keep the first implementation terminal-only under `forge provider openrouter ...`; no `%provider openrouter ...`
  direct command yet.
- Ship stable script-oriented `--json` output from the first implementation.
- No live OpenRouter probe is required before code. Later real-API checks should be credential-gated and marked
  `@pytest.mark.slow`.

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
