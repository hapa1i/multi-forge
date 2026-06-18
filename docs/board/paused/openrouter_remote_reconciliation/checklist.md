# OpenRouter Remote Reconciliation -- Execution Checklist

Branch: `openrouter_remote_reconciliation`. Card: [card.md](card.md). Epic:
[`epic_telemetry_architecture`](../../doing/epic_telemetry_architecture/card.md).

## Current Focus

Paused after Phase 0 while `epic_telemetry_architecture` runs the `upstream_downstream_ledgers` foundation first. Resume
by moving this card back to `doing/` only after the ledger foundation lands or the epic explicitly changes the sequence.

Original flow: Phase 0 recon and decision lock -> Phase 1 REST client -> Phase 2 credential/key provenance -> Phase 3
command-core reconciliation -> Phase 4 CLI surface -> Phase 5 optional view integrations -> docs, review, closeout.

## Pause Note (2026-06-17)

- [x] Phase 0 recon, OpenRouter endpoint verification, and decision lock are complete.
- [x] Card moved to `paused/` before Phase 1 implementation.
- [x] Telemetry epic decided not to resume this card next; `upstream_downstream_ledgers` runs first.
- [ ] Resume only after the telemetry epic confirms the upstream/downstream foundation is ready for remote
  reconciliation, or deliberately reopens the sequence.

## Decisions To Lock

- [x] **Remote query mode**: start with on-demand remote queries only. No remote cache/schema is part of the first
  implementation.
- [x] **Credential home**: use `openrouter-management` with `OPENROUTER_MANAGEMENT_KEY`, separate from the normal
  `openrouter` / `OPENROUTER_API_KEY` credential used for generation lookup.
- [x] **Generation endpoint key class**: use the normal `openrouter` key for `/api/v1/generation`; the official
  generation metadata docs require bearer auth but do not mark the endpoint as management-key-gated. Keep a later live
  smoke for ordinary-key behavior useful but non-blocking.
- [x] **Time-window flags**: use `--period today|week|month|all` for parity with `forge provider trace list`; add
  explicit `--from`/`--to` UTC bounds for activity/analytics if OpenRouter requires concrete date ranges. Treat older
  card sketches using `--since` or `--date` as illustrative only.
- [x] **CLI namespace**: implement remote surfaces under `forge provider openrouter ...`; keep local-only trace commands
  under `forge provider trace ...`.
- [x] **Direct command scope**: `%provider openrouter ...` is out of scope for the first implementation. Ship
  terminal-only until remote credential UX and latency are proven.
- [x] **Identifier vocabulary**: treat `gen-...` as the canonical documented OpenRouter generation id; accept observed
  `gen_...` or endpoint-specific ids defensively without rewriting local provider-trace ids or synthetic
  Forge/OpenAI-compatible ids.
- [x] **Privacy boundary**: no prompt/completion/content fetching in this card. Metadata only unless a later card adds a
  separate privacy-reviewed flag.

## Phase 0 -- Recon And Card Correction

- [x] Re-read the shipped provider-trace implementation and docs: `src/forge/proxy/provider_trace_logger.py`,
  `src/forge/core/ops/provider_trace.py`, `src/forge/cli/provider.py`, `docs/design.md` §3.14, and
  `docs/design_appendix.md` §A.14.
- [x] Correct remaining stale card language before coding: proxied OpenRouter grouping uses the standard `user` field,
  not a custom `session_id`; direct `core.llm` `user` injection remains the separate
  `docs/board/todo/openrouter_user_direct_callers/` card.
- [x] Verify the OpenRouter endpoint/key facts needed for implementation and record them in this checklist or the card:
  generation lookup key class, activity/analytics management-key requirements, id format, and any retention/window
  limits.
- [x] Decide whether a live OpenRouter probe is required before code: no blocking live probe before implementation. Add
  optional `@pytest.mark.slow` live smoke tests later if credentials are present, especially for ordinary-key
  `/generation` behavior and management-key activity/analytics access.
- [x] Update the acceptance table below with final source/test file names once the module layout is chosen.

### Phase 0 Findings (2026-06-17)

- Local provider trace is already metadata-only and joins to local cost/usage evidence by `request_id` and
  `forge_root_run_id`. `provider_generation_id` belongs to `ProviderTraceRecord`; cost records do not carry it.
- The existing op/CLI shape to mirror is `src/forge/core/ops/provider_trace.py` plus `src/forge/cli/provider.py`: frozen
  DTOs, `ExecutionContext`, `ForgeOpError`, `render_*_lines`, and `--period today|week|month|all`.
- Official docs used: [generation metadata](https://openrouter.ai/docs/api/api-reference/generations/get-generation),
  [generation content](https://openrouter.ai/docs/api/api-reference/generations/list-generation-content),
  [activity](https://openrouter.ai/docs/api/api-reference/analytics/get-user-activity),
  [analytics meta](https://openrouter.ai/docs/api/api-reference/beta-analytics/get-analytics-meta),
  [analytics query](https://openrouter.ai/docs/api/api-reference/beta-analytics/query-analytics),
  [current key](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key), and
  [key list](https://openrouter.ai/docs/api/api-reference/api-keys/list).
- Official OpenRouter docs confirm `GET /api/v1/generation` is the request/usage metadata endpoint, takes `id=gen-...`,
  returns fields such as `id`, `external_user`, `cancelled`, tokens, `total_cost`, provider, and `request_id`, and is
  documented as bearer-token auth without a management-key note.
- `GET /api/v1/generation/content` is a separate content-bearing endpoint returning stored prompt/completion fields.
  This card must not call it.
- `GET /api/v1/activity` returns user activity grouped by endpoint for the last 30 completed UTC days, accepts `date`,
  `api_key_hash`, and `user_id` filters, and is management-key required.
- `GET /api/v1/analytics/meta` and `POST /api/v1/analytics/query` are management-key required; analytics queries use
  explicit UTC `time_range.start` / `time_range.end`.
- `GET /api/v1/key` exposes `is_management_key`, and `GET /api/v1/keys` returns API-key hashes for filtering activity
  but is itself management-key required.
- Module layout: start with a single UI-agnostic op/client module, `src/forge/core/ops/openrouter_reconciliation.py`,
  plus `tests/src/core/ops/test_openrouter_reconciliation.py` and `tests/src/cli/test_provider_openrouter.py`. Split a
  dedicated provider client package only if reuse or module size demands it.

## Phase 1 -- Small OpenRouter REST Client

- [ ] Add a narrow metadata-only REST client for: `GET /api/v1/generation?id=<generation_id>`, `GET /api/v1/activity`,
  and `POST /api/v1/analytics/query`.
- [ ] Use `httpx` for the client (already a core dependency and used elsewhere in Forge). Do not use the OpenAI SDK from
  `core/llm/clients/openrouter.py`; `/generation`, `/activity`, and `/analytics/query` are OpenRouter-proprietary REST
  endpoints, not OpenAI-compatible chat/completion calls.
- [ ] Add typed response DTOs that preserve endpoint provenance, HTTP status class, key class, account/context metadata
  when exposed, remote token/cost/provider/status fields, and "not found / not authorized / unavailable" outcomes.
- [ ] Add timeout handling and typed errors that never include API key values or raw response bodies containing
  potential prompt/completion content.
- [ ] Ensure generation lookup requests do not opt into content-bearing fields. If the API returns content by default,
  strip it before any DTO/log/JSON output and add a no-content regression test.
- [ ] Unit tests: success, 404/missing remote, 401/403 key mismatch, network/timeout, malformed response, no content
  persistence, and no secret leakage in exception strings.
- [ ] Regression tests: add `tests/regression/test_bug_openrouter_remote_secret_redaction.py` for key-free
  errors/JSON/log strings and `tests/regression/test_bug_openrouter_remote_metadata_only.py` for prompt/completion/body
  stripping.

## Phase 2 -- Credential Handling

- [ ] Extend `src/forge/core/auth/capabilities.py` with the selected management credential, if needed.
- [ ] Resolve keys with `resolve_env_or_credential_with_source()` so the op can report key provenance class
  (`env`/`credential_file`/`none`) without re-deriving it.
- [ ] Keep normal OpenRouter API-key behavior separate from management-key behavior in code and user messages.
- [ ] Build missing-key/actionable messages with `format_missing_credential_error()` so signup URL, exact
  `forge auth login -c <name>`, and `not_needed_for` wording stay consistent with the rest of Forge.
- [ ] Add tests in `tests/src/core/auth/test_capabilities.py` and op/CLI tests covering env, credential-file,
  ignored-env, and missing-key cases.

## Phase 3 -- Command-Core Reconciliation Ops

- [ ] Add a UI-agnostic op module, likely `src/forge/core/ops/openrouter_reconciliation.py`, returning frozen DTOs and
  raising `ForgeOpError` on user-actionable failures.
- [ ] Mirror `src/forge/core/ops/provider_trace.py`: frozen DTOs, `ExecutionContext`, `ForgeOpError`, and shared
  `render_*_lines` plain-text helpers so terminal rendering and any future `%` surface cannot drift.
- [ ] Implement generation lookup by local `request_id` and by raw `generation_id`.
- [ ] Keep join-key roles precise: local cross-plane joins use `request_id` and/or `forge_root_run_id`
  (`ProviderTraceRecord` \<-> cost log \<-> usage ledger); local-to-remote lookup uses `provider_generation_id` as the
  OpenRouter `/generation` id. Use `core/ops/provider_trace.py::_lookup_cost_confidence` as the bounded `request_id`
  cost-plane join template.
- [ ] Implement `generation` as the single-id path: local `request_id` -> trace -> `provider_generation_id` -> remote
  generation lookup, or raw `generation_id` -> remote lookup with no local side.
- [ ] Implement `reconcile` as the windowed two-sided join path: scan local traces and management-key-gated remote
  activity over the selected window, then bucket every local and remote row into the taxonomy below. This is distinct
  from single-id generation lookup and depends on management access.
- [ ] Implement the reconciliation taxonomy exactly: `local`, `remote`, `joined`, `missing-local`, `missing-remote`, and
  `not-queryable`.
- [ ] Map taxonomy to endpoint/key tier explicitly: `joined`, `missing-remote`, and `not-queryable` can come from local
  trace + generation lookup; `missing-local` requires remote activity/analytics scans and therefore management-key
  access; `remote` may be generation or activity/analytics depending on command.
- [ ] Preserve local and remote token/cost values separately with provenance labels; never overwrite local proxy cost
  with remote cost.
- [ ] Treat cancelled-stream absences as missing remote evidence, not proof that the request never happened.
- [ ] Add stable JSON DTO shape with no secrets and no content fields.
- [ ] Unit tests in `tests/src/core/ops/test_openrouter_reconciliation.py` for joined, missing-remote, not-queryable,
  differing local/remote cost, management-key-required, and malformed remote payload cases.
- [ ] Regression tests cover the security invariants, not just unit assertions: key-free outputs and metadata-only DTOs.

## Phase 4 -- CLI Surface

- [ ] Extend `src/forge/cli/provider.py` with a remote provider subgroup: `forge provider openrouter generation`,
  `reconcile`, `activity`, and `analytics`.
- [ ] Keep `forge provider trace list|show|explain` local-only and unchanged.
- [ ] Add human renderers that group local, remote, joined, missing-local, missing-remote, and not-queryable records
  clearly.
- [ ] Add `--json` to every remote command from the first implementation; JSON should be optimized for scripts, not just
  a dump of terminal text.
- [ ] Add time-window flags: `--period today|week|month|all` by default, plus `--from`/`--to` UTC bounds for
  activity/analytics when exact ranges are needed. Do not add `--since`/`--date` aliases in the first implementation.
- [ ] Add CLI tests in `tests/src/cli/test_provider_openrouter.py` for happy paths, missing credentials, missing remote,
  no local traces, JSON shape, and no secret leakage.

## Phase 5 -- Activity / Cost View Integration

- [ ] After standalone CLI is green, decide which integrations belong in this card versus a follow-up.
- [ ] If integrating `forge activity`, show remote reconciliation hints without making remote calls during ordinary
  activity rendering.
- [ ] If integrating `forge proxy costs show`, display remote-reconciled values separately from local proxy-reported
  values with provenance.
- [ ] If adding session-closeout hints, keep them cheap and local by default; print a command the user can run for
  remote reconciliation rather than doing remote I/O on exit.
- [ ] Add tests proving integrations do not imply that missing remote evidence means the request never happened.

## Docs And Verification

- [ ] Update `docs/design.md` and `docs/design_appendix.md` for any new remote plane/cache/schema, command-core op, or
  credential ownership decision.
- [ ] Update `docs/cli_reference.md` for the new `forge provider openrouter ...` commands.
- [ ] Update `docs/end-user/proxy.md` or add an OpenRouter provider subsection explaining local vs remote evidence,
  management-key setup, and privacy limits.
- [ ] Add or update live/operator-gated integration notes if remote endpoint behavior is verified against a real
  OpenRouter account.
- [ ] Run focused unit tests for the client/op/CLI/auth slices.
- [ ] Run `make pre-commit` before closeout.
- [ ] If live OpenRouter integration tests are added, gate them on explicit credentials, mark them with
  `@pytest.mark.slow` (no separate paid marker, per `docs/developer/testing-guidelines.md`), and document the command
  used.

## Acceptance Tests

| Test                              | Fixture                                                                         | Assertion                                                                       | Test File                                              |
| --------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Generation lookup joins           | Local trace with mocked `provider_generation_id` and remote generation response | Local request id, remote tokens/cost/provider/status, and provenance all render | `tests/src/core/ops/test_openrouter_reconciliation.py` |
| Missing remote explicit           | Local trace with generation id; remote 404/not found                            | Result is `missing-remote` with key/account/cancelled explanations              | `tests/src/core/ops/test_openrouter_reconciliation.py` |
| Missing management key actionable | Activity/analytics command without management credential                        | Error names required credential and setup command; no traceback or key echo     | `tests/src/cli/test_provider_openrouter.py`            |
| Local evidence preserved          | Local and remote costs/tokens differ                                            | Both values are shown separately with provenance labels                         | `tests/src/core/ops/test_openrouter_reconciliation.py` |
| Not-queryable local trace         | Local trace has no provider generation id                                       | Result is `not-queryable`, not command failure                                  | `tests/src/core/ops/test_openrouter_reconciliation.py` |
| Activity missing-local            | Remote activity row has no local trace in selected window                       | Result is `missing-local` with model/time/session context                       | `tests/src/core/ops/test_openrouter_reconciliation.py` |
| Content not fetched or persisted  | Remote response contains content-like fields                                    | DTO, logs, and JSON omit prompt/completion/content fields                       | `tests/src/core/ops/test_openrouter_reconciliation.py` |
| JSON mode stable                  | CLI `--json` over mixed reconciliation results                                  | Output has local/remote/joined/missing arrays and no secrets                    | `tests/src/cli/test_provider_openrouter.py`            |

## Review And Closeout

- [ ] Run an adversarial/code review pass on the final diff, with special attention to secret leakage, provenance
  labeling, remote/local cost confusion, and content-fetch boundaries.
- [ ] Record completed work in `docs/board/change_log.md`.
- [ ] Promote durable lessons to `docs/board/impl_notes.md` after human review.
- [ ] Verify design docs and end-user docs match shipped behavior.
- [ ] When resumed and shipped, move `docs/board/doing/openrouter_remote_reconciliation` to
  `docs/board/done/openrouter_remote_reconciliation` after merge.
