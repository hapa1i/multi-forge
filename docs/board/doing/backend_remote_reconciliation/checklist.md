# Backend Remote Reconciliation -- Execution Checklist

Card: [card.md](card.md). Epic: [`epic_telemetry_architecture`](../epic_telemetry_architecture/card.md).

Branches: PR 1 `backend_remote_reconciliation` (generic refactor + this board move); PR 2 `backend_reconcile_mvp` (MVP
feature, branched from `main` after PR 1 merges).

## Current Focus

PR 1 (generic refactor) is implemented on `backend_remote_reconciliation`; verifying and opening the PR. PR 2 (the
`forge backend reconcile` MVP) follows on a fresh branch after PR 1 merges.

## Resume / Supersession Note (2026-06-19)

- [x] Resumed the paused `openrouter_remote_reconciliation` card generically as `backend_remote_reconciliation`; moved
  `paused/ -> doing/` with `git mv`. OpenRouter is the first adapter, not the feature.
- [x] **Supersede** these Phase 0 decisions (kept below for history; the new shape is authoritative):
  - CLI namespace: `forge backend reconcile <source-id>` (was `forge provider openrouter ...`).
  - Op/module layout: `core/ops/backend_reconcile.py` + `src/forge/backend/remote/{base,openrouter}.py` (was
    `core/ops/openrouter_reconciliation.py`).
  - Remote-reconcile capability = adapter-registry presence, not a `ModelSourceCapabilities` flag.
  - Config-key migration is alias-with-warning (proxy.yaml is user-owned = system boundary), not a silent break.
  - Scope: MVP single-id lookup only; windowed activity/analytics + management key is a deferred follow-on.
- Retained Phase 0 decisions still hold: on-demand only, metadata-only (no content fetch), `gen-...` id vocabulary,
  normal vs management key class, no blocking live probe, stable `--json`.

## PR 1 -- Generic Refactor (no new feature)

- [x] Rename capability `openrouter_user_grouping -> provider_user_grouping` (`backend/sources.py`: field + OpenRouter
  source row). Internal frozen catalog -> clean break.
- [x] Rename config key `provider_trace.inject_openrouter_user -> inject_provider_user` (`config/schema.py`: field,
  `__post_init__`, coercer). Old key honored as a warn-and-degrade alias popped before `_reject_unknown_keys`; new key
  wins if both present.
- [x] Remove the two `provider_name == "openrouter"` fallbacks; provider-trace writes and `user`-field injection are
  purely `backend_id`+capability gated. Rename `_openrouter_user_value -> _provider_user_value`,
  `_inject_openrouter_user_enabled -> _inject_provider_user_enabled`; drop the dead `provider_name` param from
  `record_provider_trace` and all call sites + the passthrough ctx dict.
- [x] Absent-source safety net: one-time INFO in `_backend_source_id()` on the no-`source:` branch, behind a dedicated
  `_warned_absent_backend_source` latch (not the value-keyed unknown-source set).
- [x] Genericize provider-coupled comments/docstrings (`run_id.py`, `reactive/env.py`, `reactive/tagger.py`,
  `ops/provider_trace.py`, `converters.py`, `client_adapter.py`, `provider_trace_logger.py`) and normative docs
  (`design.md` §3.14, `design_appendix.md` §A.14, `cli_reference.md`, `end-user/proxy.md` incl. the alias note).
- [x] Tests updated to the new names + removed fallback; new regression
  `tests/regression/test_bug_provider_trace_inject_alias.py` (old key honored + one warning, new key wins, no
  unknown-key reject). Focused suite: 185 passed.
- [ ] `make pre-commit` clean.
- [ ] Targeted integration `./scripts/test-integration.sh tests/integration/proxy/test_provider_trace_e2e.py -v`
  (live-OpenRouter; template sets `source: openrouter`, must still pass unchanged) before merge.
- [ ] Adversarial review of the diff; change_log entry; open PR 1.

## PR 2 -- MVP Feature: `forge backend reconcile` (single-id)

### Adapter registry + DTOs (`src/forge/backend/remote/base.py`)

- [ ] `RemoteOutcome = Literal["found","not_found","not_authorized","unavailable"]`;
  `KeyClass = Literal["normal","management"]`.
- [ ] `RemoteCapability(single_lookup, window_activity, window_analytics, single_lookup_key, single_lookup_credential_id, window_key, window_credential_id)`
  -- per-path credential ids.
- [ ] `RemoteRecord(remote_id, outcome, endpoint, key_class, http_status, remote_input/output_tokens, remote_cost_micros, remote_provider, cancelled, remote_request_id, detail)`
  -- generic, metadata-only; `detail` never carries a key/body.
- [ ] `BackendRemoteAdapter` protocol (`source_id`, `capabilities()`, `lookup_remote_record(...)`; `fetch_activity(...)`
  declared for the follow-on). Registry `_REMOTE_ADAPTERS`, `get_remote_adapter` (raises `RemoteAdapterNotFoundError`),
  `has_remote_adapter`, `list_remote_adapter_ids`.
- [ ] Error-vs-data: expected remote/network failures return a `RemoteRecord(outcome=...)`, never raise;
  `RemoteAdapterError` only for adapter bugs / config faults.

### OpenRouter adapter (`src/forge/backend/remote/openrouter.py`)

- [ ] Narrow `httpx` client (NOT the OpenAI-SDK chat client). Key via
  `resolve_env_or_credential_with_source("OPENROUTER_API_KEY")` (provenance only); base URL from the source endpoint.
- [ ] `GET /api/v1/generation?id=<remote-id>` with the normal key; whitelist metadata fields only; never call
  `/generation/content`; drop content-like fields at parse; normalize `total_cost` USD -> micros; map `cancelled`.
- [ ] HTTP/network -> outcome as data: 200->found (carry cancelled), 404->not_found, 401/403->not_authorized, all other
  4xx (incl. 429) + 5xx + timeout + connection -> unavailable (carry status + sanitized detail). Missing key ->
  not_authorized via pre-check (no HTTP call).

### Generic op (`src/forge/core/ops/backend_reconcile.py`)

- [ ] `reconcile_generation(*, ctx, source_id, request_id=None, remote_id=None, timeout_s=5.0) -> ReconcileResult` +
  `render_reconcile_lines`. Frozen `ReconcileEntry`/`ReconcileResult`;
  `ReconcileBucket = Literal["local","remote","joined","missing-local","missing-remote","not-queryable"]`.
- [ ] request-id mode scopes `read_downstream_records(backend_id=source_id, request_id=...)`; no local record ->
  `ForgeOpError` naming the source. Bucket logic per the card taxonomy; never overwrite local cost; set
  `needs_credential_id` on `not_authorized`.
- [ ] Export new symbols from `core/ops/__init__.py`; `--json` via `json.dumps(asdict(result), default=str)` -- no
  secrets/content.

### CLI (`src/forge/cli/backend.py`)

- [ ] `forge backend reconcile <source-id>` with `--request-id` / `--remote-id` (mutually exclusive) / `--json` /
  `--timeout`. Neither id -> usage tip + exit 1. Unknown source -> `print_error` + exit 1. `ForgeOpError` ->
  `print_error_with_tip(..., "Run 'forge backend list' ...")` + exit 1.

### PR 2 docs + verification

- [ ] `docs/cli_reference.md` (+ `design.md`/`design_appendix.md` if the op/registry seam is normative);
  `docs/end-user/proxy.md` remote-reconcile subsection.
- [ ] `uv run pytest tests/src/core/ops/test_backend_reconciliation.py tests/src/cli/test_backend_reconcile.py -v`
  (network stubbed); `make pre-commit`. Optional credential-gated `@pytest.mark.slow` live OpenRouter smoke (documented,
  not CI-gated).

## Deferred Follow-on (designed-for, NOT shipped here)

Windowed two-sided reconciliation: OpenRouter `fetch_activity`/analytics; `openrouter-management` credential;
`reconcile_window` + `local`/`missing-local` buckets + `--period/--from/--to`; optional `%backend reconcile`. The
protocol already declares the window methods + per-path credential fields, so no MVP rework.

## Acceptance Tests (MVP)

| Test                    | Fixture                                  | Assertion                                                     | Test File                                           |
| ----------------------- | ---------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------- |
| Generation lookup joins | local trace + mocked remote `found`      | `joined` with remote tokens/cost/provider + local request id  | `tests/src/core/ops/test_backend_reconciliation.py` |
| Cancelled still joins   | remote `found`, `cancelled=True`         | `joined`, `remote_cancelled=True`                             | `tests/src/core/ops/test_backend_reconciliation.py` |
| Missing remote explicit | local id + remote 404                    | `missing-remote`                                              | `tests/src/core/ops/test_backend_reconciliation.py` |
| Not-queryable renders   | local trace, no `provider_generation_id` | `not-queryable` entry renders local evidence, no raise        | `tests/src/core/ops/test_backend_reconciliation.py` |
| Unavailable is data     | remote 429/5xx/timeout                   | `not-queryable`, no raise                                     | `tests/src/core/ops/test_backend_reconciliation.py` |
| Credential actionable   | remote `not_authorized`                  | `needs_credential_id` set; CLI prints setup hint, no key echo | `tests/src/cli/test_backend_reconcile.py`           |
| Raw remote-id found     | `--remote-id`, remote `found`            | `remote`                                                      | `tests/src/core/ops/test_backend_reconciliation.py` |
| Raw remote-id not_found | `--remote-id`, remote 404                | `not-queryable`                                               | `tests/src/core/ops/test_backend_reconciliation.py` |
| Source-scoped           | record under a different `backend_id`    | `--request-id` mode -> `ForgeOpError`                         | `tests/src/core/ops/test_backend_reconciliation.py` |
| Local cost preserved    | differing local/remote cost              | both shown with provenance                                    | `tests/src/core/ops/test_backend_reconciliation.py` |
| Mutually exclusive ids  | `--request-id` + `--remote-id`           | CLI error, exit 1                                             | `tests/src/cli/test_backend_reconcile.py`           |
| JSON stable             | `--json` over mixed results              | `counts`/`entries`, no secrets/content                        | `tests/src/cli/test_backend_reconcile.py`           |

## Closeout

- [ ] Tick final checklist items with verification.
- [ ] change_log entries: PR 1 (refactor, this branch) and PR 2 (MVP) -- newest-first.
- [ ] Promote durable lessons to `impl_notes.md` after human review.
- [ ] Verify design/end-user docs match shipped behavior.
- [ ] Move `doing/backend_remote_reconciliation -> done/backend_remote_reconciliation` after the PR 2 merge.

## Retained Phase 0 Findings (2026-06-17)

- Local provider trace is metadata-only, projects from downstream telemetry, joins by `request_id` + run-tree ids;
  `backend_id` is the source key; `provider_generation_id` belongs to the provider-trace read surface.
- Mirror `core/ops/provider_trace.py` + `cli/provider.py`: frozen DTOs, `ExecutionContext`, `ForgeOpError`,
  `render_*_lines`, `--period`.
- OpenRouter REST facts: `GET /api/v1/generation?id=gen-...` is metadata (bearer auth, no management note), returns
  `id`, `external_user`, `cancelled`, tokens, `total_cost`, provider, `request_id`. `/api/v1/generation/content` is
  content-bearing -- out of scope. `/api/v1/activity` (management-key, last 30 UTC days) and `/api/v1/analytics/query`
  (management-key, explicit UTC range) + `GET /api/v1/key` (`is_management_key`) are follow-on.
