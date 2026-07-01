# T6a -- Aux-consumer lane placement (claude-max billing for memory-writer / shadow-curation / team-supervisor)

**Epic**: `docs/board/done/epic_consumer_lanes/` (member **T6a**, the first narrow slice of T6 "generalize to other
consumers"). Depends on **T1b** (the supervisor binding pattern to generalize) and **T0** (the `claude-max` source +
billing label + the three consumers' defs/slots/threading).

**Type**: Member card. UX-generalization slice. No new runtime, no dispatch change.

**Status**: Authored 2026-06-29 on branch `aux_consumer_lane_placement`. Scope fixed at **Level 1 (placement UX only)**
in a 2026-06-29 planning review (the Level 2 codex-dispatch slice is split out as **T6b**). **Phase 1 (CLI) + Phase 2
(freeze) implemented 2026-06-30**; Phase 3 (docs sync + integration) in progress. See `checklist.md`.

---

## Problem

T1b froze the **supervisor's** consumer-lane binding (`intent` requested + immutable `confirmed`) and gave it operator
UX (`forge policy supervisor set --runtime/--backend`). T0 then extended the *data* layer to three more consumers --
**memory-writer, shadow-curation, team-supervisor** -- shipping their `Consumer` defs (`memory_writer.py:53`,
`shadow_curation.py:27`, `team/handlers.py:37`), their `intent`+`confirmed` manifest slots
(`session/models.py:282-318`), and `backend_id` billing threading through `emit_usage_for_session_result` (all four call
sites pass `backend_id`).

T0 **deliberately deferred the operator half** for those three ("the other three consumers' operator CLI + binding
freeze is a follow-on -- bindable in tests/programmatically now"). The result is an honesty gap for the "Why now"
persona (Claude Max, no API key): the supervisor bills `subscription_quota`, but their memory-writer / shadow-curation /
team-supervisor aux runs still bill **`unknown`** -- because **no CLI writes their `intent` override**.
`forge policy supervisor set` (`cli/policy.py:1160-1171`) hardcodes `SUPERVISOR_CONSUMER`, so there is no surface to set
`intent.consumer_lanes.{memory_writer,shadow_curation,team_supervisor}`. With neither `intent` nor `confirmed`,
`read_bound_backend_id` returns `None` and the label stays `unknown`.

**The freeze is a second, separable concern -- not the billing blocker.** `read_bound_backend_id` reads
`read_bound_lane`, which is confirmed-first **else `intent`** else None, so once the CLI writes the `intent` override
billing already resolves `claude-max` from `intent` alone -- **no freeze required** (proven by
`test_read_bound_backend_id_for_all_consumers`, which binds via `intent` only). What the three still lack is the
supervisor's **write-once freeze** (`cli/hooks/policy.py:274-297`, also `SUPERVISOR_CONSUMER`-only): without it their
lane stays `intent`-only -- re-declarable mid-session, with no immutable `confirmed` record. T6a adds the freeze for
**parity** (lock the lane for the session + a stable observable binding), not to turn billing on. So billing honesty
lands at **Phase 1** (the CLI); **Phase 2** (the freeze) is immutability/observability hardening.

The capability gap is **UX only**: the resolver, billing, schema, and threading already exist for all four.

## Why this is Level 1 (no dispatch change)

The three consumers' `allowed_lanes` today are **`(Lane(claude_code, claude-max, opus),)`** -- `claude-max` only.
`claude-max` rides the **same `claude_code` runtime** as the default, so placing a consumer on it changes the **billing
label only**, not execution: dispatch stays the byte-identical `run_claude_session(...)` call (`memory_writer.py:527`,
`shadow_curation.py:308`, `team/handlers.py:254`). The label fires only on a **keyless + direct** run (a resolvable key
wins -> `api`, per T0's precedence); declaring `claude-max` never strips a key, so there is no surprise. Real runtime
placement (codex-exec for these three) is **T6b** -- it needs codex added to `allowed_lanes` plus a dispatch arm +
fail-open, and is explicitly out of this card.

## The pattern to generalize (T1b, supervisor)

The storage + freeze core is **already consumer-parameterized**; only the two call sites baked in the supervisor:

- `set_intent_lane(state, consumer, record)` (`session/consumer_lanes.py:136`)
- `ensure_consumer_lane_binding(state, consumer, lane)` -- write-once freeze (`session/consumer_lanes.py:167`)
- `confirmed_lane(state, consumer)` / `read_bound_lane` / `read_bound_backend_id` (`session/consumer_lanes.py:41-78`)
- `lane_record_for(consumer, *, runtime, backend)` / `lane_record_for_runtime(consumer, runtime)`

T6a re-uses all of these unchanged and adds a consumer-parameterized **CLI** and **freeze call site** for the three.

## Scope

**In**:

- A consumer-parameterized lane-binding CLI for all four consumers (set / show / clear), covering memory-writer,
  shadow-curation, team-supervisor (supervisor already has its own entry; the new surface also accepts it).
- A generalized **freeze at first dispatch** for the three, at each one's dispatch/hook point, mirroring the supervisor
  freeze.
- Acceptance tests per consumer: declared `claude-max` + keyless -> `subscription_quota`; undeclared keyless ->
  `unknown`; key present -> `api` (precedence); freeze write-once + drift handling; dispatch byte-identical (still
  `claude_code`).
- Docs sync (design §3.5/§3.6.2, appendix §G, `cli_reference`, end-user `policy.md`).

**Out**:

- Any non-claude dispatch / codex-exec arm for the three (**T6b**).
- Fan-out (`review/engine.py:214` `run_parallel`) and taggers (`core.llm` single-shot) -- different dispatch shapes,
  later slices.
- Subscription-exhaustion fail-open (**T7**).
- Stripping a key to force a subscription label (forbidden -- key always wins; the label is honest about keyless runs
  only).

## Risks / open decisions

- **CLI surface shape -- DECIDED (2026-06-30): `forge session lane set/show/clear --consumer <id>`.** Consumer lanes are
  **session-owned durable intent** (`intent.consumer_lanes`, `session/models.py:282-318`), so the canonical surface
  lives under `forge session` -- mirroring the existing `forge session memory` precedent (`main.py:424`,
  `cli/session_memory.py`) for session-scoped intent. Rejected: top-level `forge lane` (would imply global scope like
  `forge proxy`, whose registry *is* global -- lanes are per-session, frozen-per-session); `forge policy lane` (overfits
  the supervisor -- memory-writer/shadow-curation are not policy); per-domain commands (scatter one concept, duplicate
  flags). The supervisor's existing `forge policy supervisor set --runtime/--backend` stays as a convenience (same
  `intent` slot via the same helper -- no storage drift).
- **Freeze placement is per-consumer and omission-prone.** The three freeze at **three distinct points** --
  memory-writer (Stop/work-queue entry, `cli/memory_writer.py`), shadow-curation (CLI, `cli/memory.py`), team-supervisor
  (hooks, `cli/hooks/commands.py:1754,1796`). Omitting any one silently leaves that consumer at `unknown` (the same "all
  four callers" trap T0 flagged). Acceptance must cover all three.
- **Integration tests required.** This touches hooks + memory-writer + session lifecycle; per `testing_guidelines.md`
  unit tests never exercise these paths. Run the relevant integration files before closeout.
- **Value is persona-scoped.** The honest `subscription_quota` label only appears for keyless+direct aux runs (the Max,
  no-API-key persona). Keyed users are unaffected (`api`, byte-identical). This is intended, not a limitation.

## Acceptance

Fixture-grounded table lives in `checklist.md`. Headline: a keyless aux run for each of the three, declared on
`claude-max`, emits `billing_mode="subscription_quota"`; undeclared stays `unknown`; a resolvable key forces `api`;
dispatch never changes runtime.
