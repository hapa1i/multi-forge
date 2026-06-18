# Upstream / Downstream Ledgers -- Execution Checklist

Branch: `upstream_downstream_ledgers`. Card: [card.md](card.md). Epic:
[`epic_telemetry_architecture`](../epic_telemetry_architecture/card.md).

## Current Focus

Move Forge telemetry from four feature-shaped planes toward two direction-shaped planes:

- **Downstream**: one model call; session-blind; request/run/root ids; metrics, cost provenance, optional redacted wire
  evidence, provider lifecycle/correlation.
- **Upstream**: one operation; session-tagged; run/root ids; outcome, reason, latency, and fail-open classification.

Start by mapping current writers/readers and locking the schema/scope decisions. Do not resume
`openrouter_remote_reconciliation` and do not implement the full `unified_backend` model-source catalog on this branch.
Default to keying downstream on today's `proxy_id`/provider identity first unless Phase 0 overturns that, with a clear
migration seam for later `backend_id`.

Locked implementation decisions (2026-06-18):

- Upstream volume defaults to `non_success`: the upstream ledger is a failure/exception log unless
  `upstream_event_volume=all` is set.
- Downstream is a research-preview clean cut to `~/.forge/telemetry/downstream/`; legacy `costs/requests` are used only
  for cap bootstrap migration and reset compatibility.
- Spend caps reconcile in-memory/request-log totals with `~/.forge/telemetry/caps/<proxy_id>.json` at restart. Live
  downstream write failures warn; they do not block otherwise valid requests. Bad cap snapshots warn and fall back to
  JSONL bootstrap rather than resetting caps to zero. Cap-state writes are coalesced by request count/time and flushed
  on graceful proxy shutdown.
- Interim downstream source key is today's `proxy_id`/provider string; `backend_id` remains owned by `unified_backend`.
- Downstream reads are strict typed reads over `DownstreamRecord`; malformed/newer/unknown-field rows are skipped with
  warnings according to the shared reader.
- `downstream_event_id` is stable per physical attempt when the proxy owns the attempt id. True duplicate writes of the
  same attempt merge; distinct retries/attempts get distinct ids. A bare client `request_id` is correlation, not an
  idempotency key.
- V1 writer census: `costs/requests` moved to downstream attempts, `costs/verbs` durable writes are retired in favor of
  run-tree joins, audit/drift/mutation are downstream sub-stream records, provider-trace fields live on downstream
  attempts, `emit_codex_usage` is a downstream/direct provider attempt, and policy-engine outcomes populate upstream.

## Active Constraints

- Keep run-tree correlation load-bearing. Downstream records stay session-blind; session views join through upstream
  records and `forge_root_run_id`.
- Preserve the proxied-vs-direct measurement rule: direct `claude -p` self-report can be authoritative; proxied
  `claude -p` uses proxy evidence. Do not double-count verb snapshots and exact proxy records.
- Preserve `None`-is-not-`0` for cost. A route that reports no dollars remains unavailable, not free.
- Keep spend-cap accounting out of best-effort telemetry swallowing. In-memory cap accounting and bootstrap
  reconciliation must not absorb dropped downstream writes as authoritative zero spend.
- Preserve audit redaction before persistence. No prompt/completion plaintext may enter the new downstream plane.
- Treat durable schema changes as clean research-preview breaks with docs, reset instructions, and explicit tests.

## Phase 0 -- Source Map And Slice Lock

- [x] Enumerate every current telemetry writer and reader, including cost, usage, audit, provider trace,
  `confirmed.policy.decisions`, status-line health/cost, `forge activity`, and `forge proxy costs`.
- [x] Record the current write unit for each path: model call, `claude -p` run, worker, workflow verb, policy
  evaluation, hook invocation, async marker, or session closeout.
- [x] Identify no-call operations that must gain upstream outcomes: deterministic TDD/coding-standards checks, cached
  supervisor allows, auth/proxy-not-found fail-opens, parse fail-opens, memory/shadow queue decisions, and command-core
  operations that return before model calls.
- [x] Decide v1 upstream event volume: which deterministic passes are recorded, which are sampled/omitted, and which
  fail-open paths are mandatory.
- [x] Decide v1 downstream migration shape: new downstream plane beside old logs, compatibility readers over old logs,
  or a clean cut with reset guidance.
- [x] Decide interim downstream source key before `backend_id`: `proxy_id`, provider string, template, or a typed source
  object that can later accept `backend_id`.
- [x] Lock the single downstream read-strictness contract that replaces today's tolerant cost/audit readers and strict
  provider-trace reader.
- [x] Lock the downstream idempotency contract: minted key, replay semantics, and whether readers dedupe duplicate
  writes.
- [x] Treat the five Phase 0 decisions (volume, migration shape, source key, read-strictness, idempotency) as
  interdependent: the idempotency/replay choice interacts with cap reconciliation (a dropped-then-replayed write), and
  the migration shape interacts with read-strictness (a coexistence window means the merged reader must tolerate both
  old and new shapes). Record cross-decision constraints, not just per-decision answers.
- [x] Update this checklist with the chosen phase boundaries before coding if the discovery changes the implementation
  order.

## Phase 1 -- Schema And IO Primitives

- [x] Add typed upstream outcome records with schema versioning.
- [x] Add owner-only JSONL writes and a no-raise best-effort writer for upstream outcomes.
- [x] Add typed downstream call records that absorb the cost/audit/provider-trace fields needed for v1 while preserving
  redaction, provider lifecycle, measurement provenance, request id, run ids, and nullable cost.
- [x] Implement the Phase 0 downstream read-strictness decision in shared JSONL readers and tests.
- [x] Mint a guaranteed-unique downstream write/event id separate from client-suppliable `request_id`.
- [x] Implement the Phase 0 downstream replay/dedupe decision with write-twice-counts-once coverage when dedupe is
  selected.
- [x] Add shared JSONL reader guards for non-object records, newer schema versions, malformed literals, and unknown
  fields according to the selected read policy.
- [x] Reuse or extend the shared JSONL retention/pruning helper for any new downstream shards; preserve current-month
  downstream shards so retention cannot erase active-month spend before cap bootstrap.
- [x] Keep cap accounting off the best-effort write path; bootstrap reconciliation must not treat missing downstream
  writes as authoritative zero spend.
- [x] Update [design.md](../../../design.md) §3.14 and [design_appendix.md](../../../design_appendix.md) schema notes
  for any durable schema decisions made in this phase, or record the deferral as checklist debt.
- [x] Add fixture-driven tests for permissions, malformed lines, newer schemas, nullable cost, and no plaintext body
  persistence.

## Phase 2 -- Downstream Measurement Resolver

- [ ] Extract a single measurement resolver for proxied/direct/self-reported evidence that preserves today's intentional
  divergence between verb aggregates and per-worker events.
- [x] Consume `ProviderTraceMeta` on direct `core.llm` calls so direct OpenRouter-capable calls no longer build provider
  metadata and drop it before persistence.
- [x] Keep proxied `claude -p` exact-cost attribution joined through run-tree cost evidence, not a single-valued
  `source_refs.cost_request_id`.
- [x] Carry `forge_root_run_id` onto downstream records whenever available and preserve exact-vs-estimated labeling so
  join misses render as unavailable/estimated, not authoritative totals.
- [x] Preserve double-count suppression at the invoker or measurement seam, with
  `tests/regression/test_bug_4g_mixed_stamped_unstamped_undercount.py`,
  `tests/regression/test_bug_usage_workflow_double_count.py`, `tests/regression/test_bug_usage_cost_precedence.py`, and
  `tests/regression/test_bug_usage_worker_cost_precedence.py` still guarding the behavior.
- [x] Update design docs for the measurement resolver seam and direct/proxied attribution rules, or record the deferral
  as checklist debt.
- [x] Add regression coverage for direct self-report winning only when unproxied, proxied self-report ignored for cost,
  per-worker proxied cost not double-counted, and route-without-cost remaining unavailable.

## Phase 3 -- Upstream Outcome Instrumentation

- [ ] Add an operation-boundary helper/context manager that records upstream outcome at the policy evaluation or finer
  operation boundary, not merely the enclosing CLI verb.
- [ ] Cover success, warning/fail-open, deny/block, skipped/cached, timeout, parse error, auth/config error, and
  unexpected exception outcomes.
- [ ] Instrument semantic supervisor checks, including cached allows, auth/proxy fail-open, timeout, parse fail-open,
  and high-confidence deny.
- [ ] Instrument deterministic policy evaluations without flattening one `forge hook policy-check` invocation into one
  outcome; one invocation can emit N outcomes for N evaluations.
- [ ] Instrument memory writer, shadow drain, workflow invocations/workers, transfer curation, and action tagger
  boundaries where they produce user-visible automation outcomes.
- [ ] Ensure upstream writes are session-tagged where a session exists and honest when no session exists.
- [ ] Add tests proving no-call operations now produce upstream outcomes and that outcome status is not conflated with
  subprocess success.

## Phase 4 -- Read Surfaces And Compatibility

- [ ] Rework `forge activity` to read upstream outcomes by session and join downstream cost/tokens by run tree as a
  two-pane outer join, with unmatched rows on both sides visible.
- [x] Overlay upstream policy outcomes into the existing activity policy counters so no-call/fail-open policy outcomes
  are visible when they are not present in `confirmed.policy.decisions`.
- [x] Preserve or deliberately replace the current status-line `SUP!N` behavior using the upstream plane.
- [x] Keep cached/offline status-line reads fail-open and posture-preserving on upstream read failure.
- [x] Preserve `format_forge_cost` / `sum_forge_added_cost` semantics: Forge-added spend only, excluding the main
  interactive harness, with unavailable cost hidden rather than shown as zero.
- [x] Keep `forge proxy costs show` authoritative for proxy/downstream spend and make any legacy cost-log fallback
  visibly labeled.
- [ ] Resolve the `confirmed.policy.decisions` open decision below: keep it only as an audit/debug side-channel or prune
  it from activity aggregation entirely.
- [x] Update [cli_reference.md](../../../cli_reference.md) and relevant end-user cost/activity docs for any shipped CLI
  surface changes, or record the deferral as checklist debt.
- [ ] Add human and `--json` rendering tests for mixed upstream/downstream cases, join misses, exact vs estimated cost,
  fail-open breakdowns, and old-log compatibility.

## Phase 5 -- Migration, Docs, And Closeout

- [x] Update [design.md](../../../design.md) §3.14 and related sections to describe the two-plane model as shipped.
- [x] Update [design_appendix.md](../../../design_appendix.md) with upstream/downstream schemas, retention, read policy,
  and migration/reset guidance.
- [x] Update [cli_reference.md](../../../cli_reference.md) for any changed `forge activity`, `forge proxy costs`, or
  diagnostic command behavior.
- [x] Update relevant end-user docs for cost/activity/proxy telemetry behavior.
- [ ] Verify [design.md](../../../design.md) §3.14, [design_appendix.md](../../../design_appendix.md) §A.12-A.14,
  [cli_reference.md](../../../cli_reference.md), and end-user cost/activity docs match shipped behavior after the open
  Phase 2/3/4 items land.
- [x] Add a compact change-log entry when implementation ships.
- [ ] Promote durable implementation lessons to [impl_notes.md](../../impl_notes.md) after human review.
- [x] Run focused unit/regression tests for usage, proxy telemetry, provider trace, policy, activity, and status-line
  surfaces.
- [x] Run relevant integration tests if proxy runtime, hooks, sessions, memory writer, or Codex/Claude subprocess
  attribution behavior changes.
- [x] Run `make pre-commit` before closeout.
- [ ] After merge, move this card to `docs/board/done/upstream_downstream_ledgers/` and update the epic sequencing.

## Acceptance Tests

| Test                                 | Fixture                                                                                                         | Assertion                                                                                                 | Test File                                                     |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| No-call supervisor outcome           | auth/proxy fail-open with no `claude -p` call at default volume; cached allow under `upstream_event_volume=all` | upstream records the operation outcome with session/run ids                                               | `tests/src/policy/semantic/test_supervisor.py`                |
| Parse fail-open is not success       | supervisor subprocess exits 0 with unparseable output                                                           | upstream records parse/error outcome while downstream call evidence remains separate                      | `tests/src/policy/semantic/test_supervisor.py`                |
| Hook policy evaluations are granular | one `forge hook policy-check` invocation runs TDD, coding-standards, and supervisor                             | upstream records one outcome per evaluation, not one flattened hook outcome                               | `tests/src/cli/hooks/test_policy.py`                          |
| Direct provider metadata persists    | direct `core.llm` response carries `ProviderTraceMeta`                                                          | downstream record includes provider id/lifecycle metadata without proxy involvement                       | `tests/src/core/usage/test_emit.py`                           |
| Downstream write dedupes             | same downstream event is replayed twice                                                                         | readers/counts apply the selected Phase 0 replay contract and do not double-count deduped writes          | `tests/src/core/telemetry/test_downstream.py`                 |
| Cap bootstrap resists dropped writes | downstream write is dropped while in-memory cap accounting records the spend                                    | bootstrap/reconciliation keeps cap total correct instead of accepting the missing JSONL row as zero spend | `tests/src/proxy/test_cost_tracker.py`                        |
| Proxied self-report ignored for cost | proxied `claude -p` envelope reports Anthropic-priced cost and proxy logs actual cost                           | downstream/read surface uses proxy evidence only and avoids double count                                  | `tests/src/core/ops/test_usage_summary.py`                    |
| Nullable cost preserved              | route reports tokens but no dollars                                                                             | downstream cost is null/unavailable and spend surfaces do not render `$0`                                 | `tests/src/proxy/test_cost_logger.py`                         |
| Redacted body only                   | downstream record with optional body capture enabled                                                            | persisted body has structure/redaction only, no prompt/completion/plaintext secret                        | `tests/regression/test_bug_audit_header_redaction_no_leak.py` |
| Activity upstream overlay            | session has upstream-only policy outcomes and duplicate manifest/upstream warning                               | activity policy counters include upstream-only outcomes and do not double-count duplicate warnings        | `tests/src/core/ops/test_usage_summary.py`                    |
| Status-line supervisor health        | newest upstream supervisor outcomes include timeout streak                                                      | `SUP!N` renders the consecutive streak and degrades to posture-only on read failure                       | `tests/src/cli/test_statusline_forge_segments.py`             |

## Open Decisions

- [x] V1 upstream volume: record every deterministic pass, only non-success, or a bounded/sampled subset?
- [x] V1 downstream compatibility: migrate old cost/audit/provider-trace readers, dual-write temporarily, or clean-cut
  with reset instructions?
- [x] Interim downstream source key before `backend_id`.
- [ ] Whether `confirmed.policy.decisions` remains in `forge activity` after upstream outcomes ship.
- [x] Whether provider-trace paths move immediately into downstream layout or stay bridged until `unified_backend`.
- [ ] Whether tool/function calls are downstream records in v1, or remain out of scope unless they carry independent
  cost.
