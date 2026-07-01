# T6a execution checklist: aux-consumer lane placement

**Card**: [`card.md`](card.md). **Epic**: `docs/board/done/epic_consumer_lanes/`. **Branch**:
`aux_consumer_lane_placement`.

## Current focus

Generalize the supervisor's lane-binding UX (CLI write + dispatch-time freeze) to **memory-writer, shadow-curation,
team-supervisor** so each can be declared on `claude-max` and emit honest `subscription_quota` billing on keyless+direct
runs. No dispatch-runtime change (claude-max shares the `claude_code` runtime). **Phases 0-2 DONE**: Phase 1 CLI
(`cli/session_lane.py` over `set_intent_lane` / `intent_lane` / `clear_intent_lane`, wired as `forge session lane`);
Phase 2 freeze (`persist_lane_freeze` in `cli/consumer_lane_freeze.py`, fired from an `on_dispatch` hook at each
consumer's actual `run_claude_session` call, threading the dispatched lane with the supervisor's under-lock equality
guard -- see "Review hardening" below). Tests: `test_session_lane.py` (10) + `test_consumer_lane_freeze.py` (6) +
`TestIntentLane` (3) + memory-writer CLI wiring (3) + team-hook wiring (6) green; handoff **integration** (10, Docker)
green; ruff/black/mypy/pyright clean. **Billing honesty already lands at Phase 1** (`read_bound_backend_id` is
confirmed-first-else-`intent`); the freeze is immutability/observability parity, not billing-enablement. **Phases 1-3
implemented + verified on-branch; remaining closeout (epic roster T6a -> done, `git mv doing/ -> done/`) is
post-merge.**

## Phases

### Phase 0 -- CLI surface decision (blocking; no code)

- [x] Decide the consumer-keyed lane CLI surface (card "Risks / open decisions"). **Decided (2026-06-30):
  `forge session lane set/show/clear --consumer <id>`** -- consumer lanes are session-owned manifest intent
  (`intent.consumer_lanes`), so the surface sits under `forge session`, mirroring `forge session memory`
  (`main.py:424`). Rejected top-level `forge lane` (falsely global), `forge policy lane` (overfits supervisor),
  per-domain (scatters).
- [x] Confirm the supervisor's existing `forge policy supervisor set --runtime/--backend` (`cli/policy.py:1103-1257`)
  stays and writes the same `intent` slot via `set_intent_lane` (no second storage path). **Verified**:
  `forge session lane` writes via `set_intent_lane`; `supervisor set` untouched -- two entry points, one writer.

### Phase 1 -- Consumer-parameterized CLI (set / show / clear)

- [x] New command writes `intent.consumer_lanes.<consumer>` for any of the four consumers via the existing
  `set_intent_lane(state, consumer, lane_record_for(consumer, runtime=..., backend=...))`
  (`session/consumer_lanes.py:136`). Assert: `forge session lane set --consumer memory_writer --backend claude-max`
  populates `ConsumerLaneIntent.memory_writer` (`session/models.py:282`).
- [x] `show` renders each consumer's `intent` (requested) + `confirmed` (frozen) lane and flags drift
  (`intent != confirmed`); `--json` for scripts. (Effective lane is confirmed-first per `read_bound_lane`, not a
  separate column.)
- [x] `clear` removes a consumer's `intent` override (does not touch the immutable `confirmed` -- frozen is frozen).
  Assert: clearing after a freeze leaves `confirmed` intact and surfaces the drift in `show`.
- [x] Unknown/invalid `--consumer` rejects via the existing `_CONSUMER_LANE_SLOTS` membership
  (`session/consumer_lanes.py:38`); a non-`claude-max` backend on a claude-only consumer rejects through `resolve_lane`
  (`LaneError`), surfaced through `forge.cli.output` helpers (no hand-rolled `Tip:`/error markup).

### Phase 2 -- Generalized freeze at first dispatch (the three points)

The freeze fires from an `on_dispatch` callback at each consumer's actual `run_claude_session` call (the dispatch
point), threading the lane resolved once at the call site (the read `backend_id` comes from) and re-checking
`read_bound_lane(m) == dispatched_lane` under the lock -- the supervisor's pattern (`cli/hooks/policy.py:296`). Shared
wrapper: `persist_lane_freeze(store, consumer, dispatched_lane, *, timeout_s)` (`cli/consumer_lane_freeze.py`).

- [x] **memory-writer**:
  `run_memory_writer(..., on_dispatch=lambda: persist_lane_freeze(store, MEMORY_WRITER_CONSUMER, dispatched_lane))`; the
  runner calls `on_dispatch()` past every skip-return (`session/memory_writer.py`, before `run_claude_session`).
  Verified by `test_memory_writer_cli.py`: freezes on a real dispatch; **no freeze when the writer skips**
  (below-min-turns/no-docs); undeclared -> no freeze.
- [x] **shadow-curation**: same `on_dispatch` into `run_shadow_curation` (`cli/memory.py`). The runner has no skip path,
  so the hook fires on every call; the `backend_id` thread is covered by `tests/src/session/test_shadow_curation.py`.
  (No dedicated `curate` CLI harness exists; the wiring is identical to the two proven sites.)
- [x] **team-supervisor**: a `_freeze` closure (timeout `HOOK_LOCK_TIMEOUT_S`) threaded as `on_dispatch` through
  `handle_teammate_idle` / `handle_task_completed` -> `_run_supervisor`, which calls it past the depth + proxy guards
  (`policy/team/handlers.py`). Verified by `test_team_hook_lane_freeze.py` (both hooks x dispatch / skip / undeclared,
  6): a cache/tagger/resume/depth skip never freezes.
- [x] **Factoring.** Shared *primitive* `ensure_consumer_lane_binding` (supervisor + the new helper). The three new
  sites share `persist_lane_freeze` (the guarded best-effort `store.update`); the supervisor keeps its own inline freeze
  folded into the policy-persist write (no second lock). The old fresh-read `freeze_bound_lane` was **removed** -- the
  threaded lane replaces it (see Review hardening, Finding 2).
- [x] Dispatch is unchanged: each consumer still calls `run_claude_session(...)` with no runtime branch; no
  `resolve_lane`-driven dispatch arm added (that is T6b). The freeze is an additive `confirmed` write only.

### Review hardening (2026-06-30)

A code review surfaced three issues with the first freeze cut (freeze at the call site, fresh under-lock read). All
verified against the code and fixed:

- [x] **Finding 1 (premature freeze).** The call-site freeze fired before confirming a real dispatch
  (`run_memory_writer` skips at below-min-turns/no-docs/no-ready-specs; team handler skips at cache/tagger/resume +
  `_run_supervisor` depth guard). **Fix**: freeze from an `on_dispatch` hook at the actual `run_claude_session` call, so
  a skipped/throttled run never freezes. (Verified valid; the supervisor itself freezes eagerly in cascade, but the
  intermittent consumers warranted the stricter behavior -- decided "freeze only on real dispatch".)
- [x] **Finding 2 (billing/freeze divergence).** The helper re-read `read_bound_lane(m)` under the lock instead of the
  lane `backend_id` came from, so a concurrent `lane set/clear` could record a different lane than the run billed.
  **Fix**: thread the dispatched lane + equality guard `read_bound_lane(m) == dispatched_lane` (supervisor parity); drop
  the stale write otherwise. (Retracts the earlier "freezing before dispatch collapses the race window" claim -- it did
  not; the window was between the `backend_id` read and the under-lock re-read.)
- [x] **Finding 3 (hook timeout).** The team-hook freeze used the helper's `5.0s` default vs the established
  `HOOK_LOCK_TIMEOUT_S = 0.2`. **Fix**: hooks pass `HOOK_LOCK_TIMEOUT_S`; the background memory-writer/shadow CLI keep
  `5.0`.

### Phase 3 -- Tests + docs sync

- [x] Unit acceptance (table below) green. **Billing rows: covered by existing tests, no new per-consumer billing tests
  added** -- `resolve_billing_mode(direct, has_api_key, backend_id)` is consumer-agnostic (T0's `test_billing.py` covers
  every `(backend, key)` case), and the consumer->`backend_id` map is proven for all four by
  `test_read_bound_backend_id_for_all_consumers`. A per-consumer `subscription_quota` test would re-invoke the same pure
  function under a new name. Freeze/CLI rows: covered by the new freeze tests.
- [x] **Integration** (hooks + memory-writer):
  `./scripts/test-integration.sh tests/integration/cli/test_handoff_integration.py` -> **10 passed** (Docker, local
  LiteLLM). The freeze is a no-op with no lane declared, so this confirms the memory-writer dispatch path is unbroken.
  Team-hook + freeze+emit-with-a- declared-lane is the real-Claude/`slow` tier (release validation,
  `test_supervisor_e2e.py`); the hook freeze wiring is unit-covered (`test_team_hook_lane_freeze.py`), so the routine
  run is the memory-writer path.
- [x] Docs sync: `design.md` §3.5 (intent setter spans 4 consumers + `forge session lane`; freeze point varies by
  consumer) / §3.6.2 (the general lane CLI), `design_appendix.md` §G (new "Aux consumers on claude-max (T6a)" para --
  billing-only, dispatch byte-identical), `cli_reference.md` (new "Session lane" subsection), end-user
  `docs/end-user/policy.md` (aux-consumer claude-max via `forge session lane`).
- [x] Pre-commit clean on the full changed set (isort, ruff, black, mypy, pyright, mdformat) -- 2026-06-30.

## Acceptance tests (fixture-grounded)

| Test                                          | Fixture                                               | Assertion                                         | Test File                                                                                 |
| --------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Consumer -> backend_id (all 4)                | declared `claude-max` via `intent` only               | `read_bound_backend_id == "claude-max"`           | `test_consumer_lanes.py::test_read_bound_backend_id_for_all_consumers`                    |
| Declared claude-max + keyless -> subscription | `direct`, no key, `backend_id="claude-max"`           | `billing_mode == "subscription_quota"`            | `test_billing.py::test_keyless_direct_on_subscription_backend_is_subscription_quota` (T0) |
| Undeclared keyless stays unknown              | `direct`, no key, `backend_id=None`                   | `billing_mode == "unknown"`                       | `test_billing.py::test_undeclared_keyless_is_unknown` (T0)                                |
| Key present forces api (precedence)           | `direct`, key, `backend_id="claude-max"`              | `billing_mode == "api"`                           | `test_billing.py::test_key_and_subscription_backend_coexist_is_api` (T0)                  |
| CLI set writes intent slot                    | `forge session lane set --consumer memory_writer ...` | `ConsumerLaneIntent.memory_writer` populated      | `test_session_lane.py`                                                                    |
| Freeze only on real dispatch (CLI + hook)     | declared; on_dispatch fires vs a skip path            | dispatch -> `confirmed` frozen; skip -> no freeze | `test_memory_writer_cli.py`, `test_team_hook_lane_freeze.py`                              |
| Equality guard drops a stale lane             | dispatched lane != current bound (concurrent re-pin)  | no freeze recorded                                | `test_consumer_lane_freeze.py::test_equality_guard_drops_a_stale_lane`                    |
| Freeze is write-once + drift via show         | re-dispatch same lane; re-declare different in show   | `confirmed` unchanged; `show` flags drift         | `test_consumer_lane_freeze.py`, `test_session_lane.py`                                    |
| Persist is best-effort + hook timeout         | `store.update` raises; `timeout_s` forwarded          | no exception; `confirmed` unwritten; timeout set  | `test_consumer_lane_freeze.py`                                                            |
| Dispatch byte-identical                       | declared claude-max handoff run (Docker)              | run still `claude_code`; no codex arm; 10 passed  | `tests/integration/cli/test_handoff_integration.py`                                       |
| Unknown consumer rejects                      | `--consumer bogus`                                    | error via output helper; non-zero exit            | `test_session_lane.py`                                                                    |

## Blockers / deferred

- **Phase 0 decision RESOLVED (2026-06-30)**: CLI surface = `forge session lane` (session-owned intent; mirrors
  `forge session memory`, `main.py:424`).
- T6b (codex-exec dispatch for the three) and T7 (exhaustion fail-open) stay out of scope.
- Value is keyless-persona-scoped by design (keyed runs stay `api`).

## Closeout

- [x] Phases 1-3 assertions ticked with verification recorded.
- [x] `change_log.md` entry (Goal / Key changes / Verification incl. named integration test).
- [ ] Update epic roster (T6a -> done) + link-control item; `git mv doing/ -> done/` after merge.
- [ ] Durable lessons: fold into epic closeout (T1a-T5 pattern) unless a new invariant warrants `impl_notes.md` review.
