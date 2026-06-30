# T6a execution checklist: aux-consumer lane placement

**Card**: [`card.md`](card.md). **Epic**: `docs/board/doing/epic_consumer_lanes/`. **Branch**:
`aux_consumer_lane_placement`.

## Current focus

Generalize the supervisor's lane-binding UX (CLI write + dispatch-time freeze) to **memory-writer, shadow-curation,
team-supervisor** so each can be declared on `claude-max` and emit honest `subscription_quota` billing on keyless+direct
runs. No dispatch-runtime change (claude-max shares the `claude_code` runtime). **First action: settle the CLI surface
decision (Phase 0) before writing code.**

## Phases

### Phase 0 -- CLI surface decision (blocking; no code)

- [x] Decide the consumer-keyed lane CLI surface (card "Risks / open decisions"). **Decided (2026-06-30):
  `forge session lane set/show/clear --consumer <id>`** -- consumer lanes are session-owned manifest intent
  (`intent.consumer_lanes`), so the surface sits under `forge session`, mirroring `forge session memory`
  (`main.py:424`). Rejected top-level `forge lane` (falsely global), `forge policy lane` (overfits supervisor),
  per-domain (scatters).
- [ ] Confirm the supervisor's existing `forge policy supervisor set --runtime/--backend` (`cli/policy.py:1103-1257`)
  stays and writes the same `intent` slot via `set_intent_lane` (no second storage path). Assert: one writer
  (`set_intent_lane`), at most two entry points.

### Phase 1 -- Consumer-parameterized CLI (set / show / clear)

- [ ] New command writes `intent.consumer_lanes.<consumer>` for any of the four consumers via the existing
  `set_intent_lane(state, consumer, lane_record_for(consumer, runtime=..., backend=...))`
  (`session/consumer_lanes.py:136`). Assert: `forge session lane set --consumer memory_writer --backend claude-max`
  populates `ConsumerLaneIntent.memory_writer` (`session/models.py:282`).
- [ ] `show` renders each consumer's `intent` (requested) + `confirmed` (frozen) lane, reusing the resolver
  (`resolve_lane`) for the effective lane; mark drift (`intent != confirmed`) explicitly.
- [ ] `clear` removes a consumer's `intent` override (does not touch the immutable `confirmed` -- frozen is frozen).
  Assert: clearing after a freeze leaves `confirmed` intact and surfaces the drift in `show`.
- [ ] Unknown/invalid `--consumer` rejects via the existing `_CONSUMER_LANE_SLOTS` membership
  (`session/consumer_lanes.py:38`); a non-`claude-max` backend on a claude-only consumer rejects through `resolve_lane`
  (`LaneError`), surfaced through `forge.cli.output` helpers (no hand-rolled `Tip:`/error markup).

### Phase 2 -- Generalized freeze at first dispatch (the three points)

- [ ] **memory-writer**: freeze `confirmed.consumer_lanes.memory_writer` write-once at its dispatch via
  `ensure_consumer_lane_binding(state, MEMORY_WRITER_CONSUMER, lane)` (`session/consumer_lanes.py:167`), at the Stop /
  work-queue entry (`cli/memory_writer.py`). Assert: first keyless declared run freezes; `read_bound_backend_id` then
  returns `claude-max`.
- [ ] **shadow-curation**: same freeze for `SHADOW_CURATION_CONSUMER` at the CLI entry (`cli/memory.py`).
- [ ] **team-supervisor**: same freeze for `TEAM_SUPERVISOR_CONSUMER` at the hook handlers
  (`cli/hooks/commands.py:1754,1796` read backend already; add the freeze beside it).
- [ ] Factor the freeze so the supervisor's existing call (`cli/hooks/policy.py:274-297`) and the three share one
  consumer-keyed helper (no four copy-pasted freeze blocks). Assert: one freeze helper, four call sites.
- [ ] Dispatch is unchanged: each consumer still calls `run_claude_session(...)` with no runtime branch. Assert: no
  `resolve_lane`-driven dispatch arm added (that is T6b).

### Phase 3 -- Tests + docs sync

- [ ] Unit acceptance (table below) green for all three consumers.
- [ ] **Integration** (required -- hooks + memory-writer + session lifecycle): run the relevant files, not the full
  suite. At minimum a memory-writer Stop path and a team-supervisor hook path that exercise the freeze + emit. Name them
  in the change-log verification line.
- [ ] Docs sync: `design.md` §3.5 / §3.6.2 (consumer-lane binding now spans four consumers; intent/confirmed semantics
  unchanged), `design_appendix.md` §G (the three aux consumers' claude-max placement; dispatch byte-identical),
  `cli_reference.md` (new lane command), end-user `docs/end-user/policy.md` (declaring an aux consumer on claude-max).
- [ ] `make pre-commit` clean (mdformat, ruff, mypy, pyright).

## Acceptance tests (fixture-grounded)

| Test                                                              | Fixture                                                                | Assertion                                     | Test File                                                            |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------- |
| Declared claude-max + keyless emits subscription mode (each of 3) | `can_use_bare` False; consumer declared `claude-max`                   | `billing_mode == "subscription_quota"`        | per-consumer `test_*_binding_emits_subscription_quota` (extend T0's) |
| Undeclared keyless stays unknown (each of 3)                      | `can_use_bare` False; no declaration                                   | `billing_mode == "unknown"`                   | `tests/src/core/usage/test_billing.py`                               |
| Key present forces api (precedence, each of 3)                    | `can_use_bare` True; claude-max declared                               | `billing_mode == "api"`                       | `tests/src/core/usage/test_billing.py`                               |
| CLI set writes intent slot                                        | `forge session lane set --consumer memory_writer --backend claude-max` | `ConsumerLaneIntent.memory_writer` populated  | `tests/src/cli/test_session_lane.py` (new)                           |
| Freeze is write-once + drift surfaced                             | declare, dispatch (freeze), re-declare different                       | `confirmed` unchanged; `show` flags drift     | `tests/src/session/test_consumer_lanes.py`                           |
| Dispatch byte-identical                                           | declared claude-max run                                                | run still `claude_code`; no codex arm reached | `tests/src/session/test_*` per consumer                              |
| Unknown consumer rejects                                          | `--consumer bogus`                                                     | error via output helper; non-zero exit        | `tests/src/cli/test_session_lane.py`                                 |

## Blockers / deferred

- **Phase 0 decision RESOLVED (2026-06-30)**: CLI surface = `forge session lane` (session-owned intent; mirrors
  `forge session memory`, `main.py:424`).
- T6b (codex-exec dispatch for the three) and T7 (exhaustion fail-open) stay out of scope.
- Value is keyless-persona-scoped by design (keyed runs stay `api`).

## Closeout

- [ ] Phases 1-3 assertions ticked with verification recorded.
- [ ] `change_log.md` entry (Goal / Key changes / Verification incl. named integration tests).
- [ ] Update epic roster (T6a -> done) + link-control item; `git mv doing/ -> done/` after merge.
- [ ] Durable lessons: fold into epic closeout (T1a-T5 pattern) unless a new invariant warrants `impl_notes.md` review.
