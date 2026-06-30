# T6a execution checklist: aux-consumer lane placement

**Card**: [`card.md`](card.md). **Epic**: `docs/board/doing/epic_consumer_lanes/`. **Branch**:
`aux_consumer_lane_placement`.

## Current focus

Generalize the supervisor's lane-binding UX (CLI write + dispatch-time freeze) to **memory-writer, shadow-curation,
team-supervisor** so each can be declared on `claude-max` and emit honest `subscription_quota` billing on keyless+direct
runs. No dispatch-runtime change (claude-max shares the `claude_code` runtime). **Phases 0-2 DONE**: Phase 1 CLI
(`cli/session_lane.py` over `set_intent_lane` / `intent_lane` / `clear_intent_lane`, wired as `forge session lane`);
Phase 2 freeze (pure `freeze_bound_lane` in `consumer_lanes.py` + best-effort `persist_lane_freeze` in
`cli/consumer_lane_freeze.py`, called before dispatch at memory-writer / shadow-curation / both team hooks). Tests:
`test_session_lane.py` (10) + `test_consumer_lane_freeze.py` (4) + `TestFreezeBoundLane` (4) + memory-writer CLI wiring
(2) + team-hook wiring (4) green; handoff **integration** (10, Docker) green; ruff/black/mypy/pyright clean. **Billing
honesty already lands at Phase 1** (`read_bound_backend_id` is confirmed-first-else-`intent`); the freeze is
immutability/observability parity, not billing-enablement. **Phases 1-3 implemented + verified on-branch; remaining
closeout (epic roster T6a -> done, `git mv doing/ -> done/`) is post-merge.**

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

- [x] **memory-writer**: freeze write-once *before* dispatch via
  `persist_lane_freeze(store, manifest, MEMORY_WRITER_CONSUMER)` at `cli/memory_writer.py` (right after the
  `read_bound_backend_id` read). Verified: `test_run_cmd_freezes_declared_lane` -- declared claude-max freezes into
  `confirmed` and `backend_id=="claude-max"` reaches `run_memory_writer`; `test_run_cmd_undeclared_lane_does_not_freeze`
  -- no decl -> no freeze, `backend_id None`.
- [x] **shadow-curation**: same `persist_lane_freeze(resolved.store, state, SHADOW_CURATION_CONSUMER)` at
  `cli/memory.py` (before `run_shadow_curation`). Shares the unit-tested helper; the shadow runner's `backend_id` thread
  is covered by `tests/src/session/test_shadow_curation.py`. (No dedicated `curate` CLI harness exists; building one to
  cover 3 lines identical to the two proven sites is disproportionate -- noted, not deferred debt.)
- [x] **team-supervisor**: `persist_lane_freeze(store, manifest, TEAM_SUPERVISOR_CONSUMER)` at **both** hooks
  (`cli/hooks/commands.py` teammate-idle + task-completed), after the `config.enabled` guard, before
  `_run_team_handler`. Verified: `tests/src/cli/hooks/test_team_hook_lane_freeze.py` parametrizes both hooks x
  declared/undeclared (4).
- [x] **Factoring (corrected from the original "one helper, four call sites").** The shared *primitive* is
  `ensure_consumer_lane_binding` (used by both the supervisor freeze and the new `freeze_bound_lane`). The three new
  sites share `freeze_bound_lane` (pure mutate) + `persist_lane_freeze` (best-effort `store.update` wrapper, freezes
  *before* dispatch). The **supervisor keeps its own guarded inline freeze** (`cli/hooks/policy.py:274-297`): its
  `read_bound_lane(m) == supervisor_lane` re-check is **load-bearing** race protection for its multi-second *unlocked*
  call and cannot collapse into the shared wrapper. So: one shared primitive, one new mutate, one new persist wrapper, 4
  new call sites; the supervisor is deliberately not refactored onto the wrapper.
- [x] Dispatch is unchanged: each consumer still calls `run_claude_session(...)` with no runtime branch; no
  `resolve_lane`-driven dispatch arm added (that is T6b). The freeze is an additive `confirmed` write only.

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

| Test                                          | Fixture                                               | Assertion                                        | Test File                                                                                 |
| --------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------- |
| Consumer -> backend_id (all 4)                | declared `claude-max` via `intent` only               | `read_bound_backend_id == "claude-max"`          | `test_consumer_lanes.py::test_read_bound_backend_id_for_all_consumers`                    |
| Declared claude-max + keyless -> subscription | `direct`, no key, `backend_id="claude-max"`           | `billing_mode == "subscription_quota"`           | `test_billing.py::test_keyless_direct_on_subscription_backend_is_subscription_quota` (T0) |
| Undeclared keyless stays unknown              | `direct`, no key, `backend_id=None`                   | `billing_mode == "unknown"`                      | `test_billing.py::test_undeclared_keyless_is_unknown` (T0)                                |
| Key present forces api (precedence)           | `direct`, key, `backend_id="claude-max"`              | `billing_mode == "api"`                          | `test_billing.py::test_key_and_subscription_backend_coexist_is_api` (T0)                  |
| CLI set writes intent slot                    | `forge session lane set --consumer memory_writer ...` | `ConsumerLaneIntent.memory_writer` populated     | `test_session_lane.py`                                                                    |
| Freeze write-once + drift surfaced            | declare, freeze, re-declare different                 | `confirmed` unchanged; `show` flags drift        | `test_consumer_lanes.py::TestFreezeBoundLane`, `test_session_lane.py`                     |
| Freeze persists at dispatch (CLI + hook)      | declared claude-max; mocked dispatch                  | `confirmed` frozen; `backend_id` reaches runner  | `test_memory_writer_cli.py`, `test_team_hook_lane_freeze.py`                              |
| Persist is best-effort                        | declared; `store.update` raises                       | no exception; `confirmed` unwritten; lock-skip   | `test_consumer_lane_freeze.py`                                                            |
| Dispatch byte-identical                       | declared claude-max handoff run (Docker)              | run still `claude_code`; no codex arm; 10 passed | `tests/integration/cli/test_handoff_integration.py`                                       |
| Unknown consumer rejects                      | `--consumer bogus`                                    | error via output helper; non-zero exit           | `test_session_lane.py`                                                                    |

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
