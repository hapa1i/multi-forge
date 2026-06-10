# Supervisor Cascade — Execution Checklist

**Current focus**: Slice 5 (Docker integration run) + Slice 6 closeout.

## Slice 0 — Board card + checklist

- [x] `card.md` + `checklist.md` created under `doing/supervisor_cascade/` (this commit).

## Slice 1 — Engine resolver (`src/forge/policy/engine.py`)

- [x] `register_resolver(policy)` + `_resolver` field on `PolicyEngine`; resolver invoked only when a pass-1 decision is
  `needs_review`, none is `deny`, and a resolver is registered.
- [x] Per-policy evaluation body extracted into `_run_policy()` (applies_to gate, fail-mode handling, state collection)
  — behavior-preserving; existing engine tests pass unmodified.
- [x] `_collected_state` cleared at the top of `evaluate()` (no stale resolver snapshot re-persisted by a
  short-circuiting second evaluation; safe because `build_policy_state_update` merges per-policy-id).
- [x] `review_resolved` accepts the resolver's policy_id (legacy `semantic.supervisor` literal preserved for
  cascade-off).
- [x] `restore_state()` covers the resolver; `registered_policy_ids` property; `_persist_policy_state`
  (`cli/hooks/policy.py`) uses it for `rules_active`.
- [x] Tests: 13 new cases in `tests/src/policy/test_engine.py` (resolver resolves allow/warn/deny; deny skips resolver;
  no needs_review skips resolver; no resolver -> unresolved block; resolver needs_review -> unresolved; applies_to False
  -> unresolved; raises under fail open/closed; state collected + restored; two-eval staleness; registered_policy_ids).
  18 existing cases pass unmodified.

## Slice 2 — PlanCheckPolicy (`src/forge/policy/semantic/plan_check.py`, new)

- [x] `run_plan_check()` (tagger pattern: `get_client` + `SyncAdapter.complete`, X-Request-ID forwarding,
  `emit_direct_llm_usage(command="plan-check", session=...)`, returns None on any error).
- [x] `PlanCheckPolicy` (`semantic.plan_check`, StatefulDeterministicPolicy with its own ThrottleCache, plan-fingerprint
  cache key, clean-allow-only caching).
- [x] Violations-only contract: no tier-1 decision ever sets `warnings`; reasons ride in low-severity violations
  (`.uncertain` / `.error` / `.no_plan`), clamped to `_MAX_REASON_CHARS = 500`.
- [x] All failure paths (no plan, parse failure, LLM error, unexpected exception) -> `needs_review`, never raise.
- [x] Helper promotion: `supervisor.py` `_load_plan_override` -> `load_plan_override`, `_plan_fingerprint` ->
  `plan_fingerprint` (call sites + test imports updated).
- [x] Tests: 41 cases in `tests/src/policy/semantic/test_plan_check.py` (applies_to gating; verdict mapping; no-warnings
  invariant; plan unset/missing/empty; cache incl. plan-mtime invalidation, TTL, state round-trip; session-tagged usage
  emission; request-id forwarding; truncation).

## Slice 3 — Config + CLI + direct command

- [x] `SupervisorConfig.cascade` (False) + `checker_model` (None); old manifests load with defaults
  (`tests/src/session/test_store.py::TestSupervisorConfigCompat`).
- [x] `forge policy supervise`: `--cascade/--no-cascade` + `--checker-model`; modifiers when target present, standalone
  toggle action when absent; `--no-cascade <target>` and bare `--checker-model` rejected; `--checker-model` requires a
  prefixed model id.
- [x] Plan auto-resolve at wiring time via `_resolve_cascade_plan` -> `resolve_supervisor_reload_plan_path`;
  unresolvable -> `print_error_with_tip` + exit 1 before any manifest mutation.
- [x] Show-config + `forge policy status` (table + `--json`) display cascade + checker model.
- [x] `%policy supervise cascade on|off` parity; no-args display gains a Cascade line.
- [x] Tests: `TestSuperviseCascade` (14 cases, `tests/src/cli/test_policy_supervisor.py`) + `TestGuardSuperviseCascade`
  (6 cases, `tests/src/cli/test_user_prompt_dispatcher.py`) + store compat round-trip.

## Slice 4 — Hook wiring + measurement

- [x] `cli/hooks/commands.py`: cascade on -> register `PlanCheckPolicy` + supervisor as resolver; off -> exactly today's
  registration (before `restore_state`).
- [x] `PolicyActivity.plan_check_allow`/`plan_check_escalated` (decision-log-derived, cached allows counted) +
  `has_content` + `forge activity` table/`--json` rendering + `render_summary_line` plan-check segment (and the
  supervisor segment is skipped at zero checks, so all-short-circuit sessions don't read "supervisor: 0 checks").
- [x] Tests: `tests/src/cli/hooks/test_policy_check_cascade.py` (6 hook-level wiring cases: short-circuit skips
  supervisor, escalation invokes once, deny blocks, no tier-1 stderr noise on resolved escalation, cascade-off
  identical, decision log records both tiers + rules_active); `TestPlanCheckPlane` + render-line cases in
  `tests/src/core/ops/test_usage_summary.py`; activity render/JSON cases in `tests/src/cli/test_activity.py`.

**Slices 1-4 verification**: 5950 unit+regression tests pass (`-m "not integration"`); `mypy src/forge/` clean.

## Slice 5 — Integration (Docker)

- [ ] Escalation path e2e: unreachable checker endpoint -> tier-1 error -> needs_review -> mock-claude resolves (aligned
  \+ divergent); exactly one mock-claude invocation; `plan-check` ledger event `status="error"` (harness exports
  `FORGE_RUN_ID`/`FORGE_ROOT_RUN_ID` — emit no-ops without ambient run identity).
- [ ] Cascade-off regression: existing supervisor e2e modes unchanged.
- [ ] Wiring e2e: in-container `supervise <target> --cascade` persists `cascade` + `plan_override_path`.
- [x] Short-circuit path e2e: investigated — the docker conftest has no stubbable OpenAI-compatible endpoint reachable
  from the container (no `OPENAI_BASE_URL`/stub-server fixture; only the mock-claude binary pattern). Short-circuit
  coverage stays unit-level (`test_plan_check.py`, `test_policy_check_cascade.py`); recorded as debt below.
- [ ] Run:
  `./scripts/test-integration.sh tests/integration/docker/test_supervisor_e2e.py tests/integration/docker/test_policy_hooks.py -v`

## Slice 6 — Docs + closeout

- [ ] `design.md` §4.1.2 cascade block + §4.1.5 resolver-hop sentence + CLI table row.
- [ ] `design_appendix.md` §D ownership rows; §A.13 per-emitter table `plan-check` row.
- [ ] `docs/end-user/policy.md` cascade subsection.
- [ ] `change_log.md` entry (Goal / Key changes / Verification); durable lessons drafted for impl_notes (human gate);
  card `doing/ -> done/` after merge.

## Acceptance tests (risky/multi-file changes)

| Test                               | Fixture                                               | Assertion                                                            | Test File                                         |
| ---------------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------- |
| Resolver skipped on clean pass     | engine: policies all allow, resolver registered       | resolver.evaluate never called; final allow                          | `tests/src/policy/test_engine.py`                 |
| Escalation resolves                | tier-1 stub emits needs_review; resolver returns deny | final deny with resolver violations                                  | `tests/src/policy/test_engine.py`                 |
| Tier-1 never warns                 | every plan-check failure path                         | `decision.warnings == []` on all tier-1 decisions                    | `tests/src/policy/semantic/test_plan_check.py`    |
| Checker error degrades to frontier | unreachable checker endpoint, mock-claude supervisor  | one supervisor invocation; hook allows/blocks per supervisor verdict | `tests/integration/docker/test_supervisor_e2e.py` |
| Cascade-off is today               | supervisor configured, `cascade=False`                | registration + hook output identical to pre-cascade                  | `tests/integration/docker/test_supervisor_e2e.py` |
| Old manifest loads                 | manifest JSON without `cascade`/`checker_model`       | `SupervisorConfig` loads with defaults                               | `tests/src/session/` round-trip suite             |
| Wiring requires a plan             | no approved snapshot anywhere                         | `supervise t --cascade` exits 1 with tip; manifest untouched         | `tests/src/cli/test_policy_supervisor.py`         |

## Blockers / deferred decisions

- **Debt**: short-circuit-path docker e2e needs a stubbable OpenAI-compatible endpoint for `core.llm` inside the test
  container; none exists (checked Slice 5: docker conftest only stubs the claude binary, no `OPENAI_BASE_URL`/HTTP-stub
  fixture). Unit tests cover the short-circuit verdict mapping and hook wiring; the docker tier covers escalation,
  cascade-off, and CLI wiring. Build the stub fixture if/when a default-on decision needs end-to-end short-circuit
  proof.
- `forge session set policy.supervisor.cascade true` bool coercion verified by code read
  (`session/overrides.py:240-265`: `json.loads` before dacite strict) — e2e helper assumption holds.
